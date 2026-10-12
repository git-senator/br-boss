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
