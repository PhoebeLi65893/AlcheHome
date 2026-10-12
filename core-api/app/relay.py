"""Customer <-> handyman messaging bridge, without exposing either phone number.

Both sides text (or use the web chat) through Alche Home's own number, so neither ever sees the
other's number. The bridge is open only while a ticket is ASSIGNED or IN_PROGRESS. Every relayed
message is stored in `messages` (in the customer's conversation, tagged with relay_ticket_id),
and is kept out of the AI assistant's context.

Customer -> handyman: web chat panel, or a text from an SMS customer.
Handyman -> customer: a text; start it with the job number (#1042 on my way) when they have
several open jobs.
"""

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text

from app import i18n, translate
from app.conversations import store_message
from app.dispatch import Outgoing

ACTIVE = ("ASSIGNED", "IN_PROGRESS")
MAX_LEN = 500
PREFIX_RE = re.compile(
    r"^\s*(?:job\s*|工单\s*)?#?(\d{4,})(?!\d)[\s:,.，：。-]*(.*)$", re.IGNORECASE | re.DOTALL
)


@dataclass(frozen=True)
class ThreadMessage:
    id: str
    sender: str  # CUSTOMER | HANDYMAN
    body: str
    created_at: datetime


def clean(body: str) -> str:
    return " ".join(body.split())[:MAX_LEN]


def _thread_ticket(conn, ticket_id):
    return conn.execute(
        text(
            "SELECT t.id, t.ticket_number, t.category, t.status, t.customer_id, "
            "t.assigned_handyman_id, h.display_name AS handyman_name, "
            "cu.phone_e164 AS customer_phone, cu.sms_opted_out AS customer_opted_out, "
            "hu.phone_e164 AS handyman_phone, hu.sms_opted_out AS handyman_opted_out, "
            "cu.language AS customer_lang, hu.language AS handyman_lang, "
            "COALESCE(cu.last_seen_at > now() - interval '2 minutes', FALSE) AS customer_active, "
            "COALESCE(hu.last_seen_at > now() - interval '2 minutes', FALSE) AS handyman_active, "
            "(SELECT c.id FROM conversations c WHERE c.ticket_id = t.id LIMIT 1) AS conv_id, "
            "(SELECT c.channel FROM conversations c WHERE c.ticket_id = t.id LIMIT 1) AS channel "
            "FROM tickets t JOIN users cu ON cu.id = t.customer_id "
            "LEFT JOIN handymen h ON h.user_id = t.assigned_handyman_id "
            "LEFT JOIN users hu ON hu.id = t.assigned_handyman_id WHERE t.id = :t"
        ),
        {"t": ticket_id},
    ).one()


def _log(conn, t, sender: str, body: str, reader_lang: str | None) -> str:
    """Store a relayed message and return the text the reader should get.

    The original is always kept. When the reader uses the other language it is translated
    automatically; if that fails they get the original.
    """
    lang = translate.detect(body)
    translations: dict[str, str] = {}
    shown = body
    if reader_lang and reader_lang != lang:
        tr = translate.translate(body, reader_lang)
        if tr:
            translations[reader_lang] = tr
            shown = tr
    if t.conv_id:
        store_message(
            conn,
            str(t.conv_id),
            sender,
            body,
            relay_ticket_id=t.id,
            lang=lang,
            translations=translations,
        )
    return shown


def thread(conn, ticket_id) -> list[ThreadMessage]:
    rows = conn.execute(
        text(
            "SELECT id, sender, body, created_at FROM messages WHERE relay_ticket_id = :t "
            "ORDER BY created_at, id"
        ),
        {"t": ticket_id},
    ).all()
    return [
        ThreadMessage(
            str(r.id), "HANDYMAN" if r.sender == "HANDYMAN" else "CUSTOMER", r.body, r.created_at
        )
        for r in rows
    ]


def send_to_handyman(conn, ticket_id, body: str) -> tuple[bool, list[Outgoing]]:
    """Customer -> handyman. Returns (accepted, SMS to send). Not accepted: bridge is closed."""
    t = _thread_ticket(conn, ticket_id)
    body = clean(body)
    if t.status not in ACTIVE or not body:
        return False, []
    shown = _log(conn, t, "USER", body, t.handyman_lang)
    out = []
    # Texting is the fallback: skip it while the handyman is looking at the app.
    if t.handyman_phone and not t.handyman_opted_out and not t.handyman_active:
        out.append(
            Outgoing(
                t.handyman_phone,
                i18n.t(t.handyman_lang, "to_handyman", n=t.ticket_number, body=shown),
            )
        )
    return True, out


def active_ticket_for_customer(conn, customer_id, number: int | None = None):
    rows = conn.execute(
        text(
            "SELECT id, ticket_number FROM tickets WHERE customer_id = :c "
            "AND status = ANY(:s) AND (CAST(:n AS BIGINT) IS NULL OR ticket_number = :n) "
            "ORDER BY updated_at DESC"
        ),
        {"c": customer_id, "s": list(ACTIVE), "n": number},
    ).all()
    return rows[0] if rows else None


def customer_text(conn, customer_id, body: str) -> list[Outgoing] | None:
    """An SMS customer's text. Returns SMS to send, or None when no job is open (go to the AI)."""
    m = PREFIX_RE.match(body)
    number, rest = (int(m.group(1)), m.group(2)) if m else (None, body)
    row = active_ticket_for_customer(conn, customer_id, number)
    if row is None and number is not None:
        row = active_ticket_for_customer(conn, customer_id)
        rest = body
    if row is None:
        return None
    ok, out = send_to_handyman(conn, row.id, rest)
    return out if ok else None


def handyman_text(conn, handyman_id, body: str) -> tuple[str, list[Outgoing]]:
    """A handyman's text that is not an offer answer. Returns (reply to them, SMS to send)."""
    lang = conn.execute(
        text("SELECT language FROM users WHERE id = :u"), {"u": handyman_id}
    ).scalar()
    rows = conn.execute(
        text(
            "SELECT id, ticket_number, status FROM tickets WHERE assigned_handyman_id = :h "
            "AND status = ANY(:s) ORDER BY updated_at DESC"
        ),
        {"h": handyman_id, "s": list(ACTIVE)},
    ).all()
    m = PREFIX_RE.match(body)
    number, rest = (int(m.group(1)), m.group(2)) if m else (None, body)
    if not rows:
        if number is not None:
            return i18n.t(lang, "closed", n=number), []
        return i18n.t(lang, "no_job"), []
    if number is not None:
        row = next((r for r in rows if r.ticket_number == number), None)
        if row is None and len(rows) == 1:  # the digits were part of the message, not a job number
            row, rest = rows[0], body
        elif row is None:
            return i18n.t(lang, "closed", n=number), []
    elif len(rows) == 1:
        row, rest = rows[0], body
    else:
        nums = ", ".join(f"#{r.ticket_number}" for r in rows)
        return i18n.t(lang, "several_jobs", nums=nums), []
    rest = clean(rest)
    if not rest:
        return i18n.t(lang, "write_after", n=row.ticket_number), []
    return "", _handyman_says(conn, row.id, rest)


def _handyman_says(conn, ticket_id, body: str) -> list[Outgoing]:
    """Store a handyman's message in the thread; return the SMS for the customer, if due."""
    t = _thread_ticket(conn, ticket_id)
    shown = _log(conn, t, "HANDYMAN", body, t.customer_lang)
    out = []
    # Texting is the fallback: skip it while the customer is looking at the app.
    if (
        t.channel == "SMS"
        and t.customer_phone
        and not t.customer_opted_out
        and not t.customer_active
    ):
        out.append(
            Outgoing(
                t.customer_phone,
                i18n.t(
                    t.customer_lang,
                    "to_customer",
                    name=t.handyman_name,
                    cat=i18n.category(t.customer_lang, t.category),
                    n=t.ticket_number,
                    body=shown,
                ),
            )
        )
    return out


def send_from_handyman(conn, handyman_id, ticket_id, body: str) -> tuple[bool, list[Outgoing]]:
    """A handyman's message from the web app. Not accepted: not their job, or bridge closed."""
    body = clean(body)
    row = conn.execute(
        text("SELECT status FROM tickets WHERE id = :t AND assigned_handyman_id = :h"),
        {"t": ticket_id, "h": handyman_id},
    ).first()
    if row is None or row.status not in ACTIVE or not body:
        return False, []
    return True, _handyman_says(conn, ticket_id, body)


def touch(conn, user_id) -> None:
    """Note that this user is looking at the app right now (presence for the SMS fallback)."""
    conn.execute(
        text("UPDATE users SET last_seen_at = clock_timestamp() WHERE id = :u"), {"u": user_id}
    )
