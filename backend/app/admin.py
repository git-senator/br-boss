"""Criação dos donos pela linha de comando.

Os logins da equipe (o desenvolvedor e o dono) não passam pelo cadastro
do site: são criados aqui, à mão, uma vez:

    docker compose exec api python -m app.admin add boss@example.com
    docker compose exec api python -m app.admin password boss@example.com

A senha é impressa uma única vez e não fica guardada em texto puro em nenhum outro lugar.
"""

import argparse
import asyncio
import secrets
import sys

from sqlalchemy import select

from app.db import SessionFactory
from app.models import User
from app.security import hash_password


async def _add(email: str) -> int:
    email = email.strip().lower()
    async with SessionFactory() as session:
        if await session.scalar(select(User.id).where(User.email == email)):
            print(f"Esse acesso já existe: {email}")
            return 1
        password = secrets.token_urlsafe(12)
        session.add(User(email=email, password_hash=hash_password(password)))
        await session.commit()
    print(f"Acesso criado:\n  e-mail: {email}\n  senha:  {password}")
    print("A senha é exibida só uma vez — guarde-a agora.")
    return 0


async def _password(email: str) -> int:
    email = email.strip().lower()
    async with SessionFactory() as session:
        user = await session.scalar(select(User).where(User.email == email))
        if user is None:
            print(f"Acesso não encontrado: {email}")
            return 1
        password = secrets.token_urlsafe(12)
        user.password_hash = hash_password(password)
        await session.commit()
    print(f"Nova senha para {email}: {password}")
    return 0


async def _drop_totp(email: str) -> int:
    """Desligar a verificação em duas etapas — se o celular com o app foi perdido."""
    email = email.strip().lower()
    async with SessionFactory() as session:
        user = await session.scalar(select(User).where(User.email == email))
        if user is None:
            print(f"Acesso não encontrado: {email}")
            return 1
        user.totp_secret = None
        await session.commit()
    print(f"Código de verificação desativado para {email}. Configure-o de novo depois de entrar.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="app.admin", description="Acessos do sistema")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("add", "criar acesso"),
        ("password", "gerar nova senha"),
        ("drop-totp", "desativar o código de verificação"),
    ):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("email")

    args = parser.parse_args()
    action = {"add": _add, "password": _password, "drop-totp": _drop_totp}[args.command]
    return asyncio.run(action(args.email))


if __name__ == "__main__":
    sys.exit(main())
