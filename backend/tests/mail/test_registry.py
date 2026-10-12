import pytest

from app.mail.base import MailSource
from app.mail.imap_source import ImapSource
from app.mail.registry import get_source
from app.models import Account


def make_account(provider: str) -> Account:
    return Account(provider=provider, email="a@b.com", secret_ciphertext="x")


def test_imap_is_the_default_transport():
    source = get_source(make_account("imap"))
    assert isinstance(source, ImapSource)
    assert isinstance(source, MailSource)


def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="unknown provider"):
        get_source(make_account("telegram"))


def test_error_names_the_offending_provider():
    with pytest.raises(ValueError, match="telegram"):
        get_source(make_account("telegram"))
