import pytest
from sqlalchemy.exc import IntegrityError

from app.crypto import decrypt_secret
from app.models import Message


def message(msg_id: str, account_id: int) -> Message:
    return Message(
        account_id=account_id,
        provider_message_id=msg_id,
        sender="joao@uol.com.br",
        subject="Boleto",
        body_text="Pague até sexta-feira",
    )


async def test_duplicate_provider_message_id_rejected(session, account):
    session.add_all([message("msg-1", account.id), message("msg-1", account.id)])
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_different_ids_are_stored(session, account):
    session.add_all([message("msg-1", account.id), message("msg-2", account.id)])
    await session.flush()


async def test_account_stores_only_ciphertext(session, account):
    assert "app-password" not in account.secret_ciphertext
    assert decrypt_secret(account.secret_ciphertext) == "app-password-abcd"


async def test_same_email_cannot_be_connected_twice(session, account):
    from app.models import Account

    session.add(
        Account(
            user_id=account.user_id,
            provider="imap",
            email=account.email,
            secret_ciphertext="whatever",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_message_defaults_are_empty_not_null(session, account):
    record = message("msg-3", account.id)
    session.add(record)
    await session.flush()
    assert record.category is None
    assert record.priority is None
    assert record.is_read is False
    assert record.recipients == []
