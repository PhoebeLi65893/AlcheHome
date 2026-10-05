from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text

from app import bot
from app.auth import current_user
from app.db import shared_engine

router = APIRouter(prefix="/chat", tags=["chat"])

MAX_LEN = 4000
User = Annotated[dict, Depends(current_user)]


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_LEN)

    @field_validator("body")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Message cannot be empty")
        return v


class MessageOut(BaseModel):
    id: str
    sender: str
    body: str
    created_at: datetime


class ChatOut(BaseModel):
    conversation_id: str
    messages: list[MessageOut]


def active_conversation(conn, user_id) -> str:
    """Get the user's single ACTIVE web conversation, creating it if needed."""
    conn.execute(
        text(
            "INSERT INTO conversations (user_id, channel) VALUES (:u, 'WEB') "
            "ON CONFLICT (user_id, channel) WHERE status = 'ACTIVE' DO NOTHING"
        ),
        {"u": user_id},
    )
    return str(
        conn.execute(
            text(
                "SELECT id FROM conversations "
                "WHERE user_id = :u AND channel = 'WEB' AND status = 'ACTIVE'"
            ),
            {"u": user_id},
        ).scalar_one()
    )


def _store(conn, conversation_id: str, sender: str, body: str) -> MessageOut:
    # clock_timestamp() (not now()) so the user message and bot reply in one
    # transaction get different timestamps and keep their order.
    row = conn.execute(
        text(
            "INSERT INTO messages (conversation_id, sender, body, created_at) "
            "VALUES (:c, :s, :b, clock_timestamp()) RETURNING id, sender, body, created_at"
        ),
        {"c": conversation_id, "s": sender, "b": body},
    ).one()
    return MessageOut(id=str(row.id), sender=row.sender, body=row.body, created_at=row.created_at)


@router.get("/messages", response_model=ChatOut)
def history(user: User, limit: Annotated[int, Query(ge=1, le=200)] = 100):
    with shared_engine().begin() as conn:
        cid = active_conversation(conn, user["id"])
        rows = conn.execute(
            text(
                "SELECT id, sender, body, created_at FROM ("
                "  SELECT id, sender, body, created_at FROM messages "
                "  WHERE conversation_id = :c ORDER BY created_at DESC LIMIT :l"
                ") recent ORDER BY created_at"
            ),
            {"c": cid, "l": limit},
        ).all()
    return ChatOut(
        conversation_id=cid,
        messages=[
            MessageOut(id=str(r.id), sender=r.sender, body=r.body, created_at=r.created_at)
            for r in rows
        ],
    )


@router.post("/messages", response_model=ChatOut, status_code=201)
def send(body: MessageIn, user: User):
    with shared_engine().begin() as conn:
        cid = active_conversation(conn, user["id"])
        mine = _store(conn, cid, "USER", body.body)
        reply = _store(conn, cid, "BOT", bot.reply_to(body.body))
    return ChatOut(conversation_id=cid, messages=[mine, reply])
