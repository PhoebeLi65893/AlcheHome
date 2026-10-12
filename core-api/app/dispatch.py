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

from app import i18n
from app.channels import twilio
from app.config import get_settings
from app.conversations import store_message
from app.db import shared_engine
from app.matching import find_candidates, rank
from app.tickets.service import get_card
from app.tickets.state import transition

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
TIMEOUT_SECONDS = {"EMERGENCY": 3 * 60, "SAME_DAY": 15 * 60, "FLEXIBLE": 2 * 60 * 60}
REPLY_RE = re.compile(
    r"^\s*(ACCEPT|ACCEPTED|YES|Y|DECLINE|NO|N|接受|接单|同意|拒绝|不接)\s*#?\s*(\d+)?\s*[.!。！]*\s*$",
    re.IGNORECASE,
)
ACCEPT_WORDS = {"ACCEPT", "ACCEPTED", "YES", "Y", "接受", "接单", "同意"}


@dataclass(frozen=True)
class Outgoing:
    phone: str
    body: str


def timeout_seconds(urgency: str) -> float:
    return get_settings().dispatch_timeout_s or TIMEOUT_SECONDS[urgency]


def offer_text(t, seconds: float, lang: str = "en") -> str:
    summary = t.issue_summary if len(t.issue_summary) <= 140 else t.issue_summary[:137] + "..."
    return i18n.t(
        lang,
        "offer",
        n=t.ticket_number,
        cat=i18n.category(lang, t.category),
        when=i18n.when(lang, t.urgency),
        zip=t.location_zip,
        summary=summary,
        mins=i18n.duration(lang, seconds),
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


def notify_customer(conn, t, key: str, **kw) -> list[Outgoing]:
    """Post an update into the customer's conversation (and text it if they use SMS).

    `key` names the text in app.i18n; it is written in the customer's own language.
    """
    row = conn.execute(
        text(
            "SELECT c.id, c.channel, u.phone_e164, u.sms_opted_out, u.language "
            "FROM conversations c JOIN users u ON u.id = c.user_id WHERE c.ticket_id = :t"
        ),
        {"t": t.id},
    ).first()
    if row is None:
        return []
    if "cat" not in kw and key in ("customer_accepted", "customer_assigned"):
        kw["cat"] = i18n.category(row.language, t.category)
    body = i18n.t(row.language, key, n=t.ticket_number, **kw)
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
        return notify_customer(conn, t, "unmatched")
    seconds = timeout_seconds(t.urgency)
    contact = conn.execute(
        text(
            "SELECT phone_e164, language, "
            "COALESCE(last_seen_at > now() - interval '2 minutes', FALSE) "
            "AS active FROM users WHERE id = :h"
        ),
        {"h": nxt.candidate.handyman_id},
    ).one()
    body = offer_text(t, seconds, contact.language)
    # A handyman who has the app open sees the offer there, so we do not text them as well.
    # If they have not answered after a while, remind_unanswered() texts them.
    via_app = bool(contact.active)
    conn.execute(
        text(
            "INSERT INTO dispatch_offers (ticket_id, handyman_id, message, via_app, expires_at) "
            "VALUES (:t, :h, :m, :v, clock_timestamp() + make_interval(secs => :s))"
        ),
        {"t": t.id, "h": nxt.candidate.handyman_id, "m": body, "v": via_app, "s": seconds},
    )
    logger.info(
        "Offered ticket #%s to a handyman (offer %d, %s)",
        t.ticket_number,
        len(tried) + 1,
        "in the app" if via_app else "by SMS",
    )
    return [Outgoing(contact.phone_e164, body)] if contact.phone_e164 and not via_app else []


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
        from app import relay  # local import: relay uses this module's Outgoing

        with shared_engine().begin() as conn:
            return relay.handyman_text(conn, user_id, body)
    accept = m.group(1).upper() in ACCEPT_WORDS
    number = int(m.group(2)) if m.group(2) else None
    with shared_engine().begin() as conn:
        lang = conn.execute(
            text("SELECT language FROM users WHERE id = :u"), {"u": user_id}
        ).scalar()
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
            if number:
                return i18n.t(lang, "job_gone", n=number), []
            return i18n.t(lang, "job_gone_any"), []
        if len(pending) > 1:
            return i18n.t(lang, "several_offers"), []
        offer = pending[0]
        t = _ticket(conn, offer.ticket_id, lock=True)
        cur = conn.execute(
            text(
                "SELECT status, expires_at < clock_timestamp() AS late "
                "FROM dispatch_offers WHERE id = :o FOR UPDATE"
            ),
            {"o": offer.id},
        ).one()
        gone = i18n.t(lang, "job_gone", n=t.ticket_number)
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
            return i18n.t(lang, "passed_on", n=t.ticket_number), _next_offer(conn, t)
        _close(conn, offer.id, "ACCEPTED")
        conn.execute(
            text("UPDATE tickets SET assigned_handyman_id = :h WHERE id = :t"),
            {"h": user_id, "t": t.id},
        )
        transition(conn, t.id, "ASSIGNED", f"handyman:{user_id}")
        name = conn.execute(
            text("SELECT display_name FROM handymen WHERE user_id = :h"), {"h": user_id}
        ).scalar()
        out = notify_customer(conn, t, "customer_accepted", name=name)
        return i18n.t(lang, "assigned_reply", n=t.ticket_number), out


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


def remind_unanswered() -> int:
    """Text handymen whose in-app offer has gone unanswered for a while (once per offer).

    The wait is two minutes, or a third of the offer's time limit if that is shorter.
    """
    with shared_engine().begin() as conn:
        rows = conn.execute(
            text(
                "UPDATE dispatch_offers o SET reminded_at = clock_timestamp() "
                "FROM users u WHERE u.id = o.handyman_id AND o.status = 'SENT' "
                "AND o.via_app AND o.reminded_at IS NULL AND o.expires_at > clock_timestamp() "
                "AND o.sent_at < clock_timestamp() - make_interval(secs => "
                " LEAST(120, EXTRACT(EPOCH FROM (o.expires_at - o.sent_at)) / 3)) "
                "RETURNING u.phone_e164, u.sms_opted_out, u.language, o.message"
            )
        ).all()
    out = [
        Outgoing(r.phone_e164, i18n.t(r.language, "reminder") + r.message)
        for r in rows
        if r.phone_e164 and not r.sms_opted_out
    ]
    deliver(out)
    return len(rows)
