import os
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set (needs migrated Postgres)"
)

client = TestClient(app)
PASSWORD = "correct-horse-battery"


def new_email() -> str:
    return f"{uuid.uuid4().hex[:12]}@example.com"


def register(email=None, password=PASSWORD):
    email = email or new_email()
    r = client.post("/auth/register", json={"email": email, "password": password})
    return email, r


def fragment(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(url).fragment).items()}


def test_register_login_and_me():
    email, r = register()
    assert r.status_code == 201
    assert {"access_token", "refresh_token", "expires_in"} <= r.json().keys()
    r = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200
    me = client.get("/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == email
    assert me.json()["role"] == "CUSTOMER"


def test_duplicate_email_and_weak_password_rejected():
    email, _ = register()
    assert register(email)[1].status_code == 409
    assert register(password="short")[1].status_code == 422


def test_wrong_password_and_unknown_user_look_the_same():
    email, _ = register()
    bad = client.post("/auth/login", json={"email": email, "password": "wrong-password-1"})
    unknown = client.post(
        "/auth/login", json={"email": new_email(), "password": "wrong-password-1"}
    )
    assert bad.status_code == unknown.status_code == 401
    assert bad.json() == unknown.json()


def test_me_requires_a_valid_token():
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_refresh_rotates_and_reuse_revokes_everything():
    _, r = register()
    first = r.json()["refresh_token"]
    r2 = client.post("/auth/refresh", json={"refresh_token": first})
    assert r2.status_code == 200
    second = r2.json()["refresh_token"]
    assert second != first
    # Replaying the old token is treated as theft: the new token stops working too.
    assert client.post("/auth/refresh", json={"refresh_token": first}).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": second}).status_code == 401


def test_logout_revokes_refresh_token():
    _, r = register()
    token = r.json()["refresh_token"]
    assert client.post("/auth/logout", json={"refresh_token": token}).status_code == 204
    assert client.post("/auth/refresh", json={"refresh_token": token}).status_code == 401


def test_oauth_not_configured_returns_503(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    assert client.get("/auth/google/login", follow_redirects=False).status_code == 503
    assert client.get("/auth/nope/login", follow_redirects=False).status_code == 404


def test_google_oauth_flow_creates_user_and_issues_tokens(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client")
    email = new_email()
    sub = uuid.uuid4().hex
    monkeypatch.setattr(
        auth,
        "fetch_profile",
        lambda provider, code: {"sub": sub, "email": email, "email_verified": True, "name": "Sam"},
    )
    c = TestClient(app)
    start = c.get("/auth/google/login", follow_redirects=False)
    assert start.status_code == 307
    location = urlparse(start.headers["location"])
    assert location.netloc == "accounts.google.com"
    state = parse_qs(location.query)["state"][0]

    done = c.get(f"/auth/google/callback?code=abc&state={state}", follow_redirects=False)
    tokens = fragment(done.headers["location"])
    me = c.get("/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()
    assert me["email"] == email
    assert me["display_name"] == "Sam"

    # Logging in again maps to the same user.
    state2 = parse_qs(
        urlparse(c.get("/auth/google/login", follow_redirects=False).headers["location"]).query
    )["state"][0]
    again = c.get(f"/auth/google/callback?code=abc&state={state2}", follow_redirects=False)
    me2 = c.get(
        "/me",
        headers={"Authorization": f"Bearer {fragment(again.headers['location'])['access_token']}"},
    ).json()
    assert me2["id"] == me["id"]


def test_oauth_callback_rejects_wrong_state(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client")
    c = TestClient(app)
    c.get("/auth/google/login", follow_redirects=False)
    r = c.get("/auth/google/callback?code=abc&state=forged", follow_redirects=False)
    assert fragment(r.headers["location"]) == {"error": "invalid_state"}


def test_verified_google_login_takes_over_unverified_password_account(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client")
    email, r = register()
    old_refresh = r.json()["refresh_token"]
    monkeypatch.setattr(
        auth,
        "fetch_profile",
        lambda p, c: {
            "sub": uuid.uuid4().hex,
            "email": email,
            "email_verified": True,
            "name": "Real Owner",
        },
    )
    c = TestClient(app)
    state = parse_qs(
        urlparse(c.get("/auth/google/login", follow_redirects=False).headers["location"]).query
    )["state"][0]
    c.get(f"/auth/google/callback?code=abc&state={state}", follow_redirects=False)
    # The earlier password and sessions no longer work.
    assert (
        client.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401
    )
    assert client.post("/auth/refresh", json={"refresh_token": old_refresh}).status_code == 401


def test_facebook_never_links_to_existing_email(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_ID", "fb-app")
    email, _ = register()
    monkeypatch.setattr(
        auth,
        "fetch_profile",
        lambda p, c: {
            "sub": uuid.uuid4().hex,
            "email": email,
            "email_verified": False,
            "name": "X",
        },
    )
    c = TestClient(app)
    state = parse_qs(
        urlparse(c.get("/auth/facebook/login", follow_redirects=False).headers["location"]).query
    )["state"][0]
    r = c.get(f"/auth/facebook/callback?code=abc&state={state}", follow_redirects=False)
    assert fragment(r.headers["location"]) == {"error": "account_exists"}
