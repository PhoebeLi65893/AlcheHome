"""Ops fallback: list tickets nobody accepted and assign a handyman by hand (ADMIN only)."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.auth import current_user
from app.db import shared_engine
from app.dispatch import Outgoing, deliver, notify_customer, start_dispatch
from app.matching import Candidate, rank
from app.tickets.service import LABELS, TicketCard, card_from_row
from app.tickets.state import InvalidTransition, transition


def require_admin(user: Annotated[dict, Depends(current_user)]) -> dict:
    if user["role"] != "ADMIN":
        raise HTTPException(403, "Admins only")
    return user


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
Admin = Annotated[dict, Depends(require_admin)]
LISTABLE = ("UNMATCHED", "MATCHING")


class OpsTicket(TicketCard):
    created_at: str
    offers: int
    waiting_minutes: int


class HandymanChoice(BaseModel):
    handyman_id: str
    display_name: str
    score: float | None  # None when they do not cover the ZIP or are unavailable
    covers_zip: bool
    is_available: bool
    already_offered: str | None  # status of an earlier offer for this ticket, if any
    service_zips: list[str]
    rating_avg: float
    response_rate: float


class AssignIn(BaseModel):
    handyman_id: uuid.UUID


@router.get("/tickets", response_model=list[OpsTicket])
def list_tickets(status: Literal["UNMATCHED", "MATCHING"] = "UNMATCHED"):
    """Tickets needing attention, oldest first."""
    with shared_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT t.id, t.ticket_number, t.category, t.issue_summary, t.urgency, "
                "t.location_zip, t.severity, t.status, t.created_at::text AS created_at, "
                "(SELECT count(*) FROM dispatch_offers o WHERE o.ticket_id = t.id) AS offers, "
                "(EXTRACT(EPOCH FROM now() - t.updated_at) / 60)::int AS waiting_minutes "
                "FROM tickets t WHERE t.status = :s ORDER BY t.updated_at"
            ),
            {"s": status},
        ).all()
    return [
        OpsTicket(
            **card_from_row(r).model_dump(),
            created_at=r.created_at,
            offers=r.offers,
            waiting_minutes=r.waiting_minutes,
        )
        for r in rows
    ]


@router.get("/tickets/{ticket_id}/handymen", response_model=list[HandymanChoice])
def choices(ticket_id: uuid.UUID):
    """Every handyman with the right skill: ranked ones first, then the rest unscored."""
    with shared_engine().connect() as conn:
        t = conn.execute(
            text("SELECT category, urgency, location_zip FROM tickets WHERE id = :t"),
            {"t": ticket_id},
        ).first()
        if t is None:
            raise HTTPException(404, "Ticket not found")
        rows = conn.execute(
            text(
                "SELECT h.user_id, h.display_name, h.service_zips, h.rating_avg, "
                "h.response_rate, h.is_available, h.verified_at IS NOT NULL AS verified, "
                "u.sms_opted_out, "
                "(SELECT status FROM dispatch_offers o WHERE o.ticket_id = :t "
                " AND o.handyman_id = h.user_id) AS offered "
                "FROM handymen h JOIN handymen_skills s ON s.handyman_id = h.user_id "
                "JOIN users u ON u.id = h.user_id WHERE s.category = :c"
            ),
            {"t": ticket_id, "c": t.category},
        ).all()
    by_id = {str(r.user_id): r for r in rows}
    eligible = [
        Candidate(
            str(r.user_id),
            r.display_name,
            list(r.service_zips),
            float(r.rating_avg),
            float(r.response_rate),
        )
        for r in rows
        if t.location_zip in r.service_zips and r.is_available and r.verified
    ]
    ranked = rank(eligible, t.urgency, t.location_zip)
    scores = {r.candidate.handyman_id: r.score for r in ranked}
    order = [r.candidate.handyman_id for r in ranked]
    order += sorted((i for i in by_id if i not in scores), key=lambda i: by_id[i].display_name)
    return [
        HandymanChoice(
            handyman_id=i,
            display_name=by_id[i].display_name,
            score=scores.get(i),
            covers_zip=t.location_zip in by_id[i].service_zips,
            is_available=by_id[i].is_available,
            already_offered=by_id[i].offered,
            service_zips=list(by_id[i].service_zips),
            rating_avg=float(by_id[i].rating_avg),
            response_rate=float(by_id[i].response_rate),
        )
        for i in order
    ]


@router.post("/tickets/{ticket_id}/assign", response_model=TicketCard)
def assign(ticket_id: uuid.UUID, body: AssignIn, admin: Admin):
    """Assign a handyman by hand. Works on UNMATCHED tickets (and MATCHING ones, which cancels
    the pending offer)."""
    actor = f"admin:{admin['id']}"
    out: list[Outgoing] = []
    with shared_engine().begin() as conn:
        t = conn.execute(
            text(
                "SELECT id, ticket_number, customer_id, category, location_zip, status "
                "FROM tickets WHERE id = :t FOR UPDATE"
            ),
            {"t": ticket_id},
        ).first()
        if t is None:
            raise HTTPException(404, "Ticket not found")
        if t.status not in LISTABLE:
            raise HTTPException(
                409, f"Ticket is {t.status}; only UNMATCHED or MATCHING can be assigned"
            )
        h = conn.execute(
            text(
                "SELECT h.display_name, u.phone_e164, u.sms_opted_out FROM handymen h "
                "JOIN users u ON u.id = h.user_id WHERE h.user_id = :h"
            ),
            {"h": body.handyman_id},
        ).first()
        if h is None:
            raise HTTPException(404, "Handyman not found")
        conn.execute(  # an offer still out is withdrawn
            text(
                "UPDATE dispatch_offers SET status = 'EXPIRED', responded_at = clock_timestamp() "
                "WHERE ticket_id = :t AND status = 'SENT' AND handyman_id <> :h"
            ),
            {"t": ticket_id, "h": body.handyman_id},
        )
        conn.execute(  # record the assignment alongside the automatic offers
            text(
                "INSERT INTO dispatch_offers (ticket_id, handyman_id, status, message, "
                "expires_at, responded_at) VALUES (:t, :h, 'ACCEPTED', 'Assigned by ops', "
                "clock_timestamp(), clock_timestamp()) "
                "ON CONFLICT (ticket_id, handyman_id) DO UPDATE SET status = 'ACCEPTED', "
                "responded_at = clock_timestamp()"
            ),
            {"t": ticket_id, "h": body.handyman_id},
        )
        try:
            if t.status == "UNMATCHED":
                transition(conn, ticket_id, "MATCHING", actor)
            transition(conn, ticket_id, "ASSIGNED", actor)
        except InvalidTransition as e:
            raise HTTPException(409, str(e)) from None
        conn.execute(
            text("UPDATE tickets SET assigned_handyman_id = :h WHERE id = :t"),
            {"h": body.handyman_id, "t": ticket_id},
        )
        out += notify_customer(
            conn,
            t,
            f"Good news: {h.display_name} has been assigned to repair request "
            f"#{t.ticket_number} ({LABELS[t.category]}). They'll be in touch about the visit.",
        )
        if h.phone_e164 and not h.sms_opted_out:
            out.append(
                Outgoing(
                    h.phone_e164,
                    f"Alche Home: you've been assigned job #{t.ticket_number} "
                    f"({LABELS[t.category]}, ZIP {t.location_zip}). We'll send the details next.",
                )
            )
        row = conn.execute(
            text(
                "SELECT t.id, t.ticket_number, t.category, t.issue_summary, t.urgency, "
                "t.location_zip, t.severity, t.status FROM tickets t WHERE t.id = :t"
            ),
            {"t": ticket_id},
        ).one()
    deliver(out)
    return card_from_row(row)


@router.post("/tickets/{ticket_id}/retry", response_model=dict)
def retry(ticket_id: uuid.UUID):
    """Run automatic dispatch again for an UNMATCHED ticket."""
    return {"started": start_dispatch(ticket_id)}
