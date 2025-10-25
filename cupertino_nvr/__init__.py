"""
Cupertino NVR - Distributed Network Video Recorder
===================================================

Event-driven NVR system with separated inference and visualization.

Usage:
    # Processor (headless inference)
    from cupertino_nvr.processor import StreamProcessor, StreamProcessorConfig
    
    config = StreamProcessorConfig(
        stream_uris=["rtsp://..."],
        model_id="yolov8x-640",
        mqtt_host="localhost",
    )
    processor = StreamProcessor(config)
    processor.start()
    
    # Video Wall (viewer)
    from cupertino_nvr.wall import VideoWall, VideoWallConfig
    
    config = VideoWallConfig(
        stream_uris=["rtsp://..."],
        mqtt_host="localhost",
    )
    wall = VideoWall(config)
    wall.start()
"""

from cupertino_nvr.events import BoundingBox, Detection, DetectionEvent

__version__ = "0.1.0"
__author__ = "Visiona Team"

# Lazy imports to avoid circular dependencies and missing inference dependency
def _get_processor():
    """Lazy import of processor components"""
    try:
        from cupertino_nvr.processor import StreamProcessor, StreamProcessorConfig
        return StreamProcessor, StreamProcessorConfig
    except ImportError as e:
        raise ImportError(
            f"Processor components require 'inference' package to be installed: {e}"
        )

def _get_wall():
    """Lazy import of wall components"""  
    try:
        from cupertino_nvr.wall import VideoWall, VideoWallConfig
        return VideoWall, VideoWallConfig
    except ImportError as e:
        raise ImportError(
            f"Wall components require 'inference' package to be installed: {e}"
        )

# Make components available via getattr for backward compatibility
def __getattr__(name):
    if name == "StreamProcessor":
        StreamProcessor, _ = _get_processor()
        return StreamProcessor
    elif name == "StreamProcessorConfig":
        _, StreamProcessorConfig = _get_processor()
        return StreamProcessorConfig
    elif name == "VideoWall":
        VideoWall, _ = _get_wall()
        return VideoWall
    elif name == "VideoWallConfig":
        _, VideoWallConfig = _get_wall()
        return VideoWallConfig
    else:
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

__all__ = [
    "StreamProcessor",
    "StreamProcessorConfig", 
    "VideoWall",
    "VideoWallConfig",
    "DetectionEvent",
    "Detection",
    "BoundingBox",
]

