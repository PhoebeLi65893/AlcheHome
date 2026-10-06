"""messages.flag marks special bot replies (e.g. EMERGENCY safety guidance)

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.execute("ALTER TABLE messages ADD COLUMN flag TEXT CHECK (flag IN ('EMERGENCY'))")


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS flag")
