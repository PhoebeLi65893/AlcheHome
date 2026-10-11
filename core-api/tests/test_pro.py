import hashlib
import os
import secrets

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import dispatch
from app.agent import gemini
from app.agent.pro_prompt import PRO_PROMPT
from app.db import get_engine
from app.main import app
from app.security import create_access_token
from tests.test_dispatch import (  # noqa: F401  (world is a fixture)
    new_handyman,
    new_ticket,
    new_user,
    ticket_status,
    world,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set (needs migrated Postgres)"
)

client = TestClient(app)


def auth(uid, role="HANDYMAN"):
    return {"Authorization": f"Bearer {create_access_token(str(uid), role)}"}


@pytest.fixture
def fake_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    calls = []

    def fake(contents, tools=None, note="", system=None):
        calls.append({"contents": contents, "tools": tools, "note": note, "system": system})
        return gemini.GeminiResult("Check the trap and bring a roll of PTFE tape.")

    monkeypatch.setattr(gemini, "generate", fake)
    return calls


def invite(uid, expires="1 day"):
    token = secrets.token_urlsafe(32)
    with get_engine().begin() as c:
        c.execute(
            text(
                "INSERT INTO invite_tokens (token_hash, user_id, expires_at) "
                "VALUES (:h, :u, now() + CAST(:e AS interval))"
            ),
            {"h": hashlib.sha256(token.encode()).hexdigest(), "u": uid, "e": expires},
        )
    return token


def test_offers_show_up_and_accept_assigns_the_job(world):  # noqa: F811
    hid, _ = new_handyman(world, "Best", 4.9)
    tid, num = new_ticket(world)
    dispatch.start_dispatch(tid, hid)
    h = auth(hid)
    jobs = client.get("/pro/jobs", headers=h).json()
    assert [(j["number"], j["location_zip"], j["customer"]) for j in jobs["offers"]] == [
        (num, world.zip, "Customer")
    ]
    assert jobs["offers"][0]["expires_at"] is not None and jobs["active"] == []
    r = client.post(f"/pro/jobs/{tid}/accept", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "ASSIGNED"
    jobs = client.get("/pro/jobs", headers=h).json()
    assert jobs["offers"] == [] and [j["number"] for j in jobs["active"]] == [num]


def test_decline_rolls_to_the_next_handyman(world):  # noqa: F811
    a, _ = new_handyman(world, "Alpha", 4.9)
    b, _ = new_handyman(world, "Bravo", 4.0)
    tid, _ = new_ticket(world)
    dispatch.start_dispatch(tid)
    assert client.post(f"/pro/jobs/{tid}/decline", headers=auth(a)).status_code == 200
    assert len(client.get("/pro/jobs", headers=auth(b)).json()["offers"]) == 1


def test_accept_without_an_offer_or_after_it_was_taken(world):  # noqa: F811
    a, _ = new_handyman(world, "Alpha", 4.9)
    b, _ = new_handyman(world, "Bravo", 4.0)
    tid, _ = new_ticket(world)
    assert client.post(f"/pro/jobs/{tid}/accept", headers=auth(a)).status_code == 404
    dispatch.start_dispatch(tid, a)
    client.post(f"/pro/jobs/{tid}/decline", headers=auth(a))
    assert client.post(f"/pro/jobs/{tid}/accept", headers=auth(b)).status_code == 200
    assert client.post(f"/pro/jobs/{tid}/accept", headers=auth(a)).status_code == 409
    assert ticket_status(tid) == "ASSIGNED"


def test_role_checks(world):  # noqa: F811
    cust = new_user(world, "CUSTOMER")
    assert client.get("/pro/jobs", headers=auth(cust, "CUSTOMER")).status_code == 403
    assert client.get("/pro/jobs").status_code == 401


def test_invite_link_sets_a_password_once(world):  # noqa: F811
    hid, _ = new_handyman(world, "Best", 4.9)
    with get_engine().connect() as c:
        email = c.execute(text("SELECT email FROM users WHERE id = :u"), {"u": hid}).scalar()
    token = invite(hid)
    r = client.post("/pro/set-password", json={"token": token, "password": "a-long-new-password"})
    assert r.status_code == 200 and r.json()["access_token"]
    login = client.post("/auth/login", json={"email": email, "password": "a-long-new-password"})
    assert login.status_code == 200
    again = client.post(
        "/pro/set-password", json={"token": token, "password": "another-password-1"}
    )
    assert again.status_code == 400
    expired = invite(hid, expires="-1 day")
    r = client.post("/pro/set-password", json={"token": expired, "password": "another-password-1"})
    assert r.status_code == 400
    r = client.post(
        "/pro/set-password", json={"token": "x" * 20, "password": "a-long-new-password"}
    )
    assert r.status_code == 400


def test_assistant_knows_the_job_and_keeps_history(world, fake_gemini):  # noqa: F811
    hid, hphone = new_handyman(world, "Best", 4.9)
    tid, num = new_ticket(world)
    dispatch.start_dispatch(tid, hid)
    h = auth(hid)
    r = client.post(f"/pro/jobs/{tid}/assistant", json={"body": "What should I bring?"}, headers=h)
    assert r.status_code == 200
    assert [m["sender"] for m in r.json()] == ["USER", "BOT"]
    call = fake_gemini[-1]
    assert call["system"] == PRO_PROMPT and call["tools"] is None
    assert f"Job #{num}" in call["note"] and world.zip in call["note"]
    assert hphone not in call["note"]
    client.post(f"/pro/jobs/{tid}/assistant", json={"body": "And the safety bits?"}, headers=h)
    assert len(fake_gemini[-1]["contents"]) == 3  # user, model, user
    assert len(client.get(f"/pro/jobs/{tid}/assistant", headers=h).json()) == 4


def test_assistant_is_private_to_the_handymans_own_jobs(world, fake_gemini):  # noqa: F811
    a, _ = new_handyman(world, "Alpha", 4.9)
    b, _ = new_handyman(world, "Bravo", 4.0)
    tid, _ = new_ticket(world)
    dispatch.start_dispatch(tid, a)
    h = auth(b)
    assert client.get(f"/pro/jobs/{tid}/assistant", headers=h).status_code == 404
    r = client.post(f"/pro/jobs/{tid}/assistant", json={"body": "hi"}, headers=h)
    assert r.status_code == 404
    assert client.post(f"/pro/jobs/{tid}/draft", headers=h).status_code == 404
    assert fake_gemini == []


def test_assistant_without_a_key_says_so(world, monkeypatch):  # noqa: F811
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    hid, _ = new_handyman(world, "Best", 4.9)
    tid, _ = new_ticket(world)
    dispatch.start_dispatch(tid, hid)
    r = client.post(f"/pro/jobs/{tid}/assistant", json={"body": "help"}, headers=auth(hid))
    assert "not configured" in r.json()[-1]["body"]


def test_draft_is_not_stored_and_has_a_fallback(world, fake_gemini, monkeypatch):  # noqa: F811
    hid, _ = new_handyman(world, "Best", 4.9)
    tid, num = new_ticket(world)
    dispatch.start_dispatch(tid, hid)
    h = auth(hid)
    r = client.post(f"/pro/jobs/{tid}/draft", headers=h)
    assert r.status_code == 200 and r.json()["draft"].startswith("Check the trap")
    assert "Output only the message text" in fake_gemini[-1]["contents"][-1]["parts"][0]["text"]
    assert client.get(f"/pro/jobs/{tid}/assistant", headers=h).json() == []
    monkeypatch.delenv("GEMINI_API_KEY")
    fallback = client.post(f"/pro/jobs/{tid}/draft", headers=h).json()["draft"]
    assert f"#{num}" in fallback and "Best" in fallback
