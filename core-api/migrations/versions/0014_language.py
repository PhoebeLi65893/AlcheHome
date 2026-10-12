"""language: per-user language and translated relay messages

Revision ID: 0014
Revises: 0013
"""

from alembic import op

revision = "0014"
down_revision = "0013"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN language TEXT NOT NULL DEFAULT 'en' "
        "CHECK (language IN ('en','zh'))"
    )
    op.execute("ALTER TABLE messages ADD COLUMN lang TEXT")
    op.execute("ALTER TABLE messages ADD COLUMN translations JSONB NOT NULL DEFAULT '{}'")


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS translations")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS lang")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS language")
