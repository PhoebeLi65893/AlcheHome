import os
import random

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import dispatch
from app.agent import gemini
from app.agent import service as agent
from app.db import get_engine
from app.main import app
from app.security import create_access_token
from app.tickets.schema import TOOL_NAME
from tests.test_dispatch import (  # noqa: F401  (world is a fixture)
    new_handyman,
    new_ticket,
    new_user,
    world,
)

client = TestClient(app)
db = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set")


def auth(uid, role="CUSTOMER"):
    return {"Authorization": f"Bearer {create_access_token(str(uid), role)}"}


def new_number():
    return "+1619" + str(random.randint(5000000, 9999999))


# ---------- the customer's own profile ----------
@db
def test_profile_defaults_and_saving(world):  # noqa: F811
    uid = new_user(world, "CUSTOMER")
    h = auth(uid)
    p = client.get("/me/profile", headers=h).json()
    assert p["home_zip"] is None and p["phone"] is None and p["phone_pending"] is False
    r = client.put(
        "/me/profile", json={"display_name": "  Jane   Doe ", "home_zip": " 92101 "}, headers=h
    )
    assert r.status_code == 200
    assert r.json()["display_name"] == "Jane Doe" and r.json()["home_zip"] == "92101"
    cleared = client.put("/me/profile", json={"display_name": "", "home_zip": ""}, headers=h)
    assert cleared.json()["display_name"] is None and cleared.json()["home_zip"] is None


@pytest.mark.parametrize("zip_code", ["9210", "abcde", "921011", "92 101"])
@db
def test_invalid_zip_is_rejected(world, zip_code):  # noqa: F811
    uid = new_user(world, "CUSTOMER")
    r = client.put("/me/profile", json={"home_zip": zip_code}, headers=auth(uid))
    assert r.status_code == 422


@db
def test_profile_access_rules(world):  # noqa: F811
    assert client.get("/me/profile").status_code == 401
    hid = new_user(world, "HANDYMAN")
    assert client.get("/me/profile", headers=auth(hid, "HANDYMAN")).status_code == 403
    admin = new_user(world, "ADMIN")
    assert client.get("/me/profile", headers=auth(admin, "ADMIN")).status_code == 200


@db
def test_customer_phone_is_confirmed_with_a_code_and_keeps_the_channel(world):  # noqa: F811
    uid = new_user(world, "CUSTOMER")
    with get_engine().begin() as c:  # a web customer
        c.execute(text("UPDATE users SET preferred_channel = 'WEB' WHERE id = :u"), {"u": uid})
    h = auth(uid)
    number = new_number()
    r = client.post("/me/profile/phone", json={"phone": number}, headers=h)
    assert r.status_code == 200 and r.json()["dev_code"]
    code = r.json()["dev_code"]
    assert world.messages[-1][0] == number and code in world.messages[-1][1]
    assert client.get("/me/profile", headers=h).json()["phone"] is None  # not stored yet
    wrong = "000000" if code != "000000" else "111111"
    assert (
        client.post("/me/profile/phone/verify", json={"code": wrong}, headers=h).status_code == 400
    )
    ok = client.post("/me/profile/phone/verify", json={"code": code}, headers=h)
    assert ok.status_code == 200 and ok.json()["phone"].endswith(number[-4:])
    with get_engine().connect() as c:
        row = c.execute(
            text("SELECT phone_e164, preferred_channel FROM users WHERE id = :u"), {"u": uid}
        ).one()
    assert row.phone_e164 == number and row.preferred_channel == "WEB"


@db
def test_customer_phone_cannot_take_another_accounts_number(world):  # noqa: F811
    _, handyman_phone = new_handyman(world, "Other", 4.0)
    uid = new_user(world, "CUSTOMER")
    r = client.post("/me/profile/phone", json={"phone": handyman_phone}, headers=auth(uid))
    assert r.status_code == 409


# ---------- saved ZIP code ----------
def test_assistant_is_told_the_saved_zip_and_not_to_ask(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    seen = {}

    def fake(contents, tools=None, note="", system=None):
        seen["note"] = note
        return gemini.GeminiResult("ok")

    monkeypatch.setattr(gemini, "generate", fake)

    class Row:
        sender, body, media_ids = "USER", "my sink drips", []

    agent.respond([Row()], "my sink drips", home_zip="92101")
    assert "saved home ZIP code is 92101" in seen["note"] and "do not ask" in seen["note"]
    agent.respond([Row()], "my sink drips")
    assert "saved home ZIP" not in seen["note"]


@db
def test_ticket_uses_the_saved_zip_when_the_model_leaves_it_out(world, monkeypatch):  # noqa: F811
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    uid = new_user(world, "CUSTOMER")
    h = auth(uid)
    client.put("/me/profile", json={"home_zip": "92103"}, headers=h)
    args = {
        "category": "PLUMBING",
        "issue_summary": "Kitchen sink drips all day",
        "urgency": "SAME_DAY",
    }
    monkeypatch.setattr(
        gemini,
        "generate",
        lambda contents, tools=None, note="", system=None: gemini.GeminiResult(
            "Creating it.", gemini.FunctionCall(TOOL_NAME, dict(args))
        ),
    )
    bot = client.post("/chat/request-ticket", headers=h).json()["messages"][1]
    assert bot["ticket"]["location_zip"] == "92103"
    # An explicit ZIP from the conversation still wins over the saved one.
    client.post("/chat/new", headers=h)
    args["location_zip"] = "92110"
    bot = client.post("/chat/request-ticket", headers=h).json()["messages"][1]
    assert bot["ticket"]["location_zip"] == "92110"


@db
def test_without_a_saved_zip_the_ticket_still_needs_one(world, monkeypatch):  # noqa: F811
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    uid = new_user(world, "CUSTOMER")
    args = {
        "category": "PLUMBING",
        "issue_summary": "Kitchen sink drips all day",
        "urgency": "SAME_DAY",
    }
    monkeypatch.setattr(
        gemini,
        "generate",
        lambda contents, tools=None, note="", system=None: gemini.GeminiResult(
            "", gemini.FunctionCall(TOOL_NAME, dict(args))
        ),
    )
    bot = client.post("/chat/request-ticket", headers=auth(uid)).json()["messages"][1]
    assert bot["ticket"] is None and "ZIP" in bot["body"]


# ---------- the handyman's phone number ----------
def assigned(world):  # noqa: F811
    hid, hphone = new_handyman(world, "Mike R.", 4.9)
    tid, num = new_ticket(world)
    with get_engine().connect() as c:
        cust = c.execute(text("SELECT customer_id FROM tickets WHERE id = :t"), {"t": tid}).scalar()
    dispatch.start_dispatch(tid, hid)
    dispatch.handle_handyman_reply(hid, f"ACCEPT {num}")
    return hid, hphone, cust, tid


def profile_payload(**over):
    base = {
        "display_name": "Mike R.",
        "skills": ["PLUMBING"],
        "service_zips": ["92101"],
        "is_available": True,
    }
    return {**base, **over}


@db
def test_handyman_phone_is_hidden_by_default(world):  # noqa: F811
    hid, hphone, cust, tid = assigned(world)
    h = auth(cust)
    assert client.get(f"/threads/{tid}/messages", headers=h).json()["counterpart_phone"] is None
    assert client.get(f"/tickets/{tid}", headers=h).json()["handyman_phone"] is None
    mine = client.get("/pro/profile", headers=auth(hid, "HANDYMAN")).json()
    assert mine["share_phone"] is False


@db
def test_customer_sees_the_number_only_when_the_handyman_shares_it(world):  # noqa: F811
    hid, hphone, cust, tid = assigned(world)
    pro, c = auth(hid, "HANDYMAN"), auth(cust)
    r = client.put("/pro/profile", json=profile_payload(share_phone=True), headers=pro)
    assert r.status_code == 200 and r.json()["share_phone"] is True
    assert client.get(f"/threads/{tid}/messages", headers=c).json()["counterpart_phone"] == hphone
    assert client.get(f"/tickets/{tid}", headers=c).json()["handyman_phone"] == hphone
    # The handyman never sees the customer's number this way.
    seen = client.get(f"/threads/{tid}/messages", headers=pro).json()
    assert seen["counterpart_phone"] is None
    # Switching sharing off hides it again at once.
    client.put("/pro/profile", json=profile_payload(share_phone=False), headers=pro)
    assert client.get(f"/threads/{tid}/messages", headers=c).json()["counterpart_phone"] is None


@db
def test_number_is_private_to_the_jobs_customer_and_only_while_open(world):  # noqa: F811
    hid, hphone, cust, tid = assigned(world)
    client.put(
        "/pro/profile", json=profile_payload(share_phone=True), headers=auth(hid, "HANDYMAN")
    )
    stranger = auth(new_user(world, "CUSTOMER"))
    assert client.get(f"/threads/{tid}/messages", headers=stranger).status_code == 404
    assert client.get(f"/tickets/{tid}", headers=stranger).status_code == 404
    client.post(f"/tickets/{tid}/cancel", headers=auth(cust))
    c = auth(cust)
    assert client.get(f"/threads/{tid}/messages", headers=c).json()["counterpart_phone"] is None
    assert client.get(f"/tickets/{tid}", headers=c).json()["handyman_phone"] is None
    assert hphone not in str(client.get("/threads", headers=c).json())
