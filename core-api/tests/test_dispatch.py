import os
import random
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import dispatch
from app.channels import twilio
from app.channels.twilio import compute_signature
from app.db import get_engine
from app.main import app

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set (needs migrated Postgres)"
)

client = TestClient(app)


def random_phone():
    return "+1619" + str(random.randint(5000000, 9999999))


@pytest.fixture
def world(monkeypatch):
    """A private ZIP code, handymen created on demand, and every SMS captured, not sent."""
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(twilio, "send_sms", lambda to, body: sent.append((to, body)))
    monkeypatch.delenv("DISPATCH_TIMEOUT_S", raising=False)

    class World:
        zip = "9" + str(random.randint(1000, 9999))
        messages = sent
        users: list

    w = World()
    w.users = []
    yield w
    ids = [str(u) for u in w.users]
    with get_engine().begin() as c:
        c.execute(
            text(
                "DELETE FROM messages WHERE ticket_id IN (SELECT id FROM tickets "
                "WHERE customer_id = ANY(CAST(:i AS uuid[])))"
            ),
            {"i": ids},
        )
        c.execute(
            text("DELETE FROM conversations WHERE user_id = ANY(CAST(:i AS uuid[]))"), {"i": ids}
        )
        c.execute(
            text("DELETE FROM tickets WHERE customer_id = ANY(CAST(:i AS uuid[]))"), {"i": ids}
        )
        c.execute(text("DELETE FROM users WHERE id = ANY(CAST(:i AS uuid[]))"), {"i": ids})


def new_user(w, role, phone=None):
    with get_engine().begin() as c:
        uid = c.execute(
            text(
                "INSERT INTO users (role, email, phone_e164, preferred_channel) "
                "VALUES (:r, :e, :p, 'SMS') RETURNING id"
            ),
            {"r": role, "e": f"{uuid.uuid4().hex}@example.com", "p": phone},
        ).scalar_one()
    w.users.append(uid)
    return uid


def new_handyman(w, name, rating, skills=("PLUMBING",), rate=0.9):
    phone = random_phone()
    uid = new_user(w, "HANDYMAN", phone)
    with get_engine().begin() as c:
        c.execute(
            text(
                "INSERT INTO handymen (user_id, display_name, service_zips, rating_avg, "
                "response_rate, verified_at) VALUES (:u, :n, :z, :r, :rr, now())"
            ),
            {"u": uid, "n": name, "z": [w.zip], "r": rating, "rr": rate},
        )
        for s in skills:
            c.execute(text("INSERT INTO handymen_skills VALUES (:u, :c)"), {"u": uid, "c": s})
    return uid, phone


def new_ticket(w, urgency="SAME_DAY", status="OPEN", channel="WEB"):
    cust = new_user(w, "CUSTOMER", random_phone())
    with get_engine().begin() as c:
        tid, num = c.execute(
            text(
                "INSERT INTO tickets (customer_id, category, issue_summary, urgency, "
                "location_zip, status) VALUES (:c, 'PLUMBING', 'Kitchen sink leaking badly', "
                ":u, :z, :s) RETURNING id, ticket_number"
            ),
            {"c": cust, "u": urgency, "z": w.zip, "s": status},
        ).one()
        c.execute(
            text("INSERT INTO conversations (user_id, channel, ticket_id) VALUES (:u, :ch, :t)"),
            {"u": cust, "ch": channel, "t": tid},
        )
    return tid, num


def ticket_status(tid):
    with get_engine().connect() as c:
        return c.execute(text("SELECT status FROM tickets WHERE id = :t"), {"t": tid}).scalar()


def offers(tid):
    with get_engine().connect() as c:
        rows = c.execute(
            text(
                "SELECT h.display_name AS name, o.status FROM dispatch_offers o "
                "JOIN handymen h ON h.user_id = o.handyman_id WHERE o.ticket_id = :t "
                "ORDER BY o.sent_at"
            ),
            {"t": tid},
        ).all()
    return [(r.name, r.status) for r in rows]


def expire_offer_now(tid):
    with get_engine().begin() as c:
        c.execute(
            text(
                "UPDATE dispatch_offers SET expires_at = now() - interval '1 second' "
                "WHERE ticket_id = :t AND status = 'SENT'"
            ),
            {"t": tid},
        )


def reply(uid, body):
    answer, others = dispatch.handle_handyman_reply(uid, body)
    dispatch.deliver(others)
    return answer


def test_dispatch_offers_best_handyman_with_zip_only(world):
    _, best_phone = new_handyman(world, "Best", 4.9)
    new_handyman(world, "Okay", 4.0)
    new_handyman(world, "Carpenter", 5.0, skills=("CARPENTRY",))
    tid, num = new_ticket(world)
    assert dispatch.start_dispatch(tid)
    assert ticket_status(tid) == "MATCHING"
    assert offers(tid) == [("Best", "SENT")]
    [(to, body)] = world.messages
    assert to == best_phone
    assert f"#{num}" in body and f"ACCEPT {num}" in body and world.zip in body
    assert "Expires in 15 min" in body


@pytest.mark.parametrize(("urgency", "expected"), [("EMERGENCY", "3 min"), ("FLEXIBLE", "2 h")])
def test_timeout_depends_on_urgency(world, urgency, expected):
    new_handyman(world, "Best", 4.9)
    tid, _ = new_ticket(world, urgency=urgency)
    dispatch.start_dispatch(tid)
    assert f"Expires in {expected}" in world.messages[0][1]


def test_start_dispatch_only_for_open_or_unmatched(world):
    new_handyman(world, "Best", 4.9)
    tid, _ = new_ticket(world, status="CANCELLED")
    assert not dispatch.start_dispatch(tid)
    assert offers(tid) == []


def test_accept_assigns_ticket_and_tells_customer(world):
    uid, _ = new_handyman(world, "Best", 4.9)
    tid, num = new_ticket(world, channel="SMS")
    dispatch.start_dispatch(tid)
    world.messages.clear()
    assert "assigned" in reply(uid, f"accept {num}")
    assert ticket_status(tid) == "ASSIGNED"
    assert offers(tid) == [("Best", "ACCEPTED")]
    with get_engine().connect() as c:
        assigned = c.execute(
            text("SELECT assigned_handyman_id FROM tickets WHERE id = :t"), {"t": tid}
        ).scalar()
        actor = c.execute(
            text("SELECT actor FROM ticket_events WHERE ticket_id = :t ORDER BY id DESC LIMIT 1"),
            {"t": tid},
        ).scalar()
        bot = c.execute(
            text(
                "SELECT m.body FROM messages m JOIN conversations c ON c.id = m.conversation_id "
                "WHERE c.ticket_id = :t"
            ),
            {"t": tid},
        ).scalar()
    assert str(assigned) == str(uid)
    assert actor == f"handyman:{uid}"
    assert "Best has accepted" in bot
    assert len(world.messages) == 1 and "Best has accepted" in world.messages[0][1]


def test_number_is_optional_when_one_offer_is_open(world):
    uid, _ = new_handyman(world, "Best", 4.9)
    tid, _ = new_ticket(world)
    dispatch.start_dispatch(tid)
    assert "assigned" in reply(uid, "Yes")
    assert ticket_status(tid) == "ASSIGNED"


def test_decline_rolls_to_next_then_unmatched_when_out_of_handymen(world):
    a, _ = new_handyman(world, "Alpha", 4.9)
    b, b_phone = new_handyman(world, "Bravo", 4.5)
    tid, num = new_ticket(world)
    dispatch.start_dispatch(tid)
    world.messages.clear()
    assert "passed" in reply(a, f"DECLINE {num}")
    assert offers(tid) == [("Alpha", "DECLINED"), ("Bravo", "SENT")]
    assert world.messages[0][0] == b_phone
    reply(b, "no")
    assert ticket_status(tid) == "UNMATCHED"


def test_expired_offer_rolls_to_next_handyman(world):
    new_handyman(world, "Alpha", 4.9)
    _, b_phone = new_handyman(world, "Bravo", 4.5)
    tid, _ = new_ticket(world)
    dispatch.start_dispatch(tid)
    world.messages.clear()
    expire_offer_now(tid)
    assert dispatch.expire_overdue() == 1
    assert offers(tid) == [("Alpha", "EXPIRED"), ("Bravo", "SENT")]
    assert world.messages[0][0] == b_phone
    assert dispatch.expire_overdue() == 0


def test_late_accept_is_refused_and_offer_moves_on(world):
    a, _ = new_handyman(world, "Alpha", 4.9)
    new_handyman(world, "Bravo", 4.5)
    tid, num = new_ticket(world)
    dispatch.start_dispatch(tid)
    expire_offer_now(tid)
    assert "no longer available" in reply(a, f"ACCEPT {num}")
    assert ticket_status(tid) == "MATCHING"
    assert offers(tid) == [("Alpha", "EXPIRED"), ("Bravo", "SENT")]


def test_accept_after_customer_cancelled(world):
    a, _ = new_handyman(world, "Alpha", 4.9)
    tid, num = new_ticket(world)
    dispatch.start_dispatch(tid)
    with get_engine().begin() as c:
        c.execute(text("UPDATE tickets SET status = 'CANCELLED' WHERE id = :t"), {"t": tid})
    assert "no longer available" in reply(a, f"ACCEPT {num}")
    assert ticket_status(tid) == "CANCELLED"


def test_repeat_accept_does_not_double_assign(world):
    a, _ = new_handyman(world, "Alpha", 4.9)
    tid, num = new_ticket(world)
    dispatch.start_dispatch(tid)
    reply(a, f"ACCEPT {num}")
    assert "no longer available" in reply(a, f"ACCEPT {num}")


def test_gives_up_after_five_offers(world):
    people = [new_handyman(world, f"H{i}", 4.9 - i * 0.1) for i in range(6)]
    tid, num = new_ticket(world)
    dispatch.start_dispatch(tid)
    for uid, _ in people[:5]:
        reply(uid, f"DECLINE {num}")
    assert ticket_status(tid) == "UNMATCHED"
    assert len(offers(tid)) == 5


def test_no_candidates_means_unmatched_at_once(world):
    tid, _ = new_ticket(world)
    dispatch.start_dispatch(tid)
    assert ticket_status(tid) == "UNMATCHED"


def test_unmatched_ticket_can_be_retried(world):
    tid, _ = new_ticket(world)
    dispatch.start_dispatch(tid)
    new_handyman(world, "Late", 4.0)
    assert dispatch.start_dispatch(tid)
    assert offers(tid) == [("Late", "SENT")]


def test_opted_out_handyman_gets_no_offers(world):
    uid, _ = new_handyman(world, "Quiet", 5.0)
    new_handyman(world, "Loud", 4.0)
    with get_engine().begin() as c:
        c.execute(text("UPDATE users SET sms_opted_out = TRUE WHERE id = :u"), {"u": uid})
    tid, _ = new_ticket(world)
    dispatch.start_dispatch(tid)
    assert [name for name, _ in offers(tid)] == ["Loud"]


def test_unparseable_reply_gets_help(world):
    uid, _ = new_handyman(world, "Best", 4.9)
    assert "ACCEPT" in reply(uid, "maybe later?")


# ---------- through the Twilio webhook ----------
def post_sms(monkeypatch, phone, body):
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    params = {
        "MessageSid": "SM" + uuid.uuid4().hex,
        "From": phone,
        "To": "+15550000000",
        "Body": body,
        "NumMedia": "0",
    }
    sig = compute_signature("tok", "http://testserver/webhooks/twilio/sms", params)
    return client.post("/webhooks/twilio/sms", data=params, headers={"X-Twilio-Signature": sig})


def test_handyman_accepts_by_sms_webhook(world, monkeypatch):
    _, phone = new_handyman(world, "Best", 4.9)
    tid, num = new_ticket(world)
    dispatch.start_dispatch(tid)
    r = post_sms(monkeypatch, phone, f"ACCEPT {num}")
    assert r.status_code == 200
    assert "assigned to job" in r.text
    assert ticket_status(tid) == "ASSIGNED"


def test_handyman_texts_never_reach_the_ai_or_create_customer_chats(world, monkeypatch):
    uid, phone = new_handyman(world, "Best", 4.9)
    post_sms(monkeypatch, phone, "my sink is leaking")
    with get_engine().connect() as c:
        n = c.execute(
            text("SELECT count(*) FROM conversations WHERE user_id = :u"), {"u": uid}
        ).scalar()
    assert n == 0
