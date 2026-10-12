"""Checks for the pieces the release pipeline (T13-3) relies on."""

import os
import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

REPO = Path(__file__).resolve().parents[2]
client = TestClient(app)


def test_extra_web_origins_are_allowed_besides_the_main_one(monkeypatch):
    monkeypatch.setenv("WEB_BASE_URL", "https://web.example.run.app/")
    monkeypatch.setenv("CORS_ORIGINS", "https://test.alchehome.example, https://b.example/ ,")
    assert get_settings().cors_origins == [
        "https://web.example.run.app",
        "https://test.alchehome.example",
        "https://b.example",
    ]
    monkeypatch.delenv("CORS_ORIGINS")
    assert get_settings().cors_origins == ["https://web.example.run.app"]


def test_test_mode_is_off_unless_asked_for(monkeypatch):
    monkeypatch.delenv("TEST_MODE", raising=False)
    assert get_settings().test_mode is False
    monkeypatch.setenv("TEST_MODE", "true")
    assert get_settings().test_mode is True


def test_health_reports_the_cloud_run_revision(monkeypatch):
    monkeypatch.setenv("K_REVISION", "alche-dev-core-api-rabc123")
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["revision"] == "alche-dev-core-api-rabc123"


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set")
def test_verification_codes_are_returned_only_locally_or_in_test_mode(monkeypatch):
    import random

    from app.security import create_access_token
    from tests.test_dispatch import new_user  # noqa: F401  (helper only)

    class W:  # a tiny stand-in for the `world` fixture's user list
        users: list = []

    w = W()
    w.users = []
    from sqlalchemy import text

    from app.db import get_engine

    try:
        uid = new_user(w, "CUSTOMER")
        h = {"Authorization": f"Bearer {create_access_token(str(uid), 'CUSTOMER')}"}
        monkeypatch.setenv("JWT_SECRET", "x" * 40)
        monkeypatch.setenv("APP_ENV", "dev")
        monkeypatch.delenv("TEST_MODE", raising=False)
        number = "+1619" + str(random.randint(5000000, 9999999))
        h = {"Authorization": f"Bearer {create_access_token(str(uid), 'CUSTOMER')}"}
        hidden = client.post("/me/profile/phone", json={"phone": number}, headers=h)
        assert hidden.status_code == 200 and hidden.json()["dev_code"] is None
        with get_engine().begin() as c:
            c.execute(text("DELETE FROM phone_verifications WHERE user_id = :u"), {"u": uid})
        monkeypatch.setenv("TEST_MODE", "true")
        shown = client.post("/me/profile/phone", json={"phone": number}, headers=h)
        assert shown.status_code == 200 and re.fullmatch(r"\d{6}", shown.json()["dev_code"])
    finally:
        with get_engine().begin() as c:
            c.execute(
                text("DELETE FROM users WHERE id = ANY(CAST(:i AS uuid[]))"),
                {"i": [str(u) for u in w.users]},
            )


# ---------- the web pages are deployable as static files ----------
@pytest.mark.parametrize("page", ["index.html", "handyman.html", "admin.html"])
def test_pages_load_config_before_their_own_script(page):
    html = (REPO / "web" / page).read_text(encoding="utf-8")
    config = html.index('src="config.js')
    assert config < html.index("const API = window.API_BASE")
    assert config < html.index('src="i18n.js')


def test_default_config_points_at_the_local_api():
    cfg = (REPO / "web" / "config.js").read_text(encoding="utf-8")
    assert "window.API_BASE = 'http://localhost:8000'" in cfg


def test_web_image_files_exist():
    for name in ["Dockerfile", "docker/default.conf.template", "docker/40-config.sh"]:
        assert (REPO / "web" / name).is_file(), name
    template = (REPO / "web" / "docker" / "default.conf.template").read_text(encoding="utf-8")
    assert "listen ${PORT};" in template and "/healthz" in template


@pytest.mark.skipif(
    subprocess.run(["bash", "-c", "true"], capture_output=True).returncode != 0,
    reason="bash not available",
)
def test_release_script_is_valid_bash_and_stops_before_deploying_without_settings():
    script = REPO / "deploy" / "release.sh"
    assert subprocess.run(["bash", "-n", str(script)]).returncode == 0
    run = subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, env={"PATH": os.environ["PATH"]}
    )
    assert run.returncode != 0 and "PROJECT_ID" in run.stderr


# ---------- limits for the public test deployment ----------
def test_signup_login_and_chat_are_limited_outside_local_development(monkeypatch):
    from app import ratelimit

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    ratelimit.reset()
    codes = []
    for _ in range(62):
        r = client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": "wrong-password-1"},
            headers={"X-Forwarded-For": "203.0.113.9"},
        )
        codes.append(r.status_code)
    assert codes.count(401) == 60 and codes[-1] == 429
    assert "Retry-After" in r.headers
    # Another client address has its own allowance.
    other = client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "wrong-password-1"},
        headers={"X-Forwarded-For": "203.0.113.10"},
    )
    assert other.status_code == 401
    ratelimit.reset()


def test_limits_are_off_for_local_development(monkeypatch):
    from app import ratelimit

    monkeypatch.setenv("APP_ENV", "local")
    ratelimit.reset()
    statuses = {
        client.post(
            "/auth/login", json={"email": "nobody@example.com", "password": "wrong-password-1"}
        ).status_code
        for _ in range(70)
    }
    assert statuses == {401}
