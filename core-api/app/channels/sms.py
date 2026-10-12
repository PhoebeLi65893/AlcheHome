"""SMS channel: Twilio webhook in, Twilio REST API out.

The webhook checks Twilio's signature, records the MessageSid so redeliveries are ignored,
answers Twilio immediately with empty TwiML, and handles the message after the response
(the AI can take longer than Twilio's 15-second webhook timeout). The reply goes out
through Twilio's REST API.
"""

import logging
from xml.sax.saxutils import escape

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import text

from app import i18n, relay
from app.channels import twilio
from app.config import get_settings
from app.conversations import active_conversation, close_active, run_turn
from app.db import shared_engine
from app.dispatch import deliver, handle_handyman_reply
from app.images import ImageRejected
from app.media import save_photo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks/twilio", tags=["sms"])

MAX_PHOTOS = 3
MAX_BODY = 4000
STOP_WORDS = {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT", "REVOKE", "OPTOUT"}
START_WORDS = {"START", "UNSTOP", "YES"}
HELP_WORDS = {"HELP", "INFO"}
NEW_WORDS = {"NEW", "RESET"}
NEW_REPLY = i18n.t("en", "new_request")  # English text, for reference and tests
LANG_WORDS = {"ENGLISH": "en", "EN": "en", "中文": "zh", "ZH": "zh", "CHINESE": "zh"}


def twiml(message: str | None = None) -> Response:
    inner = f"<Message>{escape(message)}</Message>" if message else ""
    return Response(
        f'<?xml version="1.0" encoding="UTF-8"?><Response>{inner}</Response>',
        media_type="application/xml",
    )


def _signed_url(request: Request) -> str:
    """The exact URL Twilio called (behind ngrok or a proxy, use PUBLIC_BASE_URL)."""
    base = get_settings().public_base_url
    if not base:
        return str(request.url)
    query = f"?{request.url.query}" if request.url.query else ""
    return f"{base}{request.url.path}{query}"


def _first_delivery(provider: str, external_id: str) -> bool:
    with shared_engine().begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO webhook_events (provider, external_id) VALUES (:p, :e) "
                "ON CONFLICT DO NOTHING RETURNING external_id"
            ),
            {"p": provider, "e": external_id},
        ).first()
    return row is not None


def sms_user(conn, phone: str):
    """Find the customer with this phone number, or create a guest customer for it."""
    conn.execute(
        text(
            "INSERT INTO users (role, phone_e164, preferred_channel) "
            "VALUES ('CUSTOMER', :p, 'SMS') ON CONFLICT (phone_e164) DO NOTHING"
        ),
        {"p": phone},
    )
    return conn.execute(
        text("SELECT id, role, sms_opted_out, language FROM users WHERE phone_e164 = :p"),
        {"p": phone},
    ).one()


@router.post("/sms")
async def inbound_sms(request: Request, background: BackgroundTasks):
    s = get_settings()
    if not s.twilio_auth_token:
        raise HTTPException(503, "SMS is not configured")
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    signature = request.headers.get("X-Twilio-Signature", "")
    if not twilio.signature_is_valid(s.twilio_auth_token, _signed_url(request), params, signature):
        logger.warning("Rejected SMS webhook with an invalid signature")
        raise HTTPException(403, "Invalid signature")

    sid = params.get("MessageSid") or params.get("SmsSid") or ""
    phone = params.get("From", "")
    if not sid or not phone:
        raise HTTPException(400, "Missing MessageSid or From")
    if not _first_delivery("twilio", sid):
        return twiml()  # Twilio retried a message we already accepted

    body = params.get("Body", "").strip()[:MAX_BODY]
    word = body.upper().rstrip(".!")
    with shared_engine().begin() as conn:
        user = sms_user(conn, phone)
        # Opt-out keywords: Twilio sends the confirmation itself; we only remember the choice.
        if word in STOP_WORDS:
            conn.execute(
                text("UPDATE users SET sms_opted_out = TRUE WHERE id = :u"), {"u": user.id}
            )
            return twiml()
        if word in START_WORDS and user.sms_opted_out:
            conn.execute(
                text("UPDATE users SET sms_opted_out = FALSE WHERE id = :u"), {"u": user.id}
            )
            return twiml()
        if word in HELP_WORDS or user.sms_opted_out:
            return twiml()
        handyman = user.role == "HANDYMAN"
        if word in LANG_WORDS:  # texting ENGLISH or 中文 switches the language of replies
            new_lang = LANG_WORDS[word]
            conn.execute(
                text("UPDATE users SET language = :l WHERE id = :u"), {"l": new_lang, "u": user.id}
            )
            return twiml(i18n.t(new_lang, "lang_set"))
        if word in NEW_WORDS:
            close_active(conn, user.id, "SMS")
            active_conversation(conn, user.id, "SMS")
            return twiml(i18n.t(user.language, "new_request"))

    if handyman:  # job offers: ACCEPT / DECLINE, answered right in the webhook response
        reply, others = handle_handyman_reply(user.id, body)
        background.add_task(deliver, others)
        return twiml(reply)

    with shared_engine().begin() as conn:  # a customer with an assigned job texts the handyman
        relayed = relay.customer_text(conn, user.id, body)
    if relayed is not None:
        background.add_task(deliver, relayed)
        return twiml()

    try:
        num_media = min(int(params.get("NumMedia", "0") or 0), MAX_PHOTOS)
    except ValueError:
        num_media = 0
    media_urls = [params[f"MediaUrl{i}"] for i in range(num_media) if params.get(f"MediaUrl{i}")]
    if not body and not media_urls:
        return twiml()
    background.add_task(handle_sms, user.id, phone, body, media_urls, sid)
    return twiml()


def handle_sms(user_id, phone: str, body: str, media_urls: list[str], sid: str) -> None:
    """Runs after Twilio got its response: photos, AI turn, reply by SMS."""
    try:
        uploads = []
        for url in media_urls:
            try:
                raw = twilio.download_media(url, get_settings().max_upload_bytes)
                uploads.append(save_photo(user_id, raw))
            except (twilio.TwilioError, ImageRejected) as e:
                logger.info("Skipped an MMS attachment: %s", e)
        turn = run_turn(user_id, "SMS", body, uploads, provider_message_id=sid)
        if turn is None:
            return
        reply_sid = twilio.send_sms(phone, turn.bot.body)
        if reply_sid:
            with shared_engine().begin() as conn:
                conn.execute(
                    text("UPDATE messages SET provider_message_id = :p WHERE id = :i"),
                    {"p": reply_sid, "i": turn.bot.id},
                )
    except twilio.TwilioError as e:
        logger.warning("Could not send SMS reply to %s: %s", twilio.mask(phone), e)
    except Exception:
        logger.exception("SMS handling failed for %s", twilio.mask(phone))
        try:
            with shared_engine().connect() as conn:
                lang = conn.execute(
                    text("SELECT language FROM users WHERE id = :u"), {"u": user_id}
                ).scalar()
            twilio.send_sms(phone, i18n.t(lang, "sms_error"))
        except twilio.TwilioError:
            pass
