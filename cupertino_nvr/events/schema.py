"""
Event Schema for NVR System
============================

Pydantic models for detection events published to MQTT.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """Bounding box coordinates (center + size format)"""

    x: float = Field(description="Center X coordinate")
    y: float = Field(description="Center Y coordinate")
    width: float = Field(description="Box width")
    height: float = Field(description="Box height")


class Detection(BaseModel):
    """Single object detection"""

    class_name: str = Field(description="Detected class name")
    confidence: float = Field(ge=0.0, le=1.0, description="Detection confidence")
    bbox: BoundingBox = Field(description="Bounding box")
    tracker_id: Optional[int] = Field(default=None, description="Tracking ID if available")


class DetectionEvent(BaseModel):
    """Detection event published to MQTT"""

    # Metadata
    source_id: int = Field(description="Stream source ID (0-indexed)")
    frame_id: int = Field(description="Frame sequence number")
    timestamp: datetime = Field(description="Frame capture timestamp")

    # Inference results
    model_id: str = Field(description="Model used for inference")
    inference_time_ms: float = Field(description="Inference duration in milliseconds")
    detections: List[Detection] = Field(description="List of detections in frame")

    # Optional metadata
    fps: Optional[float] = Field(default=None, description="Current FPS")
    latency_ms: Optional[float] = Field(default=None, description="End-to-end latency")

    class Config:
        json_schema_extra = {
            "example": {
                "source_id": 0,
                "frame_id": 12345,
                "timestamp": "2025-10-25T10:30:00.123Z",
                "model_id": "yolov8x-640",
                "inference_time_ms": 45.2,
                "detections": [
                    {
                        "class_name": "person",
                        "confidence": 0.92,
                        "bbox": {"x": 100, "y": 150, "width": 80, "height": 200},
                        "tracker_id": 42,
                    }
                ],
                "fps": 25.3,
                "latency_ms": 120.5,
            }
        }

