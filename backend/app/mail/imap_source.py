"""Conexão com o e-mail via IMAP usando senha de app.

Um único transporte para todos os serviços: Google, Microsoft, UOL, Yahoo,
domínio próprio. OAuth não é usado de propósito: para dar acesso ao e-mail,
o Google exige a verificação do aplicativo, e sem ela o acesso cai a cada 7 dias.

Usamos o imaplib padrão, rodando em uma thread. Isso foge do plano, que previa
um cliente assíncrono de terceiros: o imaplib já vem com o Python, se comporta
de forma previsível com todos os provedores e não adiciona uma dependência que
precisaria ser acompanhada. Consultando 25 caixas por minuto, não há diferença
de velocidade.
"""

import asyncio
import email
import imaplib
import re
import ssl
from email.errors import HeaderParseError
from email.header import decode_header
from email.message import Message as EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from html import unescape

from app.crypto import decrypt_secret
from app.mail import guard
from app.mail.base import MailSource, RawAttachment, RawMessage
from app.mail.errors import (
    ATTACHMENT_GONE,
    ATTACHMENT_TOO_BIG,
    BAD_PASSWORD,
    IMAP_DISABLED,
    LETTER_GONE,
    PASSWORD_LOGIN_OFF,
    MailAuthError,
    MailError,
    MailGoneError,
    MailHostError,
    MailTooBigError,
    unreachable,
)
from app.mail.providers import profile_for
from app.models import Account, Attachment

# Sem «<» dentro da tag: senão um texto com mil «<» soltos faria cada um
# deles varrer o e-mail inteiro atrás de um «>» — tempo quadrático.
_TAG = re.compile(r"<[^<>]+>")
_WHITESPACE = re.compile(r"[ \t\r\f\v\xa0]+")

# A formatação do e-mail é removida inteira, junto com o conteúdo: sem isso
# sobram só as tags, e as próprias regras de estilo vão parar no texto.
# Pego em e-mail real: uma mensagem da Meta começava com duas telas de CSS.
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_STYLE = re.compile(r"<style\b[^<>]*>.*?</style>", re.I | re.S)
_SCRIPT = re.compile(r"<script\b[^<>]*>.*?</script>", re.I | re.S)
# Os fechamentos, para _sub_closed achar o último deles.
_COMMENT_END = re.compile(r"-->")
_STYLE_END = re.compile(r"</style>", re.I)
_SCRIPT_END = re.compile(r"</script>", re.I)

# E estes são os mesmos estilos, mas já vazados para o texto: aparece tanto
# «<style>» sem a tag de fechamento quanto estilo direto na parte de texto.
# Reconhecemos pelo conteúdo das chaves: só declarações do tipo
# «propriedade: valor;» e nada mais. Texto comum não tem essa cara,
# e um JSON no e-mail não é afetado — lá há vírgulas e aspas, não
# ponto e vírgula.
#
# Tudo possessivo (*+, ++): o remetente controla o texto, e uma expressão
# que volta atrás à vontade leva minutos num e-mail montado para isso —
# pego na auditoria: um «{a:» seguido de cem mil espaços. Assim cada
# chave é examinada uma vez só, até a próxima chave.
_DECLARATION = r"[-a-zA-Z_*]++\s*+:[^;{}]*+"
_CSS_BLOCK = re.compile(r"\{\s*+(?:" + _DECLARATION + r"(?:;\s*+|(?=\})))++\}")
_EMPTY_BLOCK = re.compile(r"\{\s*+\}")
# O seletor antes do bloco: até tantos caracteres para trás, sem cruzar outra chave ou tag.
_SELECTOR_REACH = 300
_SELECTOR_TOKEN = re.compile(r"^(?:[.#:@\[*(][^\s]*|[>+~)]|[a-z][a-z0-9_-]{0,30})[,){]?$")
_SELECTOR_MARK = re.compile(r"[.#:@\[*>+~]")
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_CSS_COMMENT_END = re.compile(r"\*/")
_DECLARATION_LINE = re.compile(r"^[-a-zA-Z_*]+\s*:[^{}]*;+$")
_PUNCTUATION_ONLY = re.compile(r"^[{};\s]+$")


def _is_selector(line: str) -> bool:
    """A linha parece um seletor de estilo, e não texto do e-mail?

    Duas condições ao mesmo tempo. Primeira: cada palavra parece parte de um
    seletor — «.classe», «#nome», «:root», «@media», um sinal como «>» ou um
    nome de tag. Segunda, a principal: pelo menos uma palavra traz um sinal
    que não aparece em fala humana. Sem a segunda condição, qualquer linha em
    minúsculas — «please confirm your payment» — cairia na definição, e
    cortaríamos texto do e-mail. Cortar texto em nome da limpeza não pode.
    """
    words = line.split()
    if not words or not _SELECTOR_MARK.search(line):
        return False
    return all(_SELECTOR_TOKEN.match(word) for word in words)


def _is_style_noise(line: str) -> bool:
    """Restos de estilo que sobreviveram à remoção dos blocos.

    Chaves soltas, declarações isoladas, seletores sem o próprio bloco.
    Só pegamos linhas sem cirílico (faixa U+0400 a U+04FF): em um e-mail em
    russo isso não acontece, e aqui a cautela vale mais que a cobertura.
    """
    if _PUNCTUATION_ONLY.match(line):
        return True
    if len(line) > 120 or any("\u0400" <= letter <= "\u04ff" for letter in line):
        return False
    return bool(_DECLARATION_LINE.match(line)) or _is_selector(line.rstrip("{").strip())


def _drop_selector(prefix: str) -> str:
    """Cortar do final só as linhas que acabaram sendo um seletor."""
    lines = prefix.split(chr(10))
    while lines and (not lines[-1].strip() or _is_selector(lines[-1])):
        lines.pop()
    return chr(10).join(lines)

_UNKNOWN_CHARSETS = {"unknown-8bit", "x-unknown", "unknown"}

# Quantos e-mails buscamos por rodada. A caixa é conectada com anos de
# histórico; sem um teto, a primeira sincronização puxa dezenas de milhares
# de e-mails para a memória de uma vez, estoura a memória e manda todos
# para a triagem numa só leva. Com o teto, o histórico é processado em
# lotes, rodada após rodada.
BATCH_LIMIT = 200
# E-mails acima disto não são baixados — só o cabeçalho, com um aviso no
# lugar do texto. Duzentos e-mails de 50 MB numa rodada estouram a memória
# do worker; e o que importa num e-mail desses está no anexo, que o
# sistema não mostra mesmo.
MAX_MESSAGE_BYTES = 15 * 1024 * 1024
TOO_BIG_NOTE = (
    "[Este e-mail é grande demais para ser baixado aqui. Abra-o no próprio "
    "serviço de e-mail para ver o conteúdo e os anexos.]"
)
# Anexo maior que isto não é entregue: ele passa inteiro pela memória do
# servidor, e arquivos assim é melhor abrir no próprio e-mail.
MAX_ATTACHMENT_BYTES = 30 * 1024 * 1024
# O e-mail de onde tiramos o anexo é baixado inteiro. O base64 aumenta o
# arquivo em um terço, e ainda há as outras partes — daí a folga acima do
# teto do anexo.
MAX_LETTER_FOR_ATTACHMENT = 45 * 1024 * 1024
# Quanto texto do e-mail passa pela limpeza (_tidy).
TEXT_LIMIT = 200_000
# Como os serviços de e-mail chamam a pasta de spam. O jeito certo é perguntar
# ao servidor pela marca \Junk; a lista serve quando o servidor não manda a marca.
# Nomes com acento vêm em UTF-7 modificado do IMAP («&APQ-» = «ô»).
SPAM_NAMES = (
    "[Gmail]/Spam",
    "[Gmail]/&BCEA;-",
    "Spam",
    "Junk",
    "Junk E-mail",
    "Bulk Mail",
    "INBOX.Spam",
    "INBOX.Junk",
    "Lixo Eletr&APQ-nico",
    "Lixo eletr&APQ-nico",
    "Lixo Eletrônico",
    "Lixo eletrônico",
)

_LIST_NAME = re.compile(rb'"([^"]*)"\s*$')


def find_folder(client: imaplib.IMAP4_SSL, flag: str, names: tuple[str, ...]) -> str | None:
    """Encontrar uma pasta especial — spam, enviados — neste servidor.

    Cada serviço a chama de um jeito e em idiomas diferentes, por isso
    perguntamos ao servidor: na lista de pastas, a certa vem com uma marca
    (Junk, Sent — com barra invertida na frente). Se não houver marca,
    tentamos os nomes conhecidos.
    Não achou — None.
    """
    try:
        status, rows = client.list()
    except imaplib.IMAP4.error:
        return None
    if status != "OK":
        return None

    marker = re.compile((chr(92) * 2 + flag).encode(), re.I)
    for row in rows or []:
        if not isinstance(row, bytes) or not marker.search(row):
            continue
        found = _LIST_NAME.search(row)
        if found:
            return found.group(1).decode("utf-8", errors="replace")

    known = set()
    for row in rows or []:
        if isinstance(row, bytes):
            found = _LIST_NAME.search(row)
            if found:
                known.add(found.group(1).decode("utf-8", errors="replace"))
    for name in names:
        if name in known:
            return name
    return None


def _spam_folder(client: imaplib.IMAP4_SSL) -> str | None:
    """Pasta de spam. Não achou — trabalhamos só com a «Caixa de entrada», sem spam."""
    return find_folder(client, "Junk", SPAM_NAMES)


def _marks(cursor: str | None) -> dict[str, str]:
    """Desmontar o cursor em marcas por pasta.

    Para quem chama, o cursor é opaco, e isso permite guardar nele uma
    marca para cada pasta: os números dos e-mails na «Caixa de entrada»
    e no spam são independentes entre si.

    Um cursor antigo — só um número — é a marca da «Caixa de entrada».
    """
    if not cursor:
        return {}
    if cursor.isdigit():
        return {"inbox": cursor}
    marks = {}
    for piece in cursor.split(","):
        name, _, value = piece.partition("=")
        if value.isdigit():
            marks[name] = value
    return marks


def _pack(marks: dict[str, str]) -> str:
    return ",".join(f"{name}={value}" for name, value in sorted(marks.items()))


def _decode_bytes(data: bytes, charset: str | None) -> str:
    """Decodificar um pedaço do cabeçalho.

    Se a codificação não foi declarada ou é desconhecida — e alguns sistemas
    de e-mail mandam assim, contrariando o padrão — tentamos UTF-8, depois
    latin-1. Resultado vazio é pior que torto, então insistimos até o fim.
    """
    if charset and charset.lower() not in _UNKNOWN_CHARSETS:
        try:
            return data.decode(charset, errors="replace")
        except LookupError:
            pass
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


def _decode_header(value) -> str:
    if not value:
        return ""
    try:
        parts = decode_header(value)
    except (HeaderParseError, UnicodeDecodeError, ValueError):
        return str(value)
    return "".join(
        _decode_bytes(text, charset) if isinstance(text, bytes) else text for text, charset in parts
    )


def _part_text(part: EmailMessage) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _cut_blocks(pattern: "re.Pattern[str]", text: str) -> str:
    """Tirar os blocos de estilo, cada um junto com o seletor que vem antes.

    O seletor é procurado à mão, para trás a partir da chave, e não dentro
    da expressão: na expressão, cada posição do texto tentaria trezentos
    caracteres adiante, e um e-mail grande sem chaves já custaria caro.
    """
    out: list[str] = []
    last = 0
    for match in pattern.finditer(text):
        start = match.start()
        floor = max(last, start - _SELECTOR_REACH)
        begin = start
        while begin > floor and text[begin - 1] not in "{}<>":
            begin -= 1
        out.append(text[last:begin])
        out.append(_drop_selector(text[begin:start]) + chr(10))
        last = match.end()
    out.append(text[last:])
    return "".join(out)


def _drop_styles(text: str) -> str:
    """Jogar fora as regras de estilo que foram parar no texto.

    O aninhamento (@media em volta de regras comuns) é resolvido com
    repetições: primeiro some o interno, depois o invólucro que ficou vazio.
    """
    for _ in range(5):
        cleaned = _cut_blocks(_EMPTY_BLOCK, _cut_blocks(_CSS_BLOCK, text))
        if cleaned == text:
            return text
        text = cleaned
    return text


def _sub_closed(pattern: "re.Pattern[str]", close: "re.Pattern[str]", text: str) -> str:
    """Trocar por espaço os trechos «abre … fecha» — só até o último «fecha».

    Depois do último fechamento nenhuma abertura acha o seu par, e cada uma
    varreria o resto do e-mail à toa: mil «<!--» soltos seriam um milhão de
    passos. Até ali, cada abertura acha o par e o trecho some de uma vez.
    """
    end = 0
    for found in close.finditer(text):
        end = found.end()
    return pattern.sub(" ", text[:end]) + text[end:] if end else text


def _tidy(text: str) -> str:
    """Tirar a diagramação do texto do e-mail.

    Os remetentes montam a parte de texto a partir do mesmo template da versão
    bonita: o resultado são várias telas de tabulações e linhas vazias, no meio
    das quais se perdem as três linhas que importam. Pego em e-mail real — uma
    confirmação de pagamento de 139,99 se esticou por uma tela e meia, e achar
    o valor de olho era impossível.

    Entre parágrafos deixamos uma linha vazia: ela separa as ideias.
    As que vêm em sequência saem — não separam nada.
    """
    tidied: list[str] = []
    # unescape aqui, e não só ao processar a parte HTML: «&#064;» no lugar
    # da arroba aparece também na parte de texto — ela sai do mesmo template.
    text = _sub_closed(_CSS_COMMENT, _CSS_COMMENT_END, unescape(text))
    for raw_line in _drop_styles(text).splitlines():
        line = _WHITESPACE.sub(" ", raw_line).strip()
        # Ponto e vírgula no começo da linha é resto de uma regra cortada.
        # Texto de verdade não começa assim.
        line = line.lstrip(";").strip()
        if line and _is_style_noise(line):
            continue
        if line:
            tidied.append(line)
        elif tidied and tidied[-1]:
            tidied.append("")

    while tidied and not tidied[-1]:
        tidied.pop()
    return "\n".join(tidied)


def _html_to_text(html: str) -> str:
    text = _sub_closed(_COMMENT, _COMMENT_END, html)
    text = _sub_closed(_STYLE, _STYLE_END, text)
    text = _sub_closed(_SCRIPT, _SCRIPT_END, text)
    return _tidy(_TAG.sub(" ", text))


def _is_attachment(part: EmailMessage) -> bool:
    disposition = (part.get("Content-Disposition") or "").lower()
    return "attachment" in disposition or bool(part.get_filename())


def attachment_parts(parsed: EmailMessage) -> list[EmailMessage]:
    """Partes do e-mail que são anexos — sempre na mesma ordem.

    A ordem aqui é um contrato: a posição do anexo nesta lista fica gravada
    no banco (Attachment.part_index), e é por ela que o anexo é procurado
    no e-mail quando alguém pede para baixar. Por isso a lista é montada
    por uma única função, tanto na leitura quanto no download.
    """
    return [
        part
        for part in parsed.walk()
        if part.get_content_maintype() != "multipart" and _is_attachment(part)
    ]


def attachment_name(part: EmailMessage) -> str:
    return _decode_header(part.get_filename()) or "sem-nome"


def attachment_bytes(part: EmailMessage) -> bytes:
    """Conteúdo do anexo, decodificado do base64 e afins."""
    if part.is_multipart():
        # E-mail encaminhado (message/rfc822): dentro não há bytes, há um e-mail.
        inner = part.get_payload()
        if isinstance(inner, list) and inner:
            return inner[0].as_bytes()
        return b""
    return part.get_payload(decode=True) or b""


def pick_attachment(raw: bytes, index: int | None, filename: str, size: int) -> bytes:
    """Achar no e-mail bruto o anexo descrito pela linha do banco. Aqui não há rede.

    Primeiro pela posição — mas só se o nome também bater: depois de uma
    mudança de pasta, o número do e-mail na caixa pode ir parar em outro
    e-mail, e entregar à pessoa o arquivo de outro com um nome conhecido é
    pior do que dizer com franqueza «não encontrado». Sem posição (linha
    mais antiga que a coluna) ou com nome diferente — procuramos pelo nome
    e, entre os de mesmo nome, pelo tamanho.

    Lança MailGoneError se esse anexo não estiver no e-mail.
    """
    parts = attachment_parts(email.message_from_bytes(raw))
    # O nome no banco é cortado no tamanho da coluna — comparamos cortado igual.
    limit = Attachment.__table__.c.filename.type.length
    names = [attachment_name(part)[:limit] for part in parts]

    if index is not None and 0 <= index < len(parts) and names[index] == filename:
        return attachment_bytes(parts[index])

    same_name = [part for part, name in zip(parts, names, strict=True) if name == filename]
    sized = [part for part in same_name if _encoded_size(part) == size]
    if sized:
        return attachment_bytes(sized[0])
    if len(same_name) == 1:
        return attachment_bytes(same_name[0])
    raise MailGoneError(ATTACHMENT_GONE)


def parse_email(raw: bytes, uid: str) -> RawMessage:
    """Desmontar o e-mail bruto. Função pura — aqui não há rede."""
    parsed = email.message_from_bytes(raw)

    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments = [
        RawAttachment(
            filename=attachment_name(part),
            content_type=part.get_content_type(),
            size_bytes=_encoded_size(part),
            fetch=_make_fetch(part),
        )
        for part in attachment_parts(parsed)
    ]

    for part in parsed.walk():
        if part.get_content_maintype() == "multipart" or _is_attachment(part):
            continue
        if part.get_content_type() == "text/plain":
            plain_parts.append(_part_text(part))
        elif part.get_content_type() == "text/html":
            html_parts.append(_part_text(part))

    # O teto vem antes da limpeza: ela passa várias vezes pelo texto, e um
    # e-mail de dezenas de megabytes de texto travaria o worker. Para a
    # triagem e a leitura o começo basta — o banco guarda ainda menos
    # (normalize.BODY_LIMIT).
    body = _tidy("\n".join(plain_parts)[:TEXT_LIMIT])
    if not body and html_parts:
        body = _html_to_text("\n".join(html_parts)[:TEXT_LIMIT])

    sender_name, sender = _first_address(parsed.get("From"))
    recipients = [address for _, address in getaddresses(parsed.get_all("To") or []) if address]
    _, reply_to = _first_address(parsed.get("Reply-To"))

    return RawMessage(
        provider_message_id=uid,
        thread_id=parsed.get("Message-ID"),
        sender=sender,
        sender_name=sender_name,
        recipients=recipients,
        subject=_decode_header(parsed.get("Subject")),
        body_text=body,
        sent_at=_parse_date(parsed.get("Date")),
        attachments=attachments,
        reply_to=reply_to if reply_to and reply_to != sender else None,
    )


def _encoded_size(part: EmailMessage) -> int:
    """Tamanho do anexo sem decodificá-lo.

    Decodificar só para contar bytes é duplicar na memória cada anexo de
    cada e-mail da rodada. Em base64, cada quatro letras são três bytes, e o
    «=» no fim é enchimento, sem bytes por trás. O tamanho precisa ser exato:
    é por ele que anexos de mesmo nome se distinguem no download.
    """
    raw = part.get_payload(decode=False)
    if not isinstance(raw, str):
        return 0
    if (part.get("Content-Transfer-Encoding") or "").strip().lower() == "base64":
        packed = "".join(raw.split())
        padding = len(packed) - len(packed.rstrip("="))
        return max(0, len(packed) * 3 // 4 - padding)
    return len(raw)


def _make_fetch(part: EmailMessage):
    # Decodificado só quando alguém de fato pede o anexo.
    async def fetch() -> bytes:
        return attachment_bytes(part)

    return fetch


def _first_address(value: str | None) -> tuple[str, str]:
    pairs = getaddresses([value or ""])
    if not pairs:
        return "", ""
    name, address = pairs[0]
    return _decode_header(name), address


def _quietly_close(client) -> None:
    """Fechar a conexão sem impedir que o erro de verdade suba."""
    try:
        client.logout()
    except Exception:
        pass


def _parse_date(value: str | None):
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


# Sem contexto explícito, o imaplib usa ssl._create_stdlib_context() — que
# não verifica nem o certificado nem o nome do host. Ou seja, qualquer um que
# se metesse na rede entre o servidor e o e-mail receberia as senhas de todas
# as caixas em texto puro. Aqui vai a verificação estrita normal, como no navegador.
_TLS = ssl.create_default_context()


def password_login_allowed(capabilities) -> bool:
    """Aceita login por senha? Não, se o servidor diz LOGINDISABLED e não oferece AUTH=PLAIN."""
    caps = {str(c.decode() if isinstance(c, bytes) else c).upper() for c in capabilities}
    return "LOGINDISABLED" not in caps or "AUTH=PLAIN" in caps


class ImapSource(MailSource):
    def __init__(self, account: Account) -> None:
        self.account = account
        self.profile = profile_for(account.email)
        self.host = self.profile.imap_host
        self.port = self.profile.imap_port

    def _auth_error(self, message: str) -> MailAuthError:
        return MailAuthError(
            message,
            hint=self.profile.password_hint,
            help_url=self.profile.help_url,
        )

    def _login(self) -> imaplib.IMAP4_SSL:
        # O servidor sai do domínio que a pessoa digitou: nada de endereço interno.
        guard.ensure_public_host(self.host, self.port)
        try:
            client = imaplib.IMAP4_SSL(self.host, self.port, timeout=30, ssl_context=_TLS)
        except OSError as exc:
            # aqui caem tanto «host inexistente» quanto timeout e conexão recusada
            raise MailHostError(unreachable(self.host)) from exc

    # O servidor só aceita login pela conta (OAuth), não por senha:
    # dizer isso em vez de «senha errada», que levaria a pessoa a tentar de novo.
        if not password_login_allowed(getattr(client, "capabilities", ())):
            _quietly_close(client)
            raise self._auth_error(PASSWORD_LOGIN_OFF)

        try:
            client.login(self.account.email, decrypt_secret(self.account.secret_ciphertext))
        except imaplib.IMAP4.error as exc:
            _quietly_close(client)
            raise self._auth_error(BAD_PASSWORD) from exc

        try:
            client.select("INBOX", readonly=True)
        except imaplib.IMAP4.error as exc:
            _quietly_close(client)
            raise self._auth_error(IMAP_DISABLED) from exc

        return client

    async def verify(self) -> None:
        def check() -> None:
            client = self._login()
            client.logout()

        await asyncio.to_thread(check)

    async def fetch_since(self, cursor: str | None) -> tuple[list[RawMessage], str]:
        def pull() -> tuple[list[RawMessage], str]:
            client = self._login()
            try:
                marks = _marks(cursor)
                messages: list[RawMessage] = []

                places = [("inbox", "INBOX")]
                spam = _spam_folder(client)
                if spam:
                    places.append(("spam", spam))

                for folder, mailbox in places:
                    got, mark = self._from_folder(client, mailbox, folder, marks.get(folder))
                    messages.extend(got)
                    if mark:
                        marks[folder] = mark

                return messages, _pack(marks)
            finally:
                client.logout()

        return await asyncio.to_thread(pull)

    async def fetch_attachment(
        self, provider_message_id: str, index: int | None, filename: str, size: int
    ) -> bytes:
        """Baixar um anexo do e-mail direto da caixa.

        O e-mail é buscado de novo inteiro: o IMAP sabe entregar uma parte
        só, mas o servidor numera as partes do jeito dele, e confrontar isso
        com a nossa leitura não é confiável. Pela mesma leitura que montou a
        lista de anexos — é.

        Lança MailError com um texto para a pessoa: MailGoneError — o e-mail
        ou o anexo não existe mais, MailTooBigError — grande demais.
        """
        # Número do e-mail — "7" na Caixa de entrada ou "spam:7" no spam (_from_folder).
        folder, _, uid = provider_message_id.rpartition(":")
        folder = folder or "inbox"
        if not uid.isdigit():
            raise MailGoneError(LETTER_GONE)

        def pull() -> bytes:
            client = self._login()
            try:
                if folder == "inbox":
                    mailbox = "INBOX"
                elif folder == "spam":
                    mailbox = _spam_folder(client)
                else:
                    mailbox = None
                if not mailbox:
                    raise MailGoneError(LETTER_GONE)
                raw = self._fetch_whole(client, mailbox, uid)
            finally:
                _quietly_close(client)
            data = pick_attachment(raw, index, filename, size)
            if len(data) > MAX_ATTACHMENT_BYTES:
                raise MailTooBigError(ATTACHMENT_TOO_BIG)
            return data

        return await asyncio.to_thread(pull)

    def _fetch_whole(self, client: imaplib.IMAP4_SSL, mailbox: str, uid: str) -> bytes:
        """O e-mail inteiro pelo número. Só leitura, sem mexer nas marcas."""
        try:
            status, _ = client.select(_quoted(mailbox), readonly=True)
            if status != "OK":
                raise MailGoneError(LETTER_GONE)
            # O tamanho vem antes do download: um e-mail de cem megabytes não
            # deve parar inteiro na memória só para ser recusado.
            if _sizes(client, [uid.encode()]).get(uid, 0) > MAX_LETTER_FOR_ATTACHMENT:
                raise MailTooBigError(ATTACHMENT_TOO_BIG)
            # PEEK — como na busca: baixar um anexo não marca o e-mail como
            # lido na própria caixa.
            _, payload = client.uid("fetch", uid, "(BODY.PEEK[])")
        except (imaplib.IMAP4.error, OSError) as exc:
            raise MailError(
                "O serviço de e-mail não entregou o e-mail. Tente de novo daqui a um minuto."
            ) from exc
        for item in payload or []:
            if isinstance(item, tuple) and len(item) > 1 and isinstance(item[1], bytes):
                return item[1]
        raise MailGoneError(LETTER_GONE)

    def _from_folder(
        self,
        client: imaplib.IMAP4_SSL,
        mailbox: str,
        folder: str,
        mark: str | None,
    ) -> tuple[list[RawMessage], str | None]:
        """Buscar os e-mails novos de uma pasta.

        A pasta é aberta só para leitura: o sistema não deve mudar nada
        na caixa dos outros — nem marcas, nem a posição dos e-mails.
        """
        try:
            status, _ = client.select(_quoted(mailbox), readonly=True)
        except imaplib.IMAP4.error:
            return [], None
        if status != "OK":
            return [], None

        start = int(mark or 0) + 1
        _, data = client.uid("search", None, f"UID {start}:*")
        uids = [uid for uid in (data[0] or b"").split() if int(uid) >= start]
        uids = uids[:BATCH_LIMIT]
        sizes = _sizes(client, uids)

        messages = []
        for uid in uids:
            number = uid.decode()
            too_big = sizes.get(number, 0) > MAX_MESSAGE_BYTES
            # BODY.PEEK[], e não RFC822. A diferença é uma só: o RFC822 marca
            # o e-mail como lido direto no servidor. Ou seja, nós buscávamos
            # o e-mail — e ele virava lido em silêncio no próprio Gmail, para
            # quem usa pelo celular. O PEEK lê sem mexer na marca: quem decide
            # se o e-mail foi lido é a pessoa, não o sistema.
            wanted = "(BODY.PEEK[HEADER])" if too_big else "(BODY.PEEK[])"
            _, payload = client.uid("fetch", number, wanted)
            if payload and isinstance(payload[0], tuple):
                # O número do e-mail é único dentro da pasta, mas não entre pastas.
                # Sem o prefixo, um e-mail do spam colidiria com um da
                # «Caixa de entrada» de mesmo número.
                letter = parse_email(
                    payload[0][1],
                    uid=number if folder == "inbox" else f"{folder}:{number}",
                )
                if too_big:
                    letter.body_text = TOO_BIG_NOTE
                letter.folder = folder
                messages.append(letter)

        return messages, uids[-1].decode() if uids else mark


_SIZE_UID = re.compile(rb"UID (\d+)")
_SIZE_VALUE = re.compile(rb"RFC822\.SIZE (\d+)")


def _sizes(client: imaplib.IMAP4_SSL, uids: list[bytes]) -> dict[str, int]:
    """Tamanho de cada e-mail do lote, num pedido só, antes de baixar algum.

    RFC822.SIZE só lê o tamanho — não marca nada como lido. Se o servidor
    não respondeu direito, seguimos sem tamanhos: melhor baixar como antes
    do que parar a caixa.
    """
    if not uids:
        return {}
    try:
        _, rows = client.uid("fetch", b",".join(uids).decode(), "(RFC822.SIZE)")
    except imaplib.IMAP4.error:
        return {}
    sizes: dict[str, int] = {}
    for row in rows or []:
        line = row[0] if isinstance(row, tuple) else row
        if not isinstance(line, bytes):
            continue
        uid, size = _SIZE_UID.search(line), _SIZE_VALUE.search(line)
        if uid and size:
            sizes[uid.group(1).decode()] = int(size.group(1))
    return sizes


def _quoted(mailbox: str) -> str:
    """Nome da pasta entre aspas: pode ter espaços e parênteses."""
    return chr(34) + mailbox.replace(chr(34), "") + chr(34)
