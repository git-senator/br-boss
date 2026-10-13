"""Cotas por pessoa que sobrevivem a um reinício.

Caracteres do DeepL por dia, testes de conexão de caixas por hora. Na
memória do processo não serve: um rebuild zeraria tudo, e quem quer gastar
a cota alheia só precisaria esperar o próximo deploy. Então o contador
mora no banco, na mesma tabela da pausa da triagem (WorkerState): uma
linha por pessoa e por período.
"""

from datetime import UTC, datetime

from sqlalchemy import Integer, Text, cast, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WorkerState


def today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def this_hour() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H")


async def take(session: AsyncSession, prefix: str, period: str, amount: int, limit: int) -> bool:
    """Reservar `amount` da cota do período. False — não cabe, e nada é gasto.

    Uma instrução só no banco (insert … on conflict … where): dois pedidos
    ao mesmo tempo não passam juntos pelo limite. O prefixo não pode ter
    «_» nem «%» — ele vira um LIKE na limpeza dos períodos antigos.

    Grava na hora (commit): o gasto conta mesmo que o pedido falhe depois.
    Senão uma senha errada atrás da outra nunca chegaria ao limite.
    """
    if amount > limit:
        return False
    key = f"{prefix}{period}"
    current = cast(WorkerState.value, Integer)
    statement = (
        pg_insert(WorkerState)
        .values(key=key, value=str(amount))
        .on_conflict_do_update(
            index_elements=["key"],
            set_={"value": cast(current + amount, Text)},
            where=current + amount <= limit,
        )
        .returning(WorkerState.value)
    )
    taken = (await session.execute(statement)).scalar_one_or_none() is not None
    # Os períodos passados não servem para mais nada — sem isso a tabela
    # ganharia uma linha por pessoa a cada dia, para sempre.
    await session.execute(
        delete(WorkerState).where(WorkerState.key.like(f"{prefix}%"), WorkerState.key != key)
    )
    await session.commit()
    return taken
