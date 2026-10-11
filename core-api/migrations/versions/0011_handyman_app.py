"""handyman app: presence, read state, invite links, per-job AI assistant history

Revision ID: 0011
Revises: 0010
"""

from alembic import op

revision = "0011"
down_revision = "0010"

STATEMENTS = [
    "ALTER TABLE users ADD COLUMN last_seen_at TIMESTAMPTZ",
    """CREATE TABLE thread_reads (
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        ticket_id UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
        last_read_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY (user_id, ticket_id)
    )""",
    """CREATE TABLE invite_tokens (
        token_hash TEXT PRIMARY KEY,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        expires_at TIMESTAMPTZ NOT NULL,
        used_at TIMESTAMPTZ
    )""",
    """CREATE TABLE pro_ai_messages (
        id BIGSERIAL PRIMARY KEY,
        handyman_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        ticket_id UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
        sender TEXT NOT NULL CHECK (sender IN ('USER','BOT')),
        body TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
    )""",
    "CREATE INDEX idx_pro_ai_job ON pro_ai_messages (handyman_id, ticket_id, id)",
]


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pro_ai_messages")
    op.execute("DROP TABLE IF EXISTS invite_tokens")
    op.execute("DROP TABLE IF EXISTS thread_reads")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS last_seen_at")
