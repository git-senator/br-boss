"""Triagem de e-mails com modelo local via Ollama.

Plano B para enquanto não há chave da Anthropic, e para quando o e-mail
não pode sair da máquina de jeito nenhum.

Sendo honesto sobre a diferença: o modelo local de 3 bilhões de parâmetros
ordena por prioridade razoavelmente bem — uma intimação da Receita sobe
para o topo, propaganda marcada «urgente» fica embaixo. Já o resumo do
e-mail sai ruim: mistura idiomas e repete trechos das instruções em vez do
conteúdo. Serve para «ver como tudo funciona», não para tomar decisões.

O Ollama não roda no contêiner, e sim na máquina ao lado, por isso o
endereço vem da configuração: no servidor será outro endereço, ou outra
opção de vez.
"""

import json

import httpx

from app.config import settings

# O modelo local roda na CPU e responde em segundos, não em milissegundos.
# Timeout generoso: melhor esperar do que perder o e-mail.
TIMEOUT_SECONDS = 180


class LocalModelError(Exception):
    """O modelo local não respondeu ou respondeu algo incompreensível."""


async def structured_call_local(
    *,
    max_tokens: int,
    system: str,
    user_text: str,
    schema: dict,
) -> dict:
    """Perguntar ao modelo local e receber a resposta estritamente no esquema.

    O Ollama aceita o mesmo esquema da Anthropic e garante sozinho que a
    resposta o respeite. Por isso a leitura da resposta aqui é tão simples
    quanto na opção principal.
    """
    payload = {
        "model": settings.ollama_model,
        "stream": False,
        "format": schema,
        "options": {"num_predict": max_tokens},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{settings.ollama_url.rstrip('/')}/api/chat", json=payload
            )
    except httpx.HTTPError as exc:
        raise LocalModelError(f"modelo local indisponível: {exc}") from exc

    if response.status_code != 200:
        raise LocalModelError(f"o modelo local respondeu com erro: {response.status_code}")

    text = response.json().get("message", {}).get("content")
    if not text:
        raise LocalModelError("o modelo local devolveu uma resposta vazia")

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LocalModelError("a resposta do modelo local não pôde ser lida como JSON") from exc
