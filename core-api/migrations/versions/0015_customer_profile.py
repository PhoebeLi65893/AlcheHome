"""customer profile: saved home ZIP; handyman choice to share their phone number

Revision ID: 0015
Revises: 0014
"""

from alembic import op

revision = "0015"
down_revision = "0014"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN home_zip TEXT "
        "CHECK (home_zip IS NULL OR home_zip ~ '^[0-9]{5}$')"
    )
    op.execute("ALTER TABLE handymen ADD COLUMN share_phone BOOLEAN NOT NULL DEFAULT FALSE")


def downgrade() -> None:
    op.execute("ALTER TABLE handymen DROP COLUMN IF EXISTS share_phone")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS home_zip")
