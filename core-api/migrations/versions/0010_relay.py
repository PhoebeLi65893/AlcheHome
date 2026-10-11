"""relay: customer <-> handyman messages are logged in messages, tagged with their ticket

Revision ID: 0010
Revises: 0009
"""

from alembic import op

revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    op.execute("ALTER TABLE messages ADD COLUMN relay_ticket_id UUID REFERENCES tickets(id)")
    op.execute(
        "CREATE INDEX idx_messages_relay ON messages (relay_ticket_id, created_at) "
        "WHERE relay_ticket_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_messages_relay")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS relay_ticket_id")
