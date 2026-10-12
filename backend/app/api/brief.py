"""Resumo do dia: o que pede uma decisão hoje."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app import brief
from app.api.messages import _short
from app.db import get_session
from app.models import User
from app.security import current_user

router = APIRouter(prefix="/api/brief", tags=["brief"])


def _as_dict(data: brief.BriefData) -> dict:
    return {
        "day": data.day,
        "intro": data.intro,
        "generated_at": data.generated_at,
        "attention": [_short(message) for message in data.attention],
        "replies": [_short(message) for message in data.replies],
        "money": [_short(message) for message in data.money],
        "arrived": data.arrived,
        "information": data.information,
        "filtered": data.filtered,
    }


@router.get("")
async def get_brief(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    return _as_dict(await brief.collect(session, user))


@router.post("/refresh")
async def refresh_brief(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    """Refazer a introdução agora — sem esperar a manhã."""
    return _as_dict(await brief.refresh(session, user))
