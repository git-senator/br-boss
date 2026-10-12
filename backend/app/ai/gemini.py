"""Triagem de e-mails pelo Gemini — chave do Google AI Studio.

Funciona como o OpenRouter: uma cadeia de modelos, em ordem. No Gemini os
limites são contados por modelo, então quando o primeiro esgota a cota
diária, o segundo ainda pode responder.

Falamos com a API nativa do Google, e não com a camada compatível com a
OpenAI: só a nativa informa o motivo do 429 — se o limite é por minuto ou
diário. Sem isso não dá para saber se esperamos um minuto ou pausamos a
triagem até de manhã.
"""

import asyncio
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.config import settings

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MODELS_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
TIMEOUT_SECONDS = 120
# Prazo total para a cadeia inteira, com todas as repetições. Sem ele, um
# modelo travado prendia a pessoa na tela por dois minutos a cada modelo da
# cadeia: o resumo levava três minutos e meio. Estourou o prazo — erro
# «tente de novo», e o e-mail não se perde.
BUDGET_SECONDS = 60

# 429 — limite do modelo, 5xx — falha temporária no Google, 404 — o modelo
# foi descontinuado (o Google faz isso direto: fecharam o gemini-2.5-flash-lite
# para chaves novas enquanto ele estava na cadeia padrão). Nesses casos
# passamos ao próximo modelo. O resto (400 requisição ruim, 403 chave ruim)
# é erro nosso, e o próximo modelo não vai resolver.
_TRY_NEXT = {404, 408, 429, 500, 502, 503, 504}

# O Gemini gratuito vira e mexe responde «sobrecarregado» (503) ou «limite
# por minuto» (429) na cadeia inteira de uma vez — e dali a uns segundos já
# responde. Por isso, se todas as recusas forem temporárias, percorremos a
# cadeia mais uma vez depois de uma pausa. Senão quem clicou em «Preparar
# resposta» veria um erro do nada.
PASSES = 2
PAUSE_SECONDS = 3.0

# Os limites diários do Gemini zeram à meia-noite no horário do Pacífico.
_QUOTA_ZONE = ZoneInfo("America/Los_Angeles")


class GeminiError(Exception):
    """O Gemini não conseguiu responder."""


class DailyQuotaExhausted(GeminiError):
    """Todos os modelos da cadeia esgotaram a cota diária. Esperar a renovação."""

    def __init__(self, message: str, reset_at: float | None = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at


def models() -> list[str]:
    """Cadeia de modelos, em ordem. Strings vazias e espaços são descartados."""
    return [name.strip() for name in settings.gemini_models.split(",") if name.strip()]


async def structured_call_gemini(
    *,
    api_key: str | None = None,
    max_tokens: int,
    system: str,
    user_text: str,
    schema: dict,
) -> dict:
    chain = models()
    if not chain:
        raise GeminiError("nenhum modelo definido em GEMINI_MODELS")

    # Chave pessoal do usuário, se houver; senão, a chave do servidor.
    headers = {"x-goog-api-key": api_key or settings.gemini_api_key}
    request = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
            # Triar um e-mail não pede raciocínio. Sem isto o modelo gasta
            # o limite da resposta pensando, e o JSON sai cortado.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    last_reason = ""
    daily_spent = 0
    clock = asyncio.get_running_loop().time
    deadline = clock() + BUDGET_SECONDS
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        for attempt in range(PASSES):
            if attempt:
                if deadline - clock() <= PAUSE_SECONDS:
                    break
                await asyncio.sleep(PAUSE_SECONDS)
            daily_spent = 0
            for model in chain:
                left = deadline - clock()
                if left <= 1:
                    last_reason = last_reason or "estourou o prazo"
                    break
                try:
                    response = await client.post(
                        ENDPOINT.format(model=model),
                        json=request,
                        headers=headers,
                        timeout=min(TIMEOUT_SECONDS, left),
                    )
                except httpx.HTTPError as exc:
                    last_reason = f"{model}: rede — {exc}"
                    continue

                if response.status_code == 429:
                    if _is_daily(response):
                        daily_spent += 1
                        last_reason = f"{model}: limite diário"
                    else:
                        last_reason = f"{model}: limite por minuto"
                    continue
                if response.status_code in _TRY_NEXT:
                    last_reason = f"{model}: falha ({response.status_code})"
                    continue
                if response.status_code != 200:
                    raise GeminiError(
                        f"{model}: recusa {response.status_code} — {_message(response)}"
                    )

                content = _content(response.json())
                if content is None:
                    last_reason = f"{model}: resposta vazia ou cortada"
                    continue
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    last_reason = f"{model}: a resposta não pôde ser lida como JSON"
                    continue

            if daily_spent == len(chain):
                break  # cota diária — repetir em três segundos não adianta

    if daily_spent == len(chain):
        # Insistir não adianta: até a meia-noite da Califórnia nenhum
        # modelo vai responder.
        raise DailyQuotaExhausted(
            "A cota diária de requisições do Gemini acabou em todos os modelos da cadeia.",
            reset_at=_next_reset(),
        )
    raise GeminiError(last_reason or "a cadeia de modelos está vazia")


def _content(body: dict) -> str | None:
    """Texto da resposta — só se o modelo terminou de falar.

    Um JSON cortado pelo limite pode, por acaso, ser legível mas
    incompleto. É melhor não aproveitar uma resposta dessas.
    """
    try:
        candidate = body["candidates"][0]
        if candidate.get("finishReason") not in (None, "STOP"):
            return None
        parts = candidate["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        return None
    text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
    return text or None


def _is_daily(response: httpx.Response) -> bool:
    """Se o limite é diário. O Google informa isso no quotaId: …PerDay…"""
    try:
        details = response.json().get("error", {}).get("details", [])
    except ValueError:
        return False
    for detail in details:
        for violation in detail.get("violations", []) or []:
            if "PerDay" in str(violation.get("quotaId", "")):
                return True
    return False


def _message(response: httpx.Response) -> str:
    try:
        return str(response.json().get("error", {}).get("message", ""))[:200]
    except ValueError:
        return response.text[:200]


def _next_reset() -> float:
    now = datetime.now(_QUOTA_ZONE)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    return midnight.timestamp()


async def check_key(api_key: str) -> bool | None:
    """Se a chave serve. True — sim, False — o Google não a aceitou,
    None — não deu para verificar (rede, falha no Google).

    Pedimos a lista de modelos: é grátis e não gasta a cota de requisições.
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                MODELS_ENDPOINT, params={"pageSize": 1}, headers={"x-goog-api-key": api_key}
            )
    except httpx.HTTPError:
        return None
    if response.status_code == 200:
        return True
    if response.status_code in (400, 401, 403, 404):
        return False
    return None
