"""
MQTT Detection Sink
===================

Sink function that publishes detection events to MQTT broker.
Compatible with InferencePipeline on_prediction signature.
"""

import logging
from typing import List, Optional, Union

import paho.mqtt.client as mqtt

from cupertino_nvr.events.protocol import topic_for_source
from cupertino_nvr.events.schema import BoundingBox, Detection, DetectionEvent

logger = logging.getLogger(__name__)


class MQTTDetectionSink:
    """
    Sink that publishes detection events to MQTT.

    This sink is compatible with InferencePipeline's on_prediction callback signature.
    It converts Roboflow prediction dictionaries into DetectionEvent messages and
    publishes them to MQTT topics organized by source_id.

    Args:
        mqtt_client: Connected paho.mqtt.Client instance
        topic_prefix: MQTT topic prefix (default: "nvr/detections")
        model_id: Model ID for event metadata

    Example:
        >>> import paho.mqtt.client as mqtt
        >>> from inference import InferencePipeline
        >>>
        >>> # Setup MQTT
        >>> client = mqtt.Client()
        >>> client.connect("localhost", 1883)
        >>> client.loop_start()
        >>>
        >>> # Create sink
        >>> sink = MQTTDetectionSink(client, "nvr/detections", "yolov8x-640")
        >>>
        >>> # Use with pipeline
        >>> pipeline = InferencePipeline.init(
        ...     video_reference=["rtsp://..."],
        ...     model_id="yolov8x-640",
        ...     on_prediction=sink,
        ... )
    """

    def __init__(
        self,
        mqtt_client: mqtt.Client,
        topic_prefix: str,
        model_id: str,
        source_id_mapping: Optional[List[int]] = None,
    ):
        self.client = mqtt_client
        self.topic_prefix = topic_prefix
        self.model_id = model_id
        self.source_id_mapping = source_id_mapping or []

    def __call__(
        self,
        predictions: Union[dict, List[Optional[dict]]],
        video_frame: Union[object, List[Optional[object]]],
    ) -> None:
        """
        Sink compatible with InferencePipeline signature.

        Args:
            predictions: Single prediction dict or list of prediction dicts
            video_frame: Single VideoFrame or list of VideoFrames
        """
        # Wrap in list if single prediction
        predictions = self._wrap_in_list(predictions)
        video_frames = self._wrap_in_list(video_frame)

        for pred, frame in zip(predictions, video_frames):
            if frame is None or pred is None:
                continue

            try:
                # Map internal source_id to actual stream ID
                actual_source_id = self._get_actual_source_id(frame.source_id)
                
                event = self._create_event(pred, frame, actual_source_id)
                topic = topic_for_source(actual_source_id, self.topic_prefix)
                payload = event.model_dump_json()

                result = self.client.publish(topic, payload, qos=0)

                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    logger.warning(
                        f"Failed to publish to {topic}: {mqtt.error_string(result.rc)}"
                    )

            except Exception as e:
                actual_source_id = self._get_actual_source_id(frame.source_id)
                logger.error(f"Error in MQTT sink for source {actual_source_id}: {e}")

    def _get_actual_source_id(self, internal_source_id: int) -> int:
        """
        Map internal source_id (0,1,2...) to actual stream ID.
        
        Args:
            internal_source_id: Internal source ID assigned by InferencePipeline
            
        Returns:
            Actual stream ID that corresponds to the go2rtc stream number
        """
        if self.source_id_mapping and internal_source_id < len(self.source_id_mapping):
            return self.source_id_mapping[internal_source_id]
        return internal_source_id

    def _create_event(self, prediction: dict, frame: object, actual_source_id: int) -> DetectionEvent:
        """
        Convert Roboflow prediction to DetectionEvent.

        Args:
            prediction: Roboflow prediction dictionary
            frame: VideoFrame object
            actual_source_id: Actual stream ID to use in event

        Returns:
            DetectionEvent instance
        """
        detections = []

        for p in prediction.get("predictions", []):
            detections.append(
                Detection(
                    class_name=p["class"],
                    confidence=p["confidence"],
                    bbox=BoundingBox(
                        x=p["x"],
                        y=p["y"],
                        width=p["width"],
                        height=p["height"],
                    ),
                    tracker_id=p.get("tracker_id"),
                )
            )

        return DetectionEvent(
            source_id=actual_source_id,
            frame_id=frame.frame_id,
            timestamp=frame.frame_timestamp,
            model_id=self.model_id,
            inference_time_ms=prediction.get("time", 0) * 1000,
            detections=detections,
            fps=None,  # Can be computed if needed
            latency_ms=None,
        )

    @staticmethod
    def _wrap_in_list(item):
        """Wrap item in list if not already a list"""
        if isinstance(item, list):
            return item
        return [item]

