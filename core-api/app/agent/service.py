import logging
from dataclasses import dataclass

import httpx

from app import bot
from app.agent import gemini
from app.agent.context import build_contents
from app.agent.safety import EMERGENCY_REPLIES, check_emergency
from app.config import get_settings
from app.tickets.schema import TOOL_DECLARATION, TOOL_NAME

logger = logging.getLogger(__name__)

FALLBACK = (
    "Sorry, I'm having trouble right now. If this is an emergency (gas smell, fire, sparking "
    "wires), leave the area and call 911. Otherwise please try again in a moment."
)
TICKET_EXISTS_NOTE = (
    "A repair request (#{number}) was already created in this conversation, so you cannot "
    "create another one here. Answer follow-up questions about it. If the customer describes a "
    "different problem, tell them to tap 'New request'."
)
DEV_COMMAND = "/ticket"
SMS_NOTE = (
    "The customer is texting by SMS: keep every reply under 300 characters, plain text only. "
    "When you ask whether to create a repair request, ask them to reply OK (words like YES, "
    "STOP and HELP are reserved by the SMS provider)."
)


@dataclass(frozen=True)
class Reply:
    text: str
    emergency: bool = False
    source: str = "gemini"  # safety | gemini | echo | fallback | dev
    ticket_request: dict | None = None  # arguments for create_repair_ticket, still unchecked


def _dev_ticket(latest_text: str) -> dict:
    """`/ticket CATEGORY URGENCY ZIP summary...` (local development without Gemini only)."""
    parts = latest_text.split(maxsplit=4)
    keys = ["category", "urgency", "location_zip", "issue_summary"]
    return dict(zip(keys, parts[1:], strict=False))


def respond(
    history,
    latest_text: str,
    images=(),
    existing_ticket: int | None = None,
    channel: str = "WEB",
) -> Reply:
    """Produce the bot reply.

    `history` is the stored messages, oldest first, newest included. `images` are the photos
    sent with the newest message as (mime_type, bytes) pairs. `existing_ticket` is the number of
    the ticket this conversation already has, if any; then no new ticket can be requested.
    """
    category = check_emergency(latest_text)
    if category:
        return Reply(EMERGENCY_REPLIES[category], emergency=True, source="safety")
    s = get_settings()
    if not s.gemini_api_key:
        if s.app_env == "local" and latest_text.lower().startswith(DEV_COMMAND):
            return Reply("", source="dev", ticket_request=_dev_ticket(latest_text))
        return Reply(bot.reply_to(latest_text, photos=len(images)), source="echo")
    tools = None if existing_ticket else [TOOL_DECLARATION]
    notes = []
    if existing_ticket:
        notes.append(TICKET_EXISTS_NOTE.format(number=existing_ticket))
    if channel == "SMS":
        notes.append(SMS_NOTE)
    note = " ".join(notes)
    try:
        result = gemini.generate(build_contents(history, images), tools=tools, note=note)
    except gemini.GeminiError as e:
        logger.warning("Gemini call failed: %s", e)
        return Reply(FALLBACK, source="fallback")
    except httpx.HTTPError as e:
        logger.warning("Gemini call failed: %s", type(e).__name__)
        return Reply(FALLBACK, source="fallback")
    call = result.function_call
    if call and call.name == TOOL_NAME:
        return Reply(result.text, ticket_request=call.args)
    if call:
        logger.warning("Gemini called an unknown function: %s", call.name[:50])
    return Reply(result.text or FALLBACK, source="gemini" if result.text else "fallback")
