"""trigram indexes for search

Revision ID: e3a9c7f15b20
Revises: d7f4b1e60c92
Create Date: 2026-10-11 00:30:00.000000

A busca procura um pedaço de palavra em qualquer ponto do texto: «boleto»
acha também «boletos», «inter» acha «Banco Inter». Um índice comum não
acelera esse tipo de busca — ele precisa do começo da string. O de
trigramas (pg_trgm) corta o texto em trios de letras e acha o pedaço em
qualquer lugar. Sem ele, cada busca lê todos os corpos de e-mail em
sequência, e com vinte e cinco caixas são centenas de megabytes.

A migração não mexe nos dados.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e3a9c7f15b20'
down_revision: Union[str, Sequence[str], None] = 'd7f4b1e60c92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = ("subject", "sender", "sender_name", "summary", "body_text")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for column in COLUMNS:
        op.create_index(
            f"ix_messages_{column}_trgm",
            "messages",
            [column],
            postgresql_using="gin",
            postgresql_ops={column: "gin_trgm_ops"},
        )


def downgrade() -> None:
    for column in COLUMNS:
        op.drop_index(f"ix_messages_{column}_trgm", table_name="messages")
