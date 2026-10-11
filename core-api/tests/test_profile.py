import os
import random
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import dispatch
from app.db import get_engine
from app.main import app
from app.profile import mask_phone, normalize_phone
from app.security import create_access_token
from tests.test_dispatch import (  # noqa: F401  (world is a fixture)
    new_handyman,
    new_ticket,
    new_user,
    offers,
    world,
)

client = TestClient(app)
db = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set")


def auth(uid, role="HANDYMAN"):
    return {"Authorization": f"Bearer {create_access_token(str(uid), role)}"}


def profile_payload(**over):
    base = {
        "display_name": "Sam T.",
        "skills": ["CARPENTRY"],
        "specialties": ["Hardwood floors"],
        "service_zips": ["92101", "92102"],
        "is_available": True,
    }
    return {**base, **over}


def new_pending(world, name="Sam T."):  # noqa: F811
    """A handyman account with a bare profile awaiting approval."""
    uid = new_user(world, "HANDYMAN")
    with get_engine().begin() as c:
        c.execute(
            text("INSERT INTO handymen (user_id, display_name) VALUES (:u, :n)"),
            {"u": uid, "n": name},
        )
    return uid


def admin(world):  # noqa: F811
    return auth(new_user(world, "ADMIN"), "ADMIN")


# ---------- pure helpers ----------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("6195550199", "+16195550199"),
        ("(619) 555-0199", "+16195550199"),
        ("1 619 555 0199", "+16195550199"),
        ("+442071838750", "+442071838750"),
        ("12345", None),
        ("abc", None),
        ("+0123456789", None),
    ],
)
def test_phone_normalization(raw, expected):
    assert normalize_phone(raw) == expected


def test_phone_masking():
    assert mask_phone("+16195550199") == "+1******0199"
    assert mask_phone(None) is None


# ---------- own profile ----------
@db
def test_profile_starts_pending_and_incomplete(world):  # noqa: F811
    uid = new_pending(world)
    p = client.get("/pro/profile", headers=auth(uid)).json()
    assert p["status"] == "PENDING" and p["complete"] is False
    assert p["skills"] == [] and p["service_zips"] == [] and p["phone"] is None
    assert {o["category"] for o in p["skill_options"]} >= {"CARPENTRY", "PLUMBING"}
    assert (
        client.get(
            "/pro/profile", headers=auth(new_user(world, "CUSTOMER"), "CUSTOMER")
        ).status_code
        == 403
    )
    assert client.get("/pro/profile").status_code == 401


@db
def test_profile_without_a_handymen_row_is_created_on_first_visit(world):  # noqa: F811
    uid = new_user(world, "HANDYMAN")
    assert client.get("/pro/profile", headers=auth(uid)).status_code == 200


@db
def test_save_profile_normalizes_and_completes(world):  # noqa: F811
    uid = new_pending(world)
    r = client.put(
        "/pro/profile",
        json=profile_payload(
            display_name="  Sam   T. ",
            skills=["carpentry", "CARPENTRY", "plumbing"],
            specialties=["Hardwood floors", "hardwood FLOORS", " ", "Tiles"],
            service_zips=["92102", "92101", "92102"],
        ),
        headers=auth(uid),
    )
    assert r.status_code == 200
    p = r.json()
    assert p["display_name"] == "Sam T."
    assert p["skills"] == ["CARPENTRY", "PLUMBING"]
    assert p["specialties"] == ["Hardwood floors", "Tiles"]
    assert p["service_zips"] == ["92102", "92101"]  # order kept: first is the home ZIP
    assert p["complete"] is True and p["status"] == "PENDING"


@pytest.mark.parametrize(
    "change",
    [
        {"service_zips": ["9210"]},
        {"service_zips": ["abcde"]},
        {"service_zips": [f"9{i:04d}" for i in range(31)]},
        {"skills": ["ROOFING"]},
        {"display_name": "A"},
        {"specialties": ["x" * 31]},
        {"specialties": [f"s{i}" for i in range(11)]},
    ],
)
@db
def test_invalid_profiles_are_rejected(world, change):  # noqa: F811
    uid = new_pending(world)
    r = client.put("/pro/profile", json=profile_payload(**change), headers=auth(uid))
    assert r.status_code == 422


# ---------- approval and matching ----------
@db
def test_pending_profile_gets_no_offers_until_approved_then_edits_apply_at_once(world):  # noqa: F811
    uid = new_pending(world)
    h = auth(uid)
    client.put(
        "/pro/profile",
        json=profile_payload(skills=["PLUMBING"], service_zips=[world.zip]),
        headers=h,
    )
    tid, _ = new_ticket(world)
    dispatch.start_dispatch(tid)  # nobody approved: UNMATCHED
    assert offers(tid) == []
    ops = admin(world)
    assert client.post(f"/admin/handymen/{uid}/approve", headers=ops).status_code == 200
    assert client.get("/pro/profile", headers=h).json()["status"] == "APPROVED"
    assert dispatch.start_dispatch(tid)  # retried: now they are asked
    assert offers(tid) == [("Sam T.", "SENT")]
    # Dropping the ZIP and going on break takes effect for the next ticket, no re-approval.
    client.put(
        "/pro/profile",
        json=profile_payload(skills=["PLUMBING"], service_zips=["99999"], is_available=False),
        headers=h,
    )
    tid2, _ = new_ticket(world)
    dispatch.start_dispatch(tid2)
    assert offers(tid2) == []
    assert client.get("/pro/profile", headers=h).json()["status"] == "APPROVED"


@db
def test_new_expertise_makes_a_handyman_eligible_for_that_trade(world):  # noqa: F811
    uid, _ = new_handyman(world, "Sam T.", 4.5, skills=("PLUMBING",))
    tid, _ = new_ticket(world)  # a plumbing ticket
    with get_engine().begin() as c:
        c.execute(text("UPDATE tickets SET category = 'CARPENTRY' WHERE id = :t"), {"t": tid})
    dispatch.start_dispatch(tid)
    assert offers(tid) == []  # no carpentry skill yet
    client.put(
        "/pro/profile",
        json=profile_payload(skills=["PLUMBING", "CARPENTRY"], service_zips=[world.zip]),
        headers=auth(uid),
    )
    assert dispatch.start_dispatch(tid)
    assert offers(tid) == [("Sam T.", "SENT")]


@db
def test_home_zip_order_changes_the_ranking(world):  # noqa: F811
    first, _ = new_handyman(world, "Local", 4.0)
    second, _ = new_handyman(world, "Far", 4.0)
    other = "98" + str(random.randint(100, 999))
    client.put(
        "/pro/profile",
        json=profile_payload(
            display_name="Local", skills=["PLUMBING"], service_zips=[world.zip, other]
        ),
        headers=auth(first),
    )
    client.put(
        "/pro/profile",
        json=profile_payload(
            display_name="Far", skills=["PLUMBING"], service_zips=[other, world.zip]
        ),
        headers=auth(second),
    )
    tid, _ = new_ticket(world)
    dispatch.start_dispatch(tid)
    assert offers(tid) == [("Local", "SENT")]  # same rating; the ticket ZIP is their home ZIP


# ---------- phone number ----------
@db
def test_phone_change_needs_the_sms_code(world):  # noqa: F811
    uid = new_pending(world)
    h = auth(uid)
    number = "+1619" + str(random.randint(5000000, 9999999))
    assert client.post("/pro/profile/phone", json={"phone": "12345"}, headers=h).status_code == 422
    r = client.post("/pro/profile/phone", json={"phone": number}, headers=h)
    assert r.status_code == 200 and r.json()["dev_code"]
    code = r.json()["dev_code"]
    assert world.messages[-1][0] == number and code in world.messages[-1][1]
    assert client.get("/pro/profile", headers=h).json()["phone"] is None  # not stored yet
    assert client.get("/pro/profile", headers=h).json()["phone_pending"] is True
    wrong = "000000" if code != "000000" else "111111"
    assert (
        client.post("/pro/profile/phone/verify", json={"code": wrong}, headers=h).status_code == 400
    )
    ok = client.post("/pro/profile/phone/verify", json={"code": code}, headers=h)
    assert ok.status_code == 200 and ok.json()["phone"] == mask_phone(number)
    assert ok.json()["phone_pending"] is False
    with get_engine().connect() as c:
        stored = c.execute(text("SELECT phone_e164 FROM users WHERE id = :u"), {"u": uid}).scalar()
    assert stored == number
    assert (
        client.post("/pro/profile/phone/verify", json={"code": code}, headers=h).status_code == 400
    )


@db
def test_phone_code_attempts_are_limited_and_numbers_are_unique(world):  # noqa: F811
    uid = new_pending(world)
    h = auth(uid)
    other, other_phone = new_handyman(world, "Other", 4.0)
    taken = client.post("/pro/profile/phone", json={"phone": other_phone}, headers=h)
    assert taken.status_code == 409
    number = "+1619" + str(random.randint(5000000, 9999999))
    code = client.post("/pro/profile/phone", json={"phone": number}, headers=h).json()["dev_code"]
    again = client.post("/pro/profile/phone", json={"phone": number}, headers=h)
    assert again.status_code == 429  # asked again too soon
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert (
            client.post("/pro/profile/phone/verify", json={"code": wrong}, headers=h).status_code
            == 400
        )
    # Even the right code no longer works after five misses.
    assert (
        client.post("/pro/profile/phone/verify", json={"code": code}, headers=h).status_code == 429
    )


@db
def test_expired_code_is_refused(world):  # noqa: F811
    uid = new_pending(world)
    h = auth(uid)
    number = "+1619" + str(random.randint(5000000, 9999999))
    code = client.post("/pro/profile/phone", json={"phone": number}, headers=h).json()["dev_code"]
    with get_engine().begin() as c:
        c.execute(text("UPDATE phone_verifications SET expires_at = now() - interval '1 minute'"))
    assert (
        client.post("/pro/profile/phone/verify", json={"code": code}, headers=h).status_code == 400
    )


@db
def test_dev_code_is_hidden_outside_local(world, monkeypatch):  # noqa: F811
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    uid = new_pending(world)
    number = "+1619" + str(random.randint(5000000, 9999999))
    r = client.post("/pro/profile/phone", json={"phone": number}, headers=auth(uid))
    assert r.status_code == 200 and r.json()["dev_code"] is None


# ---------- ops: add, invite, approve ----------
@db
def test_admin_adds_a_handyman_who_sets_a_password_and_completes_the_profile(world):  # noqa: F811
    ops = admin(world)
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/admin/handymen", json={"email": email, "display_name": "Sam T."}, headers=ops)
    assert r.status_code == 201
    url, hid = r.json()["invite_url"], r.json()["handyman_id"]
    world.users.append(uuid.UUID(hid))
    assert "/handyman.html#invite=" in url
    assert (
        client.post(
            "/admin/handymen", json={"email": email, "display_name": "Sam"}, headers=ops
        ).status_code
        == 409
    )
    token = url.split("invite=")[1]
    tokens = client.post(
        "/pro/set-password", json={"token": token, "password": "a-long-new-password"}
    ).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.get("/pro/profile", headers=h).json()["display_name"] == "Sam T."
    # Cannot be approved with an empty profile.
    assert client.post(f"/admin/handymen/{hid}/approve", headers=ops).status_code == 409
    client.put("/pro/profile", json=profile_payload(), headers=h)
    row = [x for x in client.get("/admin/handymen", headers=ops).json() if x["handyman_id"] == hid][
        0
    ]
    assert row["status"] == "PENDING" and row["complete"] is True and row["has_password"] is True
    assert row["skills"] == ["CARPENTRY"] and row["service_zips"] == ["92101", "92102"]
    assert client.post(f"/admin/handymen/{hid}/approve", headers=ops).json() == {
        "status": "APPROVED"
    }
    assert client.post(f"/admin/handymen/{hid}/suspend", headers=ops).json() == {
        "status": "PENDING"
    }
    assert client.post(f"/admin/handymen/{hid}/invite", headers=ops).status_code == 200


@db
def test_handyman_admin_endpoints_are_admin_only(world):  # noqa: F811
    hid = new_pending(world)
    for h in (auth(hid), auth(new_user(world, "CUSTOMER"), "CUSTOMER")):
        assert client.get("/admin/handymen", headers=h).status_code == 403
        assert client.post(f"/admin/handymen/{hid}/approve", headers=h).status_code == 403
    unknown = "00000000-0000-0000-0000-000000000000"
    assert (
        client.post(f"/admin/handymen/{unknown}/approve", headers=admin(world)).status_code == 404
    )


def test_browser_preflight_allows_put_for_the_profile_page():
    r = client.options(
        "/pro/profile",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert r.status_code == 200
    assert "PUT" in r.headers["access-control-allow-methods"]
