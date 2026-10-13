import pytest
from sqlalchemy import select

from app.crypto import decrypt_secret
from app.mail.errors import BAD_PASSWORD, MailAuthError
from app.models import Account, Message


@pytest.fixture
def mail(monkeypatch):
    """Substitui o teste de conexão — nos testes não acessamos a internet."""
    state = {"error": None, "checked": []}

    class FakeSource:
        def __init__(self, account):
            self.account = account

        async def verify(self):
            state["checked"].append(self.account.email)
            if state["error"]:
                raise state["error"]

    monkeypatch.setattr("app.api.accounts.get_source", FakeSource)
    return state


async def test_add_mailbox(auth_client, mail, session, user):
    response = await auth_client.post(
        "/api/accounts",
        json={"email": "Boss@Gmail.com", "password": "abcd efgh ijkl mnop"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "boss@gmail.com", "o endereço é convertido para minúsculas"
    assert body["service"] == "Google"
    assert body["is_active"] is True

    stored = await session.scalar(select(Account).where(Account.id == body["id"]))
    assert decrypt_secret(stored.secret_ciphertext) == "abcd efgh ijkl mnop"


async def test_password_is_never_returned(auth_client, mail):
    body = (
        await auth_client.post(
            "/api/accounts", json={"email": "boss@mail.ru", "password": "segredo"}
        )
    ).json()
    assert "segredo" not in str(body)
    assert "password" not in body
    assert "secret_ciphertext" not in body


async def test_broken_mailbox_is_not_saved(auth_client, mail, session):
    """A caixa que não conseguiu conectar não vai para o banco.

    Senão a pessoa clica em «adicionar», vê a linha na lista e vai embora —
    e os e-mails de lá não chegam, sem que ninguém saiba.
    """
    mail["error"] = MailAuthError(
        BAD_PASSWORD, hint="Senhas de app", help_url="https://example.com"
    )

    response = await auth_client.post(
        "/api/accounts", json={"email": "boss@gmail.com", "password": "senha errada"}
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "senha" in detail["message"].lower()
    assert detail["help_url"] == "https://example.com"
    assert not list(await session.scalars(select(Account.email)))


async def test_same_mailbox_twice_is_refused(auth_client, mail):
    payload = {"email": "boss@mail.ru", "password": "p"}
    await auth_client.post("/api/accounts", json=payload)
    assert (await auth_client.post("/api/accounts", json=payload)).status_code == 409


async def test_list_shows_status_of_every_mailbox(auth_client, mail, session, account):
    account.last_error = "A senha de app não funcionou"
    await session.flush()

    items = (await auth_client.get("/api/accounts")).json()["items"]

    [box] = [item for item in items if item["email"] == account.email]
    assert box["service"] == "Mail.ru"
    assert box["last_error"] == "A senha de app não funcionou"


async def test_mailbox_can_be_paused_without_losing_letters(auth_client, session, account):
    session.add(
        Message(account_id=account.id, provider_message_id="m1", sender="a@b.ru", subject="s")
    )
    await session.flush()

    response = await auth_client.patch(f"/api/accounts/{account.id}", json={"is_active": False})

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert await session.scalar(select(Message.id).where(Message.account_id == account.id))


async def test_deleting_a_mailbox_takes_its_letters_with_it(auth_client, session, account):
    session.add(
        Message(account_id=account.id, provider_message_id="m1", sender="a@b.ru", subject="s")
    )
    await session.flush()

    assert (await auth_client.delete(f"/api/accounts/{account.id}")).status_code == 204

    assert not list(await session.scalars(select(Account.id)))
    assert not list(await session.scalars(select(Message.id)))


async def test_deleting_a_missing_mailbox_is_404(auth_client):
    assert (await auth_client.delete("/api/accounts/999999")).status_code == 404


async def test_accounts_require_auth(client):
    assert (await client.get("/api/accounts")).status_code == 401


async def test_services_list_is_offered_for_the_add_form(auth_client):
    items = (await auth_client.get("/api/accounts/services")).json()["items"]

    google = next(item for item in items if item["key"] == "google")
    assert google["label"] == "Google"
    assert google["help_url"].startswith("https://")
    assert google["password_hint"]


async def test_service_is_guessed_by_address(auth_client):
    body = (await auth_client.get("/api/accounts/service-for?email=x@yandex.ru")).json()
    assert body["label"] == "Yandex"
    assert body["imap_host"] == "imap.yandex.ru"


# --- limites contra quem usaria o formulário para testar senhas alheias ---


async def _member(session, email="ana@example.com"):
    from app.models import User
    from app.security import create_token

    person = User(email=email, password_hash="x", role="member")
    session.add(person)
    await session.flush()
    return person, {"Authorization": f"Bearer {create_token(person)}"}


async def test_someone_elses_mailbox_is_not_revealed(client, mail, session, account):
    """Procurar a repetida em todas as caixas contaria a um desconhecido que
    alguém já conectou este endereço aqui. A busca é só entre as dele."""
    _, headers = await _member(session)

    response = await client.post(
        "/api/accounts", json={"email": account.email, "password": "p"}, headers=headers
    )

    assert response.status_code == 201
    assert mail["checked"] == [account.email], "a senha foi conferida como a de qualquer caixa"


async def test_connection_checks_per_hour_are_limited(
    auth_client, mail, session, user, monkeypatch
):
    """Cada caixa conferida é um login de verdade no servidor de e-mail. Sem
    teto, o formulário vira serviço gratuito de adivinhar senhas."""
    from app import quota
    from app.api import accounts as accounts_api
    from app.models import WorkerState

    monkeypatch.setattr(accounts_api, "CHECKS_PER_HOUR", 3)
    mail["error"] = MailAuthError(BAD_PASSWORD)

    for n in range(3):
        response = await auth_client.post(
            "/api/accounts", json={"email": f"chute{n}@gmail.com", "password": "errada"}
        )
        assert response.status_code == 400

    blocked = await auth_client.post(
        "/api/accounts", json={"email": "chute9@gmail.com", "password": "errada"}
    )

    assert blocked.status_code == 429
    assert "Tentativas de conexão demais" in blocked.json()["detail"]
    assert "chute9@gmail.com" not in mail["checked"], "acabou o teto — nem tentamos conectar"
    counter = await session.get(WorkerState, f"mailcheck:{user.id}:{quota.this_hour()}")
    assert counter is not None and counter.value == "3", "o contador fica no banco"


async def test_member_has_a_mailbox_ceiling(client, mail, session, monkeypatch):
    from app.api import accounts as accounts_api

    monkeypatch.setattr(accounts_api, "MEMBER_MAILBOXES", 1)
    _, headers = await _member(session)

    first = await client.post(
        "/api/accounts", json={"email": "um@gmail.com", "password": "p"}, headers=headers
    )
    second = await client.post(
        "/api/accounts", json={"email": "dois@gmail.com", "password": "p"}, headers=headers
    )

    assert first.status_code == 201
    assert second.status_code == 400
    assert "máximo" in second.json()["detail"]
    assert mail["checked"] == ["um@gmail.com"]
