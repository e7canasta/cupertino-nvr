"""
Event Protocol for NVR System
==============================

MQTT message schemas and topic utilities.
"""

from cupertino_nvr.events.protocol import parse_source_id_from_topic, topic_for_source
from cupertino_nvr.events.schema import BoundingBox, Detection, DetectionEvent

__all__ = [
    "DetectionEvent",
    "Detection",
    "BoundingBox",
    "topic_for_source",
    "parse_source_id_from_topic",
]

