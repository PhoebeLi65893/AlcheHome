"""Minimal Twilio client: request signature checks, sending SMS, downloading MMS photos."""

import base64
import hashlib
import hmac
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
API = "https://api.twilio.com/2010-04-01"
MAX_SMS_CHARS = 1600  # Twilio's limit for one (multi-part) message


class TwilioError(Exception):
    pass


def mask(phone: str) -> str:
    """+16195551234 -> +1******1234, for logs."""
    return phone[:2] + "*" * max(len(phone) - 6, 0) + phone[-4:] if len(phone) > 6 else "***"


def compute_signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    """Twilio's X-Twilio-Signature: HMAC-SHA1 of the URL plus sorted POST params, base64."""
    payload = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def signature_is_valid(auth_token: str, url: str, params: dict[str, str], signature: str) -> bool:
    if not auth_token or not signature:
        return False
    return hmac.compare_digest(compute_signature(auth_token, url, params), signature)


def is_configured_for_sending() -> bool:
    s = get_settings()
    return bool(
        s.twilio_account_sid
        and s.twilio_auth_token
        and (s.twilio_from_number or s.twilio_messaging_service_sid)
    )


def send_sms(to: str, body: str) -> str | None:
    """Send an SMS. Returns Twilio's message SID, or None when sending is not configured."""
    s = get_settings()
    if not is_configured_for_sending():
        logger.info("SMS not sent to %s: Twilio sending is not configured", mask(to))
        return None
    data = {"To": to, "Body": body[:MAX_SMS_CHARS]}
    if s.twilio_messaging_service_sid:
        data["MessagingServiceSid"] = s.twilio_messaging_service_sid
    else:
        data["From"] = s.twilio_from_number
    try:
        r = httpx.post(
            f"{API}/Accounts/{s.twilio_account_sid}/Messages.json",
            data=data,
            auth=(s.twilio_account_sid, s.twilio_auth_token),
            timeout=15,
        )
    except httpx.HTTPError as e:
        raise TwilioError(f"network error: {type(e).__name__}") from None
    if r.status_code >= 400:
        try:
            info = r.json()
            detail = f"{info.get('code')}: {info.get('message')}"
        except ValueError:
            detail = r.text[:200]
        raise TwilioError(f"HTTP {r.status_code} ({detail})")
    return r.json().get("sid")


def download_media(url: str, limit: int) -> bytes:
    """Fetch an MMS attachment from Twilio (with account credentials), up to `limit` bytes."""
    s = get_settings()
    if not url.startswith("https://api.twilio.com/"):
        raise TwilioError("unexpected media host")  # never fetch arbitrary URLs from a webhook
    auth = (s.twilio_account_sid, s.twilio_auth_token) if s.twilio_account_sid else None
    with httpx.stream("GET", url, auth=auth, follow_redirects=True, timeout=20) as r:
        if r.status_code >= 400:
            raise TwilioError(f"media HTTP {r.status_code}")
        data = bytearray()
        for chunk in r.iter_bytes():
            data.extend(chunk)
            if len(data) > limit:
                raise TwilioError("media too large")
    return bytes(data)
