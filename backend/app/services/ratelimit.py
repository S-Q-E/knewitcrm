from __future__ import annotations

import time
from collections import defaultdict


class LoginRateLimiter:
    """In-memory sliding-window limiter for failed logins.

    Keyed by (ip, email). Single-container deployment (see D9), so a
    process-local store is sufficient; entries older than the window
    are pruned on access.
    """

    def __init__(self, max_attempts: int = 5, window_seconds: int = 600) -> None:
        self._max_attempts = max_attempts
        self._window = window_seconds
        self._failures: dict[tuple[str, str], list[float]] = defaultdict(list)

    def _prune(self, key: tuple[str, str], now: float) -> list[float]:
        kept = [ts for ts in self._failures[key] if now - ts < self._window]
        if kept:
            self._failures[key] = kept
        else:
            self._failures.pop(key, None)
        return kept

    def is_blocked(self, ip: str, email: str) -> bool:
        return len(self._prune((ip, email), time.monotonic())) >= self._max_attempts

    def record_failure(self, ip: str, email: str) -> None:
        now = time.monotonic()
        key = (ip, email)
        kept = [ts for ts in self._failures.get(key, []) if now - ts < self._window]
        kept.append(now)
        self._failures[key] = kept

    def record_success(self, ip: str, email: str) -> None:
        self._failures.pop((ip, email), None)

    def clear(self) -> None:
        self._failures.clear()


login_limiter = LoginRateLimiter()
