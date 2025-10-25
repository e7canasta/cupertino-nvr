"""
Detection Renderer
==================

Renders video frames with detection overlays using supervision annotators.
"""

import logging
from datetime import datetime
from typing import List, Optional

import cv2
import numpy as np
import supervision as sv

from cupertino_nvr.events.schema import DetectionEvent
from cupertino_nvr.wall.config import VideoWallConfig

logger = logging.getLogger(__name__)


class DetectionRenderer:
    """
    Renders video frames with detection overlays.

    Uses supervision annotators to draw bounding boxes, labels, and statistics
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

        # Initialize supervision annotators
        self.box_annotator = sv.BoxAnnotator(
            thickness=config.box_thickness,
            color=sv.Color.GREEN,
        )

        self.label_annotator = sv.LabelAnnotator(
            text_scale=config.label_font_scale,
            text_thickness=2,
            text_color=sv.Color.BLACK,
            color=sv.Color.GREEN,
        )

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
        """Draw bounding boxes and labels using supervision annotators"""
        # Convert DetectionEvent to supervision.Detections
        detections = self._to_supervision_detections(event)

        # Annotate using supervision
        image = self.box_annotator.annotate(scene=image.copy(), detections=detections)

        # Create labels with class name, confidence, and tracker ID
        labels = self._create_labels(event)
        image = self.label_annotator.annotate(
            scene=image, detections=detections, labels=labels
        )

        return image

    def _to_supervision_detections(self, event: DetectionEvent) -> sv.Detections:
        """
        Convert DetectionEvent to supervision.Detections format.

        Args:
            event: DetectionEvent with bounding box detections

        Returns:
            supervision.Detections object
        """
        if not event.detections:
            # Return empty detections
            return sv.Detections.empty()

        xyxy = []
        confidence = []
        class_id = []
        tracker_id = []

        for det in event.detections:
            # Convert center+size to xyxy format
            x1 = det.bbox.x - det.bbox.width / 2
            y1 = det.bbox.y - det.bbox.height / 2
            x2 = det.bbox.x + det.bbox.width / 2
            y2 = det.bbox.y + det.bbox.height / 2

            xyxy.append([x1, y1, x2, y2])
            confidence.append(det.confidence)
            class_id.append(0)  # Default class ID (not used for visualization)

            # Tracker ID (optional)
            if det.tracker_id is not None:
                tracker_id.append(det.tracker_id)
            else:
                tracker_id.append(-1)  # Sentinel for no tracker

        return sv.Detections(
            xyxy=np.array(xyxy),
            confidence=np.array(confidence),
            class_id=np.array(class_id),
            tracker_id=np.array(tracker_id) if any(tid != -1 for tid in tracker_id) else None,
        )

    def _create_labels(self, event: DetectionEvent) -> List[str]:
        """
        Create label strings for each detection.

        Args:
            event: DetectionEvent with detections

        Returns:
            List of label strings
        """
        labels = []
        for det in event.detections:
            label = f"{det.class_name} {det.confidence:.2f}"
            if det.tracker_id is not None:
                label += f" #{det.tracker_id}"
            labels.append(label)
        return labels

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

