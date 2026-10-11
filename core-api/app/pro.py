"""Handyman app API: job offers, assigned jobs, an AI assistant for the job, account setup."""

import hashlib
import logging
import uuid
from datetime import datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app import relay
from app.agent import gemini
from app.agent.pro_prompt import PRO_PROMPT
from app.auth import TokenOut, current_user, issue_tokens
from app.config import get_settings
from app.db import shared_engine
from app.dispatch import deliver, handle_handyman_reply
from app.security import hash_password
from app.tickets.service import LABELS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pro", tags=["handyman"])


def handyman_user(user: Annotated[dict, Depends(current_user)]) -> dict:
    if user["role"] != "HANDYMAN":
        raise HTTPException(403, "Handymen only")
    return user


Pro = Annotated[dict, Depends(handyman_user)]
HISTORY_TURNS = 20
UNAVAILABLE = "The assistant is not configured yet (no GEMINI_API_KEY). Please try again later."
FALLBACK = "Sorry, the assistant is having trouble right now. Please try again in a moment."


class Job(BaseModel):
    ticket_id: str
    number: int
    category: str
    category_label: str
    urgency: str
    location_zip: str
    issue_summary: str
    severity: str | None
    status: str
    customer: str  # first name only
    expires_at: datetime | None = None  # offers: when the offer times out
    unread: int = 0


class Jobs(BaseModel):
    offers: list[Job]
    active: list[Job]
    past: list[Job]


class SetPasswordIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=10, max_length=128)


class AssistantIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class AssistantMsg(BaseModel):
    sender: str
    body: str
    created_at: datetime


class Draft(BaseModel):
    draft: str


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------- account setup (invite link from an admin) ----------
@router.post("/set-password", response_model=TokenOut)
def set_password(body: SetPasswordIn):
    with shared_engine().begin() as conn:
        row = conn.execute(
            text(
                "SELECT user_id FROM invite_tokens WHERE token_hash = :h AND used_at IS NULL "
                "AND expires_at > now() FOR UPDATE"
            ),
            {"h": hash_token(body.token)},
        ).first()
        if row is None:
            raise HTTPException(400, "This invite link is invalid or has expired")
        role = conn.execute(
            text(
                "UPDATE users SET password_hash = :p WHERE id = :u AND role = 'HANDYMAN' "
                "RETURNING role"
            ),
            {"p": hash_password(body.password), "u": row.user_id},
        ).scalar()
        if role is None:
            raise HTTPException(400, "This invite link is invalid or has expired")
        conn.execute(
            text("UPDATE invite_tokens SET used_at = now() WHERE token_hash = :h"),
            {"h": hash_token(body.token)},
        )
        tokens, _ = issue_tokens(conn, row.user_id, role)
    return tokens


# ---------- jobs ----------
def _job(r, unread: int = 0) -> Job:
    return Job(
        ticket_id=str(r.id),
        number=r.ticket_number,
        category=r.category,
        category_label=LABELS[r.category],
        urgency=r.urgency,
        location_zip=r.location_zip,
        issue_summary=r.issue_summary,
        severity=r.severity,
        status=r.status,
        customer=(r.customer_name or "").split(" ")[0] or "Customer",
        expires_at=getattr(r, "expires_at", None),
        unread=unread,
    )


JOB_COLUMNS = (
    "t.id, t.ticket_number, t.category, t.urgency, t.location_zip, t.issue_summary, "
    "t.severity, t.status, cu.display_name AS customer_name"
)


@router.get("/jobs", response_model=Jobs)
def jobs(user: Pro):
    with shared_engine().begin() as conn:
        relay.touch(conn, user["id"])
        offers = conn.execute(
            text(
                f"SELECT {JOB_COLUMNS}, o.expires_at FROM dispatch_offers o "
                "JOIN tickets t ON t.id = o.ticket_id JOIN users cu ON cu.id = t.customer_id "
                "WHERE o.handyman_id = :h AND o.status = 'SENT' AND t.status = 'MATCHING' "
                "AND o.expires_at > now() ORDER BY o.sent_at DESC"
            ),
            {"h": user["id"]},
        ).all()
        mine = conn.execute(
            text(
                f"SELECT {JOB_COLUMNS}, "
                "(SELECT count(*) FROM messages m WHERE m.relay_ticket_id = t.id "
                " AND m.sender = 'USER' AND m.created_at > COALESCE("
                "  (SELECT last_read_at FROM thread_reads "
                "   WHERE user_id = :h AND ticket_id = t.id), "
                "  'epoch'::timestamptz)) AS unread "
                "FROM tickets t JOIN users cu ON cu.id = t.customer_id "
                "WHERE t.assigned_handyman_id = :h ORDER BY t.updated_at DESC LIMIT 60"
            ),
            {"h": user["id"]},
        ).all()
    active = [_job(r, r.unread) for r in mine if r.status in relay.ACTIVE]
    past = [_job(r) for r in mine if r.status not in relay.ACTIVE][:20]
    return Jobs(offers=[_job(r) for r in offers], active=active, past=past)


def _ticket_number(conn, ticket_id, handyman_id) -> int:
    n = conn.execute(
        text(
            "SELECT t.ticket_number FROM tickets t WHERE t.id = :t AND ("
            " t.assigned_handyman_id = :h OR EXISTS (SELECT 1 FROM dispatch_offers o "
            " WHERE o.ticket_id = t.id AND o.handyman_id = :h))"
        ),
        {"t": ticket_id, "h": handyman_id},
    ).scalar()
    if n is None:
        raise HTTPException(404, "Job not found")
    return n


class Answer(BaseModel):
    message: str
    status: str


def _answer(ticket_id, user, word: str) -> Answer:
    with shared_engine().connect() as conn:
        number = _ticket_number(conn, ticket_id, user["id"])
    reply, others = handle_handyman_reply(user["id"], f"{word} {number}")
    deliver(others)
    with shared_engine().connect() as conn:
        t = conn.execute(
            text("SELECT status, assigned_handyman_id FROM tickets WHERE id = :t"),
            {"t": ticket_id},
        ).one()
    if word == "ACCEPT" and str(t.assigned_handyman_id) != str(user["id"]):
        raise HTTPException(409, reply)
    return Answer(message=reply, status=t.status)


@router.post("/jobs/{ticket_id}/accept", response_model=Answer)
def accept(ticket_id: uuid.UUID, user: Pro):
    return _answer(ticket_id, user, "ACCEPT")


@router.post("/jobs/{ticket_id}/decline", response_model=Answer)
def decline(ticket_id: uuid.UUID, user: Pro):
    return _answer(ticket_id, user, "DECLINE")


# ---------- AI assistant for the job ----------
def _job_note(conn, ticket_id, handyman_id) -> tuple[str, str]:
    """(situation note for the model, handyman display name). 404 unless it is their job."""
    _ticket_number(conn, ticket_id, handyman_id)
    t = conn.execute(
        text(
            "SELECT t.ticket_number, t.category, t.urgency, t.location_zip, t.issue_summary, "
            "t.severity, t.status, cu.display_name AS customer_name, h.display_name "
            "FROM tickets t JOIN users cu ON cu.id = t.customer_id "
            "JOIN handymen h ON h.user_id = :h WHERE t.id = :t"
        ),
        {"t": ticket_id, "h": handyman_id},
    ).one()
    first = (t.customer_name or "").split(" ")[0] or "the customer"
    note = (
        f"Job #{t.ticket_number}: {LABELS[t.category]}, urgency {t.urgency}, ZIP {t.location_zip}, "
        f"status {t.status}, severity {t.severity or 'unknown'}. Customer: {first}. "
        f"Customer's description: {t.issue_summary}"
    )
    return note, t.display_name


def _history(conn, ticket_id, handyman_id) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT sender, body, created_at FROM pro_ai_messages "
            "WHERE handyman_id = :h AND ticket_id = :t ORDER BY id DESC LIMIT :l"
        ),
        {"h": handyman_id, "t": ticket_id, "l": HISTORY_TURNS},
    ).all()
    return list(reversed(rows))


def _contents(rows, extra_user: str | None = None) -> list[dict]:
    contents: list[dict] = []
    for r in rows:
        role = "user" if r.sender == "USER" else "model"
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"][0]["text"] += "\n" + r.body
        else:
            contents.append({"role": role, "parts": [{"text": r.body}]})
    if extra_user:
        if contents and contents[-1]["role"] == "user":
            contents[-1]["parts"][0]["text"] += "\n" + extra_user
        else:
            contents.append({"role": "user", "parts": [{"text": extra_user}]})
    while contents and contents[0]["role"] != "user":
        contents.pop(0)
    return contents


def _ask(contents, note: str) -> str | None:
    if not get_settings().gemini_api_key:
        return None
    try:
        return gemini.generate(contents, system=PRO_PROMPT, note=note).text or FALLBACK
    except (gemini.GeminiError, httpx.HTTPError) as e:
        logger.warning("Handyman assistant call failed: %s", type(e).__name__)
        return FALLBACK


@router.get("/jobs/{ticket_id}/assistant", response_model=list[AssistantMsg])
def assistant_history(ticket_id: uuid.UUID, user: Pro):
    with shared_engine().connect() as conn:
        _ticket_number(conn, ticket_id, user["id"])
        rows = _history(conn, ticket_id, user["id"])
    return [AssistantMsg(sender=r.sender, body=r.body, created_at=r.created_at) for r in rows]


@router.post("/jobs/{ticket_id}/assistant", response_model=list[AssistantMsg])
def assistant(ticket_id: uuid.UUID, body: AssistantIn, user: Pro):
    text_in = " ".join(body.body.split())
    with shared_engine().begin() as conn:
        note, _ = _job_note(conn, ticket_id, user["id"])
        conn.execute(
            text(
                "INSERT INTO pro_ai_messages (handyman_id, ticket_id, sender, body) "
                "VALUES (:h, :t, 'USER', :b)"
            ),
            {"h": user["id"], "t": ticket_id, "b": text_in},
        )
        rows = _history(conn, ticket_id, user["id"])
    reply = _ask(_contents(rows), note) or UNAVAILABLE
    with shared_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO pro_ai_messages (handyman_id, ticket_id, sender, body) "
                "VALUES (:h, :t, 'BOT', :b)"
            ),
            {"h": user["id"], "t": ticket_id, "b": reply},
        )
        rows = _history(conn, ticket_id, user["id"])
    return [AssistantMsg(sender=r.sender, body=r.body, created_at=r.created_at) for r in rows]


@router.post("/jobs/{ticket_id}/draft", response_model=Draft)
def draft_reply(ticket_id: uuid.UUID, user: Pro):
    """A suggested message to the customer. Never sent automatically: the handyman edits it."""
    with shared_engine().begin() as conn:
        note, name = _job_note(conn, ticket_id, user["id"])
        rows = _history(conn, ticket_id, user["id"])
        thread = conn.execute(
            text(
                "SELECT sender, body FROM messages WHERE relay_ticket_id = :t "
                "ORDER BY created_at DESC LIMIT 6"
            ),
            {"t": ticket_id},
        ).all()
        label = conn.execute(
            text("SELECT category, ticket_number FROM tickets WHERE id = :t"), {"t": ticket_id}
        ).one()
    convo = "\n".join(
        ("Customer: " if m.sender == "USER" else "Me: ") + m.body for m in reversed(thread)
    )
    ask = (
        "Write one short, friendly message from me to the customer about this job"
        + (f", answering their latest message. Recent messages:\n{convo}" if convo else "")
        + "\nOutput only the message text, no quotes, under 300 characters."
    )
    drafted = _ask(_contents(rows, ask), note)
    if drafted is None or drafted == FALLBACK:
        drafted = (
            f"Hi, this is {name} from Alche Home. I'll take care of your "
            f"{LABELS[label.category].lower()} request (#{label.ticket_number}). "
            "When is a good time for me to come by?"
        )
    return Draft(draft=drafted.strip()[: relay.MAX_LEN])
