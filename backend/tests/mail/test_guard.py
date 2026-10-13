"""O servidor de e-mail tem que estar na internet, e não do lado de dentro.

O endereço do servidor sai do domínio que a pessoa digita. Sem a checagem,
um domínio apontado para 127.0.0.1 ou para a rede do Docker faria o sistema
bater em portas internas a pedido de um desconhecido.
"""

import socket

import pytest

from app.mail import guard, smtp_send
from app.mail.errors import MailHostError
from app.mail.imap_source import ImapSource
from app.models import Account


def resolves_to(monkeypatch, *addresses):
    monkeypatch.setattr(guard, "_addresses", lambda host, port: list(addresses))


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",  # a própria máquina
        "10.0.0.5",  # rede interna
        "172.18.0.3",  # rede do Docker
        "192.168.1.1",
        "169.254.169.254",  # metadados da nuvem
        "0.0.0.0",
        "224.0.0.1",  # multicast
        "240.0.0.1",  # reservado
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",  # 127.0.0.1 disfarçado de IPv6
    ],
)
def test_internal_addresses_are_refused(monkeypatch, address):
    resolves_to(monkeypatch, address)

    with pytest.raises(MailHostError) as exc:
        guard.ensure_public_host("imap.firma.com.br", 993)

    assert "imap.firma.com.br" in str(exc.value)
    assert address not in str(exc.value), "a mensagem não conta o que existe do lado de dentro"


def test_public_address_passes(monkeypatch):
    resolves_to(monkeypatch, "142.250.0.108", "2607:f8b0:4004:c1b::6c")

    assert guard.ensure_public_host("imap.gmail.com", 993) is None


def test_one_internal_address_among_public_ones_is_enough_to_refuse(monkeypatch):
    """O DNS pode devolver vários endereços, e a conexão pode cair em qualquer um."""
    resolves_to(monkeypatch, "142.250.0.108", "10.0.0.5")

    with pytest.raises(MailHostError):
        guard.ensure_public_host("imap.firma.com.br", 993)


def test_name_that_does_not_resolve_is_a_host_error(monkeypatch):
    def nowhere(host, port):
        raise socket.gaierror("name or service not known")

    monkeypatch.setattr(guard, "_addresses", nowhere)

    with pytest.raises(MailHostError) as exc:
        guard.ensure_public_host("imap.nao-existe.com.br", 993)
    assert "imap.nao-existe.com.br" in str(exc.value)


async def test_imap_does_not_even_connect_to_an_internal_host(monkeypatch):
    resolves_to(monkeypatch, "127.0.0.1")
    built = []

    class MustNotConnect:
        def __init__(self, *args, **kwargs):
            built.append(args)

    monkeypatch.setattr("app.mail.imap_source.imaplib.IMAP4_SSL", MustNotConnect)
    account = Account(provider="imap", email="boss@firma.com.br", secret_ciphertext="x")

    with pytest.raises(MailHostError):
        await ImapSource(account).verify()
    assert built == [], "a conexão nem chegou a ser aberta"


def test_smtp_does_not_even_connect_to_an_internal_host(monkeypatch):
    resolves_to(monkeypatch, "10.0.0.5")
    monkeypatch.setattr("app.mail.smtp_send.decrypt_secret", lambda value: "senha")
    built = []

    def must_not_connect(*args, **kwargs):
        built.append(args)
        raise AssertionError("não devia conectar")

    monkeypatch.setattr("app.mail.smtp_send.smtplib.SMTP_SSL", must_not_connect)
    monkeypatch.setattr("app.mail.smtp_send.smtplib.SMTP", must_not_connect)
    account = Account(provider="imap", email="boss@firma.com.br", secret_ciphertext="x")
    letter = smtp_send.build(account, smtp_send.Outgoing(to="a@b.com.br", subject="Oi", text="t"))

    with pytest.raises(MailHostError):
        smtp_send._send(account, letter)
    assert built == []
