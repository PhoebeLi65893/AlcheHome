"""Admin tool: print the ranked handyman list for a ticket (read-only).

Usage (inside the core-api container):
    python -m scripts.rank_handymen 1024
"""

import sys

from app.db import get_engine
from app.matching import rank_for_ticket


def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1].lstrip("#").isdigit():
        sys.exit(__doc__)
    number = int(sys.argv[1].lstrip("#"))
    with get_engine().connect() as conn:
        found = rank_for_ticket(conn, number)
    if found is None:
        sys.exit(f"No ticket #{number}.")
    t, ranked = found
    print(
        f"Ticket #{t['ticket_number']} [{t['status']}] {t['category']} / {t['urgency']} "
        f"/ ZIP {t['location_zip']}: {t['issue_summary']}"
    )
    if not ranked:
        print("\nNo eligible handymen (would be UNMATCHED).")
        return
    print(f"\n{'#':<3}{'Handyman':<12}{'Score':>7}{'Prox':>7}{'Rating':>8}{'Resp':>7}{'Urg':>7}")
    for i, r in enumerate(ranked, 1):
        p = r.parts
        print(
            f"{i:<3}{r.candidate.display_name:<12}{r.score:>7.3f}{p['proximity']:>7.2f}"
            f"{p['rating']:>8.2f}{p['response_rate']:>7.2f}{p['urgency_fit']:>7.2f}"
        )


if __name__ == "__main__":
    main()
