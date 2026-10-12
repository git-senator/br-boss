"""Camada sobre o modelo.

Todo o resto do código fala com a IA só por este arquivo. O motivo está na
especificação: o modelo tem que poder ser trocado sem reescrever o sistema.
Aqui também fica o tratamento de recusas e erros, para que quem chama
receba uma exceção clara, e não uma estrutura de resposta inesperada.

São quatro opções, trocadas com uma linha no .env:

    AI_PROVIDER=anthropic — a principal, Claude com chave;
    AI_PROVIDER=gemini    — Gemini com chave do Google AI Studio;
    AI_PROVIDER=openrouter — cadeia de modelos do OpenRouter;
    AI_PROVIDER=ollama    — modelo local na própria máquina, sem chave
                            e sem mandar e-mails para fora.
"""

import json

from anthropic import APIStatusError, AsyncAnthropic

from app.ai import gemini, keys
from app.ai.local import LocalModelError, structured_call_local
from app.ai.openrouter import DailyQuotaExhausted, OpenRouterError, structured_call_openrouter
from app.config import settings


class AIError(Exception):
    """O modelo não conseguiu responder: recusa, falha ou resposta ilegível."""


class AIQuotaExhausted(AIError):
    """A cota de requisições acabou até amanhã. Esperar, não repetir."""

    def __init__(self, message: str, reset_at: float | None = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at


class AINotConfigured(AIError):
    """O modelo não está configurado: falta a chave. É um estado esperado
    enquanto o dono não fornece a chave — não é uma falha para gritar no
    log a cada e-mail."""


_client = AsyncAnthropic(api_key=settings.anthropic_api_key)


def using_local_model() -> bool:
    return settings.ai_provider == "ollama"


def using_openrouter() -> bool:
    return settings.ai_provider == "openrouter"


def using_gemini() -> bool:
    return settings.ai_provider == "gemini"


_NO_OWN_KEY = (
    "Você precisa da sua própria chave do Gemini: cadastre-a na página «Chave de IA» "
    "(menu do avatar). A chave do servidor não é usada aqui."
)

_NO_KEY = (
    "A chave da Anthropic não foi configurada. Os e-mails são salvos, mas não são analisados: "
    "defina ANTHROPIC_API_KEY no .env e reinicie."
)


async def _anthropic_call(
    *,
    model: str,
    max_tokens: int,
    system: str,
    user_text: str,
    schema: dict,
) -> dict:
    # Sem esta checagem a biblioteca solta um TypeError lá de dentro, e em
    # cima ninguém entende o que houve. Chave vazia é o estado normal
    # enquanto o dono não a fornece.
    if not settings.anthropic_api_key:
        raise AINotConfigured(_NO_KEY)

    try:
        response = await _client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": user_text}],
        )
    except APIStatusError as exc:
        raise AIError(f"modelo indisponível: {exc.status_code}") from exc

    if response.stop_reason == "refusal":
        raise AIError("o modelo se recusou a analisar este e-mail")
    if response.stop_reason == "max_tokens":
        raise AIError("a resposta do modelo não coube no limite")

    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        raise AIError("o modelo devolveu uma resposta sem texto")

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIError("a resposta do modelo não pôde ser lida como JSON") from exc


async def structured_call(
    *,
    model: str,
    max_tokens: int,
    system: str,
    user_text: str,
    schema: dict,
) -> dict:
    """Perguntar ao modelo e receber a resposta estritamente no esquema.

    Qual modelo exatamente — quem decide é a configuração. Quem chama não
    sabe disso e nem deve saber: o e-mail é analisado do mesmo jeito, e o
    erro que chega é sempre o mesmo.
    """
    key = keys.current()
    if not key.allowed:
        raise AINotConfigured(_NO_OWN_KEY)
    # Chave pessoal é sempre Gemini, seja qual for a configuração do servidor.
    if key.personal or using_gemini():
        if not (key.personal or settings.gemini_api_key):
            raise AINotConfigured("A chave do Gemini não foi configurada: defina GEMINI_API_KEY no .env.")
        try:
            return await gemini.structured_call_gemini(
                api_key=key.personal,
                max_tokens=max_tokens,
                system=system,
                user_text=user_text,
                schema=schema,
            )
        except gemini.DailyQuotaExhausted as exc:
            raise AIQuotaExhausted(str(exc), reset_at=exc.reset_at) from exc
        except gemini.GeminiError as exc:
            raise AIError(str(exc)) from exc

    if using_openrouter():
        if not settings.openrouter_api_key:
            raise AINotConfigured("A chave do OpenRouter não foi configurada: defina OPENROUTER_API_KEY no .env.")
        try:
            return await structured_call_openrouter(
                max_tokens=max_tokens,
                system=system,
                user_text=user_text,
                schema=schema,
            )
        except DailyQuotaExhausted as exc:
            raise AIQuotaExhausted(str(exc), reset_at=exc.reset_at) from exc
        except OpenRouterError as exc:
            raise AIError(str(exc)) from exc

    if using_local_model():
        try:
            return await structured_call_local(
                max_tokens=max_tokens,
                system=system,
                user_text=user_text,
                schema=schema,
            )
        except LocalModelError as exc:
            raise AIError(str(exc)) from exc

    return await _anthropic_call(
        model=model,
        max_tokens=max_tokens,
        system=system,
        user_text=user_text,
        schema=schema,
    )
