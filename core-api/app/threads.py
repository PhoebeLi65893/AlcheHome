"""Messages view API: one conversation per job between a customer and their handyman.

Used by both the customer app and the handyman app. Customers see the handyman's display name,
handymen see only the customer's first name; phone numbers never appear. Reading a conversation
marks it read, and any call here counts as "active in the app" so we do not also send an SMS.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app import relay
from app.auth import current_user
from app.db import shared_engine
from app.dispatch import deliver
from app.tickets.service import LABELS

router = APIRouter(prefix="/threads", tags=["messages"])


def messaging_user(user: Annotated[dict, Depends(current_user)]) -> dict:
    # Admins can also use the customer app, so they take part as the customer of their own
    # tickets. Every query below is limited to tickets that belong to the caller.
    if user["role"] not in ("CUSTOMER", "HANDYMAN", "ADMIN"):
        raise HTTPException(403, "Messages are for customers and handymen")
    return user


User = Annotated[dict, Depends(messaging_user)]


class ThreadSummary(BaseModel):
    ticket_id: str
    number: int
    category: str
    category_label: str
    status: str
    counterpart: str
    last_body: str | None
    last_at: datetime | None
    last_from_me: bool | None
    unread: int
    open: bool


class ThreadList(BaseModel):
    threads: list[ThreadSummary]
    unread_total: int


class ChatMessage(BaseModel):
    id: str
    mine: bool
    body: str
    created_at: datetime


class ChatOut(BaseModel):
    ticket_id: str
    number: int
    category_label: str
    status: str
    issue_summary: str
    location_zip: str
    counterpart: str
    open: bool
    other_read_at: datetime | None  # when the other person last opened the conversation
    messages: list[ChatMessage]


class SendIn(BaseModel):
    body: str = Field(min_length=1, max_length=relay.MAX_LEN)


def _side(user) -> tuple[str, str]:
    """(column that identifies me on a ticket, sender value of my messages)."""
    if user["role"] == "HANDYMAN":
        return "assigned_handyman_id", "HANDYMAN"
    return "customer_id", "USER"  # customers, and admins acting as customers


def _first_name(display_name: str | None) -> str:
    return (display_name or "").split(" ")[0] or "Customer"


@router.get("", response_model=ThreadList)
def list_threads(user: User):
    col, mine = _side(user)
    with shared_engine().begin() as conn:
        relay.touch(conn, user["id"])
        rows = conn.execute(
            text(
                f"SELECT t.id, t.ticket_number, t.category, t.status, "
                f"h.display_name AS handyman_name, cu.display_name AS customer_name, "
                f"last.body AS last_body, last.created_at AS last_at, last.sender AS last_sender, "
                f"(SELECT count(*) FROM messages m WHERE m.relay_ticket_id = t.id "
                f" AND m.sender <> :mine "
                f" AND m.created_at > COALESCE(tr.last_read_at, 'epoch'::timestamptz)) AS unread "
                f"FROM tickets t "
                f"JOIN users cu ON cu.id = t.customer_id "
                f"LEFT JOIN handymen h ON h.user_id = t.assigned_handyman_id "
                f"LEFT JOIN thread_reads tr ON tr.ticket_id = t.id AND tr.user_id = :u "
                f"LEFT JOIN LATERAL (SELECT body, created_at, sender FROM messages "
                f" WHERE relay_ticket_id = t.id ORDER BY created_at DESC LIMIT 1) last ON TRUE "
                f"WHERE t.{col} = :u AND t.assigned_handyman_id IS NOT NULL "
                f"AND (t.status = ANY(:active) OR last.body IS NOT NULL) "
                f"ORDER BY COALESCE(last.created_at, t.updated_at) DESC LIMIT 100"
            ),
            {"u": user["id"], "mine": mine, "active": list(relay.ACTIVE)},
        ).all()
    threads = [
        ThreadSummary(
            ticket_id=str(r.id),
            number=r.ticket_number,
            category=r.category,
            category_label=LABELS[r.category],
            status=r.status,
            counterpart=r.handyman_name or "Handyman"
            if user["role"] != "HANDYMAN"
            else _first_name(r.customer_name),
            last_body=r.last_body,
            last_at=r.last_at,
            last_from_me=None if r.last_sender is None else r.last_sender == mine,
            unread=r.unread,
            open=r.status in relay.ACTIVE,
        )
        for r in rows
    ]
    return ThreadList(threads=threads, unread_total=sum(t.unread for t in threads))


def _chat(conn, ticket_id, user, mark_read: bool) -> ChatOut:
    col, mine = _side(user)
    t = conn.execute(
        text(
            f"SELECT t.id, t.ticket_number, t.category, t.status, t.issue_summary, "
            f"t.location_zip, t.customer_id, t.assigned_handyman_id, "
            f"h.display_name AS handyman_name, cu.display_name AS customer_name "
            f"FROM tickets t JOIN users cu ON cu.id = t.customer_id "
            f"LEFT JOIN handymen h ON h.user_id = t.assigned_handyman_id "
            f"WHERE t.id = :t AND t.{col} = :u"
        ),
        {"t": ticket_id, "u": user["id"]},
    ).first()
    if t is None:
        raise HTTPException(404, "Conversation not found")
    other_id = t.assigned_handyman_id if user["role"] != "HANDYMAN" else t.customer_id
    rows = conn.execute(
        text(
            "SELECT id, sender, body, created_at FROM messages WHERE relay_ticket_id = :t "
            "ORDER BY created_at, id"
        ),
        {"t": ticket_id},
    ).all()
    other_read = conn.execute(
        text("SELECT last_read_at FROM thread_reads WHERE user_id = :u AND ticket_id = :t"),
        {"u": other_id, "t": ticket_id},
    ).scalar()
    if mark_read:
        conn.execute(
            text(
                "INSERT INTO thread_reads (user_id, ticket_id) VALUES (:u, :t) "
                "ON CONFLICT (user_id, ticket_id) DO UPDATE SET last_read_at = clock_timestamp()"
            ),
            {"u": user["id"], "t": ticket_id},
        )
    return ChatOut(
        ticket_id=str(t.id),
        number=t.ticket_number,
        category_label=LABELS[t.category],
        status=t.status,
        issue_summary=t.issue_summary,
        location_zip=t.location_zip,
        counterpart=(t.handyman_name or "Handyman")
        if user["role"] != "HANDYMAN"
        else _first_name(t.customer_name),
        open=t.status in relay.ACTIVE,
        other_read_at=other_read,
        messages=[
            ChatMessage(id=str(r.id), mine=r.sender == mine, body=r.body, created_at=r.created_at)
            for r in rows
        ],
    )


@router.get("/{ticket_id}/messages", response_model=ChatOut)
def messages(ticket_id: uuid.UUID, user: User):
    with shared_engine().begin() as conn:
        relay.touch(conn, user["id"])
        return _chat(conn, ticket_id, user, mark_read=True)


@router.post("/{ticket_id}/messages", response_model=ChatOut, status_code=201)
def send(ticket_id: uuid.UUID, body: SendIn, user: User):
    with shared_engine().begin() as conn:
        relay.touch(conn, user["id"])
        _chat(conn, ticket_id, user, mark_read=False)  # 404 unless it is my conversation
        if user["role"] == "HANDYMAN":
            ok, out = relay.send_from_handyman(conn, user["id"], ticket_id, body.body)
        else:
            ok, out = relay.send_to_handyman(conn, ticket_id, body.body)
        if not ok:
            raise HTTPException(409, "This conversation is closed")
        result = _chat(conn, ticket_id, user, mark_read=True)
    deliver(out)
    return result
