import json
import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text

from app.agent import service as agent
from app.agent.context import MAX_TURNS
from app.auth import current_user
from app.db import shared_engine
from app.media import owned_uploads
from app.storage import get_storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

MAX_LEN = 4000
MAX_PHOTOS = 3
User = Annotated[dict, Depends(current_user)]


class MessageIn(BaseModel):
    body: str = Field(default="", max_length=MAX_LEN)
    media_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_PHOTOS)

    @model_validator(mode="after")
    def text_or_photo(self):
        self.body = self.body.strip()
        self.media_ids = list(dict.fromkeys(self.media_ids))  # drop duplicates, keep order
        if not self.body and not self.media_ids:
            raise ValueError("Message cannot be empty")
        return self


class MessageOut(BaseModel):
    id: str
    sender: str
    body: str
    created_at: datetime
    flag: str | None = None
    media_ids: list[str] = []


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


def _message(row) -> MessageOut:
    return MessageOut(
        id=str(row.id),
        sender=row.sender,
        body=row.body,
        created_at=row.created_at,
        flag=row.flag,
        media_ids=list(row.media_refs or []),
    )


def _store(conn, conversation_id: str, sender: str, body: str, flag: str | None = None, media=()):
    # clock_timestamp() (not now()) so the user message and bot reply get different
    # timestamps and keep their order.
    row = conn.execute(
        text(
            "INSERT INTO messages (conversation_id, sender, body, flag, media_refs, created_at) "
            "VALUES (:c, :s, :b, :f, CAST(:m AS jsonb), clock_timestamp()) "
            "RETURNING id, sender, body, flag, media_refs, created_at"
        ),
        {
            "c": conversation_id,
            "s": sender,
            "b": body,
            "f": flag,
            "m": json.dumps([str(m) for m in media]),
        },
    ).one()
    return _message(row)


def _recent(conn, conversation_id: str, limit: int):
    return conn.execute(
        text(
            "SELECT id, sender, body, flag, media_refs, created_at FROM ("
            "  SELECT id, sender, body, flag, media_refs, created_at FROM messages "
            "  WHERE conversation_id = :c ORDER BY created_at DESC LIMIT :l"
            ") recent ORDER BY created_at"
        ),
        {"c": conversation_id, "l": limit},
    ).all()


@router.get("/messages", response_model=ChatOut)
def history(user: User, limit: Annotated[int, Query(ge=1, le=200)] = 100):
    with shared_engine().begin() as conn:
        cid = active_conversation(conn, user["id"])
        rows = _recent(conn, cid, limit)
    return ChatOut(conversation_id=cid, messages=[_message(r) for r in rows])


@router.post("/messages", response_model=ChatOut, status_code=201)
def send(body: MessageIn, user: User):
    # Step 1: check the photos, save the user's message and read the context (short transaction).
    with shared_engine().begin() as conn:
        uploads = owned_uploads(conn, user["id"], body.media_ids)
        if len(uploads) != len(body.media_ids):
            raise HTTPException(400, "One or more photos were not found")
        cid = active_conversation(conn, user["id"])
        mine = _store(conn, cid, "USER", body.body, media=body.media_ids)
        context = _recent(conn, cid, MAX_TURNS)
    # Step 2: load the photo bytes and ask the agent. This can take seconds, so no
    # database transaction is held open.
    storage = get_storage()
    images = []
    for u in uploads:
        try:
            images.append((u.mime_type, storage.load(u.storage_key)))
        except OSError:
            logger.warning("Upload %s missing from storage; sending text only", u.id)
    reply = agent.respond(context, body.body, images)
    # Step 3: save the reply.
    with shared_engine().begin() as conn:
        bot_msg = _store(
            conn, cid, "BOT", reply.text, flag="EMERGENCY" if reply.emergency else None
        )
    return ChatOut(conversation_id=cid, messages=[mine, bot_msg])
