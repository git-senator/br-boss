import pyotp
import pytest

from app.security import hash_password, make_totp_secret

PASSWORD = "correct-horse-battery"


@pytest.fixture
async def owner(session, user):
    user.password_hash = hash_password(PASSWORD)
    await session.flush()
    return user


@pytest.fixture
async def owner_with_totp(session, owner):
    owner.totp_secret = make_totp_secret()
    await session.flush()
    return owner


async def test_login_returns_token(client, owner):
    response = await client.post(
        "/api/auth/login", json={"email": owner.email, "password": PASSWORD}
    )

    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_wrong_password_is_rejected(client, owner):
    response = await client.post(
        "/api/auth/login", json={"email": owner.email, "password": "senha errada"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_credentials"


async def test_unknown_email_is_rejected(client, owner):
    response = await client.post(
        "/api/auth/login", json={"email": "desconhecido@uol.com.br", "password": PASSWORD}
    )
    assert response.status_code == 401


async def test_email_case_does_not_matter(client, owner):
    response = await client.post(
        "/api/auth/login", json={"email": owner.email.upper(), "password": PASSWORD}
    )
    assert response.status_code == 200


async def test_login_requires_totp_code(client, owner_with_totp):
    response = await client.post(
        "/api/auth/login", json={"email": owner_with_totp.email, "password": PASSWORD}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "totp_required"


async def test_login_succeeds_with_valid_code(client, owner_with_totp):
    code = pyotp.TOTP(owner_with_totp.totp_secret).now()

    response = await client.post(
        "/api/auth/login",
        json={"email": owner_with_totp.email, "password": PASSWORD, "code": code},
    )

    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_wrong_totp_code_is_rejected(client, owner_with_totp):
    response = await client.post(
        "/api/auth/login",
        json={"email": owner_with_totp.email, "password": PASSWORD, "code": "000000"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_code"


async def test_messages_require_auth(client):
    assert (await client.get("/api/messages")).status_code == 401


async def test_garbage_token_is_rejected(client):
    response = await client.get("/api/messages", headers={"Authorization": "Bearer falsificado"})
    assert response.status_code == 401


async def test_token_opens_the_inbox(auth_client):
    assert (await auth_client.get("/api/messages")).status_code == 200


async def test_totp_is_saved_only_after_the_code_is_confirmed(auth_client, session, user):
    """O segredo só é salvo depois que a pessoa digita o código do aplicativo.

    Senão bastaria fechar a página no meio do caminho para perder o acesso
    à conta — e, junto, a todos os e-mails.
    """
    secret = (await auth_client.post("/api/auth/totp/setup")).json()["secret"]
    await session.refresh(user)
    assert user.totp_secret is None

    bad = await auth_client.post(
        "/api/auth/totp/confirm", json={"secret": secret, "code": "000000"}
    )
    assert bad.status_code == 400
    await session.refresh(user)
    assert user.totp_secret is None

    good = await auth_client.post(
        "/api/auth/totp/confirm",
        json={"secret": secret, "code": pyotp.TOTP(secret).now()},
    )
    assert good.status_code == 200
    await session.refresh(user)
    assert user.totp_secret == secret


async def test_who_am_i(auth_client, user):
    body = (await auth_client.get("/api/auth/me")).json()
    assert body["email"] == user.email
    assert body["totp_enabled"] is False
