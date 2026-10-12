"""translations

Revision ID: d2a7c4e19f58
Revises: c9e5a1b74d36
Create Date: 2026-10-12 05:00:00.000000

Tradução do e-mail pelo botão — fica salva no próprio e-mail.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd2a7c4e19f58'
down_revision: Union[str, Sequence[str], None] = 'c9e5a1b74d36'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("subject_translated", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("body_translated", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "body_translated")
    op.drop_column("messages", "subject_translated")
