"""indexes for tab counters and the parsing queue

Revision ID: a1c7d40e9b32
Revises: 78952e82b325
Create Date: 2026-09-10 18:20:00.000000

Os contadores das abas são uma agregação sobre a tabela inteira de e-mails,
feita a cada carregamento da caixa de entrada. Com mil e-mails ninguém nota;
com cinquenta mil, são dezenas de megabytes lidos toda vez.

A migração não mexe nos dados.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1c7d40e9b32'
down_revision: Union[str, Sequence[str], None] = '78952e82b325'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # As três colunas que os contadores usam estão no próprio índice —
    # o banco lê o índice em vez da tabela com os corpos dos e-mails.
    op.create_index(
        "ix_messages_account_category_read",
        "messages",
        ["account_id", "category", "is_read"],
    )
    # Fila de triagem: o worker procura e-mails sem categoria. O índice
    # parcial encolhe quase a zero quando a IA alcança a caixa.
    op.create_index(
        "ix_messages_unsorted",
        "messages",
        ["sent_at"],
        postgresql_where=sa.text("category IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_messages_unsorted", table_name="messages")
    op.drop_index("ix_messages_account_category_read", table_name="messages")
