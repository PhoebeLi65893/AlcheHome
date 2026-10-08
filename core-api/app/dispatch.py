"""Dispatch by SMS: offer a ticket to the best handyman, handle ACCEPT/DECLINE, time out, fall back.

One offer is out at a time. A declined or expired offer rolls to the next-ranked handyman who has
not been asked yet; after MAX_ATTEMPTS offers (or when nobody is left) the ticket becomes
UNMATCHED. The offer SMS shows the ZIP only, never the street address.

Functions take an open connection and return the SMS messages to send; callers send them with
`deliver()` after the transaction commits, so a rolled-back change never texts anyone.
"""

import logging
import re
from dataclasses import dataclass

from sqlalchemy import text

from app.channels import twilio
from app.config import get_settings
from app.conversations import store_message
from app.db import shared_engine
from app.matching import find_candidates, rank
from app.tickets.service import LABELS, get_card
from app.tickets.state import transition

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
TIMEOUT_SECONDS = {"EMERGENCY": 3 * 60, "SAME_DAY": 15 * 60, "FLEXIBLE": 2 * 60 * 60}
WHEN = {"EMERGENCY": "emergency", "SAME_DAY": "today", "FLEXIBLE": "flexible timing"}
REPLY_RE = re.compile(
    r"^\s*(ACCEPT|ACCEPTED|YES|Y|DECLINE|NO|N)\b\s*#?\s*(\d+)?\s*[.!]*\s*$", re.IGNORECASE
)
ACCEPT_WORDS = {"ACCEPT", "ACCEPTED", "YES", "Y"}
HELP_REPLY = "To answer a job offer reply ACCEPT <number> or DECLINE <number>, e.g. ACCEPT 1024."


@dataclass(frozen=True)
class Outgoing:
    phone: str
    body: str


def timeout_seconds(urgency: str) -> float:
    return get_settings().dispatch_timeout_s or TIMEOUT_SECONDS[urgency]


def _minutes(seconds: float) -> str:
    m = round(seconds / 60)
    return f"{m} min" if m < 120 else f"{round(m / 60)} h"


def offer_text(t, seconds: float) -> str:
    summary = t.issue_summary if len(t.issue_summary) <= 140 else t.issue_summary[:137] + "..."
    return (
        f"Alche Home job #{t.ticket_number}: {LABELS[t.category]}, {WHEN[t.urgency]}, "
        f"ZIP {t.location_zip}. {summary} Reply ACCEPT {t.ticket_number} to take it or "
        f"DECLINE {t.ticket_number}. Expires in {_minutes(seconds)}."
    )


def deliver(messages: list[Outgoing]) -> None:
    for m in messages:
        try:
            twilio.send_sms(m.phone, m.body)
        except twilio.TwilioError as e:
            logger.warning("Could not send dispatch SMS to %s: %s", twilio.mask(m.phone), e)


def _ticket(conn, ticket_id, lock=False):
    return conn.execute(
        text(
            "SELECT id, ticket_number, customer_id, category, urgency, location_zip, "
            "issue_summary, status FROM tickets WHERE id = :t" + (" FOR UPDATE" if lock else "")
        ),
        {"t": ticket_id},
    ).one()


def notify_customer(conn, t, body: str) -> list[Outgoing]:
    """Post an update into the customer's conversation (and text it if they use SMS)."""
    row = conn.execute(
        text(
            "SELECT c.id, c.channel, u.phone_e164, u.sms_opted_out FROM conversations c "
            "JOIN users u ON u.id = c.user_id WHERE c.ticket_id = :t"
        ),
        {"t": t.id},
    ).first()
    if row is None:
        return []
    store_message(conn, str(row.id), "BOT", body, ticket=get_card(conn, t.id))
    if row.channel == "SMS" and row.phone_e164 and not row.sms_opted_out:
        return [Outgoing(row.phone_e164, body)]
    return []


def _next_offer(conn, t, preferred: str | None = None) -> list[Outgoing]:
    """Ticket `t` is MATCHING and locked: offer it to the next handyman, or give up.

    `preferred` (the customer's pick) goes first if they are eligible; otherwise, and for every
    later offer, the best-ranked handyman who has not been asked yet.
    """
    tried = {
        str(r[0])
        for r in conn.execute(
            text("SELECT handyman_id FROM dispatch_offers WHERE ticket_id = :t"), {"t": t.id}
        )
    }
    nxt = None
    if len(tried) < MAX_ATTEMPTS:
        ranked = rank(find_candidates(conn, t.category, t.location_zip), t.urgency, t.location_zip)
        untried = [r for r in ranked if r.candidate.handyman_id not in tried]
        nxt = next((r for r in untried if r.candidate.handyman_id == preferred), None)
        nxt = nxt or next(iter(untried), None)
    if nxt is None:
        transition(conn, t.id, "UNMATCHED", "dispatch")
        logger.info("Ticket #%s is UNMATCHED after %d offers", t.ticket_number, len(tried))
        return notify_customer(
            conn,
            t,
            f"We couldn't find an available handyman for request #{t.ticket_number} yet. "
            "Our team has been alerted and will follow up.",
        )
    seconds = timeout_seconds(t.urgency)
    body = offer_text(t, seconds)
    conn.execute(
        text(
            "INSERT INTO dispatch_offers (ticket_id, handyman_id, message, expires_at) "
            "VALUES (:t, :h, :m, clock_timestamp() + make_interval(secs => :s))"
        ),
        {"t": t.id, "h": nxt.candidate.handyman_id, "m": body, "s": seconds},
    )
    phone = conn.execute(
        text("SELECT phone_e164 FROM users WHERE id = :h"), {"h": nxt.candidate.handyman_id}
    ).scalar()
    logger.info("Offered ticket #%s to a handyman (offer %d)", t.ticket_number, len(tried) + 1)
    return [Outgoing(phone, body)] if phone else []


class NotEligible(ValueError):
    """The preferred handyman cannot take this ticket."""


def start_dispatch(ticket_id, preferred=None, actor: str = "dispatch") -> bool:
    """Move an OPEN (or UNMATCHED) ticket to MATCHING and send the first offer.

    With `preferred` (a handyman id) that person is asked first; if they decline or do not
    answer, the offers continue down the ranking. Raises NotEligible for someone who does not
    cover the ticket's ZIP, lacks the skill or is unavailable.
    """
    preferred = str(preferred) if preferred else None
    with shared_engine().begin() as conn:
        t = _ticket(conn, ticket_id, lock=True)
        if t.status not in ("OPEN", "UNMATCHED"):
            return False
        if preferred and preferred not in {
            c.handyman_id for c in find_candidates(conn, t.category, t.location_zip)
        }:
            raise NotEligible(preferred)
        transition(conn, t.id, "MATCHING", actor)
        if t.status == "UNMATCHED":  # a retry starts with a clean slate of handymen
            conn.execute(text("DELETE FROM dispatch_offers WHERE ticket_id = :t"), {"t": t.id})
        out = _next_offer(conn, t, preferred)
    deliver(out)
    return True


def handle_handyman_reply(user_id, body: str) -> tuple[str, list[Outgoing]]:
    """Process an SMS from a handyman. Returns (reply text for them, other messages to send)."""
    m = REPLY_RE.match(body)
    if not m:
        return HELP_REPLY, []
    accept = m.group(1).upper() in ACCEPT_WORDS
    number = int(m.group(2)) if m.group(2) else None
    with shared_engine().begin() as conn:
        pending = conn.execute(
            text(
                "SELECT o.id, o.ticket_id, t.ticket_number FROM dispatch_offers o "
                "JOIN tickets t ON t.id = o.ticket_id "
                "WHERE o.handyman_id = :h AND o.status = 'SENT' "
                "AND (CAST(:n AS BIGINT) IS NULL OR t.ticket_number = :n) "
                "ORDER BY o.sent_at DESC"
            ),
            {"h": user_id, "n": number},
        ).all()
        if not pending:
            what = f"Job #{number} is" if number else "That job is"
            return f"{what} no longer available. Thanks for responding.", []
        if len(pending) > 1:
            return (
                "You have more than one open offer. Reply with the job number, e.g. ACCEPT 1024.",
                [],
            )
        offer = pending[0]
        t = _ticket(conn, offer.ticket_id, lock=True)
        cur = conn.execute(
            text(
                "SELECT status, expires_at < clock_timestamp() AS late "
                "FROM dispatch_offers WHERE id = :o FOR UPDATE"
            ),
            {"o": offer.id},
        ).one()
        gone = f"Job #{t.ticket_number} is no longer available. Thanks for responding."
        if cur.status != "SENT":
            return gone, []
        if t.status != "MATCHING":  # the customer cancelled, or it was assigned elsewhere
            _close(conn, offer.id, "EXPIRED")
            return gone, []
        if cur.late:  # too slow: the sweeper hasn't rolled it yet, so do it now
            _close(conn, offer.id, "EXPIRED")
            return gone, _next_offer(conn, t)
        if not accept:
            _close(conn, offer.id, "DECLINED")
            return f"No problem, we've passed job #{t.ticket_number} on.", _next_offer(conn, t)
        _close(conn, offer.id, "ACCEPTED")
        conn.execute(
            text("UPDATE tickets SET assigned_handyman_id = :h WHERE id = :t"),
            {"h": user_id, "t": t.id},
        )
        transition(conn, t.id, "ASSIGNED", f"handyman:{user_id}")
        name = conn.execute(
            text("SELECT display_name FROM handymen WHERE user_id = :h"), {"h": user_id}
        ).scalar()
        out = notify_customer(
            conn,
            t,
            f"Good news: {name} has accepted repair request #{t.ticket_number} "
            f"({LABELS[t.category]}). They'll be in touch about the visit.",
        )
        return (
            f"Thanks! You're assigned to job #{t.ticket_number}. We'll send the details next.",
            out,
        )


def _close(conn, offer_id, status: str) -> None:
    conn.execute(
        text(
            "UPDATE dispatch_offers SET status = :s, responded_at = clock_timestamp() "
            "WHERE id = :o"
        ),
        {"s": status, "o": offer_id},
    )


def expire_overdue() -> int:
    """Roll every timed-out offer to the next handyman. Returns how many offers expired."""
    with shared_engine().connect() as conn:
        due = [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT id FROM dispatch_offers "
                    "WHERE status = 'SENT' AND expires_at < clock_timestamp()"
                )
            )
        ]
    count = 0
    for offer_id in due:
        with shared_engine().begin() as conn:
            row = conn.execute(
                text("SELECT ticket_id FROM dispatch_offers WHERE id = :o"), {"o": offer_id}
            ).one()
            t = _ticket(conn, row.ticket_id, lock=True)  # same lock order as replies
            still = conn.execute(
                text("SELECT 1 FROM dispatch_offers WHERE id = :o AND status = 'SENT' FOR UPDATE"),
                {"o": offer_id},
            ).first()
            if not still:
                continue
            _close(conn, offer_id, "EXPIRED")
            count += 1
            out = _next_offer(conn, t) if t.status == "MATCHING" else []
        deliver(out)
    return count
