"""Regras do usuário: «tudo dos advogados é importante».

As regras valem para os dois acessos, assim como as caixas: os e-mails
pertencem ao negócio. Uma regra criada pelo dono vale também para as
caixas conectadas pelo desenvolvedor — senão metade dos e-mails seguiria
uma lei, metade outra, e ninguém entenderia por quê.
"""

from dataclasses import asdict
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import keys
from app.ai.provider import AIError, AINotConfigured
from app.ai.rule_parser import parse_rule
from app.ai.schemas import CATEGORIES
from app.ai.triage import TriageResult
from app.db import get_session
from app.models import Account, Message, Rule, User
from app.priority.engine import (
    ACTION_KINDS,
    AMOUNT_OVER,
    BODY_CONTAINS,
    CATEGORY_IS,
    CONDITION_KINDS,
    SENDER_CONTAINS,
    SET_CATEGORY,
    SUBJECT_CONTAINS,
    apply_rules,
)
from app.security import current_user, visible_accounts, visible_rules

router = APIRouter(prefix="/api/rules", tags=["rules"])


class Phrase(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class NewRule(BaseModel):
    title: str = Field(default="", max_length=200)
    condition_kind: str
    condition_value: str = Field(min_length=1, max_length=500)
    action_kind: str
    action_value: str = Field(min_length=1, max_length=64)
    apply_to_existing: bool = True


class RulePatch(BaseModel):
    is_active: bool | None = None


def _as_dict(rule: Rule) -> dict:
    return {
        "id": rule.id,
        "title": rule.title,
        "condition_kind": rule.condition_kind,
        "condition_value": rule.condition_value,
        "action_kind": rule.action_kind,
        "action_value": rule.action_value,
        "is_active": rule.is_active,
        "created_at": rule.created_at,
    }


def _check(rule: NewRule) -> str | None:
    """O que há de errado com a regra, em linguagem humana. None se está tudo certo.

    Validamos aqui em vez de confiar no motor: ele ignora em silêncio uma
    regra que não conhece, e a pessoa acharia que a regra existe quando ela
    não funciona.
    """
    if rule.condition_kind not in CONDITION_KINDS:
        return "Condição desconhecida"
    if rule.action_kind not in ACTION_KINDS:
        return "Ação desconhecida"
    if not rule.condition_value.strip():
        return "A condição está vazia"

    if rule.condition_kind == AMOUNT_OVER:
        try:
            if Decimal(rule.condition_value) < 0:
                return "O valor não pode ser negativo"
        except InvalidOperation:
            return "O valor precisa ser um número: 50000 ou 1284.50"
    if rule.condition_kind == CATEGORY_IS and rule.condition_value not in CATEGORIES:
        return "Essa categoria não existe"

    if rule.action_kind == SET_CATEGORY:
        if rule.action_value not in CATEGORIES:
            return "Essa categoria não existe"
    else:
        try:
            priority = int(rule.action_value)
        except ValueError:
            return "A prioridade precisa ser um número de 0 a 100"
        if not 0 <= priority <= 100:
            return "A prioridade precisa ser um número de 0 a 100"
    return None


def _candidates(rule: Rule):
    """Filtro grosso dos e-mails no banco: só os que podem casar com a regra.

    A checagem exata fica com o motor — o mesmo da triagem de e-mails novos.
    O filtro serve apenas para não puxar do banco todos os cem mil e-mails.
    """
    pattern = f"%{rule.condition_value.strip()}%"
    if rule.condition_kind == SENDER_CONTAINS:
        return or_(Message.sender.ilike(pattern), Message.sender_name.ilike(pattern))
    if rule.condition_kind == SUBJECT_CONTAINS:
        return Message.subject.ilike(pattern)
    if rule.condition_kind == BODY_CONTAINS:
        return or_(Message.subject.ilike(pattern), Message.body_text.ilike(pattern))
    if rule.condition_kind == AMOUNT_OVER:
        return Message.amount > Decimal(rule.condition_value)
    return Message.category == rule.condition_value


async def _apply_to_existing(session: AsyncSession, user: User, rule: Rule) -> int:
    """Aplicar a regra aos e-mails já triados. Devolve quantos e-mails mudaram.

    Sem isso a regra só vale para e-mails novos, e a pessoa que criou
    «tudo do Banco Inter é importante» vê os e-mails do Banco Inter
    continuarem lá embaixo e conclui que as regras não funcionam.
    """
    messages = await session.scalars(
        select(Message)
        .join(Account)
        .where(visible_accounts(user), Message.category.is_not(None), _candidates(rule))
    )
    changed = 0
    for message in messages:
        current = TriageResult(
            category=message.category,
            priority=message.priority if message.priority is not None else 0,
            summary=message.summary or "",
            action_required=message.action_required,
            deadline=message.deadline,
            amount=message.amount,
            currency=message.currency,
        )
        result = apply_rules(current, message, [rule])
        if (result.category, result.priority) != (current.category, current.priority):
            message.category = result.category
            message.priority = result.priority
            changed += 1
    return changed


@router.get("")
async def list_rules(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    rules = await session.scalars(select(Rule).where(visible_rules(user)).order_by(Rule.id.desc()))
    return {"items": [_as_dict(rule) for rule in rules], "categories": CATEGORIES}


@router.post("/parse")
async def parse(
    phrase: Phrase,
    user: User = Depends(current_user),
) -> dict:
    """Transformar uma frase em regra. Não salva nada — só mostra como
    a IA entendeu a pessoa."""
    try:
        with keys.using(keys.key_of(user)):
            parsed = await parse_rule(phrase.text.strip())
    except AINotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except AIError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "A IA não respondeu agora. Tente de novo em um minuto."
        ) from exc

    draft = asdict(parsed)
    if parsed.understood:
        problem = _check(
            NewRule(
                condition_kind=parsed.condition_kind,
                condition_value=parsed.condition_value or "-",
                action_kind=parsed.action_kind,
                action_value=parsed.action_value or "-",
            )
        )
        if problem:
            # A IA acha que entendeu, mas devolveu algo que o motor não aceita.
            # Mostramos como não entendido — melhor perguntar de novo do que salvar lixo.
            draft["understood"] = False
            draft["explanation"] = (
                f"Não consegui entender a regra: {problem.lower()}. Tente dizer de outro jeito."
            )
    draft["title"] = phrase.text.strip()
    return draft


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_rule(
    new: NewRule,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    problem = _check(new)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)

    rule = Rule(
        user_id=user.id,
        title=new.title.strip(),
        condition_kind=new.condition_kind,
        condition_value=new.condition_value.strip(),
        action_kind=new.action_kind,
        action_value=new.action_value.strip(),
        is_active=True,
    )
    session.add(rule)
    await session.flush()

    applied = await _apply_to_existing(session, user, rule) if new.apply_to_existing else 0
    await session.commit()
    await session.refresh(rule)
    return {**_as_dict(rule), "applied": applied}


async def _owned_rule(rule_id: int, session: AsyncSession, user: User) -> Rule:
    rule = await session.scalar(select(Rule).where(Rule.id == rule_id, visible_rules(user)))
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Regra não encontrada")
    return rule


@router.patch("/{rule_id}")
async def update_rule(
    rule_id: int,
    patch: RulePatch,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    rule = await _owned_rule(rule_id, session, user)
    if patch.is_active is not None:
        rule.is_active = patch.is_active
    await session.commit()
    await session.refresh(rule)
    return _as_dict(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> Response:
    rule = await _owned_rule(rule_id, session, user)
    await session.delete(rule)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

