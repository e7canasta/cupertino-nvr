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

from cupertino_nvr.processor.config import StreamProcessorConfig, ConfigValidationError
from cupertino_nvr.processor.mqtt_sink import MQTTDetectionSink
from cupertino_nvr.processor.control_plane import MQTTControlPlane
from cupertino_nvr.processor.metrics_reporter import MetricsReporter

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
        self.mqtt_sink: Optional[object] = None
        self.watchdog: Optional[object] = None
        self.control_plane: Optional[MQTTControlPlane] = None
        self.metrics_reporter: Optional[MetricsReporter] = None

        # State tracking
        self.is_running = False
        self.is_paused = False

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def start(self):
        """Start the processor"""
        import time
        
        # Track start time for uptime calculation (PING/PONG)
        self._start_time = time.time()
        
        logger.info(
            f"Starting StreamProcessor with {len(self.config.stream_uris)} streams",
            extra={
                "component": "processor",
                "event": "processor_start",
                "instance_id": self.config.instance_id,
                "stream_count": len(self.config.stream_uris),
                "model_id": self.config.model_id
            }
        )

        # Enable frame dropping for better performance (new behavior from v0.26.0)
        os.environ["ENABLE_FRAME_DROP_ON_VIDEO_FILE_RATE_LIMITING"] = "True"
        logger.info(
            "Frame dropping enabled for optimal performance",
            extra={"component": "processor", "event": "frame_drop_enabled"}
        )

        # Initialize MQTT client
        self.mqtt_client = self._init_mqtt_client()

        # Create MQTT sink with config reference for dynamic model_id lookup
        self.mqtt_sink = MQTTDetectionSink(
            mqtt_client=self.mqtt_client,
            topic_prefix=self.config.mqtt_topic_prefix,
            config=self.config,  # Pass config reference for dynamic model_id
            source_id_mapping=self.config.source_id_mapping,
        )

        # Import InferencePipeline here to avoid hard dependency at module level
        # Env vars for model disabling must be set BEFORE this import (see cli.py)
        try:
            # Debug: Log env vars before import (if DEBUG_ENV_VARS set)
            if os.getenv("DEBUG_ENV_VARS", "false").lower() == "true":
                logger.info(
                    "🔧 [DEBUG] Importing inference with disabled models",
                    extra={
                        "component": "processor",
                        "event": "inference_import_start",
                        "sam2_disabled": os.getenv("CORE_MODEL_SAM2_ENABLED"),
                        "clip_disabled": os.getenv("CORE_MODEL_CLIP_ENABLED"),
                    }
                )

            from inference import InferencePipeline
            from inference.core.interfaces.stream.watchdog import BasePipelineWatchDog
        except ImportError as e:
            logger.error(
                "Failed to import InferencePipeline. "
                "Make sure 'inference' package is installed.",
                extra={
                    "component": "processor",
                    "event": "import_error",
                    "error_type": type(e).__name__
                }
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
            on_prediction=self.mqtt_sink,
            watchdog=self.watchdog,
            max_fps=self.config.max_fps,
        )

        logger.info(
            "Pipeline initialized, starting processing...",
            extra={
                "component": "processor",
                "event": "pipeline_initialized",
                "model_id": self.config.model_id,
                "max_fps": self.config.max_fps
            }
        )

        # =====================================================================
        # Initialize Control Plane BEFORE starting pipeline
        # (pipeline.start() may block for several seconds connecting to streams)
        # =====================================================================
        if self.config.enable_control_plane:
            logger.info(
                "🎛️  Initializing MQTT Control Plane",
                extra={
                    "component": "processor",
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
                instance_id=self.config.instance_id,  # Multi-instance support
                client_id="nvr_processor_control",
                username=self.config.mqtt_username,
                password=self.config.mqtt_password,
            )

            # Register commands
            self._setup_control_commands()

            # Connect to broker
            if self.control_plane.connect(timeout=10):
                logger.info(
                    "✅ CONTROL PLANE READY",
                    extra={
                        "component": "processor",
                        "event": "control_plane_ready",
                        "command_topic": self.config.control_command_topic,
                        "status_topic": self.config.control_status_topic,
                        "ack_topic": f"{self.config.control_status_topic}/ack",
                        "available_commands": ["pause", "resume", "stop", "status", "metrics"]
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
                        "component": "processor",
                        "event": "auto_announce",
                        "instance_id": self.config.instance_id
                    }
                )
            else:
                logger.warning(
                    "⚠️  Control Plane connection failed, continuing without remote control",
                    extra={
                        "component": "processor",
                        "event": "control_plane_connection_failed",
                        "mqtt_host": self.config.mqtt_host,
                        "mqtt_port": self.config.mqtt_port
                    }
                )
                self.control_plane = None

        # =====================================================================
        # Start metrics reporting BEFORE pipeline (pipeline.start() blocks!)
        # =====================================================================
        if self.watchdog and self.config.metrics_reporting_interval > 0:
            self.metrics_reporter = MetricsReporter(
                watchdog=self.watchdog,
                mqtt_client=self.mqtt_client,
                config=self.config
            )
            self.metrics_reporter.start()

        # =====================================================================
        # PRODUCTION MODE: Pipeline starting
        # =====================================================================
        import sys

        logger.info(
            "▶️ Starting InferencePipeline...",
            extra={
                "component": "processor",
                "event": "pipeline_start_attempt",
            }
        )
        sys.stdout.flush()
        sys.stderr.flush()

        try:
            # IMPORTANT: use_main_thread=False to avoid blocking
            # (pipeline.start() would block in _dispatch_inference_results() otherwise)
            self.pipeline.start(use_main_thread=False)
            self._pipeline_started = True  # Flag for join() to know pipeline actually started
            self.is_running = True

            logger.info(
                "✅ Pipeline started successfully",
                extra={
                    "component": "processor",
                    "event": "pipeline_started",
                }
            )
            sys.stdout.flush()
            sys.stderr.flush()

        except Exception as e:
            logger.error(
                "❌ Failed to start pipeline",
                extra={
                    "component": "processor",
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
        import time

        # Main loop: Rejoin pipeline after restart
        while True:
            if self.is_running and self.pipeline and hasattr(self, '_pipeline_started'):
                # Production mode: pipeline was actually started

                # Save reference to current pipeline to detect restart
                current_pipeline = self.pipeline

                logger.info(
                    "Waiting for pipeline to finish...",
                    extra={
                        "component": "processor",
                        "event": "pipeline_join_start",
                        "pipeline_id": id(current_pipeline)
                    }
                )

                current_pipeline.join()  # Blocks until THIS pipeline terminates

                logger.debug(
                    "Pipeline join returned",
                    extra={
                        "component": "processor",
                        "event": "pipeline_join_returned",
                        "old_pipeline_id": id(current_pipeline),
                        "current_pipeline_id": id(self.pipeline) if self.pipeline else None,
                        "is_restarting": getattr(self, '_is_restarting', False)
                    }
                )

                # Check if this is a restart or actual shutdown
                # Restart detection: either _is_restarting flag OR pipeline reference changed
                is_restart = (
                    (hasattr(self, '_is_restarting') and self._is_restarting) or
                    (self.pipeline is not None and self.pipeline is not current_pipeline)
                )

                if is_restart:
                    # Restart in progress - wait for it to complete
                    logger.info(
                        "Restart detected, waiting for completion...",
                        extra={
                            "component": "processor",
                            "event": "join_waiting_restart",
                            "detection_method": "flag" if (hasattr(self, '_is_restarting') and self._is_restarting) else "pipeline_changed"
                        }
                    )

                    # Wait until restart completes (new pipeline ready)
                    while (hasattr(self, '_is_restarting') and self._is_restarting):
                        time.sleep(0.1)

                    logger.info(
                        "Restart completed, rejoining new pipeline",
                        extra={
                            "component": "processor",
                            "event": "join_restart_completed",
                            "new_pipeline_id": id(self.pipeline) if self.pipeline else None
                        }
                    )

                    # Continue loop to rejoin new pipeline
                    continue
                else:
                    # Real shutdown - exit loop
                    logger.info(
                        "Pipeline terminated (not a restart), exiting join loop",
                        extra={
                            "component": "processor",
                            "event": "join_shutdown_detected"
                        }
                    )
                    break

            else:
                # Debug mode: pipeline exists but was never started
                # Keep alive for MQTT control testing
                logger.info(
                    "Keep-alive loop active (waiting for STOP command)",
                    extra={
                        "component": "processor",
                        "event": "debug_keepalive_start",
                    }
                )

                # Wait until STOP is called (via global flag)
                while not STOP:
                    time.sleep(1)

                logger.info(
                    "Keep-alive loop exited (STOP received)",
                    extra={
                        "component": "processor",
                        "event": "debug_keepalive_stop",
                    }
                )

                break

        # Cleanup (only on real shutdown, not restart)
        logger.info(
            "Performing shutdown cleanup",
            extra={
                "component": "processor",
                "event": "shutdown_cleanup_start"
            }
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
            extra={"component": "processor", "event": "processor_stopped"}
        )

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
        registry.register('metrics', self._handle_metrics, "Get performance metrics")

        # Register dynamic configuration commands
        registry.register('restart', self._handle_restart, "Restart pipeline (reconnect streams)")
        registry.register('change_model', self._handle_change_model, "Change inference model")
        registry.register('set_fps', self._handle_set_fps, "Change max FPS")
        registry.register('add_stream', self._handle_add_stream, "Add stream to monitoring")
        registry.register('remove_stream', self._handle_remove_stream, "Remove stream from monitoring")

        # Register discovery commands
        registry.register('ping', self._handle_ping, "Health check / discovery (responds with PONG)")
        
        # Register orchestrator integration commands
        registry.register('rename_instance', self._handle_rename_instance, "Rename instance (orchestrator integration)")

        logger.info(
            "Control commands registered",
            extra={
                "component": "processor",
                "event": "commands_registered",
                "commands": ["pause", "resume", "stop", "status", "metrics", "restart",
                            "change_model", "set_fps", "add_stream", "remove_stream", "ping", "rename_instance"]
            }
        )

    def _handle_pause(self):
        """Handle PAUSE command"""
        logger.info(
            "⏸️  Executing PAUSE command",
            extra={
                "component": "processor",
                "event": "pause_command_start",
                "is_running": self.is_running,
                "is_paused": self.is_paused
            }
        )

        # Check pipeline exists (not is_running, because pipeline.start() blocks during connection)
        if self.pipeline and not self.is_paused:
            try:
                # Step 1: Pause sink (immediate stop)
                if self.mqtt_sink:
                    self.mqtt_sink.pause()
                
                # Step 2: Pause stream (stop buffering)
                self.pipeline.pause_stream()
                
                self.is_paused = True
                
                # Step 3: Publish status
                if self.control_plane:
                    self.control_plane.publish_status("paused")
                
                logger.info(
                    "✅ PAUSE completed successfully",
                    extra={
                        "component": "processor",
                        "event": "pause_completed",
                        "is_paused": self.is_paused
                    }
                )
            except Exception as e:
                logger.error(
                    f"❌ PAUSE failed: {e}",
                    extra={
                        "component": "processor",
                        "event": "pause_failed",
                        "error_type": type(e).__name__,
                        "error_message": str(e)
                    },
                    exc_info=True
                )
        else:
            logger.warning(
                "⚠️  Cannot pause: Pipeline not in correct state",
                extra={
                    "component": "processor",
                    "event": "pause_rejected",
                    "is_running": self.is_running,
                    "is_paused": self.is_paused
                }
            )

    def _handle_resume(self):
        """Handle RESUME command"""
        logger.info(
            "▶️  Executing RESUME command",
            extra={
                "component": "processor",
                "event": "resume_command_start",
                "is_running": self.is_running,
                "is_paused": self.is_paused
            }
        )

        # Check pipeline exists and is paused
        if self.pipeline and self.is_paused:
            try:
                # Step 1: Resume stream (start buffering)
                self.pipeline.resume_stream()
                
                # Step 2: Resume sink (start publishing)
                if self.mqtt_sink:
                    self.mqtt_sink.resume()
                
                self.is_paused = False
                
                # Step 3: Publish status
                if self.control_plane:
                    self.control_plane.publish_status("running")
                
                logger.info(
                    "✅ RESUME completed successfully",
                    extra={
                        "component": "processor",
                        "event": "resume_completed",
                        "is_paused": self.is_paused
                    }
                )
            except Exception as e:
                logger.error(
                    f"❌ RESUME failed: {e}",
                    extra={
                        "component": "processor",
                        "event": "resume_failed",
                        "error_type": type(e).__name__,
                        "error_message": str(e)
                    },
                    exc_info=True
                )
        else:
            logger.warning(
                "⚠️  Cannot resume: Pipeline not in paused state",
                extra={
                    "component": "processor",
                    "event": "resume_rejected",
                    "is_running": self.is_running,
                    "is_paused": self.is_paused
                }
            )

    def _handle_stop(self):
        """Handle STOP command"""
        logger.info(
            "⏹️  Executing STOP command",
            extra={
                "component": "processor",
                "event": "stop_command_start",
                "is_running": self.is_running
            }
        )

        # Check pipeline exists (stop should work even if pipeline.start() is still connecting)
        if self.pipeline:
            try:
                self.terminate()
                if self.control_plane:
                    self.control_plane.publish_status("stopped")
                logger.info(
                    "✅ STOP completed successfully",
                    extra={
                        "component": "processor",
                        "event": "stop_completed"
                    }
                )
            except Exception as e:
                logger.error(
                    f"❌ STOP failed: {e}",
                    extra={
                        "component": "processor",
                        "event": "stop_failed",
                        "error_type": type(e).__name__,
                        "error_message": str(e)
                    },
                    exc_info=True
                )
        else:
            logger.warning(
                "⚠️  Cannot stop: Pipeline is not running",
                extra={
                    "component": "processor",
                    "event": "stop_rejected",
                    "is_running": self.is_running
                }
            )

    def _handle_status(self):
        """Handle STATUS command"""
        status = "stopped"
        if self.is_running:
            status = "paused" if self.is_paused else "running"

        logger.info(
            "📋 STATUS query",
            extra={
                "component": "processor",
                "event": "status_query",
                "status": status,
                "is_running": self.is_running,
                "is_paused": self.is_paused
            }
        )

        if self.control_plane:
            self.control_plane.publish_status(status)

    def _handle_metrics(self):
        """Handle METRICS command - Returns full detailed report"""
        logger.info(
            "📊 METRICS query",
            extra={
                "component": "processor",
                "event": "metrics_query"
            }
        )

        if not self.metrics_reporter or not self.watchdog:
            logger.warning(
                "⚠️ Metrics reporting not available",
                extra={
                    "component": "processor",
                    "event": "metrics_unavailable"
                }
            )
            return

        # Get full report from MetricsReporter
        metrics = self.metrics_reporter.get_full_report()

        # Publish to MQTT
        import json
        topic = f"{self.config.control_status_topic}/metrics/{self.config.instance_id}"
        payload = json.dumps(metrics)
        self.mqtt_client.publish(topic, payload, qos=0, retain=False)

        logger.info(
            "✅ METRICS report published",
            extra={
                "component": "processor",
                "event": "metrics_published",
                "inference_throughput": metrics.get("inference_throughput")
            }
        )

    def _handle_ping(self):
        """
        Handle PING command - respond with PONG (full status + config).
        
        Allows orchestrator to:
        - Discover alive processors
        - Sync configuration state
        - Health check
        """
        import time
        
        logger.info(
            "PING received",
            extra={
                "component": "processor",
                "event": "ping_received",
                "instance_id": self.config.instance_id
            }
        )
        
        # Calculate uptime
        uptime_seconds = time.time() - self._start_time if hasattr(self, '_start_time') else 0
        
        # Respond with PONG (full status + config + health)
        if self.control_plane:
            self.control_plane.publish_status(
                status=self._get_current_status(),
                uptime_seconds=uptime_seconds,
                config=self.config.to_status_dict(),
                health={
                    "is_paused": self.is_paused,
                    "pipeline_running": self.is_running and self.pipeline is not None,
                    "mqtt_connected": self.mqtt_client.is_connected() if self.mqtt_client else False,
                    "control_plane_connected": self.control_plane is not None,
                },
                pong=True  # Flag: PING response
            )
        
        logger.info(
            "PONG sent",
            extra={
                "component": "processor",
                "event": "pong_sent",
                "instance_id": self.config.instance_id,
                "uptime_seconds": uptime_seconds
            }
        )
    
    def _get_current_status(self) -> str:
        """Get current processor status string"""
        if not self.is_running:
            return "stopped"
        if self.is_paused:
            return "paused"
        if hasattr(self, '_is_restarting') and self._is_restarting:
            return "restarting"
        return "running"

    def _handle_rename_instance(self, params: dict):
        """
        Handle RENAME_INSTANCE command - change instance_id without restart.
        
        Allows orchestrator to rename instance after spawn.
        
        With single broadcast topic design, rename is trivial:
        - No need to reconnect control plane (same subscription)
        - Only update config.instance_id
        - Status/metrics topics will use new instance_id automatically
        
        Args:
            params: Dict with 'new_instance_id' key
        
        Raises:
            ValueError: If new_instance_id parameter is missing
        """
        new_instance_id = params.get('new_instance_id')
        if not new_instance_id:
            raise ValueError("Missing required parameter: new_instance_id")
        
        old_instance_id = self.config.instance_id
        
        logger.info(
            "RENAME_INSTANCE executing",
            extra={
                "component": "processor",
                "event": "rename_instance_start",
                "old_instance_id": old_instance_id,
                "new_instance_id": new_instance_id
            }
        )
        
        # Update config (simple!)
        self.config.instance_id = new_instance_id
        
        # Control plane will automatically use new instance_id
        # (reads from self.instance_id dynamically)
        if self.control_plane:
            self.control_plane.instance_id = new_instance_id
            self.control_plane.publish_status(
                "running",
                renamed_from=old_instance_id
            )
        
        logger.info(
            "RENAME_INSTANCE completed successfully",
            extra={
                "component": "processor",
                "event": "rename_instance_completed",
                "new_instance_id": new_instance_id
            }
        )

    def _handle_restart(self):
        """
        Handle RESTART command.

        IoT Pattern:
        1. ACK "received" (automatic - done by control_plane)
        2. Publish status "restarting"
        3. Execute restart
        4. Publish status "running" or "error"
        5. ACK "completed" or "error" (automatic - done by control_plane)
        """
        logger.info(
            "RESTART command executing",
            extra={
                "component": "processor",
                "event": "restart_command_start",
                "current_state": "running" if self.is_running else "stopped",
                "stream_count": len(self.config.stream_uris),
                "model_id": self.config.model_id
            }
        )

        # Check if restart already in progress
        if hasattr(self, '_is_restarting') and self._is_restarting:
            logger.warning(
                "Restart already in progress",
                extra={
                    "component": "processor",
                    "event": "restart_rejected",
                    "reason": "restart_in_progress"
                }
            )
            return

        # Publish intermediate status: restarting
        if self.control_plane:
            self.control_plane.publish_status("restarting")

        self._is_restarting = True

        try:
            # Step 1: Terminate current pipeline
            logger.info(
                "Terminating current pipeline",
                extra={
                    "component": "processor",
                    "event": "restart_pipeline_terminate_start"
                }
            )

            if self.pipeline:
                self.pipeline.terminate()
                self.pipeline = None

            self.is_running = False

            logger.info(
                "Pipeline terminated",
                extra={
                    "component": "processor",
                    "event": "restart_pipeline_terminated"
                }
            )

            # Step 2: Stop metrics thread (set watchdog to None)
            if self.watchdog:
                logger.debug(
                    "Stopping metrics reporting thread",
                    extra={
                        "component": "processor",
                        "event": "restart_metrics_stop"
                    }
                )
                self.watchdog = None

            # Step 3: Recreate pipeline with current config
            logger.info(
                "Recreating pipeline from current config",
                extra={
                    "component": "processor",
                    "event": "restart_pipeline_recreate_start",
                    "stream_count": len(self.config.stream_uris),
                    "model_id": self.config.model_id,
                    "max_fps": self.config.max_fps
                }
            )

            from inference import InferencePipeline
            from inference.core.interfaces.stream.watchdog import BasePipelineWatchDog

            # Recreate watchdog if enabled
            if self.config.enable_watchdog:
                self.watchdog = BasePipelineWatchDog()

            # Recreate pipeline (reuse existing sink!)
            self.pipeline = InferencePipeline.init(
                video_reference=self.config.stream_uris,
                model_id=self.config.model_id,
                on_prediction=self.mqtt_sink,  # Sink persists!
                watchdog=self.watchdog,
                max_fps=self.config.max_fps,
            )

            logger.info(
                "Pipeline recreated",
                extra={
                    "component": "processor",
                    "event": "restart_pipeline_recreated"
                }
            )

            # Step 4: Restart metrics reporting if enabled
            if self.watchdog and self.config.metrics_reporting_interval > 0:
                # Stop old reporter if exists
                if self.metrics_reporter:
                    self.metrics_reporter.stop()

                # Create and start new reporter with new watchdog
                self.metrics_reporter = MetricsReporter(
                    watchdog=self.watchdog,
                    mqtt_client=self.mqtt_client,
                    config=self.config
                )
                self.metrics_reporter.start()

                logger.debug(
                    "Metrics reporting thread restarted",
                    extra={
                        "component": "processor",
                        "event": "restart_metrics_started",
                        "interval": self.config.metrics_reporting_interval
                    }
                )

            # Step 5: Start new pipeline
            logger.info(
                "Starting new pipeline",
                extra={
                    "component": "processor",
                    "event": "restart_pipeline_start_attempt"
                }
            )

            self.pipeline.start(use_main_thread=False)
            self._pipeline_started = True
            self.is_running = True
            self.is_paused = False

            logger.info(
                "RESTART completed successfully",
                extra={
                    "component": "processor",
                    "event": "restart_completed",
                    "new_state": "running",
                    "stream_count": len(self.config.stream_uris),
                    "model_id": self.config.model_id
                }
            )

            # Step 6: Publish final status: running
            if self.control_plane:
                self.control_plane.publish_status("running")

        except Exception as e:
            logger.error(
                "RESTART failed",
                extra={
                    "component": "processor",
                    "event": "restart_failed",
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "new_state": "error"
                },
                exc_info=True
            )

            self.is_running = False

            # Publish error status
            if self.control_plane:
                self.control_plane.publish_status("error")

            # Re-raise to trigger ACK error in control_plane
            raise

        finally:
            self._is_restarting = False

    def _handle_change_model(self, params: dict):
        """
        Handle CHANGE_MODEL command.

        Params:
            model_id (str): New model ID (e.g., "yolov11x-640")

        IoT Pattern:
        1. ACK "received" (automatic)
        2. Status "reconfiguring"
        3. Execute change
        4. Status "running" or "error"
        5. ACK "completed" or "error" (automatic)
        """
        new_model_id = params.get('model_id')
        if not new_model_id:
            raise ValueError("Missing required parameter: model_id")

        old_model_id = self.config.model_id

        logger.info(
            "CHANGE_MODEL command executing",
            extra={
                "component": "processor",
                "event": "change_model_command_start",
                "old_model_id": old_model_id,
                "new_model_id": new_model_id
            }
        )

        # Publish intermediate status
        if self.control_plane:
            self.control_plane.publish_status("reconfiguring")

        try:
            # Update config
            self.config.model_id = new_model_id

            logger.info(
                "Model config updated, restarting pipeline",
                extra={
                    "component": "processor",
                    "event": "change_model_config_updated",
                    "new_model_id": new_model_id
                }
            )

            # Trigger restart with new config
            # Note: This will set _is_restarting, terminate, recreate, restart
            # The restart handler will publish "running" status when done
            self._handle_restart()

            logger.info(
                "CHANGE_MODEL completed successfully",
                extra={
                    "component": "processor",
                    "event": "change_model_completed",
                    "old_model_id": old_model_id,
                    "new_model_id": new_model_id
                }
            )

        except Exception as e:
            # Rollback on failure
            self.config.model_id = old_model_id

            logger.error(
                "CHANGE_MODEL failed, rolled back",
                extra={
                    "component": "processor",
                    "event": "change_model_failed",
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "rolled_back_to": old_model_id
                },
                exc_info=True
            )

            if self.control_plane:
                self.control_plane.publish_status("error")

            raise

    def _handle_set_fps(self, params: dict):
        """
        Handle SET_FPS command.

        Params:
            max_fps (float): New max FPS (e.g., 1.0, 0.1)

        IoT Pattern: Same as change_model
        """
        new_fps = params.get('max_fps')
        if new_fps is None:
            raise ValueError("Missing required parameter: max_fps")

        # Validate FPS
        try:
            new_fps = float(new_fps)
            if new_fps <= 0:
                raise ValueError("max_fps must be > 0")
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid max_fps value: {new_fps}") from e

        old_fps = self.config.max_fps

        logger.info(
            "SET_FPS command executing",
            extra={
                "component": "processor",
                "event": "set_fps_command_start",
                "old_fps": old_fps,
                "new_fps": new_fps
            }
        )

        if self.control_plane:
            self.control_plane.publish_status("reconfiguring")

        try:
            # Update config
            self.config.max_fps = new_fps

            logger.info(
                "FPS config updated, restarting pipeline",
                extra={
                    "component": "processor",
                    "event": "set_fps_config_updated",
                    "new_fps": new_fps
                }
            )

            # Restart pipeline
            self._handle_restart()

            logger.info(
                "SET_FPS completed successfully",
                extra={
                    "component": "processor",
                    "event": "set_fps_completed",
                    "old_fps": old_fps,
                    "new_fps": new_fps
                }
            )

        except Exception as e:
            # Rollback
            self.config.max_fps = old_fps

            logger.error(
                "SET_FPS failed, rolled back",
                extra={
                    "component": "processor",
                    "event": "set_fps_failed",
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "rolled_back_to": old_fps
                },
                exc_info=True
            )

            if self.control_plane:
                self.control_plane.publish_status("error")

            raise

    def _handle_add_stream(self, params: dict):
        """
        Handle ADD_STREAM command.

        Params:
            source_id (int): Source ID (room number) to add (e.g., 8)

        Stream URI is constructed automatically from stream_server config:
            rtsp://{stream_server}/{source_id}

        Example:
            source_id=8 → rtsp://go2rtc-server/8

        IoT Pattern: Same as change_model
        """
        source_id = params.get('source_id')

        if source_id is None:
            raise ValueError("Missing required parameter: source_id")

        # Validate source_id
        try:
            source_id = int(source_id)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid source_id value: {source_id}") from e

        logger.info(
            "ADD_STREAM command executing",
            extra={
                "component": "processor",
                "event": "add_stream_command_start",
                "source_id": source_id,
                "current_stream_count": len(self.config.stream_uris)
            }
        )

        if self.control_plane:
            self.control_plane.publish_status("reconfiguring")

        # Backup for rollback
        old_stream_uris = list(self.config.stream_uris)
        old_source_id_mapping = list(self.config.source_id_mapping) if self.config.source_id_mapping else []

        try:
            # Use config's add_stream method (validates + constructs URI)
            self.config.add_stream(source_id)

            stream_uri = self.config.stream_uris[-1]  # Just added

            logger.info(
                "Stream config updated, restarting pipeline",
                extra={
                    "component": "processor",
                    "event": "add_stream_config_updated",
                    "new_stream_count": len(self.config.stream_uris),
                    "added_stream_uri": stream_uri
                }
            )

            # Restart pipeline
            self._handle_restart()

            logger.info(
                "ADD_STREAM completed successfully",
                extra={
                    "component": "processor",
                    "event": "add_stream_completed",
                    "source_id": source_id,
                    "stream_uri": stream_uri,
                    "new_stream_count": len(self.config.stream_uris)
                }
            )

        except (ConfigValidationError, Exception) as e:
            # Rollback to backup
            self.config.stream_uris = old_stream_uris
            self.config.source_id_mapping = old_source_id_mapping

            logger.error(
                "ADD_STREAM failed, rolled back",
                extra={
                    "component": "processor",
                    "event": "add_stream_failed",
                    "error_type": type(e).__name__,
                    "error_message": str(e)
                },
                exc_info=True
            )

            if self.control_plane:
                self.control_plane.publish_status("error")

            raise

    def _handle_remove_stream(self, params: dict):
        """
        Handle REMOVE_STREAM command.

        Params:
            source_id (int): Source ID to remove (e.g., 2)

        IoT Pattern: Same as change_model
        """
        source_id = params.get('source_id')

        if source_id is None:
            raise ValueError("Missing required parameter: source_id")

        # Validate source_id
        try:
            source_id = int(source_id)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid source_id value: {source_id}") from e

        logger.info(
            "REMOVE_STREAM command executing",
            extra={
                "component": "processor",
                "event": "remove_stream_command_start",
                "source_id": source_id,
                "current_stream_count": len(self.config.stream_uris)
            }
        )

        if self.control_plane:
            self.control_plane.publish_status("reconfiguring")

        # Backup for rollback
        old_stream_uris = list(self.config.stream_uris)
        old_source_id_mapping = list(self.config.source_id_mapping) if self.config.source_id_mapping else []

        try:
            # Use config's remove_stream method (validates + removes)
            self.config.remove_stream(source_id)

            logger.info(
                "Stream config updated, restarting pipeline",
                extra={
                    "component": "processor",
                    "event": "remove_stream_config_updated",
                    "new_stream_count": len(self.config.stream_uris)
                }
            )

            # Restart pipeline
            self._handle_restart()

            logger.info(
                "REMOVE_STREAM completed successfully",
                extra={
                    "component": "processor",
                    "event": "remove_stream_completed",
                    "source_id": source_id,
                    "new_stream_count": len(self.config.stream_uris)
                }
            )

        except (ConfigValidationError, Exception) as e:
            # Rollback to backup
            self.config.stream_uris = old_stream_uris
            self.config.source_id_mapping = old_source_id_mapping

            logger.error(
                "REMOVE_STREAM failed, rolled back",
                extra={
                    "component": "processor",
                    "event": "remove_stream_failed",
                    "error_type": type(e).__name__,
                    "error_message": str(e)
                },
                exc_info=True
            )

            if self.control_plane:
                self.control_plane.publish_status("error")

            raise

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
                "component": "processor",
                "event": "mqtt_connection_start",
                "mqtt_host": self.config.mqtt_host,
                "mqtt_port": self.config.mqtt_port
            }
        )
        client.connect(self.config.mqtt_host, self.config.mqtt_port)
        client.loop_start()

        return client

    def _signal_handler(self, signum, frame):
        """Handle termination signals"""
        logger.info(
            f"Received signal {signum}, shutting down...",
            extra={
                "component": "processor",
                "event": "signal_received",
                "signal": signum
            }
        )
        self.terminate()

