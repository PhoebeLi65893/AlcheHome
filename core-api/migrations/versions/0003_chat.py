"""chat: at most one ACTIVE conversation per user per channel

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX uq_conversation_active ON conversations (user_id, channel) "
        "WHERE status = 'ACTIVE'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_conversation_active")
