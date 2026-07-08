"""Tiny in-process rate limiter.

Single-user app, single process — no Redis, no per-IP bookkeeping. A fixed
window per named bucket is enough to (a) blunt password brute-force on
``/api/login`` and (b) stop a runaway client from hammering ``POST /api/sync``
into a Garmin lockout. Used as a FastAPI dependency via ``rate_limiter(...)``.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import HTTPException


class RateLimiter:
    """Fixed-window limiter: at most ``max_calls`` per ``window_s`` per bucket key."""

    def __init__(self, max_calls: int, window_s: float) -> None:
        self._max = max_calls
        self._window = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def retry_after(self, key: str = "global", *, now: float | None = None) -> float | None:
        """Register a call. Returns None if allowed, else seconds until the next slot."""
        current = now if now is not None else time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and current - hits[0] >= self._window:
                hits.popleft()
            if len(hits) >= self._max:
                return round(self._window - (current - hits[0]), 1)
            hits.append(current)
            return None


def rate_limiter(limiter: RateLimiter, key: str = "global") -> Callable[[], None]:
    """Build a FastAPI dependency that 429s (with Retry-After) when over budget."""

    def dependency() -> None:
        wait = limiter.retry_after(key)
        if wait is not None:
            raise HTTPException(
                status_code=429,
                detail="Too many requests; slow down.",
                headers={"Retry-After": str(int(wait) + 1)},
            )

    return dependency
