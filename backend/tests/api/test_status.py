"""Selo de estado no cabeçalho."""

import time
from datetime import UTC, datetime, timedelta

from app.config import settings
from app.models import Message, WorkerState
from app.worker.tasks import PAUSE_KEY


async def test_counts_attention_and_queue(auth_client, session, inbox, monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "AIza-test")

    body = (await auth_client.get("/api/status")).json()

    assert body["ai"] == {
        "name": "Gemini",
        "configured": True,
        "own_key": False,
        "paused_until": None,
    }
    # Na «Caixa de entrada» da fixture: m1 e m4 têm 91, os outros menos; m5 não foi triado.
    assert body["attention"] == 2
    assert body["unsorted"] == 1


async def test_handled_and_snoozed_do_not_ring(auth_client, session, inbox):
    first = (await auth_client.get("/api/messages")).json()["items"]
    top = [m for m in first if (m["priority"] or 0) >= 80]
    await session.get(Message, top[0]["id"])
    (await session.get(Message, top[0]["id"])).handled_at = datetime.now(UTC)
    (await session.get(Message, top[1]["id"])).snoozed_until = datetime.now(UTC) + timedelta(days=1)
    await session.flush()

    assert (await auth_client.get("/api/status")).json()["attention"] == 0


async def test_pause_and_missing_key_are_reported(auth_client, session, monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    session.add(WorkerState(key=PAUSE_KEY, value=str(time.time() + 3600)))
    await session.flush()

    ai = (await auth_client.get("/api/status")).json()["ai"]
    assert ai["configured"] is False
    assert ai["paused_until"] is not None


async def test_closed_without_login(client):
    assert (await client.get("/api/status")).status_code == 401
