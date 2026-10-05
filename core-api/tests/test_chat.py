import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import get_engine
from app.main import app

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set (needs migrated Postgres)"
)

client = TestClient(app)


def signed_in():
    email = f"{uuid.uuid4().hex[:12]}@example.com"
    r = client.post("/auth/register", json={"email": email, "password": "correct-horse-battery"})
    return email, {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_chat_requires_login():
    assert client.get("/chat/messages").status_code == 401
    assert client.post("/chat/messages", json={"body": "hi"}).status_code == 401


def test_new_user_has_empty_history():
    _, h = signed_in()
    r = client.get("/chat/messages", headers=h)
    assert r.status_code == 200
    assert r.json()["messages"] == []


def test_send_returns_user_message_and_echo_reply_in_order():
    _, h = signed_in()
    r = client.post("/chat/messages", json={"body": "  hello  "}, headers=h)
    assert r.status_code == 201
    user_msg, bot_msg = r.json()["messages"]
    assert (user_msg["sender"], user_msg["body"]) == ("USER", "hello")
    assert (bot_msg["sender"], bot_msg["body"]) == ("BOT", "Echo: hello")
    assert user_msg["created_at"] < bot_msg["created_at"]


def test_history_persists_and_is_ordered():
    _, h = signed_in()
    for word in ("one", "two"):
        client.post("/chat/messages", json={"body": word}, headers=h)
    msgs = client.get("/chat/messages", headers=h).json()["messages"]
    assert [m["body"] for m in msgs] == ["one", "Echo: one", "two", "Echo: two"]
    assert client.get("/chat/messages?limit=2", headers=h).json()["messages"][0]["body"] == "two"


def test_messages_are_stored_in_database_and_one_active_conversation():
    email, h = signed_in()
    first = client.get("/chat/messages", headers=h).json()["conversation_id"]
    client.post("/chat/messages", json={"body": "stored?"}, headers=h)
    second = client.get("/chat/messages", headers=h).json()["conversation_id"]
    assert first == second
    with get_engine().connect() as c:
        rows = c.execute(
            text(
                "SELECT m.sender, m.body FROM messages m "
                "JOIN conversations cv ON cv.id = m.conversation_id "
                "JOIN users u ON u.id = cv.user_id WHERE u.email = :e ORDER BY m.created_at"
            ),
            {"e": email},
        ).all()
        active = c.execute(
            text(
                "SELECT count(*) FROM conversations cv JOIN users u ON u.id = cv.user_id "
                "WHERE u.email = :e AND cv.status = 'ACTIVE'"
            ),
            {"e": email},
        ).scalar()
    assert [(r.sender, r.body) for r in rows] == [("USER", "stored?"), ("BOT", "Echo: stored?")]
    assert active == 1


def test_users_cannot_see_each_others_messages():
    _, alice = signed_in()
    _, bob = signed_in()
    client.post("/chat/messages", json={"body": "secret"}, headers=alice)
    assert client.get("/chat/messages", headers=bob).json()["messages"] == []


@pytest.mark.parametrize("body", ["", "   ", "x" * 4001])
def test_invalid_messages_rejected(body):
    _, h = signed_in()
    assert client.post("/chat/messages", json={"body": body}, headers=h).status_code == 422
