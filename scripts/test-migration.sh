#!/usr/bin/env sh
# Teste de mudança de servidor de verdade: o sistema é destruído por
# completo e sobe de novo a partir do backup.
#
#   sh scripts/test-migration.sh --sim-destruir
#
# A promessa «nada se perde» não vale nada até ser testada destruindo tudo.
# Antes de uma mudança de servidor real, rode este script.
set -eu

export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."

[ "${1:-}" = "--sim-destruir" ] || {
    echo "Este script apaga o banco e os anexos e depois os restaura do backup."
    echo "Se estiver de acordo: sh scripts/test-migration.sh --sim-destruir"
    exit 1
}

MARK="teste-mudanca-$(date +%s)"

echo "1. Gravando uma marca no banco"
docker compose exec -T api python - "$MARK" <<'PY'
import asyncio
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from app.crypto import encrypt_secret
from app.db import SessionFactory
from app.models import Account, Message, User

mark = sys.argv[1]


async def main() -> None:
    async with SessionFactory() as session:
        user_id = await session.scalar(select(User.id).order_by(User.id))
        if user_id is None:
            raise SystemExit("nenhum acesso cadastrado — rode antes app.admin add")
        box = Account(
            user_id=user_id,
            email=f"{mark}@example.com",
            secret_ciphertext=encrypt_secret(mark),
        )
        session.add(box)
        await session.flush()
        session.add(
            Message(
                account_id=box.id,
                provider_message_id=mark,
                sender="teste@example.com",
                subject=mark,
                priority=77,
                sent_at=datetime.now(UTC),
            )
        )
        await session.commit()


asyncio.run(main())
PY

echo "2. Fazendo o backup"
sh scripts/backup.sh > /dev/null
ARCHIVE="$(ls -t backups/br-boss-*.tar.gz | head -1)"
[ -s "$ARCHIVE" ] || { echo "FALHA: o backup não foi feito, nada foi tocado"; exit 1; }
echo "   $ARCHIVE"

echo "3. Destruindo tudo"
docker compose down -v > /dev/null 2>&1

echo "4. Subindo a partir do backup"
sh scripts/restore.sh "$ARCHIVE" > /dev/null 2>&1

echo "5. Conferindo se a marca voltou"
docker compose exec -T api python - "$MARK" <<'PY'
import asyncio
import sys

from sqlalchemy import delete, select

from app.crypto import decrypt_secret
from app.db import SessionFactory
from app.models import Account, Message

mark = sys.argv[1]


async def main() -> None:
    async with SessionFactory() as session:
        box = await session.scalar(select(Account).where(Account.email == f"{mark}@example.com"))
        assert box is not None, "a caixa não sobreviveu à mudança"
        assert decrypt_secret(box.secret_ciphertext) == mark, "a senha não é descriptografada"
        message = await session.scalar(select(Message).where(Message.subject == mark))
        assert message is not None, "o e-mail não sobreviveu à mudança"
        assert message.priority == 77, "a importância se perdeu"

        await session.execute(delete(Message).where(Message.account_id == box.id))
        await session.delete(box)
        await session.commit()


asyncio.run(main())
print("   caixa, senha e e-mail no lugar, marca removida")
PY

echo "Mudança testada: o sistema sobreviveu à destruição completa."
