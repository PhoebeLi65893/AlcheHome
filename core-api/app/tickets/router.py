import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.auth import current_user
from app.db import shared_engine
from app.dispatch import MAX_ATTEMPTS, NotEligible, start_dispatch
from app.matching import find_candidates, rank
from app.tickets.service import CARD_COLUMNS, TicketCard, card_from_row, get_card
from app.tickets.state import InvalidTransition, transition

router = APIRouter(prefix="/tickets", tags=["tickets"])
User = Annotated[dict, Depends(current_user)]


class TicketEvent(BaseModel):
    from_status: str | None
    to_status: str
    actor: str
    created_at: datetime


class TicketDetail(TicketCard):
    created_at: datetime
    offers_sent: int = 0  # how many handymen have been asked so far
    max_offers: int = MAX_ATTEMPTS
    offer_expires_at: datetime | None = None  # when the current offer times out
    handyman_name: str | None = None  # once assigned
    media_ids: list[str]
    events: list[TicketEvent]


@router.get("", response_model=list[TicketCard])
def my_tickets(user: User):
    with shared_engine().connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT {CARD_COLUMNS} FROM tickets t WHERE t.customer_id = :c "
                "ORDER BY t.created_at DESC LIMIT 50"
            ),
            {"c": user["id"]},
        ).all()
    return [card_from_row(r) for r in rows]


@router.get("/{ticket_id}", response_model=TicketDetail)
def ticket_detail(ticket_id: uuid.UUID, user: User):
    with shared_engine().connect() as conn:
        card = get_card(conn, ticket_id, customer_id=user["id"])
        if card is None:
            raise HTTPException(404, "Ticket not found")
        created = conn.execute(
            text("SELECT created_at FROM tickets WHERE id = :t"), {"t": ticket_id}
        ).scalar_one()
        media = conn.execute(
            text("SELECT upload_id FROM ticket_media WHERE ticket_id = :t ORDER BY upload_id"),
            {"t": ticket_id},
        ).scalars()
        events = conn.execute(
            text(
                "SELECT from_status, to_status, actor, created_at FROM ticket_events "
                "WHERE ticket_id = :t ORDER BY created_at, id"
            ),
            {"t": ticket_id},
        ).all()
        progress = conn.execute(
            text(
                "SELECT (SELECT count(*) FROM dispatch_offers WHERE ticket_id = :t) AS sent, "
                "(SELECT min(expires_at) FROM dispatch_offers "
                " WHERE ticket_id = :t AND status = 'SENT') AS expires, "
                "(SELECT h.display_name FROM tickets t JOIN handymen h "
                " ON h.user_id = t.assigned_handyman_id WHERE t.id = :t) AS name"
            ),
            {"t": ticket_id},
        ).one()
    return TicketDetail(
        **card.model_dump(),
        offers_sent=progress.sent,
        offer_expires_at=progress.expires,
        handyman_name=progress.name,
        created_at=created,
        media_ids=[str(m) for m in media],
        events=[TicketEvent(**e._mapping) for e in events],
    )


class HandymanOption(BaseModel):
    handyman_id: str
    display_name: str
    rating_avg: float
    response_rate: float
    recommended: bool  # the top-ranked one


class DispatchIn(BaseModel):
    handyman_id: uuid.UUID | None = None  # none = we choose for you, best ranked first


@router.get("/{ticket_id}/handymen", response_model=list[HandymanOption])
def handyman_options(ticket_id: uuid.UUID, user: User):
    """Handymen who could take this ticket, best match first (customer's own tickets only)."""
    with shared_engine().connect() as conn:
        t = conn.execute(
            text(
                "SELECT category, urgency, location_zip, status FROM tickets "
                "WHERE id = :t AND customer_id = :c"
            ),
            {"t": ticket_id, "c": user["id"]},
        ).first()
        if t is None:
            raise HTTPException(404, "Ticket not found")
        if t.status not in ("OPEN", "UNMATCHED"):
            return []
        ranked = rank(find_candidates(conn, t.category, t.location_zip), t.urgency, t.location_zip)
    return [
        HandymanOption(
            handyman_id=r.candidate.handyman_id,
            display_name=r.candidate.display_name,
            rating_avg=r.candidate.rating_avg,
            response_rate=r.candidate.response_rate,
            recommended=i == 0,
        )
        for i, r in enumerate(ranked)
    ]


@router.post("/{ticket_id}/dispatch", response_model=TicketCard)
def find_handyman(ticket_id: uuid.UUID, body: DispatchIn, user: User):
    """Start looking for a handyman: the customer's pick first, then best ranked in turn."""
    with shared_engine().connect() as conn:
        card = get_card(conn, ticket_id, customer_id=user["id"])
    if card is None:
        raise HTTPException(404, "Ticket not found")
    try:
        started = start_dispatch(ticket_id, body.handyman_id, actor=f"customer:{user['id']}")
    except NotEligible:
        raise HTTPException(400, "That handyman is not available for this request") from None
    if not started:
        raise HTTPException(409, f"We are already working on request #{card.number}")
    with shared_engine().connect() as conn:
        return get_card(conn, ticket_id)


@router.post("/{ticket_id}/cancel", response_model=TicketCard)
def cancel(ticket_id: uuid.UUID, user: User):
    with shared_engine().begin() as conn:
        if get_card(conn, ticket_id, customer_id=user["id"]) is None:
            raise HTTPException(404, "Ticket not found")
        try:
            transition(conn, ticket_id, "CANCELLED", actor=f"customer:{user['id']}")
        except InvalidTransition as e:
            raise HTTPException(409, str(e)) from None
        return get_card(conn, ticket_id)
