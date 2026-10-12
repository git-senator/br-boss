"""Dinheiro e prazos: da triagem do e-mail até a linha da lista.

Antes a triagem extraía o valor e o prazo e jogava fora: não havia onde
guardar no banco. Estes testes vigiam o caminho inteiro: se qualquer elo
sumir, a tela «Dinheiro e prazos» fica vazia com as caixas cheias.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Message


@pytest.fixture
async def bills(session, inbox):
    """Três cobranças com prazos diferentes e um pagamento sem prazo."""
    letters = [
        ("b1", date(2026, 8, 1), Decimal("1200.50"), "BRL"),
        ("b2", date(2026, 9, 30), Decimal("47000.00"), "BRL"),
        ("b3", date(2026, 9, 15), Decimal("300.00"), "USD"),
        ("b4", None, Decimal("99.99"), "EUR"),
    ]
    for msg_id, deadline, amount, currency in letters:
        session.add(
            Message(
                account_id=inbox["first"].id,
                provider_message_id=msg_id,
                sender="cobranca@fornecedor.com.br",
                subject=f"Boleto {msg_id}",
                body_text="Pague até sexta",
                summary="Cobrança a pagar",
                category="payments",
                priority=70,
                sent_at=datetime(2026, 8, 20, tzinfo=UTC),
                deadline=deadline,
                amount=amount,
                currency=currency,
                action_required=True,
            )
        )
    await session.flush()
    return inbox


async def test_money_reaches_the_list(auth_client, bills):
    items = (await auth_client.get("/api/messages?category=payments")).json()["items"]
    bill = next(m for m in items if m["provider_message_id"] == "b2")

    assert bill["amount"] == "47000.00"
    assert bill["currency"] == "BRL"
    assert bill["deadline"] == "2026-09-30"
    assert bill["action_required"] is True


async def test_amount_travels_as_text_not_as_a_fraction(auth_client, bills):
    """Dinheiro não pode trafegar como número de ponto flutuante: ele
    arredonda calado, e os centavos da cobrança deixam de bater."""
    items = (await auth_client.get("/api/messages?category=payments")).json()["items"]
    bill = next(m for m in items if m["provider_message_id"] == "b1")

    assert bill["amount"] == "1200.50"
    assert isinstance(bill["amount"], str)


async def test_letters_without_money_say_so_plainly(auth_client, bills):
    items = (await auth_client.get("/api/messages?category=urgent")).json()["items"]

    assert items[0]["amount"] is None
    assert items[0]["deadline"] is None
    assert items[0]["action_required"] is False


async def test_money_screen_shows_only_what_costs(auth_client, bills):
    body = (await auth_client.get("/api/messages?with_money=true")).json()

    assert body["total"] == 4, "quatro e-mails com cobrança; o resto não conta"
    assert {m["provider_message_id"] for m in body["items"]} == {"b1", "b2", "b3", "b4"}


async def test_overdue_comes_first(auth_client, bills):
    """A regra principal da tela: o vencido vai em cima, mesmo que a
    prioridade dele seja média. Sem prazo vai lá no fim, senão o prazo
    vazio subiria para o topo e empurraria as dívidas de verdade."""
    items = (await auth_client.get("/api/messages?with_money=true&by_deadline=true")).json()[
        "items"
    ]

    assert [m["provider_message_id"] for m in items] == ["b1", "b3", "b2", "b4"]


async def test_the_main_list_still_goes_by_importance(auth_client, bills):
    """A tela de dinheiro muda a ordem só dentro dela. A caixa de entrada
    continua sendo caixa de entrada: em cima, o que custa mais caro adiar."""
    items = (await auth_client.get("/api/messages")).json()["items"]
    priorities = [m["priority"] for m in items if m["priority"] is not None]

    assert priorities == sorted(priorities, reverse=True)


async def test_a_letter_keeps_its_money_after_being_read(auth_client, bills, session):
    letter = await session.scalar(select(Message).where(Message.provider_message_id == "b2"))
    await auth_client.post(f"/api/messages/{letter.id}/read")

    full = (await auth_client.get(f"/api/messages/{letter.id}")).json()
    assert full["amount"] == "47000.00"
    assert full["deadline"] == "2026-09-30"
