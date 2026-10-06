import logging
from dataclasses import dataclass

import httpx

from app import bot
from app.agent import gemini
from app.agent.context import build_contents
from app.agent.safety import EMERGENCY_REPLIES, check_emergency
from app.config import get_settings

logger = logging.getLogger(__name__)

FALLBACK = (
    "Sorry, I'm having trouble right now. If this is an emergency (gas smell, fire, sparking "
    "wires), leave the area and call 911. Otherwise please try again in a moment."
)


@dataclass(frozen=True)
class Reply:
    text: str
    emergency: bool = False
    source: str = "gemini"  # safety | gemini | echo | fallback


def respond(history, latest_text: str) -> Reply:
    """Produce the bot reply. `history` is the stored messages, oldest first, newest included."""
    category = check_emergency(latest_text)
    if category:
        return Reply(EMERGENCY_REPLIES[category], emergency=True, source="safety")
    if not get_settings().gemini_api_key:
        return Reply(bot.reply_to(latest_text), source="echo")
    try:
        return Reply(gemini.generate(build_contents(history)))
    except gemini.GeminiError as e:
        logger.warning("Gemini call failed: %s", e)
    except httpx.HTTPError as e:
        logger.warning("Gemini call failed: %s", type(e).__name__)
    return Reply(FALLBACK, source="fallback")
