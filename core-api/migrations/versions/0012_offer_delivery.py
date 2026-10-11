"""dispatch_offers: remember offers delivered in the app (not texted) and their SMS reminder

Revision ID: 0012
Revises: 0011
"""

from alembic import op

revision = "0012"
down_revision = "0011"


def upgrade() -> None:
    op.execute("ALTER TABLE dispatch_offers ADD COLUMN via_app BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE dispatch_offers ADD COLUMN reminded_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE dispatch_offers DROP COLUMN IF EXISTS reminded_at")
    op.execute("ALTER TABLE dispatch_offers DROP COLUMN IF EXISTS via_app")
