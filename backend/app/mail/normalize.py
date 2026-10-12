"""Transformação da mensagem bruta em registro do banco.

A tarefa principal é não criar duplicatas. É fácil consultar a mesma caixa
duas vezes: o worker reiniciou, o cursor não chegou a ser salvo, a caixa
foi conectada de novo. O usuário não pode ver o mesmo e-mail duas vezes.

A proteção é dupla: conferimos o banco antes de inserir e mantemos um índice
único em (account_id, provider_message_id) — para o caso de duas
sincronizações da mesma caixa rodarem ao mesmo tempo.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mail.base import RawMessage
from app.models import Account, Message

# Há e-mails de tamanho monstruoso — em geral por causa de assinaturas e citações.
# Para a triagem o começo basta, e o banco não incha.
BODY_LIMIT = 100_000


# Os tamanhos vêm da própria tabela, para não divergirem do modelo.
_LIMITS = {
    name: column.type.length
    for name, column in Message.__table__.columns.items()
    if getattr(column.type, "length", None)
}


def _fit(field: str, value: str) -> str:
    """Cortar o valor para caber na coluna.

    Quem manda no e-mail é o remetente, não nós. Um e-mail com nome de
    remetente de três mil letras não é hipótese, é um jeito de travar para
    sempre a sincronização da caixa: o insert falha, o cursor não anda, o
    mesmo e-mail volta a cada minuto. Cortamos e seguimos em frente.
    """
    limit = _LIMITS.get(field)
    return value[:limit] if limit and value and len(value) > limit else value


async def store_messages(
    session: AsyncSession, account: Account, raws: list[RawMessage]
) -> list[Message]:
    """Salvar os e-mails novos da caixa. Devolve só os que foram de fato adicionados."""
    if not raws:
        return []

    # o dict remove repetições dentro do mesmo lote: o último vence
    incoming = {raw.provider_message_id: raw for raw in raws}

    already_stored = set(
        await session.scalars(
            select(Message.provider_message_id).where(
                Message.account_id == account.id,
                Message.provider_message_id.in_(incoming),
            )
        )
    )

    fresh = [incoming[key] for key in incoming if key not in already_stored]
    stored = [
        Message(
            account_id=account.id,
            provider_message_id=_fit("provider_message_id", raw.provider_message_id),
            thread_id=_fit("thread_id", raw.thread_id) if raw.thread_id else None,
            sender=_fit("sender", raw.sender),
            sender_name=_fit("sender_name", raw.sender_name),
            recipients=raw.recipients,
            subject=raw.subject,
            body_text=raw.body_text[:BODY_LIMIT],
            sent_at=raw.sent_at,
            folder=_fit("folder", raw.folder),
            reply_to=_fit("reply_to", raw.reply_to) if raw.reply_to else None,
        )
        for raw in fresh
    ]
    session.add_all(stored)
    await session.flush()
    return stored
