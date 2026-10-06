import base64
import os
import uuid
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.agent import gemini
from app.agent.context import PHOTO_NOTE
from app.main import app
from tests.helpers import make_image

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set (needs migrated Postgres)"
)

client = TestClient(app)


def signed_in():
    email = f"{uuid.uuid4().hex[:12]}@example.com"
    r = client.post("/auth/register", json={"email": email, "password": "correct-horse-battery"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def upload(h, data=None, name="leak.png", ctype="image/png"):
    data = make_image("PNG") if data is None else data
    return client.post("/media", files={"file": (name, data, ctype)}, headers=h)


# ---------- upload and download ----------
def test_upload_returns_metadata_and_saves_a_jpeg(temp_media_dir):
    h = signed_in()
    r = upload(h, make_image("PNG", size=(3000, 1500)))
    assert r.status_code == 201
    body = r.json()
    assert body["mime_type"] == "image/jpeg"
    assert (body["width"], body["height"]) == (1600, 800)
    saved = list(temp_media_dir.rglob("*.jpg"))
    assert len(saved) == 1 and saved[0].name == f"{body['id']}.jpg"


def test_owner_can_download_photo():
    h = signed_in()
    upload_id = upload(h).json()["id"]
    r = client.get(f"/media/{upload_id}", headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert Image.open(BytesIO(r.content)).format == "JPEG"


def test_other_users_and_anonymous_cannot_download():
    owner, stranger = signed_in(), signed_in()
    upload_id = upload(owner).json()["id"]
    assert client.get(f"/media/{upload_id}", headers=stranger).status_code == 404
    assert client.get(f"/media/{upload_id}").status_code == 401
    assert client.get(f"/media/{uuid.uuid4()}", headers=owner).status_code == 404


def test_upload_requires_login():
    r = client.post("/media", files={"file": ("a.png", make_image(), "image/png")})
    assert r.status_code == 401


def test_fake_image_rejected_even_with_image_name_and_type(temp_media_dir):
    h = signed_in()
    r = upload(h, b"<script>alert(1)</script>", name="evil.jpg", ctype="image/jpeg")
    assert r.status_code == 415
    assert not list(temp_media_dir.rglob("*"))  # nothing stored


def test_oversized_upload_rejected(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "1000")
    h = signed_in()
    r = upload(h, make_image("PNG", size=(400, 400), color=(1, 2, 3)) + b"x" * 2000)
    assert r.status_code == 413


# ---------- photos in chat ----------
def test_photo_only_message_gets_echo_reply_and_shows_in_history():
    h = signed_in()
    upload_id = upload(h).json()["id"]
    r = client.post("/chat/messages", json={"media_ids": [upload_id]}, headers=h)
    assert r.status_code == 201
    mine, bot = r.json()["messages"]
    assert mine["body"] == "" and mine["media_ids"] == [upload_id]
    assert bot["body"] == "Echo: (received 1 photo)"
    history = client.get("/chat/messages", headers=h).json()["messages"]
    assert history[0]["media_ids"] == [upload_id]
    assert history[1]["media_ids"] == []


def test_photo_is_sent_to_gemini_inline_and_later_only_as_a_note(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    calls = []

    def fake(contents, **kw):
        calls.append(contents)
        return gemini.GeminiResult("I can see water damage. Severity: Medium")

    monkeypatch.setattr(gemini, "generate", fake)
    h = signed_in()
    upload_id = upload(h).json()["id"]
    r = client.post(
        "/chat/messages", json={"body": "what is this stain?", "media_ids": [upload_id]}, headers=h
    )
    assert r.json()["messages"][1]["body"].endswith("Severity: Medium")
    parts = calls[0][-1]["parts"]
    assert parts[0]["text"] == f"what is this stain? {PHOTO_NOTE}"
    inline = parts[1]["inline_data"]
    assert inline["mime_type"] == "image/jpeg"
    assert base64.b64decode(inline["data"])[:2] == b"\xff\xd8"  # JPEG bytes

    client.post("/chat/messages", json={"body": "it is on the ceiling"}, headers=h)
    second = calls[1]
    assert all("inline_data" not in p for c in second for p in c["parts"])
    assert PHOTO_NOTE in second[0]["parts"][0]["text"]


def test_cannot_attach_someone_elses_or_unknown_photo():
    owner, stranger = signed_in(), signed_in()
    upload_id = upload(owner).json()["id"]
    for media_id in (upload_id, str(uuid.uuid4())):
        r = client.post(
            "/chat/messages", json={"body": "hi", "media_ids": [media_id]}, headers=stranger
        )
        assert r.status_code == 400
    assert client.get("/chat/messages", headers=stranger).json()["messages"] == []


def test_message_limits():
    h = signed_in()
    ids = [upload(h).json()["id"] for _ in range(4)]
    assert client.post("/chat/messages", json={"media_ids": ids}, headers=h).status_code == 422
    assert client.post("/chat/messages", json={"body": "  "}, headers=h).status_code == 422
    r = client.post("/chat/messages", json={"media_ids": [ids[0], ids[0]]}, headers=h)
    assert r.json()["messages"][0]["media_ids"] == [ids[0]]


def test_emergency_text_with_photo_still_skips_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(
        gemini, "generate", lambda c, **kw: pytest.fail("Gemini must not be called")
    )
    h = signed_in()
    upload_id = upload(h).json()["id"]
    r = client.post(
        "/chat/messages", json={"body": "I smell gas here", "media_ids": [upload_id]}, headers=h
    )
    assert r.json()["messages"][1]["flag"] == "EMERGENCY"
