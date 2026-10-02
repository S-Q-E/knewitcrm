from __future__ import annotations

import time
from collections import defaultdict


class SlidingWindowLimiter:
    """Generic in-memory sliding-window limiter (single-container, see D9).

    Counts hits per key inside a rolling window. ``check`` records a hit and
    reports whether the key is still within budget; ``retry_after`` tells a
    rejected caller how long to wait. Entries older than the window are
    pruned on access.
    """

    def __init__(self, max_hits: int = 600, window_seconds: int = 60) -> None:
        self._max_hits = max_hits
        self._window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str, max_hits: int | None = None, window: float | None = None) -> bool:
        """Record a hit; True when the key is still within budget.

        Limits come from the caller (per-app Settings) so one process can
        serve apps with different budgets, e.g. in tests.
        """
        limit = self._max_hits if max_hits is None else max_hits
        span = float(self._window) if window is None else window
        now = time.monotonic()
        kept = [ts for ts in self._hits.get(key, []) if now - ts < span]
        kept.append(now)
        self._hits[key] = kept
        return len(kept) <= limit

    def retry_after(self, key: str, window: float | None = None) -> int:
        span = float(self._window) if window is None else window
        now = time.monotonic()
        kept = [ts for ts in self._hits.get(key, []) if now - ts < span]
        if kept:
            self._hits[key] = kept
        else:
            self._hits.pop(key, None)
        if not kept:
            return 0
        return max(0, int(span - (now - kept[0])) + 1)

    def clear(self) -> None:
        self._hits.clear()


# NOTE (Step 16a): the in-memory LoginRateLimiter lived here until the
# failure budget moved to crm_login_attempts (services/login_limits.py).
# SlidingWindowLimiter above still backs the API-wide and send limiters.
# Step 14: shared buckets for the API-wide middleware (per IP) and the
# manager-send endpoint (per user). Limits come from Settings; the singletons
# below only hold state, so tests can reconfigure freely.
# NOTE (Step 16a): failed-login counting moved to the DB table
# crm_login_attempts (services/login_limits.py) so the budget is shared
# across uvicorn workers; nothing login-related stays in process memory.
api_limiter = SlidingWindowLimiter()
send_limiter = SlidingWindowLimiter()


def clear_all_limiters() -> None:
    api_limiter.clear()
    send_limiter.clear()
