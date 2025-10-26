"""
Metrics Reporter
================

Handles metrics collection and periodic reporting to MQTT.

Extraído de StreamProcessor para separar la responsabilidad de reporting
según el diseño propuesto en DESIGN_CONSULTANCY_REFACTORING.md (Prioridad 6).
"""

import logging
import threading
import time
import json
from datetime import datetime
from typing import Optional, Any

logger = logging.getLogger(__name__)


class MetricsReporter:
    """
    Periodic metrics reporter using InferencePipeline watchdog.

    Collects metrics from watchdog and publishes them periodically to MQTT.

    Responsibilities:
    - Get full detailed metrics (for METRICS command)
    - Get lightweight metrics (for periodic reporting)
    - Publish metrics to MQTT
    - Manage background reporting thread lifecycle

    Args:
        watchdog: InferencePipeline watchdog instance
        mqtt_client: MQTT client for publishing (Protocol: MessageBroker)
        config: StreamProcessorConfig instance

    Usage:
        >>> reporter = MetricsReporter(watchdog, mqtt_client, config)
        >>> reporter.start()  # Start background thread
        >>> # Later...
        >>> full_report = reporter.get_full_report()
        >>> reporter.stop()  # Stop background thread
    """

    def __init__(
        self,
        watchdog: Optional[object],
        mqtt_client: Any,  # MessageBroker protocol (paho.mqtt.Client)
        config: Any  # StreamProcessorConfig
    ):
        self.watchdog = watchdog
        self.mqtt_client = mqtt_client
        self.config = config

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self):
        """Start periodic metrics reporting in background thread."""
        if self.config.metrics_reporting_interval <= 0:
            logger.info(
                "Metrics reporting disabled (interval = 0)",
                extra={
                    "component": "metrics_reporter",
                    "event": "metrics_reporting_disabled"
                }
            )
            return

        if not self.watchdog:
            logger.warning(
                "Watchdog not available, cannot start metrics reporting",
                extra={
                    "component": "metrics_reporter",
                    "event": "watchdog_unavailable"
                }
            )
            return

        self._thread = threading.Thread(
            target=self._reporting_loop,
            daemon=True,
            name="MetricsReporter"
        )
        self._thread.start()

        logger.info(
            f"📊 Metrics reporting started (interval: {self.config.metrics_reporting_interval}s)",
            extra={
                "component": "metrics_reporter",
                "event": "metrics_started",
                "interval": self.config.metrics_reporting_interval,
                "topic": self.config.metrics_topic
            }
        )

    def stop(self):
        """Stop metrics reporting thread."""
        if self._thread:
            self._stop_event.set()
            self._thread.join(timeout=5)
            logger.info(
                "Metrics reporting stopped",
                extra={
                    "component": "metrics_reporter",
                    "event": "metrics_stopped"
                }
            )

    def get_full_report(self) -> dict:
        """
        Get full detailed metrics report (for METRICS command).

        Returns complete watchdog report with all details:
        - inference_throughput
        - per-source latency reports (decoding, inference, e2e)
        - sources metadata (fps, resolution)
        - status updates (warnings, errors)

        Returns:
            Dict with complete metrics, or empty dict if watchdog unavailable
        """
        if not self.watchdog:
            return {}

        report = self.watchdog.get_report()

        return {
            "timestamp": datetime.now().isoformat(),
            "instance_id": self.config.instance_id,
            "inference_throughput": report.inference_throughput,
            "latency_reports": [
                {
                    "source_id": r.source_id,
                    "frame_decoding_latency_ms": round(r.frame_decoding_latency * 1000, 2) if r.frame_decoding_latency else None,
                    "inference_latency_ms": round(r.inference_latency * 1000, 2) if r.inference_latency else None,
                    "e2e_latency_ms": round(r.e2e_latency * 1000, 2) if r.e2e_latency else None,
                }
                for r in report.latency_reports
            ],
            "sources_metadata": [
                {
                    "source_id": m.source_id,
                    "fps": m.fps,
                    "resolution": f"{m.width}x{m.height}" if m.width and m.height else None,
                }
                for m in report.sources_metadata
            ],
            "status_updates": [
                {
                    "source_id": u.source_id,
                    "severity": u.severity.name,
                    "message": u.payload.get("message", "") if isinstance(u.payload, dict) else str(u.payload),
                }
                for u in report.video_source_status_updates
            ]
        }

    # ========================================================================
    # Private
    # ========================================================================

    def _reporting_loop(self):
        """Background thread loop for periodic reporting."""
        while not self._stop_event.wait(timeout=self.config.metrics_reporting_interval):
            try:
                metrics = self._get_lightweight_metrics()

                # Only publish if valid data (watchdog has collected samples)
                if metrics.get("inference_throughput", 0) > 0:
                    self._publish_metrics(metrics)

            except Exception as e:
                logger.error(
                    f"Error in metrics reporting: {e}",
                    extra={
                        "component": "metrics_reporter",
                        "event": "metrics_error"
                    },
                    exc_info=True
                )

    def _get_lightweight_metrics(self) -> dict:
        """
        Get lightweight metrics (for periodic reporting).

        Returns only throughput and average latencies - optimized for
        frequent polling without excessive data.
        """
        if not self.watchdog:
            return {}

        report = self.watchdog.get_report()

        # Compute average latency across all sources
        latencies = [r.e2e_latency for r in report.latency_reports if r.e2e_latency is not None]
        avg_latency_ms = round(sum(latencies) / len(latencies) * 1000, 2) if latencies else None

        return {
            "timestamp": datetime.now().isoformat(),
            "instance_id": self.config.instance_id,
            "inference_throughput": round(report.inference_throughput, 2),
            "avg_latency_ms": avg_latency_ms,
            "sources": [
                {
                    "source_id": r.source_id,
                    "latency_ms": round(r.e2e_latency * 1000, 2) if r.e2e_latency else None,
                }
                for r in report.latency_reports
            ]
        }

    def _publish_metrics(self, metrics: dict):
        """Publish metrics to MQTT with instance_id in topic."""
        if not self.mqtt_client:
            return

        # Include instance_id in topic path: nvr/status/metrics/{instance_id}
        topic = f"{self.config.metrics_topic}/{self.config.instance_id}"
        payload = json.dumps(metrics)

        self.mqtt_client.publish(topic, payload, qos=0, retain=True)

        logger.debug(
            "📊 Metrics published",
            extra={
                "component": "metrics_reporter",
                "event": "metrics_published",
                "inference_throughput": metrics.get("inference_throughput"),
                "avg_latency_ms": metrics.get("avg_latency_ms")
            }
        )
