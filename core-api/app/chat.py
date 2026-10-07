import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from app.auth import current_user
from app.conversations import (
    MessageOut,
    active_conversation,
    close_active,
    recent_messages,
    run_turn,
)
from app.db import shared_engine
from app.media import owned_uploads

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


class ChatOut(BaseModel):
    conversation_id: str
    messages: list[MessageOut]


@router.get("/messages", response_model=ChatOut)
def history(user: User, limit: Annotated[int, Query(ge=1, le=200)] = 100):
    with shared_engine().begin() as conn:
        cid = active_conversation(conn, user["id"])
        messages = recent_messages(conn, cid, limit)
    return ChatOut(conversation_id=cid, messages=messages)


@router.post("/new", response_model=ChatOut, status_code=201)
def new_conversation(user: User):
    """Close the current conversation and start an empty one (for a different problem)."""
    with shared_engine().begin() as conn:
        close_active(conn, user["id"])
        cid = active_conversation(conn, user["id"])
    return ChatOut(conversation_id=cid, messages=[])


@router.post("/messages", response_model=ChatOut, status_code=201)
def send(body: MessageIn, user: User):
    with shared_engine().connect() as conn:
        uploads = owned_uploads(conn, user["id"], body.media_ids)
    if len(uploads) != len(body.media_ids):
        raise HTTPException(400, "One or more photos were not found")
    turn = run_turn(user["id"], "WEB", body.body, uploads)
    return ChatOut(conversation_id=turn.conversation_id, messages=[turn.mine, turn.bot])
