import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.agent import gemini
from app.channels import sms, twilio
from app.channels.twilio import compute_signature, mask, signature_is_valid
from app.db import get_engine
from app.main import app
from app.tickets.schema import TOOL_NAME
from tests.helpers import make_image

TOKEN = "test-auth-token"
URL = "http://testserver/webhooks/twilio/sms"


# ---------- pure helpers (no database) ----------
def test_signature_matches_twilios_documented_example():
    # Twilio's documented example (also checked against the official twilio SDK validator).
    url = "https://mycompany.com/myapp.php?foo=1&bar=2"
    params = {
        "CallSid": "CA1234567890ABCDE",
        "Caller": "+12349013030",
        "Digits": "1234",
        "From": "+12349013030",
        "To": "+18005551212",
    }
    assert compute_signature("12345", url, params) == "0/KCTR6DLpKmkAf8muzZqo1nDgQ="


def test_signature_check_rejects_tampering():
    params = {"Body": "hi", "From": "+16195550100"}
    good = compute_signature(TOKEN, URL, params)
    assert signature_is_valid(TOKEN, URL, params, good)
    assert not signature_is_valid(TOKEN, URL, {**params, "Body": "changed"}, good)
    assert not signature_is_valid(TOKEN, URL + "x", params, good)
    assert not signature_is_valid("other-token", URL, params, good)
    assert not signature_is_valid(TOKEN, URL, params, "")


def test_phone_numbers_are_masked_in_logs():
    assert mask("+16195551234") == "+1******1234"


def test_send_sms_without_credentials_is_a_logged_no_op(monkeypatch):
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    assert twilio.send_sms("+16195550100", "hello") is None


def test_media_download_refuses_non_twilio_hosts():
    with pytest.raises(twilio.TwilioError, match="unexpected media host"):
        twilio.download_media("https://evil.example.com/a.jpg", 1000)


# ---------- webhook (needs the database) ----------
db = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set (needs migrated Postgres)"
)
client = TestClient(app)


@pytest.fixture
def outbox(monkeypatch):
    """Twilio configured with a fake sender; collects (to, body) of every SMS sent."""
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", TOKEN)
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    sent = []

    def fake_send(to, body):
        sent.append((to, body))
        return "SM" + uuid.uuid4().hex[:32]

    monkeypatch.setattr(twilio, "send_sms", fake_send)
    return sent


def new_phone() -> str:
    return "+1619" + str(uuid.uuid4().int)[:7]


def post_sms(phone, body, sid=None, extra=None, signature=None, url=URL):
    params = {"MessageSid": sid or "SM" + uuid.uuid4().hex[:32], "From": phone, "Body": body}
    params.update(extra or {})
    sig = signature if signature is not None else compute_signature(TOKEN, url, params)
    return client.post("/webhooks/twilio/sms", data=params, headers={"X-Twilio-Signature": sig})


def sms_messages(phone):
    with get_engine().connect() as c:
        return c.execute(
            text(
                "SELECT m.sender, m.body, m.provider_message_id FROM messages m "
                "JOIN conversations cv ON cv.id = m.conversation_id "
                "JOIN users u ON u.id = cv.user_id "
                "WHERE u.phone_e164 = :p AND cv.channel = 'SMS' ORDER BY m.created_at"
            ),
            {"p": phone},
        ).all()


@db
def test_valid_sms_gets_ai_turn_and_reply_by_sms(outbox):
    phone = new_phone()
    r = post_sms(phone, "my sink is leaking")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    assert "<Response></Response>" in r.text  # empty TwiML: the reply goes via the REST API
    assert outbox == [(phone, "Echo: my sink is leaking")]
    rows = sms_messages(phone)
    assert [(m.sender, m.body) for m in rows] == [
        ("USER", "my sink is leaking"),
        ("BOT", "Echo: my sink is leaking"),
    ]
    assert rows[1].provider_message_id.startswith("SM")  # Twilio's id of our reply


@db
def test_new_number_becomes_a_guest_customer(outbox):
    phone = new_phone()
    post_sms(phone, "hello")
    with get_engine().connect() as c:
        user = c.execute(
            text("SELECT role, email, preferred_channel FROM users WHERE phone_e164 = :p"),
            {"p": phone},
        ).one()
    assert (user.role, user.email, user.preferred_channel) == ("CUSTOMER", None, "SMS")


@db
def test_bad_or_missing_signature_rejected_and_nothing_stored(outbox):
    phone = new_phone()
    assert post_sms(phone, "hi", signature="bogus").status_code == 403
    assert post_sms(phone, "hi", signature="").status_code == 403
    assert outbox == [] and sms_messages(phone) == []


@db
def test_public_base_url_is_used_for_the_signature(outbox, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://abc.ngrok-free.app/")
    phone = new_phone()
    public = "https://abc.ngrok-free.app/webhooks/twilio/sms"
    assert post_sms(phone, "hi", url=public).status_code == 200
    assert post_sms(phone, "hi", url=URL).status_code == 403


@db
def test_webhook_disabled_without_auth_token(monkeypatch):
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    assert post_sms(new_phone(), "hi", signature="x").status_code == 503


@db
def test_redelivered_message_is_processed_once(outbox):
    phone, sid = new_phone(), "SM" + uuid.uuid4().hex[:32]
    assert post_sms(phone, "hello", sid=sid).status_code == 200
    assert post_sms(phone, "hello", sid=sid).status_code == 200
    assert len(outbox) == 1
    assert len(sms_messages(phone)) == 2  # one USER + one BOT


@db
def test_stop_start_help_and_new_keywords(outbox):
    phone = new_phone()
    assert post_sms(phone, "STOP").status_code == 200
    post_sms(phone, "are you there?")
    assert outbox == [] and sms_messages(phone) == []  # opted out: nothing processed or sent
    post_sms(phone, "start")
    post_sms(phone, "HELP")
    assert outbox == []  # Twilio answers these keywords itself
    post_sms(phone, "back again")
    assert outbox == [(phone, "Echo: back again")]
    r = post_sms(phone, "new")
    assert sms.NEW_REPLY in r.text  # answered directly in TwiML
    with get_engine().connect() as c:
        statuses = (
            c.execute(
                text(
                    "SELECT cv.status FROM conversations cv JOIN users u ON u.id = cv.user_id "
                    "WHERE u.phone_e164 = :p ORDER BY cv.started_at"
                ),
                {"p": phone},
            )
            .scalars()
            .all()
        )
    assert statuses == ["CLOSED", "ACTIVE"]


@db
def test_yes_is_a_normal_message_when_not_opted_out(outbox):
    phone = new_phone()
    post_sms(phone, "yes")
    assert outbox == [(phone, "Echo: yes")]


@db
def test_sms_uses_gemini_with_sms_note_and_can_create_ticket(outbox, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    calls = []
    results = [
        gemini.GeminiResult("Where is the leak, and what is your ZIP?"),
        gemini.GeminiResult(
            "",
            gemini.FunctionCall(
                TOOL_NAME,
                {
                    "category": "PLUMBING",
                    "issue_summary": "Kitchen sink leaking under the cabinet",
                    "urgency": "SAME_DAY",
                    "location_zip": "92101",
                },
            ),
        ),
    ]

    def fake(contents, tools=None, note=""):
        calls.append(note)
        return results[len(calls) - 1]

    monkeypatch.setattr(gemini, "generate", fake)
    phone = new_phone()
    post_sms(phone, "my sink is leaking")
    post_sms(phone, "OK")
    assert "SMS" in calls[0] and "reply OK" in calls[0]
    assert outbox[0][1] == "Where is the leak, and what is your ZIP?"
    assert "repair request #" in outbox[1][1]
    with get_engine().connect() as c:
        n = c.execute(
            text(
                "SELECT count(*) FROM tickets t JOIN users u ON u.id = t.customer_id "
                "WHERE u.phone_e164 = :p AND t.status = 'OPEN'"
            ),
            {"p": phone},
        ).scalar()
    assert n == 1


@db
def test_emergency_by_sms(outbox):
    phone = new_phone()
    post_sms(phone, "I smell gas in my kitchen")
    assert "911" in outbox[0][1]


@db
def test_mms_photo_is_downloaded_validated_and_attached(outbox, monkeypatch):
    monkeypatch.setattr(twilio, "download_media", lambda url, limit: make_image("JPEG"))
    phone = new_phone()
    post_sms(
        phone,
        "",
        extra={
            "NumMedia": "1",
            "MediaUrl0": "https://api.twilio.com/2010-04-01/Accounts/AC1/Messages/MM1/Media/ME1",
            "MediaContentType0": "image/jpeg",
        },
    )
    assert outbox == [(phone, "Echo: (received 1 photo)")]


@db
def test_bad_mms_attachment_is_skipped_but_text_still_answered(outbox, monkeypatch):
    monkeypatch.setattr(twilio, "download_media", lambda url, limit: b"not an image")
    phone = new_phone()
    post_sms(
        phone,
        "see photo",
        extra={"NumMedia": "1", "MediaUrl0": "https://api.twilio.com/x"},
    )
    assert outbox == [(phone, "Echo: see photo")]


@db
def test_send_failure_is_logged_not_raised(outbox, monkeypatch, caplog):
    def broken(to, body):
        raise twilio.TwilioError("HTTP 400 (21608: unverified number)")

    monkeypatch.setattr(twilio, "send_sms", broken)
    phone = new_phone()
    assert post_sms(phone, "hello").status_code == 200
    assert "21608" in caplog.text
    assert phone not in caplog.text  # numbers are masked in logs
