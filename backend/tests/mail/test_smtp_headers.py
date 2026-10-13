"""Cabeçalhos da resposta: o assunto e o Message-ID vêm do remetente."""

import pytest

from app.mail import smtp_send
from app.mail.errors import MailError
from app.models import Account


def account(name: str = "") -> Account:
    return Account(
        provider="imap", email="boss@firma.com.br", display_name=name, secret_ciphertext="x"
    )


def test_line_breaks_in_headers_do_not_reach_the_letter():
    """Uma quebra de linha no assunto viraria um cabeçalho a mais (um Bcc,
    por exemplo) — ou derrubaria o envio com erro 500."""
    letter = smtp_send.build(
        account("Ana\r\nBcc: espiao@fora.com"),
        smtp_send.Outgoing(
            to="cliente@empresa.com.br",
            subject="Re: Fatura\r\nBcc: espiao@fora.com",
            text="Olá",
            in_reply_to="<abc@x.com>\n\tBcc: espiao@fora.com",
        ),
    )

    raw = letter.as_string()
    assert "\nBcc:" not in raw
    assert letter["Subject"] == "Re: Fatura Bcc: espiao@fora.com"
    assert letter["In-Reply-To"] == "<abc@x.com> Bcc: espiao@fora.com"
    assert letter["References"] == letter["In-Reply-To"]


def test_header_the_library_refuses_becomes_a_mail_error(monkeypatch):
    """O que a biblioteca de e-mail recusa chega à pessoa como explicação, e não como erro 500."""

    def refuses(*args, **kwargs):
        raise ValueError("cabeçalho inválido")

    monkeypatch.setattr(smtp_send, "formatdate", refuses)

    with pytest.raises(MailError) as exc:
        smtp_send.build(account(), smtp_send.Outgoing(to="a@b.com.br", subject="Oi", text="t"))
    assert "caracteres inválidos" in str(exc.value)
