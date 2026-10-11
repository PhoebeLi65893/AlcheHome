"""Create a set-password link for a handyman account (they then log in at /handyman.html).

Usage (inside the core-api container):
    python -m scripts.invite_handyman mike@example.com
The seeded handymen (python -m scripts.seed) are mike@example.com, sofia@example.com,
dan@example.com, aisha@example.com, carlos@example.com and priya@example.com.
"""

import hashlib
import os
import secrets
import sys

from sqlalchemy import text

from app.db import get_engine


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    email = sys.argv[1].lower()
    token = secrets.token_urlsafe(32)
    with get_engine().begin() as conn:
        uid = conn.execute(
            text("SELECT id FROM users WHERE email = :e AND role = 'HANDYMAN'"), {"e": email}
        ).scalar()
        if uid is None:
            sys.exit(f"No handyman account with email {email}.")
        conn.execute(
            text(
                "INSERT INTO invite_tokens (token_hash, user_id, expires_at) "
                "VALUES (:h, :u, now() + interval '7 days')"
            ),
            {"h": hashlib.sha256(token.encode()).hexdigest(), "u": uid},
        )
    base = (os.getenv("WEB_BASE_URL") or "http://localhost:3000").rstrip("/")
    print(f"Invite for {email} (valid for 7 days, works once):")
    print(f"{base}/handyman.html#invite={token}")


if __name__ == "__main__":
    main()
