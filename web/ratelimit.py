"""In-memory sliding-window rate limiter keyed by client address."""

import threading
import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Record a hit and return True while the key is within its limit."""
        now = self.clock()
        with self._lock:
            self._prune(now)
            hits = self._hits.setdefault(key, deque())
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def retry_after(self, key: str) -> int:
        """Whole seconds until the oldest hit leaves the window."""
        now = self.clock()
        with self._lock:
            hits = self._hits.get(key)
            if not hits:
                return 0
            return max(1, int(hits[0] + self.window - now) + 1)

    def _prune(self, now: float) -> None:
        for key in [k for k, hits in self._hits.items() if hits[-1] <= now - self.window]:
            del self._hits[key]
        for hits in self._hits.values():
            while hits and hits[0] <= now - self.window:
                hits.popleft()
