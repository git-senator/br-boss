"""Cadeia de modelos Gemini: acabou o limite — vamos para o próximo."""

import json

import httpx
import pytest

from app.ai.gemini import GeminiError, structured_call_gemini
from app.ai.provider import (
    AIError,
    AINotConfigured,
    AIQuotaExhausted,
    structured_call,
    using_gemini,
)
from app.ai.schemas import TRIAGE_SCHEMA
from app.config import settings

ANSWER = {"category": "payments", "priority": 88, "summary": "Fatura", "action_required": True}

PER_DAY = {
    "error": {
        "code": 429,
        "status": "RESOURCE_EXHAUSTED",
        "details": [
            {
                "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}],
            }
        ],
    }
}
PER_MINUTE = {
    "error": {
        "code": 429,
        "status": "RESOURCE_EXHAUSTED",
        "details": [
            {
                "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                "violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}],
            }
        ],
    }
}


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setattr("app.ai.gemini.PAUSE_SECONDS", 0)
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "AIza-test")
    monkeypatch.setattr(settings, "gemini_models", "flash, flash-lite")


def _answer(text: str, finish: str = "STOP") -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}]}


@pytest.fixture
def responder(monkeypatch):
    """Google falso: definimos uma resposta para cada modelo."""
    plan: dict[str, object] = {}
    tried: list[str] = []
    sent: list[dict] = []

    async def fake_post(self, url, json=None, headers=None, **kwargs):
        model = url.split("/models/")[1].split(":")[0]
        tried.append(model)
        sent.append({"json": json, "headers": headers})
        outcome = plan.get(model, _answer(_dump(ANSWER)))
        if isinstance(outcome, list):
            # Fila de respostas: cada chamada pega a próxima; depois, a resposta normal.
            outcome = outcome.pop(0) if outcome else _answer(_dump(ANSWER))
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, tuple):
            status, body = outcome
            return httpx.Response(status, json=body, request=httpx.Request("POST", url))
        return httpx.Response(200, json=outcome, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return {"plan": plan, "tried": tried, "sent": sent}


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


async def test_first_model_answers(gemini, responder):
    assert await call() == ANSWER
    assert responder["tried"] == ["flash"]


async def test_request_carries_key_schema_and_system(gemini, responder):
    await call()
    sent = responder["sent"][0]
    assert sent["headers"]["x-goog-api-key"] == "AIza-test"
    config = sent["json"]["generationConfig"]
    assert config["responseJsonSchema"] == TRIAGE_SCHEMA
    assert config["responseMimeType"] == "application/json"
    assert sent["json"]["systemInstruction"]["parts"][0]["text"] == "faça a triagem do e-mail"


async def test_minute_limit_falls_through_to_the_next(gemini, responder):
    responder["plan"]["flash"] = (429, PER_MINUTE)

    assert await call() == ANSWER
    assert responder["tried"] == ["flash", "flash-lite"]


async def test_daily_limit_on_one_model_falls_through(gemini, responder):
    """No Gemini cada modelo tem seus limites — o próximo ainda responde."""
    responder["plan"]["flash"] = (429, PER_DAY)

    assert await call() == ANSWER
    assert responder["tried"] == ["flash", "flash-lite"]


async def test_daily_limit_on_every_model_pauses(gemini, responder):
    """A cota diária acabou em todos — é uma pausa até a renovação, e não um
    erro do e-mail. Senão o worker passa o dia batendo numa porta fechada."""
    responder["plan"]["flash"] = (429, PER_DAY)
    responder["plan"]["flash-lite"] = (429, PER_DAY)

    with pytest.raises(AIQuotaExhausted) as caught:
        await call()
    assert caught.value.reset_at is not None


async def test_minute_limits_everywhere_is_a_normal_error(gemini, responder):
    """Limites por minuto não são motivo para pausar até de manhã."""
    responder["plan"]["flash"] = (429, PER_MINUTE)
    responder["plan"]["flash-lite"] = (429, PER_DAY)

    with pytest.raises(AIError) as caught:
        await call()
    assert not isinstance(caught.value, AIQuotaExhausted)


async def test_busy_chain_is_tried_once_more(gemini, responder):
    """O Gemini gratuito às vezes fica sobrecarregado por inteiro. Alguns
    segundos depois responde — então uma segunda tentativa é melhor do que
    um erro na frente da pessoa."""
    responder["plan"]["flash"] = [(503, {})]
    responder["plan"]["flash-lite"] = [(503, {})]

    assert await call() == ANSWER
    assert responder["tried"] == ["flash", "flash-lite", "flash"]


async def test_chain_stops_when_time_is_up(gemini, responder, monkeypatch):
    """Um modelo travado não prende a pessoa na tela: acabou o tempo total —
    não seguimos pela cadeia."""
    monkeypatch.setattr("app.ai.gemini.BUDGET_SECONDS", 0)

    with pytest.raises(AIError):
        await call()
    assert responder["tried"] == []


async def test_daily_quota_is_not_retried(gemini, responder):
    responder["plan"]["flash"] = (429, PER_DAY)
    responder["plan"]["flash-lite"] = (429, PER_DAY)

    with pytest.raises(AIQuotaExhausted):
        await call()
    assert responder["tried"] == ["flash", "flash-lite"]


async def test_retired_model_tries_the_next(gemini, responder):
    """O Google descontinua modelos. Um modelo descontinuado na cadeia não deve
    parar a triagem — o próximo ainda funciona."""
    responder["plan"]["flash"] = (404, {"error": {"message": "no longer available"}})

    assert await call() == ANSWER
    assert responder["tried"] == ["flash", "flash-lite"]


async def test_bad_key_stops_the_chain_at_once(gemini, responder):
    responder["plan"]["flash"] = (400, {"error": {"message": "API key not valid"}})

    with pytest.raises(AIError, match="API key not valid"):
        await call()
    assert responder["tried"] == ["flash"]


async def test_cut_off_answer_is_not_taken(gemini, responder):
    """Uma resposta cortada pelo limite de tamanho não é aceita — mesmo que,
    por acaso, seja um JSON válido."""
    responder["plan"]["flash"] = _answer(_dump(ANSWER), finish="MAX_TOKENS")

    assert await call() == ANSWER
    assert responder["tried"] == ["flash", "flash-lite"]


async def test_broken_json_tries_the_next(gemini, responder):
    responder["plan"]["flash"] = _answer("isto não é JSON")

    assert await call() == ANSWER
    assert responder["tried"] == ["flash", "flash-lite"]


async def test_network_failure_tries_the_next(gemini, responder):
    responder["plan"]["flash"] = httpx.ConnectError("sem rede")

    assert await call() == ANSWER
    assert responder["tried"] == ["flash", "flash-lite"]


async def test_missing_key_is_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "")

    with pytest.raises(AINotConfigured):
        await call()


async def test_empty_chain_is_an_error(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "AIza-test")
    monkeypatch.setattr(settings, "gemini_models", "  , ,  ")

    with pytest.raises(GeminiError):
        await structured_call_gemini(
            max_tokens=10, system="s", user_text="u", schema=TRIAGE_SCHEMA
        )


async def test_gemini_is_off_by_default():
    assert using_gemini() is False
