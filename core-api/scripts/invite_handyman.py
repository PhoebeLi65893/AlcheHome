"""Create a set-password link for a handyman account (they then log in at /handyman.html).

Usage (inside the core-api container):
    python -m scripts.invite_handyman mike@example.com          # existing account
    python -m scripts.invite_handyman new@example.com "Sam T."  # new account, pending approval
Prefer the Handymen section of the ops page (/admin.html), which does the same.
"""

import sys

from sqlalchemy import text

from app.db import get_engine
from app.profile import create_invite, invite_url


def main() -> None:
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    email = sys.argv[1].lower()
    with get_engine().begin() as conn:
        uid = conn.execute(
            text("SELECT id FROM users WHERE email = :e AND role = 'HANDYMAN'"), {"e": email}
        ).scalar()
        if uid is None:
            if len(sys.argv) != 3:
                sys.exit(
                    f"No handyman account with email {email}. Add a display name to create one."
                )
            if conn.execute(text("SELECT 1 FROM users WHERE email = :e"), {"e": email}).first():
                sys.exit(f"{email} already belongs to a non-handyman account.")
            uid = conn.execute(
                text("INSERT INTO users (role, email) VALUES ('HANDYMAN', :e) RETURNING id"),
                {"e": email},
            ).scalar_one()
            conn.execute(
                text("INSERT INTO handymen (user_id, display_name) VALUES (:u, :n)"),
                {"u": uid, "n": " ".join(sys.argv[2].split())},
            )
        token = create_invite(conn, uid)
    print(f"Invite for {email} (valid for 7 days, works once):")
    print(invite_url(token))


if __name__ == "__main__":
    main()
