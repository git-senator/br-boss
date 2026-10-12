"""Os números nas abas.

O contador existe porque a decisão «onde olhar» é tomada antes do clique.
Então ele não tem o direito de mentir: uma aba vazia marcando 12 é pior
do que não ter número nenhum.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.ai.schemas import CATEGORIES, SPAM, UNSORTED
from app.models import Message


async def counts(client, query: str = "") -> dict:
    return (await client.get(f"/api/messages/counts{query}")).json()


async def test_counts_are_not_mistaken_for_a_message_id(auth_client, inbox):
    """Proteção contra ser engolido pela rota «/{message_id}».

    As rotas são testadas na ordem em que foram declaradas. Mova este endpoint
    para baixo da rota que lê o id do e-mail e «counts» vai parar lá como id,
    e a caixa de entrada recebe um erro de validação confuso em vez dos números.
    """
    response = await auth_client.get("/api/messages/counts")

    assert response.status_code == 200


async def test_counts_need_a_login(client):
    assert (await client.get("/api/messages/counts")).status_code == 401


async def test_every_category_has_a_key_even_when_empty(auth_client, inbox):
    """Zero vem como zero, e não como chave ausente: senão a interface
    precisa distinguir «não há e-mails» de «essa aba não existe»."""
    body = await counts(auth_client)

    assert set(body["categories"]) == {*CATEGORIES, UNSORTED, SPAM}
    assert body["categories"]["legal"] == {"total": 0, "unread": 0}


async def test_numbers_match_the_inbox(auth_client, inbox):
    body = await counts(auth_client)

    assert body["categories"]["payments"]["total"] == 2
    assert body["categories"]["urgent"]["total"] == 1
    assert body["categories"]["low"]["total"] == 1
    assert body["all"]["total"] == 5


async def test_unsorted_letters_are_counted_honestly(auth_client, inbox):
    """E-mail sem categoria tem que aparecer nos números.

    Enquanto a IA não fez a triagem, todos os e-mails ficam justamente aqui.
    Não mostrá-los é mostrar zeros com a caixa cheia.
    """
    body = await counts(auth_client)

    assert body["categories"][UNSORTED]["total"] == 1


async def test_reading_a_letter_moves_only_the_unread_number(auth_client, inbox, session):
    letter = await session.scalar(select(Message).where(Message.provider_message_id == "m4"))

    before = await counts(auth_client)
    await auth_client.post(f"/api/messages/{letter.id}/read")
    after = await counts(auth_client)

    assert before["categories"]["urgent"] == {"total": 1, "unread": 1}
    assert after["categories"]["urgent"] == {"total": 1, "unread": 0}
    assert after["all"]["total"] == before["all"]["total"]


async def test_counts_follow_the_chosen_mailbox(auth_client, inbox):
    first = await counts(auth_client, f"?account_id={inbox['first'].id}")
    second = await counts(auth_client, f"?account_id={inbox['second'].id}")

    assert first["all"]["total"] == 2
    assert second["all"]["total"] == 3
    assert first["categories"]["urgent"]["total"] == 0, "o urgente está na segunda caixa"


async def test_counts_do_not_depend_on_the_open_tab(auth_client, inbox):
    """Senão todas as abas, menos a aberta, mostrariam zero, e a pessoa
    deixaria de ver onde há algo esperando por ela."""
    plain = await counts(auth_client)
    with_tab = await counts(auth_client, "?category=payments")

    assert plain == with_tab


async def test_ads_are_counted_apart(auth_client, with_ads):
    body = await counts(auth_client)

    assert body["categories"]["ads"]["total"] == 2
    assert body["all"]["total"] == 5, "«Tudo» não conta propaganda, nem a mostra"


@pytest.mark.parametrize("category", [*CATEGORIES, UNSORTED])
async def test_every_number_matches_its_own_list(auth_client, with_ads, category):
    """O teste mais valioso do conjunto.

    «Tudo» é definido em dois lugares: no filtro dos e-mails e na agregação
    dos contadores. Se divergirem, será em silêncio: a lista mostra uma coisa,
    o número no botão outra, e só uma pessoa vai perceber. Aqui cada número
    é conferido com o tamanho da mesma lista que abre ao clicar.
    """
    shown = (await auth_client.get(f"/api/messages?category={category}")).json()
    counted = (await counts(auth_client))["categories"][category]

    assert counted["total"] == shown["total"]


async def test_the_total_matches_the_main_list(auth_client, with_ads):
    shown = (await auth_client.get("/api/messages")).json()
    counted = await counts(auth_client)

    assert counted["all"]["total"] == shown["total"]


async def test_a_rule_may_write_a_category_nobody_knows(auth_client, session, inbox):
    """A regra do usuário grava qualquer texto na categoria, sem validação.

    Esse e-mail não tem aba própria, mas não pode sumir do total: na lista
    ele aparece. Senão a soma das abas não bate com «Total de e-mails»
    e a confiança nos números acaba.
    """
    letter = await session.scalar(select(Message).where(Message.provider_message_id == "m5"))
    letter.category = "meu-projeto"
    await session.flush()

    body = await counts(auth_client)

    assert "meu-projeto" not in body["categories"]
    assert body["all"]["total"] == 5


async def test_spam_is_counted_apart_from_everything(auth_client, session, inbox):
    """E-mail do spam não pode entrar nem em «Tudo», nem na sua categoria.

    Um e-mail importante que caiu no spam o sistema tem que mostrar, mas em
    uma prateleira à parte, não misturado com as demais decisões.
    """
    session.add(
        Message(
            account_id=inbox["first"].id,
            provider_message_id="spam:1",
            sender="cobranca@fornecedor.com.br",
            subject="Cobrança vinda do spam",
            body_text="Pague",
            summary="Cobrança",
            category="payments",
            priority=90,
            sent_at=datetime(2026, 9, 1, tzinfo=UTC),
            folder="spam",
        )
    )
    await session.flush()

    body = await counts(auth_client)

    assert body["categories"][SPAM]["total"] == 1
    assert body["categories"]["payments"]["total"] == 2, "em «Pagamentos» só o que não é spam"
    assert body["all"]["total"] == 5, "«Tudo» não conta spam"


async def test_the_spam_shelf_shows_what_is_in_it(auth_client, session, inbox):
    session.add(
        Message(
            account_id=inbox["first"].id,
            provider_message_id="spam:2",
            sender="promo@loja.com.br",
            subject="Propaganda vinda do spam",
            body_text="desconto",
            category="ads",
            priority=3,
            sent_at=datetime(2026, 9, 1, tzinfo=UTC),
            folder="spam",
        )
    )
    await session.flush()

    shown = (await auth_client.get(f"/api/messages?category={SPAM}")).json()

    assert shown["total"] == 1, "dentro do spam mostramos tudo, propaganda inclusive"
    assert shown["items"][0]["folder"] == "spam"
