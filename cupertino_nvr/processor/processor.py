"""
Stream Processor
================

Headless stream processor with MQTT event publishing.
Wraps InferencePipeline for multi-stream processing.
"""

import logging
import signal
from typing import Optional

import paho.mqtt.client as mqtt

from cupertino_nvr.processor.config import StreamProcessorConfig
from cupertino_nvr.processor.mqtt_sink import MQTTDetectionSink

logger = logging.getLogger(__name__)

# Global stop flag for signal handling
STOP = False


class StreamProcessor:
    """
    Headless stream processor with MQTT event publishing.

    Processes multiple RTSP streams with AI inference and publishes
    detection events to MQTT broker. Designed to run without GUI overhead.

    Args:
        config: StreamProcessorConfig instance

    Example:
        >>> config = StreamProcessorConfig(
        ...     stream_uris=["rtsp://localhost:8554/live/0.stream"],
        ...     model_id="yolov8x-640",
        ...     mqtt_host="localhost",
        ... )
        >>> processor = StreamProcessor(config)
        >>> processor.start()
        >>> processor.join()  # Blocks until stopped
    """

    def __init__(self, config: StreamProcessorConfig):
        self.config = config
        self.pipeline: Optional[object] = None
        self.mqtt_client: Optional[mqtt.Client] = None
        self.watchdog: Optional[object] = None

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def start(self):
        """Start the processor"""
        logger.info(
            f"Starting StreamProcessor with {len(self.config.stream_uris)} streams"
        )

        # Initialize MQTT client
        self.mqtt_client = self._init_mqtt_client()

        # Create MQTT sink
        mqtt_sink = MQTTDetectionSink(
            mqtt_client=self.mqtt_client,
            topic_prefix=self.config.mqtt_topic_prefix,
            model_id=self.config.model_id,
        )

        # Import InferencePipeline here to avoid hard dependency at module level
        try:
            from inference import InferencePipeline
            from inference.core.interfaces.stream.watchdog import BasePipelineWatchDog
        except ImportError as e:
            logger.error(
                "Failed to import InferencePipeline. "
                "Make sure 'inference' package is installed."
            )
            raise ImportError(
                "InferencePipeline not available. Install with: pip install inference"
            ) from e

        # Create watchdog if enabled
        if self.config.enable_watchdog:
            self.watchdog = BasePipelineWatchDog()

        # Initialize pipeline
        self.pipeline = InferencePipeline.init(
            video_reference=self.config.stream_uris,
            model_id=self.config.model_id,
            on_prediction=mqtt_sink,
            watchdog=self.watchdog,
            max_fps=self.config.max_fps,
        )

        logger.info("Pipeline initialized, starting processing...")
        self.pipeline.start()

    def join(self):
        """Wait for pipeline to finish"""
        if self.pipeline:
            self.pipeline.join()

        # Cleanup
        if self.mqtt_client:
            self.mqtt_client.disconnect()
            self.mqtt_client.loop_stop()

        logger.info("StreamProcessor stopped")

    def terminate(self):
        """Stop the processor"""
        global STOP
        STOP = True

        if self.pipeline:
            self.pipeline.terminate()

    def _init_mqtt_client(self) -> mqtt.Client:
        """Initialize and connect MQTT client"""
        client = mqtt.Client()

        # Setup authentication if provided
        if self.config.mqtt_username:
            client.username_pw_set(
                self.config.mqtt_username, self.config.mqtt_password
            )

        # Connect
        logger.info(
            f"Connecting to MQTT broker at "
            f"{self.config.mqtt_host}:{self.config.mqtt_port}"
        )
        client.connect(self.config.mqtt_host, self.config.mqtt_port)
        client.loop_start()

        return client

    def _signal_handler(self, signum, frame):
        """Handle termination signals"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.terminate()

