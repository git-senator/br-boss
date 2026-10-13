"""session version and last totp step

Revision ID: e8b3f1c62a07
Revises: d2a7c4e19f58
Create Date: 2026-10-12 12:00:00.000000

«Sair» tem que derrubar o token de verdade, e não só apagar o cookie
deste navegador: token_version vai dentro do token, e aumentá-la invalida
todos os emitidos antes. totp_last_step guarda o último código aceito —
o mesmo código não serve duas vezes.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e8b3f1c62a07'
down_revision: Union[str, Sequence[str], None] = 'd2a7c4e19f58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("users", sa.Column("totp_last_step", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "totp_last_step")
    op.drop_column("users", "token_version")
