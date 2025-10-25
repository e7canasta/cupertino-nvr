"""
Unit tests for MQTT detection sink
"""

from datetime import datetime
from unittest.mock import MagicMock

import numpy as np
import paho.mqtt.client as mqtt
import pytest

from cupertino_nvr.events import DetectionEvent
from cupertino_nvr.processor import MQTTDetectionSink


class MockVideoFrame:
    """Mock VideoFrame for testing"""

    def __init__(self, source_id, frame_id, timestamp):
        self.source_id = source_id
        self.frame_id = frame_id
        self.frame_timestamp = timestamp
        self.image = np.zeros((720, 1280, 3), dtype=np.uint8)


class TestMQTTDetectionSink:
    def test_sink_creation(self):
        mock_client = MagicMock()
        sink = MQTTDetectionSink(mock_client, "nvr/detections", "yolov8x-640")

        assert sink.client == mock_client
        assert sink.topic_prefix == "nvr/detections"
        assert sink.model_id == "yolov8x-640"

    def test_sink_publishes_event(self):
        # Mock MQTT client
        mock_client = MagicMock()
        mock_client.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS

        # Create sink
        sink = MQTTDetectionSink(mock_client, "nvr/detections", "yolov8x-640")

        # Mock prediction and frame
        prediction = {
            "predictions": [
                {
                    "class": "person",
                    "confidence": 0.92,
                    "x": 100,
                    "y": 150,
                    "width": 80,
                    "height": 200,
                }
            ],
            "time": 0.045,
        }

        frame = MockVideoFrame(
            source_id=0, frame_id=123, timestamp=datetime(2025, 10, 25, 10, 30, 0)
        )

        # Call sink
        sink(prediction, frame)

        # Verify publish was called
        mock_client.publish.assert_called_once()
        call_args = mock_client.publish.call_args

        # Check topic
        assert call_args[0][0] == "nvr/detections/0"

        # Check payload is valid DetectionEvent
        payload = call_args[0][1]
        event = DetectionEvent.model_validate_json(payload)
        assert event.source_id == 0
        assert event.frame_id == 123
        assert len(event.detections) == 1
        assert event.detections[0].class_name == "person"
        assert event.detections[0].confidence == 0.92

        # Check QoS
        assert call_args[1]["qos"] == 0

    def test_sink_handles_multiple_predictions(self):
        mock_client = MagicMock()
        mock_client.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS

        sink = MQTTDetectionSink(mock_client, "nvr/detections", "yolov8x-640")

        # Multiple predictions
        prediction = {
            "predictions": [
                {
                    "class": "person",
                    "confidence": 0.92,
                    "x": 100,
                    "y": 150,
                    "width": 80,
                    "height": 200,
                },
                {
                    "class": "car",
                    "confidence": 0.85,
                    "x": 300,
                    "y": 200,
                    "width": 120,
                    "height": 100,
                },
            ],
            "time": 0.045,
        }

        frame = MockVideoFrame(
            source_id=0, frame_id=123, timestamp=datetime(2025, 10, 25, 10, 30, 0)
        )

        sink(prediction, frame)

        # Verify event has both detections
        payload = mock_client.publish.call_args[0][1]
        event = DetectionEvent.model_validate_json(payload)
        assert len(event.detections) == 2
        assert event.detections[0].class_name == "person"
        assert event.detections[1].class_name == "car"

    def test_sink_handles_batch_predictions(self):
        """Test sink with list of predictions and frames"""
        mock_client = MagicMock()
        mock_client.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS

        sink = MQTTDetectionSink(mock_client, "nvr/detections", "yolov8x-640")

        # Batch of predictions and frames
        predictions = [
            {
                "predictions": [
                    {
                        "class": "person",
                        "confidence": 0.92,
                        "x": 100,
                        "y": 150,
                        "width": 80,
                        "height": 200,
                    }
                ],
                "time": 0.045,
            },
            {
                "predictions": [
                    {
                        "class": "car",
                        "confidence": 0.85,
                        "x": 300,
                        "y": 200,
                        "width": 120,
                        "height": 100,
                    }
                ],
                "time": 0.050,
            },
        ]

        frames = [
            MockVideoFrame(
                source_id=0, frame_id=100, timestamp=datetime(2025, 10, 25, 10, 30, 0)
            ),
            MockVideoFrame(
                source_id=1, frame_id=200, timestamp=datetime(2025, 10, 25, 10, 30, 1)
            ),
        ]

        sink(predictions, frames)

        # Verify publish was called twice
        assert mock_client.publish.call_count == 2

    def test_sink_handles_none_frame(self):
        """Test sink gracefully handles None frames"""
        mock_client = MagicMock()
        mock_client.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS

        sink = MQTTDetectionSink(mock_client, "nvr/detections", "yolov8x-640")

        # None frame
        prediction = {
            "predictions": [
                {
                    "class": "person",
                    "confidence": 0.92,
                    "x": 100,
                    "y": 150,
                    "width": 80,
                    "height": 200,
                }
            ],
            "time": 0.045,
        }

        sink(prediction, None)

        # Should not publish
        mock_client.publish.assert_not_called()

    def test_sink_with_tracker_id(self):
        """Test sink handles tracker_id in predictions"""
        mock_client = MagicMock()
        mock_client.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS

        sink = MQTTDetectionSink(mock_client, "nvr/detections", "yolov8x-640")

        prediction = {
            "predictions": [
                {
                    "class": "person",
                    "confidence": 0.92,
                    "x": 100,
                    "y": 150,
                    "width": 80,
                    "height": 200,
                    "tracker_id": 42,
                }
            ],
            "time": 0.045,
        }

        frame = MockVideoFrame(
            source_id=0, frame_id=123, timestamp=datetime(2025, 10, 25, 10, 30, 0)
        )

        sink(prediction, frame)

        # Verify tracker_id is in event
        payload = mock_client.publish.call_args[0][1]
        event = DetectionEvent.model_validate_json(payload)
        assert event.detections[0].tracker_id == 42

