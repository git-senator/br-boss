"""Chave própria do Gemini por usuário: o e-mail dele, por conta dele."""

import time
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.ai import gemini, keys
from app.ai.provider import AINotConfigured, AIQuotaExhausted, structured_call
from app.ai.triage import TriageResult
from app.config import settings
from app.crypto import encrypt_secret
from app.mail.base import RawMessage
from app.models import Account, Message, User
from app.worker import tasks

KEY = "AIzaSyPersonal-key-for-tests-0000wxyz"


@pytest.fixture(autouse=True)
def clean_pauses(monkeypatch):
    monkeypatch.setattr(tasks, "_paused", {})


@pytest.fixture
def google(monkeypatch):
    """Checagem da chave no Google — sem rede. verdict: True/False/None."""
    state = {"verdict": True, "checked": []}

    async def check(api_key):
        state["checked"].append(api_key)
        return state["verdict"]

    monkeypatch.setattr(gemini, "check_key", check)
    return state


def raw(msg_id: str) -> RawMessage:
    return RawMessage(
        provider_message_id=msg_id,
        sender="ana@fornecedor.com.br",
        subject="Boleto",
        body_text="Pague até sexta",
        sent_at=datetime(2026, 8, 17, tzinfo=UTC),
    )


# --- salvar a chave ---


async def test_key_is_saved_encrypted_and_never_shown_whole(auth_client, session, user, google):
    response = await auth_client.put("/api/auth/ai-key", json={"key": f"  {KEY}\n"})

    assert response.status_code == 200
    assert response.json() == {"ai_key_hint": "…wxyz"}
    await session.refresh(user)
    assert user.ai_key_ciphertext and KEY not in user.ai_key_ciphertext
    assert google["checked"] == [KEY], "espaços e quebra de linha vindos da área de transferência foram removidos"

    me = (await auth_client.get("/api/auth/me")).text
    assert KEY not in me
    assert "…wxyz" in me


async def test_a_key_google_rejects_is_not_saved(auth_client, session, user, google):
    google["verdict"] = False

    response = await auth_client.put("/api/auth/ai-key", json={"key": KEY})

    assert response.status_code == 400
    assert "O Google não aceitou" in response.json()["detail"]
    await session.refresh(user)
    assert user.ai_key_ciphertext is None


async def test_garbage_is_refused_without_asking_google(auth_client, google):
    response = await auth_client.put("/api/auth/ai-key", json={"key": "minha chave"})

    assert response.status_code == 400
    assert google["checked"] == []


async def test_key_is_saved_when_google_cannot_be_asked(auth_client, session, user, google):
    """Falha de conexão com o Google não é motivo para impedir a pessoa de trabalhar."""
    google["verdict"] = None

    assert (await auth_client.put("/api/auth/ai-key", json={"key": KEY})).status_code == 200
    await session.refresh(user)
    assert user.ai_key_ciphertext


async def test_key_can_be_removed(auth_client, session, user, google):
    await auth_client.put("/api/auth/ai-key", json={"key": KEY})

    response = await auth_client.delete("/api/auth/ai-key")

    assert response.json() == {"ai_key_hint": None}
    await session.refresh(user)
    assert user.ai_key_ciphertext is None


# --- qual chave está valendo ---


@pytest.fixture
def gemini_calls(monkeypatch):
    calls = []

    async def fake(*, api_key=None, **_):
        calls.append(api_key)
        return {"ok": True}

    monkeypatch.setattr(gemini, "structured_call_gemini", fake)
    return calls


async def _ask() -> dict:
    return await structured_call(model="m", max_tokens=10, system="s", user_text="u", schema={})


async def test_personal_key_goes_to_gemini_whatever_the_server_uses(user, gemini_calls):
    user.ai_key_ciphertext = encrypt_secret(KEY)

    with keys.using(keys.key_of(user)):
        await _ask()

    assert gemini_calls == [KEY], "o servidor está no Claude, mas a chave pessoal é Gemini mesmo assim"


async def test_without_a_personal_key_the_server_key_works(user, gemini_calls, monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "AIza-server")

    with keys.using(keys.key_of(user)):
        await _ask()

    assert gemini_calls == [None], "a chave do servidor vem da configuração, não do usuário"


async def test_server_key_can_be_kept_to_yourself(user, gemini_calls, monkeypatch):
    """AI_SHARED_KEY=false: quem se cadastrou sozinho e não colou a própria
    chave não ganha IA por conta dos outros."""
    user.role = "member"
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "AIza-server")
    monkeypatch.setattr(settings, "ai_shared_key", False)

    with keys.using(keys.key_of(user)), pytest.raises(AINotConfigured):
        await _ask()
    assert gemini_calls == []


async def test_draft_is_written_with_the_key_of_whoever_asked(
    auth_client, session, user, account, gemini_calls
):
    user.ai_key_ciphertext = encrypt_secret(KEY)
    message = Message(
        account_id=account.id,
        provider_message_id="d1",
        sender="ana@fornecedor.com.br",
        subject="Boleto",
        body_text="Pague até sexta",
    )
    session.add(message)
    await session.flush()

    seen = []

    async def fake_draft(*_):
        seen.append(keys.current().personal)
        raise AINotConfigured("pare")

    import app.api.replies as replies

    replies_draft = replies.draft_reply
    replies.draft_reply = fake_draft
    try:
        await auth_client.post(f"/api/messages/{message.id}/draft")
    finally:
        replies.draft_reply = replies_draft

    assert seen == [KEY]
    assert keys.current() == keys.SERVER, "a chave não ficou pendurada depois da requisição"


# --- worker ---


@pytest.fixture
def triage_keys(monkeypatch):
    """Triagem falsa: registra com qual chave saiu cada requisição."""
    state = {"seen": [], "exhausted": set()}

    async def fake_triage(message):
        key = keys.current()
        state["seen"].append(key.personal)
        if key.personal in state["exhausted"]:
            raise AIQuotaExhausted("a cota acabou", reset_at=time.time() + 3600)
        return TriageResult(category="payments", priority=50, summary="Boleto")

    monkeypatch.setattr("app.worker.tasks.triage", fake_triage)
    return state


async def test_mailbox_is_sorted_with_its_owners_key(session, user, account, triage_keys, monkeypatch):
    user.ai_key_ciphertext = encrypt_secret(KEY)
    source = type("S", (), {"fetch_since": lambda self, cursor: _done([raw("m1")])})()
    monkeypatch.setattr("app.worker.tasks.get_source", lambda account: source)

    await tasks.sync_account(session, account)

    assert triage_keys["seen"] == [KEY]


async def _done(messages):
    return messages, "1"


async def test_one_exhausted_key_does_not_stop_the_others(session_factory, triage_keys):
    """Acabou a cota da chave pessoal — a pausa vale só para ela. O e-mail
    na chave do servidor continua sendo triado, e vice-versa."""
    async with session_factory() as session:
        own = User(email="own@example.com", password_hash="x", ai_key_ciphertext=encrypt_secret(KEY))
        shared = User(email="shared@example.com", password_hash="x")
        session.add_all([own, shared])
        await session.flush()
        for person in (own, shared):
            box = Account(
                user_id=person.id,
                email=f"box@{person.email.split('@')[0]}.com.br",
                secret_ciphertext=encrypt_secret("p"),
            )
            session.add(box)
            await session.flush()
            session.add_all(
                Message(
                    account_id=box.id,
                    provider_message_id=f"{person.email}-{i}",
                    sender="ana@fornecedor.com.br",
                    subject="Boleto",
                    sent_at=datetime(2026, 8, 17, tzinfo=UTC),
                )
                for i in range(3)
            )
        await session.commit()
        own_scope = keys.scope_of(own)

    triage_keys["exhausted"].add(KEY)

    sorted_now = await tasks.classify_pending(session_factory)

    assert sorted_now == 3, "os três e-mails na chave do servidor foram triados"
    assert tasks.classification_paused(own_scope)
    assert not tasks.classification_paused(""), "a pausa da chave pessoal não afetou o servidor"

    # O próximo ciclo não usa a chave pessoal enquanto ela está em pausa.
    before = triage_keys["seen"].count(KEY)
    await tasks.classify_pending(session_factory)
    assert triage_keys["seen"].count(KEY) == before

    async with session_factory() as session:
        left = await session.scalars(select(Message).where(Message.category.is_(None)))
        assert len(list(left)) == 3, "os e-mails em pausa esperam, não se perdem"


async def test_a_new_key_is_not_held_by_the_old_ones_pause(session, user):
    user.ai_key_ciphertext = encrypt_secret(KEY)
    old = keys.scope_of(user)
    tasks._pause_until(time.time() + 3600, old)

    user.ai_key_ciphertext = encrypt_secret("AIzaSyAnother-key-for-tests-1111abcd")

    assert not tasks.classification_paused(keys.scope_of(user))


async def test_status_tells_whose_key_works(auth_client, session, user, monkeypatch):
    user.role = "member"
    monkeypatch.setattr(settings, "ai_shared_key", False)
    ai = (await auth_client.get("/api/status")).json()["ai"]
    assert ai["configured"] is False and ai["own_key"] is False

    user.ai_key_ciphertext = encrypt_secret(KEY)
    await session.flush()
    ai = (await auth_client.get("/api/status")).json()["ai"]
    assert ai == {"name": "Gemini", "configured": True, "own_key": True, "paused_until": None}


async def test_the_team_always_has_the_server_key(user, gemini_calls, monkeypatch):
    """A equipe (owner) é para quem o servidor existe: a chave do servidor é
    dela por direito, mesmo quando está fechada para desconhecidos."""
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "AIza-server")
    monkeypatch.setattr(settings, "ai_shared_key", False)

    with keys.using(keys.key_of(user)):
        await _ask()
    assert gemini_calls == [None]
