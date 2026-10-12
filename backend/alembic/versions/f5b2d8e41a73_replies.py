"""replies: drafts, sending and the journal

Revision ID: f5b2d8e41a73
Revises: e3a9c7f15b20
Create Date: 2026-10-11 02:00:00.000000

Rascunhos de resposta, envio e registro do que foi enviado. O e-mail
ganha endereço de resposta (Reply-To), a marca «resolvido» e «lembrar em».

A migração não mexe nos dados: nos e-mails antigos os campos novos ficam
vazios, ou seja, «não resolvido, não adiado, responder ao remetente».
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f5b2d8e41a73'
down_revision: Union[str, Sequence[str], None] = 'e3a9c7f15b20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("reply_to", sa.String(length=320), nullable=True))
    op.add_column("messages", sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "messages", sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "replies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("to_address", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("ai_text", sa.Text(), nullable=False),
        sa.Column("final_text", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("sent_message_id", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("sent_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["sent_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_replies_message_id", "replies", ["message_id"])


def downgrade() -> None:
    op.drop_index("ix_replies_message_id", table_name="replies")
    op.drop_table("replies")
    op.drop_column("messages", "snoozed_until")
    op.drop_column("messages", "handled_at")
    op.drop_column("messages", "reply_to")
