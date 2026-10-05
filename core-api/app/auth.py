import hmac
import secrets
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import shared_engine
from app.security import (
    burn_password_check,
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    display_name: str | None = Field(default=None, max_length=80)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


def issue_tokens(conn, user_id, role) -> tuple[TokenOut, str]:
    s = get_settings()
    raw = new_refresh_token()
    row_id = conn.execute(
        text(
            "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) "
            "VALUES (:u, :h, now() + make_interval(days => :d)) RETURNING id"
        ),
        {"u": user_id, "h": hash_refresh_token(raw), "d": s.refresh_ttl_days},
    ).scalar_one()
    tokens = TokenOut(
        access_token=create_access_token(str(user_id), role),
        refresh_token=raw,
        expires_in=s.access_ttl_min * 60,
    )
    return tokens, str(row_id)


# ---------- email / password ----------
@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn):
    try:
        with shared_engine().begin() as conn:
            row = conn.execute(
                text(
                    "INSERT INTO users (role, email, password_hash, display_name) "
                    "VALUES ('CUSTOMER', :e, :p, :n) RETURNING id, role"
                ),
                {
                    "e": body.email.lower(),
                    "p": hash_password(body.password),
                    "n": body.display_name,
                },
            ).one()
            tokens, _ = issue_tokens(conn, row.id, row.role)
    except IntegrityError:
        raise HTTPException(409, "Email already registered") from None
    return tokens


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn):
    with shared_engine().begin() as conn:
        user = conn.execute(
            text("SELECT id, role, password_hash FROM users WHERE email = :e"),
            {"e": body.email.lower()},
        ).first()
        if user is None or not user.password_hash:
            burn_password_check(body.password)
            ok = False
        else:
            ok = verify_password(body.password, user.password_hash)
        if not ok:
            raise HTTPException(401, "Invalid email or password")
        tokens, _ = issue_tokens(conn, user.id, user.role)
    return tokens


# ---------- refresh / logout ----------
@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn):
    tokens = None
    with shared_engine().begin() as conn:
        row = conn.execute(
            text(
                "SELECT r.id, r.user_id, r.revoked_at, r.expires_at, u.role "
                "FROM refresh_tokens r JOIN users u ON u.id = r.user_id "
                "WHERE r.token_hash = :h FOR UPDATE OF r"
            ),
            {"h": hash_refresh_token(body.refresh_token)},
        ).first()
        if row is not None and row.revoked_at is not None:
            # A used token came back: assume theft and end every session for this user.
            conn.execute(
                text(
                    "UPDATE refresh_tokens SET revoked_at = now() "
                    "WHERE user_id = :u AND revoked_at IS NULL"
                ),
                {"u": row.user_id},
            )
        elif row is not None and row.expires_at > datetime.now(UTC):
            tokens, new_id = issue_tokens(conn, row.user_id, row.role)
            conn.execute(
                text(
                    "UPDATE refresh_tokens SET revoked_at = now(), replaced_by = :n WHERE id = :i"
                ),
                {"n": new_id, "i": row.id},
            )
    if tokens is None:
        raise HTTPException(401, "Invalid refresh token")
    return tokens


@router.post("/logout", status_code=204)
def logout(body: RefreshIn):
    with shared_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE refresh_tokens SET revoked_at = now() "
                "WHERE token_hash = :h AND revoked_at IS NULL"
            ),
            {"h": hash_refresh_token(body.refresh_token)},
        )


# ---------- current user dependency ----------
def current_user(creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> dict:
    if creds is None:
        raise HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired") from None
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token") from None
    with shared_engine().connect() as conn:
        user = (
            conn.execute(
                text(
                    "SELECT id, role, email, display_name, phone_e164, preferred_channel, "
                    "created_at FROM users WHERE id = :i"
                ),
                {"i": payload["sub"]},
            )
            .mappings()
            .first()
        )
    if user is None:
        raise HTTPException(401, "Unknown user")
    return dict(user)


# ---------- Google / Facebook OAuth ----------
PROVIDERS = {
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "userinfo": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
    },
    "facebook": {
        "authorize": "https://www.facebook.com/v19.0/dialog/oauth",
        "token": "https://graph.facebook.com/v19.0/oauth/access_token",
        "userinfo": "https://graph.facebook.com/v19.0/me?fields=id,name,email",
        "scope": "email,public_profile",
    },
}


class OAuthError(Exception):
    pass


def _credentials(provider: str) -> tuple[str, str]:
    s = get_settings()
    if provider == "google":
        return s.google_client_id, s.google_client_secret
    return s.facebook_app_id, s.facebook_app_secret


def _redirect_uri(provider: str) -> str:
    return f"{get_settings().api_base_url}/auth/{provider}/callback"


def fetch_profile(provider: str, code: str) -> dict:
    """Exchange the authorization code and return {sub, email, email_verified, name}."""
    cfg = PROVIDERS[provider]
    client_id, client_secret = _credentials(provider)
    with httpx.Client(timeout=10) as http:
        token = http.post(
            cfg["token"],
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": _redirect_uri(provider),
                "grant_type": "authorization_code",
            },
        )
        token.raise_for_status()
        access = token.json()["access_token"]
        info = http.get(cfg["userinfo"], headers={"Authorization": f"Bearer {access}"})
        info.raise_for_status()
        data = info.json()
    if provider == "google":
        return {
            "sub": data["sub"],
            "email": data.get("email"),
            "email_verified": bool(data.get("email_verified")),
            "name": data.get("name"),
        }
    # Facebook does not guarantee a verified email, so it is never used to link accounts.
    return {
        "sub": data["id"],
        "email": data.get("email"),
        "email_verified": False,
        "name": data.get("name"),
    }


def upsert_oauth_user(conn, provider: str, profile: dict) -> tuple[str, str]:
    found = conn.execute(
        text("SELECT id, role FROM users WHERE auth_provider = :p AND provider_sub = :s"),
        {"p": provider, "s": profile["sub"]},
    ).first()
    if found:
        return found.id, found.role
    email = (profile.get("email") or "").lower() or None
    if email:
        existing = conn.execute(
            text("SELECT id, role, auth_provider FROM users WHERE email = :e"), {"e": email}
        ).first()
        if existing:
            if profile.get("email_verified") and existing.auth_provider is None:
                # Link, and drop the password: that account's email was never verified,
                # so whoever registered it must not keep access.
                conn.execute(
                    text(
                        "UPDATE users SET auth_provider = :p, provider_sub = :s, "
                        "password_hash = NULL, display_name = COALESCE(display_name, :n) "
                        "WHERE id = :i"
                    ),
                    {
                        "p": provider,
                        "s": profile["sub"],
                        "n": profile.get("name"),
                        "i": existing.id,
                    },
                )
                conn.execute(
                    text(
                        "UPDATE refresh_tokens SET revoked_at = now() "
                        "WHERE user_id = :i AND revoked_at IS NULL"
                    ),
                    {"i": existing.id},
                )
                return existing.id, existing.role
            raise OAuthError("account_exists")
    row = conn.execute(
        text(
            "INSERT INTO users (role, email, auth_provider, provider_sub, display_name) "
            "VALUES ('CUSTOMER', :e, :p, :s, :n) RETURNING id, role"
        ),
        {"e": email, "p": provider, "s": profile["sub"], "n": profile.get("name")},
    ).one()
    return row.id, row.role


def _provider_or_404(provider: str) -> dict:
    if provider not in PROVIDERS:
        raise HTTPException(404, "Unknown provider")
    return PROVIDERS[provider]


@router.get("/{provider}/login")
def oauth_login(provider: str):
    cfg = _provider_or_404(provider)
    client_id, _ = _credentials(provider)
    if not client_id:
        raise HTTPException(503, f"{provider} login is not configured")
    state = secrets.token_urlsafe(24)
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": _redirect_uri(provider),
            "response_type": "code",
            "scope": cfg["scope"],
            "state": state,
        }
    )
    resp = RedirectResponse(f"{cfg['authorize']}?{query}")
    resp.set_cookie(
        "oauth_state",
        state,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=get_settings().api_base_url.startswith("https"),
    )
    return resp


@router.get("/{provider}/callback")
def oauth_callback(
    provider: str,
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    _provider_or_404(provider)
    web = get_settings().web_base_url

    def fail(reason: str) -> RedirectResponse:
        resp = RedirectResponse(f"{web}/#{urlencode({'error': reason})}")
        resp.delete_cookie("oauth_state")
        return resp

    cookie_state = request.cookies.get("oauth_state") or ""
    if error or not code or not state or not hmac.compare_digest(state, cookie_state):
        return fail(error or "invalid_state")
    try:
        profile = fetch_profile(provider, code)
        with shared_engine().begin() as conn:
            user_id, role = upsert_oauth_user(conn, provider, profile)
            tokens, _ = issue_tokens(conn, user_id, role)
    except OAuthError as e:
        return fail(str(e))
    except (httpx.HTTPError, KeyError):
        return fail("provider_error")
    fragment = urlencode(
        {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires_in": tokens.expires_in,
        }
    )
    resp = RedirectResponse(f"{web}/#{fragment}")
    resp.delete_cookie("oauth_state")
    return resp
