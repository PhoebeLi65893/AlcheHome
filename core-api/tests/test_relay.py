import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import dispatch, relay
from app.conversations import recent_messages
from app.db import get_engine
from app.main import app
from app.security import create_access_token
from tests.test_dispatch import (  # noqa: F401  (world is a fixture)
    new_handyman,
    new_ticket,
    post_sms,
    world,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set (needs migrated Postgres)"
)

client = TestClient(app)


def customer_of(tid):
    with get_engine().connect() as c:
        row = c.execute(
            text(
                "SELECT u.id, u.phone_e164 FROM tickets t JOIN users u ON u.id = t.customer_id "
                "WHERE t.id = :t"
            ),
            {"t": tid},
        ).one()
    token = create_access_token(str(row.id), "CUSTOMER")
    return row.id, row.phone_e164, {"Authorization": f"Bearer {token}"}


def assigned(world, channel="WEB", rating=4.9, name="Best"):  # noqa: F811
    hid, hphone = new_handyman(world, name, rating)
    tid, num = new_ticket(world, channel=channel)
    dispatch.start_dispatch(tid, hid)
    dispatch.handle_handyman_reply(hid, f"ACCEPT {num}")
    world.messages.clear()
    return hid, hphone, tid, num


def thread_rows(tid):
    with get_engine().connect() as c:
        return c.execute(
            text(
                "SELECT sender, body FROM messages WHERE relay_ticket_id = :t "
                "ORDER BY created_at, id"
            ),
            {"t": tid},
        ).all()


def test_customer_message_reaches_handyman_without_the_customers_number(world):  # noqa: F811
    _, hphone, tid, num = assigned(world)
    _, cphone, h = customer_of(tid)
    r = client.post(f"/tickets/{tid}/thread", json={"body": "The key is under the mat"}, headers=h)
    assert r.status_code == 201
    assert [(m["sender"], m["body"]) for m in r.json()["messages"]] == [
        ("CUSTOMER", "The key is under the mat")
    ]
    [(to, body)] = world.messages
    assert to == hphone
    assert f"#{num}" in body and "The key is under the mat" in body
    assert cphone not in body
    assert [tuple(row) for row in thread_rows(tid)] == [("USER", "The key is under the mat")]


def test_handyman_text_reaches_an_sms_customer_without_the_handymans_number(world):  # noqa: F811
    hid, hphone, tid, num = assigned(world, channel="SMS")
    _, cphone, h = customer_of(tid)
    answer, out = dispatch.handle_handyman_reply(hid, "I am on my way, 20 minutes")
    assert answer == ""
    dispatch.deliver(out)
    [(to, body)] = world.messages
    assert to == cphone
    assert "Best" in body and "on my way" in body and hphone not in body
    seen = client.get(f"/tickets/{tid}/thread", headers=h).json()
    assert seen["open"] is True and seen["handyman_name"] == "Best"
    assert [(m["sender"], m["body"]) for m in seen["messages"]] == [
        ("HANDYMAN", "I am on my way, 20 minutes")
    ]
    assert hphone not in str(seen) and cphone not in str(seen)


def test_web_customer_sees_handyman_text_without_an_sms(world):  # noqa: F811
    hid, _, tid, _ = assigned(world, channel="WEB")
    _, _, h = customer_of(tid)
    _, out = dispatch.handle_handyman_reply(hid, "Running 10 minutes late")
    assert out == [] and world.messages == []
    thread = client.get(f"/tickets/{tid}/thread", headers=h).json()["messages"]
    assert [m["body"] for m in thread] == ["Running 10 minutes late"]


def test_relayed_messages_stay_out_of_the_ai_conversation(world):  # noqa: F811
    hid, _, tid, _ = assigned(world)
    cid, _, h = customer_of(tid)
    client.post(f"/tickets/{tid}/thread", json={"body": "hello handyman"}, headers=h)
    dispatch.handle_handyman_reply(hid, "hello customer")
    with get_engine().connect() as c:
        conv = c.execute(
            text("SELECT id FROM conversations WHERE ticket_id = :t"), {"t": tid}
        ).scalar()
        bodies = [m.body for m in recent_messages(c, str(conv), 50)]
    assert "hello handyman" not in bodies and "hello customer" not in bodies
    chat = client.get("/chat/messages", headers=h).json()["messages"]
    assert all("hello" not in m["body"] for m in chat)


def test_bridge_is_closed_before_acceptance_and_after_cancelling(world):  # noqa: F811
    hid, _ = new_handyman(world, "Best", 4.9)
    tid, num = new_ticket(world)
    _, _, h = customer_of(tid)
    assert client.post(f"/tickets/{tid}/thread", json={"body": "hi"}, headers=h).status_code == 409
    dispatch.start_dispatch(tid, hid)
    assert client.post(f"/tickets/{tid}/thread", json={"body": "hi"}, headers=h).status_code == 409
    dispatch.handle_handyman_reply(hid, f"ACCEPT {num}")
    assert client.post(f"/tickets/{tid}/thread", json={"body": "hi"}, headers=h).status_code == 201
    client.post(f"/tickets/{tid}/cancel", headers=h)
    r = client.post(f"/tickets/{tid}/thread", json={"body": "again"}, headers=h)
    assert r.status_code == 409
    assert client.get(f"/tickets/{tid}/thread", headers=h).json()["open"] is False
    assert "no longer open" in dispatch.handle_handyman_reply(hid, f"#{num} still there?")[0]


def test_handyman_without_a_job_is_told_so(world):  # noqa: F811
    hid, _ = new_handyman(world, "Best", 4.9)
    assert "no active job" in dispatch.handle_handyman_reply(hid, "hello?")[0]


def test_several_jobs_need_the_job_number(world):  # noqa: F811
    hid, _ = new_handyman(world, "Best", 4.9)
    jobs = []
    for _ in range(2):
        tid, num = new_ticket(world)
        dispatch.start_dispatch(tid, hid)
        dispatch.handle_handyman_reply(hid, f"ACCEPT {num}")
        jobs.append((tid, num))
    answer, out = dispatch.handle_handyman_reply(hid, "I am outside")
    assert "several jobs" in answer and out == [] and thread_rows(jobs[0][0]) == []
    first, second = jobs
    assert dispatch.handle_handyman_reply(hid, f"#{second[1]} I am outside")[0] == ""
    assert [tuple(r) for r in thread_rows(second[0])] == [("HANDYMAN", "I am outside")]
    assert thread_rows(first[0]) == []


def test_digits_that_are_not_a_job_number_are_part_of_the_message(world):  # noqa: F811
    hid, _, tid, _ = assigned(world)
    dispatch.handle_handyman_reply(hid, "92101 is the right ZIP, right?")
    assert [r.body for r in thread_rows(tid)] == ["92101 is the right ZIP, right?"]


def test_sms_customer_text_is_relayed_through_the_webhook(world, monkeypatch):  # noqa: F811
    _, hphone, tid, _ = assigned(world, channel="SMS")
    _, cphone, _ = customer_of(tid)
    r = post_sms(monkeypatch, cphone, "Please use the side door")
    assert r.status_code == 200
    assert [(to, "side door" in body) for to, body in world.messages] == [(hphone, True)]
    assert cphone not in world.messages[0][1]
    assert [r.body for r in thread_rows(tid)] == ["Please use the side door"]


def test_handyman_text_is_relayed_through_the_webhook(world, monkeypatch):  # noqa: F811
    hid, hphone, tid, num = assigned(world, channel="SMS")
    _, cphone, _ = customer_of(tid)
    r = post_sms(monkeypatch, hphone, f"#{num} arriving now")
    assert r.status_code == 200 and "<Message>" not in r.text
    assert [to for to, _ in world.messages] == [cphone]
    assert "arriving now" in world.messages[0][1]


def test_privacy_of_the_thread_endpoints(world):  # noqa: F811
    _, _, tid, _ = assigned(world)
    other = new_ticket(world)[0]
    _, _, h_other = customer_of(other)
    assert client.get(f"/tickets/{tid}/thread", headers=h_other).status_code == 404
    assert (
        client.post(f"/tickets/{tid}/thread", json={"body": "hi"}, headers=h_other).status_code
        == 404
    )
    assert client.get(f"/tickets/{tid}/thread").status_code == 401


def test_message_is_cleaned_and_limited():
    assert relay.clean("  hello \n  there  ") == "hello there"
    assert len(relay.clean("x" * 2000)) == relay.MAX_LEN
