"""where the letter came from: inbox or spam

Revision ID: d7f4b1e60c92
Revises: c5d2a80f9e13
Create Date: 2026-09-11 13:20:00.000000

Buscamos o spam também: um e-mail importante que caiu no spam o sistema
tem que mostrar, não perder. Mas ele não deve ficar misturado com o e-mail
normal — daí um campo separado e uma aba separada.

Todos os e-mails buscados antes desta migração recebem "inbox": até ela
não líamos o spam de jeito nenhum.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd7f4b1e60c92'
down_revision: Union[str, Sequence[str], None] = 'c5d2a80f9e13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("folder", sa.String(length=16), nullable=False, server_default="inbox"),
    )
    op.alter_column("messages", "folder", server_default=None)


def downgrade() -> None:
    op.drop_column("messages", "folder")
