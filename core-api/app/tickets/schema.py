"""The create_repair_ticket tool: what Gemini may send, and how it is checked."""

import re
from enum import StrEnum

from pydantic import BaseModel, ValidationError, field_validator


class Category(StrEnum):
    PLUMBING = "PLUMBING"
    ELECTRICAL = "ELECTRICAL"
    HVAC = "HVAC"
    CARPENTRY = "CARPENTRY"
    APPLIANCE = "APPLIANCE"
    GENERAL = "GENERAL"


class Urgency(StrEnum):
    EMERGENCY = "EMERGENCY"
    SAME_DAY = "SAME_DAY"
    FLEXIBLE = "FLEXIBLE"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    EMERGENCY = "EMERGENCY"


TOOL_NAME = "create_repair_ticket"

TOOL_DECLARATION = {
    "name": TOOL_NAME,
    "description": (
        "Create a repair request so Alche Home can find a handyman. Call it only after the "
        "customer has confirmed they want a handyman and you know the category, a clear "
        "summary, the urgency and their 5-digit US ZIP code."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "category": {"type": "STRING", "enum": [c.value for c in Category]},
            "issue_summary": {
                "type": "STRING",
                "description": (
                    "One or two sentences a handyman can act on: what, where, since when."
                ),
            },
            "urgency": {
                "type": "STRING",
                "enum": [u.value for u in Urgency],
                "description": "EMERGENCY = now, SAME_DAY = today, FLEXIBLE = within days.",
            },
            "location_zip": {"type": "STRING", "description": "5-digit US ZIP code."},
            "severity": {
                "type": "STRING",
                "enum": [s.value for s in Severity],
                "description": "Your severity estimate, especially after seeing photos.",
            },
        },
        "required": ["category", "issue_summary", "urgency", "location_zip"],
    },
}

FIELD_NAMES = {
    "category": "the type of repair",
    "issue_summary": "a short description of the problem",
    "urgency": "how urgent it is",
    "location_zip": "a valid 5-digit ZIP code",
    "severity": "a severity level",
}


class TicketDraft(BaseModel):
    category: Category
    issue_summary: str
    urgency: Urgency
    location_zip: str
    severity: Severity | None = None

    @field_validator("category", "urgency", "severity", mode="before")
    @classmethod
    def upper(cls, v):
        return v.strip().upper().replace("-", "_").replace(" ", "_") if isinstance(v, str) else v

    @field_validator("issue_summary")
    @classmethod
    def summary_length(cls, v: str) -> str:
        v = " ".join(v.split())
        if not 10 <= len(v) <= 500:
            raise ValueError("summary must be 10-500 characters")
        return v

    @field_validator("location_zip", mode="before")
    @classmethod
    def zip_code(cls, v):
        v = str(v).strip()
        if not re.fullmatch(r"\d{5}", v):
            raise ValueError("ZIP must be 5 digits")
        return v


def validate_draft(args: dict) -> tuple[TicketDraft | None, list[str]]:
    """Return (draft, []) when valid, or (None, [problem fields in plain words])."""
    try:
        return TicketDraft.model_validate(args or {}), []
    except ValidationError as e:
        fields = []
        for err in e.errors():
            name = str(err["loc"][0]) if err["loc"] else "details"
            label = FIELD_NAMES.get(name, name)
            if label not in fields:
                fields.append(label)
        return None, fields
