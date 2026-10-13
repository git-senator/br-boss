"""Caixas de e-mail conectadas.

Serão umas trinta, e quem conecta é uma pessoa, na mão. Por isso há
duas regras aqui: depois de salva, a senha nunca mais é mostrada, e a
caixa que não conseguiu conectar simplesmente não é salva — senão ela
ficaria na lista sem trazer e-mail nenhum, em silêncio.
"""

import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import quota
from app.crypto import encrypt_secret
from app.db import get_session
from app.mail.errors import MailError
from app.mail.providers import known_services, profile_for
from app.mail.registry import get_source
from app.models import Account, Attachment, Message, Reply, User
from app.security import MEMBER, current_user, visible_accounts

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


class NewAccount(BaseModel):
    email: str
    password: str
    display_name: str = ""


# Limites contra quem usaria o formulário como serviço gratuito de testar
# senhas em servidores alheios: cada caixa conferida é um login IMAP de
# verdade, saindo do nosso endereço.
#
# Linhas e tamanho de um envio da lista. São umas trinta caixas, com folga.
BULK_LINES = 50
BULK_CHARS = 20_000
# Testes de conexão por pessoa por hora — somando o formulário e a lista.
# Fica no banco (app.quota), e não na memória: sobrevive a um reinício.
CHECKS_PER_HOUR = 30
# Caixas por pessoa que se cadastrou sozinha. A equipe não tem teto.
MEMBER_MAILBOXES = 50

TOO_MANY_LINES = f"São no máximo {BULK_LINES} caixas por vez. Divida a lista em partes."
TOO_LONG = "A lista está grande demais. Divida em partes."
TOO_MANY_CHECKS = (
    "Tentativas de conexão demais na última hora. Espere um pouco e tente de novo."
)
TOO_MANY_MAILBOXES = f"Você já tem o máximo de {MEMBER_MAILBOXES} caixas de e-mail conectadas."


class BulkAccounts(BaseModel):
    # O tamanho é conferido na rota, e não aqui: o erro do pydantic sai em
    # inglês, e a página o mostraria como «algo deu errado».
    text: str


class AccountPatch(BaseModel):
    is_active: bool | None = None
    display_name: str | None = None


def _as_dict(account: Account) -> dict:
    profile = profile_for(account.email)
    return {
        "id": account.id,
        "email": account.email,
        "display_name": account.display_name,
        "service": profile.label,
        "imap_host": profile.imap_host,
        "is_active": account.is_active,
        "last_error": account.last_error,
        "last_synced_at": account.last_synced_at,
    }


async def _owned_account(account_id: int, session: AsyncSession, user: User) -> Account:
    account = await session.scalar(
        select(Account).where(Account.id == account_id, visible_accounts(user))
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Caixa de e-mail não encontrada")
    return account


@router.get("/services")
async def services(user: User = Depends(current_user)) -> dict:
    """Serviços com dicas prontas — para o formulário «Adicionar e-mail»."""
    return {
        "items": [
            {
                "key": profile.key,
                "label": profile.label,
                "help_url": profile.help_url,
                "password_hint": profile.password_hint,
            }
            for profile in known_services()
        ]
    }


@router.get("/service-for")
async def service_for(email: str, user: User = Depends(current_user)) -> dict:
    profile = profile_for(email)
    return {
        "key": profile.key,
        "label": profile.label,
        "imap_host": profile.imap_host,
        "help_url": profile.help_url,
        "password_hint": profile.password_hint,
    }


@router.get("")
async def list_accounts(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    accounts = await session.scalars(
        select(Account).where(visible_accounts(user)).order_by(Account.email)
    )
    return {"items": [_as_dict(account) for account in accounts]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_account(
    data: NewAccount,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    email = data.email.strip().lower()
    # Só entre as caixas que esta pessoa enxerga. Procurar em todas contaria
    # a um desconhecido que alguém já conectou este endereço aqui.
    taken = await session.scalar(
        select(Account.id).where(Account.email == email, visible_accounts(user))
    )
    if taken:
        raise HTTPException(status_code=409, detail="Esta caixa de e-mail já está conectada")
    if await _room_left(session, user) < 1:
        raise HTTPException(status_code=400, detail=TOO_MANY_MAILBOXES)
    if not await _take_check(session, user):
        raise HTTPException(status_code=429, detail=TOO_MANY_CHECKS)

    account = Account(
        user_id=user.id,
        provider="imap",
        email=email,
        display_name=data.display_name,
        secret_ciphertext=encrypt_secret(data.password),
    )
    try:
        await get_source(account).verify()
    except MailError as exc:
        raise HTTPException(
            status_code=400,
            detail={"message": str(exc), "hint": exc.hint, "help_url": exc.help_url},
        ) from exc

    session.add(account)
    await session.commit()
    return _as_dict(account)


async def _room_left(session: AsyncSession, user: User) -> int:
    """Quantas caixas ainda cabem. Para a equipe, sem teto."""
    if user.role != MEMBER:
        return BULK_LINES
    own = await session.scalar(
        select(func.count()).select_from(Account).where(Account.user_id == user.id)
    )
    return max(0, MEMBER_MAILBOXES - (own or 0))


async def _take_check(session: AsyncSession, user: User) -> bool:
    """Gastar um teste de conexão da hora. False — acabaram."""
    return await quota.take(
        session, f"mailcheck:{user.id}:", quota.this_hour(), 1, CHECKS_PER_HOUR
    )


# Linha da lista: endereço, depois senha. O separador pode ser qualquer coisa
# razoável — as pessoas copiam do bloco de notas, de planilha, de conversa.
_SPLIT = re.compile(r"[\s,;:]+")
_APP_PASSWORD = re.compile(r"^[a-zA-Z0-9]{16}$")


def _clean_password(raw: str) -> str:
    """O Google mostra a senha de app como «abcd efgh ijkl mnop».

    As pessoas copiam com os espaços. Se sem espaços sobram exatamente
    dezesseis letras e números, é ela mesma — tiramos os espaços.
    Uma senha de verdade com espaços não cai nessa regra.
    """
    squeezed = raw.replace(" ", "")
    return squeezed if _APP_PASSWORD.match(squeezed) else raw


def _parse_line(line: str) -> tuple[str, str] | None:
    parts = [part for part in _SPLIT.split(line.strip()) if part]
    if len(parts) < 2 or "@" not in parts[0]:
        return None
    return parts[0].lower(), _clean_password(" ".join(parts[1:]))


@router.post("/bulk")
async def add_many(
    data: BulkAccounts,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    """Conectar várias caixas de uma vez — uma linha para cada.

    São duas ou três dezenas, e adicionar uma por uma pelo formulário é
    uma noite de trabalho. Uma senha errada não cancela as outras: cada
    linha segue seu caminho, e a resposta mostra quem não conectou e por quê.
    """
    if len(data.text) > BULK_CHARS:
        raise HTTPException(status_code=400, detail=TOO_LONG)
    lines = [line for line in data.text.splitlines() if line.strip()]
    if len(lines) > BULK_LINES:
        raise HTTPException(status_code=400, detail=TOO_MANY_LINES)
    failed: list[dict] = []
    candidates: list[Account] = []

    # Repetidas só entre as caixas que esta pessoa enxerga — como no formulário.
    known = set(await session.scalars(select(Account.email).where(visible_accounts(user))))
    seen: set[str] = set()

    for line in lines:
        parsed = _parse_line(line)
        if parsed is None:
            failed.append(
                {"email": line.strip()[:80], "message": "Informe o e-mail e a senha separados por espaço"}
            )
            continue
        email, password = parsed
        if email in known or email in seen:
            failed.append({"email": email, "message": "Esta caixa de e-mail já está conectada"})
            continue
        seen.add(email)
        candidates.append(
            Account(
                user_id=user.id,
                provider="imap",
                email=email,
                secret_ciphertext=encrypt_secret(password),
            )
        )

    # O que não cabe no teto de caixas ou nos testes da hora volta na lista
    # de falhas, com o motivo — as outras linhas seguem normalmente.
    room = await _room_left(session, user)
    allowed: list[Account] = []
    for account in candidates:
        if len(allowed) >= room:
            failed.append({"email": account.email, "message": TOO_MANY_MAILBOXES})
        elif not await _take_check(session, user):
            failed.append({"email": account.email, "message": TOO_MANY_CHECKS})
        else:
            allowed.append(account)
    candidates = allowed

    # Testamos as conexões em paralelo, mas no máximo cinco por vez:
    # os serviços de e-mail não gostam de levar trinta conexões de uma vez.
    limit = asyncio.Semaphore(5)

    async def check(account: Account) -> str | None:
        async with limit:
            try:
                await get_source(account).verify()
            except MailError as exc:
                return str(exc)
            except Exception:  # noqa: BLE001 — qualquer problema tem que chegar à linha da lista
                return "Não foi possível conectar"
        return None

    problems = await asyncio.gather(*(check(account) for account in candidates))

    added = 0
    for account, problem in zip(candidates, problems, strict=True):
        if problem:
            failed.append({"email": account.email, "message": problem})
            continue
        session.add(account)
        added += 1

    await session.commit()
    return {"added": added, "failed": failed}


@router.patch("/{account_id}")
async def update_account(
    account_id: int,
    data: AccountPatch,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    account = await _owned_account(account_id, session, user)
    if data.is_active is not None:
        account.is_active = data.is_active
    if data.display_name is not None:
        account.display_name = data.display_name
    await session.commit()
    return _as_dict(account)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> Response:
    """Desconectar a caixa de vez — junto com os e-mails dela.

    Se a ideia é só pausar a leitura sem perder os e-mails já triados,
    use PATCH is_active=false.
    """
    account = await _owned_account(account_id, session, user)
    messages = select(Message.id).where(Message.account_id == account.id).scalar_subquery()
    await session.execute(delete(Attachment).where(Attachment.message_id.in_(messages)))
    await session.execute(delete(Reply).where(Reply.message_id.in_(messages)))
    await session.execute(delete(Message).where(Message.account_id == account.id))
    await session.delete(account)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
