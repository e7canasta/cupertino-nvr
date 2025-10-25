"""
Detection Renderer
==================

Renders video frames with detection overlays.
"""

import logging
from datetime import datetime
from typing import Optional

import cv2
import numpy as np

from cupertino_nvr.events.schema import DetectionEvent
from cupertino_nvr.wall.config import VideoWallConfig

logger = logging.getLogger(__name__)


class DetectionRenderer:
    """
    Renders video frames with detection overlays.

    Uses OpenCV to draw bounding boxes, labels, and statistics
    on video frames based on detection events.

    Args:
        config: VideoWallConfig instance

    Example:
        >>> config = VideoWallConfig(stream_uris=[...])
        >>> renderer = DetectionRenderer(config)
        >>> rendered_image = renderer.render_frame(frame, event)
    """

    def __init__(self, config: VideoWallConfig):
        self.config = config

    def render_frame(self, frame: object, event: Optional[DetectionEvent]) -> np.ndarray:
        """
        Render single frame with detection overlay.

        Args:
            frame: VideoFrame object with .image attribute
            event: DetectionEvent or None

        Returns:
            Rendered image as numpy array
        """
        image = frame.image.copy()

        # Draw detections if available
        if event is not None and len(event.detections) > 0:
            image = self._draw_detections(image, event)

        # Resize to tile size
        image = self._letterbox_image(image, self.config.tile_size)

        # Add statistics overlay
        if event is not None:
            image = self._draw_statistics(image, event, frame)
        else:
            # Add source ID even without detections
            image = self._draw_source_id(image, frame.source_id)

        return image

    def _draw_detections(self, image: np.ndarray, event: DetectionEvent) -> np.ndarray:
        """Draw bounding boxes and labels for detections"""
        for det in event.detections:
            # Convert center+size to xyxy
            x1 = int(det.bbox.x - det.bbox.width / 2)
            y1 = int(det.bbox.y - det.bbox.height / 2)
            x2 = int(det.bbox.x + det.bbox.width / 2)
            y2 = int(det.bbox.y + det.bbox.height / 2)

            # Draw bounding box
            cv2.rectangle(
                image,
                (x1, y1),
                (x2, y2),
                (0, 255, 0),  # Green
                self.config.box_thickness,
            )

            # Draw label
            label = f"{det.class_name} {det.confidence:.2f}"
            if det.tracker_id is not None:
                label += f" #{det.tracker_id}"

            # Label background
            (label_width, label_height), _ = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, self.config.label_font_scale, 2
            )
            cv2.rectangle(
                image,
                (x1, y1 - label_height - 10),
                (x1 + label_width, y1),
                (0, 255, 0),
                -1,  # Filled
            )

            # Label text
            cv2.putText(
                image,
                label,
                (x1, y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                self.config.label_font_scale,
                (0, 0, 0),  # Black text
                2,
            )

        return image

    def _draw_statistics(
        self, image: np.ndarray, event: DetectionEvent, frame: object
    ) -> np.ndarray:
        """Draw statistics overlay"""
        y_offset = 30

        # Latency
        if self.config.display_latency:
            latency_ms = (datetime.now() - event.timestamp).total_seconds() * 1000
            cv2.putText(
                image,
                f"Latency: {latency_ms:.0f}ms",
                (10, y_offset),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
            )
            y_offset += 30

        # FPS
        if self.config.display_fps and event.fps:
            cv2.putText(
                image,
                f"FPS: {event.fps:.1f}",
                (10, y_offset),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
            )
            y_offset += 30

        # Source ID at bottom
        self._draw_source_id(image, frame.source_id)

        return image

    def _draw_source_id(self, image: np.ndarray, source_id: int) -> np.ndarray:
        """Draw source ID at bottom of frame"""
        cv2.putText(
            image,
            f"Stream {source_id}",
            (10, image.shape[0] - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            2,
        )
        return image

    def _letterbox_image(
        self, image: np.ndarray, target_size: tuple
    ) -> np.ndarray:
        """
        Resize image to target size maintaining aspect ratio with letterboxing.

        Args:
            image: Input image
            target_size: (width, height) tuple

        Returns:
            Resized image with letterboxing
        """
        target_w, target_h = target_size
        h, w = image.shape[:2]

        # Calculate scaling factor
        scale = min(target_w / w, target_h / h)
        new_w = int(w * scale)
        new_h = int(h * scale)

        # Resize
        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        # Create letterboxed image (black background)
        letterboxed = np.zeros((target_h, target_w, 3), dtype=np.uint8)

        # Calculate offsets for centering
        x_offset = (target_w - new_w) // 2
        y_offset = (target_h - new_h) // 2

        # Place resized image in center
        letterboxed[y_offset : y_offset + new_h, x_offset : x_offset + new_w] = resized

        return letterboxed

