import imaplib
import socket

import pytest

from app.mail.errors import MailAuthError, MailHostError
from app.mail.imap_source import ImapSource
from app.models import Account


def account(email: str = "boss@gmail.com") -> Account:
    return Account(provider="imap", email=email, secret_ciphertext="x")


class FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    def login(self, user, password):
        return "OK", [b"logged in"]

    def select(self, folder, readonly=False):
        return "OK", [b"1"]

    def logout(self):
        return "BYE", [b"bye"]


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    monkeypatch.setattr("app.crypto.decrypt_secret", lambda value: "senha-secreta")
    monkeypatch.setattr("app.mail.imap_source.decrypt_secret", lambda value: "senha-secreta")


def patch_client(monkeypatch, client_class):
    monkeypatch.setattr("app.mail.imap_source.imaplib.IMAP4_SSL", client_class)


async def test_successful_verify_returns_none(monkeypatch):
    patch_client(monkeypatch, FakeClient)
    assert await ImapSource(account()).verify() is None


async def test_bad_password_gives_auth_error_with_help_link(monkeypatch):
    class Rejecting(FakeClient):
        def login(self, user, password):
            raise imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials")

    patch_client(monkeypatch, Rejecting)
    with pytest.raises(MailAuthError) as exc:
        await ImapSource(account()).verify()
    assert "senha de app" in str(exc.value).lower()
    assert exc.value.help_url == "https://myaccount.google.com/apppasswords"
    assert exc.value.hint


async def test_unreachable_host_gives_host_error_naming_the_server(monkeypatch):
    class Unreachable(FakeClient):
        def __init__(self, *args, **kwargs):
            raise socket.gaierror("name or service not known")

    patch_client(monkeypatch, Unreachable)
    with pytest.raises(MailHostError) as exc:
        await ImapSource(account("boss@firma.com.br")).verify()
    assert "imap.firma.com.br" in str(exc.value)


async def test_timeout_gives_host_error(monkeypatch):
    class Slow(FakeClient):
        def __init__(self, *args, **kwargs):
            raise TimeoutError

    patch_client(monkeypatch, Slow)
    with pytest.raises(MailHostError):
        await ImapSource(account()).verify()


async def test_imap_disabled_in_mailbox_settings_is_explained(monkeypatch):
    class ImapOff(FakeClient):
        def select(self, folder, readonly=False):
            raise imaplib.IMAP4.error(b"IMAP is disabled for this account")

    patch_client(monkeypatch, ImapOff)
    with pytest.raises(MailAuthError) as exc:
        await ImapSource(account("boss@yandex.ru")).verify()
    assert "imap" in str(exc.value).lower()


async def test_fetch_reports_the_same_friendly_errors(monkeypatch):
    class Rejecting(FakeClient):
        def login(self, user, password):
            raise imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED]")

    patch_client(monkeypatch, Rejecting)
    with pytest.raises(MailAuthError):
        await ImapSource(account()).fetch_since(None)
