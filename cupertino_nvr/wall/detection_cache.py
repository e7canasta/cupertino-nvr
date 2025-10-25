"""
Detection Cache
===============

Thread-safe cache for detection events with TTL (Time-To-Live).
"""

from datetime import datetime, timedelta
from threading import Lock
from typing import Dict, Optional, Tuple

from cupertino_nvr.events.schema import DetectionEvent


class DetectionCache:
    """
    Thread-safe cache for detection events with TTL.

    Stores detection events by source_id and automatically expires
    old events based on TTL. Safe for concurrent access from multiple threads.

    Args:
        ttl_seconds: Time-to-live for cached events in seconds

    Example:
        >>> cache = DetectionCache(ttl_seconds=1.0)
        >>> cache.update(event)  # Store event
        >>> event = cache.get(source_id=0)  # Retrieve event
        >>> if event is None:
        ...     print("Event expired or not found")
    """

    def __init__(self, ttl_seconds: float = 1.0):
        self._cache: Dict[int, Tuple[DetectionEvent, datetime]] = {}
        self._lock = Lock()
        self._ttl = timedelta(seconds=ttl_seconds)

    def update(self, event: DetectionEvent) -> None:
        """
        Update cache with new event.

        Args:
            event: DetectionEvent to cache
        """
        with self._lock:
            self._cache[event.source_id] = (event, datetime.now())

    def get(self, source_id: int) -> Optional[DetectionEvent]:
        """
        Get event for source, None if expired or missing.

        Args:
            source_id: Stream source ID

        Returns:
            DetectionEvent if found and not expired, None otherwise
        """
        with self._lock:
            if source_id not in self._cache:
                return None

            event, timestamp = self._cache[source_id]

            # Check if expired
            if datetime.now() - timestamp > self._ttl:
                del self._cache[source_id]
                return None

            return event

    def clear(self) -> None:
        """Clear all cached events"""
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        """Get number of cached events"""
        with self._lock:
            return len(self._cache)

