"""dispatch: job offers sent to handymen

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    op.execute(
        """CREATE TABLE dispatch_offers (
            id BIGSERIAL PRIMARY KEY,
            ticket_id UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            handyman_id UUID NOT NULL REFERENCES handymen(user_id),
            status TEXT NOT NULL DEFAULT 'SENT'
                CHECK (status IN ('SENT','ACCEPTED','DECLINED','EXPIRED')),
            message TEXT NOT NULL,
            sent_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            expires_at TIMESTAMPTZ NOT NULL,
            responded_at TIMESTAMPTZ,
            UNIQUE (ticket_id, handyman_id)
        )"""
    )
    op.execute(
        "CREATE INDEX idx_offers_pending ON dispatch_offers (expires_at) WHERE status = 'SENT'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dispatch_offers")
