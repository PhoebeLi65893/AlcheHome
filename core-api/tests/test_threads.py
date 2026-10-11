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
    world,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set (needs migrated Postgres)"
)

client = TestClient(app)


def auth(uid, role):
    return {"Authorization": f"Bearer {create_access_token(str(uid), role)}"}


def job(world, channel="WEB"):  # noqa: F811
    """An assigned job. Returns handyman id/phone/headers, customer phone/headers, ticket."""
    hid, hphone = new_handyman(world, "Mike R.", 4.9)
    tid, num = new_ticket(world, channel=channel)
    with get_engine().begin() as c:
        cust, cphone = c.execute(
            text(
                "UPDATE users SET display_name = 'Jane Doe' WHERE id = "
                "(SELECT customer_id FROM tickets WHERE id = :t) RETURNING id, phone_e164"
            ),
            {"t": tid},
        ).one()
    dispatch.start_dispatch(tid, hid)
    dispatch.handle_handyman_reply(hid, f"ACCEPT {num}")
    world.messages.clear()
    return {
        "hid": hid,
        "hphone": hphone,
        "h": auth(hid, "HANDYMAN"),
        "cphone": cphone,
        "c": auth(cust, "CUSTOMER"),
        "tid": tid,
        "num": num,
    }


def post(j, who, body):
    return client.post(f"/threads/{j['tid']}/messages", json={"body": body}, headers=j[who])


def test_both_sides_chat_and_see_the_right_names(world):  # noqa: F811
    j = job(world)
    assert post(j, "c", "Hello, door code is 4321").status_code == 201
    assert post(j, "h", "Great, see you at 3").status_code == 201
    mine = client.get(f"/threads/{j['tid']}/messages", headers=j["c"]).json()
    assert mine["counterpart"] == "Mike R." and mine["open"] is True
    assert [(m["mine"], m["body"]) for m in mine["messages"]] == [
        (True, "Hello, door code is 4321"),
        (False, "Great, see you at 3"),
    ]
    theirs = client.get(f"/threads/{j['tid']}/messages", headers=j["h"]).json()
    assert theirs["counterpart"] == "Jane"  # first name only
    assert [m["mine"] for m in theirs["messages"]] == [False, True]
    for body in (str(mine), str(theirs)):
        assert j["hphone"] not in body and j["cphone"] not in body


def test_list_shows_last_message_and_unread_until_opened(world):  # noqa: F811
    j = job(world)
    post(j, "c", "first")
    post(j, "c", "second")
    lst = client.get("/threads", headers=j["h"]).json()
    mine = [t for t in lst["threads"] if t["ticket_id"] == str(j["tid"])][0]
    assert mine["unread"] == 2 and mine["last_body"] == "second" and mine["last_from_me"] is False
    assert mine["counterpart"] == "Jane" and lst["unread_total"] >= 2
    own = client.get("/threads", headers=j["c"]).json()["threads"][0]
    assert own["unread"] == 0 and own["last_from_me"] is True
    client.get(f"/threads/{j['tid']}/messages", headers=j["h"])  # opening marks it read
    assert client.get("/threads", headers=j["h"]).json()["threads"][0]["unread"] == 0
    seen = client.get(f"/threads/{j['tid']}/messages", headers=j["c"]).json()
    assert seen["other_read_at"] is not None


def test_sms_is_the_fallback_not_a_duplicate(world):  # noqa: F811
    j = job(world)
    post(j, "c", "ping one")  # handyman is away: texted
    assert [to for to, _ in world.messages] == [j["hphone"]]
    world.messages.clear()
    client.get("/threads", headers=j["h"])  # handyman opens the app
    post(j, "c", "ping two")
    assert world.messages == []
    with get_engine().begin() as c:  # idle for over two minutes: texted again
        c.execute(
            text("UPDATE users SET last_seen_at = now() - interval '5 minutes' WHERE id = :u"),
            {"u": j["hid"]},
        )
    post(j, "c", "ping three")
    assert [to for to, _ in world.messages] == [j["hphone"]]


def test_handyman_message_texts_an_sms_customer_unless_in_the_app(world):  # noqa: F811
    j = job(world, channel="SMS")
    post(j, "h", "On my way")
    assert [to for to, _ in world.messages] == [j["cphone"]]
    assert j["hphone"] not in world.messages[0][1]
    world.messages.clear()
    client.get("/threads", headers=j["c"])
    post(j, "h", "Almost there")
    assert world.messages == []


def test_privacy_and_closed_conversations(world):  # noqa: F811
    j = job(world)
    other_customer = auth(new_user(world, "CUSTOMER"), "CUSTOMER")
    other_handyman = auth(new_handyman(world, "Other", 4.0)[0], "HANDYMAN")
    admin = auth(new_user(world, "ADMIN"), "ADMIN")
    for h in (other_customer, other_handyman):
        assert client.get(f"/threads/{j['tid']}/messages", headers=h).status_code == 404
        r = client.post(f"/threads/{j['tid']}/messages", json={"body": "x"}, headers=h)
        assert r.status_code == 404
    assert client.get("/threads", headers=admin).json()["threads"] == []  # not their tickets
    r = client.get(f"/threads/{j['tid']}/messages", headers=admin)
    assert r.status_code == 404
    assert client.get("/threads").status_code == 401
    client.post(f"/tickets/{j['tid']}/cancel", headers=j["c"])
    closed = client.get(f"/threads/{j['tid']}/messages", headers=j["c"]).json()
    assert closed["open"] is False
    assert post(j, "c", "late").status_code == 409
    assert post(j, "h", "late").status_code == 409
    assert post(j, "c", "").status_code == 422


def test_inbound_sms_and_app_messages_share_one_thread(world):  # noqa: F811
    j = job(world, channel="SMS")
    dispatch.handle_handyman_reply(j["hid"], f"#{j['num']} I am outside")
    post(j, "c", "Coming down")
    data = client.get(f"/threads/{j['tid']}/messages", headers=j["c"]).json()
    assert [m["body"] for m in data["messages"]] == ["I am outside", "Coming down"]


def test_an_admin_using_the_customer_app_can_message_about_their_own_job(world):  # noqa: F811
    hid, _ = new_handyman(world, "Mike R.", 4.9)
    tid, num = new_ticket(world)
    with get_engine().begin() as c:
        owner = c.execute(
            text("SELECT customer_id FROM tickets WHERE id = :t"), {"t": tid}
        ).scalar()
        c.execute(text("UPDATE users SET role = 'ADMIN' WHERE id = :u"), {"u": owner})
    admin = auth(owner, "ADMIN")
    dispatch.start_dispatch(tid, hid)
    dispatch.handle_handyman_reply(hid, f"ACCEPT {num}")
    handyman = auth(hid, "HANDYMAN")
    assert (
        client.post(
            f"/threads/{tid}/messages", json={"body": "Hi from the admin account"}, headers=admin
        ).status_code
        == 201
    )
    client.post(f"/threads/{tid}/messages", json={"body": "Hello back"}, headers=handyman)
    lst = client.get("/threads", headers=admin).json()["threads"]
    assert lst[0]["counterpart"] == "Mike R." and lst[0]["unread"] == 1
    data = client.get(f"/threads/{tid}/messages", headers=admin).json()
    assert [(m["mine"], m["body"]) for m in data["messages"]] == [
        (True, "Hi from the admin account"),
        (False, "Hello back"),
    ]
