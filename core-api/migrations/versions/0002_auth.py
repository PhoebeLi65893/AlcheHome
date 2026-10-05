"""auth: password hash, display name, refresh tokens

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"

STATEMENTS = [
    "ALTER TABLE users ADD COLUMN password_hash TEXT, ADD COLUMN display_name TEXT",
    """CREATE TABLE refresh_tokens (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token_hash TEXT NOT NULL UNIQUE,
        expires_at TIMESTAMPTZ NOT NULL,
        revoked_at TIMESTAMPTZ,
        replaced_by UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX idx_refresh_tokens_user ON refresh_tokens (user_id)",
]


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS refresh_tokens")
    op.execute(
        "ALTER TABLE users DROP COLUMN IF EXISTS password_hash, DROP COLUMN IF EXISTS display_name"
    )
