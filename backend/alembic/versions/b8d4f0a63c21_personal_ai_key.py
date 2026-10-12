"""personal ai key

Revision ID: b8d4f0a63c21
Revises: a7c3e9d52f18
Create Date: 2026-10-11 14:00:00.000000

Chave própria do Gemini por usuário: o e-mail dele é triado por conta dele.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8d4f0a63c21'
down_revision: Union[str, Sequence[str], None] = 'a7c3e9d52f18'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("ai_key_ciphertext", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "ai_key_ciphertext")
