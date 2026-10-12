import json
from decimal import Decimal

import pytest

from app.ai.provider import AIError
from app.ai.schemas import CATEGORIES, TRIAGE_SCHEMA
from app.ai.triage import TriageResult, triage
from app.models import Message


class FakeBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class FakeResponse:
    def __init__(self, payload: dict | str, stop_reason: str = "end_turn") -> None:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        self.content = [FakeBlock(text)]
        self.stop_reason = stop_reason


class FakeMessages:
    def __init__(self) -> None:
        self.response = FakeResponse({})
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FakeClient:
    def __init__(self) -> None:
        self.messages = FakeMessages()


@pytest.fixture
def model(monkeypatch) -> FakeClient:
    client = FakeClient()
    monkeypatch.setattr("app.ai.provider._client", client)
    return client


def letter(subject: str = "Boleto", body: str = "Pague até sexta.") -> Message:
    return Message(
        sender="ana@fornecedor.com.br",
        sender_name="Ana Silva",
        subject=subject,
        body_text=body,
    )


def test_schema_is_strict():
    assert TRIAGE_SCHEMA["additionalProperties"] is False
    assert "category" in TRIAGE_SCHEMA["required"]
    assert TRIAGE_SCHEMA["properties"]["priority"]["type"] == "integer"
    assert TRIAGE_SCHEMA["properties"]["category"]["enum"] == CATEGORIES


async def test_maps_full_answer(model):
    model.messages.response = FakeResponse(
        {
            "category": "payments",
            "priority": 88,
            "summary": "Boleto de R$ 56.315,00 com vencimento em 18 de agosto",
            "action_required": True,
            "deadline": "2026-08-18",
            "amount": "56315.00",
            "currency": "BRL",
        }
    )
    # O valor está no próprio e-mail — senão a checagem de números
    # inventados o descartaria, e com razão.
    result = await triage(letter(body="Boleto de R$ 56.315,00 até 18/08"))
    assert result == TriageResult(
        category="payments",
        priority=88,
        summary="Boleto de R$ 56.315,00 com vencimento em 18 de agosto",
        action_required=True,
        deadline=__import__("datetime").date(2026, 8, 18),
        amount=Decimal("56315.00"),
        currency="BRL",
    )


async def test_minimal_answer_is_enough(model):
    model.messages.response = FakeResponse(
        {"category": "low", "priority": 5, "summary": "Publicidade", "action_required": False}
    )
    result = await triage(letter())
    assert result.deadline is None
    assert result.amount is None
    assert result.currency is None


async def test_amount_with_comma_is_understood(model):
    model.messages.response = FakeResponse(
        {
            "category": "payments",
            "priority": 70,
            "summary": "s",
            "action_required": True,
            "amount": "1 234,56",
            "currency": "BRL",
        }
    )
    body = "Total: R$ 1.234,56"
    assert (await triage(letter(body=body))).amount == Decimal("1234.56")


async def test_unparseable_deadline_becomes_none_not_a_crash(model):
    model.messages.response = FakeResponse(
        {
            "category": "urgent",
            "priority": 95,
            "summary": "s",
            "action_required": True,
            "deadline": "até o fim da semana",
        }
    )
    assert (await triage(letter())).deadline is None


@pytest.mark.parametrize("priority", [140, -5, "alta"])
async def test_priority_out_of_range_is_rejected(model, priority):
    model.messages.response = FakeResponse(
        {"category": "low", "priority": priority, "summary": "s", "action_required": False}
    )
    with pytest.raises(AIError, match="importância"):
        await triage(letter())


async def test_unknown_category_is_rejected(model):
    model.messages.response = FakeResponse(
        {"category": "lixo", "priority": 10, "summary": "s", "action_required": False}
    )
    with pytest.raises(AIError, match="categoria"):
        await triage(letter())


async def test_refusal_is_reported_clearly(model):
    model.messages.response = FakeResponse({}, stop_reason="refusal")
    with pytest.raises(AIError) as caught:
        await triage(letter())
    assert str(caught.value), "a recusa vem com uma explicação"


async def test_broken_json_is_reported_clearly(model):
    model.messages.response = FakeResponse("isto não é JSON")
    with pytest.raises(AIError, match="JSON"):
        await triage(letter())


async def test_uses_the_cheap_model_and_the_schema(model):
    model.messages.response = FakeResponse(
        {"category": "low", "priority": 5, "summary": "s", "action_required": False}
    )
    await triage(letter())
    call = model.messages.calls[0]
    assert call["model"] == "claude-haiku-4-5"
    assert call["output_config"]["format"]["schema"] is TRIAGE_SCHEMA
    assert "temperature" not in call, "neste modelo não se passa temperature"


async def test_long_body_is_cut_before_sending(model):
    model.messages.response = FakeResponse(
        {"category": "low", "priority": 5, "summary": "s", "action_required": False}
    )
    await triage(letter(body="ç" * 100_000))
    assert len(model.messages.calls[0]["messages"][0]["content"]) < 25_000


async def test_sender_and_subject_reach_the_model(model):
    model.messages.response = FakeResponse(
        {"category": "low", "priority": 5, "summary": "s", "action_required": False}
    )
    await triage(letter(subject="Cobrança"))
    sent = model.messages.calls[0]["messages"][0]["content"]
    assert "ana@fornecedor.com.br" in sent
    assert "Cobrança" in sent


async def test_ads_is_a_category_of_its_own(model):
    """Publicidade separada de "baixa prioridade": não é renomeação, é uma prateleira nova.

    Conferimos a cadeia inteira — da lista que vai ao modelo no esquema
    até a triagem pronta. Se esquecerem de colocar "ads" em CATEGORIES,
    a resposta do modelo esbarra na checagem de categoria, e os e-mails
    de publicidade se acumulam em silêncio sem triagem.
    """
    assert "ads" in CATEGORIES
    assert "low" in CATEGORIES

    model.messages.response = FakeResponse(
        {
            "category": "ads",
            "priority": 5,
            "summary": "Newsletter com descontos",
            "action_required": False,
        }
    )
    result = await triage(letter())
    assert result.category == "ads"


async def test_security_is_a_shelf_of_its_own(model):
    """E-mails sobre acesso à conta vão para a sua própria prateleira.

    Em e-mail real, alertas idênticos do Google se espalharam por três
    categorias diferentes — "Bancos", "Urgente" e "Outros". É exatamente
    para isso que a categoria existe.
    """
    assert "security" in CATEGORIES

    model.messages.response = FakeResponse(
        {
            "category": "security",
            "priority": 45,
            "summary": "Login na conta a partir de um novo dispositivo",
            "action_required": False,
        }
    )
    result = await triage(letter())
    assert result.category == "security"


def test_the_prompt_tells_security_from_alarm():
    """O prompt precisa separar a linguagem dos avisos de um problema real.
    Sem isso, "proteja sua conta" volta para "Urgente" com importância 95."""
    from app.ai.triage import SYSTEM

    assert "security" in SYSTEM
    assert "alerta de segurança" in SYSTEM.lower()


def test_the_summary_is_asked_in_brazilian_portuguese():
    """A essência é lida por um usuário brasileiro, seja qual for o idioma do e-mail."""
    from app.ai.triage import SYSTEM

    assert "sempre em português do Brasil" in SYSTEM
    assert "português do Brasil" in TRIAGE_SCHEMA["properties"]["summary"]["description"]


async def test_an_amount_that_is_not_in_the_letter_is_dropped(model):
    """Um valor inventado não pode chegar à tela de pagamentos.

    Visto em e-mail real: um modelo gratuito transformou uma newsletter
    comum sobre currículos numa intimação judicial. A categoria não dá
    para conferir, o número dá — e é a coisa mais cara que o modelo pode
    inventar.
    """
    model.messages.response = FakeResponse(
        {
            "category": "payments",
            "priority": 80,
            "summary": "Fatura",
            "action_required": True,
            "amount": "99999.00",
            "currency": "BRL",
        }
    )
    result = await triage(letter(body="Um e-mail comum sem nenhum número"))

    assert result.amount is None
    assert result.currency is None, "moeda sem valor não faz sentido"
    assert result.category == "payments", "o resto da triagem continua valendo"


@pytest.mark.parametrize(
    "written",
    ["R$ 56.315,00", "56 315", "56315", "56,315.00", "valor 56 315 reais"],
)
async def test_a_real_amount_is_kept_however_it_is_written(model, written):
    """No Brasil o ponto separa os milhares; em outros lugares, o espaço.
    A checagem não pode descartar faturas reais por causa do formato."""
    model.messages.response = FakeResponse(
        {
            "category": "payments",
            "priority": 80,
            "summary": "Fatura",
            "action_required": True,
            "amount": "56315.00",
            "currency": "BRL",
        }
    )
    result = await triage(letter(body=f"Pague até sexta: {written}"))

    assert result.amount == Decimal("56315.00")
    assert result.currency == "BRL"
