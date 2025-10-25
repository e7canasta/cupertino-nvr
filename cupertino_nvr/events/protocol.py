"""
MQTT Protocol Utilities
========================

Topic naming conventions and parsing utilities for NVR MQTT protocol.
"""

from typing import Optional


def topic_for_source(source_id: int, prefix: str = "nvr/detections") -> str:
    """
    Generate MQTT topic for a video source.

    Args:
        source_id: Stream source ID (0-indexed)
        prefix: Topic prefix (default: "nvr/detections")

    Returns:
        MQTT topic string (e.g., "nvr/detections/0")

    Examples:
        >>> topic_for_source(0)
        'nvr/detections/0'
        >>> topic_for_source(5, prefix="custom/events")
        'custom/events/5'
    """
    return f"{prefix}/{source_id}"


def parse_source_id_from_topic(topic: str) -> Optional[int]:
    """
    Extract source_id from MQTT topic.

    Args:
        topic: MQTT topic string (e.g., "nvr/detections/0")

    Returns:
        Source ID as integer, or None if parsing fails

    Examples:
        >>> parse_source_id_from_topic("nvr/detections/0")
        0
        >>> parse_source_id_from_topic("nvr/detections/42")
        42
        >>> parse_source_id_from_topic("invalid/topic")
        None
    """
    parts = topic.split("/")
    if len(parts) >= 3:
        try:
            return int(parts[-1])
        except ValueError:
            return None
    return None

