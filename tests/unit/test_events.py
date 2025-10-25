"""
Unit tests for event schemas and protocol
"""

from datetime import datetime

import pytest

from cupertino_nvr.events import (
    BoundingBox,
    Detection,
    DetectionEvent,
    parse_source_id_from_topic,
    topic_for_source,
)


class TestBoundingBox:
    def test_create_bbox(self):
        bbox = BoundingBox(x=100, y=150, width=80, height=200)
        assert bbox.x == 100
        assert bbox.y == 150
        assert bbox.width == 80
        assert bbox.height == 200

    def test_bbox_serialization(self):
        bbox = BoundingBox(x=100, y=150, width=80, height=200)
        json_str = bbox.model_dump_json()
        parsed = BoundingBox.model_validate_json(json_str)
        assert parsed == bbox


class TestDetection:
    def test_create_detection(self):
        bbox = BoundingBox(x=100, y=150, width=80, height=200)
        det = Detection(class_name="person", confidence=0.92, bbox=bbox)
        assert det.class_name == "person"
        assert det.confidence == 0.92
        assert det.bbox == bbox
        assert det.tracker_id is None

    def test_detection_with_tracker(self):
        bbox = BoundingBox(x=100, y=150, width=80, height=200)
        det = Detection(
            class_name="person", confidence=0.92, bbox=bbox, tracker_id=42
        )
        assert det.tracker_id == 42

    def test_detection_confidence_validation(self):
        bbox = BoundingBox(x=100, y=150, width=80, height=200)

        # Valid confidence
        det = Detection(class_name="person", confidence=0.5, bbox=bbox)
        assert det.confidence == 0.5

        # Invalid confidence (out of range)
        with pytest.raises(Exception):  # Pydantic validation error
            Detection(class_name="person", confidence=1.5, bbox=bbox)


class TestDetectionEvent:
    def test_create_event(self):
        bbox = BoundingBox(x=100, y=150, width=80, height=200)
        det = Detection(class_name="person", confidence=0.92, bbox=bbox)

        event = DetectionEvent(
            source_id=0,
            frame_id=123,
            timestamp=datetime.now(),
            model_id="yolov8x-640",
            inference_time_ms=45.2,
            detections=[det],
        )

        assert event.source_id == 0
        assert event.frame_id == 123
        assert event.model_id == "yolov8x-640"
        assert len(event.detections) == 1
        assert event.detections[0].class_name == "person"

    def test_event_serialization_roundtrip(self):
        """Test full serialization/deserialization cycle"""
        bbox = BoundingBox(x=100, y=150, width=80, height=200)
        det = Detection(class_name="person", confidence=0.92, bbox=bbox, tracker_id=42)

        event = DetectionEvent(
            source_id=0,
            frame_id=123,
            timestamp=datetime(2025, 10, 25, 10, 30, 0),
            model_id="yolov8x-640",
            inference_time_ms=45.2,
            detections=[det],
            fps=25.3,
            latency_ms=120.5,
        )

        # Serialize
        json_str = event.model_dump_json()

        # Deserialize
        parsed = DetectionEvent.model_validate_json(json_str)

        # Verify
        assert parsed.source_id == event.source_id
        assert parsed.frame_id == event.frame_id
        assert parsed.model_id == event.model_id
        assert parsed.inference_time_ms == event.inference_time_ms
        assert len(parsed.detections) == 1
        assert parsed.detections[0].class_name == "person"
        assert parsed.detections[0].confidence == 0.92
        assert parsed.detections[0].tracker_id == 42
        assert parsed.fps == 25.3
        assert parsed.latency_ms == 120.5

    def test_event_with_multiple_detections(self):
        det1 = Detection(
            class_name="person",
            confidence=0.92,
            bbox=BoundingBox(x=100, y=150, width=80, height=200),
        )
        det2 = Detection(
            class_name="car",
            confidence=0.85,
            bbox=BoundingBox(x=300, y=200, width=120, height=100),
        )

        event = DetectionEvent(
            source_id=0,
            frame_id=123,
            timestamp=datetime.now(),
            model_id="yolov8x-640",
            inference_time_ms=45.2,
            detections=[det1, det2],
        )

        assert len(event.detections) == 2
        assert event.detections[0].class_name == "person"
        assert event.detections[1].class_name == "car"


class TestProtocol:
    def test_topic_for_source(self):
        topic = topic_for_source(0)
        assert topic == "nvr/detections/0"

        topic = topic_for_source(42)
        assert topic == "nvr/detections/42"

    def test_topic_for_source_custom_prefix(self):
        topic = topic_for_source(5, prefix="custom/events")
        assert topic == "custom/events/5"

    def test_parse_source_id_from_topic(self):
        source_id = parse_source_id_from_topic("nvr/detections/0")
        assert source_id == 0

        source_id = parse_source_id_from_topic("nvr/detections/42")
        assert source_id == 42

    def test_parse_source_id_invalid_topic(self):
        source_id = parse_source_id_from_topic("invalid/topic")
        assert source_id is None

        source_id = parse_source_id_from_topic("nvr/detections/not_a_number")
        assert source_id is None

