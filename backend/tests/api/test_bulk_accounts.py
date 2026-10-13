"""Conectar várias caixas de e-mail com um único bloco de texto."""

import pytest
from sqlalchemy import select

from app.crypto import decrypt_secret
from app.mail.errors import BAD_PASSWORD, MailAuthError
from app.models import Account


@pytest.fixture
def mail(monkeypatch):
    state = {"broken": set()}

    class FakeSource:
        def __init__(self, account):
            self.account = account

        async def verify(self):
            if self.account.email in state["broken"]:
                raise MailAuthError(BAD_PASSWORD, hint="dica", help_url="https://x")

    monkeypatch.setattr("app.api.accounts.get_source", FakeSource)
    return state


async def added_emails(session):
    return sorted(await session.scalars(select(Account.email)))


async def test_whole_list_connects_at_once(auth_client, mail, session):
    response = await auth_client.post(
        "/api/accounts/bulk",
        json={
            "text": """
            boss@gmail.com abcd efgh ijkl mnop
            work@mail.ru senha-do-app
            second@yandex.ru xxxxyyyyzzzzwwww
            """
        },
    )

    assert response.status_code == 200
    assert response.json()["added"] == 3
    assert await added_emails(session) == ["boss@gmail.com", "second@yandex.ru", "work@mail.ru"]


async def test_one_bad_line_does_not_stop_the_rest(auth_client, mail, session):
    """Uma senha errada entre trinta não pode cancelar as outras
    vinte e nove — senão seria preciso começar tudo de novo."""
    mail["broken"].add("bad@gmail.com")

    body = (
        await auth_client.post(
            "/api/accounts/bulk",
            json={"text": "good@gmail.com senha1\nbad@gmail.com senha2\nalso@mail.ru senha3"},
        )
    ).json()

    assert body["added"] == 2
    assert [item["email"] for item in body["failed"]] == ["bad@gmail.com"]
    assert "senha" in body["failed"][0]["message"].lower()
    assert await added_emails(session) == ["also@mail.ru", "good@gmail.com"]


async def test_spaces_inside_app_password_do_not_break_it(auth_client, mail, session):
    """O Google mostra a senha como «abcd efgh ijkl mnop». As pessoas copiam
    com os espaços — isso tem que funcionar."""
    await auth_client.post(
        "/api/accounts/bulk", json={"text": "boss@gmail.com abcd efgh ijkl mnop"}
    )

    stored = await session.scalar(select(Account).where(Account.email == "boss@gmail.com"))
    assert decrypt_secret(stored.secret_ciphertext) == "abcdefghijklmnop"


async def test_password_with_spaces_that_is_not_an_app_password_is_kept_as_is(
    auth_client, mail, session
):
    await auth_client.post(
        "/api/accounts/bulk", json={"text": "boss@mail.ru minha senha longa da caixa"}
    )
    stored = await session.scalar(select(Account).where(Account.email == "boss@mail.ru"))
    assert decrypt_secret(stored.secret_ciphertext) == "minha senha longa da caixa"


async def test_already_connected_mailbox_is_reported_not_duplicated(auth_client, mail, session):
    await auth_client.post("/api/accounts/bulk", json={"text": "boss@gmail.com senha"})

    body = (
        await auth_client.post("/api/accounts/bulk", json={"text": "boss@gmail.com senha"})
    ).json()

    assert body["added"] == 0
    assert "já está conectada" in body["failed"][0]["message"]


async def test_garbage_lines_are_reported_clearly(auth_client, mail):
    body = (
        await auth_client.post(
            "/api/accounts/bulk", json={"text": "só uma linha sem senha\n\n   \nboss@gmail.com p"}
        )
    ).json()

    assert body["added"] == 1
    assert len(body["failed"]) == 1
    assert "e-mail" in body["failed"][0]["message"].lower()


async def test_separators_can_be_tabs_colons_or_commas(auth_client, mail, session):
    await auth_client.post(
        "/api/accounts/bulk",
        json={"text": "a@gmail.com\tsenha1\nb@mail.ru:senha2\nc@yandex.ru, senha3"},
    )
    assert await added_emails(session) == ["a@gmail.com", "b@mail.ru", "c@yandex.ru"]


async def test_bulk_requires_auth(client):
    assert (await client.post("/api/accounts/bulk", json={"text": "a@b.ru p"})).status_code == 401


# --- limites da lista ---


async def test_too_many_lines_are_refused_plainly(auth_client, mail):
    text = "\n".join(f"caixa{n}@gmail.com senha" for n in range(51))

    response = await auth_client.post("/api/accounts/bulk", json={"text": text})

    assert response.status_code == 400
    assert "50" in response.json()["detail"]


async def test_huge_list_is_refused_plainly(auth_client, mail):
    response = await auth_client.post("/api/accounts/bulk", json={"text": "x" * 20_001})

    assert response.status_code == 400
    assert "grande demais" in response.json()["detail"]


async def test_list_shares_the_hourly_checks_with_the_form(auth_client, mail, session, monkeypatch):
    """O teto de testes por hora vale para o formulário e a lista somados:
    senão bastaria trocar de tela para dar a volta nele."""
    from app.api import accounts as accounts_api

    monkeypatch.setattr(accounts_api, "CHECKS_PER_HOUR", 3)
    await auth_client.post("/api/accounts", json={"email": "form@gmail.com", "password": "p"})

    body = (
        await auth_client.post(
            "/api/accounts/bulk",
            json={"text": "a@gmail.com s1\nb@gmail.com s2\nc@gmail.com s3"},
        )
    ).json()

    assert body["added"] == 2
    assert [item["email"] for item in body["failed"]] == ["c@gmail.com"]
    assert "Tentativas de conexão demais" in body["failed"][0]["message"]


async def test_mailbox_of_a_stranger_is_not_reported_as_taken(client, mail, session, account):
    from app.models import User
    from app.security import create_token

    person = User(email="ana@example.com", password_hash="x", role="member")
    session.add(person)
    await session.flush()

    body = (
        await client.post(
            "/api/accounts/bulk",
            json={"text": f"{account.email} senha"},
            headers={"Authorization": f"Bearer {create_token(person)}"},
        )
    ).json()

    assert body == {"added": 1, "failed": []}
