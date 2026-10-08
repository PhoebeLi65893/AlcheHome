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
    "There is no Create request button here. Once you know what is wrong, roughly where, how "
    "urgent it is and their 5-digit ZIP code, give a one-sentence summary and ask whether they "
    "would like you to create a repair request. Ask them to reply OK (words like YES, STOP and "
    "HELP are reserved by the SMS provider). Only after they agree, call create_repair_ticket."
)
NO_AI_REQUEST_REPLY = (
    "Creating a request from chat needs the AI assistant, which is not configured. "
    "For local testing type /ticket CATEGORY URGENCY ZIP description, for example: "
    "/ticket plumbing same_day 92101 Kitchen sink leaking under the cabinet"
)
WEB_CHAT_NOTE = (
    "The customer is chatting in the app. Focus on understanding the problem and giving "
    "technical suggestions. Do not ask for their ZIP code or how urgent it is, and do not offer "
    "to create a repair request: the app has a Create request button they press when ready. "
    "Do not call create_repair_ticket."
)
WANT_TICKET_NOTE = (
    "The customer pressed the Create request button. Use everything said so far. If you know "
    "the type of repair, can write a short description of the problem, know how urgent it is "
    "and have their 5-digit ZIP code, call create_repair_ticket now without asking for "
    "confirmation. Otherwise do not call it: ask only for the missing details (at most two "
    "short questions, plain text) and say you will create the request as soon as you have them."
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
    want_ticket: bool = False,
) -> Reply:
    """Produce the bot reply.

    `history` is the stored messages, oldest first, newest included. `images` are the photos
    sent with the newest message as (mime_type, bytes) pairs. `existing_ticket` is the number of
    the ticket this conversation already has, if any; then no new ticket can be requested.
    `want_ticket` means the customer pressed Create request (web); only then, or on SMS, may the
    model create a ticket.
    """
    category = check_emergency(latest_text)
    if category:
        return Reply(EMERGENCY_REPLIES[category], emergency=True, source="safety")
    s = get_settings()
    if not s.gemini_api_key:
        if s.app_env == "local" and latest_text.lower().startswith(DEV_COMMAND):
            return Reply("", source="dev", ticket_request=_dev_ticket(latest_text))
        if want_ticket:
            return Reply(NO_AI_REQUEST_REPLY, source="echo")
        return Reply(bot.reply_to(latest_text, photos=len(images)), source="echo")
    may_create = not existing_ticket and (channel == "SMS" or want_ticket)
    tools = [TOOL_DECLARATION] if may_create else None
    notes = []
    if existing_ticket:
        notes.append(TICKET_EXISTS_NOTE.format(number=existing_ticket))
    if channel == "SMS":
        notes.append(SMS_NOTE)
    elif want_ticket and not existing_ticket:
        notes.append(WANT_TICKET_NOTE)
    elif not existing_ticket:
        notes.append(WEB_CHAT_NOTE)
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
    if call and call.name == TOOL_NAME and may_create:
        return Reply(result.text, ticket_request=call.args)
    if call:
        logger.warning("Gemini called an unknown function: %s", call.name[:50])
    return Reply(result.text or FALLBACK, source="gemini" if result.text else "fallback")
