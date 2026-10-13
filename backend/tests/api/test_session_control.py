"""O que acontece com as sessões já abertas quando a senha e o código mudam."""

import pytest

from app.security import create_token, hash_password

PASSWORD = "correct-horse-battery"


@pytest.fixture
async def owner(session, user):
    user.password_hash = hash_password(PASSWORD)
    await session.flush()
    return user


async def test_password_change_kicks_out_old_sessions(client, session, owner):
    """A senha é trocada quando se suspeita que vazou. Se a sessão antiga
    continua valendo por uma semana, trocar a senha não salva nada."""
    stolen = create_token(owner)
    assert (
        await client.get("/api/auth/me", headers={"Authorization": f"Bearer {stolen}"})
    ).status_code == 200

    owner.password_hash = hash_password("nova-senha-depois-do-vazamento")
    await session.commit()

    response = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {stolen}"})
    assert response.status_code == 401, "a sessão roubada sobreviveu à troca de senha"


async def test_totp_cannot_be_rebound_without_the_current_code(auth_client, session, user):
    """Quem roubou a sessão não pode vincular o próprio autenticador e trancar o dono."""
    from app.security import make_totp_secret

    user.totp_secret = make_totp_secret()
    await session.commit()

    import pyotp

    new_secret = make_totp_secret()
    response = await auth_client.post(
        "/api/auth/totp/confirm",
        json={"secret": new_secret, "code": pyotp.TOTP(new_secret).now()},
    )

    assert response.status_code == 400
    await session.refresh(user)
    assert user.totp_secret != new_secret

    replaced = await auth_client.post(
        "/api/auth/totp/confirm",
        json={
            "secret": new_secret,
            "code": pyotp.TOTP(new_secret).now(),
            "current_code": pyotp.TOTP(user.totp_secret).now(),
        },
    )
    assert replaced.status_code == 200


async def test_logout_kills_the_token_on_the_server(client, owner):
    """Apagar o cookie não basta: um token copiado antes continuaria valendo
    por uma semana."""
    token = {"Authorization": f"Bearer {create_token(owner)}"}

    assert (await client.post("/api/auth/logout", headers=token)).status_code == 200

    assert (await client.get("/api/auth/me", headers=token)).status_code == 401


def _as(person) -> dict:
    # O token sai depois que a senha do dono foi definida: um token emitido
    # antes já não valeria (a impressão da senha vai dentro dele).
    return {"Authorization": f"Bearer {create_token(person)}"}


async def test_password_change_needs_the_current_one(client, owner):
    response = await client.post(
        "/api/auth/password",
        json={"current_password": "chute", "new_password": "nova-senha-bem-longa"},
        headers=_as(owner),
    )

    assert response.status_code == 400
    assert "senha atual" in response.json()["detail"]


async def test_new_password_follows_the_same_rules_as_signup(client, owner):
    response = await client.post(
        "/api/auth/password",
        json={"current_password": PASSWORD, "new_password": "curta"},
        headers=_as(owner),
    )

    assert response.status_code == 400
    assert "pelo menos" in response.json()["detail"]


async def test_password_change_drops_other_sessions_and_keeps_this_one(client, owner):
    old = {"Authorization": f"Bearer {create_token(owner)}"}

    response = await client.post(
        "/api/auth/password",
        json={"current_password": PASSWORD, "new_password": "nova-senha-bem-longa"},
        headers=old,
    )

    assert response.status_code == 200
    fresh = {"Authorization": f"Bearer {response.json()['access_token']}"}
    assert (await client.get("/api/auth/me", headers=old)).status_code == 401
    assert (await client.get("/api/auth/me", headers=fresh)).status_code == 200
    login = await client.post(
        "/api/auth/login", json={"email": owner.email, "password": "nova-senha-bem-longa"}
    )
    assert login.status_code == 200


async def test_guessing_the_current_password_is_limited(client, owner):
    """Uma sessão roubada não pode virar um jeito de adivinhar a senha sem limite."""
    headers = _as(owner)
    for _ in range(5):
        await client.post(
            "/api/auth/password",
            json={"current_password": "chute", "new_password": "nova-senha-bem-longa"},
            headers=headers,
        )

    blocked = await client.post(
        "/api/auth/password",
        json={"current_password": PASSWORD, "new_password": "nova-senha-bem-longa"},
        headers=headers,
    )
    assert blocked.status_code == 429


async def test_totp_confirm_cannot_be_brute_forced(auth_client, session, user):
    """Sem limite, quem tem a sessão testaria códigos até acertar e trocar o
    autenticador do dono pelo próprio."""
    import pyotp

    from app.security import make_totp_secret

    user.totp_secret = make_totp_secret()
    await session.commit()
    new_secret = make_totp_secret()
    for _ in range(10):
        await auth_client.post(
            "/api/auth/totp/confirm",
            json={"secret": new_secret, "code": "000000", "current_code": "000000"},
        )

    blocked = await auth_client.post(
        "/api/auth/totp/confirm",
        json={
            "secret": new_secret,
            "code": pyotp.TOTP(new_secret).now(),
            "current_code": pyotp.TOTP(user.totp_secret).now(),
        },
    )
    assert blocked.status_code == 429
