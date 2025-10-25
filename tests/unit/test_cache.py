"""
Unit tests for detection cache
"""

import time
from datetime import datetime

import pytest

from cupertino_nvr.events import BoundingBox, Detection, DetectionEvent
from cupertino_nvr.wall import DetectionCache


class TestDetectionCache:
    def test_cache_update_and_get(self):
        cache = DetectionCache(ttl_seconds=1.0)

        # Create test event
        event = DetectionEvent(
            source_id=0,
            frame_id=123,
            timestamp=datetime.now(),
            model_id="yolov8x-640",
            inference_time_ms=45.2,
            detections=[
                Detection(
                    class_name="person",
                    confidence=0.92,
                    bbox=BoundingBox(x=100, y=150, width=80, height=200),
                )
            ],
        )

        # Update cache
        cache.update(event)

        # Retrieve event
        retrieved = cache.get(0)
        assert retrieved is not None
        assert retrieved.source_id == 0
        assert retrieved.frame_id == 123

    def test_cache_ttl_expiration(self):
        cache = DetectionCache(ttl_seconds=0.1)  # 100ms TTL

        event = DetectionEvent(
            source_id=0,
            frame_id=123,
            timestamp=datetime.now(),
            model_id="yolov8x-640",
            inference_time_ms=45.2,
            detections=[],
        )

        # Update cache
        cache.update(event)

        # Event should be available immediately
        assert cache.get(0) is not None

        # Wait for TTL to expire
        time.sleep(0.2)

        # Event should be expired
        assert cache.get(0) is None

    def test_cache_multiple_sources(self):
        cache = DetectionCache(ttl_seconds=1.0)

        # Create events for different sources
        event0 = DetectionEvent(
            source_id=0,
            frame_id=100,
            timestamp=datetime.now(),
            model_id="yolov8x-640",
            inference_time_ms=45.2,
            detections=[],
        )

        event1 = DetectionEvent(
            source_id=1,
            frame_id=200,
            timestamp=datetime.now(),
            model_id="yolov8x-640",
            inference_time_ms=45.2,
            detections=[],
        )

        # Update cache
        cache.update(event0)
        cache.update(event1)

        # Retrieve events
        retrieved0 = cache.get(0)
        retrieved1 = cache.get(1)

        assert retrieved0 is not None
        assert retrieved0.frame_id == 100

        assert retrieved1 is not None
        assert retrieved1.frame_id == 200

    def test_cache_update_overwrites(self):
        cache = DetectionCache(ttl_seconds=1.0)

        # Create first event
        event1 = DetectionEvent(
            source_id=0,
            frame_id=100,
            timestamp=datetime.now(),
            model_id="yolov8x-640",
            inference_time_ms=45.2,
            detections=[],
        )

        # Update cache
        cache.update(event1)

        # Create second event for same source
        event2 = DetectionEvent(
            source_id=0,
            frame_id=200,
            timestamp=datetime.now(),
            model_id="yolov8x-640",
            inference_time_ms=45.2,
            detections=[],
        )

        # Update cache again
        cache.update(event2)

        # Retrieve event
        retrieved = cache.get(0)
        assert retrieved is not None
        assert retrieved.frame_id == 200  # Should be the latest

    def test_cache_get_missing_source(self):
        cache = DetectionCache(ttl_seconds=1.0)

        # Try to get non-existent source
        retrieved = cache.get(99)
        assert retrieved is None

    def test_cache_clear(self):
        cache = DetectionCache(ttl_seconds=1.0)

        # Add multiple events
        for i in range(5):
            event = DetectionEvent(
                source_id=i,
                frame_id=100 + i,
                timestamp=datetime.now(),
                model_id="yolov8x-640",
                inference_time_ms=45.2,
                detections=[],
            )
            cache.update(event)

        # Verify events are cached
        assert cache.size() == 5

        # Clear cache
        cache.clear()

        # Verify cache is empty
        assert cache.size() == 0
        assert cache.get(0) is None

    def test_cache_thread_safety(self):
        """Basic thread safety test"""
        import threading

        cache = DetectionCache(ttl_seconds=1.0)

        def update_cache(source_id):
            for i in range(100):
                event = DetectionEvent(
                    source_id=source_id,
                    frame_id=i,
                    timestamp=datetime.now(),
                    model_id="yolov8x-640",
                    inference_time_ms=45.2,
                    detections=[],
                )
                cache.update(event)

        # Create multiple threads
        threads = [threading.Thread(target=update_cache, args=(i,)) for i in range(5)]

        # Start all threads
        for t in threads:
            t.start()

        # Wait for all threads to complete
        for t in threads:
            t.join()

        # Cache should have 5 entries (one per source)
        assert cache.size() == 5

