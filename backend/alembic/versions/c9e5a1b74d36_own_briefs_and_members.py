"""own briefs and members

Revision ID: c9e5a1b74d36
Revises: b8d4f0a63c21
Create Date: 2026-10-12 04:00:00.000000

Cada um tem o seu resumo (user_id), e não um por servidor: com o cadastro
pelo link, cada pessoa tem o próprio e-mail. Os resumos antigos ficam com
o primeiro dono — antes desta migração não existia nenhum outro.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c9e5a1b74d36'
down_revision: Union[str, Sequence[str], None] = 'b8d4f0a63c21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("briefs", sa.Column("user_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE briefs SET user_id = (SELECT min(id) FROM users WHERE role = 'owner')"
    )
    # Resumo sem dono (banco sem usuários) não serve para ninguém.
    op.execute("DELETE FROM briefs WHERE user_id IS NULL")
    op.alter_column("briefs", "user_id", nullable=False)
    op.create_foreign_key("fk_briefs_user", "briefs", "users", ["user_id"], ["id"])
    op.create_index("ix_briefs_user_id", "briefs", ["user_id"])
    op.drop_constraint("briefs_day_key", "briefs", type_="unique")
    op.create_unique_constraint("uq_brief_user_day", "briefs", ["user_id", "day"])


def downgrade() -> None:
    op.drop_constraint("uq_brief_user_day", "briefs", type_="unique")
    op.execute(
        "DELETE FROM briefs WHERE user_id <> (SELECT min(id) FROM users WHERE role = 'owner')"
    )
    op.create_unique_constraint("briefs_day_key", "briefs", ["day"])
    op.drop_index("ix_briefs_user_id", "briefs")
    op.drop_constraint("fk_briefs_user", "briefs", type_="foreignkey")
    op.drop_column("briefs", "user_id")
