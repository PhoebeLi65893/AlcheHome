"""Pretend to be Twilio: send a signed SMS webhook to the local API and print the bot's reply.

Usage (inside the core-api container):
    python -m scripts.sim_sms "+16195550199" "my kitchen sink is leaking"

Needs TWILIO_AUTH_TOKEN (any value works locally, it just has to match the API's) and
DATABASE_URL (to read the reply back). The reply is also what a real phone would receive.
"""

import os
import sys
import time
import uuid

import httpx
from sqlalchemy import text

from app.channels.twilio import compute_signature
from app.db import get_engine


def latest_bot_reply(phone: str, after_sid: str) -> str | None:
    with get_engine().connect() as conn:
        return conn.execute(
            text(
                "SELECT b.body FROM messages u "
                "JOIN messages b ON b.conversation_id = u.conversation_id "
                "AND b.sender = 'BOT' AND b.created_at > u.created_at "
                "WHERE u.provider_message_id = :sid ORDER BY b.created_at LIMIT 1"
            ),
            {"sid": after_sid},
        ).scalar()


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    phone, body = sys.argv[1], " ".join(sys.argv[2:])
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    if not token:
        sys.exit("Set TWILIO_AUTH_TOKEN (the same value the API uses).")
    api = os.environ.get("SIM_API_URL", "http://localhost:8000")
    path = "/webhooks/twilio/sms"
    signed_url = (os.environ.get("PUBLIC_BASE_URL") or api).rstrip("/") + path
    sid = "SMsim" + uuid.uuid4().hex[:28]
    params = {
        "MessageSid": sid,
        "From": phone,
        "To": os.environ.get("TWILIO_FROM_NUMBER", "+15550000000"),
        "Body": body,
        "NumMedia": "0",
    }
    headers = {"X-Twilio-Signature": compute_signature(token, signed_url, params)}
    r = httpx.post(api + path, data=params, headers=headers, timeout=60)
    print(f"Webhook answered HTTP {r.status_code}: {r.text}")
    if r.status_code != 200:
        return
    for _ in range(30):
        reply = latest_bot_reply(phone, sid)
        if reply:
            print(f"\nBot reply by SMS:\n{reply}")
            return
        time.sleep(1)
    print("\nNo bot reply stored (keywords like STOP, HELP and NEW get no AI reply).")


if __name__ == "__main__":
    main()
