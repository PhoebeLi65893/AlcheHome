import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.auth import current_user
from app.db import shared_engine
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
    return TicketDetail(
        **card.model_dump(),
        created_at=created,
        media_ids=[str(m) for m in media],
        events=[TicketEvent(**e._mapping) for e in events],
    )


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
