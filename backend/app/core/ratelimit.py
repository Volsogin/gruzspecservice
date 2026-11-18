"""In-process sliding-window rate limiter.

Good enough for a single API instance (our deployment). With several replicas this
should move to Redis — the interface stays the same (see ARCHITECTURE.md).
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable

from app.core.errors import RateLimited


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic, enabled: bool = True) -> None:
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self.enabled = enabled

    def hit(self, key: str, limit: int, window_seconds: float, message: str | None = None) -> None:
        """Register a hit for `key`; raise RateLimited if the window is already full."""
        if not self.enabled or limit <= 0:
            return
        now = self._clock()
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and bucket[0] <= now - window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, math.ceil(bucket[0] + window_seconds - now))
                raise RateLimited(
                    message or "Слишком много запросов. Попробуйте позже или позвоните нам.",
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.append(now)
            if len(self._hits) > 50_000:  # crude memory guard
                self._evict(now, window_seconds)

    def _evict(self, now: float, window_seconds: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= now - window_seconds]:
            del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
