"""money and deadlines on messages

Revision ID: b3e91f27c5a4
Revises: a1c7d40e9b32
Create Date: 2026-09-10 20:05:00.000000

A triagem do e-mail já extraía valor, moeda e prazo — e jogava fora:
não havia lugar na tabela. Agora há.

Os campos ficam vazios para todos os e-mails triados antes desta migração.
Vão sendo preenchidos conforme a triagem avança; a migração não vai forçar
uma nova triagem do que é antigo — apagar dados por causa de um campo novo
não pode.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b3e91f27c5a4'
down_revision: Union[str, Sequence[str], None] = 'a1c7d40e9b32'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("deadline", sa.Date(), nullable=True))
    op.add_column("messages", sa.Column("amount", sa.Numeric(14, 2), nullable=True))
    op.add_column("messages", sa.Column("currency", sa.String(length=3), nullable=True))
    # server_default só é necessário enquanto a coluna é adicionada: os e-mails
    # que já estão na tabela ainda não têm valor. Depois quem define é a aplicação.
    op.add_column(
        "messages",
        sa.Column("action_required", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("messages", "action_required", server_default=None)

    op.create_index(
        "ix_messages_deadline",
        "messages",
        ["deadline"],
        postgresql_where=sa.text("deadline IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_messages_deadline", table_name="messages")
    op.drop_column("messages", "action_required")
    op.drop_column("messages", "currency")
    op.drop_column("messages", "amount")
    op.drop_column("messages", "deadline")
