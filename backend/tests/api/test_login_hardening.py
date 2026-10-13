"""Proteção do login: força bruta, sondagem de contas, token falsificado."""

import time

import jwt
import pytest

from app.config import settings
from app.security import hash_password

PASSWORD = "correct-horse-battery"


@pytest.fixture
async def owner(session, user):
    user.password_hash = hash_password(PASSWORD)
    await session.flush()
    return user


@pytest.fixture(autouse=True)
def clean_attempts():
    from app.ratelimit import attempts

    attempts.clear()
    yield
    attempts.clear()


async def wrong(client, email):
    return await client.post("/api/auth/login", json={"email": email, "password": "errou"})


async def test_password_guessing_is_stopped(client, owner):
    """Sem limite, dá para testar senhas a seis tentativas por segundo —
    numa noite, são meio milhão de combinações."""
    for _ in range(10):
        assert (await wrong(client, owner.email)).status_code == 401

    blocked = await wrong(client, owner.email)
    assert blocked.status_code == 429
    assert blocked.headers.get("Retry-After")


async def test_correct_password_also_blocked_while_locked(client, owner):
    """O bloqueio não pode ser contornado com a senha certa: senão ele
    não atrapalha a força bruta em nada."""
    for _ in range(11):
        await wrong(client, owner.email)

    right = await client.post("/api/auth/login", json={"email": owner.email, "password": PASSWORD})
    assert right.status_code == 429


async def test_successful_login_clears_the_counter(client, owner):
    for _ in range(5):
        await wrong(client, owner.email)

    ok = await client.post("/api/auth/login", json={"email": owner.email, "password": PASSWORD})
    assert ok.status_code == 200

    for _ in range(10):
        assert (await wrong(client, owner.email)).status_code == 401


async def test_existing_login_is_not_revealed_by_timing(client, owner):
    """A diferença no tempo de resposta denuncia quais endereços têm conta no sistema."""

    async def elapsed(email):
        started = time.perf_counter()
        await wrong(client, email)
        return time.perf_counter() - started

    known = await elapsed(owner.email)
    from app.ratelimit import attempts

    attempts.clear()
    unknown = await elapsed("ninguem@example.com")

    assert unknown > known / 3, (
        f"endereço desconhecido responde rápido demais: {unknown} contra {known}"
    )


async def test_token_without_expiry_is_refused(client, user):
    """Token sem validade é uma chave eterna."""
    forever = jwt.encode({"sub": str(user.id)}, settings.auth_secret, algorithm="HS256")
    response = await client.get("/api/messages", headers={"Authorization": f"Bearer {forever}"})
    assert response.status_code == 401


async def test_a_stranger_cannot_lock_the_owner_out(client, owner):
    """Contando os erros só pelo e-mail, qualquer um trancaria o dono fora da
    própria conta: bastava errar a senha dele dez vezes. O bloqueio é por
    endereço — o desconhecido tranca só a si mesmo."""
    stranger = {"X-Client-IP": "6.6.6.6"}
    for _ in range(11):
        await client.post(
            "/api/auth/login", json={"email": owner.email, "password": "errou"}, headers=stranger
        )
    assert (await wrong(client, owner.email)).status_code == 401, "de outro endereço, ainda pode"

    right = await client.post(
        "/api/auth/login",
        json={"email": owner.email, "password": PASSWORD},
        headers={"X-Client-IP": "1.2.3.4"},
    )
    assert right.status_code == 200


async def test_one_address_cannot_sweep_many_accounts(client, owner):
    """Uma senha por conta, em muitas contas, também é força bruta."""
    away = {"X-Client-IP": "6.6.6.6"}
    for n in range(30):
        await client.post(
            "/api/auth/login",
            json={"email": f"conta{n}@example.com", "password": "x"},
            headers=away,
        )

    blocked = await client.post(
        "/api/auth/login", json={"email": owner.email, "password": PASSWORD}, headers=away
    )
    assert blocked.status_code == 429


def test_invented_emails_do_not_fill_the_memory(monkeypatch):
    """Um script mandando um e-mail inventado a cada tentativa faria o
    contador crescer sem fim."""
    from app import ratelimit

    monkeypatch.setattr(ratelimit, "MAX_KEYS", 50)
    for n in range(500):
        ratelimit.note_failure(f"login:robo{n}@example.com|6.6.6.6")

    assert len(ratelimit.attempts) <= 50


async def test_a_totp_code_cannot_be_used_twice(client, session, owner):
    """Quem espiou o código por cima do ombro tem até um minuto e meio em que
    ele ainda vale. Só o primeiro uso passa."""
    import pyotp

    from app.security import make_totp_secret

    owner.totp_secret = make_totp_secret()
    await session.flush()
    code = pyotp.TOTP(owner.totp_secret).now()
    payload = {"email": owner.email, "password": PASSWORD, "code": code}

    assert (await client.post("/api/auth/login", json=payload)).status_code == 200

    again = await client.post("/api/auth/login", json=payload)
    assert again.status_code == 401
    assert again.json()["detail"] == "invalid_code"
