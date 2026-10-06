import os
import uuid

import pytest
from fastapi.testclient import TestClient

from app.agent import gemini
from app.main import app

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set (needs migrated Postgres)"
)

client = TestClient(app)


def signed_in():
    email = f"{uuid.uuid4().hex[:12]}@example.com"
    r = client.post("/auth/register", json={"email": email, "password": "correct-horse-battery"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_chat_uses_gemini_reply_and_sends_history(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    calls = []

    def fake(contents, **kw):
        calls.append(contents)
        return gemini.GeminiResult(f"reply {len(calls)}")

    monkeypatch.setattr(gemini, "generate", fake)
    h = signed_in()
    r1 = client.post("/chat/messages", json={"body": "my sink is leaking"}, headers=h)
    assert r1.json()["messages"][1]["body"] == "reply 1"
    client.post("/chat/messages", json={"body": "under the kitchen sink"}, headers=h)
    roles = [c["role"] for c in calls[1]]
    assert roles == ["user", "model", "user"]
    assert calls[1][0]["parts"][0]["text"] == "my sink is leaking"
    assert calls[1][2]["parts"][0]["text"] == "under the kitchen sink"


def test_emergency_reply_is_flagged_persisted_and_skips_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(
        gemini, "generate", lambda c, **kw: pytest.fail("Gemini must not be called")
    )
    h = signed_in()
    r = client.post("/chat/messages", json={"body": "I smell gas in the kitchen"}, headers=h)
    assert r.status_code == 201
    user_msg, bot_msg = r.json()["messages"]
    assert user_msg["flag"] is None
    assert bot_msg["flag"] == "EMERGENCY" and "911" in bot_msg["body"]
    again = client.get("/chat/messages", headers=h).json()["messages"]
    assert again[1]["flag"] == "EMERGENCY"


def test_gemini_outage_still_returns_a_reply(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")

    def down(contents, **kw):
        raise gemini.GeminiError("down")

    monkeypatch.setattr(gemini, "generate", down)
    h = signed_in()
    r = client.post("/chat/messages", json={"body": "my sink is leaking"}, headers=h)
    assert r.status_code == 201
    assert "trouble" in r.json()["messages"][1]["body"]
