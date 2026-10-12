"""Estado do sistema para o cabeçalho: quem está triando os e-mails e o que
espera pela pessoa.

O selo no cabeçalho conta a verdade sobre a triagem: qual modelo está
rodando, se está em pausa, quantos e-mails esperam na fila. O sininho mostra
quantos e-mails pedem atenção agora mesmo (as mesmas regras do resumo do dia).
"""

import time

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.schemas import ADS, SPAM
from app.brief import ATTENTION_FROM
from app.config import settings
from app.db import get_session
from app.models import Account, Message, User, WorkerState
from app.security import current_user, visible_accounts
from app.ai import keys
from app.worker.tasks import pause_name

router = APIRouter(prefix="/api/status", tags=["status"])

PROVIDERS = {
    "anthropic": ("Claude", "anthropic_api_key"),
    "gemini": ("Gemini", "gemini_api_key"),
    "openrouter": ("OpenRouter", "openrouter_api_key"),
    "ollama": ("Modelo local", None),
}


@router.get("")
async def status(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    # O selo fala da chave usada na triagem dos e-mails desta pessoa.
    if user.ai_key_ciphertext:
        name, configured, own = "Gemini", True, True
    else:
        name, key_field = PROVIDERS.get(settings.ai_provider, (settings.ai_provider, None))
        configured = keys.may_use_server_key(user) and (
            key_field is None or bool(getattr(settings, key_field, ""))
        )
        own = False

    stored = await session.scalar(
        select(WorkerState.value).where(WorkerState.key == pause_name(keys.scope_of(user)))
    )
    try:
        paused_until = float(stored) if stored else 0.0
    except ValueError:
        paused_until = 0.0

    visible = [visible_accounts(user), Account.is_active.is_(True)]
    unsorted = await session.scalar(
        select(func.count())
        .select_from(Message)
        .join(Account)
        .where(*visible, Message.category.is_(None), Message.folder.is_distinct_from(SPAM))
    )
    attention = await session.scalar(
        select(func.count())
        .select_from(Message)
        .join(Account)
        .where(
            *visible,
            Message.handled_at.is_(None),
            or_(Message.snoozed_until.is_(None), Message.snoozed_until <= func.now()),
            Message.folder.is_distinct_from(SPAM),
            Message.category.is_distinct_from(ADS),
            Message.priority >= ATTENTION_FROM,
        )
    )
    return {
        "ai": {
            "name": name,
            "configured": configured,
            "own_key": own,
            "paused_until": paused_until if paused_until > time.time() else None,
        },
        "unsorted": unsorted,
        "attention": attention,
    }
