"""
Cupertino NVR - Distributed Network Video Recorder
===================================================

Event-driven NVR system with separated inference and visualization.

Usage:
    # Processor (headless inference)
    from cupertino.nvr.processor import StreamProcessor, StreamProcessorConfig
    
    config = StreamProcessorConfig(
        stream_uris=["rtsp://..."],
        model_id="yolov8x-640",
        mqtt_host="localhost",
    )
    processor = StreamProcessor(config)
    processor.start()
    
    # Video Wall (viewer)
    from cupertino.nvr.wall import VideoWall, VideoWallConfig
    
    config = VideoWallConfig(
        stream_uris=["rtsp://..."],
        mqtt_host="localhost",
    )
    wall = VideoWall(config)
    wall.start()
"""

__version__ = "0.1.0"
__author__ = "Visiona Team"

from .processor import StreamProcessor, StreamProcessorConfig
from .wall import VideoWall, VideoWallConfig
from .events import DetectionEvent, Detection, BoundingBox

__all__ = [
    "StreamProcessor",
    "StreamProcessorConfig",
    "VideoWall",
    "VideoWallConfig",
    "DetectionEvent",
    "Detection",
    "BoundingBox",
]

