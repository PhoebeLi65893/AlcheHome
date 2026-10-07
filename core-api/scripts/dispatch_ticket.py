"""Admin tool: start dispatch for a ticket (OPEN or UNMATCHED) and show its offers.

Usage (inside the core-api container):
    python -m scripts.dispatch_ticket 1024
"""

import sys

from sqlalchemy import text

from app.db import get_engine
from app.dispatch import start_dispatch


def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1].lstrip("#").isdigit():
        sys.exit(__doc__)
    number = int(sys.argv[1].lstrip("#"))
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT id, status FROM tickets WHERE ticket_number = :n"), {"n": number}
        ).first()
    if row is None:
        sys.exit(f"No ticket #{number}.")
    if not start_dispatch(row.id):
        sys.exit(
            f"Ticket #{number} is {row.status}; only OPEN or UNMATCHED tickets can be dispatched."
        )
    with get_engine().connect() as conn:
        for o in conn.execute(
            text(
                "SELECT h.display_name, o.status, o.expires_at, o.message FROM dispatch_offers o "
                "JOIN handymen h ON h.user_id = o.handyman_id "
                "WHERE o.ticket_id = :t ORDER BY o.sent_at"
            ),
            {"t": row.id},
        ):
            print(f"Offer to {o.display_name} [{o.status}] expires {o.expires_at:%H:%M:%S}")
            print(f"  SMS: {o.message}")


if __name__ == "__main__":
    main()
