"""
Interfaces for Dependency Injection
====================================

Protocols (interfaces) for decoupling from concrete implementations.

This allows:
- Testing with fake implementations (no MQTT broker, no Roboflow needed)
- Swapping implementations (e.g., replace paho.mqtt with another client)
- Clear contracts (documented interface methods)

Based on DESIGN_CONSULTANCY_REFACTORING.md - Prioridad 3: Dependency Inversion.
"""

from typing import Protocol, Any, Optional, List, Union


class MessageBroker(Protocol):
    """
    Protocol for MQTT-like message broker.

    This protocol defines the minimal interface required by MQTTDetectionSink
    and MQTTControlPlane for publishing/subscribing to messages.

    Concrete implementation: paho.mqtt.Client
    Test implementation: FakeMessageBroker (see tests/unit/test_mqtt_sink_with_fakes.py)

    Why Protocol instead of ABC:
    - Structural subtyping (duck typing with type checking)
    - Existing paho.mqtt.Client already implements this interface
    - No need to modify third-party code
    """

    def publish(
        self, topic: str, payload: str, qos: int = 0, retain: bool = False
    ) -> Any:
        """
        Publish message to topic.

        Args:
            topic: MQTT topic string
            payload: Message payload (JSON string)
            qos: Quality of Service (0, 1, or 2)
            retain: Retain message on broker

        Returns:
            MQTTMessageInfo or equivalent (result.rc == 0 for success)
        """
        ...

    def subscribe(self, topic: str, qos: int = 0) -> None:
        """
        Subscribe to topic.

        Args:
            topic: MQTT topic string (supports wildcards: +, #)
            qos: Quality of Service (0, 1, or 2)
        """
        ...

    def connect(self, host: str, port: int, keepalive: int = 60) -> None:
        """
        Connect to broker.

        Args:
            host: Broker hostname or IP
            port: Broker port (typically 1883 for MQTT)
            keepalive: Keep-alive interval in seconds
        """
        ...

    def disconnect(self) -> None:
        """Disconnect from broker."""
        ...

    def loop_start(self) -> None:
        """Start background network loop (threaded)."""
        ...

    def loop_stop(self) -> None:
        """Stop background network loop."""
        ...


class InferencePipeline(Protocol):
    """
    Protocol for inference pipeline.

    This protocol defines the minimal interface required by InferencePipelineManager
    for controlling the inference pipeline lifecycle.

    Concrete implementation: inference.InferencePipeline (Roboflow)
    Test implementation: FakePipeline (see tests/unit/test_pipeline_manager_with_fakes.py)

    Note:
        The actual Roboflow InferencePipeline has more methods. This protocol
        only defines what we actually use in our code.
    """

    def start(self, use_main_thread: bool = True) -> None:
        """
        Start pipeline processing.

        Args:
            use_main_thread: If True, blocks main thread. If False, runs in background.

        Note:
            Starting can block for 20+ seconds while connecting to RTSP streams.
        """
        ...

    def terminate(self) -> None:
        """Terminate pipeline completely (cannot be restarted)."""
        ...

    def pause_stream(self) -> None:
        """
        Pause stream processing.

        Note:
            This stops buffering NEW frames. Frames already in prediction queue
            continue processing for ~5-10s (Roboflow implementation detail).
        """
        ...

    def resume_stream(self) -> None:
        """Resume stream processing (after pause)."""
        ...

    def join(self) -> None:
        """Wait for pipeline to finish (blocks until terminated)."""
        ...


class VideoFrame(Protocol):
    """
    Protocol for video frame metadata.

    Represents a frame passed to on_prediction callback in InferencePipeline.

    Concrete implementation: inference.core.interfaces.camera.entities.VideoFrame
    Test implementation: MockVideoFrame (see tests/unit/test_mqtt_sink_with_fakes.py)
    """

    source_id: int
    """Internal source ID (0-indexed position in stream_uris list)"""

    frame_id: int
    """Sequential frame number from this source"""

    frame_timestamp: float
    """Frame timestamp (Unix epoch, seconds)"""


class PipelineWatchdog(Protocol):
    """
    Protocol for pipeline watchdog (metrics collector).

    Concrete implementation: inference.core.interfaces.stream.watchdog.BasePipelineWatchDog
    Test implementation: FakeWatchdog (see tests/unit/test_metrics_reporter_with_fakes.py)
    """

    def get_report(self) -> "WatchdogReport":
        """
        Get current metrics report.

        Returns:
            WatchdogReport with inference throughput, latencies, and source metadata
        """
        ...


class WatchdogReport(Protocol):
    """
    Protocol for watchdog metrics report.

    Concrete implementation: inference.core.interfaces.stream.watchdog.PipelineWatchDog.Report
    """

    inference_throughput: float
    """Inferences per second (across all sources)"""

    latency_reports: List["LatencyReport"]
    """Per-source latency breakdown"""

    sources_metadata: List["SourceMetadata"]
    """Per-source stream metadata (FPS, resolution)"""


class LatencyReport(Protocol):
    """
    Protocol for per-source latency report.

    Concrete implementation: inference.core.interfaces.stream.watchdog.LatencyMonitor
    """

    source_id: int
    """Source ID (0-indexed)"""

    frame_decoding_latency: Optional[float]
    """Frame decoding latency in seconds"""

    inference_latency: Optional[float]
    """Model inference latency in seconds"""

    e2e_latency: Optional[float]
    """End-to-end latency in seconds (decode + inference + callback)"""


class SourceMetadata(Protocol):
    """
    Protocol for source stream metadata.

    Concrete implementation: inference.core.interfaces.stream.watchdog.StreamMetadata
    """

    source_id: int
    """Source ID (0-indexed)"""

    fps: Optional[float]
    """Frames per second"""

    width: Optional[int]
    """Frame width in pixels"""

    height: Optional[int]
    """Frame height in pixels"""


# Type aliases for convenience
MQTTClient = MessageBroker  # Alias for backward compatibility
