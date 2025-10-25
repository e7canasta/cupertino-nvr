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
RTSP Streams → StreamProcessor → MQTT Broker → VideoWall(s)
              (InferencePipeline)  (Events)    (Visualization)
```

### Key Technical Decisions

- **Stateless components**: Processor and Wall don't maintain state beyond cache TTL
- **MQTT QoS 0**: Fire-and-forget for real-time video (no delivery guarantees)
- **Thread-safe cache**: DetectionCache uses locks and automatic TTL expiration
- **Signal handling**: Graceful shutdown on SIGINT/SIGTERM
- **Lazy imports**: InferencePipeline imported only when needed to avoid hard dependency

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

### Adding Event Fields

1. Update `cupertino_nvr/events/schema.py` with new Pydantic field
2. Update `cupertino_nvr/processor/mqtt_sink.py` to populate field
3. Add unit test in `tests/unit/test_events.py`

### Adding Configuration Options

1. Update config dataclass in `processor/config.py` or `wall/config.py`
2. Add CLI option in `cli.py` if needed
3. Use in implementation

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
The parent `inference` package must be installed separately:
```bash
cd ../..  # Go to repo root
pip install -e .
cd cupertino/nvr
```

## Common Issues

### "ModuleNotFoundError: No module named 'inference'"
Install parent inference package from repo root: `pip install -e .`

### "Connection refused" on MQTT
Start MQTT broker: `docker run -d -p 1883:1883 eclipse-mosquitto`

### Import errors with relative imports
Use absolute imports: `from cupertino_nvr.events import ...`

## Testing Philosophy

- **Unit tests**: Mock external dependencies (MQTT, InferencePipeline)
- **Integration tests**: Require MQTT broker + RTSP streams + Roboflow Inference
- Tests are reviewed manually (pair-programming style)
- Always test: serialization, thread safety, error handling, TTL expiration

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
