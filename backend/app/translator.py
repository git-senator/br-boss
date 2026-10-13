"""Tradução de e-mails para o português do Brasil sem rede neural.

Dois tradutores, nesta ordem:

1. DeepL API Free (se DEEPL_API_KEY estiver definida) — a melhor qualidade
   sem uma rede neural de uso geral, 500 000 caracteres por mês de graça.
2. LibreTranslate neste mesmo servidor (contêiner translator) — de graça
   e sem limites, os e-mails não saem daqui; o estilo às vezes é truncado.

Acabou a cota mensal do DeepL ou ele não respondeu — o e-mail é traduzido
pelo tradutor próprio: a pessoa recebe uma tradução, e não um erro.

Links nunca são entregues ao tradutor: a tradução automática adora
"traduzir" endereços, e um link quebrado numa fatura é pior do que um
e-mail sem tradução. O parágrafo é cortado em volta dos links, só os
pedaços de texto são traduzidos, e os links voltam ao lugar como estavam.
"""

import logging
import re

import httpx

from app.ai.translate import CUT_NOTE, LETTER_CHARS, Translation
from app.config import settings
from app.models import Message

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 110  # o nginx espera 120 — responder antes disso
DEEPL_TIMEOUT_SECONDS = 40  # se não respondeu — dá tempo de traduzir com o próprio
TARGET = "pt"  # idioma de destino no LibreTranslate
DEEPL_TARGET = "PT-BR"  # no DeepL o português é escolhido com a variante
_URL = re.compile(r"(https?://\S+|www\.\S+|\S+@\S+\.\w+)")
_LETTER = re.compile(r"[^\W\d_]")


class TranslatorError(Exception):
    """O tradutor não conseguiu traduzir — o texto é para a pessoa."""


class _DeeplUnavailable(Exception):
    """O DeepL não traduziu (cota, chave, rede) — traduzimos com o próprio."""


def pieces(text: str) -> list[tuple[str, bool]]:
    """O texto do e-mail em pedaços: (pedaço, traduzir ou não). Função pura.

    Parágrafos separados (o tradutor mantém o sentido dentro do parágrafo),
    links e endereços intactos, linhas vazias e pedaços sem letras como estão.
    """
    out: list[tuple[str, bool]] = []
    for part in re.split(r"(\n\s*\n)", text):
        if not part.strip():
            out.append((part, False))
            continue
        for bit in _URL.split(part):
            if not bit:
                continue
            out.append((bit, bool(_LETTER.search(bit)) and not _URL.fullmatch(bit)))
    return out


def _assemble(parts: list[tuple[str, bool]], translated: list[str]) -> str:
    rest = iter(translated)
    out = []
    for text, wanted in parts:
        if not wanted:
            out.append(text)
            continue
        # O tradutor come os espaços das pontas — e eles separam o texto do link.
        lead = text[: len(text) - len(text.lstrip())]
        tail = text[len(text.rstrip()) :]
        out.append(f"{lead}{next(rest).strip()}{tail}")
    return "".join(out)


# --- DeepL ---


def _deepl_url() -> str:
    # Chaves do plano gratuito terminam em :fx e têm endereço próprio.
    host = "api-free.deepl.com" if settings.deepl_api_key.endswith(":fx") else "api.deepl.com"
    return f"https://{host}/v2/translate"


async def _deepl(texts: list[str]) -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=DEEPL_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _deepl_url(),
                headers={"Authorization": f"DeepL-Auth-Key {settings.deepl_api_key}"},
                json={"text": texts, "target_lang": DEEPL_TARGET, "preserve_formatting": True},
            )
    except httpx.HTTPError as exc:
        raise _DeeplUnavailable(f"rede: {exc}") from exc
    if response.status_code == 456:
        raise _DeeplUnavailable("acabou a cota mensal de caracteres")
    if response.status_code != 200:
        raise _DeeplUnavailable(f"resposta {response.status_code}")
    try:
        result = [item["text"] for item in response.json()["translations"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise _DeeplUnavailable("resposta incompreensível") from exc
    if len(result) != len(texts):
        raise _DeeplUnavailable("o número de traduções não bate com o de pedaços")
    return result


# --- tradutor próprio (LibreTranslate) ---


async def _post(client: httpx.AsyncClient, path: str, body: dict) -> object:
    try:
        response = await client.post(f"{settings.libretranslate_url}{path}", json=body)
    except httpx.HTTPError as exc:
        raise TranslatorError(
            "O tradutor está indisponível no momento — tente de novo em um minuto."
        ) from exc
    if response.status_code == 400:
        raise TranslatorError("O tradutor ainda não conhece este idioma.")
    if response.status_code != 200:
        raise TranslatorError("O tradutor não conseguiu traduzir este e-mail.")
    return response.json()


async def _libre(sample: str, texts: list[str]) -> list[str] | None:
    """Traduzir com o próprio tradutor. None — o e-mail já está em português."""
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        # O idioma é detectado uma vez para o e-mail inteiro: num pedaço curto
        # ("Hi!") o tradutor erra a detecção e traduz do idioma errado.
        found = await _post(client, "/detect", {"q": sample})
        language = found[0]["language"] if isinstance(found, list) and found else "auto"
        if language == TARGET:
            return None
        result = await _post(
            client,
            "/translate",
            {"q": texts, "source": language, "target": TARGET, "format": "text"},
        )
    translated = result.get("translatedText") if isinstance(result, dict) else None
    if not isinstance(translated, list) or len(translated) != len(texts):
        raise TranslatorError("O tradutor devolveu algo estranho — tente de novo.")
    return translated


def _texts(message: Message) -> tuple[str, list[tuple[str, bool]], list[str]]:
    body = message.body_text[:LETTER_CHARS]
    parts = pieces(body)
    return body, parts, [message.subject or " "] + [text for text, wanted in parts if wanted]


def deepl_chars(message: Message) -> int:
    """Quantos caracteres este e-mail gasta da cota do DeepL — o que de fato vai para lá."""
    return sum(len(text) for text in _texts(message)[2])


async def translate(message: Message, use_deepl: bool = True) -> Translation:
    """use_deepl=False — direto o tradutor próprio: a pessoa já gastou o
    seu teto diário do DeepL (veja DEEPL_MEMBER_DAILY_CHARS)."""
    body, parts, texts = _texts(message)

    translated: list[str] | None = None
    if settings.deepl_api_key and use_deepl:
        try:
            translated = await _deepl(texts)
        except _DeeplUnavailable as reason:
            log.warning(
                "o DeepL não traduziu o e-mail %s (%s) — traduzindo com o próprio",
                message.id,
                reason,
            )
    if translated is None:
        translated = await _libre(f"{message.subject}\n{body[:2000]}", texts)
        if translated is None:
            return Translation(subject=message.subject, body=message.body_text)

    text = _assemble(parts, translated[1:])
    if len(message.body_text) > LETTER_CHARS:
        text += CUT_NOTE
    return Translation(subject=translated[0].strip() or message.subject, body=text)
