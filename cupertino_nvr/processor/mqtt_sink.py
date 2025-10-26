"""
MQTT Detection Sink
===================

Sink function that publishes detection events to MQTT broker.
Compatible with InferencePipeline on_prediction signature.
"""

import logging
import threading
from typing import List, Optional, Union

import paho.mqtt.client as mqtt

from cupertino_nvr.events.protocol import topic_for_source
from cupertino_nvr.events.schema import BoundingBox, Detection, DetectionEvent
from cupertino_nvr.interfaces import MessageBroker

logger = logging.getLogger(__name__)


class MQTTDetectionSink:
    """
    Sink that publishes detection events to MQTT.

    This sink is compatible with InferencePipeline's on_prediction callback signature.
    It converts Roboflow prediction dictionaries into DetectionEvent messages and
    publishes them to MQTT topics organized by source_id.

    Args:
        mqtt_client: Connected MQTT client (MessageBroker protocol)
        topic_prefix: MQTT topic prefix (default: "nvr/detections")
        config: Reference to StreamProcessorConfig for dynamic model_id lookup
        source_id_mapping: Optional mapping from internal source_id to actual stream ID

    Note:
        The sink stores a reference to config (not a copy) so it can access
        the current model_id dynamically. This allows model changes via
        MQTT control commands without recreating the sink.

    Example:
        >>> import paho.mqtt.client as mqtt
        >>> from inference import InferencePipeline
        >>> from cupertino_nvr.processor import StreamProcessorConfig
        >>>
        >>> # Setup MQTT
        >>> client = mqtt.Client()
        >>> client.connect("localhost", 1883)
        >>> client.loop_start()
        >>>
        >>> # Create config and sink
        >>> config = StreamProcessorConfig(...)
        >>> sink = MQTTDetectionSink(client, "nvr/detections", config)
        >>>
        >>> # Use with pipeline
        >>> pipeline = InferencePipeline.init(
        ...     video_reference=["rtsp://..."],
        ...     model_id=config.model_id,
        ...     on_prediction=sink,
        ... )
    """

    def __init__(
        self,
        mqtt_client: MessageBroker,
        topic_prefix: str,
        config: object,  # StreamProcessorConfig
        source_id_mapping: Optional[List[int]] = None,
    ):
        self.client = mqtt_client
        self.topic_prefix = topic_prefix
        self.config = config  # Store reference to config for dynamic model_id lookup
        self.source_id_mapping = source_id_mapping or []

        # Thread-safe pause control using Event (guarantees memory visibility across threads)
        # See PAUSE_BUG_HYPOTHESIS.md for explanation of why Event > boolean flag
        self._running = threading.Event()
        self._running.set()  # Start in running state

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
        # Skip publishing if paused (thread-safe check with memory barrier)
        if not self._running.is_set():
            return
        
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
            instance_id=self.config.instance_id,  # Multi-instance support
            source_id=actual_source_id,
            frame_id=frame.frame_id,
            timestamp=frame.frame_timestamp,
            model_id=self.config.model_id,  # Dynamic lookup from config
            inference_time_ms=prediction.get("time", 0) * 1000,
            detections=detections,
            fps=None,  # Can be computed if needed
            latency_ms=None,
        )

    def pause(self):
        """Pause publishing (immediate effect, thread-safe)"""
        self._running.clear()  # Thread-safe pause with memory barrier
        logger.info(
            "MQTT sink paused - no events will be published",
            extra={"component": "mqtt_sink", "event": "sink_paused"}
        )

    def resume(self):
        """Resume publishing (thread-safe)"""
        self._running.set()  # Thread-safe resume with memory barrier
        logger.info(
            "MQTT sink resumed - publishing events",
            extra={"component": "mqtt_sink", "event": "sink_resumed"}
        )

    @staticmethod
    def _wrap_in_list(item):
        """Wrap item in list if not already a list"""
        if isinstance(item, list):
            return item
        return [item]

