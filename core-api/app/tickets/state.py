"""Ticket state machine (see the System Architecture Document, section 3.3)."""

from sqlalchemy import text

TERMINAL = {"RATED", "CANCELLED"}

TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"OPEN", "CANCELLED"},
    "OPEN": {"MATCHING", "CANCELLED"},
    "MATCHING": {"ASSIGNED", "UNMATCHED", "CANCELLED"},
    "UNMATCHED": {"MATCHING", "CANCELLED"},
    "ASSIGNED": {"IN_PROGRESS", "CANCELLED"},
    "IN_PROGRESS": {"COMPLETED", "CANCELLED"},
    "COMPLETED": {"RATED"},
    "RATED": set(),
    "CANCELLED": set(),
}


class InvalidTransition(Exception):
    def __init__(self, current: str, target: str):
        super().__init__(f"Cannot move a ticket from {current} to {target}")
        self.current, self.target = current, target


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, set())


def record_event(conn, ticket_id, from_status, to_status, actor: str) -> None:
    conn.execute(
        text(
            "INSERT INTO ticket_events (ticket_id, from_status, to_status, actor) "
            "VALUES (:t, :f, :to, :a)"
        ),
        {"t": ticket_id, "f": from_status, "to": to_status, "a": actor},
    )


def transition(conn, ticket_id, target: str, actor: str) -> str:
    """Move a ticket to `target` (locking its row) and record the event. Returns the old status."""
    current = conn.execute(
        text("SELECT status FROM tickets WHERE id = :t FOR UPDATE"), {"t": ticket_id}
    ).scalar_one()
    if not can_transition(current, target):
        raise InvalidTransition(current, target)
    conn.execute(
        text("UPDATE tickets SET status = :s, updated_at = now() WHERE id = :t"),
        {"s": target, "t": ticket_id},
    )
    record_event(conn, ticket_id, current, target, actor)
    return current
