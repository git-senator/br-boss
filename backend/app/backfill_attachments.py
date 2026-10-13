"""Preenchimento único: listas de anexos dos e-mails buscados antes delas existirem.

Até agora o worker não guardava a descrição dos anexos — nos e-mails antigos
a lista está vazia, embora os arquivos estejam na caixa. O comando relê esses
e-mails da caixa (só leitura, as marcações não mudam) e grava as descrições.
Os arquivos em si, como em todo o resto, não são guardados.

    docker compose exec api python -m app.backfill_attachments

Rodar de novo é seguro: um e-mail que já tem anexos gravados não é relido.
"""

import asyncio
import logging

from sqlalchemy import exists, select

from app.db import SessionFactory
from app.mail.errors import MailError
from app.mail.imap_source import ImapSource, _quietly_close, _spam_folder, parse_email
from app.mail.normalize import _attachments
from app.models import Account, Attachment, Message

log = logging.getLogger("backfill")


def _read(source: ImapSource, letters: list[tuple[int, str]]) -> dict[int, bytes]:
    """E-mails da caixa inteiros, num único login. O que não vier, pulamos."""
    found: dict[int, bytes] = {}
    client = source._login()
    try:
        spam = None
        for message_id, provider_id in letters:
            folder, _, uid = provider_id.rpartition(":")
            if folder == "spam":
                spam = spam or _spam_folder(client)
                mailbox = spam
            else:
                mailbox = "INBOX" if not folder else None
            if not mailbox or not uid.isdigit():
                continue
            try:
                found[message_id] = source._fetch_whole(client, mailbox, uid)
            except MailError:
                continue  # apagado da caixa ou grande demais
    finally:
        _quietly_close(client)
    return found


async def backfill_account(account_id: int) -> int:
    async with SessionFactory() as session:
        account = await session.get(Account, account_id)
        letters = [
            (row.id, row.provider_message_id)
            for row in await session.execute(
                select(Message.id, Message.provider_message_id).where(
                    Message.account_id == account_id,
                    ~exists().where(Attachment.message_id == Message.id),
                )
            )
        ]
        if not letters:
            return 0
        raws = await asyncio.to_thread(_read, ImapSource(account), letters)

        added = 0
        for message_id, raw in raws.items():
            for item in _attachments(parse_email(raw, "0")):
                item.message_id = message_id
                session.add(item)
                added += 1
        await session.commit()
        return added


async def main() -> None:
    async with SessionFactory() as session:
        account_ids = list(
            await session.scalars(select(Account.id).where(Account.is_active.is_(True)))
        )
    for account_id in account_ids:
        try:
            added = await backfill_account(account_id)
            print(f"caixa {account_id}: anexos adicionados {added}")
        except Exception as exc:
            print(f"caixa {account_id}: não deu certo — {exc}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
