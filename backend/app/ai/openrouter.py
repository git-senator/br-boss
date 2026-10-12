"""Triagem de e-mails pelo OpenRouter — vários modelos com uma só chave.

A ideia é a cadeia: tentamos o primeiro modelo e, quando o limite gratuito
dele acaba no dia, a requisição passa sozinha para o segundo, depois para o
terceiro. Para quatro caixas, os limites gratuitos somados dão conta.

O OpenRouter fala a língua da OpenAI — a mesma de quase todo mundo, menos
a Anthropic. Por isso aqui o formato da requisição é próprio, mas para cima
sai exatamente o mesmo que das outras opções: um dicionário no esquema ou
um erro claro.
"""

import json

import httpx

from app.config import settings

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT_SECONDS = 120

# Códigos em que vale passar ao próximo modelo em vez de desistir:
# 429 — bateu no limite do modelo gratuito, 402 — acabaram os créditos,
# 5xx — falha temporária do lado deles.
_TRY_NEXT = {402, 408, 429, 500, 502, 503, 504}


class OpenRouterError(Exception):
    """O OpenRouter não conseguiu responder."""


class AllModelsExhausted(OpenRouterError):
    """A cadeia inteira se esgotou: cada modelo deu limite ou falha."""


class DailyQuotaExhausted(OpenRouterError):
    """Acabou a cota diária de requisições gratuitas da chave inteira.

    Não é «tente outro modelo» nem «tente de novo em um minuto»: é preciso
    esperar a renovação. Esmurrar a porta fechada com centenas de
    requisições por minuto é o jeito certo de ter a chave bloqueada de vez.
    """

    def __init__(self, message: str, reset_at: float | None = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at


def models() -> list[str]:
    """Cadeia de modelos, em ordem. Strings vazias e espaços são descartados."""
    return [name.strip() for name in settings.openrouter_models.split(",") if name.strip()]


async def structured_call_openrouter(
    *,
    max_tokens: int,
    system: str,
    user_text: str,
    schema: dict,
) -> dict:
    chain = models()
    if not chain:
        raise OpenRouterError("nenhum modelo definido em OPENROUTER_MODELS")

    headers = {"Authorization": f"Bearer {settings.openrouter_api_key}"}
    request = {
        "max_tokens": max_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "triage", "strict": True, "schema": schema},
        },
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ],
    }

    last_reason = ""
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        for model in chain:
            try:
                response = await client.post(
                    ENDPOINT, json={**request, "model": model}, headers=headers
                )
            except httpx.HTTPError as exc:
                last_reason = f"{model}: rede — {exc}"
                continue

            if response.status_code == 429:
                quota = _daily_quota(response)
                if quota is not None:
                    raise quota
                last_reason = f"{model}: limite do modelo"
                continue
            if response.status_code in _TRY_NEXT:
                last_reason = f"{model}: limite ou falha ({response.status_code})"
                continue
            if response.status_code != 200:
                # 400/401/403 não é «tente outro», é erro nosso (chave ruim,
                # requisição ruim). Não adianta seguir pela cadeia.
                raise OpenRouterError(f"{model}: recusa {response.status_code}")

            content = _content(response.json())
            if content is None:
                last_reason = f"{model}: resposta vazia"
                continue
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                last_reason = f"{model}: a resposta não pôde ser lida como JSON"
                continue

    raise AllModelsExhausted(last_reason or "a cadeia de modelos está vazia")


def _content(body: dict) -> str | None:
    try:
        return body["choices"][0]["message"]["content"] or None
    except (KeyError, IndexError, TypeError):
        return None


def _daily_quota(response: httpx.Response) -> DailyQuotaExhausted | None:
    """Distinguir a cota diária da chave do limite de um modelo específico.

    A primeira vale para todos os modelos — percorrer a cadeia é inútil.
    O segundo afeta um modelo só, e o próximo pode responder.
    """
    try:
        error = response.json().get("error", {})
    except ValueError:
        return None

    source = str(error.get("metadata", {}).get("limit_source", ""))
    text = str(error.get("message", ""))
    if "free-models-per-day" not in text and "free_tier_daily" not in source:
        return None

    reset = error.get("metadata", {}).get("headers", {}).get("X-RateLimit-Reset")
    try:
        reset_at = float(reset) / 1000 if reset else None
    except (TypeError, ValueError):
        reset_at = None
    return DailyQuotaExhausted(
        "A cota diária de requisições gratuitas do OpenRouter acabou. "
        "Uma recarga de 10 créditos aumenta a cota de 50 para 1000 por dia.",
        reset_at=reset_at,
    )
