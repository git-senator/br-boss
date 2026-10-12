"""Busca em todos os e-mails."""

from datetime import UTC, datetime

import pytest

from app.models import Message


@pytest.fixture
async def mail(session, inbox):
    """E-mails que só se distinguem pelas palavras de dentro."""
    letters = [
        ("s1", "cobranca@condominio.com.br", "Condomínio", "Boleto de outubro", "Valor R$ 1.284,50", "payments", "inbox"),
        ("s2", "joao@petro.ae", "João Silva", "Crude oil 120 KT", "Refinery confirmed the boleto", "business", "inbox"),
        ("s3", "promo@loja.com.br", "Loja", "Boletos com desconto", "50% off", "ads", "inbox"),
        ("s4", "x@spam.example", "", "Boleto urgente", "clique aqui", "low", "spam"),
        ("s5", "ana@x.com", "Ana", "Desconto de 100%", "Promo_da semana", "ads", "inbox"),
    ]
    for day, (msg_id, sender, name, subject, body, category, folder) in enumerate(letters, start=1):
        session.add(
            Message(
                account_id=inbox["first"].id,
                provider_message_id=msg_id,
                sender=sender,
                sender_name=name,
                subject=subject,
                body_text=body,
                category=category,
                priority=50,
                folder=folder,
                sent_at=datetime(2026, 9, day, tzinfo=UTC),
            )
        )
    await session.flush()
    return inbox


async def ids(client, query: str) -> list[str]:
    body = (await client.get("/api/messages", params={"q": query})).json()
    return [m["provider_message_id"] for m in body["items"]]


async def test_finds_by_a_piece_of_a_word_in_any_case(auth_client, mail):
    """«boleto» encontra «Boleto», «Boletos» e a palavra no meio do texto."""
    assert set(await ids(auth_client, "BOLETO")) == {"s1", "s2", "s3", "s4"}


async def test_every_word_must_be_found(auth_client, mail):
    assert await ids(auth_client, "boleto refinery") == ["s2"]


async def test_finds_by_sender_name_and_address(auth_client, mail):
    assert await ids(auth_client, "joão") == ["s2"]
    assert await ids(auth_client, "condominio.com") == ["s1"]


async def test_search_reaches_ads_and_spam(auth_client, mail):
    """A lista comum esconde propaganda e spam. A busca, não: a pessoa
    procura um e-mail específico, e «não encontrado» seria mentira."""
    found = await ids(auth_client, "boleto")
    assert "s3" in found, "propaganda"
    assert "s4" in found, "spam"


async def test_freshest_first(auth_client, mail):
    assert await ids(auth_client, "boleto") == ["s4", "s3", "s2", "s1"]


async def test_percent_and_underscore_are_letters(auth_client, mail):
    """«100%» é texto, não o padrão «100 seguido de qualquer coisa»."""
    assert await ids(auth_client, "100%") == ["s5"]
    assert await ids(auth_client, "Promo_da") == ["s5"]
    assert await ids(auth_client, "_") == ["s5"]


async def test_search_inside_one_tab(auth_client, mail):
    body = (await auth_client.get("/api/messages", params={"q": "boleto", "category": "payments"})).json()
    assert [m["provider_message_id"] for m in body["items"]] == ["s1"]


async def test_search_inside_one_mailbox(auth_client, mail):
    box = mail["second"].id
    body = (await auth_client.get("/api/messages", params={"q": "boleto", "account_id": box})).json()
    assert body["items"] == []


async def test_blank_query_is_the_ordinary_inbox(auth_client, mail):
    plain = (await auth_client.get("/api/messages")).json()
    blank = (await auth_client.get("/api/messages", params={"q": "   "})).json()
    assert blank == plain


async def test_total_counts_matches_not_the_page(auth_client, mail):
    body = (await auth_client.get("/api/messages", params={"q": "boleto", "limit": 2})).json()
    assert body["total"] == 4
    assert len(body["items"]) == 2
