"""Idempotent seed: sample handymen in San Diego. Run: python -m scripts.seed"""

from sqlalchemy import text

from app.db import get_engine

HANDYMEN = [
    (
        "mike@example.com",
        "+16195550101",
        "Mike R.",
        ["92101", "92102", "92103"],
        4.8,
        0.95,
        ["PLUMBING", "GENERAL"],
    ),
    (
        "sofia@example.com",
        "+16195550102",
        "Sofia L.",
        ["92104", "92105", "92116"],
        4.6,
        0.90,
        ["ELECTRICAL"],
    ),
    (
        "dan@example.com",
        "+16195550103",
        "Dan K.",
        ["92101", "92109", "92110"],
        4.2,
        0.80,
        ["HVAC", "APPLIANCE"],
    ),
    (
        "aisha@example.com",
        "+16195550104",
        "Aisha T.",
        ["92103", "92108", "92116"],
        4.9,
        0.98,
        ["CARPENTRY", "GENERAL"],
    ),
    (
        "carlos@example.com",
        "+16195550105",
        "Carlos M.",
        ["92101", "92102", "92113"],
        4.4,
        0.70,
        ["PLUMBING", "APPLIANCE"],
    ),
    (
        "priya@example.com",
        "+16195550106",
        "Priya S.",
        ["92109", "92110", "92117"],
        4.7,
        0.92,
        ["ELECTRICAL", "HVAC"],
    ),
]


def main() -> None:
    with get_engine().begin() as conn:
        for email, phone, name, zips, rating, rate, skills in HANDYMEN:
            uid = conn.execute(
                text(
                    "INSERT INTO users (role, email, phone_e164, preferred_channel) "
                    "VALUES ('HANDYMAN', :e, :p, 'SMS') "
                    "ON CONFLICT (email) DO UPDATE SET phone_e164 = EXCLUDED.phone_e164 "
                    "RETURNING id"
                ),
                {"e": email, "p": phone},
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO handymen (user_id, display_name, service_zips, rating_avg, "
                    "response_rate, verified_at) VALUES (:u, :n, :z, :r, :rr, now()) "
                    "ON CONFLICT (user_id) DO UPDATE SET display_name = EXCLUDED.display_name, "
                    "service_zips = EXCLUDED.service_zips, rating_avg = EXCLUDED.rating_avg, "
                    "response_rate = EXCLUDED.response_rate"
                ),
                {"u": uid, "n": name, "z": zips, "r": rating, "rr": rate},
            )
            for skill in skills:
                conn.execute(
                    text(
                        "INSERT INTO handymen_skills (handyman_id, category) VALUES (:u, :c) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {"u": uid, "c": skill},
                )
    print(f"Seeded {len(HANDYMEN)} handymen")


if __name__ == "__main__":
    main()
