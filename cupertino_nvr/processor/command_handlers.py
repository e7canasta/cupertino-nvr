"""
Command Handlers for StreamProcessor Control Plane
===================================================

Handles all MQTT control commands (pause/resume/stop/restart/dynamic config).

Extracted from StreamProcessor per DESIGN_CONSULTANCY_REFACTORING.md (Prioridad 1, Paso 1).
"""

import logging
import json
import time
from typing import Protocol, Optional, Any, Callable

from cupertino_nvr.logging_utils import get_component_logger
from cupertino_nvr.processor.config import ConfigValidationError
from cupertino_nvr.processor.validators import CommandValidators, CommandValidationError

logger = get_component_logger(__name__, "command_handlers")


# ============================================================================
# Protocol: PipelineController (interface for pipeline lifecycle)
# ============================================================================

class PipelineController(Protocol):
    """
    Protocol for controlling pipeline lifecycle.

    This allows CommandHandlers to work with any pipeline manager
    that implements these methods (not just InferencePipelineManager).
    """

    def pause_pipeline(self) -> None:
        """Pause stream processing."""
        ...

    def resume_pipeline(self) -> None:
        """Resume stream processing."""
        ...

    def terminate_pipeline(self) -> None:
        """Terminate pipeline completely."""
        ...

    def restart_pipeline(self, new_config: Optional[dict] = None) -> None:
        """Restart pipeline (terminate + recreate + start)."""
        ...


# ============================================================================
# CommandHandlers: Centralized MQTT command execution
# ============================================================================

class CommandHandlers:
    """
    Centralized command handlers for MQTT control plane.

    Separates command execution logic from StreamProcessor lifecycle.
    Each command handler is small, focused, and testable.

    Responsibilities:
    - Execute control commands (pause/resume/stop/restart)
    - Execute dynamic config commands (change_model/set_fps/add_stream/remove_stream)
    - Execute observability commands (status/metrics/ping)
    - Execute orchestration commands (rename_instance)

    Args:
        pipeline_manager: Interface to control the inference pipeline
        config: StreamProcessorConfig instance (for dynamic updates)
        control_plane: MQTTControlPlane for status publishing
        metrics_reporter: Optional MetricsReporter (for METRICS command)
        mqtt_client: Optional MQTT client (for direct publishing in METRICS)
        processor: Optional reference to StreamProcessor (for uptime tracking in PING)

    Usage:
        >>> handlers = CommandHandlers(
        ...     pipeline_manager=pipeline_manager,
        ...     config=config,
        ...     control_plane=control_plane
        ... )
        >>> handlers.handle_pause()
        >>> handlers.handle_change_model({"model_id": "yolov11x-640"})
    """

    def __init__(
        self,
        pipeline_manager: PipelineController,
        config: Any,  # StreamProcessorConfig
        control_plane: Any,  # MQTTControlPlane
        metrics_reporter: Optional[Any] = None,
        mqtt_client: Optional[Any] = None,
        processor: Optional[Any] = None
    ):
        self.pipeline = pipeline_manager
        self.config = config
        self.control_plane = control_plane
        self.metrics_reporter = metrics_reporter
        self.mqtt_client = mqtt_client
        self.processor = processor

    # ========================================================================
    # Basic Control Commands
    # ========================================================================

    def handle_pause(self):
        """
        Handle PAUSE command - immediate stop of processing.

        Two-level pause:
        1. Sink pause (immediate MQTT stop)
        2. Pipeline pause (stop buffering)
        """
        logger.info(
            "⏸️  Executing PAUSE command",
            extra={"event": "pause_command_start"}
        )

        try:
            self.pipeline.pause_pipeline()
            self.control_plane.publish_status("paused")
            logger.info("✅ PAUSE completed", extra={"event": "pause_completed"})
        except Exception as e:
            logger.error(
                f"❌ PAUSE failed: {e}",
                extra={
                    "event": "pause_failed",
                    "error_type": type(e).__name__,
                    "error_message": str(e)
                },
                exc_info=True
            )
            raise

    def handle_resume(self):
        """
        Handle RESUME command - resume processing.

        Resume order:
        1. Pipeline resume (start buffering)
        2. Sink resume (start MQTT publishing)
        """
        logger.info(
            "▶️  Executing RESUME command",
            extra={"event": "resume_command_start"}
        )

        try:
            self.pipeline.resume_pipeline()
            self.control_plane.publish_status("running")
            logger.info("✅ RESUME completed", extra={"event": "resume_completed"})
        except Exception as e:
            logger.error(
                f"❌ RESUME failed: {e}",
                extra={
                    "event": "resume_failed",
                    "error_type": type(e).__name__,
                    "error_message": str(e)
                },
                exc_info=True
            )
            raise

    def handle_stop(self):
        """
        Handle STOP command - terminate completely.

        This triggers graceful shutdown of the entire processor.
        """
        logger.info(
            "⏹️  Executing STOP command",
            extra={"event": "stop_command_start"}
        )

        try:
            self.pipeline.terminate_pipeline()
            self.control_plane.publish_status("stopped")
            logger.info("✅ STOP completed", extra={"event": "stop_completed"})
        except Exception as e:
            logger.error(
                f"❌ STOP failed: {e}",
                extra={
                    "event": "stop_failed",
                    "error_type": type(e).__name__,
                    "error_message": str(e)
                },
                exc_info=True
            )
            raise

    def handle_restart(self):
        """
        Handle RESTART command - full pipeline restart.

        IoT Pattern:
        1. ACK "received" (automatic - done by control_plane)
        2. Publish status "restarting"
        3. Execute restart (with coordination)
        4. Publish status "running" or "error"
        5. ACK "completed" or "error" (automatic - done by control_plane)
        """
        logger.info(
            "🔄 RESTART command executing",
            extra={"event": "restart_command_start"}
        )

        # Publish intermediate status
        if self.control_plane:
            self.control_plane.publish_status("restarting")

        try:
            # Use restart_with_coordination (handles flag internally)
            self.pipeline.restart_with_coordination(coordinator=self.processor)

            self.control_plane.publish_status("running")
            logger.info("✅ RESTART completed", extra={"event": "restart_completed"})
        except Exception as e:
            logger.error(
                f"❌ RESTART failed: {e}",
                extra={
                    "event": "restart_failed",
                    "error_type": type(e).__name__,
                    "error_message": str(e)
                },
                exc_info=True
            )
            self.control_plane.publish_status("error")
            raise

    # ========================================================================
    # Dynamic Configuration Commands (with Template Method)
    # ========================================================================

    def handle_change_model(self, params: dict):
        """
        Handle CHANGE_MODEL command with automatic rollback on failure.

        Params:
            model_id (str): New model ID (e.g., "yolov11x-640")

        Uses template method pattern to eliminate duplication.
        """
        return self._execute_config_change(
            param_name="model_id",
            param_value=params.get("model_id"),
            validator=CommandValidators.validate_model_id,
            config_attr="model_id",
            command_name="CHANGE_MODEL"
        )

    def handle_set_fps(self, params: dict):
        """
        Handle SET_FPS command with validation and rollback.

        Params:
            max_fps (float): New max FPS (e.g., 1.0, 0.1)
        """
        return self._execute_config_change(
            param_name="max_fps",
            param_value=params.get("max_fps"),
            validator=CommandValidators.validate_fps,
            config_attr="max_fps",
            command_name="SET_FPS"
        )

    def handle_add_stream(self, params: dict):
        """
        Handle ADD_STREAM command.

        Params:
            source_id (int): Source ID to add (e.g., 8)

        Stream URI is constructed automatically from stream_server config.
        """
        # Validate parameter presence
        source_id = params.get("source_id")
        if source_id is None:
            raise ValueError("Missing required parameter: source_id")

        # Validate source_id (replaces inline try/except)
        source_id = CommandValidators.validate_source_id(source_id)

        # Execute using template method
        return self._execute_stream_change(
            source_id=source_id,
            operation=self.config.add_stream,
            command_name="ADD_STREAM"
        )

    def handle_remove_stream(self, params: dict):
        """
        Handle REMOVE_STREAM command.

        Params:
            source_id (int): Source ID to remove (e.g., 2)
        """
        # Validate parameter presence
        source_id = params.get("source_id")
        if source_id is None:
            raise ValueError("Missing required parameter: source_id")

        # Validate source_id (replaces inline try/except)
        source_id = CommandValidators.validate_source_id(source_id)

        # Execute using template method
        return self._execute_stream_change(
            source_id=source_id,
            operation=self.config.remove_stream,
            command_name="REMOVE_STREAM"
        )

    # ========================================================================
    # Observability Commands
    # ========================================================================

    def handle_status(self):
        """
        Handle STATUS command - query current status.

        Returns current processor state: running/paused/stopped.
        """
        # Get status from processor if available
        if self.processor and hasattr(self.processor, '_get_current_status'):
            status = self.processor._get_current_status()
        else:
            # Fallback: simple status based on pipeline state
            status = "running"  # Simplified

        logger.info(
            "📋 STATUS query",
            extra={
                "event": "status_query",
                "status": status
            }
        )

        if self.control_plane:
            self.control_plane.publish_status(status)

    def handle_metrics(self):
        """
        Handle METRICS command - returns full detailed report.

        Publishes complete watchdog metrics to MQTT.
        """
        logger.info(
            "📊 METRICS query",
            extra={"event": "metrics_query"}
        )

        if not self.metrics_reporter:
            logger.warning(
                "⚠️ Metrics reporting not available",
                extra={"event": "metrics_unavailable"}
            )
            return

        # Get full report from MetricsReporter
        metrics = self.metrics_reporter.get_full_report()

        # Publish to MQTT
        topic = f"{self.config.control_status_topic}/metrics/{self.config.instance_id}"
        payload = json.dumps(metrics)
        self.mqtt_client.publish(topic, payload, qos=0, retain=False)

        logger.info(
            "✅ METRICS report published",
            extra={
                "event": "metrics_published",
                "inference_throughput": metrics.get("inference_throughput")
            }
        )

    def handle_ping(self):
        """
        Handle PING command - respond with PONG (full status + config).

        Allows orchestrator to:
        - Discover alive processors
        - Sync configuration state
        - Health check
        """
        logger.info(
            "🏓 PING received",
            extra={
                "event": "ping_received",
                "instance_id": self.config.instance_id
            }
        )

        # Calculate uptime from processor's _start_time
        uptime_seconds = 0
        if self.processor and hasattr(self.processor, '_start_time'):
            uptime_seconds = time.time() - self.processor._start_time

        # Get current status
        if self.processor and hasattr(self.processor, '_get_current_status'):
            status = self.processor._get_current_status()
        else:
            status = "running"

        # Respond with PONG (full status + config + health)
        if self.control_plane:
            health = {}
            if self.processor:
                health = {
                    "is_paused": getattr(self.processor, 'is_paused', False),
                    "pipeline_running": getattr(self.processor, 'is_running', False),
                    "mqtt_connected": self.mqtt_client.is_connected() if self.mqtt_client else False,
                    "control_plane_connected": self.control_plane is not None,
                }

            self.control_plane.publish_status(
                status=status,
                uptime_seconds=uptime_seconds,
                config=self.config.to_status_dict(),
                health=health,
                pong=True  # Flag: PING response
            )

        logger.info(
            "PONG sent",
            extra={
                "event": "pong_sent",
                "instance_id": self.config.instance_id,
                "uptime_seconds": uptime_seconds
            }
        )

    def handle_rename_instance(self, params: dict):
        """
        Handle RENAME_INSTANCE command - change instance_id without restart.

        Allows orchestrator to rename instance after spawn.

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
                "event": "rename_instance_start",
                "old_instance_id": old_instance_id,
                "new_instance_id": new_instance_id
            }
        )

        # Update config
        self.config.instance_id = new_instance_id

        # Update control plane instance_id
        if self.control_plane:
            self.control_plane.instance_id = new_instance_id
            self.control_plane.publish_status(
                "running",
                renamed_from=old_instance_id
            )

        logger.info(
            "RENAME_INSTANCE completed successfully",
            extra={
                "event": "rename_instance_completed",
                "new_instance_id": new_instance_id
            }
        )

    # ========================================================================
    # Private: Template Method Pattern for Config Changes
    # ========================================================================

    def _execute_config_change(
        self,
        param_name: str,
        param_value: Any,
        validator: Callable[[Any], Any],
        config_attr: str,
        command_name: str
    ):
        """
        Template method for config change commands.

        Pattern: Validate → Backup → Publish status → Execute → Rollback on error

        This eliminates duplication across change_model/set_fps commands.

        Args:
            param_name: Parameter name (for error messages)
            param_value: Parameter value to validate
            validator: Validator function (returns validated value or raises)
            config_attr: Config attribute to update
            command_name: Command name (for logging)

        Raises:
            ValueError: If validation fails
            Exception: If restart fails (after rollback)
        """
        # 1. Validate params
        if param_value is None:
            raise ValueError(f"Missing required parameter: {param_name}")

        validated_value = validator(param_value)

        # 2. Backup for rollback
        old_value = getattr(self.config, config_attr)

        logger.info(
            f"{command_name} executing",
            extra={
                "event": f"{command_name.lower()}_command_start",
                f"old_{config_attr}": old_value,
                f"new_{config_attr}": validated_value
            }
        )

        # 3. Publish intermediate status
        if self.control_plane:
            self.control_plane.publish_status("reconfiguring")

        try:
            # 4. Update config
            setattr(self.config, config_attr, validated_value)

            logger.info(
                f"Config updated: {config_attr}={validated_value}",
                extra={
                    "event": f"{command_name.lower()}_config_updated",
                    config_attr: validated_value
                }
            )

            # 5. Restart pipeline with coordination
            self.pipeline.restart_with_coordination(coordinator=self.processor)

            logger.info(
                f"✅ {command_name} completed",
                extra={"event": f"{command_name.lower()}_completed"}
            )

        except Exception as e:
            # 6. Rollback on failure
            setattr(self.config, config_attr, old_value)

            if self.control_plane:
                self.control_plane.publish_status("error")

            logger.error(
                f"❌ {command_name} failed, rolled back",
                extra={
                    "event": f"{command_name.lower()}_failed",
                    f"rolled_back_to": old_value,
                    "error_type": type(e).__name__,
                    "error_message": str(e)
                },
                exc_info=True
            )
            raise

    def _execute_stream_change(
        self,
        source_id: int,
        operation: Callable[[int], None],
        command_name: str
    ) -> None:
        """
        Template method for stream change commands (add/remove).

        Pattern: Validate → Backup → Execute → Rollback on error

        This eliminates duplication between handle_add_stream and handle_remove_stream.

        Args:
            source_id: Stream source ID to add or remove
            operation: Config method to call (config.add_stream or config.remove_stream)
            command_name: Command name for logging (e.g., "ADD_STREAM", "REMOVE_STREAM")

        Raises:
            ConfigValidationError: If validation or operation fails (after rollback)
        """
        logger.info(
            f"{command_name} executing",
            extra={
                "event": f"{command_name.lower()}_command_start",
                "source_id": source_id,
                "current_stream_count": len(self.config.stream_uris)
            }
        )

        # Publish intermediate status
        if self.control_plane:
            self.control_plane.publish_status("reconfiguring")

        # Backup for rollback (defensive copy)
        old_stream_uris = list(self.config.stream_uris)
        old_source_id_mapping = list(self.config.source_id_mapping) if self.config.source_id_mapping else []

        try:
            # Execute operation (config.add_stream(source_id) or config.remove_stream(source_id))
            operation(source_id)

            logger.info(
                f"Stream config updated, restarting pipeline",
                extra={
                    "event": f"{command_name.lower()}_config_updated",
                    "new_stream_count": len(self.config.stream_uris)
                }
            )

            # Restart pipeline with coordination
            self.pipeline.restart_with_coordination(coordinator=self.processor)

            logger.info(
                f"✅ {command_name} completed successfully",
                extra={
                    "event": f"{command_name.lower()}_completed",
                    "source_id": source_id,
                    "new_stream_count": len(self.config.stream_uris)
                }
            )

        except (ConfigValidationError, Exception) as e:
            # Rollback to backup
            self.config.stream_uris = old_stream_uris
            self.config.source_id_mapping = old_source_id_mapping

            logger.error(
                f"❌ {command_name} failed, rolled back",
                extra={
                    "event": f"{command_name.lower()}_failed",
                    "error_type": type(e).__name__,
                    "error_message": str(e)
                },
                exc_info=True
            )

            if self.control_plane:
                self.control_plane.publish_status("error")

            raise


