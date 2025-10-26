"""
Stabilization Event Sourcing Module
====================================

Event sourcing para debugging y audit trail de stabilization.

Philosophy: "Pragmatismo > Purismo" - Blues Style
- Event log OPCIONAL (configurable via config.yaml)
- Zero cost si disabled (None check es O(1))
- Simple strings (no Enum overhead)
- Immutable events (dataclass frozen)

Design:
- TrackEvent: Inmutable event de tracking
- Event types: Simple strings (JSON-serializable)
- Circular log: deque con maxlen (no unbounded growth)

Use Cases:
- 🐛 Debugging: "¿Por qué se perdió el track?"
- 🧪 Testing: Replay scenarios para reproducir bugs
- 📊 Audit: Compliance en geriatric monitoring
- ⏱ Time-travel: Reconstruct estado en cualquier momento

Example:
    >>> from collections import deque
    >>> events = deque(maxlen=1000)
    >>> event = TrackEvent(
    ...     timestamp=time.time(),
    ...     frame_id=42,
    ...     track_id='person_1',
    ...     event_type=EVENT_CONFIRMED,
    ...     confidence=0.72,
    ...     bbox=(120, 80, 240, 320),
    ...     reason='min_frames_met'
    ... )
    >>> events.append(event)
"""

from dataclasses import dataclass
from typing import Optional
import time
import json

# ============================================================================
# Event Type Constants (Simple Strings)
# ============================================================================

# Por qué strings y no Enum:
# - ✅ JSON-serializable out-of-the-box
# - ✅ Legible: 'appeared' > TrackEvent.APPEARED.value
# - ✅ No overhead de Enum serialization
# - ✅ Blues Style: "Simple para leer, no complicar"

EVENT_APPEARED = 'appeared'       # Nueva detección creó track
EVENT_UPDATED = 'updated'         # Track existente actualizado con detection
EVENT_CONFIRMED = 'confirmed'     # Track alcanzó min_frames, ahora se emite
EVENT_MISSED = 'missed'           # Frame sin detection para este track
EVENT_REMOVED = 'removed'         # Track eliminado por max_gap exceeded


# ============================================================================
# Track Event (Immutable)
# ============================================================================

@dataclass(frozen=True)
class TrackEvent:
    """
    Event inmutable de tracking.

    Philosophy:
    - Immutable (frozen=True): No bugs de mutación
    - Self-documenting: Campos con nombres obvios
    - Minimal: Solo datos necesarios para debugging

    Lifecycle:
        APPEARED → UPDATED* → CONFIRMED → [UPDATED | MISSED]* → REMOVED

    Fields:
        timestamp: Unix timestamp del event (float)
        frame_id: ID del frame donde ocurrió el event
        track_id: ID único del track (class_name + spatial hash)
        event_type: Tipo de event (appeared, updated, confirmed, missed, removed)
        confidence: Confidence de la detección (0.0 si missed/removed)
        bbox: Bounding box (x, y, width, height) normalized
        reason: Razón del event (opcional, para debugging)

    Example:
        >>> event = TrackEvent(
        ...     timestamp=1698062400.123,
        ...     frame_id=42,
        ...     track_id='person_1',
        ...     event_type=EVENT_CONFIRMED,
        ...     confidence=0.72,
        ...     bbox=(0.5, 0.5, 0.2, 0.3),
        ...     reason='min_frames_met (3 consecutive)'
        ... )
        >>> event.to_dict()
        {'timestamp': 1698062400.123, 'frame_id': 42, ...}
    """
    timestamp: float
    frame_id: int
    track_id: str
    event_type: str  # One of: appeared, updated, confirmed, missed, removed
    confidence: float
    bbox: tuple[float, float, float, float]  # (x, y, width, height) normalized
    reason: Optional[str] = None  # Human-readable reason (debugging)

    def to_dict(self) -> dict:
        """
        Export to JSON-serializable dict.

        Returns:
            Dict con todos los campos del event

        Example:
            >>> event.to_dict()
            {
                'timestamp': 1698062400.123,
                'frame_id': 42,
                'track_id': 'person_1',
                'event_type': 'confirmed',
                'confidence': 0.72,
                'bbox': [0.5, 0.5, 0.2, 0.3],
                'reason': 'min_frames_met (3 consecutive)'
            }
        """
        return {
            'timestamp': self.timestamp,
            'frame_id': self.frame_id,
            'track_id': self.track_id,
            'event_type': self.event_type,
            'confidence': self.confidence,
            'bbox': list(self.bbox),  # tuple → list para JSON
            'reason': self.reason,
        }

    def to_json(self) -> str:
        """
        Export to JSON string.

        Returns:
            JSON string del event

        Example:
            >>> event.to_json()
            '{"timestamp": 1698062400.123, "frame_id": 42, ...}'
        """
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict) -> 'TrackEvent':
        """
        Create TrackEvent from dict.

        Args:
            data: Dict con campos del event

        Returns:
            TrackEvent instance

        Example:
            >>> data = {'timestamp': 1698062400.123, 'frame_id': 42, ...}
            >>> event = TrackEvent.from_dict(data)
        """
        return cls(
            timestamp=data['timestamp'],
            frame_id=data['frame_id'],
            track_id=data['track_id'],
            event_type=data['event_type'],
            confidence=data['confidence'],
            bbox=tuple(data['bbox']),  # list → tuple
            reason=data.get('reason'),
        )

    @classmethod
    def from_json(cls, json_str: str) -> 'TrackEvent':
        """
        Create TrackEvent from JSON string.

        Args:
            json_str: JSON string

        Returns:
            TrackEvent instance

        Example:
            >>> json_str = '{"timestamp": 1698062400.123, ...}'
            >>> event = TrackEvent.from_json(json_str)
        """
        data = json.loads(json_str)
        return cls.from_dict(data)


# ============================================================================
# Event Log Helpers
# ============================================================================

def export_events_to_json(events: list[TrackEvent], filepath: str) -> None:
    """
    Export event log to JSON file.

    Args:
        events: Lista de TrackEvent
        filepath: Path al archivo JSON output

    Example:
        >>> from collections import deque
        >>> events = deque([event1, event2, event3])
        >>> export_events_to_json(list(events), 'stabilization_events.json')
    """
    data = [event.to_dict() for event in events]
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)


def load_events_from_json(filepath: str) -> list[TrackEvent]:
    """
    Load event log from JSON file.

    Args:
        filepath: Path al archivo JSON input

    Returns:
        Lista de TrackEvent

    Example:
        >>> events = load_events_from_json('stabilization_events.json')
        >>> len(events)
        1000
    """
    with open(filepath, 'r') as f:
        data = json.load(f)
    return [TrackEvent.from_dict(event_dict) for event_dict in data]


def get_track_history(events: list[TrackEvent], track_id: str) -> list[TrackEvent]:
    """
    Filter events for specific track.

    Args:
        events: Lista de TrackEvent
        track_id: ID del track a filtrar

    Returns:
        Lista de TrackEvent para ese track

    Example:
        >>> events = [event1, event2, event3]  # 3 tracks diferentes
        >>> person_events = get_track_history(events, 'person_1')
        >>> len(person_events)
        5
    """
    return [event for event in events if event.track_id == track_id]


def get_events_by_type(events: list[TrackEvent], event_type: str) -> list[TrackEvent]:
    """
    Filter events by type.

    Args:
        events: Lista de TrackEvent
        event_type: Tipo de event (appeared, updated, confirmed, missed, removed)

    Returns:
        Lista de TrackEvent de ese tipo

    Example:
        >>> events = [event1, event2, event3]
        >>> confirmed_events = get_events_by_type(events, EVENT_CONFIRMED)
        >>> len(confirmed_events)
        15
    """
    return [event for event in events if event.event_type == event_type]


def print_event_summary(events: list[TrackEvent]) -> None:
    """
    Print human-readable summary of events.

    Args:
        events: Lista de TrackEvent

    Example:
        >>> print_event_summary(events)
        Event Log Summary (1000 events)
        ================================
        appeared:   150 (15.0%)
        updated:    450 (45.0%)
        confirmed:   80 (8.0%)
        missed:     200 (20.0%)
        removed:    120 (12.0%)

        Unique tracks: 45
        Frames covered: 1-500
    """
    if not events:
        print("Event log is empty")
        return

    total = len(events)
    by_type = {}
    unique_tracks = set()
    frame_ids = []

    for event in events:
        by_type[event.event_type] = by_type.get(event.event_type, 0) + 1
        unique_tracks.add(event.track_id)
        frame_ids.append(event.frame_id)

    print(f"Event Log Summary ({total} events)")
    print("=" * 40)
    for event_type in [EVENT_APPEARED, EVENT_UPDATED, EVENT_CONFIRMED, EVENT_MISSED, EVENT_REMOVED]:
        count = by_type.get(event_type, 0)
        pct = (count / total * 100) if total > 0 else 0
        print(f"{event_type:12s}: {count:5d} ({pct:5.1f}%)")

    print()
    print(f"Unique tracks: {len(unique_tracks)}")
    print(f"Frames covered: {min(frame_ids)}-{max(frame_ids)}")
