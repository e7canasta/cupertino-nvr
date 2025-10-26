"""
Stream Processor - Main Orchestrator
=====================================

Headless stream processor with MQTT event publishing.

Refactored per DESIGN_CONSULTANCY_REFACTORING.md (Fase 2):
- Delegates pipeline lifecycle to InferencePipelineManager
- Delegates command handling to CommandHandlers
- Delegates metrics reporting to MetricsReporter
- Coordinates control plane setup and registration

This class is now a thin orchestrator (~200 lines) instead of a God Object (1500+ lines).
"""

import logging
import os
import signal
import time
from typing import Optional

import paho.mqtt.client as mqtt

from cupertino_nvr.processor.config import StreamProcessorConfig
from cupertino_nvr.processor.mqtt_sink import MQTTDetectionSink
from cupertino_nvr.processor.control_plane import MQTTControlPlane
from cupertino_nvr.processor.pipeline_manager import InferencePipelineManager
from cupertino_nvr.processor.command_handlers import CommandHandlers
from cupertino_nvr.processor.metrics_reporter import MetricsReporter
from cupertino_nvr.logging_utils import get_component_logger

logger = get_component_logger(__name__, "processor")

# Global stop flag for signal handling
STOP = False


class StreamProcessor:
    """
    Main orchestrator for headless stream processing.

    Responsibilities (delegated):
    - Pipeline management → InferencePipelineManager
    - Command handling → CommandHandlers
    - Metrics reporting → MetricsReporter
    - Control plane → MQTTControlPlane

    This class coordinates component lifecycle and initialization order.

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

        # Components (created in start())
        self.mqtt_client: Optional[mqtt.Client] = None
        self.mqtt_sink: Optional[MQTTDetectionSink] = None
        self.pipeline_manager: Optional[InferencePipelineManager] = None
        self.control_plane: Optional[MQTTControlPlane] = None
        self.command_handlers: Optional[CommandHandlers] = None
        self.metrics_reporter: Optional[MetricsReporter] = None

        # State tracking
        self.is_running = False
        self.is_paused = False
        self._is_restarting = False

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def start(self):
        """
        Start processor with correct initialization order.

        Order (CRITICAL):
        1. MQTT client + Sink
        2. Pipeline manager (create pipeline, don't start)
        3. Control plane (must be ready BEFORE pipeline starts)
        4. Metrics reporter
        5. Start pipeline (blocks connecting to streams)
        """
        # Track start time for uptime calculation (PING/PONG)
        self._start_time = time.time()

        logger.info(
            f"Starting StreamProcessor with {len(self.config.stream_uris)} streams",
            extra={
                "event": "processor_start",
                "instance_id": self.config.instance_id,
                "stream_count": len(self.config.stream_uris),
                "model_id": self.config.model_id
            }
        )

        # =====================================================================
        # Step 1: MQTT Client + Sink
        # =====================================================================
        self.mqtt_client = self._init_mqtt_client()

        self.mqtt_sink = MQTTDetectionSink(
            mqtt_client=self.mqtt_client,
            topic_prefix=self.config.mqtt_topic_prefix,
            config=self.config,
            source_id_mapping=self.config.source_id_mapping,
        )

        logger.info(
            "MQTT sink created",
            extra={"event": "mqtt_sink_created"}
        )

        # =====================================================================
        # Step 2: Pipeline Manager (create but don't start)
        # =====================================================================

        # Set env vars for model disabling BEFORE importing inference
        # (see cli.py for context on why this is needed)
        if os.getenv("DEBUG_ENV_VARS", "false").lower() == "true":
            logger.info(
                "🔧 [DEBUG] Environment check",
                extra={
                    "event": "env_check",
                    "sam2_disabled": os.getenv("CORE_MODEL_SAM2_ENABLED"),
                    "clip_disabled": os.getenv("CORE_MODEL_CLIP_ENABLED"),
                }
            )

        self.pipeline_manager = InferencePipelineManager(
            config=self.config,
            mqtt_sink=self.mqtt_sink,
            watchdog=None  # Created by pipeline_manager if config.enable_watchdog
        )

        self.pipeline_manager.create_pipeline()
        logger.info(
            "Pipeline created (not started yet)",
            extra={"event": "pipeline_created"}
        )

        # =====================================================================
        # Step 3: Control Plane (BEFORE pipeline.start!)
        # =====================================================================
        if self.config.enable_control_plane:
            self._setup_control_plane()

        # =====================================================================
        # Step 4: Metrics Reporter
        # =====================================================================
        if self.pipeline_manager.watchdog and self.config.metrics_reporting_interval > 0:
            self.metrics_reporter = MetricsReporter(
                watchdog=self.pipeline_manager.watchdog,
                mqtt_client=self.mqtt_client,
                config=self.config
            )
            self.metrics_reporter.start()

        # =====================================================================
        # Step 5: Start Pipeline (blocks here!)
        # =====================================================================
        logger.info(
            "▶️  Starting InferencePipeline...",
            extra={"event": "pipeline_start_attempt"}
        )

        try:
            self.pipeline_manager.start_pipeline()
            self.is_running = True

            logger.info(
                "✅ StreamProcessor running",
                extra={"event": "processor_running"}
            )

        except Exception as e:
            logger.error(
                "❌ Failed to start pipeline",
                extra={
                    "event": "pipeline_start_failed",
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
                exc_info=True
            )
            raise  # Re-raise to stop processor startup

    def join(self):
        """
        Wait for pipeline to finish.

        Handles restart: If pipeline terminates due to restart command,
        waits for restart to complete and rejoins the new pipeline.
        """
        # Main loop: Rejoin pipeline after restart
        while True:
            if self.is_running and self.pipeline_manager and self.pipeline_manager._pipeline_started:
                # Production mode: pipeline was actually started

                # Save reference to current pipeline to detect restart
                current_pipeline = self.pipeline_manager.pipeline

                logger.info(
                    "Waiting for pipeline to finish...",
                    extra={
                        "event": "pipeline_join_start",
                        "pipeline_id": id(current_pipeline) if current_pipeline else None
                    }
                )

                if current_pipeline:
                    current_pipeline.join()  # Blocks until THIS pipeline terminates

                logger.debug(
                    "Pipeline join returned",
                    extra={
                        "event": "pipeline_join_returned",
                        "old_pipeline_id": id(current_pipeline) if current_pipeline else None,
                        "current_pipeline_id": id(self.pipeline_manager.pipeline) if self.pipeline_manager.pipeline else None,
                        "is_restarting": self._is_restarting
                    }
                )

                # Check if this is a restart or actual shutdown
                is_restart = (
                    self._is_restarting or
                    (self.pipeline_manager.pipeline is not None and
                     self.pipeline_manager.pipeline is not current_pipeline)
                )

                if is_restart:
                    # Restart in progress - wait for it to complete
                    logger.info(
                        "Restart detected, waiting for completion...",
                        extra={
                            "event": "join_waiting_restart",
                            "detection_method": "flag" if self._is_restarting else "pipeline_changed"
                        }
                    )

                    # Wait until restart completes
                    while self._is_restarting:
                        time.sleep(0.1)

                    logger.info(
                        "Restart completed, rejoining new pipeline",
                        extra={
                            "event": "join_restart_completed",
                            "new_pipeline_id": id(self.pipeline_manager.pipeline) if self.pipeline_manager.pipeline else None
                        }
                    )

                    # Continue loop to rejoin new pipeline
                    continue
                else:
                    # Real shutdown - exit loop
                    logger.info(
                        "Pipeline terminated (not a restart), exiting join loop",
                        extra={"event": "join_shutdown_detected"}
                    )
                    break

            else:
                # Debug mode: pipeline exists but was never started
                # Keep alive for MQTT control testing
                logger.info(
                    "Keep-alive loop active (waiting for STOP command)",
                    extra={"event": "debug_keepalive_start"}
                )

                # Wait until STOP is called (via global flag)
                while not STOP:
                    time.sleep(1)

                logger.info(
                    "Keep-alive loop exited (STOP received)",
                    extra={"event": "debug_keepalive_stop"}
                )

                break

        # Cleanup (only on real shutdown, not restart)
        self._cleanup()

    def terminate(self):
        """Stop the processor"""
        global STOP
        STOP = True

        if self.pipeline_manager:
            self.pipeline_manager.terminate_pipeline()

        self.is_running = False

    # ========================================================================
    # Private: Control Plane Setup
    # ========================================================================

    def _setup_control_plane(self):
        """Initialize control plane and register commands."""
        logger.info(
            "🎛️  Initializing MQTT Control Plane",
            extra={
                "event": "control_plane_init_start",
                "mqtt_host": self.config.mqtt_host,
                "mqtt_port": self.config.mqtt_port
            }
        )

        self.control_plane = MQTTControlPlane(
            broker_host=self.config.mqtt_host,
            broker_port=self.config.mqtt_port,
            command_topic=self.config.control_command_topic,
            status_topic=self.config.control_status_topic,
            instance_id=self.config.instance_id,
            client_id="nvr_processor_control",
            username=self.config.mqtt_username,
            password=self.config.mqtt_password,
        )

        # Create command handlers (delegates all command logic)
        self.command_handlers = CommandHandlers(
            pipeline_manager=self.pipeline_manager,
            config=self.config,
            control_plane=self.control_plane,
            metrics_reporter=self.metrics_reporter,
            mqtt_client=self.mqtt_client,
            processor=self  # For uptime tracking in PING
        )

        # Register commands from command_handlers
        self._register_control_commands()

        # Connect to broker
        if self.control_plane.connect(timeout=10):
            logger.info(
                "✅ CONTROL PLANE READY",
                extra={
                    "event": "control_plane_ready",
                    "command_topic": self.config.control_command_topic,
                    "status_topic": self.config.control_status_topic,
                }
            )

            # Auto-announce on startup (Discovery pattern)
            self.control_plane.publish_status(
                "starting",
                uptime_seconds=0,
                config=self.config.to_status_dict()
            )

            logger.info(
                "📢 Auto-announced to orchestrator",
                extra={
                    "event": "auto_announce",
                    "instance_id": self.config.instance_id
                }
            )
        else:
            logger.warning(
                "⚠️  Control Plane connection failed, continuing without remote control",
                extra={
                    "event": "control_plane_connection_failed",
                    "mqtt_host": self.config.mqtt_host,
                    "mqtt_port": self.config.mqtt_port
                }
            )
            self.control_plane = None

    def _register_control_commands(self):
        """Register MQTT control commands from CommandHandlers."""
        if not self.control_plane or not self.command_handlers:
            return

        registry = self.control_plane.command_registry

        # Register basic control commands
        registry.register('pause', self.command_handlers.handle_pause, "Pause stream processing")
        registry.register('resume', self.command_handlers.handle_resume, "Resume stream processing")
        registry.register('stop', self.command_handlers.handle_stop, "Stop processor completely")
        registry.register('restart', self.command_handlers.handle_restart, "Restart pipeline")

        # Register dynamic configuration commands
        registry.register('change_model', self.command_handlers.handle_change_model, "Change inference model")
        registry.register('set_fps', self.command_handlers.handle_set_fps, "Change max FPS")
        registry.register('add_stream', self.command_handlers.handle_add_stream, "Add stream to monitoring")
        registry.register('remove_stream', self.command_handlers.handle_remove_stream, "Remove stream from monitoring")

        # Register observability commands
        registry.register('status', self.command_handlers.handle_status, "Query current status")
        registry.register('metrics', self.command_handlers.handle_metrics, "Get performance metrics")
        registry.register('ping', self.command_handlers.handle_ping, "Health check / discovery")

        # Register orchestration commands
        registry.register('rename_instance', self.command_handlers.handle_rename_instance, "Rename instance")

        logger.info(
            "Control commands registered",
            extra={
                "event": "commands_registered",
                "command_count": 11
            }
        )

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
            f"Connecting to MQTT broker at {self.config.mqtt_host}:{self.config.mqtt_port}",
            extra={
                "event": "mqtt_connection_start",
                "mqtt_host": self.config.mqtt_host,
                "mqtt_port": self.config.mqtt_port
            }
        )
        client.connect(self.config.mqtt_host, self.config.mqtt_port)
        client.loop_start()

        return client

    def _cleanup(self):
        """Cleanup on shutdown."""
        logger.info(
            "Performing shutdown cleanup",
            extra={"event": "shutdown_cleanup_start"}
        )

        if self.mqtt_client:
            self.mqtt_client.disconnect()
            self.mqtt_client.loop_stop()

        if self.control_plane:
            self.control_plane.disconnect()

        if self.metrics_reporter:
            self.metrics_reporter.stop()

        logger.info(
            "StreamProcessor stopped",
            extra={"event": "processor_stopped"}
        )

    def _signal_handler(self, signum, frame):
        """Handle termination signals"""
        logger.info(
            f"Received signal {signum}, shutting down...",
            extra={
                "event": "signal_received",
                "signal": signum
            }
        )
        self.terminate()

    def _get_current_status(self) -> str:
        """
        Get current processor status string.

        Used by command_handlers for STATUS command.

        Returns:
            Status string: "running", "paused", "stopped", "restarting"
        """
        if not self.is_running:
            return "stopped"
        if self.is_paused:
            return "paused"
        if self._is_restarting:
            return "restarting"
        return "running"
