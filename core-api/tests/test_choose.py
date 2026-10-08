import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import dispatch
from app.db import get_engine
from app.main import app
from app.security import create_access_token
from tests.test_dispatch import (  # noqa: F401  (world is a fixture)
    new_handyman,
    new_ticket,
    offers,
    ticket_status,
    world,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set (needs migrated Postgres)"
)

client = TestClient(app)


def owner_of(tid):
    with get_engine().connect() as c:
        uid = c.execute(text("SELECT customer_id FROM tickets WHERE id = :t"), {"t": tid}).scalar()
    return uid, {"Authorization": f"Bearer {create_access_token(str(uid), 'CUSTOMER')}"}


def stranger(world):  # noqa: F811
    from tests.test_dispatch import new_user

    uid = new_user(world, "CUSTOMER")
    return {"Authorization": f"Bearer {create_access_token(str(uid), 'CUSTOMER')}"}


def test_options_are_ranked_trimmed_and_private(world):  # noqa: F811
    best, _ = new_handyman(world, "Best", 4.9)
    low, _ = new_handyman(world, "Low", 3.0)
    tid, _ = new_ticket(world)
    _, h = owner_of(tid)
    r = client.get(f"/tickets/{tid}/handymen", headers=h)
    assert r.status_code == 200
    assert [(o["display_name"], o["recommended"]) for o in r.json()] == [
        ("Best", True),
        ("Low", False),
    ]
    assert set(r.json()[0]) == {
        "handyman_id",
        "display_name",
        "rating_avg",
        "response_rate",
        "recommended",
    }
    assert client.get(f"/tickets/{tid}/handymen", headers=stranger(world)).status_code == 404
    assert client.get(f"/tickets/{tid}/handymen").status_code == 401


def test_options_empty_once_the_search_started(world):  # noqa: F811
    new_handyman(world, "Best", 4.9)
    tid, _ = new_ticket(world, status="MATCHING")
    _, h = owner_of(tid)
    assert client.get(f"/tickets/{tid}/handymen", headers=h).json() == []


def test_customer_choice_gets_the_first_offer_then_ranking_continues(world):  # noqa: F811
    best, _ = new_handyman(world, "Best", 4.9)
    mid, _ = new_handyman(world, "Mid", 4.0)
    low, low_phone = new_handyman(world, "Low", 3.0)
    tid, num = new_ticket(world)
    uid, h = owner_of(tid)
    r = client.post(f"/tickets/{tid}/dispatch", json={"handyman_id": str(low)}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "MATCHING"
    assert offers(tid) == [("Low", "SENT")]
    assert world.messages[0][0] == low_phone
    with get_engine().connect() as c:
        actor = c.execute(
            text("SELECT actor FROM ticket_events WHERE ticket_id = :t ORDER BY id DESC LIMIT 1"),
            {"t": tid},
        ).scalar()
    assert actor == f"customer:{uid}"
    dispatch.handle_handyman_reply(low, f"DECLINE {num}")  # preferred one says no
    assert offers(tid) == [("Low", "DECLINED"), ("Best", "SENT")]  # then best ranked
    dispatch.handle_handyman_reply(best, f"DECLINE {num}")
    assert offers(tid)[-1] == ("Mid", "SENT")
    dispatch.handle_handyman_reply(mid, f"ACCEPT {num}")
    assert ticket_status(tid) == "ASSIGNED"


def test_no_choice_means_best_ranked_first(world):  # noqa: F811
    new_handyman(world, "Best", 4.9)
    new_handyman(world, "Low", 3.0)
    tid, _ = new_ticket(world)
    _, h = owner_of(tid)
    r = client.post(f"/tickets/{tid}/dispatch", json={}, headers=h)
    assert r.status_code == 200
    assert offers(tid) == [("Best", "SENT")]


def test_choice_falls_through_to_unmatched_when_everyone_declines(world):  # noqa: F811
    a, _ = new_handyman(world, "Alpha", 4.9)
    tid, num = new_ticket(world)
    _, h = owner_of(tid)
    client.post(f"/tickets/{tid}/dispatch", json={"handyman_id": str(a)}, headers=h)
    dispatch.handle_handyman_reply(a, f"DECLINE {num}")
    assert ticket_status(tid) == "UNMATCHED"


def test_ineligible_choice_is_refused_and_nothing_changes(world):  # noqa: F811
    new_handyman(world, "Best", 4.9)
    other, _ = new_handyman(world, "Elsewhere", 5.0)
    with get_engine().begin() as c:
        c.execute(
            text("UPDATE handymen SET service_zips = '{99999}' WHERE user_id = :u"), {"u": other}
        )
    tid, _ = new_ticket(world)
    _, h = owner_of(tid)
    r = client.post(f"/tickets/{tid}/dispatch", json={"handyman_id": str(other)}, headers=h)
    assert r.status_code == 400
    assert ticket_status(tid) == "OPEN" and offers(tid) == []


def test_dispatch_only_for_the_owner_and_only_once(world):  # noqa: F811
    new_handyman(world, "Best", 4.9)
    tid, _ = new_ticket(world)
    _, h = owner_of(tid)
    assert (
        client.post(f"/tickets/{tid}/dispatch", json={}, headers=stranger(world)).status_code == 404
    )
    assert client.post(f"/tickets/{tid}/dispatch", json={}, headers=h).status_code == 200
    assert client.post(f"/tickets/{tid}/dispatch", json={}, headers=h).status_code == 409


def test_ticket_detail_reports_matching_progress(world):  # noqa: F811
    a, _ = new_handyman(world, "Alpha", 4.9)
    new_handyman(world, "Bravo", 4.0)
    tid, num = new_ticket(world)
    _, h = owner_of(tid)
    d = client.get(f"/tickets/{tid}", headers=h).json()
    assert d["offers_sent"] == 0 and d["offer_expires_at"] is None and d["handyman_name"] is None
    client.post(f"/tickets/{tid}/dispatch", json={}, headers=h)
    d = client.get(f"/tickets/{tid}", headers=h).json()
    assert d["status"] == "MATCHING" and d["offers_sent"] == 1 and d["max_offers"] == 5
    assert d["offer_expires_at"] is not None
    dispatch.handle_handyman_reply(a, f"ACCEPT {num}")
    d = client.get(f"/tickets/{tid}", headers=h).json()
    assert d["status"] == "ASSIGNED" and d["handyman_name"] == "Alpha"
    assert d["offer_expires_at"] is None
