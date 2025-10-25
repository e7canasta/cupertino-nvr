"""
Stream Processor
================

Headless stream processor with MQTT event publishing.
Wraps InferencePipeline for multi-stream processing.
"""

import logging
import os
import signal
from typing import Optional

import paho.mqtt.client as mqtt

from cupertino_nvr.processor.config import StreamProcessorConfig
from cupertino_nvr.processor.mqtt_sink import MQTTDetectionSink
from cupertino_nvr.processor.control_plane import MQTTControlPlane

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
        self.control_plane: Optional[MQTTControlPlane] = None
        
        # State tracking
        self.is_running = False
        self.is_paused = False

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def start(self):
        """Start the processor"""
        logger.info(
            f"Starting StreamProcessor with {len(self.config.stream_uris)} streams"
        )

        # Enable frame dropping for better performance (new behavior from v0.26.0)
        os.environ["ENABLE_FRAME_DROP_ON_VIDEO_FILE_RATE_LIMITING"] = "True"
        logger.info("Frame dropping enabled for optimal performance")

        # Initialize MQTT client
        self.mqtt_client = self._init_mqtt_client()

        # Create MQTT sink with source ID mapping
        mqtt_sink = MQTTDetectionSink(
            mqtt_client=self.mqtt_client,
            topic_prefix=self.config.mqtt_topic_prefix,
            model_id=self.config.model_id,
            source_id_mapping=self.config.source_id_mapping,
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
        self.is_running = True

        # Initialize Control Plane if enabled
        if self.config.enable_control_plane:
            logger.info("Initializing MQTT Control Plane...")
            self.control_plane = MQTTControlPlane(
                broker_host=self.config.mqtt_host,
                broker_port=self.config.mqtt_port,
                command_topic=self.config.control_command_topic,
                status_topic=self.config.control_status_topic,
                client_id="nvr_processor_control",
                username=self.config.mqtt_username,
                password=self.config.mqtt_password,
            )
            
            # Register commands
            self._setup_control_commands()
            
            # Connect to broker
            if self.control_plane.connect(timeout=10):
                logger.info("✅ Control Plane connected and ready")
                logger.info(f"📡 Control Topic: {self.config.control_command_topic}")
                logger.info("💡 Available commands: pause, resume, stop, status")
            else:
                logger.warning("⚠️  Failed to connect Control Plane (continuing without it)")
                self.control_plane = None

    def join(self):
        """Wait for pipeline to finish"""
        if self.pipeline:
            self.pipeline.join()

        # Cleanup
        if self.mqtt_client:
            self.mqtt_client.disconnect()
            self.mqtt_client.loop_stop()
        
        if self.control_plane:
            self.control_plane.disconnect()

        logger.info("StreamProcessor stopped")

    def terminate(self):
        """Stop the processor"""
        global STOP
        STOP = True

        if self.pipeline:
            self.pipeline.terminate()
            self.is_running = False

    def _setup_control_commands(self):
        """Register MQTT control commands"""
        if not self.control_plane:
            return
        
        registry = self.control_plane.command_registry
        
        # Register basic commands
        registry.register('pause', self._handle_pause, "Pause stream processing")
        registry.register('resume', self._handle_resume, "Resume stream processing")
        registry.register('stop', self._handle_stop, "Stop processor completely")
        registry.register('status', self._handle_status, "Query current status")
        
        logger.info("Control commands registered: pause, resume, stop, status")

    def _handle_pause(self):
        """Handle PAUSE command"""
        logger.info("⏸️  PAUSE command received")
        if self.is_running and not self.is_paused:
            try:
                self.pipeline.pause_stream()
                self.is_paused = True
                if self.control_plane:
                    self.control_plane.publish_status("paused")
                logger.info("✅ Pipeline paused")
            except Exception as e:
                logger.error(f"Failed to pause pipeline: {e}", exc_info=True)
        else:
            logger.warning("⚠️  Pipeline is not running or already paused")

    def _handle_resume(self):
        """Handle RESUME command"""
        logger.info("▶️  RESUME command received")
        if self.is_running and self.is_paused:
            try:
                self.pipeline.resume_stream()
                self.is_paused = False
                if self.control_plane:
                    self.control_plane.publish_status("running")
                logger.info("✅ Pipeline resumed")
            except Exception as e:
                logger.error(f"Failed to resume pipeline: {e}", exc_info=True)
        else:
            logger.warning("⚠️  Pipeline is not paused")

    def _handle_stop(self):
        """Handle STOP command"""
        logger.info("⏹️  STOP command received")
        if self.is_running:
            try:
                self.terminate()
                if self.control_plane:
                    self.control_plane.publish_status("stopped")
                logger.info("✅ Pipeline stopped")
            except Exception as e:
                logger.error(f"Failed to stop pipeline: {e}", exc_info=True)
        else:
            logger.warning("⚠️  Pipeline is not running")

    def _handle_status(self):
        """Handle STATUS command"""
        logger.info("📋 STATUS command received")
        if self.is_running:
            status = "paused" if self.is_paused else "running"
        else:
            status = "stopped"
        
        if self.control_plane:
            self.control_plane.publish_status(status)
        logger.info(f"Current status: {status}")

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

