"""
StreamProcessor Configuration
==============================

Configuration dataclass for headless stream processor.
"""

from dataclasses import dataclass
from typing import List, Optional


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

