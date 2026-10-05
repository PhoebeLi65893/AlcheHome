import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import get_engine

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set (needs migrated Postgres)"
)


def test_core_tables_and_pgvector_exist():
    with get_engine().connect() as c:
        tables = {
            r[0]
            for r in c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        }
        ext = c.execute(text("SELECT count(*) FROM pg_extension WHERE extname='vector'")).scalar()
    assert {"users", "handymen", "tickets", "conversations", "messages"} <= tables
    assert ext == 1


def test_invalid_ticket_category_rejected():
    with pytest.raises(IntegrityError), get_engine().begin() as c:
        uid = c.execute(
            text(
                "INSERT INTO users (role, email) VALUES ('CUSTOMER','t@example.com') "
                "ON CONFLICT (email) DO UPDATE SET role='CUSTOMER' RETURNING id"
            )
        ).scalar_one()
        c.execute(
            text(
                "INSERT INTO tickets (customer_id, category, issue_summary, urgency, location_zip)"
                " VALUES (:u,'MAGIC','x','FLEXIBLE','92101')"
            ),
            {"u": uid},
        )
