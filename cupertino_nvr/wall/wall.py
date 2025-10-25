"""
Video Wall
==========

Video wall viewer with MQTT event overlays.
"""

import logging
import signal
from typing import List

import cv2
import numpy as np

from cupertino_nvr.wall.config import VideoWallConfig
from cupertino_nvr.wall.detection_cache import DetectionCache
from cupertino_nvr.wall.mqtt_listener import MQTTListener
from cupertino_nvr.wall.renderer import DetectionRenderer

logger = logging.getLogger(__name__)

# Global stop flag for signal handling
STOP = False
BLACK_FRAME = np.zeros((360, 480, 3), dtype=np.uint8)


class VideoWall:
    """
    Video wall viewer with MQTT event overlays.

    Displays multiple RTSP streams in a grid layout with detection
    overlays received via MQTT. Does not perform inference itself.

    Args:
        config: VideoWallConfig instance

    Example:
        >>> config = VideoWallConfig(
        ...     stream_uris=["rtsp://localhost:8554/live/0.stream"],
        ...     mqtt_host="localhost",
        ... )
        >>> wall = VideoWall(config)
        >>> wall.start()  # Blocks until stopped
    """

    def __init__(self, config: VideoWallConfig):
        self.config = config
        self.cache = DetectionCache(ttl_seconds=config.detection_ttl_seconds)
        self.mqtt_listener = MQTTListener(config, self.cache)
        self.renderer = DetectionRenderer(config)

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def start(self):
        """Start the video wall"""
        global STOP

        logger.info(f"Starting VideoWall with {len(self.config.stream_uris)} streams")

        # Start MQTT listener
        self.mqtt_listener.start()

        # Import video utilities here to avoid hard dependency
        try:
            from inference.core.interfaces.camera.entities import VideoFrame
            from inference.core.interfaces.camera.utils import multiplex_videos
            from inference.core.interfaces.camera.video_source import VideoSource
        except ImportError as e:
            logger.error(
                "Failed to import inference video utilities. "
                "Make sure 'inference' package is installed."
            )
            raise ImportError(
                "Inference video utilities not available. "
                "Install with: pip install inference"
            ) from e

        # Initialize video sources with proper source_id mapping
        # Use source_id_mapping if provided, otherwise use sequential indices
        source_ids = self.config.source_id_mapping or list(range(len(self.config.stream_uris)))
        cameras = [
            VideoSource.init(uri, source_id=source_id)
            for uri, source_id in zip(self.config.stream_uris, source_ids)
        ]

        for camera in cameras:
            camera.start()

        logger.info("Video sources started, beginning display...")

        # Multiplex and render
        try:
            multiplexer = multiplex_videos(
                videos=cameras,
                should_stop=lambda: STOP,
            )

            for frames in multiplexer:
                self._render_frame_batch(frames)

                # Check for quit key
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

        finally:
            # Cleanup
            cv2.destroyAllWindows()
            for camera in cameras:
                camera.terminate(
                    wait_on_frames_consumption=False, purge_frames_buffer=True
                )
            self.mqtt_listener.stop()

            logger.info("VideoWall stopped")

    def _render_frame_batch(self, frames: List[object]):
        """Render batch of frames as grid"""
        images = []

        for frame in frames:
            # Get cached detections for this source
            event = self.cache.get(frame.source_id)

            # Render frame with detection overlay
            image = self.renderer.render_frame(frame, event)
            images.append(image)

        # Fill missing tiles with black frames
        n_streams = len(self.config.stream_uris)
        while len(images) < n_streams:
            black = np.zeros(
                (self.config.tile_size[1], self.config.tile_size[0], 3), dtype=np.uint8
            )
            images.append(black)

        # Create grid
        rows = self._create_grid(images, self.config.grid_columns)

        # Merge rows into single image
        rows_merged = [np.concatenate(r, axis=1) for r in rows]
        grid = np.concatenate(rows_merged, axis=0)

        # Display
        cv2.imshow("NVR Video Wall", grid)

    def _create_grid(self, images: List[np.ndarray], columns: int) -> List[List[np.ndarray]]:
        """Create grid of images"""
        rows = []
        for i in range(0, len(images), columns):
            row = images[i : i + columns]

            # Pad last row with black frames if needed
            while len(row) < columns:
                black = np.zeros(
                    (self.config.tile_size[1], self.config.tile_size[0], 3),
                    dtype=np.uint8,
                )
                row.append(black)

            rows.append(row)

        return rows

    def _signal_handler(self, signum, frame):
        """Handle termination signals"""
        global STOP
        logger.info(f"Received signal {signum}, shutting down...")
        STOP = True

