"""
StreamProcessor Configuration
==============================

Configuration dataclass for headless stream processor.

Refactored per DESIGN_CONSULTANCY_REFACTORING.md (Prioridad 4):
- Added: Validation in __post_init__()
- Added: Behavior methods (build_stream_uri, add_stream, remove_stream, to_status_dict)
- Philosophy: Rich config object with validation + behavior, not just data bag
"""

from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse
import uuid


class ConfigValidationError(ValueError):
    """Error in configuration validation."""
    pass


@dataclass
class StreamProcessorConfig:
    """Configuration for headless stream processor with MQTT event publishing"""

    # Stream sources
    stream_uris: List[str]
    """List of RTSP stream URIs to process"""

    model_id: str = "yolov8x-640"
    """Roboflow model ID for inference"""

    # MQTT configuration
    mqtt_host: str = "localhost"
    """MQTT broker hostname"""

    mqtt_port: int = 1883
    """MQTT broker port"""

    mqtt_topic_prefix: str = "nvr/detections"
    """MQTT topic prefix for detection events"""

    mqtt_qos: int = 0
    """MQTT QoS level (0=fire-and-forget, 1=at-least-once, 2=exactly-once)"""

    mqtt_username: Optional[str] = None
    """MQTT broker username (optional)"""

    mqtt_password: Optional[str] = None
    """MQTT broker password (optional)"""

    # Pipeline configuration
    max_fps: Optional[float] = None
    """Maximum FPS limiter (None = unlimited)"""

    confidence_threshold: float = 0.5
    """Minimum confidence threshold for detections"""

    # Watchdog
    enable_watchdog: bool = True
    """Enable pipeline watchdog monitoring"""

    # Source ID mapping
    source_id_mapping: Optional[List[int]] = None
    """Map internal source indices (0,1,2...) to actual stream IDs.
    Used when specific streams are selected (e.g., [0,2,4] maps internal 0->0, 1->2, 2->4)"""

    # Stream server base URL (for add_stream command)
    stream_server: str = "rtsp://localhost:8554"
    """Base RTSP server URL (go2rtc proxy). Used to construct stream URIs: {stream_server}/{source_id}"""

    # Control Plane (MQTT control commands)
    enable_control_plane: bool = False
    """Enable MQTT control plane for remote control (pause/resume/stop)"""

    control_command_topic: str = "nvr/control/commands"
    """MQTT topic for receiving control commands"""

    control_status_topic: str = "nvr/control/status"
    """MQTT topic for publishing status updates"""

    # Metrics Reporting (Observability)
    metrics_reporting_interval: int = 10
    """Interval in seconds for auto-reporting metrics (0 = disabled)"""

    metrics_topic: str = "nvr/status/metrics"
    """MQTT topic for periodic metrics reporting (observability channel)"""

    # Instance Identification (Multi-Instance Support)
    instance_id: str = field(default_factory=lambda: f"processor-{uuid.uuid4().hex[:8]}")
    """Unique instance identifier (default: auto-generated processor-{random})"""

    def __post_init__(self):
        """Validate configuration after initialization."""
        self._validate()

    def _validate(self):
        """
        Validate configuration values.

        Raises:
            ConfigValidationError: If any validation fails
        """
        # Validate stream URIs
        if not self.stream_uris:
            raise ConfigValidationError("stream_uris cannot be empty")

        for uri in self.stream_uris:
            if not self._is_valid_uri(uri):
                raise ConfigValidationError(f"Invalid stream URI: {uri}")

        # Validate MQTT port
        if not (1 <= self.mqtt_port <= 65535):
            raise ConfigValidationError(f"Invalid MQTT port: {self.mqtt_port}")

        # Validate max_fps
        if self.max_fps is not None and self.max_fps <= 0:
            raise ConfigValidationError(f"max_fps must be > 0, got {self.max_fps}")

        # Validate metrics interval
        if self.metrics_reporting_interval < 0:
            raise ConfigValidationError(
                f"metrics_reporting_interval cannot be negative, got {self.metrics_reporting_interval}"
            )

        # Validate confidence threshold
        if not (0 <= self.confidence_threshold <= 1):
            raise ConfigValidationError(
                f"confidence_threshold must be between 0 and 1, got {self.confidence_threshold}"
            )

    @staticmethod
    def _is_valid_uri(uri: str) -> bool:
        """
        Check if URI is valid.

        Args:
            uri: URI to validate

        Returns:
            True if valid, False otherwise
        """
        try:
            result = urlparse(uri)
            # URI must have scheme and either netloc or path
            return all([result.scheme, result.netloc or result.path])
        except Exception:
            return False

    # ========================================================================
    # Behavior: URI Construction
    # ========================================================================

    def build_stream_uri(self, source_id: int) -> str:
        """
        Build stream URI from stream_server and source_id.

        Uses go2rtc convention: rtsp://server/{source_id}

        Args:
            source_id: Stream source ID (room number)

        Returns:
            Full RTSP URI

        Example:
            >>> config = StreamProcessorConfig(
            ...     stream_uris=["dummy"],
            ...     stream_server="rtsp://go2rtc:8554"
            ... )
            >>> config.build_stream_uri(8)
            'rtsp://go2rtc:8554/8'
        """
        return f"{self.stream_server}/{source_id}"

    def add_stream(self, source_id: int) -> None:
        """
        Add stream to configuration.

        Constructs URI from stream_server and updates stream_uris and source_id_mapping.

        Args:
            source_id: Stream source ID to add

        Raises:
            ConfigValidationError: If source_id already exists or is invalid
        """
        # Validate source_id
        if not isinstance(source_id, int):
            raise ConfigValidationError(f"source_id must be int, got {type(source_id).__name__}")

        # Initialize source_id_mapping if None
        if self.source_id_mapping is None:
            self.source_id_mapping = []

        # Check if already exists
        if source_id in self.source_id_mapping:
            raise ConfigValidationError(f"Stream with source_id {source_id} already exists")

        # Build URI and add
        stream_uri = self.build_stream_uri(source_id)
        self.stream_uris.append(stream_uri)
        self.source_id_mapping.append(source_id)

    def remove_stream(self, source_id: int) -> None:
        """
        Remove stream from configuration.

        Args:
            source_id: Stream source ID to remove

        Raises:
            ConfigValidationError: If source_id not found or cannot be removed
        """
        # Initialize source_id_mapping if None
        if self.source_id_mapping is None:
            raise ConfigValidationError("Cannot remove stream: source_id_mapping is None")

        # Check if exists
        if source_id not in self.source_id_mapping:
            raise ConfigValidationError(f"Stream with source_id {source_id} not found")

        # Cannot remove last stream
        if len(self.stream_uris) == 1:
            raise ConfigValidationError("Cannot remove last stream (at least one stream required)")

        # Remove from both lists
        idx = self.source_id_mapping.index(source_id)
        self.stream_uris.pop(idx)
        self.source_id_mapping.pop(idx)

    # ========================================================================
    # Behavior: Serialization for Status Publishing
    # ========================================================================

    def to_status_dict(self) -> dict:
        """
        Serialize config for status publishing.

        Returns only relevant fields for orchestrator/monitoring,
        omitting sensitive data (passwords) and internal details.

        Returns:
            Dict with public config fields
        """
        return {
            "stream_uris": self.stream_uris,
            "source_id_mapping": self.source_id_mapping,
            "model_id": self.model_id,
            "max_fps": self.max_fps,
            "stream_server": self.stream_server,
            "mqtt_topic_prefix": self.mqtt_topic_prefix,
            "enable_watchdog": self.enable_watchdog,
            "metrics_reporting_interval": self.metrics_reporting_interval,
        }

