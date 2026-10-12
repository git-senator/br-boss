"""Envio da resposta: SMTP com a mesma senha de app usada para buscar os e-mails.

Não é preciso um acesso separado para envio: em todos os serviços a senha de app
libera tanto o IMAP quanto o SMTP. Ou seja, não pedimos nada novo ao dono.

A resposta entra na mesma conversa do e-mail original (In-Reply-To
e References) — para o destinatário ela aparece como resposta, e não como e-mail novo.
"""

import asyncio
import imaplib
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from app.crypto import decrypt_secret
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


@dataclass(slots=True)
class Outgoing:
    to: str
    subject: str
    text: str
    in_reply_to: str | None = None


def reply_subject(subject: str) -> str:
    """«Re: assunto», mas sem «Re: Re: Re:» na terceira rodada."""
    clean = (subject or "").strip()
    # "\u043e\u0442\u0432\u0435\u0442:" é o prefixo de resposta russo ("otvet:").
    if clean.lower().startswith(("re:", "\u043e\u0442\u0432\u0435\u0442:", "res:")):
        return clean
    return f"Re: {clean}" if clean else "Re:"


def build(account: Account, outgoing: Outgoing) -> EmailMessage:
    """Montar o e-mail. Função pura — aqui não há rede."""
    letter = EmailMessage()
    letter["From"] = formataddr((account.display_name or "", account.email))
    letter["To"] = outgoing.to
    letter["Subject"] = outgoing.subject
    letter["Date"] = formatdate(localtime=False)
    letter["Message-ID"] = make_msgid(domain=account.email.rsplit("@", 1)[-1])
    if outgoing.in_reply_to:
        letter["In-Reply-To"] = outgoing.in_reply_to
        letter["References"] = outgoing.in_reply_to
    letter.set_content(outgoing.text)
    return letter


def _send(account: Account, letter: EmailMessage) -> None:
    profile = profile_for(account.email)
    password = decrypt_secret(account.secret_ciphertext)
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
