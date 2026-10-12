import time
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.ai.provider import AIError
from app.ai.triage import TriageResult
from app.mail.base import RawMessage
from app.mail.errors import MailAuthError
from app.models import Account, Message, Rule
from app.worker.tasks import classify_pending, sync_account, sync_all


def raw(msg_id: str, subject: str = "Boleto") -> RawMessage:
    return RawMessage(
        provider_message_id=msg_id,
        sender="ana@fornecedor.com.br",
        subject=subject,
        body_text="Pague até sexta",
        sent_at=datetime(2026, 8, 17, tzinfo=UTC),
    )


class FakeSource:
    def __init__(self, messages, cursor="10", error=None):
        self.messages = messages
        self.cursor = cursor
        self.error = error

    async def verify(self):
        return None

    async def fetch_since(self, cursor):
        if self.error:
            raise self.error
        return self.messages, self.cursor


@pytest.fixture
def mail(monkeypatch):
    sources: dict[str, FakeSource] = {}

    def register(email: str, source: FakeSource) -> None:
        sources[email] = source

    monkeypatch.setattr("app.worker.tasks.get_source", lambda account: sources[account.email])
    return register


@pytest.fixture
def ai(monkeypatch):
    state = {"result": TriageResult(category="payments", priority=88, summary="Boleto"), "calls": 0}

    async def fake_triage(message):
        state["calls"] += 1
        if isinstance(state["result"], Exception):
            raise state["result"]
        return state["result"]

    monkeypatch.setattr("app.worker.tasks.triage", fake_triage)
    return state


async def messages_of(session, account) -> list[Message]:
    from sqlalchemy import select

    return list(
        await session.scalars(
            select(Message).where(Message.account_id == account.id).order_by(Message.id)
        )
    )


async def test_stores_classifies_and_advances_cursor(session, account, mail, ai):
    mail(account.email, FakeSource([raw("m1"), raw("m2")], cursor="99"))

    added = await sync_account(session, account)

    assert added == 2
    assert account.cursor == "99"
    assert account.last_synced_at is not None
    assert account.last_error is None
    stored = await messages_of(session, account)
    assert [m.category for m in stored] == ["payments", "payments"]
    assert [m.priority for m in stored] == [88, 88]


async def test_second_run_adds_nothing_new(session, account, mail, ai):
    mail(account.email, FakeSource([raw("m1")], cursor="1"))
    await sync_account(session, account)
    assert await sync_account(session, account) == 0


async def test_user_rules_are_applied_on_top_of_ai(session, account, user, mail, ai):
    session.add(
        Rule(
            user_id=user.id,
            condition_kind="sender_contains",
            condition_value="fornecedor",
            action_kind="set_min_priority",
            action_value="95",
        )
    )
    await session.flush()
    mail(account.email, FakeSource([raw("m1")]))

    await sync_account(session, account)

    [stored] = await messages_of(session, account)
    assert stored.priority == 95


async def test_message_survives_when_ai_fails(session, account, mail, ai):
    mail(account.email, FakeSource([raw("m1")]))
    ai["result"] = AIError("modelo indisponível")

    added = await sync_account(session, account)

    assert added == 1, "o e-mail tem que ser salvo mesmo sem triagem"
    [stored] = await messages_of(session, account)
    assert stored.category is None
    assert stored.priority is None
    assert account.cursor == "10", "o cursor anda — o e-mail já foi baixado"


async def test_mail_error_is_recorded_and_cursor_stays(session, account, mail, ai):
    mail(account.email, FakeSource([], error=MailAuthError("Senha incorreta")))
    account.cursor = "5"

    with pytest.raises(MailAuthError):
        await sync_account(session, account)

    assert account.cursor == "5"
    assert "Senha incorreta" in account.last_error


async def test_error_is_cleared_after_successful_run(session, account, mail, ai):
    account.last_error = "erro antigo"
    mail(account.email, FakeSource([raw("m1")]))
    await sync_account(session, account)
    assert account.last_error is None


async def test_broken_mailbox_does_not_stop_the_others(session, session_factory, user, mail, ai):
    from app.crypto import encrypt_secret

    broken = Account(user_id=user.id, email="broken@bol.com", secret_ciphertext=encrypt_secret("p"))
    healthy = Account(
        user_id=user.id, email="healthy@bol.com", secret_ciphertext=encrypt_secret("p")
    )
    session.add_all([broken, healthy])
    await session.commit()

    mail(broken.email, FakeSource([], error=MailAuthError("Senha incorreta")))
    mail(healthy.email, FakeSource([raw("m1")]))

    results = await sync_all(session_factory)

    assert results[broken.id] == -1
    assert results[healthy.id] == 1


async def test_every_mailbox_gets_its_own_connection(session, session_factory, user, mail, ai):
    """Vinte e cinco caixas são consultadas em paralelo — com uma sessão de banco
    compartilhada isto caía com 'another operation is in progress'."""
    from app.crypto import encrypt_secret

    boxes = [
        Account(user_id=user.id, email=f"box{i}@uol.com.br", secret_ciphertext=encrypt_secret("p"))
        for i in range(12)
    ]
    session.add_all(boxes)
    await session.commit()
    for box in boxes:
        mail(box.email, FakeSource([raw("m1"), raw("m2")]))

    results = await sync_all(session_factory)

    assert len(results) == 12
    assert all(count == 2 for count in results.values())


async def test_disabled_mailbox_is_skipped(session, session_factory, account, mail, ai):
    account.is_active = False
    await session.commit()
    assert await sync_all(session_factory) == {}


async def test_unparsed_letters_are_picked_up_next_round(
    session, session_factory, account, mail, ai
):
    """O modelo estava indisponível — o e-mail foi salvo sem categoria.
    Sem a recuperação ele ficaria sem triagem para sempre."""
    from app.worker.tasks import classify_pending

    mail(account.email, FakeSource([raw("m1"), raw("m2")]))
    ai["result"] = AIError("modelo indisponível")
    await sync_account(session, account)
    await session.commit()
    assert [m.category for m in await messages_of(session, account)] == [None, None]

    ai["result"] = TriageResult(category="payments", priority=88, summary="Boleto")
    done = await classify_pending(session_factory)

    assert done == 2
    for message in await messages_of(session, account):
        await session.refresh(message)
        assert message.category == "payments"


async def test_already_parsed_letters_are_not_paid_for_twice(
    session, session_factory, account, mail, ai
):
    from app.worker.tasks import classify_pending

    mail(account.email, FakeSource([raw("m1")]))
    await sync_account(session, account)
    await session.commit()
    calls_before = ai["calls"]

    assert await classify_pending(session_factory) == 0
    assert ai["calls"] == calls_before, "a triagem se repetiu e foi paga de novo"


async def test_pending_pass_takes_a_portion_not_everything(
    session, session_factory, account, mail, ai
):
    from app.worker.tasks import classify_pending

    mail(account.email, FakeSource([raw(f"m{i}") for i in range(10)]))
    ai["result"] = AIError("modelo indisponível")
    await sync_account(session, account)
    await session.commit()

    ai["result"] = TriageResult(category="low", priority=5, summary="Propaganda")
    assert await classify_pending(session_factory, limit=4) == 4


async def test_letters_survive_when_the_model_layer_blows_up_unexpectedly(
    session, account, mail, ai
):
    """Pego no e-mail real: sem chave, a biblioteca da Anthropic lança
    TypeError, e não o nosso erro. Só pegávamos o nosso — e a rodada inteira
    caía: e-mails não eram salvos, o cursor não andava, a caixa ficava muda.
    A promessa «o e-mail não se perde» tem que valer diante de qualquer problema."""
    mail(account.email, FakeSource([raw("m1"), raw("m2")]))
    ai["result"] = TypeError("Could not resolve authentication method")

    added = await sync_account(session, account)

    assert added == 2, "e-mails sumiram por causa de uma falha na triagem"
    assert account.cursor == "10", "o cursor não andou — os e-mails vão chegar de novo"
    assert [m.category for m in await messages_of(session, account)] == [None, None]


async def test_missing_key_does_not_flood_the_log(session, account, mail, ai, caplog):
    """Sem chave é o estado normal enquanto o dono não a fornece. Centenas
    de e-mails não podem gerar centenas de linhas iguais no log."""
    import logging

    from app.ai.provider import AINotConfigured

    mail(account.email, FakeSource([raw(f"m{i}") for i in range(5)]))
    ai["result"] = AINotConfigured("chave não definida")

    with caplog.at_level(logging.WARNING):
        added = await sync_account(session, account)

    assert added == 5, "os e-mails são salvos de qualquer jeito"
    assert not caplog.records, "log poluído, embora seja um estado esperado"


async def test_old_letters_are_not_parsed(session, session_factory, account, mail, ai, monkeypatch):
    """A caixa traz anos de correspondência. Triar tudo isso é tempo e
    limites do modelo jogados fora: e-mail antigo não pede decisões."""
    from app.config import settings
    from app.worker.tasks import classify_pending

    monkeypatch.setattr(settings, "classify_since", "2026-09-01")

    old = raw("antigo")
    old.sent_at = datetime(2026, 8, 15, tzinfo=UTC)
    fresh = raw("recente")
    fresh.sent_at = datetime(2026, 9, 5, tzinfo=UTC)
    mail(account.email, FakeSource([old, fresh]))

    await sync_account(session, account)
    await session.commit()

    stored = {m.provider_message_id: m for m in await messages_of(session, account)}
    assert stored["antigo"].category is None, "e-mail antigo triado à toa"
    assert stored["recente"].category == "payments"

    assert await classify_pending(session_factory) == 0, "e-mail antigo rodando em círculos"


async def test_without_the_date_everything_is_parsed(session, account, mail, ai, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "classify_since", "")
    old = raw("antigo")
    old.sent_at = datetime(2020, 1, 1, tzinfo=UTC)
    mail(account.email, FakeSource([old]))

    await sync_account(session, account)

    [stored] = await messages_of(session, account)
    assert stored.category == "payments"


async def test_exhausted_daily_quota_stops_the_hammering(
    session, session_factory, account, mail, ai
):
    """A cota diária acabou — o worker tem que ficar quieto até a renovação.
    Senão ele bate a cada minuto com centenas de requisições na porta fechada,
    e a chave acaba bloqueada de vez."""
    from app.ai.provider import AIQuotaExhausted
    from app.worker import tasks

    tasks._paused.clear()
    mail(account.email, FakeSource([raw(f"m{i}") for i in range(20)]))
    ai["result"] = AIQuotaExhausted("a cota acabou", reset_at=time.time() + 3600)

    await sync_account(session, account)
    await session.commit()

    assert tasks.classification_paused(), "sem pausa — o worker vai continuar insistindo"
    calls_after_sync = ai["calls"]
    assert calls_after_sync <= 2, f"continuaram perguntando depois da recusa: {calls_after_sync}"

    assert await tasks.classify_pending(session_factory) == 0
    assert ai["calls"] == calls_after_sync, "a recuperação bateu na porta fechada"

    tasks._paused.clear()


async def test_pause_lifts_after_the_reset(session, session_factory, account, mail, ai):
    from app.worker import tasks

    tasks._paused.clear()
    mail(account.email, FakeSource([raw("m1")]))
    await sync_account(session, account)
    await session.commit()

    assert not tasks.classification_paused()


async def test_money_and_deadline_are_kept_not_thrown_away(session, account, mail, ai):
    """A triagem extraía valor e prazo desde o início — e eles se perdiam,
    porque não havia lugar na tabela. Este teste vigia exatamente esse
    trecho: da resposta do modelo até a gravação no banco."""
    from datetime import date
    from decimal import Decimal

    ai["result"] = TriageResult(
        category="payments",
        priority=88,
        summary="Boleto de R$ 56.315 com vencimento em 18 de agosto",
        action_required=True,
        deadline=date(2026, 8, 18),
        amount=Decimal("56315.00"),
        currency="BRL",
    )
    mail(account.email, FakeSource([raw("m1")]))

    await sync_account(session, account)

    saved = await session.scalar(
        select(Message).where(Message.provider_message_id == "m1")
    )
    assert saved.amount == Decimal("56315.00")
    assert saved.currency == "BRL"
    assert saved.deadline == date(2026, 8, 18)
    assert saved.action_required is True


async def test_pause_survives_a_restart(session_factory, session, account, mail, ai, monkeypatch):
    """A pausa tem que sobreviver a um reinício.

    Enquanto ela vivia só na memória, cada rebuild a apagava, e o worker
    voltava a bater na porta fechada. Numa noite foram embora assim todas as
    cinquenta requisições gratuitas do dia — só em recusas.
    """
    from app.ai.provider import AIQuotaExhausted
    from app.worker import tasks

    ai["result"] = AIQuotaExhausted("a cota acabou", reset_at=time.time() + 3600)
    mail(account.email, FakeSource([raw("m1")]))
    await sync_account(session, account)
    assert tasks.classification_paused(), "pausa definida"

    # Reinício: a memória do processo está limpa, o banco não.
    monkeypatch.setattr(tasks, "_paused", {})
    assert not tasks.classification_paused()

    assert await classify_pending(session_factory) == 0
    assert tasks.classification_paused(), "a pausa foi lembrada a partir do banco"
    assert ai["calls"] == 1, "nenhuma chamada extra ao modelo depois do reinício"


async def test_an_empty_base_does_not_cancel_a_fresh_pause(session_factory, monkeypatch):
    """O outro lado: lembrar a pausa pode, encurtá-la não.

    Senão um banco vazio derrubaria a pausa definida um segundo atrás,
    e todo o sentido se perderia.
    """
    from app.worker import tasks

    monkeypatch.setattr(tasks, "_paused", {"": time.time() + 600})

    assert await classify_pending(session_factory) == 0
    assert tasks.classification_paused()


async def test_first_visit_stores_everything_before_sorting(session, account, mail, ai):
    """A primeira visita à caixa traz centenas de e-mails. Eles têm que ir para
    o banco na hora, e não depois que o modelo triar um por um: senão a pessoa
    fica meia hora olhando uma caixa de entrada vazia. Na hora só se tria um
    lote dos mais recentes, o resto fica com a recuperação."""
    from app.worker import tasks

    tasks._paused.clear()
    letters = [raw(f"m{i}") for i in range(tasks.INLINE_CLASSIFY + 15)]
    mail(account.email, FakeSource(letters))

    assert await sync_account(session, account) == len(letters)

    stored = await messages_of(session, account)
    assert len(stored) == len(letters)
    assert ai["calls"] == tasks.INLINE_CLASSIFY
    assert sum(1 for m in stored if m.category) == tasks.INLINE_CLASSIFY
    assert account.last_synced_at is not None
