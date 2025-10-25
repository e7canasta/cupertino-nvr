# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Cupertino NVR** - Distributed Network Video Recorder with AI Inference

Event-driven NVR system with separated inference and visualization using MQTT pub/sub architecture. Built on Roboflow Inference with YOLOv8 for object detection.

## Architecture

### Bounded Contexts (Clear Separation of Concerns)

1. **Processor** (`cupertino_nvr/processor/`) - Inference domain
   - Headless inference pipeline wrapping InferencePipeline
   - Publishes DetectionEvent to MQTT broker
   - No GUI overhead, designed for scalability

2. **Wall** (`cupertino_nvr/wall/`) - Visualization domain
   - Event-driven viewer consuming MQTT events
   - Multiplexes video streams with detection overlays
   - Thread-safe DetectionCache with TTL for event storage

3. **Events** (`cupertino_nvr/events/`) - Integration domain
   - Pydantic schemas for DetectionEvent, Detection, BoundingBox
   - MQTT topic protocol: `nvr/detections/{source_id}`
   - Type-safe serialization/deserialization

### Data Flow

```
RTSP Streams → InferencePipeline → MQTTDetectionSink → MQTT Broker
    ↓              (YOLOv8)           (on_prediction)       ↓
VideoSource                                          MQTTListener
    ↓                                                       ↓
VideoFrame                                          DetectionCache (TTL)
    ↓                                                       ↓
multiplex_videos → DetectionRenderer → cv2.imshow("NVR Video Wall")
    (grid)         (overlay detections)
```

**Critical architectural pattern**: The processor and wall are completely decoupled via MQTT pub/sub. Processor knows nothing about the wall. Wall subscribes to events by source_id topic pattern.

### Key Technical Decisions

- **InferencePipeline callback pattern**: MQTTDetectionSink implements `__call__` to be compatible with `on_prediction` callback signature
- **VideoFrame attributes**: Uses `frame.source_id`, `frame.frame_id`, `frame.frame_timestamp` from Roboflow Inference
- **MQTT QoS 0**: Fire-and-forget for real-time video (no delivery guarantees, lower latency)
- **TTL-based cache expiration**: DetectionCache automatically expires old events on `get()` - no background cleanup thread needed
- **Thread-safe cache**: Uses `threading.Lock` for concurrent access from MQTT listener thread and main render thread
- **Signal handling**: Graceful shutdown on SIGINT/SIGTERM in both processor and wall
- **Lazy imports**: InferencePipeline/VideoSource imported only when `start()` called to avoid hard dependency
- **Global STOP flag**: Used by signal handlers to communicate with multiplex_videos `should_stop` callback

## Development Commands

### Setup & Installation

```bash
# Install in development mode (from nvr directory)
pip install -e ".[dev]"

# Or using Makefile
make install-dev
```

### Testing

```bash
# Run all unit tests
pytest tests/unit/ -v

# Run specific test file
pytest tests/unit/test_events.py -v

# Run with coverage
pytest tests/unit/ --cov=cupertino_nvr --cov-report=html

# Using Makefile
make test           # All tests
make test-unit      # Unit tests only
make coverage       # With coverage report
```

### Code Quality

```bash
# Format code
black cupertino_nvr/ tests/
isort cupertino_nvr/ tests/

# Lint
flake8 cupertino_nvr/ tests/
mypy cupertino_nvr/

# Using Makefile
make format
make lint
```

### Running Locally

```bash
# Start MQTT broker (required)
docker run -d --name mosquitto -p 1883:1883 eclipse-mosquitto
# Or: make run-broker

# Run processor (headless inference)
cupertino-nvr processor --n 6 --model yolov8x-640

# Run wall (viewer)
cupertino-nvr wall --n 6

# Using Makefile
make run-processor N=6 MODEL=yolov8x-640
make run-wall N=6
```

### Debugging MQTT

```bash
# Monitor all detection events
mosquitto_sub -h localhost -t "nvr/detections/#" -v

# Pretty print JSON
mosquitto_sub -h localhost -t "nvr/detections/#" | jq

# Test connection
mosquitto_pub -h localhost -t "test" -m "hello"
```

## Code Structure Guidelines

### Understanding the Callback Pattern

**MQTTDetectionSink** is designed as a callable object to work with InferencePipeline:
```python
# InferencePipeline calls: on_prediction(predictions, video_frame)
# MQTTDetectionSink implements: __call__(predictions, video_frame)

# Signature handles both single and batch predictions:
# - Single: prediction=dict, video_frame=VideoFrame
# - Batch: predictions=List[dict], video_frames=List[VideoFrame]
```

This pattern allows the sink to be passed directly to `InferencePipeline.init(on_prediction=sink)`.

### Adding Event Fields

1. Update `cupertino_nvr/events/schema.py` with new Pydantic field
2. Update `cupertino_nvr/processor/mqtt_sink.py` in `_create_event()` method
3. Update `cupertino_nvr/wall/renderer.py` if visualization needed
4. Add unit test in `tests/unit/test_events.py`

**Example flow**: To add "detection_count" field:
- Schema: `detection_count: int = Field(...)`
- MQTTSink: `detection_count=len(prediction.get("predictions", []))`
- Renderer: Use `event.detection_count` for overlay text
- Test: Verify serialization round-trip

### Adding Configuration Options

1. Update config dataclass in `processor/config.py` or `wall/config.py`
2. Add CLI option in `cli.py` if user-facing
3. Use in implementation (access via `self.config.option_name`)

**Note**: CLI uses `--n` for number of streams and auto-generates URIs like `rtsp://server/live/{i}.stream`.

### Environment Variables

- `STREAM_SERVER`: Default RTSP server URL (fallback: `rtsp://localhost:8554`)
- Used by CLI when `--stream-server` not provided

### Import Conventions

Use absolute imports (not relative):
```python
# ✅ Good
from cupertino_nvr.events import DetectionEvent

# ❌ Bad
from .events import DetectionEvent
```

## Important Design Principles

This codebase follows the **Visiona Design Manifesto** ("Blues Style"):

### Pragmatismo > Purismo
- Reuse proven components (InferencePipeline, supervision)
- Simple solutions that work (JSON over MQTT, not MessagePack)
- MVP functionality first, optimization later

### Bounded Contexts Claros
- Processor, Wall, and Events are independent modules
- Each has single responsibility and minimal coupling
- Processor doesn't know about Wall (pub/sub decoupling)

### KISS ≠ Simplicidad Ingenua
- Simple architecture, not simplistic
- DetectionCache has TTL to prevent memory leaks
- Thread-safe operations with proper locking
- Graceful error handling throughout

### Diseño Evolutivo
- Extension points for Phase 2 (event store, web UI)
- Clean interfaces for future enhancements
- No premature optimization

## Dependencies

### Core Dependencies
- `paho-mqtt` - MQTT client for pub/sub messaging
- `pydantic` - Schema validation and serialization
- `opencv-python` - Video processing
- `supervision` - Detection annotations
- Roboflow Inference (external) - Core inference engine

### Installation Note
The parent `inference` package must be installed separately (Roboflow Inference framework):
```bash
cd ../..  # Go to repo root (inference/)
pip install -e .
cd cupertino/nvr
```

**Why separate**: `cupertino-nvr` is an independent package that uses Roboflow Inference as a library, not part of the inference core. This allows separate versioning and deployment.

## Common Issues & Debugging

### "ModuleNotFoundError: No module named 'inference'"
Install parent inference package from repo root: `pip install -e .`

### "Connection refused" on MQTT
Start MQTT broker: `docker run -d -p 1883:1883 eclipse-mosquitto`

Check broker is running: `docker ps | grep mosquitto`

### No detections appearing in VideoWall
1. Verify processor is publishing: `mosquitto_sub -t "nvr/detections/#" -v`
2. Check topic pattern matches: Topics should be `nvr/detections/0`, `nvr/detections/1`, etc.
3. Verify cache TTL not expiring too fast (default 1 second)
4. Check MQTT connection in wall logs

### Import errors with relative imports
Use absolute imports: `from cupertino_nvr.events import ...`

### AttributeError on VideoFrame
Ensure using Roboflow Inference's `VideoFrame` which has `source_id`, `frame_id`, `frame_timestamp` attributes.

## Testing Philosophy

- **Unit tests**: Mock external dependencies (MQTT client, VideoFrame objects)
- **Integration tests**: Require MQTT broker + RTSP streams + Roboflow Inference installed
- **Manual test execution**: Tests are reviewed and run manually (pair-programming style, not CI/CD automated)
- **Test coverage focus**: Serialization round-trips, thread safety (concurrent access), error handling (missing data), TTL expiration logic

### Running Single Tests

```bash
# Single test file
pytest tests/unit/test_events.py -v

# Single test function
pytest tests/unit/test_events.py::test_detection_event_serialization -v

# Single test with output
pytest tests/unit/test_cache.py::test_cache_ttl_expiration -v -s
```

## Git Commit Convention

Commits use:
```
Co-Authored-By: Gaby <noreply@visiona.com>
```

NOT "Generated with Claude Code" - the Co-Authored-By makes it clear.

## Documentation References

- **[README.md](README.md)** - User-facing documentation and quick start
- **[DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md)** - Detailed developer reference
- **[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)** - Current implementation status
- **[../../wiki/DESIGN_NVR_MULTIPLEXER.md](../../wiki/DESIGN_NVR_MULTIPLEXER.md)** - Complete architecture design
- **[../../wiki/MANIFESTO_DISENO - Blues Style.md](../../wiki/MANIFESTO_DISENO%20-%20Blues%20Style.md)** - Design philosophy

## Performance Targets

- End-to-end latency: <200ms (RTSP → display)
- CPU usage: 55-65% for 12 streams (6-core Intel i5-10400)
- Memory (Processor): ~2.5GB
- Memory (Wall): ~800MB
- Scalability: N processors + M viewers (horizontal scaling)

## Current Status

**Version:** 0.1.0
**Status:** MVP Phase 1 Complete
**Next:** Integration testing and deployment

### Completed
✅ Event protocol with Pydantic schemas
✅ StreamProcessor with MQTT publishing
✅ VideoWall with MQTT consumption
✅ CLI commands
✅ Unit tests >80% coverage

### Pending
🟡 Integration tests (requires hardware setup)
🟡 Long-running stability tests (1+ hours)
🟡 Performance validation on target hardware

## Implementation Notes

### MQTT Topic Hierarchy
- Pattern: `{prefix}/{source_id}` (e.g., `nvr/detections/0`)
- Prefix configurable via `StreamProcessorConfig.mqtt_topic_prefix`
- Wall subscribes to wildcard: `nvr/detections/#` to receive all sources
- Protocol utilities in `events/protocol.py`: `topic_for_source()`, `parse_source_id_from_topic()`

### DetectionCache TTL Mechanism
- **On write**: Stores `(event, timestamp)` tuple
- **On read**: Checks `datetime.now() - timestamp > ttl` and auto-deletes if expired
- **No background thread**: Expiration happens lazily during `get()` calls
- **Thread-safe**: All operations protected by `threading.Lock`

This design prevents memory leaks without requiring a cleanup thread - expired entries are removed when accessed.

### VideoWall Rendering Pipeline
1. `multiplex_videos()` yields `List[VideoFrame]` batches (one frame per camera)
2. For each frame, look up cached detections by `frame.source_id`
3. `DetectionRenderer.render_frame()` draws bboxes and labels using supervision annotators
4. Frames arranged in grid (configurable columns)
5. Grid displayed via `cv2.imshow()`

**Key insight**: Wall doesn't do inference. It only renders frames + overlays from MQTT events.

**Recent refactor (2025-10-25)**: DetectionRenderer migrated from raw OpenCV to supervision annotators (`BoxAnnotator`, `LabelAnnotator`). This provides:
- Better visual quality (optimized drawing)
- Less code (~68% reduction in `_draw_detections`)
- Extensibility for keypoints/segmentation (see `docs/wiki/QUICKWIN_SUPERVISION_INTEGRATION.md`)
