"""Handyman matching: filter by skill, ZIP coverage and availability, then score and rank.

Score = 0.4*proximity + 0.3*rating + 0.2*response_rate + 0.1*urgency_fit (each part is 0..1).
- proximity: 1.0 when the ticket ZIP is the handyman's first (home) ZIP, falling linearly to 0.5
  for the last ZIP they cover. (service_zips is stored home-first.)
- rating: rating_avg / 5.
- response_rate: stored 0..1 value.
- urgency_fit: FLEXIBLE 1.0, SAME_DAY 0.5 + 0.5*response_rate, EMERGENCY response_rate
  (fast responders matter most when it is urgent).
"""

from dataclasses import dataclass

from sqlalchemy import text

WEIGHTS = {"proximity": 0.4, "rating": 0.3, "response_rate": 0.2, "urgency_fit": 0.1}


@dataclass(frozen=True)
class Candidate:
    handyman_id: str
    display_name: str
    service_zips: list[str]
    rating_avg: float
    response_rate: float


@dataclass(frozen=True)
class Ranked:
    candidate: Candidate
    score: float
    parts: dict[str, float]


def proximity(zips: list[str], zip_code: str) -> float:
    if zip_code not in zips:
        return 0.0
    if len(zips) == 1:
        return 1.0
    return 1.0 - 0.5 * zips.index(zip_code) / (len(zips) - 1)


def urgency_fit(urgency: str, response_rate: float) -> float:
    if urgency == "EMERGENCY":
        return response_rate
    if urgency == "SAME_DAY":
        return 0.5 + 0.5 * response_rate
    return 1.0


def score(c: Candidate, urgency: str, zip_code: str) -> Ranked:
    parts = {
        "proximity": proximity(c.service_zips, zip_code),
        "rating": min(max(c.rating_avg / 5, 0.0), 1.0),
        "response_rate": min(max(c.response_rate, 0.0), 1.0),
        "urgency_fit": urgency_fit(urgency, c.response_rate),
    }
    total = sum(WEIGHTS[k] * v for k, v in parts.items())
    return Ranked(c, round(total, 4), parts)


def rank(candidates: list[Candidate], urgency: str, zip_code: str) -> list[Ranked]:
    """Score eligible candidates (ZIP covered) and sort best first; ties break by name."""
    scored = [score(c, urgency, zip_code) for c in candidates if zip_code in c.service_zips]
    return sorted(scored, key=lambda r: (-r.score, r.candidate.display_name))


def find_candidates(conn, category: str, zip_code: str) -> list[Candidate]:
    """Verified, available, not opted-out handymen with the skill who cover the ZIP."""
    rows = conn.execute(
        text(
            "SELECT h.user_id, h.display_name, h.service_zips, h.rating_avg, h.response_rate "
            "FROM handymen h JOIN handymen_skills s ON s.handyman_id = h.user_id "
            "JOIN users u ON u.id = h.user_id "
            "WHERE s.category = :c AND :z = ANY(h.service_zips) "
            "AND h.is_available AND h.verified_at IS NOT NULL AND NOT u.sms_opted_out"
        ),
        {"c": category, "z": zip_code},
    ).all()
    return [
        Candidate(
            str(r.user_id),
            r.display_name,
            list(r.service_zips),
            float(r.rating_avg),
            float(r.response_rate),
        )
        for r in rows
    ]


def rank_for_ticket(conn, ticket_number: int) -> tuple[dict, list[Ranked]] | None:
    t = (
        conn.execute(
            text(
                "SELECT ticket_number, category, urgency, location_zip, status, issue_summary "
                "FROM tickets WHERE ticket_number = :n"
            ),
            {"n": ticket_number},
        )
        .mappings()
        .first()
    )
    if t is None:
        return None
    candidates = find_candidates(conn, t["category"], t["location_zip"])
    return dict(t), rank(candidates, t["urgency"], t["location_zip"])
