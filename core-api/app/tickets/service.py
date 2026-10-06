import logging
from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy import text

from app.tickets.schema import TicketDraft, validate_draft
from app.tickets.state import record_event, transition

logger = logging.getLogger(__name__)

LABELS = {
    "PLUMBING": "Plumbing",
    "ELECTRICAL": "Electrical",
    "HVAC": "Heating / cooling",
    "CARPENTRY": "Carpentry",
    "APPLIANCE": "Appliance",
    "GENERAL": "General repair",
    "EMERGENCY": "Emergency",
    "SAME_DAY": "Today",
    "FLEXIBLE": "Flexible",
}


class TicketCard(BaseModel):
    id: str
    number: int
    category: str
    issue_summary: str
    urgency: str
    location_zip: str
    severity: str | None
    status: str


CARD_COLUMNS = (
    "t.id, t.ticket_number, t.category, t.issue_summary, t.urgency, t.location_zip, "
    "t.severity, t.status"
)


def card_from_row(row) -> TicketCard:
    return TicketCard(
        id=str(row.id),
        number=row.ticket_number,
        category=row.category,
        issue_summary=row.issue_summary,
        urgency=row.urgency,
        location_zip=row.location_zip,
        severity=row.severity,
        status=row.status,
    )


def get_card(conn, ticket_id, customer_id=None) -> TicketCard | None:
    sql = f"SELECT {CARD_COLUMNS} FROM tickets t WHERE t.id = :t"
    params = {"t": ticket_id}
    if customer_id is not None:
        sql += " AND t.customer_id = :c"
        params["c"] = customer_id
    row = conn.execute(text(sql), params).first()
    return card_from_row(row) if row else None


@dataclass(frozen=True)
class ToolOutcome:
    message: str
    ticket: TicketCard | None = None


def _confirmation(card: TicketCard) -> str:
    when = {
        "EMERGENCY": "as an emergency",
        "SAME_DAY": "for today",
        "FLEXIBLE": "with flexible timing",
    }[card.urgency]
    return (
        f"I've created repair request #{card.number} ({LABELS[card.category]}, {when}, "
        f"ZIP {card.location_zip}). Next we'll look for an available handyman near you, and "
        "you'll be able to follow the status here."
    )


def create_from_tool(conn, customer_id, conversation_id, args: dict, actor: str) -> ToolOutcome:
    """Run the create_repair_ticket tool: validate, create DRAFT, move to OPEN, link photos."""
    existing = conn.execute(
        text(
            "SELECT ticket_id FROM conversations WHERE id = :c AND ticket_id IS NOT NULL "
            "FOR UPDATE"
        ),
        {"c": conversation_id},
    ).scalar()
    if existing:
        card = get_card(conn, existing)
        return ToolOutcome(
            f"This conversation already has repair request #{card.number}. To report a "
            "different problem, start a new request.",
            card,
        )
    draft, problems = validate_draft(args)
    if draft is None:
        # Log field names only: the arguments can contain the customer's own words.
        logger.info("create_repair_ticket rejected; problems with: %s", ", ".join(problems))
        return ToolOutcome(
            "Before I can create the request I still need " + " and ".join(problems) + "."
        )
    card = _create(conn, customer_id, conversation_id, draft, actor)
    return ToolOutcome(_confirmation(card), card)


def _create(conn, customer_id, conversation_id, draft: TicketDraft, actor: str) -> TicketCard:
    ticket_id = conn.execute(
        text(
            "INSERT INTO tickets (customer_id, category, issue_summary, urgency, location_zip, "
            "severity, status) VALUES (:c, :cat, :s, :u, :z, :sev, 'DRAFT') RETURNING id"
        ),
        {
            "c": customer_id,
            "cat": draft.category.value,
            "s": draft.issue_summary,
            "u": draft.urgency.value,
            "z": draft.location_zip,
            "sev": draft.severity.value if draft.severity else None,
        },
    ).scalar_one()
    record_event(conn, ticket_id, None, "DRAFT", actor)
    transition(conn, ticket_id, "OPEN", actor)
    conn.execute(
        text("UPDATE conversations SET ticket_id = :t WHERE id = :c"),
        {"t": ticket_id, "c": conversation_id},
    )
    # Attach every photo the customer sent in this conversation.
    conn.execute(
        text(
            "INSERT INTO ticket_media (ticket_id, upload_id) "
            "SELECT DISTINCT :t, u.id FROM messages m "
            "CROSS JOIN LATERAL jsonb_array_elements_text(m.media_refs) AS ref(id) "
            "JOIN uploads u ON u.id = ref.id::uuid AND u.user_id = :c "
            "WHERE m.conversation_id = :conv AND m.sender = 'USER' "
            "ON CONFLICT DO NOTHING"
        ),
        {"t": ticket_id, "c": customer_id, "conv": conversation_id},
    )
    return get_card(conn, ticket_id)
