"""In-memory TTL cache for BWS secrets.

Avoids shelling out to ``bws`` CLI on every request.  Writes
(create / edit / delete) invalidate the cache automatically.
"""

from __future__ import annotations

import threading
import time
from typing import Any


class BWSCache:
    """Thread-safe TTL cache for BWS list and get operations."""

    def __init__(self, ttl_seconds: float = 30.0) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()

        # list_secrets cache: (timestamp, full_list)
        self._list_ts: float = 0.0
        self._list_data: list[dict[str, Any]] = []

        # get_secret_by_id cache: {secret_id: (timestamp, parsed_value)}
        self._get_cache: dict[str, tuple[float, Any]] = {}

    # ------------------------------------------------------------------
    # List cache
    # ------------------------------------------------------------------

    def get_list(self) -> list[dict[str, Any]] | None:
        """Return cached secret list if still fresh, else None."""
        with self._lock:
            if self._list_data and (time.monotonic() - self._list_ts) < self._ttl:
                return self._list_data
            return None

    def set_list(self, data: list[dict[str, Any]]) -> None:
        """Store a fresh secret list."""
        with self._lock:
            self._list_ts = time.monotonic()
            self._list_data = data

    # ------------------------------------------------------------------
    # Per-secret value cache
    # ------------------------------------------------------------------

    def get_value(self, secret_id: str) -> Any | None:
        """Return cached secret value if still fresh, else None.

        Returns a sentinel ``_MISS`` to distinguish 'not cached' from
        a cached ``None`` value.
        """
        with self._lock:
            entry = self._get_cache.get(secret_id)
            if entry and (time.monotonic() - entry[0]) < self._ttl:
                return entry[1]
            return _MISS

    def set_value(self, secret_id: str, value: Any) -> None:
        """Store a fresh secret value."""
        with self._lock:
            self._get_cache[secret_id] = (time.monotonic(), value)

    # ------------------------------------------------------------------
    # Invalidation
    # ------------------------------------------------------------------

    def invalidate(self) -> None:
        """Clear all caches (called after any write operation)."""
        with self._lock:
            self._list_ts = 0.0
            self._list_data = []
            self._get_cache.clear()

    def invalidate_value(self, secret_id: str) -> None:
        """Remove a single secret from the value cache."""
        with self._lock:
            self._get_cache.pop(secret_id, None)


class _Miss:
    """Sentinel for cache miss (distinct from None)."""

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "<CACHE_MISS>"


_MISS = _Miss()


# Module-level singleton
_cache = BWSCache()


def get_cache() -> BWSCache:
    """Return the module-level BWS cache singleton."""
    return _cache
