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
    new_user,
    offers,
    ticket_status,
    world,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set (needs migrated Postgres)"
)

client = TestClient(app)


def headers_for(uid, role):
    return {"Authorization": f"Bearer {create_access_token(str(uid), role)}"}


@pytest.fixture
def admin(world):  # noqa: F811
    uid = new_user(world, "ADMIN")
    return uid, headers_for(uid, "ADMIN")


def unmatched_ticket(world):  # noqa: F811
    tid, num = new_ticket(world)
    dispatch.start_dispatch(tid)  # nobody serves the ZIP yet, so it becomes UNMATCHED
    assert ticket_status(tid) == "UNMATCHED"
    return tid, num


def test_only_admins_can_use_the_ops_api(world):  # noqa: F811
    cust = new_user(world, "CUSTOMER")
    assert client.get("/admin/tickets").status_code == 401
    r = client.get("/admin/tickets", headers=headers_for(cust, "CUSTOMER"))
    assert r.status_code == 403
    tid, _ = unmatched_ticket(world)
    r = client.post(
        f"/admin/tickets/{tid}/assign",
        json={"handyman_id": str(cust)},
        headers=headers_for(cust, "CUSTOMER"),
    )
    assert r.status_code == 403


def test_lists_unmatched_tickets_not_other_statuses(world, admin):  # noqa: F811
    tid, num = unmatched_ticket(world)
    open_tid, _ = new_ticket(world)
    numbers = {t["number"] for t in client.get("/admin/tickets", headers=admin[1]).json()}
    assert num in numbers
    ids = {t["id"] for t in client.get("/admin/tickets", headers=admin[1]).json()}
    assert str(tid) in ids and str(open_tid) not in ids
    assert client.get("/admin/tickets?status=OPEN", headers=admin[1]).status_code == 422


def test_choices_rank_eligible_first_then_the_rest(world, admin):  # noqa: F811
    tid, _ = unmatched_ticket(world)
    new_handyman(world, "Low", 3.0)
    new_handyman(world, "High", 4.9)
    other, _ = new_handyman(world, "Elsewhere", 5.0)
    new_handyman(world, "Carpenter", 5.0, skills=("CARPENTRY",))
    with get_engine().begin() as c:
        c.execute(
            text("UPDATE handymen SET service_zips = '{99999}' WHERE user_id = :u"), {"u": other}
        )
    r = client.get(f"/admin/tickets/{tid}/handymen", headers=admin[1])
    assert r.status_code == 200
    mine = {"High", "Low", "Elsewhere"}  # the seeded handymen may be in the list too
    got = [
        (h["display_name"], h["score"] is not None) for h in r.json() if h["display_name"] in mine
    ]
    assert got == [("High", True), ("Low", True), ("Elsewhere", False)]
    assert [h for h in r.json() if h["display_name"] == "Elsewhere"][0]["covers_zip"] is False


def test_assign_unmatched_ticket(world, admin):  # noqa: F811
    tid, num = unmatched_ticket(world)
    uid, phone = new_handyman(world, "Chosen", 4.0)
    world.messages.clear()
    r = client.post(
        f"/admin/tickets/{tid}/assign", json={"handyman_id": str(uid)}, headers=admin[1]
    )
    assert r.status_code == 200 and r.json()["status"] == "ASSIGNED"
    assert ticket_status(tid) == "ASSIGNED"
    with get_engine().connect() as c:
        assigned = c.execute(
            text("SELECT assigned_handyman_id FROM tickets WHERE id = :t"), {"t": tid}
        ).scalar()
        events = c.execute(
            text("SELECT to_status, actor FROM ticket_events WHERE ticket_id = :t ORDER BY id"),
            {"t": tid},
        ).all()
    assert str(assigned) == str(uid)
    assert [e.to_status for e in events][-3:] == ["UNMATCHED", "MATCHING", "ASSIGNED"]
    assert events[-1].actor == f"admin:{admin[0]}"
    assert offers(tid) == [("Chosen", "ACCEPTED")]
    assert [to for to, _ in world.messages] == [phone]  # handyman is told; customer is on WEB
    assert f"#{num}" in world.messages[0][1]


def test_assign_works_for_someone_outside_the_area(world, admin):  # noqa: F811
    tid, _ = unmatched_ticket(world)
    uid, _ = new_handyman(world, "Far", 4.0)
    with get_engine().begin() as c:
        c.execute(
            text("UPDATE handymen SET service_zips = '{99999}' WHERE user_id = :u"), {"u": uid}
        )
    r = client.post(
        f"/admin/tickets/{tid}/assign", json={"handyman_id": str(uid)}, headers=admin[1]
    )
    assert r.status_code == 200


def test_assign_withdraws_a_pending_offer(world, admin):  # noqa: F811
    first, _ = new_handyman(world, "Offered", 4.9)
    second, _ = new_handyman(world, "Manual", 4.0)
    tid, num = new_ticket(world)
    dispatch.start_dispatch(tid)
    assert offers(tid) == [("Offered", "SENT")]
    r = client.post(
        f"/admin/tickets/{tid}/assign", json={"handyman_id": str(second)}, headers=admin[1]
    )
    assert r.status_code == 200
    assert sorted(offers(tid)) == [("Manual", "ACCEPTED"), ("Offered", "EXPIRED")]
    assert "no longer available" in dispatch.handle_handyman_reply(first, f"ACCEPT {num}")[0]
    assert ticket_status(tid) == "ASSIGNED"


def test_assign_after_earlier_decline_reuses_the_offer_row(world, admin):  # noqa: F811
    a, _ = new_handyman(world, "Alpha", 4.9)
    tid, num = new_ticket(world)
    dispatch.start_dispatch(tid)
    dispatch.handle_handyman_reply(a, f"DECLINE {num}")
    assert ticket_status(tid) == "UNMATCHED"
    r = client.post(f"/admin/tickets/{tid}/assign", json={"handyman_id": str(a)}, headers=admin[1])
    assert r.status_code == 200
    assert offers(tid) == [("Alpha", "ACCEPTED")]


def test_cannot_assign_a_finished_or_open_ticket(world, admin):  # noqa: F811
    uid, _ = new_handyman(world, "Chosen", 4.0)
    for status in ("OPEN", "CANCELLED", "ASSIGNED"):
        tid, _ = new_ticket(world, status=status)
        r = client.post(
            f"/admin/tickets/{tid}/assign", json={"handyman_id": str(uid)}, headers=admin[1]
        )
        assert r.status_code == 409, status


def test_assign_unknown_handyman_or_ticket(world, admin):  # noqa: F811
    tid, _ = unmatched_ticket(world)
    nobody = "00000000-0000-0000-0000-000000000000"
    r = client.post(f"/admin/tickets/{tid}/assign", json={"handyman_id": nobody}, headers=admin[1])
    assert r.status_code == 404
    uid, _ = new_handyman(world, "Real", 4.0)
    r = client.post(
        f"/admin/tickets/{nobody}/assign", json={"handyman_id": str(uid)}, headers=admin[1]
    )
    assert r.status_code == 404
    assert ticket_status(tid) == "UNMATCHED"


def test_retry_dispatch_after_adding_a_handyman(world, admin):  # noqa: F811
    tid, _ = unmatched_ticket(world)
    new_handyman(world, "Late", 4.0)
    r = client.post(f"/admin/tickets/{tid}/retry", headers=admin[1])
    assert r.json() == {"started": True}
    assert ticket_status(tid) == "MATCHING"
    assert client.post(f"/admin/tickets/{tid}/retry", headers=admin[1]).json() == {"started": False}
