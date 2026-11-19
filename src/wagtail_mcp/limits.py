"""Request size and per-token rate limits for the MCP endpoint.

Both limits are opt-in (see ``WAGTAIL_MCP`` in docs/configuration.md) so
existing deployments behave as before until a project sets them.
"""

import hashlib
import threading
import time

from collections import deque


def token_key(token: str | None) -> str:
    """Return a stable, non-reversible key for ``token`` (never the secret)."""
    if token is None:
        return "anonymous"
    return hashlib.sha256(token.encode()).hexdigest()


def content_length(request) -> int:
    """Return the declared request body size in bytes (0 when absent or invalid)."""
    try:
        return max(int(request.META.get("CONTENT_LENGTH") or 0), 0)
    except (TypeError, ValueError):
        return 0


class SlidingWindowRateLimiter:
    """In-process sliding-window counter, keyed by an opaque string.

    State is per process: with several workers each one enforces the limit on
    its own, so the effective ceiling is ``limit`` times the worker count.
    """

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: dict[str, deque] = {}

    def hit(self, key: str, limit: int, window: float) -> float:
        """Record a request. Return 0 if allowed, else seconds until a retry works."""
        now = self._clock()
        cutoff = now - window
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return max(hits[0] + window - now, 0.001)
            hits.append(now)
            self._prune(cutoff)
            return 0

    def _prune(self, cutoff: float) -> None:
        """Drop keys with no recent hits so the table cannot grow without bound."""
        stale = [
            key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff
        ]
        for key in stale:
            del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = SlidingWindowRateLimiter()
