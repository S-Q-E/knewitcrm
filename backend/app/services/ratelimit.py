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


class LoginRateLimiter:
    """In-memory sliding-window limiter for failed logins.

    Two buckets: (ip, email) stops credential stuffing against one account
    from one source, email-only stops distributed guessing across many IPs
    (e.g. rotating a spoofed X-Forwarded-For). A success resets both.
    Single-container deployment (see D9), so a process-local store is
    sufficient; entries older than the window are pruned on access.
    """

    def __init__(
        self,
        max_attempts: int = 5,
        window_seconds: int = 600,
        email_max_attempts: int = 20,
        email_window_seconds: int = 600,
    ) -> None:
        self._max_attempts = max_attempts
        self._window = window_seconds
        self._email_max_attempts = email_max_attempts
        self._email_window = email_window_seconds
        self._failures: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._email_failures: dict[str, list[float]] = defaultdict(list)

    @staticmethod
    def _kept(stamps: list[float], now: float, window: float) -> list[float]:
        return [ts for ts in stamps if now - ts < window]

    def _prune(self, key: tuple[str, str], now: float) -> list[float]:
        kept = self._kept(self._failures[key], now, self._window)
        if kept:
            self._failures[key] = kept
        else:
            self._failures.pop(key, None)
        return kept

    def _prune_email(self, email: str, now: float) -> list[float]:
        kept = self._kept(self._email_failures[email], now, self._email_window)
        if kept:
            self._email_failures[email] = kept
        else:
            self._email_failures.pop(email, None)
        return kept

    def is_blocked(self, ip: str, email: str) -> bool:
        now = time.monotonic()
        if len(self._prune((ip, email), now)) >= self._max_attempts:
            return True
        return len(self._prune_email(email, now)) >= self._email_max_attempts

    def record_failure(self, ip: str, email: str) -> None:
        now = time.monotonic()
        key = (ip, email)
        kept = self._kept(self._failures.get(key, []), now, self._window)
        kept.append(now)
        self._failures[key] = kept
        email_kept = self._kept(self._email_failures.get(email, []), now, self._email_window)
        email_kept.append(now)
        self._email_failures[email] = email_kept

    def record_success(self, ip: str, email: str) -> None:
        self._failures.pop((ip, email), None)
        self._email_failures.pop(email, None)

    def clear(self) -> None:
        self._failures.clear()
        self._email_failures.clear()


login_limiter = LoginRateLimiter()
# Step 14: shared buckets for the API-wide middleware (per IP) and the
# manager-send endpoint (per user). Limits come from Settings; the singletons
# below only hold state, so tests can reconfigure freely.
api_limiter = SlidingWindowLimiter()
send_limiter = SlidingWindowLimiter()


def clear_all_limiters() -> None:
    login_limiter.clear()
    api_limiter.clear()
    send_limiter.clear()
