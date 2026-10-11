"""handyman profile: specialties and phone verification codes

Revision ID: 0013
Revises: 0012
"""

from alembic import op

revision = "0013"
down_revision = "0012"


def upgrade() -> None:
    op.execute("ALTER TABLE handymen ADD COLUMN specialties TEXT[] NOT NULL DEFAULT '{}'")
    op.execute(
        """CREATE TABLE phone_verifications (
            user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            phone_e164 TEXT NOT NULL,
            code_hash TEXT NOT NULL,
            attempts INT NOT NULL DEFAULT 0,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )"""
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS phone_verifications")
    op.execute("ALTER TABLE handymen DROP COLUMN IF EXISTS specialties")
