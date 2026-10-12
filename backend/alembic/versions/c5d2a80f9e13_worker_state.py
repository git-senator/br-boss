"""worker state that survives a restart

Revision ID: c5d2a80f9e13
Revises: b3e91f27c5a4
Create Date: 2026-09-10 21:55:00.000000

A pausa da triagem vivia só na memória do processo. A cada rebuild o
worker esquecia dela e voltava a esmurrar a porta fechada, gastando o
resto da cota diária em recusas.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c5d2a80f9e13'
down_revision: Union[str, Sequence[str], None] = 'b3e91f27c5a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "worker_state",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("worker_state")
