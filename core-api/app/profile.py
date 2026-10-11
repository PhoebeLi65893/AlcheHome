"""Handyman profiles: the handyman edits their own, an admin approves and invites.

Expertise is a set of matching categories (the friendly names below map to them) plus optional
specialties shown to customers. ZIP codes are ordered: the first is the home ZIP, which gives
the best proximity score. A phone number only replaces the stored one after an SMS code.
"""

import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text

from app.admin import require_admin
from app.config import get_settings
from app.db import shared_engine
from app.dispatch import Outgoing, deliver
from app.pro import handyman_user

SKILL_OPTIONS = [
    {"category": "PLUMBING", "label": "Pipes and plumbing"},
    {"category": "CARPENTRY", "label": "Wood, flooring and carpentry"},
    {"category": "ELECTRICAL", "label": "Electrical"},
    {"category": "HVAC", "label": "Heating and cooling"},
    {"category": "APPLIANCE", "label": "Appliances"},
    {"category": "GENERAL", "label": "General repair"},
]
CATEGORIES = {o["category"] for o in SKILL_OPTIONS}
MAX_ZIPS = 30
MAX_SPECIALTIES = 10
CODE_TTL_MINUTES = 10
MAX_CODE_ATTEMPTS = 5
RESEND_SECONDS = 30

router = APIRouter(prefix="/pro/profile", tags=["handyman"])
admin_router = APIRouter(
    prefix="/admin/handymen", tags=["admin"], dependencies=[Depends(require_admin)]
)
Pro = Annotated[dict, Depends(handyman_user)]


# ---------- helpers ----------
def normalize_phone(raw: str) -> str | None:
    """+16195550199 style; 10-digit numbers are taken as US. None when it is not a phone number."""
    s = re.sub(r"[\s().-]", "", raw or "")
    if re.fullmatch(r"\d{10}", s):
        return "+1" + s
    if re.fullmatch(r"1\d{10}", s):
        return "+" + s
    return s if re.fullmatch(r"\+[1-9]\d{7,14}", s) else None


def mask_phone(phone: str | None) -> str | None:
    return None if not phone else phone[:2] + "*" * max(len(phone) - 6, 0) + phone[-4:]


def create_invite(conn, user_id) -> str:
    """A one-time set-password link token for a handyman account (valid 7 days)."""
    token = secrets.token_urlsafe(32)
    conn.execute(
        text(
            "INSERT INTO invite_tokens (token_hash, user_id, expires_at) "
            "VALUES (:h, :u, now() + interval '7 days')"
        ),
        {"h": hashlib.sha256(token.encode()).hexdigest(), "u": user_id},
    )
    return token


def invite_url(token: str) -> str:
    return f"{get_settings().web_base_url}/handyman.html#invite={token}"


def _code_hash(user_id, code: str) -> str:
    return hashlib.sha256(f"{user_id}:{code}".encode()).hexdigest()


# ---------- models ----------
class ProfileOut(BaseModel):
    display_name: str
    email: str | None
    phone: str | None  # masked
    phone_pending: bool
    skills: list[str]
    skill_options: list[dict]
    specialties: list[str]
    service_zips: list[str]
    is_available: bool
    status: str  # PENDING until an admin approves, then APPROVED
    complete: bool  # has expertise and at least one ZIP


class ProfileIn(BaseModel):
    display_name: str = Field(min_length=2, max_length=40)
    skills: list[str] = Field(default_factory=list, max_length=len(CATEGORIES))
    specialties: list[str] = Field(default_factory=list, max_length=MAX_SPECIALTIES)
    service_zips: list[str] = Field(default_factory=list, max_length=MAX_ZIPS)
    is_available: bool = True

    @field_validator("display_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("Display name is too short")
        return v

    @field_validator("skills")
    @classmethod
    def _skills(cls, v: list[str]) -> list[str]:
        out = list(dict.fromkeys(s.strip().upper() for s in v))
        bad = [s for s in out if s not in CATEGORIES]
        if bad:
            raise ValueError("Unknown expertise: " + ", ".join(bad))
        return out

    @field_validator("specialties")
    @classmethod
    def _specialties(cls, v: list[str]) -> list[str]:
        out = []
        for s in v:
            s = " ".join(s.split())
            if not s:
                continue
            if len(s) > 30:
                raise ValueError("A specialty can be at most 30 characters")
            if s.lower() not in {x.lower() for x in out}:
                out.append(s)
        return out

    @field_validator("service_zips")
    @classmethod
    def _zips(cls, v: list[str]) -> list[str]:
        out = []
        for z in v:
            z = z.strip()
            if not re.fullmatch(r"\d{5}", z):
                raise ValueError(f"{z!r} is not a 5-digit ZIP code")
            if z not in out:
                out.append(z)
        return out


class PhoneIn(BaseModel):
    phone: str = Field(min_length=7, max_length=30)


class CodeIn(BaseModel):
    code: str = Field(min_length=4, max_length=8)


class PhoneStarted(BaseModel):
    sent_to: str
    expires_in_minutes: int
    dev_code: str | None = None  # only when APP_ENV is local, so you can test without SMS


# ---------- the handyman's own profile ----------
def _ensure_profile(conn, user) -> None:
    conn.execute(
        text(
            "INSERT INTO handymen (user_id, display_name) VALUES (:u, :n) "
            "ON CONFLICT (user_id) DO NOTHING"
        ),
        {"u": user["id"], "n": (user.get("email") or "Handyman").split("@")[0].title()},
    )


def _load(conn, user) -> ProfileOut:
    h = conn.execute(
        text(
            "SELECT h.display_name, h.specialties, h.service_zips, h.is_available, "
            "h.verified_at, u.email, u.phone_e164, "
            "EXISTS (SELECT 1 FROM phone_verifications p WHERE p.user_id = u.id "
            " AND p.expires_at > now()) AS phone_pending "
            "FROM handymen h JOIN users u ON u.id = h.user_id WHERE h.user_id = :u"
        ),
        {"u": user["id"]},
    ).one()
    skills = [
        r[0]
        for r in conn.execute(
            text("SELECT category FROM handymen_skills WHERE handyman_id = :u ORDER BY category"),
            {"u": user["id"]},
        )
    ]
    return ProfileOut(
        display_name=h.display_name,
        email=h.email,
        phone=mask_phone(h.phone_e164),
        phone_pending=h.phone_pending,
        skills=skills,
        skill_options=SKILL_OPTIONS,
        specialties=list(h.specialties),
        service_zips=list(h.service_zips),
        is_available=h.is_available,
        status="APPROVED" if h.verified_at else "PENDING",
        complete=bool(skills and h.service_zips),
    )


@router.get("", response_model=ProfileOut)
def get_profile(user: Pro):
    with shared_engine().begin() as conn:
        _ensure_profile(conn, user)
        return _load(conn, user)


@router.put("", response_model=ProfileOut)
def save_profile(body: ProfileIn, user: Pro):
    """Replace the editable parts of the profile. Takes effect for the next job offer."""
    with shared_engine().begin() as conn:
        _ensure_profile(conn, user)
        conn.execute(
            text(
                "UPDATE handymen SET display_name = :n, specialties = :sp, service_zips = :z, "
                "is_available = :a WHERE user_id = :u"
            ),
            {
                "n": body.display_name,
                "sp": body.specialties,
                "z": body.service_zips,
                "a": body.is_available,
                "u": user["id"],
            },
        )
        conn.execute(text("DELETE FROM handymen_skills WHERE handyman_id = :u"), {"u": user["id"]})
        for category in body.skills:
            conn.execute(
                text("INSERT INTO handymen_skills (handyman_id, category) VALUES (:u, :c)"),
                {"u": user["id"], "c": category},
            )
        return _load(conn, user)


@router.post("/phone", response_model=PhoneStarted)
def start_phone_change(body: PhoneIn, user: Pro):
    phone = normalize_phone(body.phone)
    if phone is None:
        raise HTTPException(
            422, "Enter the phone number in international format, e.g. +16195550199"
        )
    code = f"{secrets.randbelow(10**6):06d}"
    with shared_engine().begin() as conn:
        taken = conn.execute(
            text("SELECT 1 FROM users WHERE phone_e164 = :p AND id <> :u"),
            {"p": phone, "u": user["id"]},
        ).first()
        if taken:
            raise HTTPException(409, "That phone number is already used by another account")
        recent = conn.execute(
            text(
                "SELECT 1 FROM phone_verifications WHERE user_id = :u "
                "AND created_at > now() - make_interval(secs => :s)"
            ),
            {"u": user["id"], "s": RESEND_SECONDS},
        ).first()
        if recent:
            raise HTTPException(429, "Please wait a moment before requesting another code")
        conn.execute(
            text(
                "INSERT INTO phone_verifications (user_id, phone_e164, code_hash, expires_at) "
                "VALUES (:u, :p, :h, now() + make_interval(mins => :m)) "
                "ON CONFLICT (user_id) DO UPDATE SET phone_e164 = EXCLUDED.phone_e164, "
                "code_hash = EXCLUDED.code_hash, attempts = 0, expires_at = EXCLUDED.expires_at, "
                "created_at = now()"
            ),
            {"u": user["id"], "p": phone, "h": _code_hash(user["id"], code), "m": CODE_TTL_MINUTES},
        )
    deliver([Outgoing(phone, f"Your Alche Home verification code is {code}")])
    return PhoneStarted(
        sent_to=mask_phone(phone) or "",
        expires_in_minutes=CODE_TTL_MINUTES,
        dev_code=code if get_settings().app_env == "local" else None,
    )


@router.post("/phone/verify", response_model=ProfileOut)
def verify_phone(body: CodeIn, user: Pro):
    wrong = False
    with shared_engine().begin() as conn:
        row = conn.execute(
            text(
                "SELECT phone_e164, code_hash, attempts, expires_at FROM phone_verifications "
                "WHERE user_id = :u FOR UPDATE"
            ),
            {"u": user["id"]},
        ).first()
        if row is None or row.expires_at < datetime.now(UTC):
            raise HTTPException(400, "That code has expired. Request a new one.")
        if row.attempts >= MAX_CODE_ATTEMPTS:
            raise HTTPException(429, "Too many wrong codes. Request a new one.")
        if _code_hash(user["id"], body.code.strip()) != row.code_hash:
            wrong = True
        else:
            taken = conn.execute(
                text("SELECT 1 FROM users WHERE phone_e164 = :p AND id <> :u"),
                {"p": row.phone_e164, "u": user["id"]},
            ).first()
            if taken:
                raise HTTPException(409, "That phone number is already used by another account")
            conn.execute(
                text("UPDATE users SET phone_e164 = :p, preferred_channel = 'SMS' WHERE id = :u"),
                {"p": row.phone_e164, "u": user["id"]},
            )
            conn.execute(
                text("DELETE FROM phone_verifications WHERE user_id = :u"), {"u": user["id"]}
            )
            return _load(conn, user)
    if wrong:  # a separate transaction, so the attempt is counted even though we answer 400
        with shared_engine().begin() as conn:
            conn.execute(
                text("UPDATE phone_verifications SET attempts = attempts + 1 WHERE user_id = :u"),
                {"u": user["id"]},
            )
        raise HTTPException(400, "That code is not right")


# ---------- ops: create, approve, invite ----------
class HandymanRow(BaseModel):
    handyman_id: str
    display_name: str
    email: str | None
    phone: str | None
    status: str
    complete: bool
    skills: list[str]
    service_zips: list[str]
    is_available: bool
    has_password: bool


class NewHandyman(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=200)
    display_name: str = Field(min_length=2, max_length=40)


class InviteOut(BaseModel):
    handyman_id: str
    invite_url: str


@admin_router.get("", response_model=list[HandymanRow])
def list_handymen():
    with shared_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT h.user_id, h.display_name, h.service_zips, h.is_available, h.verified_at, "
                "u.email, u.phone_e164, u.password_hash IS NOT NULL AS has_password, "
                "COALESCE((SELECT array_agg(s.category ORDER BY s.category) FROM handymen_skills s "
                " WHERE s.handyman_id = h.user_id), '{}') AS skills "
                "FROM handymen h JOIN users u ON u.id = h.user_id "
                "ORDER BY (h.verified_at IS NOT NULL), h.display_name"
            )
        ).all()
    return [
        HandymanRow(
            handyman_id=str(r.user_id),
            display_name=r.display_name,
            email=r.email,
            phone=mask_phone(r.phone_e164),
            status="APPROVED" if r.verified_at else "PENDING",
            complete=bool(r.skills and r.service_zips),
            skills=list(r.skills),
            service_zips=list(r.service_zips),
            is_available=r.is_available,
            has_password=r.has_password,
        )
        for r in rows
    ]


@admin_router.post("", response_model=InviteOut, status_code=201)
def add_handyman(body: NewHandyman):
    """Create a handyman account (pending approval) and a set-password link for them."""
    with shared_engine().begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM users WHERE email = :e"), {"e": body.email.lower()}
        ).first()
        if exists:
            raise HTTPException(409, "That email already has an account")
        uid = conn.execute(
            text(
                "INSERT INTO users (role, email, preferred_channel) "
                "VALUES ('HANDYMAN', :e, 'WEB') RETURNING id"
            ),
            {"e": body.email.lower()},
        ).scalar_one()
        conn.execute(
            text("INSERT INTO handymen (user_id, display_name) VALUES (:u, :n)"),
            {"u": uid, "n": " ".join(body.display_name.split())},
        )
        token = create_invite(conn, uid)
    return InviteOut(handyman_id=str(uid), invite_url=invite_url(token))


def _handyman_or_404(conn, handyman_id):
    row = conn.execute(
        text(
            "SELECT h.user_id, "
            "EXISTS (SELECT 1 FROM handymen_skills s "
            " WHERE s.handyman_id = h.user_id) AS has_skill, "
            "cardinality(h.service_zips) > 0 AS has_zip "
            "FROM handymen h WHERE h.user_id = :h"
        ),
        {"h": handyman_id},
    ).first()
    if row is None:
        raise HTTPException(404, "Handyman not found")
    return row


@admin_router.post("/{handyman_id}/invite", response_model=InviteOut)
def new_invite(handyman_id: uuid.UUID):
    with shared_engine().begin() as conn:
        _handyman_or_404(conn, handyman_id)
        token = create_invite(conn, handyman_id)
    return InviteOut(handyman_id=str(handyman_id), invite_url=invite_url(token))


@admin_router.post("/{handyman_id}/approve", response_model=dict)
def approve(handyman_id: uuid.UUID):
    with shared_engine().begin() as conn:
        row = _handyman_or_404(conn, handyman_id)
        if not (row.has_skill and row.has_zip):
            raise HTTPException(409, "The profile needs expertise and at least one ZIP code first")
        conn.execute(
            text(
                "UPDATE handymen SET verified_at = COALESCE(verified_at, now()) WHERE user_id = :h"
            ),
            {"h": handyman_id},
        )
    return {"status": "APPROVED"}


@admin_router.post("/{handyman_id}/suspend", response_model=dict)
def suspend(handyman_id: uuid.UUID):
    with shared_engine().begin() as conn:
        _handyman_or_404(conn, handyman_id)
        conn.execute(
            text("UPDATE handymen SET verified_at = NULL WHERE user_id = :h"), {"h": handyman_id}
        )
    return {"status": "PENDING"}
