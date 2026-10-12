"""Small per-client request limits for a publicly reachable test deployment.

Counted in memory per instance, which is enough to stop casual abuse of the sign-up, login,
chat (each AI reply costs money) and phone-code endpoints. Disabled for local development,
where tests and demos make many quick calls. T22 adds the real edge protection.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.config import get_settings

_hits: dict[tuple[str, str], deque] = defaultdict(deque)
_lock = threading.Lock()
_MAX_KEYS = 20000


def client_ip(request: Request) -> str:
    """The caller's address; behind Cloud Run the first X-Forwarded-For entry."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def reset() -> None:
    with _lock:
        _hits.clear()


def limit(name: str, max_calls: int, window_seconds: int):
    """A FastAPI dependency: at most `max_calls` per client per window, then 429."""

    def check(request: Request) -> None:
        if get_settings().app_env == "local":
            return
        key = (name, client_ip(request))
        now = time.monotonic()
        with _lock:
            if len(_hits) > _MAX_KEYS:  # forget clients that have gone quiet
                for k in [k for k, q in _hits.items() if not q or q[-1] < now - window_seconds]:
                    del _hits[k]
            q = _hits[key]
            while q and q[0] <= now - window_seconds:
                q.popleft()
            if len(q) >= max_calls:
                raise HTTPException(
                    429,
                    "Too many requests. Please try again in a few minutes.",
                    headers={"Retry-After": str(window_seconds)},
                )
            q.append(now)

    return check
