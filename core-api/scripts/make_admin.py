"""Make an existing user an ADMIN (so they can open the ops page).

Usage (inside the core-api container):
    python -m scripts.make_admin you@example.com
Register that email in the web app first. Use --revoke to turn it back into a CUSTOMER.
"""

import sys

from sqlalchemy import text

from app.db import get_engine


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    role = "CUSTOMER" if "--revoke" in sys.argv else "ADMIN"
    with get_engine().begin() as conn:
        n = conn.execute(
            text("UPDATE users SET role = :r WHERE email = :e AND role IN ('CUSTOMER','ADMIN')"),
            {"r": role, "e": args[0].lower()},
        ).rowcount
    if not n:
        sys.exit(f"No customer account with email {args[0]}. Register it in the web app first.")
    print(f"{args[0]} is now {role}")


if __name__ == "__main__":
    main()
