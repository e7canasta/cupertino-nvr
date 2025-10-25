"""
Video Wall - Event-Driven Viewer
=================================

Displays RTSP streams with detection overlays from MQTT events.
"""

from cupertino_nvr.wall.config import VideoWallConfig
from cupertino_nvr.wall.detection_cache import DetectionCache
from cupertino_nvr.wall.mqtt_listener import MQTTListener
from cupertino_nvr.wall.renderer import DetectionRenderer
from cupertino_nvr.wall.wall import VideoWall

__all__ = [
    "VideoWall",
    "VideoWallConfig",
    "DetectionCache",
    "MQTTListener",
    "DetectionRenderer",
]

