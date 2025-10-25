"""
VideoWall Configuration
========================

Configuration dataclass for video wall viewer.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class VideoWallConfig:
    """Configuration for video wall viewer with MQTT event overlays"""

    # Stream sources
    stream_uris: List[str]
    """List of RTSP stream URIs to display"""

    # MQTT configuration
    mqtt_host: str = "localhost"
    """MQTT broker hostname"""

    mqtt_port: int = 1883
    """MQTT broker port"""

    mqtt_topic_pattern: str = "nvr/detections/#"
    """MQTT topic pattern to subscribe (# = wildcard for all sources)"""

    mqtt_username: Optional[str] = None
    """MQTT broker username (optional)"""

    mqtt_password: Optional[str] = None
    """MQTT broker password (optional)"""

    # Display configuration
    tile_size: Tuple[int, int] = (480, 360)
    """Size of each video tile in pixels (width, height)"""

    grid_columns: int = 4
    """Number of columns in the video grid"""

    display_fps: bool = True
    """Display FPS overlay on each tile"""

    display_latency: bool = True
    """Display latency overlay on each tile"""

    # Detection overlay
    detection_ttl_seconds: float = 1.0
    """TTL for cached detection events (seconds)"""

    box_thickness: int = 2
    """Bounding box line thickness"""

    label_font_scale: float = 0.6
    """Font scale for detection labels"""

