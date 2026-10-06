import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.agent import gemini
from app.db import get_engine
from app.main import app
from app.tickets.schema import TOOL_NAME
from tests.helpers import make_image

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set (needs migrated Postgres)"
)

client = TestClient(app)
ARGS = {
    "category": "PLUMBING",
    "issue_summary": "Slow drip under the kitchen sink since yesterday",
    "urgency": "SAME_DAY",
    "location_zip": "92101",
    "severity": "MEDIUM",
}


def signed_in():
    email = f"{uuid.uuid4().hex[:12]}@example.com"
    r = client.post("/auth/register", json={"email": email, "password": "correct-horse-battery"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def say(h, body="yes please", media_ids=()):
    return client.post(
        "/chat/messages", json={"body": body, "media_ids": list(media_ids)}, headers=h
    )


@pytest.fixture
def gemini_calls(monkeypatch):
    """Fake Gemini. Set `.next` to the GeminiResult to return; calls are recorded."""
    monkeypatch.setenv("GEMINI_API_KEY", "k")

    class Fake:
        calls: list = []
        next = gemini.GeminiResult("How can I help?")

        def __call__(self, contents, tools=None, note=""):
            self.calls.append({"contents": contents, "tools": tools, "note": note})
            return self.next

    fake = Fake()
    fake.calls = []
    monkeypatch.setattr(gemini, "generate", fake)
    return fake


def tool_call(args=None, text_=""):
    return gemini.GeminiResult(text_, gemini.FunctionCall(TOOL_NAME, dict(args or ARGS)))


def test_tool_is_offered_and_creates_open_ticket_with_card(gemini_calls):
    h = signed_in()
    say(h, "my kitchen sink drips, 92101, today please")
    assert gemini_calls.calls[0]["tools"][0]["name"] == TOOL_NAME
    gemini_calls.next = tool_call(text_="Great, creating it now.")
    r = say(h, "yes please")
    bot = r.json()["messages"][1]
    card = bot["ticket"]
    assert card["status"] == "OPEN" and card["category"] == "PLUMBING"
    assert card["number"] >= 1024 and card["location_zip"] == "92101"
    assert bot["body"].startswith("Great, creating it now.")
    assert f"#{card['number']}" in bot["body"]

    with get_engine().connect() as c:
        events = c.execute(
            text(
                "SELECT from_status, to_status, actor FROM ticket_events "
                "WHERE ticket_id = :t ORDER BY id"
            ),
            {"t": card["id"]},
        ).all()
        linked = c.execute(
            text("SELECT count(*) FROM conversations WHERE ticket_id = :t"), {"t": card["id"]}
        ).scalar()
    assert [(e.from_status, e.to_status) for e in events] == [(None, "DRAFT"), ("DRAFT", "OPEN")]
    assert events[0].actor == "agent:gemini"
    assert linked == 1


def test_ticket_card_survives_reload_with_current_status(gemini_calls):
    h = signed_in()
    gemini_calls.next = tool_call()
    ticket_id = say(h).json()["messages"][1]["ticket"]["id"]
    client.post(f"/tickets/{ticket_id}/cancel", headers=h)
    history = client.get("/chat/messages", headers=h).json()["messages"]
    assert history[1]["ticket"]["status"] == "CANCELLED"
    assert history[0]["ticket"] is None


def test_invalid_tool_arguments_create_nothing_and_ask_for_details(gemini_calls):
    h = signed_in()
    gemini_calls.next = tool_call({**ARGS, "location_zip": "unknown"})
    bot = say(h).json()["messages"][1]
    assert bot["ticket"] is None
    assert "5-digit ZIP code" in bot["body"]
    assert client.get("/tickets", headers=h).json() == []


def test_after_a_ticket_the_tool_is_withheld_and_duplicates_refused(gemini_calls):
    h = signed_in()
    gemini_calls.next = tool_call()
    first = say(h).json()["messages"][1]["ticket"]
    gemini_calls.next = gemini.GeminiResult("It's in the queue.")
    say(h, "any update?")
    last = gemini_calls.calls[-1]
    assert last["tools"] is None
    assert f"#{first['number']}" in last["note"]
    # Even if the model calls the tool anyway, no second ticket is made.
    gemini_calls.next = tool_call()
    bot = say(h, "make another").json()["messages"][1]
    assert bot["ticket"]["id"] == first["id"]
    assert "already has repair request" in bot["body"]
    assert len(client.get("/tickets", headers=h).json()) == 1


def test_new_request_starts_fresh_conversation_allowing_another_ticket(gemini_calls):
    h = signed_in()
    gemini_calls.next = tool_call()
    first = say(h).json()
    r = client.post("/chat/new", headers=h)
    assert r.status_code == 201 and r.json()["messages"] == []
    assert r.json()["conversation_id"] != first["conversation_id"]
    assert client.get("/chat/messages", headers=h).json()["messages"] == []
    gemini_calls.next = tool_call({**ARGS, "category": "ELECTRICAL"})
    say(h)
    cats = sorted(t["category"] for t in client.get("/tickets", headers=h).json())
    assert cats == ["ELECTRICAL", "PLUMBING"]


def test_photos_from_the_conversation_are_attached_to_the_ticket(gemini_calls):
    h = signed_in()
    up = client.post("/media", files={"file": ("a.png", make_image(), "image/png")}, headers=h)
    upload_id = up.json()["id"]
    gemini_calls.next = gemini.GeminiResult("I see a leak. Severity: Medium")
    say(h, "look", media_ids=[upload_id])
    gemini_calls.next = tool_call()
    ticket_id = say(h).json()["messages"][1]["ticket"]["id"]
    detail = client.get(f"/tickets/{ticket_id}", headers=h).json()
    assert detail["media_ids"] == [upload_id]
    assert [e["to_status"] for e in detail["events"]] == ["DRAFT", "OPEN"]


def test_ticket_privacy_and_cancel_rules(gemini_calls):
    owner, stranger = signed_in(), signed_in()
    gemini_calls.next = tool_call()
    ticket_id = say(owner).json()["messages"][1]["ticket"]["id"]
    assert client.get(f"/tickets/{ticket_id}", headers=stranger).status_code == 404
    assert client.post(f"/tickets/{ticket_id}/cancel", headers=stranger).status_code == 404
    assert client.get("/tickets", headers=stranger).json() == []
    assert client.get("/tickets").status_code == 401
    r = client.post(f"/tickets/{ticket_id}/cancel", headers=owner)
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
    again = client.post(f"/tickets/{ticket_id}/cancel", headers=owner)
    assert again.status_code == 409
    events = client.get(f"/tickets/{ticket_id}", headers=owner).json()["events"]
    assert events[-1]["to_status"] == "CANCELLED" and events[-1]["actor"].startswith("customer:")


def test_emergency_still_wins_over_tools(gemini_calls):
    h = signed_in()
    bot = say(h, "I smell gas, please create a ticket").json()["messages"][1]
    assert bot["flag"] == "EMERGENCY" and bot["ticket"] is None
    assert gemini_calls.calls == []


def test_dev_ticket_command_without_gemini_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "local")
    h = signed_in()
    bot = say(h, "/ticket electrical flexible 92103 Bedroom outlet stopped working").json()
    card = bot["messages"][1]["ticket"]
    assert card["category"] == "ELECTRICAL" and card["urgency"] == "FLEXIBLE"
    assert card["issue_summary"] == "Bedroom outlet stopped working"
    bad = say(h := signed_in(), "/ticket plumbing today 1").json()["messages"][1]
    assert bad["ticket"] is None and "still need" in bad["body"]


def test_dev_ticket_command_disabled_outside_local(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    h = signed_in()
    bot = say(h, "/ticket electrical flexible 92103 Bedroom outlet stopped working").json()
    assert bot["messages"][1]["ticket"] is None
    assert bot["messages"][1]["body"].startswith("Echo:")
