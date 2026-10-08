"""Channel-independent conversation core, shared by the web chat and SMS.

A "turn" is: store the customer's message, ask the agent, run the ticket tool if requested,
store the bot reply. Channels (web, SMS, later WhatsApp) only translate in and out of this.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import text

from app.agent import service as agent
from app.agent.context import MAX_TURNS
from app.config import get_settings
from app.db import shared_engine
from app.storage import get_storage
from app.tickets.service import CARD_COLUMNS, TicketCard, card_from_row, create_from_tool

logger = logging.getLogger(__name__)

CHANNELS = {"WEB", "SMS", "WHATSAPP"}


class MessageOut(BaseModel):
    id: str
    sender: str
    body: str
    created_at: datetime
    flag: str | None = None
    media_ids: list[str] = []
    ticket: TicketCard | None = None


@dataclass(frozen=True)
class Turn:
    conversation_id: str
    mine: MessageOut
    bot: MessageOut


def active_conversation(conn, user_id, channel: str = "WEB") -> str:
    """Get the user's single ACTIVE conversation on this channel, creating it if needed."""
    assert channel in CHANNELS
    conn.execute(
        text(
            "INSERT INTO conversations (user_id, channel) VALUES (:u, :ch) "
            "ON CONFLICT (user_id, channel) WHERE status = 'ACTIVE' DO NOTHING"
        ),
        {"u": user_id, "ch": channel},
    )
    return str(
        conn.execute(
            text(
                "SELECT id FROM conversations "
                "WHERE user_id = :u AND channel = :ch AND status = 'ACTIVE'"
            ),
            {"u": user_id, "ch": channel},
        ).scalar_one()
    )


def close_active(conn, user_id, channel: str = "WEB") -> None:
    conn.execute(
        text(
            "UPDATE conversations SET status = 'CLOSED' "
            "WHERE user_id = :u AND channel = :ch AND status = 'ACTIVE'"
        ),
        {"u": user_id, "ch": channel},
    )


def _message(row, ticket: TicketCard | None = None) -> MessageOut:
    return MessageOut(
        id=str(row.id),
        sender=row.sender,
        body=row.body,
        created_at=row.created_at,
        flag=row.flag,
        media_ids=list(row.media_refs or []),
        ticket=ticket,
    )


def store_message(
    conn,
    conversation_id: str,
    sender: str,
    body: str,
    flag: str | None = None,
    media=(),
    ticket: TicketCard | None = None,
    provider_message_id: str | None = None,
) -> MessageOut | None:
    """Insert a message. Returns None if `provider_message_id` was already stored (a retry)."""
    # clock_timestamp() (not now()) so the user message and bot reply get different
    # timestamps and keep their order.
    row = conn.execute(
        text(
            "INSERT INTO messages (conversation_id, sender, body, flag, media_refs, ticket_id, "
            "provider_message_id, created_at) "
            "VALUES (:c, :s, :b, :f, CAST(:m AS jsonb), :t, :p, clock_timestamp()) "
            "ON CONFLICT (provider_message_id) DO NOTHING "
            "RETURNING id, sender, body, flag, media_refs, created_at"
        ),
        {
            "c": conversation_id,
            "s": sender,
            "b": body,
            "f": flag,
            "m": json.dumps([str(m) for m in media]),
            "t": ticket.id if ticket else None,
            "p": provider_message_id,
        },
    ).first()
    return _message(row, ticket) if row else None


def recent_messages(conn, conversation_id: str, limit: int) -> list[MessageOut]:
    """The newest `limit` messages, oldest first, each with its ticket card (current status)."""
    rows = conn.execute(
        text(
            f"SELECT m.*, {CARD_COLUMNS} FROM ("
            "  SELECT id AS msg_id, sender, body, flag, media_refs, ticket_id, created_at "
            "  FROM messages WHERE conversation_id = :c ORDER BY created_at DESC LIMIT :l"
            ") m LEFT JOIN tickets t ON t.id = m.ticket_id ORDER BY m.created_at"
        ),
        {"c": conversation_id, "l": limit},
    ).all()
    return [
        MessageOut(
            id=str(r.msg_id),
            sender=r.sender,
            body=r.body,
            created_at=r.created_at,
            flag=r.flag,
            media_ids=list(r.media_refs or []),
            ticket=card_from_row(r) if r.ticket_id else None,
        )
        for r in rows
    ]


def conversation_ticket(conn, conversation_id: str) -> int | None:
    return conn.execute(
        text(
            "SELECT t.ticket_number FROM conversations c JOIN tickets t ON t.id = c.ticket_id "
            "WHERE c.id = :c"
        ),
        {"c": conversation_id},
    ).scalar()


def run_turn(
    user_id,
    channel: str,
    body: str,
    uploads=(),
    provider_message_id: str | None = None,
    want_ticket: bool = False,
) -> Turn | None:
    """Handle one customer message end to end. `uploads` must already belong to the user.

    `want_ticket` is the Create request button: from then on (until a ticket exists) the
    assistant asks for any missing details and creates the ticket as soon as it has them.

    Returns None when `provider_message_id` was seen before (a duplicate delivery).
    """
    # Step 1: save the customer's message and read the context (short transaction).
    with shared_engine().begin() as conn:
        cid = active_conversation(conn, user_id, channel)
        if want_ticket:
            conn.execute(
                text("UPDATE conversations SET ticket_requested = TRUE WHERE id = :c"), {"c": cid}
            )
        requested = conn.execute(
            text("SELECT ticket_requested FROM conversations WHERE id = :c"), {"c": cid}
        ).scalar_one()
        mine = store_message(
            conn,
            cid,
            "USER",
            body,
            media=[u.id for u in uploads],
            provider_message_id=provider_message_id,
        )
        if mine is None:
            return None
        context = recent_messages(conn, cid, MAX_TURNS)
        existing_ticket = conversation_ticket(conn, cid)
    # Step 2: load the photo bytes and ask the agent. This can take seconds, so no
    # database transaction is held open.
    storage = get_storage()
    images = []
    for u in uploads:
        try:
            images.append((u.mime_type, storage.load(u.storage_key)))
        except OSError:
            logger.warning("Upload %s missing from storage; sending text only", u.id)
    if want_ticket and existing_ticket:  # button pressed again: just show the existing request
        reply = agent.Reply("", source="system", ticket_request={})
    else:
        reply = agent.respond(
            context,
            body,
            images,
            existing_ticket=existing_ticket,
            channel=channel,
            want_ticket=requested,
        )
    # Step 3: run the ticket tool if the agent asked for it, then save the reply.
    with shared_engine().begin() as conn:
        text_out, ticket = reply.text, None
        if reply.ticket_request is not None:
            outcome = create_from_tool(
                conn, user_id, cid, reply.ticket_request, actor=f"agent:{reply.source}"
            )
            ticket = outcome.ticket
            text_out = f"{reply.text}\n\n{outcome.message}" if reply.text else outcome.message
        bot = store_message(
            conn,
            cid,
            "BOT",
            text_out,
            flag="EMERGENCY" if reply.emergency else None,
            ticket=ticket,
        )
    if ticket is not None and ticket.status == "OPEN" and get_settings().dispatch_auto:
        from app.dispatch import start_dispatch  # local import: dispatch imports this module

        start_dispatch(ticket.id)
    return Turn(conversation_id=cid, mine=mine, bot=bot)
