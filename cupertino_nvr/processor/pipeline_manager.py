"""
Inference Pipeline Lifecycle Manager
=====================================

Manages InferencePipeline lifecycle: creation, start, pause, resume, restart, terminate.

Extracted from StreamProcessor per DESIGN_CONSULTANCY_REFACTORING.md (Prioridad 1, Paso 2).
"""

import logging
import os
from typing import Optional, Any

from cupertino_nvr.logging_utils import get_component_logger

logger = get_component_logger(__name__, "pipeline_manager")


class InferencePipelineManager:
    """
    Manages InferencePipeline lifecycle.

    Responsibilities:
    - Create pipeline from config
    - Start/stop pipeline
    - Pause/resume streaming (two-level: sink + pipeline)
    - Restart pipeline (terminate + recreate + start)
    - Watchdog management

    This class isolates all InferencePipeline-specific logic from StreamProcessor,
    enabling easier testing and maintenance.

    Args:
        config: StreamProcessorConfig instance
        mqtt_sink: MQTTDetectionSink instance (for on_prediction callback)
        watchdog: Optional watchdog instance (created internally if config.enable_watchdog)

    Usage:
        >>> manager = InferencePipelineManager(config, mqtt_sink, watchdog=None)
        >>> manager.create_pipeline()
        >>> manager.start_pipeline()  # Blocks during stream connection
        >>> # Later...
        >>> manager.pause_pipeline()
        >>> manager.resume_pipeline()
        >>> manager.restart_pipeline()
        >>> manager.terminate_pipeline()
    """

    def __init__(
        self,
        config: Any,  # StreamProcessorConfig
        mqtt_sink: Any,  # MQTTDetectionSink
        watchdog: Optional[object] = None
    ):
        self.config = config
        self.mqtt_sink = mqtt_sink
        self.watchdog = watchdog
        self.pipeline: Optional[object] = None
        self.is_paused = False
        self._pipeline_started = False

    def create_pipeline(self):
        """
        Create InferencePipeline instance (but don't start yet).

        Returns:
            InferencePipeline instance
        """
        # Import here to avoid hard dependency at module level
        from inference import InferencePipeline
        from inference.core.interfaces.stream.watchdog import BasePipelineWatchDog

        # Create watchdog if enabled and not provided
        if self.config.enable_watchdog and not self.watchdog:
            self.watchdog = BasePipelineWatchDog()
            logger.debug(
                "Watchdog created",
                extra={"event": "watchdog_created"}
            )

        logger.info(
            "Creating InferencePipeline",
            extra={
                "event": "pipeline_create_start",
                "model_id": self.config.model_id,
                "stream_count": len(self.config.stream_uris),
                "max_fps": self.config.max_fps,
                "enable_watchdog": self.config.enable_watchdog
            }
        )

        self.pipeline = InferencePipeline.init(
            video_reference=self.config.stream_uris,
            model_id=self.config.model_id,
            on_prediction=self.mqtt_sink,
            watchdog=self.watchdog,
            max_fps=self.config.max_fps,
        )

        logger.info(
            "Pipeline created successfully",
            extra={"event": "pipeline_created"}
        )

        return self.pipeline

    def start_pipeline(self):
        """
        Start pipeline processing (blocks during stream connection).

        Raises:
            RuntimeError: If pipeline not created yet
        """
        if not self.pipeline:
            raise RuntimeError("Pipeline not created. Call create_pipeline() first.")

        logger.info(
            "▶️  Starting pipeline (may block connecting to streams)...",
            extra={"event": "pipeline_start_attempt"}
        )

        # Enable frame dropping for better performance (from v0.26.0)
        os.environ["ENABLE_FRAME_DROP_ON_VIDEO_FILE_RATE_LIMITING"] = "True"

        # Start pipeline (use_main_thread=False to avoid blocking main thread)
        self.pipeline.start(use_main_thread=False)
        self._pipeline_started = True

        logger.info(
            "✅ Pipeline started successfully",
            extra={"event": "pipeline_started"}
        )

    def pause_pipeline(self):
        """
        Pause pipeline processing (two-level: sink + stream).

        Two-level pause pattern:
        1. Pause sink FIRST (immediate stop of MQTT publications)
        2. Pause pipeline (stop buffering new frames - gradual)

        This ensures immediate stop of detections publishing while pipeline
        processes remaining frames in prediction queue (~5-10s).
        """
        if not self.pipeline or self.is_paused:
            logger.warning(
                "Cannot pause: pipeline not running or already paused",
                extra={
                    "event": "pause_rejected",
                    "pipeline_exists": self.pipeline is not None,
                    "is_paused": self.is_paused
                }
            )
            return

        logger.info(
            "⏸️  Pausing pipeline",
            extra={"event": "pause_start"}
        )

        # Step 1: Pause sink FIRST (immediate stop)
        if self.mqtt_sink:
            self.mqtt_sink.pause()
            logger.debug("Sink paused (immediate)", extra={"event": "sink_paused"})

        # Step 2: Pause pipeline (gradual - frames in queue still process)
        self.pipeline.pause_stream()
        logger.debug("Pipeline paused (gradual)", extra={"event": "pipeline_paused"})

        self.is_paused = True

        logger.info(
            "✅ Pipeline paused",
            extra={"event": "pause_completed"}
        )

    def resume_pipeline(self):
        """
        Resume pipeline processing.

        Resume order (opposite of pause):
        1. Resume pipeline FIRST (start buffering frames)
        2. Resume sink (start publishing detections)
        """
        if not self.pipeline or not self.is_paused:
            logger.warning(
                "Cannot resume: pipeline not paused",
                extra={
                    "event": "resume_rejected",
                    "pipeline_exists": self.pipeline is not None,
                    "is_paused": self.is_paused
                }
            )
            return

        logger.info(
            "▶️  Resuming pipeline",
            extra={"event": "resume_start"}
        )

        # Step 1: Resume pipeline FIRST (start buffering)
        self.pipeline.resume_stream()
        logger.debug("Pipeline resumed", extra={"event": "pipeline_resumed"})

        # Step 2: Resume sink (start publishing)
        if self.mqtt_sink:
            self.mqtt_sink.resume()
            logger.debug("Sink resumed", extra={"event": "sink_resumed"})

        self.is_paused = False

        logger.info(
            "✅ Pipeline resumed",
            extra={"event": "resume_completed"}
        )

    def restart_pipeline(self, new_config: Optional[dict] = None):
        """
        Restart pipeline (terminate + recreate + start).

        This is used for dynamic configuration changes (model, fps, streams).

        Args:
            new_config: Optional dict of config updates to apply before restart.
                       Keys are config attribute names (e.g., {"model_id": "yolov11x-640"})

        Workflow:
        1. Terminate current pipeline
        2. Apply config updates (if provided)
        3. Recreate watchdog (if enabled)
        4. Recreate pipeline with new config
        5. Start new pipeline
        """
        logger.info(
            "🔄 Restarting pipeline",
            extra={
                "event": "restart_start",
                "config_updates": list(new_config.keys()) if new_config else None
            }
        )

        # Step 1: Terminate old pipeline
        if self.pipeline:
            logger.debug("Terminating old pipeline", extra={"event": "restart_terminate_old"})
            self.pipeline.terminate()
            self.pipeline = None
            self._pipeline_started = False

        # Step 2: Apply config updates if provided
        if new_config:
            for key, value in new_config.items():
                old_value = getattr(self.config, key, None)
                setattr(self.config, key, value)
                logger.debug(
                    f"Config updated: {key}",
                    extra={
                        "event": "restart_config_update",
                        "config_key": key,
                        "old_value": old_value,
                        "new_value": value
                    }
                )

        # Step 3: Recreate watchdog if enabled
        if self.config.enable_watchdog:
            from inference.core.interfaces.stream.watchdog import BasePipelineWatchDog
            self.watchdog = BasePipelineWatchDog()
            logger.debug("Watchdog recreated", extra={"event": "restart_watchdog_recreated"})
        else:
            self.watchdog = None

        # Step 4: Recreate pipeline
        logger.info(
            "Recreating pipeline with config",
            extra={
                "event": "restart_recreate_pipeline",
                "model_id": self.config.model_id,
                "stream_count": len(self.config.stream_uris),
                "max_fps": self.config.max_fps
            }
        )
        self.create_pipeline()

        # Step 5: Start new pipeline
        logger.info(
            "Starting new pipeline",
            extra={"event": "restart_start_new_pipeline"}
        )
        self.start_pipeline()
        self.is_paused = False

        logger.info(
            "✅ Pipeline restarted successfully",
            extra={"event": "restart_completed"}
        )

    def restart_with_coordination(
        self,
        new_config: Optional[dict] = None,
        coordinator: Optional[Any] = None
    ) -> None:
        """
        Restart pipeline with coordination flag management.

        Centralizes restart logic + flag setting for join() detection.
        The coordinator (StreamProcessor) sets _is_restarting flag to signal
        join() that this is a restart, not a shutdown.

        Args:
            new_config: Optional dict of config updates to apply before restart
            coordinator: Optional StreamProcessor reference (for _is_restarting flag)

        Example:
            >>> # CommandHandlers calls this instead of restart_pipeline()
            >>> self.pipeline.restart_with_coordination(
            ...     new_config={"model_id": "yolov11x-640"},
            ...     coordinator=self.processor
            ... )

        Note:
            This method is the ONLY place where _is_restarting flag should be managed.
            Command handlers should call this method instead of restart_pipeline() directly.
        """
        # Set coordination flag BEFORE restarting
        if coordinator:
            coordinator._is_restarting = True

        try:
            # Delegate to restart_pipeline (actual restart logic)
            self.restart_pipeline(new_config=new_config)
        finally:
            # Clear coordination flag AFTER restart completes (or fails)
            if coordinator:
                coordinator._is_restarting = False

    def terminate_pipeline(self):
        """
        Terminate pipeline completely.

        This stops all stream processing and cleans up resources.
        """
        if self.pipeline:
            logger.info(
                "⏹️  Terminating pipeline",
                extra={"event": "pipeline_terminate_start"}
            )

            self.pipeline.terminate()
            self.pipeline = None
            self._pipeline_started = False
            self.is_paused = False

            logger.info(
                "✅ Pipeline terminated",
                extra={"event": "pipeline_terminated"}
            )
        else:
            logger.debug(
                "Pipeline already terminated or not created",
                extra={"event": "pipeline_already_terminated"}
            )
