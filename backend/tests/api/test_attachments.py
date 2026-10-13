"""Anexos recebidos: baixados da caixa no clique, não ficam guardados com a gente."""

from email.message import EmailMessage

import pytest
from sqlalchemy import select

from app.api.attachments import disposition, safe_type
from app.crypto import encrypt_secret
from app.mail.base import RawMessage
from app.mail.errors import MailGoneError, MailHostError
from app.mail.imap_source import ImapSource, parse_email, pick_attachment
from app.mail.normalize import store_messages
from app.models import Account, Attachment, Message, User
from app.security import create_token

PDF = b"%PDF-1.4 boleto"
HTML = b"<script>alert(1)</script>"
SVG = b"<svg onload='alert(1)'/>"


def raw_letter() -> bytes:
    """E-mail com três anexos — na ordem em que a leitura vai vê-los."""
    letter = EmailMessage()
    letter["From"] = "ana@fornecedor.com.br"
    letter["To"] = "boss@mail.ru"
    letter["Subject"] = "Boleto"
    letter.set_content("Segue o boleto.")
    letter.add_attachment(HTML, maintype="text", subtype="html", filename="pagina.html")
    letter.add_attachment(PDF, maintype="application", subtype="pdf", filename="Orçamento nº5.pdf")
    letter.add_attachment(SVG, maintype="image", subtype="svg+xml", filename="logo.svg")
    return letter.as_bytes()


class FakeImap:
    """Caixa falsa: e-mails por número, «Caixa de entrada» e spam."""

    def __init__(self, inbox: dict[str, bytes], spam: dict[str, bytes] | None = None) -> None:
        self.inbox = inbox
        self.spam = spam or {}
        self.current = inbox
        self.opened: list[str] = []
        self.fetches: list[tuple[str, str]] = []
        self.logged_out = False

    def list(self):
        return "OK", [rb'(\HasNoChildren) "/" "INBOX"', rb'(\HasNoChildren \Junk) "/" "Spam"']

    def select(self, mailbox, readonly=False):
        assert readonly, "na caixa dos outros, só leitura"
        name = mailbox.strip(chr(34))
        self.opened.append(name)
        self.current = self.spam if name == "Spam" else self.inbox
        return "OK", [b"1"]

    def uid(self, command, *args):
        assert command == "fetch"
        uid, what = args[0], args[-1]
        self.fetches.append((uid, what))
        if uid not in self.current:
            return "OK", [None]
        if what == "(RFC822.SIZE)":
            return "OK", [f"1 (UID {uid} RFC822.SIZE {len(self.current[uid])})".encode()]
        return "OK", [(f"1 (UID {uid} BODY[] {{{len(self.current[uid])}}}".encode(), self.current[uid]), b")"]

    def logout(self):
        self.logged_out = True


@pytest.fixture
def mailbox(monkeypatch):
    fake = FakeImap({"7": raw_letter()}, spam={"9": raw_letter()})
    monkeypatch.setattr(ImapSource, "_login", lambda self: fake)
    return fake


@pytest.fixture
async def letter(session, account):
    """E-mail salvo do mesmo jeito que o worker salva."""
    [stored] = await store_messages(
        session,
        account,
        [parse_email(raw_letter(), uid="7")],
    )
    return stored


async def rows(session, message) -> list[Attachment]:
    return list(
        await session.scalars(
            select(Attachment).where(Attachment.message_id == message.id).order_by(Attachment.id)
        )
    )


def url(message, item) -> str:
    return f"/api/messages/{message.id}/attachments/{item.id}"


async def test_worker_keeps_a_description_of_each_attachment(session, letter):
    stored = await rows(session, letter)
    assert [(a.filename, a.part_index) for a in stored] == [
        ("pagina.html", 0),
        ("Orçamento nº5.pdf", 1),
        ("logo.svg", 2),
    ]
    assert stored[1].content_type == "application/pdf"
    assert all(a.s3_key is None for a in stored), "não guardamos arquivos"


async def test_message_page_lists_attachments(auth_client, session, letter):
    body = (await auth_client.get(f"/api/messages/{letter.id}")).json()
    assert [a["filename"] for a in body["attachments"]] == ["pagina.html", "Orçamento nº5.pdf", "logo.svg"]


async def test_download_gives_the_right_part(auth_client, session, letter, mailbox):
    pdf = (await rows(session, letter))[1]

    response = await auth_client.get(url(letter, pdf))

    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert "filename*=UTF-8''Or%C3%A7amento%20n%C2%BA5.pdf" in response.headers[
        "content-disposition"
    ]
    # O e-mail é buscado com PEEK — baixar não o marca como lido na caixa.
    assert ("7", "(BODY.PEEK[])") in mailbox.fetches
    assert mailbox.logged_out


@pytest.mark.parametrize("index", [0, 2])
async def test_html_and_svg_are_never_served_as_pages(auth_client, session, letter, mailbox, index):
    """Um HTML ou SVG do e-mail aberto no nosso endereço rodaria com as
    permissões do nosso site. Por isso — só «bytes puros»."""
    item = (await rows(session, letter))[index]

    response = await auth_client.get(url(letter, item))

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment;")


async def test_old_rows_without_a_part_number_are_found_by_name(
    auth_client, session, letter, mailbox
):
    pdf = (await rows(session, letter))[1]
    pdf.part_index = None
    await session.flush()

    response = await auth_client.get(url(letter, pdf))

    assert response.status_code == 200
    assert response.content == PDF


async def test_spam_letter_is_taken_from_the_spam_folder(auth_client, session, account, mailbox):
    raw = parse_email(raw_letter(), uid="spam:9")
    raw.folder = "spam"
    [spam] = await store_messages(session, account, [raw])
    pdf = (await rows(session, spam))[1]

    response = await auth_client.get(url(spam, pdf))

    assert response.status_code == 200
    assert response.content == PDF
    assert mailbox.opened[-1] == "Spam"


async def test_letter_removed_from_the_mailbox(auth_client, session, letter, mailbox):
    mailbox.inbox.clear()
    pdf = (await rows(session, letter))[1]

    response = await auth_client.get(url(letter, pdf))

    assert response.status_code == 404
    assert "não está mais" in response.json()["detail"]


async def test_unreachable_mailbox_is_explained(auth_client, session, letter, monkeypatch):
    def down(self):
        raise MailHostError("Não foi possível conectar ao servidor imap.mail.ru.")

    monkeypatch.setattr(ImapSource, "_login", down)
    pdf = (await rows(session, letter))[1]

    response = await auth_client.get(url(letter, pdf))

    assert response.status_code == 502
    assert "Não foi possível conectar" in response.json()["detail"]


async def test_attachment_must_belong_to_that_letter(auth_client, session, account, letter, mailbox):
    other = Message(account_id=account.id, provider_message_id="8", sender="x@y.com")
    session.add(other)
    await session.flush()
    pdf = (await rows(session, letter))[1]

    response = await auth_client.get(f"/api/messages/{other.id}/attachments/{pdf.id}")

    assert response.status_code == 404
    assert mailbox.fetches == [], "nem chegou a ir à caixa"


async def test_someone_elses_attachment_does_not_exist(client, session, letter, mailbox):
    stranger = User(email="stranger@example.com", password_hash="x", role="member")
    session.add(stranger)
    await session.flush()
    session.add(
        Account(user_id=stranger.id, email="s@mail.ru", secret_ciphertext=encrypt_secret("p"))
    )
    await session.flush()
    pdf = (await rows(session, letter))[1]

    response = await client.get(
        url(letter, pdf), headers={"Authorization": f"Bearer {create_token(stranger)}"}
    )

    assert response.status_code == 404
    assert mailbox.fetches == []


async def test_no_login_no_file(client, session, letter, mailbox):
    pdf = (await rows(session, letter))[1]
    assert (await client.get(url(letter, pdf))).status_code == 401


async def test_huge_attachment_is_refused_before_touching_the_mailbox(
    auth_client, session, letter, mailbox
):
    pdf = (await rows(session, letter))[1]
    pdf.size_bytes = 31 * 1024 * 1024
    await session.flush()

    response = await auth_client.get(url(letter, pdf))

    assert response.status_code == 413
    assert mailbox.fetches == []


async def test_attachments_are_capped_per_letter(session, account):
    from app.mail.base import RawAttachment
    from app.mail.normalize import ATTACHMENTS_LIMIT

    async def nothing() -> bytes:
        return b""

    many = [RawAttachment(f"{n}.txt", "text/plain", 1, nothing) for n in range(ATTACHMENTS_LIMIT + 20)]
    raw = RawMessage(provider_message_id="m", sender="a@b.c", subject="", body_text="", attachments=many)
    [message] = await store_messages(session, account, [raw])
    assert len(await rows(session, message)) == ATTACHMENTS_LIMIT


# --- funções puras ---


def test_pick_by_number_checks_the_name_too():
    """O número do e-mail pode ter ido parar em outro e-mail — só pelo
    número não entregamos o arquivo de outro."""
    with pytest.raises(MailGoneError):
        pick_attachment(raw_letter(), 1, "outro.pdf", len(PDF))


def test_pick_falls_back_to_name_when_the_number_is_off():
    assert pick_attachment(raw_letter(), 0, "Orçamento nº5.pdf", len(PDF)) == PDF
    assert pick_attachment(raw_letter(), None, "logo.svg", 0) == SVG


def test_pick_among_namesakes_uses_the_size():
    letter = EmailMessage()
    letter["From"] = "a@b.c"
    letter.set_content("x")
    letter.add_attachment(b"first", maintype="application", subtype="pdf", filename="a.pdf")
    letter.add_attachment(b"second!!", maintype="application", subtype="pdf", filename="a.pdf")
    assert pick_attachment(letter.as_bytes(), None, "a.pdf", len(b"second!!")) == b"second!!"


def test_risky_types_become_plain_bytes():
    assert safe_type("application/pdf") == "application/pdf"
    assert safe_type("IMAGE/PNG; name=x.png") == "image/png"
    for risky in ("text/html", "image/svg+xml", "text/xml", "application/javascript", "", "x/y"):
        assert safe_type(risky) == "application/octet-stream"


def test_disposition_cannot_be_broken_by_the_name():
    header = disposition('evil"; filename="x.html\r\nSet-Cookie: a=b')
    assert "\r" not in header and "\n" not in header
    simple = header.split("filename*=")[0]
    assert simple.count('"') == 2, "as aspas do nome não escapam do próprio par"
    assert disposition("relatório.pdf").endswith("filename*=UTF-8''relat%C3%B3rio.pdf")
