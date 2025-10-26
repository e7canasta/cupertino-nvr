# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Cupertino NVR** - Headless Network Video Recorder with AI Inference and MQTT Control Plane

Event-driven NVR system with separated inference and visualization using MQTT pub/sub architecture. Built on Roboflow InferencePipeline with YOLOv8/YOLOv11 for object detection.

**Current Focus:** Production-ready control plane with dynamic runtime configuration (change models, add/remove streams, adjust FPS - all without restart).

## Core Architecture

### Three-Plane Design

```
┌─────────────────────────────────────────────────────────┐
│                    StreamProcessor                      │
│                                                         │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Data Plane  │  │ Control      │  │ Metrics      │  │
│  │ (Inference) │  │ Plane (MQTT) │  │ Plane        │  │
│  └──────┬──────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                │                  │          │
│         │ on_prediction  │ on_command       │ watchdog │
│         ▼                ▼                  ▼          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ MQTT Sink    │◄─┤ Command      │  │ Periodic     │ │
│  │ (pauseable)  │  │ Handlers     │  │ Reporter     │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────┘
```

**Data Plane:** InferencePipeline → MQTTDetectionSink → MQTT broker
**Control Plane:** MQTT commands → CommandRegistry → Handlers (pause/resume/restart/change_model/etc)
**Metrics Plane:** Watchdog → Periodic metrics → MQTT (every 10s by default)

### Critical Architectural Patterns

#### 1. Control Plane Initialization Order (CRITICAL!)

```python
# ✅ CORRECT ORDER (cupertino_nvr/processor/processor.py:63-255)
def start(self):
    # 1. Setup MQTT + Sink
    self.mqtt_client = self._init_mqtt_client()
    self.mqtt_sink = MQTTDetectionSink(...)

    # 2. Create pipeline (NOT started yet)
    self.pipeline = InferencePipeline.init(
        video_reference=streams,
        model_id=model_id,
        on_prediction=self.mqtt_sink,
    )

    # 3. Initialize Control Plane BEFORE pipeline.start()
    #    (pipeline.start() blocks 20+ seconds connecting to streams)
    if enable_control_plane:
        self.control_plane = MQTTControlPlane(...)
        self._setup_control_commands()
        self.control_plane.connect()
        logger.info("✅ CONTROL PLANE READY")

    # 4. Start pipeline (BLOCKS here!)
    self.pipeline.start()
    self.is_running = True
```

**Why this order matters:**
- `pipeline.start()` blocks for 20+ seconds connecting to RTSP streams
- If control plane is initialized AFTER, commands sent during startup are lost
- Commands must work immediately (even during pipeline connection phase)

See: `docs/nvr/BLUEPRINT_INFERENCE_PIPELINE_CONTROL.md` for complete rationale.

#### 2. Thread-Safe Sink Pause (threading.Event pattern)

```python
# ✅ CORRECT (cupertino_nvr/processor/mqtt_sink.py:65-92)
class MQTTDetectionSink:
    def __init__(self):
        # Use threading.Event (NOT boolean flag!)
        self._running = threading.Event()
        self._running.set()  # Start running

    def __call__(self, predictions, video_frame):
        # Check pause FIRST (memory barrier guaranteed)
        if not self._running.is_set():
            return

        # Publish detections...

    def pause(self):
        self._running.clear()  # Memory barrier

    def resume(self):
        self._running.set()  # Memory barrier
```

**Why threading.Event:**
- ✅ Built-in memory barriers (CPU cache flush across cores)
- ✅ Thread-safe without explicit locks
- ✅ Minimal overhead (~50ns per check)
- ❌ Boolean flags have memory visibility issues (GIL != memory barriers)

#### 3. Two-Level Pause (Immediate + Graceful)

```python
# ✅ CORRECT PAUSE ORDER (cupertino_nvr/processor/processor.py:455-511)
def _handle_pause(self):
    # Check pipeline exists (NOT is_running flag!)
    if self.pipeline and not self.is_paused:
        # Step 1: Pause sink FIRST (immediate stop)
        self.sink.pause()

        # Step 2: Pause pipeline (gradual - frames in queue still process)
        self.pipeline.pause_stream()

        self.is_paused = True
        self.control_plane.publish_status("paused")

# ✅ CORRECT RESUME ORDER (cupertino_nvr/processor/processor.py:513-569)
def _handle_resume(self):
    if self.pipeline and self.is_paused:
        # Step 1: Resume pipeline FIRST (start buffering frames)
        self.pipeline.resume_stream()

        # Step 2: Resume sink (start publishing)
        self.sink.resume()

        self.is_paused = False
        self.control_plane.publish_status("running")
```

**Pause order:** Sink first (immediate), pipeline second (gradual)
**Resume order:** Pipeline first (buffer ready), sink second (publish)

**Workaround:** `pipeline.pause_stream()` only stops buffering NEW frames. Frames already in prediction queue continue processing for ~5-10s. Sink-level pause provides immediate stop of publications.

## Development Commands

### Setup

```bash
# Install in development mode
pip install -e ".[dev]"

# Or using uv (faster)
uv pip install -e ".[dev]"
```

### Running Locally

```bash
# Start MQTT broker (required for all modes)
docker run -d --name mosquitto -p 1883:1883 eclipse-mosquitto

# Run processor (headless inference with control plane)
cupertino-nvr processor \
    --n 6 \
    --model yolov8x-640 \
    --enable-control \
    --metrics-interval 10

# Run wall (visualization - subscribes to detection events)
cupertino-nvr wall --n 6

# Monitor MQTT events
mosquitto_sub -h localhost -t "nvr/#" -v | jq
```

### MQTT Control Commands

All commands use JSON format on topic `nvr/control/commands`:

```bash
# Basic Control
mosquitto_pub -t nvr/control/commands -m '{"command": "pause", "target_instances": ["*"]}'
mosquitto_pub -t nvr/control/commands -m '{"command": "resume", "target_instances": ["*"]}'
mosquitto_pub -t nvr/control/commands -m '{"command": "stop", "target_instances": ["*"]}'
mosquitto_pub -t nvr/control/commands -m '{"command": "status", "target_instances": ["*"]}'
mosquitto_pub -t nvr/control/commands -m '{"command": "metrics", "target_instances": ["*"]}'

# Dynamic Configuration (NO RESTART REQUIRED!)
mosquitto_pub -t nvr/control/commands -m '{"command": "change_model", "params": {"model_id": "yolov11x-640"}, "target_instances": ["*"]}'
mosquitto_pub -t nvr/control/commands -m '{"command": "set_fps", "params": {"max_fps": 0.5}, "target_instances": ["*"]}'
mosquitto_pub -t nvr/control/commands -m '{"command": "add_stream", "params": {"source_id": 8}, "target_instances": ["*"]}'
mosquitto_pub -t nvr/control/commands -m '{"command": "remove_stream", "params": {"source_id": 2}, "target_instances": ["*"]}'

# Discovery & Orchestration
mosquitto_pub -t nvr/control/commands -m '{"command": "ping", "target_instances": ["*"]}'
mosquitto_pub -t nvr/control/commands -m '{"command": "rename_instance", "params": {"new_instance_id": "emergency-room-2"}, "target_instances": ["processor-xyz123"]}'
```

**Multi-instance targeting:**
- `"target_instances": ["*"]` → Broadcast to all processors
- `"target_instances": ["proc-a"]` → Single processor
- `"target_instances": ["proc-a", "proc-b"]` → Multiple processors

**Command acknowledgments:**
- ACK "received" published immediately on `nvr/control/status/{instance_id}/ack`
- ACK "completed" or "error" published after execution

### Testing Control Plane

```bash
# Manual test scripts (see test_*.sh)
./test_restart_command.sh      # Test RESTART command
./test_dynamic_config.sh        # Test model/FPS changes
./test_metrics.sh               # Test metrics reporting

# Debug logging
JSON_LOGS=true LOG_LEVEL=DEBUG cupertino-nvr processor --enable-control
```

### Code Quality

```bash
# Format (black + isort)
black cupertino_nvr/ tests/
isort cupertino_nvr/ tests/

# Lint
flake8 cupertino_nvr/ tests/
mypy cupertino_nvr/

# Tests (manual execution - pair programming style)
pytest tests/unit/ -v
pytest tests/unit/test_events.py::test_detection_event_serialization -v
```

## Code Structure & Key Files

### StreamProcessor Architecture

**Core files:**
- `cupertino_nvr/processor/processor.py` - Main service class (1524 lines)
  - `start()` - Initialization order (CRITICAL - see line 63-255)
  - `_handle_pause/resume/stop()` - Basic control (line 455-615)
  - `_handle_restart()` - Pipeline recreation (line 792-967)
  - `_handle_change_model/set_fps/add_stream/remove_stream()` - Dynamic config (line 969-1324)
  - `_handle_ping()` - Discovery pattern (line 673-726)

- `cupertino_nvr/processor/mqtt_sink.py` - Thread-safe detection publisher
  - Uses `threading.Event` for pause control (line 65-92)
  - Handles both single and batch predictions (line 94-150)

- `cupertino_nvr/processor/control_plane.py` - MQTT command handling
  - `CommandRegistry` - Command registration and execution (line 28-91)
  - `MQTTControlPlane` - MQTT client wrapper (line 93-413)
  - Instance filtering (`_should_process_command()` - line 282-297)

- `cupertino_nvr/processor/config.py` - Configuration dataclass
  - `StreamProcessorConfig` with defaults and validation
  - Instance ID auto-generation (UUID-based)

### Event Protocol

- `cupertino_nvr/events/schema.py` - Pydantic schemas
  - `DetectionEvent`, `Detection`, `BoundingBox`
  - JSON serialization/deserialization

- `cupertino_nvr/events/protocol.py` - MQTT topic utilities
  - `topic_for_source(prefix, source_id)` → `"nvr/detections/0"`
  - `parse_source_id_from_topic(topic)` → `0`

### Wall (Visualization)

- `cupertino_nvr/wall/wall.py` - Video wall main
- `cupertino_nvr/wall/renderer.py` - Detection overlay (uses `supervision` annotators)
- `cupertino_nvr/wall/detection_cache.py` - TTL-based cache (thread-safe)
- `cupertino_nvr/wall/mqtt_listener.py` - Event subscriber

## Important Implementation Notes

### Dynamic Configuration Pattern

All dynamic config commands (`change_model`, `set_fps`, `add_stream`, `remove_stream`) follow this pattern:

```python
def _handle_change_model(self, params: dict):
    # 1. Validate params
    new_model_id = params.get('model_id')
    if not new_model_id:
        raise ValueError("Missing required parameter: model_id")

    # 2. Backup for rollback
    old_model_id = self.config.model_id

    # 3. Publish intermediate status
    self.control_plane.publish_status("reconfiguring")

    try:
        # 4. Update config
        self.config.model_id = new_model_id

        # 5. Restart pipeline with new config
        self._handle_restart()  # Terminates old, creates new, starts

        # 6. Status published by restart handler ("running" or "error")

    except Exception as e:
        # 7. Rollback on failure
        self.config.model_id = old_model_id
        self.control_plane.publish_status("error")
        raise
```

**Key insight:** Config changes trigger `_handle_restart()` which:
1. Terminates current pipeline
2. Sets `_is_restarting = True` flag
3. Recreates pipeline with updated config
4. Restarts pipeline
5. `join()` detects restart and rejoins new pipeline (line 280-387)

### go2rtc Proxy Pattern

Stream URIs follow go2rtc convention:
```python
# CLI: --stream-server rtsp://go2rtc-server
# Auto-generates: rtsp://go2rtc-server/0, rtsp://go2rtc-server/1, ...

# ADD_STREAM command:
# source_id=8 → rtsp://go2rtc-server/8
stream_uri = f"{self.config.stream_server}/{source_id}"
```

This allows dynamic stream addition without pre-configuring URIs.

See: `docs/nvr/GO2RTC_PROXY_ARCHITECTURE.md`

### Structured Logging

Uses `python-json-logger` for machine-readable logs:

```python
from cupertino_nvr.logging_utils import log_event, log_command, log_mqtt_event

log_event(logger, "info", "Pipeline started",
    component="processor", event="pipeline_started", model_id=model_id)

log_command(logger, "pause", "received", component="control_plane")

log_mqtt_event(logger, "published", topic, component="control_plane", status="paused")
```

**Environment variables:**
- `JSON_LOGS=true` - Enable JSON format (default: human-readable)
- `LOG_LEVEL=DEBUG` - Set log level (default: INFO)

### Metrics & Watchdog

```python
# Enable watchdog in config
config.enable_watchdog = True  # Default: True
config.metrics_reporting_interval = 10  # Seconds (0 = disabled)

# Watchdog provides:
# - inference_throughput (inferences/second)
# - latency_reports (per-source e2e/decoding/inference latency)
# - sources_metadata (FPS, resolution)
# - status_updates (warnings, errors)

# Metrics published to: nvr/status/metrics/{instance_id}
# Full report on-demand: {"command": "metrics"}
```

## Common Pitfalls & Solutions

### ❌ 1. Control Plane After pipeline.start()

```python
# WRONG
self.pipeline.start()  # Blocks 20+ seconds
self.control_plane = MQTTControlPlane(...)  # Too late!
```

**Fix:** Initialize control plane BEFORE `pipeline.start()` (see line 157 in processor.py)

### ❌ 2. Checking is_running in Handlers

```python
# WRONG
if self.is_running:  # False during startup!
    self.pipeline.pause()
```

**Fix:** Check `if self.pipeline:` (object exists, not state flag)

### ❌ 3. Boolean Flag for Pause

```python
# WRONG - Memory visibility issue
self._paused = False
if self._paused:  # May read stale value from CPU cache
    return
```

**Fix:** Use `threading.Event` (built-in memory barriers)

### ❌ 4. Heavy Model Initialization

```python
# WRONG - InferencePipeline may try to download SAM2/CLIP/etc
from inference import InferencePipeline  # Import at module level
```

**Fix:** Disable heavy models BEFORE import (see cli.py:16-25)
```python
# Set env vars BEFORE importing inference
os.environ["CORE_MODEL_SAM2_ENABLED"] = "False"
os.environ["CORE_MODEL_CLIP_ENABLED"] = "False"
# ... then import
```

## Git Workflow

### Commit Convention

```
Co-Authored-By: Gaby <noreply@visiona.com>
```

**NOT** "Generated with Claude Code" (the Co-Authored-By makes it clear).

### Testing Philosophy

- Tests are executed manually (pair-programming style, not CI/CD automated)
- Focus on: serialization round-trips, thread safety, TTL expiration, error handling
- Mock external dependencies (MQTT client, VideoFrame objects)
- Integration tests require: MQTT broker + RTSP streams + Roboflow Inference installed

## Documentation References

**Project docs:**
- `docs/nvr/BLUEPRINT_INFERENCE_PIPELINE_CONTROL.md` - Complete control plane guide
- `docs/nvr/QUICK_REFERENCE_CONTROL_PLANE.md` - Quick reference for common patterns
- `docs/nvr/GO2RTC_PROXY_ARCHITECTURE.md` - Stream proxy pattern
- `docs/nvr/DISCOVERY_HEARTBEAT_PATTERN.md` - PING/PONG orchestration
- `docs/nvr/IOT_COMMAND_PATTERN.md` - Command ACK protocol
- `docs/nvr/WATCHDOG_EXPLAINED.md` - Metrics collection

**Reference docs (Roboflow):**
- `docs/references/adeline/` - Reference architecture (similar control plane)
- `docs/references/roboflow/inference/` - InferencePipeline docs
- `docs/references/roboflow/supervision/` - Detection annotation library

## Performance & Deployment

**Targets:**
- End-to-end latency: <200ms (RTSP → MQTT publish)
- CPU usage: 55-65% for 12 streams (6-core Intel i5-10400)
- Memory (Processor): ~2.5GB
- Memory (Wall): ~800MB
- Scalability: N processors + M viewers (horizontal scaling via MQTT)

**Production considerations:**
- Use `--json-logs` for log aggregation (Elasticsearch, Loki)
- Set `--metrics-interval 60` for production (lower overhead)
- Use `--instance-id` for meaningful names (e.g., "emergency-room-1")
- Monitor MQTT ACK topics for command failures
- Use retained messages for status (new subscribers get last state)

## Current Status

**Version:** 0.1.0
**Status:** MVP Phase 1 Complete + Control Plane Production-Ready

**Completed:**
✅ Event protocol with Pydantic schemas
✅ StreamProcessor with MQTT publishing
✅ VideoWall with MQTT consumption
✅ CLI commands
✅ MQTT Control Plane (pause/resume/stop/status/metrics)
✅ Dynamic Configuration (change_model/set_fps/add_stream/remove_stream)
✅ Discovery Pattern (PING/PONG)
✅ Multi-instance orchestration
✅ Structured JSON logging
✅ Metrics reporting (watchdog integration)

**Next:**
🟡 Long-running stability tests (24+ hours)
🟡 Performance validation on target hardware
🟡 Event store integration (PostgreSQL/TimescaleDB)
🟡 Web UI for orchestration
