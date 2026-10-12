"""Modelo local como substituto do Claude quando não há chave."""

import json

import httpx
import pytest

from app.ai.provider import AIError, structured_call, using_local_model
from app.ai.schemas import TRIAGE_SCHEMA
from app.config import settings


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "ollama")
    monkeypatch.setattr(settings, "ollama_model", "llama3.2:3b")
    monkeypatch.setattr(settings, "ollama_url", "http://host.docker.internal:11434")


@pytest.fixture
def ollama(monkeypatch):
    """Ollama falsa: os testes não usam a rede."""
    state = {"answer": {"category": "payments", "priority": 88, "summary": "Fatura"}, "sent": None}

    async def fake_post(self, url, json=None, **kwargs):
        state["sent"] = {"url": url, "body": json}
        answer = state["answer"]
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, int):
            return httpx.Response(answer, request=httpx.Request("POST", url))
        return httpx.Response(
            200,
            json={"message": {"content": answer if isinstance(answer, str) else _dump(answer)}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return state


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


async def call() -> dict:
    return await structured_call(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system="faça a triagem do e-mail",
        user_text="<email>fatura a pagar</email>",
        schema=TRIAGE_SCHEMA,
    )


async def test_local_model_answers_like_the_main_one(local, ollama):
    assert await call() == {"category": "payments", "priority": 88, "summary": "Fatura"}


async def test_schema_is_handed_to_the_local_model(local, ollama):
    """Quem garante o esquema é a própria Ollama — senão a resposta teria de
    ser pescada no meio da prosa, e a triagem quebraria a cada dois e-mails."""
    await call()

    body = ollama["sent"]["body"]
    assert body["format"] == TRIAGE_SCHEMA
    assert body["stream"] is False
    assert body["model"] == "llama3.2:3b"
    assert ollama["sent"]["url"].endswith("/api/chat")


async def test_unreachable_model_is_a_normal_ai_error(local, ollama):
    """Um computador desligado com o modelo não deve parecer diferente de
    um Claude indisponível: o e-mail é salvo e a triagem será repetida."""
    ollama["answer"] = httpx.ConnectError("sem conexão")

    with pytest.raises(AIError):
        await call()


async def test_broken_answer_is_an_ai_error(local, ollama):
    ollama["answer"] = "isto não é JSON"
    with pytest.raises(AIError):
        await call()


async def test_error_code_is_an_ai_error(local, ollama):
    ollama["answer"] = 500
    with pytest.raises(AIError):
        await call()


async def test_anthropic_stays_the_default():
    assert settings.ai_provider == "anthropic"
    assert using_local_model() is False


async def test_missing_key_is_a_clear_error(monkeypatch):
    """Chave vazia é o estado normal enquanto o cliente não a fornece.
    O erro precisa ser compreensível, e não um erro interno da biblioteca."""
    monkeypatch.setattr(settings, "ai_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "")

    with pytest.raises(AIError) as problem:
        await call()

    assert "chave" in str(problem.value).lower()
