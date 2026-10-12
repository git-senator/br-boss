"""Cadastro pelo link e a promessa principal: o e-mail dos outros não aparece.

Todo mundo que se cadastrou sozinho é member: vê só as próprias caixas,
e-mails, regras, rascunhos e resumo. A equipe (owner) compartilha a sua
caixa de entrada, mas não vê o e-mail dos cadastrados, nem eles o dela.
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.api import auth as auth_api
from app.config import settings
from app.crypto import encrypt_secret
from app.models import Account, Brief, Message, Rule, User
from app.security import create_token

PASSWORD = "senha-bem-longa-123"


@pytest.fixture(autouse=True)
def fresh_limits(monkeypatch):
    monkeypatch.setattr(auth_api, "_registered", {})
    monkeypatch.setattr(settings, "registration_open", True)


def _as(client: AsyncClient, user: User) -> dict:
    return {"Authorization": f"Bearer {create_token(user)}"}


async def _person(session, email: str, role: str) -> tuple[User, Account, Message]:
    person = User(email=email, password_hash="x", role=role)
    session.add(person)
    await session.flush()
    box = Account(
        user_id=person.id, email=f"box-{person.id}@uol.com.br", secret_ciphertext=encrypt_secret("p")
    )
    session.add(box)
    await session.flush()
    letter = Message(
        account_id=box.id,
        provider_message_id=f"secret-{person.id}",
        sender="bank@example.com",
        subject=f"Segredo {email}",
        body_text="Senha do cofre",
        category="payments",
        priority=95,
        sent_at=datetime.now(UTC),
    )
    session.add(letter)
    session.add(
        Rule(
            user_id=person.id,
            condition_kind="sender_contains",
            condition_value="bank",
            action_kind="set_priority_min",
            action_value="90",
        )
    )
    await session.flush()
    return person, box, letter


@pytest_asyncio.fixture
async def world(session):
    """Dois da equipe e dois desconhecidos, cada um com sua caixa e seu e-mail."""
    return {
        "boss": await _person(session, "boss@team.com", "owner"),
        "client": await _person(session, "client@team.com", "owner"),
        "ana": await _person(session, "ana@example.com", "member"),
        "bob": await _person(session, "bob@example.com", "member"),
    }


# --- cadastro ---


async def test_anyone_with_the_link_can_register(client, session):
    response = await client.post(
        "/api/auth/register",
        json={"email": " New@Example.com ", "password": PASSWORD},
        headers={"X-Client-IP": "1.2.3.4"},
    )

    assert response.status_code == 201
    token = response.json()["access_token"]
    created = await session.scalar(select(User).where(User.email == "new@example.com"))
    assert created.role == "member", "cadastrou-se sozinho — vê só o que é seu"
    assert created.password_hash != PASSWORD

    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["email"] == "new@example.com"
    assert me.json()["role"] == "member"


@pytest.mark.parametrize(
    ("email", "password", "why"),
    [
        ("nao-e-email", PASSWORD, "endereço de e-mail"),
        ("a@b.com", "curta", "pelo menos"),
        ("long-address@b.com", "long-address@b.com", "igual ao e-mail"),
    ],
)
async def test_bad_registration_is_explained(client, email, password, why):
    response = await client.post("/api/auth/register", json={"email": email, "password": password})

    assert response.status_code == 400
    assert why in response.json()["detail"]


async def test_one_address_one_account(client, world):
    response = await client.post(
        "/api/auth/register", json={"email": "ANA@example.com", "password": PASSWORD}
    )

    assert response.status_code == 409


async def test_registration_spam_is_stopped(client):
    for number in range(auth_api.REGISTER_PER_ADDRESS):
        ok = await client.post(
            "/api/auth/register",
            json={"email": f"bot{number}@spam.com", "password": PASSWORD},
            headers={"X-Client-IP": "6.6.6.6"},
        )
        assert ok.status_code == 201

    blocked = await client.post(
        "/api/auth/register",
        json={"email": "bot-last@spam.com", "password": PASSWORD},
        headers={"X-Client-IP": "6.6.6.6"},
    )
    assert blocked.status_code == 429

    other = await client.post(
        "/api/auth/register",
        json={"email": "human@example.com", "password": PASSWORD},
        headers={"X-Client-IP": "7.7.7.7"},
    )
    assert other.status_code == 201, "outro endereço não sofre por causa do spammer"


async def test_registration_can_be_closed(client, monkeypatch):
    monkeypatch.setattr(settings, "registration_open", False)

    response = await client.post(
        "/api/auth/register", json={"email": "late@example.com", "password": PASSWORD}
    )

    assert response.status_code == 403


# --- o e-mail dos outros não aparece ---


async def test_list_shows_only_your_own_mail(client, world):
    ana, _, ana_letter = world["ana"]

    items = (await client.get("/api/messages", headers=_as(client, ana))).json()["items"]

    assert [item["id"] for item in items] == [ana_letter.id]


async def test_search_does_not_reach_into_other_mail(client, world):
    ana = world["ana"][0]

    items = (
        await client.get("/api/messages", params={"q": "Segredo"}, headers=_as(client, ana))
    ).json()["items"]

    assert {item["subject"] for item in items} == {"Segredo ana@example.com"}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/messages/{id}", None),
        ("post", "/api/messages/{id}/read", None),
        ("post", "/api/messages/{id}/draft", None),
        ("post", "/api/messages/{id}/send", {"text": "olá", "to": "x@example.com"}),
        ("post", "/api/messages/{id}/ignore", None),
        ("post", "/api/messages/{id}/snooze", {"hours": 24}),
        ("post", "/api/messages/{id}/reopen", None),
        ("post", "/api/messages/{id}/translate", None),
    ],
)
async def test_someone_elses_letter_is_not_there_even_by_direct_link(
    client, world, method, path, body
):
    ana = world["ana"][0]
    bob_letter = world["bob"][2]

    call = getattr(client, method)
    kwargs = {"headers": _as(client, ana)}
    if body is not None:
        kwargs["json"] = body
    response = await call(path.format(id=bob_letter.id), **kwargs)

    assert response.status_code == 404


async def test_mailboxes_are_private(client, world):
    ana = world["ana"][0]
    bob_box = world["bob"][1]

    boxes = (await client.get("/api/accounts", headers=_as(client, ana))).json()["items"]
    assert [box["email"] for box in boxes] == [world["ana"][1].email]

    for method, kwargs in (
        ("patch", {"json": {"is_active": False}}),
        ("delete", {}),
    ):
        response = await getattr(client, method)(
            f"/api/accounts/{bob_box.id}", headers=_as(client, ana), **kwargs
        )
        assert response.status_code == 404


async def test_rules_are_private(client, world, session):
    ana = world["ana"][0]
    bob = world["bob"][0]

    rules = (await client.get("/api/rules", headers=_as(client, ana))).json()["items"]
    assert len(rules) == 1

    bob_rule = await session.scalar(select(Rule).where(Rule.user_id == bob.id))
    for method in ("patch", "delete"):
        kwargs = {"json": {"is_active": False}} if method == "patch" else {}
        response = await getattr(client, method)(
            f"/api/rules/{bob_rule.id}", headers=_as(client, ana), **kwargs
        )
        assert response.status_code == 404


async def test_counts_and_bell_count_only_your_mail(client, world):
    ana = world["ana"][0]

    status = (await client.get("/api/status", headers=_as(client, ana))).json()
    assert status["attention"] == 1

    counts = (await client.get("/api/messages/counts", headers=_as(client, ana))).json()
    assert sum(value for key, value in counts.items() if isinstance(value, int)) <= 2


async def test_the_team_shares_its_inbox_but_not_strangers_mail(client, world):
    boss = world["boss"][0]

    subjects = {
        item["subject"]
        for item in (await client.get("/api/messages", headers=_as(client, boss))).json()["items"]
    }

    assert subjects == {"Segredo boss@team.com", "Segredo client@team.com"}


async def test_strangers_do_not_see_the_team(client, world):
    ana = world["ana"][0]
    boss_letter = world["boss"][2]

    response = await client.get(f"/api/messages/{boss_letter.id}", headers=_as(client, ana))

    assert response.status_code == 404


async def test_each_person_has_their_own_brief(client, world, session, monkeypatch):
    from app import brief

    async def fake(data):
        return f"Pedem atenção: {len(data.attention)}"

    monkeypatch.setattr(brief, "write_intro", fake)
    ana, bob = world["ana"][0], world["bob"][0]

    ana_brief = (await client.post("/api/brief/refresh", headers=_as(client, ana))).json()
    bob_brief = (await client.post("/api/brief/refresh", headers=_as(client, bob))).json()

    assert [m["subject"] for m in ana_brief["attention"]] == ["Segredo ana@example.com"]
    assert [m["subject"] for m in bob_brief["attention"]] == ["Segredo bob@example.com"]
    stored = list(await session.scalars(select(Brief)))
    assert {row.user_id for row in stored} == {ana.id, bob.id}
