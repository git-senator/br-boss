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
