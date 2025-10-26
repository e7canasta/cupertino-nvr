"""
Unit Tests for MQTTDetectionSink using Fake Implementations
===========================================================

Demonstrates the value of Protocol-based dependency injection.

Benefits:
- ✅ No MQTT broker required (instant test execution)
- ✅ Deterministic (no network flakiness)
- ✅ Easy to test edge cases (connection failures, publish errors)
- ✅ Clear test intent (readable fake implementations)

This is enabled by the MessageBroker protocol (cupertino_nvr/interfaces.py).

Based on DESIGN_CONSULTANCY_REFACTORING.md - Prioridad 3: Abstracciones.
"""

import pytest
from dataclasses import dataclass
from typing import List, Tuple, Optional

from cupertino_nvr.processor.mqtt_sink import MQTTDetectionSink
from cupertino_nvr.processor.config import StreamProcessorConfig


# ============================================================================
# Fake Implementations (no real infrastructure needed)
# ============================================================================


@dataclass
class FakePublishResult:
    """Fake MQTT publish result."""

    rc: int  # Return code (0 = success)


class FakeMessageBroker:
    """
    Fake MQTT broker for testing.

    Implements MessageBroker protocol without requiring a real broker.
    Captures all published messages for assertions.
    """

    def __init__(self, fail_publish: bool = False):
        self.published: List[Tuple[str, str, int, bool]] = []
        self.fail_publish = fail_publish
        self.connected = False
        self._subscriptions: List[str] = []

    def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False):
        """Record published message."""
        self.published.append((topic, payload, qos, retain))
        return FakePublishResult(rc=1 if self.fail_publish else 0)

    def subscribe(self, topic: str, qos: int = 0) -> None:
        """Record subscription."""
        self._subscriptions.append(topic)

    def connect(self, host: str, port: int, keepalive: int = 60) -> None:
        """Fake connect."""
        self.connected = True

    def disconnect(self) -> None:
        """Fake disconnect."""
        self.connected = False

    def loop_start(self) -> None:
        """Fake loop start."""
        pass

    def loop_stop(self) -> None:
        """Fake loop stop."""
        pass


class MockVideoFrame:
    """
    Mock video frame for testing.

    Implements VideoFrame protocol (cupertino_nvr/interfaces.py).
    """

    def __init__(self, source_id: int, frame_id: int, frame_timestamp: float):
        self.source_id = source_id
        self.frame_id = frame_id
        self.frame_timestamp = frame_timestamp


# ============================================================================
# Tests
# ============================================================================


def test_mqtt_sink_publishes_detection_to_correct_topic():
    """
    Test that sink publishes detections to correct MQTT topic.

    Without FakeMessageBroker, this would require:
    - Running mosquitto broker
    - Subscribing to topics
    - Parsing JSON payloads
    - Race conditions between publish/subscribe

    With FakeMessageBroker:
    - Instant execution
    - Direct assertion on published messages
    - No infrastructure needed
    """
    # Setup
    broker = FakeMessageBroker()
    config = StreamProcessorConfig(
        stream_uris=["rtsp://localhost:8554/0"],
        model_id="yolov8x-640",
        instance_id="test-processor",
    )
    sink = MQTTDetectionSink(
        mqtt_client=broker, topic_prefix="nvr/detections", config=config
    )

    # Mock prediction and frame
    prediction = {
        "predictions": [
            {
                "class": "person",
                "confidence": 0.92,
                "x": 100.0,
                "y": 200.0,
                "width": 50.0,
                "height": 80.0,
            }
        ],
        "time": 0.045,  # 45ms inference time
    }
    frame = MockVideoFrame(source_id=0, frame_id=123, frame_timestamp=1234567.89)

    # Execute
    sink(prediction, frame)

    # Assert
    assert len(broker.published) == 1
    topic, payload, qos, retain = broker.published[0]

    assert topic == "nvr/detections/0"
    assert qos == 0
    assert retain is False

    # Verify payload contains expected fields (JSON)
    import json

    event_data = json.loads(payload)
    assert event_data["instance_id"] == "test-processor"
    assert event_data["source_id"] == 0
    assert event_data["frame_id"] == 123
    assert event_data["model_id"] == "yolov8x-640"
    assert event_data["inference_time_ms"] == 45.0  # 0.045 * 1000
    assert len(event_data["detections"]) == 1

    detection = event_data["detections"][0]
    assert detection["class_name"] == "person"
    assert detection["confidence"] == 0.92
    assert detection["bbox"]["x"] == 100.0


def test_mqtt_sink_with_source_id_mapping():
    """
    Test that sink correctly maps internal source_id to actual stream ID.

    This is critical for go2rtc proxy pattern where:
    - Internal source_id: 0, 1, 2 (InferencePipeline indices)
    - Actual stream IDs: 8, 6, 2 (go2rtc room numbers)
    """
    # Setup with source_id_mapping
    broker = FakeMessageBroker()
    config = StreamProcessorConfig(
        stream_uris=["rtsp://localhost:8554/8", "rtsp://localhost:8554/6"],
        source_id_mapping=[8, 6],  # Map internal [0,1] to actual [8,6]
        instance_id="test-processor",
    )
    sink = MQTTDetectionSink(
        mqtt_client=broker,
        topic_prefix="nvr/detections",
        config=config,
        source_id_mapping=config.source_id_mapping,
    )

    # Mock frames from both sources
    prediction = {"predictions": [], "time": 0.03}
    frame_source_0 = MockVideoFrame(source_id=0, frame_id=1, frame_timestamp=123.0)
    frame_source_1 = MockVideoFrame(source_id=1, frame_id=1, frame_timestamp=123.0)

    # Execute
    sink(prediction, frame_source_0)
    sink(prediction, frame_source_1)

    # Assert: topics should use ACTUAL source IDs (8, 6), not internal (0, 1)
    assert len(broker.published) == 2

    topic_0, payload_0, _, _ = broker.published[0]
    topic_1, payload_1, _, _ = broker.published[1]

    assert topic_0 == "nvr/detections/8"  # Mapped from internal 0 → actual 8
    assert topic_1 == "nvr/detections/6"  # Mapped from internal 1 → actual 6

    # Verify payload also contains correct source_id
    import json

    event_0 = json.loads(payload_0)
    event_1 = json.loads(payload_1)

    assert event_0["source_id"] == 8
    assert event_1["source_id"] == 6


def test_mqtt_sink_pause_stops_publishing():
    """
    Test that pausing sink immediately stops publishing.

    This is the two-level pause pattern (sink-level + pipeline-level).
    Sink-level pause provides immediate stop, while pipeline pause is gradual.
    """
    # Setup
    broker = FakeMessageBroker()
    config = StreamProcessorConfig(
        stream_uris=["rtsp://localhost:8554/0"], instance_id="test-processor"
    )
    sink = MQTTDetectionSink(
        mqtt_client=broker, topic_prefix="nvr/detections", config=config
    )

    prediction = {"predictions": [], "time": 0.03}
    frame = MockVideoFrame(source_id=0, frame_id=1, frame_timestamp=123.0)

    # Publish before pause
    sink(prediction, frame)
    assert len(broker.published) == 1

    # Pause
    sink.pause()

    # Publish after pause (should be dropped)
    sink(prediction, frame)
    sink(prediction, frame)
    assert len(broker.published) == 1  # Still only 1 (paused)

    # Resume
    sink.resume()

    # Publish after resume (should work)
    sink(prediction, frame)
    assert len(broker.published) == 2


def test_mqtt_sink_handles_batch_predictions():
    """
    Test that sink handles batch predictions (list of predictions).

    InferencePipeline can return either:
    - Single prediction dict
    - List of prediction dicts (multi-source)
    """
    # Setup
    broker = FakeMessageBroker()
    config = StreamProcessorConfig(
        stream_uris=["rtsp://localhost:8554/0", "rtsp://localhost:8554/1"],
        instance_id="test-processor",
    )
    sink = MQTTDetectionSink(
        mqtt_client=broker, topic_prefix="nvr/detections", config=config
    )

    # Batch predictions (list)
    predictions = [
        {"predictions": [{"class": "person", "confidence": 0.9, "x": 10, "y": 20, "width": 30, "height": 40}], "time": 0.05},
        {"predictions": [{"class": "car", "confidence": 0.85, "x": 50, "y": 60, "width": 70, "height": 80}], "time": 0.05},
    ]
    frames = [
        MockVideoFrame(source_id=0, frame_id=1, frame_timestamp=123.0),
        MockVideoFrame(source_id=1, frame_id=1, frame_timestamp=123.0),
    ]

    # Execute
    sink(predictions, frames)

    # Assert: should publish 2 messages (one per source)
    assert len(broker.published) == 2

    import json

    event_0 = json.loads(broker.published[0][1])
    event_1 = json.loads(broker.published[1][1])

    assert event_0["source_id"] == 0
    assert event_0["detections"][0]["class_name"] == "person"

    assert event_1["source_id"] == 1
    assert event_1["detections"][0]["class_name"] == "car"


def test_mqtt_sink_skips_none_frames():
    """
    Test that sink gracefully handles None frames (connection loss).

    InferencePipeline may return None for frames when stream disconnects.
    """
    # Setup
    broker = FakeMessageBroker()
    config = StreamProcessorConfig(
        stream_uris=["rtsp://localhost:8554/0"], instance_id="test-processor"
    )
    sink = MQTTDetectionSink(
        mqtt_client=broker, topic_prefix="nvr/detections", config=config
    )

    # Mix of valid and None frames
    predictions = [
        {"predictions": [], "time": 0.03},
        None,  # Stream disconnected
        {"predictions": [], "time": 0.03},
    ]
    frames = [
        MockVideoFrame(source_id=0, frame_id=1, frame_timestamp=123.0),
        None,  # Connection lost
        MockVideoFrame(source_id=0, frame_id=3, frame_timestamp=125.0),
    ]

    # Execute (should not crash)
    sink(predictions, frames)

    # Assert: only 2 messages published (None skipped)
    assert len(broker.published) == 2


def test_mqtt_sink_dynamic_model_id():
    """
    Test that sink uses dynamic model_id from config (not snapshot).

    This allows model changes via MQTT control without recreating sink.
    Sink stores reference to config (not copy), so it sees updates.
    """
    # Setup
    broker = FakeMessageBroker()
    config = StreamProcessorConfig(
        stream_uris=["rtsp://localhost:8554/0"],
        model_id="yolov8x-640",
        instance_id="test-processor",
    )
    sink = MQTTDetectionSink(
        mqtt_client=broker, topic_prefix="nvr/detections", config=config
    )

    prediction = {"predictions": [], "time": 0.03}
    frame = MockVideoFrame(source_id=0, frame_id=1, frame_timestamp=123.0)

    # Publish with original model_id
    sink(prediction, frame)

    import json

    event_1 = json.loads(broker.published[0][1])
    assert event_1["model_id"] == "yolov8x-640"

    # Change model_id in config (simulates CHANGE_MODEL command)
    config.model_id = "yolov11x-640"

    # Publish again (should use NEW model_id)
    sink(prediction, frame)

    event_2 = json.loads(broker.published[1][1])
    assert event_2["model_id"] == "yolov11x-640"  # Dynamic lookup!


# ============================================================================
# Error Handling Tests
# ============================================================================


def test_mqtt_sink_handles_publish_failure_gracefully():
    """
    Test that sink logs errors but doesn't crash on publish failure.

    This is important for reliability: MQTT connection issues shouldn't
    crash the entire pipeline.
    """
    # Setup with failing broker
    broker = FakeMessageBroker(fail_publish=True)
    config = StreamProcessorConfig(
        stream_uris=["rtsp://localhost:8554/0"], instance_id="test-processor"
    )
    sink = MQTTDetectionSink(
        mqtt_client=broker, topic_prefix="nvr/detections", config=config
    )

    prediction = {"predictions": [], "time": 0.03}
    frame = MockVideoFrame(source_id=0, frame_id=1, frame_timestamp=123.0)

    # Execute (should not crash, even though publish fails)
    sink(prediction, frame)

    # Verify: publish was attempted (captured in fake broker)
    assert len(broker.published) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
