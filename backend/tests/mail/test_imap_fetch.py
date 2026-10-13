from email.header import Header

import pytest

from app.mail.imap_source import ImapSource
from app.models import Account


def letter(subject: str) -> bytes:
    """E-mail com o assunto codificado conforme as regras — como a maioria envia."""
    encoded = Header(subject, "utf-8").encode()
    return (
        f"From: a@b.com\nSubject: {encoded}\nDate: Mon, 17 Aug 2026 10:00:00 +0000\n\nbody\n"
    ).encode()


def sloppy_letter(subject: str) -> bytes:
    """E-mail com o assunto em UTF-8 cru, sem declarar a codificação — alguns
    servidores fazem isso contrariando o padrão, e temos que aguentar."""
    return (
        f"From: a@b.com\nSubject: {subject}\nDate: Mon, 17 Aug 2026 10:00:00 +0000\n\nbody\n"
    ).encode()


class FakeImap:
    """Servidor IMAP de mentira: guarda os e-mails por UID."""

    def __init__(
        self,
        letters: dict[str, bytes],
        spam: dict[str, bytes] | None = None,
        junk_flag: bool = True,
    ) -> None:
        self.letters = letters
        self.spam = spam or {}
        self.junk_flag = junk_flag
        self.logged_out = False
        self.fetch_commands: list[tuple[str, str]] = []
        self.opened: list[str] = []
        self.current = self.letters
        # Tamanho declarado de cada e-mail (RFC822.SIZE). Sem entrada — pequeno.
        self.sizes: dict[str, int] = {}

    def list(self):
        junk = rb'(\HasNoChildren \Junk) "/" "[Gmail]/Spam"'
        plain = rb'(\HasNoChildren) "/" "[Gmail]/Spam"'
        return "OK", [
            rb'(\HasNoChildren) "/" "INBOX"',
            junk if self.junk_flag else plain,
        ]

    def select(self, mailbox, readonly=False):
        name = mailbox.strip(chr(34))
        self.opened.append(name)
        self.current = self.spam if "Spam" in name else self.letters
        return "OK", [b"1"]

    def uid(self, command: str, *args):
        if command == "search":
            query = args[-1]
            start = int(query.split()[1].split(":")[0])
            matching = sorted((uid for uid in self.current if int(uid) >= start), key=int)
            return "OK", [" ".join(matching).encode()]
        if command == "fetch" and args[-1] == "(RFC822.SIZE)":
            rows = [
                f"{n} (UID {uid} RFC822.SIZE {self.sizes.get(uid, 100)})".encode()
                for n, uid in enumerate(args[0].split(","), start=1)
            ]
            return "OK", rows
        if command == "fetch":
            uid = args[0]
            self.fetch_commands.append((uid, args[-1]))
            return "OK", [(b"header", self.current[uid])]
        raise AssertionError(f"unexpected command {command}")

    def logout(self):
        self.logged_out = True


@pytest.fixture
def source(monkeypatch):
    def build(
        letters: dict[str, bytes],
        spam: dict[str, bytes] | None = None,
        junk_flag: bool = True,
    ) -> tuple[ImapSource, FakeImap]:
        fake = FakeImap(letters, spam, junk_flag)
        account = Account(provider="imap", email="boss@uol.com.br", secret_ciphertext="x")
        instance = ImapSource(account)
        monkeypatch.setattr(instance, "_login", lambda: fake)
        return instance, fake

    return build


async def test_first_run_takes_everything(source):
    instance, _ = source({"1": letter("um"), "2": letter("dois")})
    messages, cursor = await instance.fetch_since(None)
    assert [m.subject for m in messages] == ["um", "dois"]
    assert cursor == "inbox=2"


async def test_second_run_takes_only_new(source):
    instance, _ = source({"1": letter("antigo"), "2": letter("novo")})
    messages, cursor = await instance.fetch_since("1")
    assert [m.subject for m in messages] == ["novo"]
    assert cursor == "inbox=2"


async def test_no_new_messages_keeps_cursor(source):
    instance, _ = source({"1": letter("antigo")})
    messages, cursor = await instance.fetch_since("1")
    assert messages == []
    assert cursor == "inbox=1", "a marca fica no lugar, os e-mails não chegam de novo"


async def test_connection_is_always_closed(source):
    instance, fake = source({"1": letter("um")})
    await instance.fetch_since(None)
    assert fake.logged_out is True


async def test_connection_closed_even_on_error(source, monkeypatch):
    instance, fake = source({"1": letter("um")})
    monkeypatch.setattr(fake, "uid", lambda *args: (_ for _ in ()).throw(OSError("a rede caiu")))
    with pytest.raises(OSError):
        await instance.fetch_since(None)
    assert fake.logged_out is True


async def test_raw_utf8_subject_survives(source):
    instance, _ = source({"1": sloppy_letter("Urgente: boleto vence amanhã, ação necessária")})
    messages, _ = await instance.fetch_since(None)
    assert messages[0].subject == "Urgente: boleto vence amanhã, ação necessária"


async def test_latin_subject_unaffected_by_the_fix(source):
    instance, _ = source({"1": letter("Invoice #4417 — café")})
    messages, _ = await instance.fetch_since(None)
    assert messages[0].subject == "Invoice #4417 — café"


def test_host_is_derived_from_email_domain():
    account = Account(provider="imap", email="boss@firma.com.br", secret_ciphertext="x")
    assert ImapSource(account).host == "imap.firma.com.br"


async def test_reading_mail_does_not_mark_it_read_in_the_mailbox(source):
    """Buscar os e-mails não pode mexer na marca «lido» no servidor.

    Com «RFC822», o e-mail virava lido direto no Gmail: o sistema
    buscou a mensagem — e ela já não aparece em negrito no celular do dono.
    Quem decide se o e-mail foi lido é a pessoa, não o sistema.
    """
    instance, fake = source({"1": letter("Boleto"), "2": letter("Segundo")})

    await instance.fetch_since(None)

    assert fake.fetch_commands, "os e-mails foram mesmo buscados"
    assert all("PEEK" in command for _, command in fake.fetch_commands)
    assert not any("RFC822" in command for _, command in fake.fetch_commands)


async def test_spam_is_fetched_too(source):
    """Um e-mail importante que caiu no spam, o sistema tem que mostrar.

    Antes líamos só a «Caixa de entrada», e para o sistema esse e-mail
    simplesmente não existia.
    """
    instance, fake = source({"1": letter("Boleto")}, spam={"7": letter("Do spam")})

    messages, cursor = await instance.fetch_since(None)

    assert [m.folder for m in messages] == ["inbox", "spam"]
    assert [m.subject for m in messages] == ["Boleto", "Do spam"]
    assert "[Gmail]/Spam" in fake.opened


async def test_numbers_from_different_folders_do_not_collide(source):
    """O número do e-mail é único dentro da pasta, mas não entre pastas. Sem
    o prefixo, um e-mail do spam sobrescreveria um da «Caixa de entrada»."""
    instance, _ = source({"5": letter("Recebido")}, spam={"5": letter("Spammado")})

    messages, _ = await instance.fetch_since(None)

    assert sorted(m.provider_message_id for m in messages) == ["5", "spam:5"]


async def test_each_folder_keeps_its_own_mark(source):
    """As marcas de cada pasta vivem separadas no cursor: senão uma pasta
    bagunçaria a contagem da outra, e e-mails se perderiam aos montes."""
    instance, _ = source({"1": letter("a"), "2": letter("b")}, spam={"9": letter("c")})

    _, cursor = await instance.fetch_since(None)
    assert cursor == "inbox=2,spam=9"

    again, _ = await instance.fetch_since(cursor)
    assert again == [], "a segunda rodada não traz a mesma coisa"


async def test_an_old_cursor_still_works(source):
    """Antes desta mudança o cursor guardava só um número — a marca da «Caixa
    de entrada». As caixas já conectadas não podem buscar tudo de novo por isso."""
    instance, _ = source({"1": letter("a"), "2": letter("b")}, spam={})

    messages, _ = await instance.fetch_since("1")

    assert [m.subject for m in messages] == ["b"]


async def test_a_mailbox_without_spam_folder_still_works(source):
    """Nem todo serviço tem pasta de spam. Isso não é motivo para quebrar."""
    instance, fake = source({"1": letter("a")}, spam={}, junk_flag=False)
    fake.spam = {}

    messages, cursor = await instance.fetch_since(None)

    assert [m.subject for m in messages] == ["a"]
    assert cursor.startswith("inbox=")


def test_password_login_turned_off_is_detected():
    """Outlook/Hotmail: o servidor anuncia LOGINDISABLED e só AUTH=XOAUTH2."""
    from app.mail.imap_source import password_login_allowed

    microsoft = ("IMAP4REV1", "AUTH=XOAUTH2", "LOGINDISABLED", "SASL-IR")
    gmail = ("IMAP4REV1", "AUTH=XOAUTH2", "AUTH=PLAIN", "AUTH=PLAIN-CLIENTTOKEN")
    uol = ("IMAP4REV1", "SASL-IR", "AUTH=PLAIN")
    old_server = ("IMAP4REV1", "IDLE")

    assert password_login_allowed(microsoft) is False
    assert password_login_allowed(gmail) is True
    assert password_login_allowed(uol) is True
    assert password_login_allowed(old_server) is True, "sem LOGINDISABLED, LOGIN vale"


async def test_a_huge_letter_is_not_downloaded(source):
    """Duzentos e-mails de 50 MB numa rodada estouram a memória do worker.
    O gigante entra só com o cabeçalho e um aviso — e a caixa segue."""
    from app.mail.imap_source import MAX_MESSAGE_BYTES, TOO_BIG_NOTE

    instance, fake = source({"1": letter("Pequeno"), "2": letter("Gigante")}, spam={})
    fake.sizes = {"2": MAX_MESSAGE_BYTES + 1}

    messages, cursor = await instance.fetch_since(None)

    assert dict(fake.fetch_commands) == {"1": "(BODY.PEEK[])", "2": "(BODY.PEEK[HEADER])"}
    big = next(m for m in messages if m.provider_message_id == "2")
    assert big.subject == "Gigante", "o cabeçalho chegou"
    assert big.body_text == TOO_BIG_NOTE
    assert cursor.startswith("inbox=2"), "o cursor anda: o gigante não trava a caixa"
