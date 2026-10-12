"""Cadeia de modelos OpenRouter: acabou o limite — vamos para o próximo."""

import json

import httpx
import pytest

from app.ai.openrouter import OpenRouterError, structured_call_openrouter
from app.ai.provider import AIError, structured_call, using_openrouter
from app.ai.schemas import TRIAGE_SCHEMA
from app.config import settings

ANSWER = {"category": "payments", "priority": 88, "summary": "Fatura"}


@pytest.fixture
def openrouter(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-or-test")
    monkeypatch.setattr(settings, "openrouter_models", "flash-free, medium-free, big-free")


@pytest.fixture
def responder(monkeypatch):
    """OpenRouter falso: definimos uma resposta para cada modelo."""
    plan: dict[str, object] = {}
    tried: list[str] = []

    async def fake_post(self, url, json=None, headers=None, **kwargs):
        model = json["model"]
        tried.append(model)
        outcome = plan.get(model, 200)
        if isinstance(outcome, int):
            body = {"choices": [{"message": {"content": _dump(ANSWER)}}]} if outcome == 200 else {}
            return httpx.Response(outcome, json=body, request=httpx.Request("POST", url))
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": outcome}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return {"plan": plan, "tried": tried}


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


async def call() -> dict:
    return await structured_call(
        model="unused",
        max_tokens=1024,
        system="faça a triagem do e-mail",
        user_text="<email>fatura</email>",
        schema=TRIAGE_SCHEMA,
    )


async def test_first_model_answers(openrouter, responder):
    assert await call() == ANSWER
    assert responder["tried"] == ["flash-free"]


async def test_exhausted_model_falls_through_to_the_next(openrouter, responder):
    """O limite do modelo gratuito é 429. O pedido deve ir para o próximo,
    e não perder o e-mail."""
    responder["plan"]["flash-free"] = 429

    assert await call() == ANSWER
    assert responder["tried"] == ["flash-free", "medium-free"]


async def test_walks_the_whole_chain(openrouter, responder):
    responder["plan"]["flash-free"] = 429
    responder["plan"]["medium-free"] = 503

    assert await call() == ANSWER
    assert responder["tried"] == ["flash-free", "medium-free", "big-free"]


async def test_all_exhausted_is_a_normal_ai_error(openrouter, responder):
    """Todos os limites esgotados — o e-mail é salvo e a triagem se repete depois."""
    for model in ("flash-free", "medium-free", "big-free"):
        responder["plan"][model] = 429

    with pytest.raises(AIError):
        await call()


async def test_bad_key_stops_the_chain_at_once(openrouter, responder):
    """401 não é "tente outro modelo", e sim um erro nosso. Não faz sentido
    percorrer a lista inteira e receber três recusas em vez de uma."""
    responder["plan"]["flash-free"] = 401

    with pytest.raises(AIError):
        await call()
    assert responder["tried"] == ["flash-free"]


async def test_broken_json_from_one_model_tries_the_next(openrouter, responder):
    responder["plan"]["flash-free"] = "isto não é JSON"

    assert await call() == ANSWER
    assert responder["tried"] == ["flash-free", "medium-free"]


async def test_missing_key_is_not_configured(monkeypatch):
    from app.ai.provider import AINotConfigured

    monkeypatch.setattr(settings, "ai_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_api_key", "")

    with pytest.raises(AINotConfigured):
        await call()


async def test_empty_chain_is_an_error(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-or-test")
    monkeypatch.setattr(settings, "openrouter_models", "  , ,  ")

    with pytest.raises(OpenRouterError):
        await structured_call_openrouter(
            max_tokens=10, system="s", user_text="u", schema=TRIAGE_SCHEMA
        )


async def test_openrouter_is_off_by_default():
    assert using_openrouter() is False
