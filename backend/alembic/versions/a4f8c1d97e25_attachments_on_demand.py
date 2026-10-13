"""attachments on demand and in replies

Revision ID: a4f8c1d97e25
Revises: e8b3f1c62a07
Create Date: 2026-10-13 12:00:00.000000

Os anexos dos e-mails são baixados no clique direto da caixa; não os
guardamos. Para achar o anexo certo no e-mail, gravamos a posição dele
entre os anexos (part_index); s3_key deixa de ser obrigatório — não há
armazenamento de arquivos. Na resposta gravamos nomes e tamanhos dos
arquivos anexados — para o histórico; os arquivos em si também não ficam.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a4f8c1d97e25'
down_revision: Union[str, Sequence[str], None] = 'e8b3f1c62a07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("attachments", sa.Column("part_index", sa.Integer(), nullable=True))
    op.alter_column(
        "attachments", "s3_key", existing_type=sa.String(length=500), nullable=True
    )
    op.add_column(
        "replies",
        sa.Column(
            "attachments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("replies", "attachments")
    # O esquema antigo não aceitava valores vazios.
    op.execute("UPDATE attachments SET s3_key = '' WHERE s3_key IS NULL")
    op.alter_column(
        "attachments", "s3_key", existing_type=sa.String(length=500), nullable=False
    )
    op.drop_column("attachments", "part_index")
