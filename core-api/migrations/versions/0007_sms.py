"""sms: opt-out flag on users, webhook idempotency log

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN sms_opted_out BOOLEAN NOT NULL DEFAULT FALSE")
    # One row per provider event we accepted, so redeliveries are ignored. No message content.
    op.execute(
        """CREATE TABLE webhook_events (
            provider TEXT NOT NULL,
            external_id TEXT NOT NULL,
            received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (provider, external_id)
        )"""
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS webhook_events")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS sms_opted_out")
