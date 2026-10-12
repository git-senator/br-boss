from app.mail.base import MailSource
from app.mail.imap_source import ImapSource
from app.models import Account

# provider é o transporte, não o serviço de e-mail. Gmail, Outlook, UOL e os
# demais se conectam pelo mesmo IMAP com senha de app; qual é o serviço —
# isso se descobre pelo domínio do endereço em app.mail.providers.
_SOURCES: dict[str, type[MailSource]] = {
    "imap": ImapSource,
}


def get_source(account: Account) -> MailSource:
    source_class = _SOURCES.get(account.provider)
    if source_class is None:
        raise ValueError(f"unknown provider: {account.provider}")
    return source_class(account)
