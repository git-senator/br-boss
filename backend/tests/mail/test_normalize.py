from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.mail.base import RawMessage
from app.mail.normalize import BODY_LIMIT, store_messages
from app.models import Account, Message


def raw(msg_id: str, **overrides) -> RawMessage:
    defaults = {
        "provider_message_id": msg_id,
        "sender": "joao@fornecedor.com.br",
        "sender_name": "João Pereira",
        "subject": "Boleto",
        "body_text": "Pague até sexta",
        "sent_at": datetime(2026, 8, 17, 10, 0, tzinfo=UTC),
        "recipients": ["boss@example.com"],
    }
    return RawMessage(**{**defaults, **overrides})


async def count_messages(session) -> int:
    return await session.scalar(select(func.count()).select_from(Message))


async def test_stores_new_messages(session, account):
    stored = await store_messages(session, account, [raw("m1"), raw("m2")])
    assert len(stored) == 2
    assert await count_messages(session) == 2


async def test_second_run_with_same_ids_stores_nothing(session, account):
    await store_messages(session, account, [raw("m1"), raw("m2")])
    again = await store_messages(session, account, [raw("m1"), raw("m2")])
    assert again == []
    assert await count_messages(session) == 2


async def test_partial_overlap_stores_only_the_new_one(session, account):
    await store_messages(session, account, [raw("m1")])
    stored = await store_messages(session, account, [raw("m1"), raw("m2")])
    assert [m.provider_message_id for m in stored] == ["m2"]


async def test_duplicates_inside_one_batch_are_collapsed(session, account):
    stored = await store_messages(session, account, [raw("m1"), raw("m1")])
    assert len(stored) == 1


async def test_empty_input_is_fine(session, account):
    assert await store_messages(session, account, []) == []


async def test_same_id_in_another_mailbox_is_not_a_duplicate(session, account, user):
    other = Account(user_id=user.id, provider="imap", email="dois@bol.com", secret_ciphertext="x")
    session.add(other)
    await session.flush()

    await store_messages(session, account, [raw("m1")])
    stored = await store_messages(session, other, [raw("m1")])
    assert len(stored) == 1
    assert await count_messages(session) == 2


async def test_long_body_is_trimmed(session, account):
    [stored] = await store_messages(session, account, [raw("m1", body_text="x" * 500_000)])
    assert len(stored.body_text) == BODY_LIMIT


async def test_fields_survive_storing(session, account):
    [stored] = await store_messages(session, account, [raw("m1")])
    assert stored.sender == "joao@fornecedor.com.br"
    assert stored.sender_name == "João Pereira"
    assert stored.subject == "Boleto"
    assert stored.recipients == ["boss@example.com"]
    assert stored.sent_at is not None
    assert stored.category is None, "a triagem da IA vem em um passo separado"


@pytest.mark.parametrize("field", ["subject", "body_text", "sender_name"])
async def test_missing_text_fields_become_empty_not_null(session, account, field):
    [stored] = await store_messages(session, account, [raw("m1", **{field: ""})])
    assert getattr(stored, field) == ""
