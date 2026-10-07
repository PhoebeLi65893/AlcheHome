import os
import uuid

import pytest
from sqlalchemy import text

from app.db import get_engine
from app.matching import Candidate, find_candidates, proximity, rank, rank_for_ticket, urgency_fit


def cand(name, zips, rating=4.0, rate=0.5):
    return Candidate(name, name, zips, rating, rate)


def test_proximity_home_zip_best_last_zip_half():
    assert proximity(["1", "2", "3"], "1") == 1.0
    assert proximity(["1", "2", "3"], "2") == 0.75
    assert proximity(["1", "2", "3"], "3") == 0.5
    assert proximity(["1"], "1") == 1.0
    assert proximity(["1"], "9") == 0.0


def test_urgency_fit():
    assert urgency_fit("FLEXIBLE", 0.2) == 1.0
    assert urgency_fit("SAME_DAY", 0.8) == pytest.approx(0.9)
    assert urgency_fit("EMERGENCY", 0.8) == 0.8


def test_weights_exact_score():
    r = rank([cand("A", ["92101"], rating=5.0, rate=1.0)], "SAME_DAY", "92101")[0]
    assert r.score == 1.0
    r = rank([cand("B", ["92101", "92102"], rating=4.0, rate=0.5)], "FLEXIBLE", "92102")[0]
    # 0.4*0.5 + 0.3*0.8 + 0.2*0.5 + 0.1*1.0
    assert r.score == pytest.approx(0.64)


def test_rank_excludes_uncovered_and_sorts_best_first_with_stable_ties():
    out = rank(
        [
            cand("Zed", ["92101"], 4.0, 0.5),
            cand("Out", ["92109"], 5.0, 1.0),
            cand("Best", ["92101"], 5.0, 1.0),
            cand("Amy", ["92101"], 4.0, 0.5),
        ],
        "FLEXIBLE",
        "92101",
    )
    assert [r.candidate.display_name for r in out] == ["Best", "Amy", "Zed"]


def test_emergency_prefers_fast_responder_over_slightly_better_rated():
    out = rank(
        [cand("Fast", ["92101"], 4.4, 1.0), cand("Slow", ["92101"], 4.6, 0.3)],
        "EMERGENCY",
        "92101",
    )
    assert out[0].candidate.display_name == "Fast"


db = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set")


@pytest.fixture
def conn():
    with get_engine().connect() as c:
        yield c
        c.rollback()  # leave no rows behind


def add_handyman(c, name, zips, skills, rating=4.0, rate=0.5, available=True, verified=True):
    uid = c.execute(
        text("INSERT INTO users (role, email) VALUES ('HANDYMAN', :e) RETURNING id"),
        {"e": f"{uuid.uuid4().hex}@example.com"},
    ).scalar_one()
    c.execute(
        text(
            "INSERT INTO handymen (user_id, display_name, service_zips, rating_avg, "
            "response_rate, is_available, verified_at) VALUES (:u, :n, :z, :r, :rr, :a, "
            "CASE WHEN :v THEN now() END)"
        ),
        {"u": uid, "n": name, "z": zips, "r": rating, "rr": rate, "a": available, "v": verified},
    )
    for s in skills:
        c.execute(text("INSERT INTO handymen_skills VALUES (:u, :c)"), {"u": uid, "c": s})


@db
def test_find_candidates_filters_skill_zip_availability_verification(conn):
    z = "99901"
    add_handyman(conn, "Ok", [z], ["PLUMBING"])
    add_handyman(conn, "WrongSkill", [z], ["HVAC"])
    add_handyman(conn, "WrongZip", ["99902"], ["PLUMBING"])
    add_handyman(conn, "Busy", [z], ["PLUMBING"], available=False)
    add_handyman(conn, "Unverified", [z], ["PLUMBING"], verified=False)
    found = find_candidates(conn, "PLUMBING", z)
    assert [c.display_name for c in found] == ["Ok"]


@db
def test_rank_for_ticket_and_unknown_ticket(conn):
    z = "99903"
    add_handyman(conn, "Low", [z], ["PLUMBING"], rating=3.0, rate=0.4)
    add_handyman(conn, "High", [z], ["PLUMBING"], rating=4.9, rate=0.9)
    cust = conn.execute(
        text("INSERT INTO users (role, email) VALUES ('CUSTOMER', :e) RETURNING id"),
        {"e": f"{uuid.uuid4().hex}@example.com"},
    ).scalar_one()
    n = conn.execute(
        text(
            "INSERT INTO tickets (customer_id, category, issue_summary, urgency, location_zip, "
            "status) VALUES (:c, 'PLUMBING', 'Leaking pipe under sink', 'SAME_DAY', :z, 'OPEN') "
            "RETURNING ticket_number"
        ),
        {"c": cust, "z": z},
    ).scalar_one()
    ticket, ranked = rank_for_ticket(conn, n)
    assert ticket["location_zip"] == z
    assert [r.candidate.display_name for r in ranked] == ["High", "Low"]
    assert rank_for_ticket(conn, 999999999) is None
