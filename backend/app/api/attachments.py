"""Baixar um anexo do e-mail — direto da caixa, no clique.

Não guardamos os arquivos: no banco fica só a descrição (nome, tipo, tamanho,
posição entre os anexos). Os bytes vêm da caixa de e-mail na hora do
download e vão direto para a pessoa. Assim não precisamos responder por um
armazenamento de arquivos dos outros, e um e-mail apagado da caixa deixa,
com franqueza, de poder ser baixado.

Sempre entregamos como download, nunca para exibir no navegador: o anexo
pode ter sido mandado por qualquer um, e um HTML ou SVG do e-mail aberto
no nosso endereço rodaria com as permissões do nosso site. Os tipos
perigosos ainda são trocados por application/octet-stream — para o caso
de um navegador que não obedeça.
"""

import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_session
from app.mail.errors import (
    ATTACHMENT_TOO_BIG,
    MailError,
    MailGoneError,
    MailTooBigError,
)
from app.mail.imap_source import MAX_ATTACHMENT_BYTES, ImapSource
from app.models import Account, Attachment, Message, User
from app.security import current_user, visible_accounts

router = APIRouter(prefix="/api/messages", tags=["attachments"])

# Tipos que o navegador não executa. Todo o resto — HTML, SVG, XML,
# scripts e o que não conhecemos — vai como application/octet-stream.
SAFE_TYPES = {
    "application/pdf",
    "application/zip",
    "application/x-zip-compressed",
    "application/x-7z-compressed",
    "application/x-rar-compressed",
    "application/vnd.rar",
    "application/gzip",
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.presentation",
    "application/rtf",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/bmp",
    "image/tiff",
    "image/heic",
    "text/plain",
    "text/csv",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "video/mp4",
    "video/quicktime",
}

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def safe_type(declared: str) -> str:
    """Tipo da resposta: o declarado, se for seguro; senão, «só bytes»."""
    kind = (declared or "").split(";", 1)[0].strip().lower()
    return kind if kind in SAFE_TYPES else "application/octet-stream"


def disposition(filename: str) -> str:
    """Content-Disposition: attachment com o nome conforme a RFC 5987.

    Quem escreve o nome é o remetente do e-mail. Aspas, barra invertida ou
    quebra de linha nele quebrariam o cabeçalho — por isso o filename simples
    leva só ASCII seguro, e o nome verdadeiro inteiro vai em filename*, codificado.
    """
    name = _CONTROL.sub("", filename).strip() or "file"
    fallback = "".join(
        char if 32 <= ord(char) < 127 and char not in '"\\;' else "_" for char in name
    )
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"


@router.get("/{message_id}/attachments/{attachment_id}")
async def download_attachment(
    message_id: int,
    attachment_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
) -> Response:
    # Numa só consulta, o e-mail e o anexo — e só das caixas visíveis:
    # o anexo de outra pessoa não existe para este acesso, assim como o e-mail.
    row = (
        await session.execute(
            select(Attachment, Message)
            .join(Message, Attachment.message_id == Message.id)
            .join(Account, Message.account_id == Account.id)
            .options(selectinload(Message.account))
            .where(
                Attachment.id == attachment_id,
                Message.id == message_id,
                visible_accounts(user),
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Anexo não encontrado")
    item, message = row

    if item.size_bytes > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, ATTACHMENT_TOO_BIG)

    try:
        data = await ImapSource(message.account).fetch_attachment(
            message.provider_message_id, item.part_index, item.filename, item.size_bytes
        )
    except MailGoneError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except MailTooBigError as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc)) from exc
    except MailError as exc:
        # Caixa fora do ar, senha revogada, serviço sem resposta — o texto
        # já está em linguagem de gente, e é ele que mostramos.
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    return Response(
        content=data,
        media_type=safe_type(item.content_type),
        headers={
            "Content-Disposition": disposition(item.filename),
            "X-Content-Type-Options": "nosniff",
            # Um arquivo do e-mail de outra pessoa não deve ficar nem em
            # caches compartilhados, nem no cache do navegador de um computador alheio.
            "Cache-Control": "private, no-store",
        },
    )
