"""conversations.ticket_requested: the customer pressed Create request

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE conversations ADD COLUMN ticket_requested BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS ticket_requested")
