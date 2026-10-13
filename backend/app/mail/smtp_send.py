"""Envio da resposta: SMTP com a mesma senha de app usada para buscar os e-mails.

Não é preciso um acesso separado para envio: em todos os serviços a senha de app
libera tanto o IMAP quanto o SMTP. Ou seja, não pedimos nada novo ao dono.

A resposta entra na mesma conversa do e-mail original (In-Reply-To
e References) — para o destinatário ela aparece como resposta, e não como e-mail novo.
"""

import asyncio
import imaplib
import mimetypes
import re
import smtplib
import ssl
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from app.crypto import decrypt_secret
from app.mail import guard
from app.mail.errors import MailAuthError, MailError, MailHostError
from app.mail.imap_source import find_folder
from app.mail.providers import profile_for
from app.models import Account

TIMEOUT_SECONDS = 30

# Como na busca dos e-mails: verificação estrita do certificado e do nome do servidor.
_TLS = ssl.create_default_context()

SENT_NAMES = (
    "Sent",
    "Sent Items",
    "Sent Messages",
    "Enviados",
    "Itens Enviados",
    "Enviadas",
    "\u041e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u043d\u044b\u0435",  # pasta de enviados em servidores russos
    "INBOX.Sent",
    "[Gmail]/Sent Mail",
)

AUTH_REFUSED = (
    "O provedor de e-mail não permitiu o envio a partir desta caixa. A senha de app "
    "serve para leitura, mas o envio foi recusado — confira se a senha "
    "não foi revogada e se as configurações da caixa permitem programas de e-mail."
)


# Anexos da resposta. 25 MB é o teto do Gmail e da maioria dos serviços;
# acima disso o serviço não aceita de qualquer jeito, só que a pessoa
# descobriria mais tarde.
MAX_FILES = 10
MAX_FILES_BYTES = 25 * 1024 * 1024
FILENAME_LIMIT = 150

_FILENAME_JUNK = re.compile(r'[\x00-\x1f\x7f<>:"|?*]')


@dataclass(slots=True)
class OutgoingFile:
    filename: str
    data: bytes


@dataclass(slots=True)
class Outgoing:
    to: str
    subject: str
    text: str
    in_reply_to: str | None = None
    files: list[OutgoingFile] = field(default_factory=list)


def clean_filename(name: str | None) -> str:
    """Nome do arquivo anexado, adequado para o e-mail.

    O nome vem do navegador e pode ser qualquer coisa: com caminho
    («C:\\Users\\…\\fatura.pdf» em navegadores antigos), com quebras de
    linha, com caracteres que o e-mail do destinatário no Windows não salva.
    Cortamos o caminho, trocamos o lixo, limitamos o tamanho — a extensão
    é mantida no corte, senão o arquivo não abre para o destinatário.
    """
    base = re.split(r"[\\/]", name or "")[-1]
    base = _FILENAME_JUNK.sub("_", base)
    base = " ".join(base.split()).strip(" .")
    if not base:
        return "arquivo"
    if len(base) > FILENAME_LIMIT:
        stem, dot, ext = base.rpartition(".")
        if dot and stem and len(ext) <= 10:
            base = stem[: FILENAME_LIMIT - len(ext) - 1].rstrip(" .") + "." + ext
        else:
            base = base[:FILENAME_LIMIT]
    return base


def file_type(filename: str) -> tuple[str, str]:
    """Tipo do arquivo pela extensão. O tipo mandado pelo navegador não
    usamos: qualquer um pode forjá-lo, e o destinatário vai decidir com o
    que abrir o arquivo pelo nome de qualquer forma."""
    guessed, encoding = mimetypes.guess_type(filename)
    if not guessed or encoding or "/" not in guessed:
        return "application", "octet-stream"
    maintype, subtype = guessed.split("/", 1)
    # .eml e parecidos: pelas regras, um e-mail dentro de outro não pode
    # ir em base64, e de outro jeito não dá para mandar bytes arbitrários.
    if maintype in ("message", "multipart"):
        return "application", "octet-stream"
    return maintype, subtype


def reply_subject(subject: str) -> str:
    """«Re: assunto», mas sem «Re: Re: Re:» na terceira rodada."""
    clean = (subject or "").strip()
    # "\u043e\u0442\u0432\u0435\u0442:" é o prefixo de resposta russo ("otvet:").
    if clean.lower().startswith(("re:", "\u043e\u0442\u0432\u0435\u0442:", "res:")):
        return clean
    return f"Re: {clean}" if clean else "Re:"


def _one_line(value: str | None) -> str:
    """O valor do cabeçalho numa linha só.

    O assunto e o Message-ID vêm do e-mail recebido — quem escreve é o
    remetente. Uma quebra de linha ali faria o e-mail montado carregar um
    cabeçalho a mais (Bcc, por exemplo) ou simplesmente derrubaria o envio.
    Quebras e espaços em sequência viram um espaço.
    """
    return " ".join((value or "").split())


def build(account: Account, outgoing: Outgoing) -> EmailMessage:
    """Montar o e-mail. Função pura — aqui não há rede.

    Lança MailError se, mesmo limpo, algum cabeçalho não for aceito.
    """
    letter = EmailMessage()
    try:
        letter["From"] = formataddr((_one_line(account.display_name), account.email))
        letter["To"] = _one_line(outgoing.to)
        letter["Subject"] = _one_line(outgoing.subject)
        letter["Date"] = formatdate(localtime=False)
        letter["Message-ID"] = make_msgid(domain=account.email.rsplit("@", 1)[-1])
        thread = _one_line(outgoing.in_reply_to)
        if thread:
            letter["In-Reply-To"] = thread
            letter["References"] = thread
        letter.set_content(outgoing.text)
        # A cópia para «Enviados» é montada a partir deste mesmo e-mail
        # (_keep_copy), então os anexos vão estar lá também.
        for item in outgoing.files:
            maintype, subtype = file_type(item.filename)
            letter.add_attachment(
                item.data,
                maintype=maintype,
                subtype=subtype,
                filename=clean_filename(item.filename),
            )
    except ValueError as exc:
        # A biblioteca de e-mail recusa cabeçalhos tortos com ValueError —
        # sem isto a pessoa veria um erro 500 em vez de uma explicação.
        raise MailError(
            "Não foi possível montar a resposta: o assunto ou o endereço tem caracteres inválidos."
        ) from exc
    return letter


def _send(account: Account, letter: EmailMessage) -> None:
    profile = profile_for(account.email)
    password = decrypt_secret(account.secret_ciphertext)
    # Como na busca: o servidor de envio sai do domínio digitado — nada de endereço interno.
    guard.ensure_public_host(profile.smtp_host, profile.smtp_port)
    try:
        if profile.smtp_port == 465:
            server = smtplib.SMTP_SSL(
                profile.smtp_host, profile.smtp_port, timeout=TIMEOUT_SECONDS, context=_TLS
            )
        else:
            server = smtplib.SMTP(profile.smtp_host, profile.smtp_port, timeout=TIMEOUT_SECONDS)
            server.starttls(context=_TLS)
    except (OSError, smtplib.SMTPException) as exc:
        raise MailHostError(
            f"Não foi possível conectar ao servidor de envio {profile.smtp_host}."
        ) from exc

    try:
        server.login(account.email, password)
        server.send_message(letter)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailAuthError(AUTH_REFUSED, hint=profile.password_hint, help_url=profile.help_url) from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise MailError("O provedor de e-mail não aceitou o endereço do destinatário.") from exc
    except (OSError, smtplib.SMTPException) as exc:
        raise MailError(f"O provedor de e-mail não aceitou a mensagem: {exc}") from exc
    finally:
        try:
            server.quit()
        except (OSError, smtplib.SMTPException):
            pass


def _keep_copy(account: Account, letter: EmailMessage) -> None:
    """Guardar uma cópia em «Enviados» onde o serviço não faz isso sozinho.

    Se não der certo, tudo bem: o e-mail já foi, e é isso que importa. Não
    cancelamos o envio por causa da cópia nem tratamos isso como erro.
    """
    profile = profile_for(account.email)
    if profile.saves_sent:
        return
    try:
        guard.ensure_public_host(profile.imap_host, profile.imap_port)
    except MailError:
        return
    try:
        client = imaplib.IMAP4_SSL(
            profile.imap_host, profile.imap_port, timeout=TIMEOUT_SECONDS, ssl_context=_TLS
        )
    except OSError:
        return
    try:
        client.login(account.email, decrypt_secret(account.secret_ciphertext))
        folder = find_folder(client, "Sent", SENT_NAMES)
        if folder:
            client.append(
                chr(34) + folder + chr(34),
                "(" + chr(92) + "Seen)",
                imaplib.Time2Internaldate(time.time()),
                letter.as_bytes(),
            )
    except imaplib.IMAP4.error:
        pass
    finally:
        try:
            client.logout()
        except Exception:  # noqa: BLE001 — fechamos em silêncio, o e-mail já foi
            pass


async def send(account: Account, outgoing: Outgoing) -> str:
    """Enviar o e-mail. Retorna o Message-ID dele.

    Lança MailError com um texto pronto para mostrar à pessoa.
    """
    letter = build(account, outgoing)

    def work() -> None:
        _send(account, letter)
        _keep_copy(account, letter)

    await asyncio.to_thread(work)
    return str(letter["Message-ID"])
