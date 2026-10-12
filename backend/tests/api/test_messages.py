from app.models import User
from app.security import create_token


async def test_sorted_by_priority_then_by_date(auth_client, inbox):
    items = (await auth_client.get("/api/messages")).json()["items"]

    assert [(m["priority"], m["provider_message_id"]) for m in items] == [
        (91, "m4"),
        (91, "m1"),
        (74, "m3"),
        (12, "m2"),
        (None, "m5"),
    ], "na mesma prioridade, o mais recente em cima; os sem triagem no fim"


async def test_filter_by_category(auth_client, inbox):
    items = (await auth_client.get("/api/messages?category=payments")).json()["items"]
    assert {m["category"] for m in items} == {"payments"}


async def test_filter_by_minimum_priority(auth_client, inbox):
    items = (await auth_client.get("/api/messages?min_priority=80")).json()["items"]
    assert {m["provider_message_id"] for m in items} == {"m1", "m4"}


async def test_filter_by_mailbox(auth_client, inbox):
    box = inbox["second"]
    items = (await auth_client.get(f"/api/messages?account_id={box.id}")).json()["items"]
    assert {m["account"]["email"] for m in items} == {box.email}


async def test_message_carries_mailbox_label(auth_client, inbox):
    item = (await auth_client.get("/api/messages")).json()["items"][0]
    assert item["account"]["email"]
    assert item["account"]["service"] in {"Google", "Microsoft", "Mail.ru", "Yandex"}


async def test_paging_reports_the_total(auth_client, inbox):
    body = (await auth_client.get("/api/messages?limit=2&offset=2")).json()
    assert body["total"] == 5
    assert [m["provider_message_id"] for m in body["items"]] == ["m3", "m2"]


async def test_list_does_not_carry_full_text(auth_client, inbox):
    """A lista é para decidir, não para ler. Nela não vai o corpo do e-mail:
    vinte e cinco caixas vezes o texto de cada e-mail dá megabytes por tela."""
    item = (await auth_client.get("/api/messages")).json()["items"][0]
    assert "body_text" not in item


async def test_single_message_opens_in_full(auth_client, inbox):
    listed = (await auth_client.get("/api/messages")).json()["items"][0]

    body = (await auth_client.get(f"/api/messages/{listed['id']}")).json()

    assert body["body_text"] == "Pague até sexta"
    assert body["summary"] == "Cobrança a pagar"


async def test_missing_message_is_404(auth_client, inbox):
    assert (await auth_client.get("/api/messages/999999")).status_code == 404


async def test_message_can_be_marked_read(auth_client, inbox):
    listed = (await auth_client.get("/api/messages")).json()["items"][0]
    assert listed["is_read"] is False

    await auth_client.post(f"/api/messages/{listed['id']}/read")

    assert (await auth_client.get(f"/api/messages/{listed['id']}")).json()["is_read"] is True


async def test_both_owners_see_the_same_inbox(client, session, inbox):
    """As caixas pertencem ao negócio, não a uma pessoa.

    O dono e o desenvolvedor são dois logins separados com acesso total;
    não dá para dividir a caixa de entrada ao meio entre eles, senão metade
    dos e-mails fica invisível justamente para quem deveria tratá-los.
    """
    partner = User(email="dono@example.com", password_hash="x")
    session.add(partner)
    await session.flush()
    client.headers["Authorization"] = f"Bearer {create_token(partner)}"

    items = (await client.get("/api/messages")).json()["items"]

    assert len(items) == 5


async def test_ads_stay_out_of_the_main_list(auth_client, with_ads):
    """Propaganda não dilui a lista de decisões nem infla o total."""
    body = (await auth_client.get("/api/messages")).json()

    assert "ads" not in {m["category"] for m in body["items"]}
    assert body["total"] == 5, "propaganda não aparece nem na lista, nem no contador"


async def test_unsorted_letters_survive_hidden_ads(auth_client, with_ads):
    """A armadilha principal: esconder a propaganda sem perder o que não tem triagem.

    Em SQL, comparar com valor nulo dá «desconhecido», não «verdadeiro».
    Escreva «category != 'ads'» em vez de is_distinct_from e todos os e-mails
    que a IA ainda não triou somem de «Tudo». No banco de produção isso hoje
    são 747 de 775 e-mails: a caixa de entrada ficaria vazia com a caixa cheia.
    """
    items = (await auth_client.get("/api/messages")).json()["items"]

    assert "m5" in {m["provider_message_id"] for m in items}


async def test_ads_have_their_own_shelf(auth_client, with_ads):
    body = (await auth_client.get("/api/messages?category=ads")).json()

    assert body["total"] == 2
    assert {m["provider_message_id"] for m in body["items"]} == {"ad1", "ad2"}


async def test_unsorted_is_a_tab_of_its_own(auth_client, with_ads):
    body = (await auth_client.get("/api/messages?category=none")).json()

    assert body["total"] == 1
    assert body["items"][0]["provider_message_id"] == "m5"


async def test_ads_can_be_asked_for_explicitly(auth_client, with_ads):
    """Uma brecha para depuração: mostrar absolutamente tudo, propaganda inclusive."""
    body = (await auth_client.get("/api/messages?include_ads=true")).json()

    assert body["total"] == 7
