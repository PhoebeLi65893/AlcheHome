"""tickets: audit trail, photos on tickets, ticket card on bot messages

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"

STATEMENTS = [
    """CREATE TABLE ticket_events (
        id BIGSERIAL PRIMARY KEY,
        ticket_id UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
        from_status TEXT,
        to_status TEXT NOT NULL,
        actor TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
    )""",
    "CREATE INDEX idx_ticket_events_ticket ON ticket_events (ticket_id, created_at)",
    """CREATE TABLE ticket_media (
        ticket_id UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
        upload_id UUID NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
        PRIMARY KEY (ticket_id, upload_id)
    )""",
    "ALTER TABLE messages ADD COLUMN ticket_id UUID REFERENCES tickets(id)",
    "ALTER TABLE tickets ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now()",
    "ALTER TABLE tickets ADD CONSTRAINT tickets_severity_check "
    "CHECK (severity IS NULL OR severity IN ('LOW','MEDIUM','HIGH','EMERGENCY'))",
]


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("ALTER TABLE tickets DROP CONSTRAINT IF EXISTS tickets_severity_check")
    op.execute("ALTER TABLE tickets DROP COLUMN IF EXISTS updated_at")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS ticket_id")
    op.execute("DROP TABLE IF EXISTS ticket_media")
    op.execute("DROP TABLE IF EXISTS ticket_events")
