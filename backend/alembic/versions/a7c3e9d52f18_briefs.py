"""daily briefs

Revision ID: a7c3e9d52f18
Revises: f5b2d8e41a73
Create Date: 2026-10-11 04:00:00.000000

Resumo matinal: a introdução do dia feita pela IA e a marca de envio por e-mail.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7c3e9d52f18'
down_revision: Union[str, Sequence[str], None] = 'f5b2d8e41a73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "briefs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("intro", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("emailed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("day"),
    )


def downgrade() -> None:
    op.drop_table("briefs")
