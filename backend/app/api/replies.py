"""Resposta a um e-mail: rascunho da IA → ajuste pela pessoa → envio.

Recebido → triagem → rascunho → decisão da pessoa → envio (especificação,
seção 13). A IA não envia nada sozinha. O e-mail só sai quando alguém
aperta «Enviar» embaixo de um texto que está vendo por inteiro.

Botões da especificação: SEND, EDIT (edição direto no campo), IGNORE,
REMIND ME. DELEGATE ainda não existe: não há para quem delegar, o sistema
tem dois acessos, e os dois têm permissão total.
"""

from datetime import UTC, datetime, timedelta
from email.utils import parseaddr

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.draft import draft_reply
from app.ai import keys
from app.ai.provider import AIError, AINotConfigured
from app.db import get_session
from app.mail import smtp_send
from app.mail.errors import MailError
from app.models import Account, Message, Reply, User
from app.security import current_user, visible_accounts

router = APIRouter(prefix="/api/messages", tags=["replies"])

# Quantos e-mails anteriores da mesma pessoa mostramos ao modelo.
HISTORY_LETTERS = 5
HISTORY_REPLIES = 3

OPEN = ("draft", "failed")


class DraftRequest(BaseModel):
    # Um rascunho novo no lugar do atual: o anterior fica no histórico
    # com status dropped, em vez de ser apagado.
    regenerate: bool = False


class SendRequest(BaseModel):
    # Sem rascunho: a pessoa escreve a resposta sozinha, sem IA.
    reply_id: int | None = None
    text: str = Field(min_length=1, max_length=50_000)
    to: str = Field(min_length=3, max_length=320)
    subject: str = Field(default="", max_length=1000)


class SnoozeRequest(BaseModel):
    hours: int = Field(ge=1, le=24 * 60)


def reply_dict(reply: Reply) -> dict:
    return {
        "id": reply.id,
        "status": reply.status,
        "to": reply.to_address,
        "subject": reply.subject,
        "ai_text": reply.ai_text,
        "final_text": reply.final_text,
        "language": reply.language,
        "note": reply.note,
        "error": reply.error,
        "created_at": reply.created_at,
        "sent_at": reply.sent_at,
    }


def answer_address(message: Message) -> str:
    """Para onde responder: o Reply-To, se o e-mail tiver um; senão, o remetente."""
    return message.reply_to or message.sender


def _valid_address(value: str) -> str | None:
    _, address = parseaddr(value)
    address = address.strip()
    if "@" not in address or " " in address or "\n" in address or "\r" in address:
        return None
    local, _, domain = address.rpartition("@")
    if not local or "." not in domain:
        return None
    return address


async def _message(message_id: int, session: AsyncSession, user: User) -> Message:
    message = await session.scalar(
        select(Message)
        .join(Account)
        .options(selectinload(Message.account))
        .where(Message.id == message_id, visible_accounts(user))
    )
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "E-mail não encontrado")
    return message


async def _open_replies(session: AsyncSession, message: Message) -> list[Reply]:
    """Rascunhos abertos do e-mail — por consulta direta, e não pelo
    relacionamento message.replies: depois de carregado na sessão, ele
    não enxerga linhas adicionadas mais tarde."""
    return list(
        await session.scalars(
            select(Reply)
            .where(Reply.message_id == message.id, Reply.status.in_(OPEN))
            .order_by(Reply.id)
        )
    )


async def _context(
    session: AsyncSession, message: Message, user: User
) -> tuple[list[Message], list[Reply]]:
    """Conversa anterior com essa pessoa: os e-mails dela e as nossas respostas."""
    earlier = list(
        await session.scalars(
            select(Message)
            .join(Account)
            .where(
                Message.sender == message.sender,
                Message.id != message.id,
                Message.folder.is_distinct_from("spam"),
                # Só das caixas que essa pessoa vê — senão o rascunho
                # traria o e-mail de outro usuário para o prompt.
                visible_accounts(user),
            )
            .order_by(Message.sent_at.desc().nulls_last())
            .limit(HISTORY_LETTERS)
        )
    )
    sent = list(
        await session.scalars(
            select(Reply)
            .join(Message, Reply.message_id == Message.id)
            .join(Account)
            .where(
                Reply.to_address == answer_address(message),
                Reply.status == "sent",
                visible_accounts(user),
            )
            .order_by(Reply.id.desc())
            .limit(HISTORY_REPLIES)
        )
    )
    return earlier, sent


@router.post("/{message_id}/draft")
async def make_draft(
    message_id: int,
    body: DraftRequest | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    """Rascunho de resposta. Se já existe um rascunho aberto, devolvemos
    esse, em vez de gastar uma chamada ao modelo com outro igual."""
    message = await _message(message_id, session, user)
    opened = await _open_replies(session, message)
    current = opened[-1] if opened else None
    if current and not (body and body.regenerate):
        return reply_dict(current)

    earlier, sent = await _context(session, message, user)
    try:
        # O rascunho sai pela chave de quem pediu.
        with keys.using(keys.key_of(user)):
            draft = await draft_reply(message, earlier, sent)
    except AINotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except AIError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "A IA não respondeu agora. Tente de novo em um minuto.",
        ) from exc

    if current:
        current.status = "dropped"
    reply = Reply(
        message_id=message.id,
        status="draft",
        to_address=answer_address(message)[:320],
        subject=smtp_send.reply_subject(message.subject),
        ai_text=draft.text,
        language=draft.language,
        note=draft.note,
        created_by=user.id,
    )
    session.add(reply)
    await session.commit()
    await session.refresh(reply)
    return reply_dict(reply)


@router.post("/{message_id}/send")
async def send_reply(
    message_id: int,
    body: SendRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    """Enviar a resposta — exatamente o texto que a pessoa vê no campo.

    A linha da resposta fica travada durante o envio. Senão um clique duplo
    em «Enviar» (ou dois donos no mesmo segundo) mandaria o mesmo e-mail
    duas vezes: a segunda requisição espera e vê que já foi enviado.
    """
    message = await _message(message_id, session, user)
    if body.reply_id is None:
        # Resposta própria, sem rascunho da IA. No histórico ela é igual,
        # só que com ai_text vazio: fica claro que o modelo não participou.
        reply = Reply(
            message_id=message.id,
            status="draft",
            to_address=answer_address(message)[:320],
            subject=smtp_send.reply_subject(message.subject),
            ai_text="",
            created_by=user.id,
        )
        session.add(reply)
        await session.flush()
    else:
        reply = await session.scalar(
            select(Reply)
            .where(Reply.id == body.reply_id, Reply.message_id == message.id)
            .with_for_update()
        )
    if reply is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rascunho não encontrado")
    if reply.status == "sent":
        raise HTTPException(status.HTTP_409_CONFLICT, "Esta resposta já foi enviada")
    if reply.status not in OPEN:
        raise HTTPException(status.HTTP_409_CONFLICT, "Este rascunho foi substituído por um novo")

    text = body.text.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Não dá para enviar uma resposta vazia")
    to = _valid_address(body.to)
    if to is None:
        # A edição do texto é salva mesmo na recusa: a página vai abrir de
        # novo, e a pessoa vai ver o texto dela, não o rascunho original da IA.
        reply.final_text = text
        await session.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "O endereço do destinatário não parece um e-mail")
    subject = body.subject.strip() or reply.subject

    reply.to_address = to
    reply.subject = subject
    reply.final_text = text
    try:
        sent_id = await smtp_send.send(
            message.account,
            smtp_send.Outgoing(to=to, subject=subject, text=text, in_reply_to=message.thread_id),
        )
    except MailError as exc:
        # O texto não se perde: a resposta fica no histórico com status
        # failed e pode ser reenviada sem digitar nada de novo.
        reply.status = "failed"
        reply.error = str(exc)
        await session.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    now = datetime.now(UTC)
    reply.status = "sent"
    reply.error = None
    reply.sent_message_id = sent_id[:255]
    reply.sent_by = user.id
    reply.sent_at = now
    message.handled_at = now
    message.snoozed_until = None
    await session.commit()
    await session.refresh(reply)
    return reply_dict(reply)


@router.post("/{message_id}/ignore")
async def ignore(
    message_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    """«Ignorar»: não haverá resposta. O e-mail desce na lista de pendências,
    e o rascunho aberto vai para o histórico como descartado."""
    message = await _message(message_id, session, user)
    message.handled_at = datetime.now(UTC)
    message.snoozed_until = None
    for reply in await _open_replies(session, message):
        reply.status = "dropped"
    await session.commit()
    return {"status": "ok"}


@router.post("/{message_id}/snooze")
async def snooze(
    message_id: int,
    body: SnoozeRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    """«Lembrar depois»: tirar da lista até a hora marcada e depois devolver."""
    message = await _message(message_id, session, user)
    message.snoozed_until = datetime.now(UTC) + timedelta(hours=body.hours)
    await session.commit()
    return {"status": "ok", "snoozed_until": message.snoozed_until}


@router.post("/{message_id}/reopen")
async def reopen(
    message_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    """Devolver o e-mail às pendências: a pessoa desistiu de ignorar ou adiar."""
    message = await _message(message_id, session, user)
    message.handled_at = None
    message.snoozed_until = None
    await session.commit()
    return {"status": "ok"}
