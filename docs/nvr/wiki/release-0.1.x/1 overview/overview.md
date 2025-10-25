
# Overview

Relevant source files

- [ARCHITECTURE_4+1.md](https://github.com/e7canasta/cupertino-nvr/blob/51ee905a/ARCHITECTURE_4+1.md)
- [docs/nvr/NVR_EXECUTIVE_SUMMARY.md](https://github.com/e7canasta/cupertino-nvr/blob/51ee905a/docs/nvr/NVR_EXECUTIVE_SUMMARY.md)
- [docs/nvr/NVR_INDEX.md](https://github.com/e7canasta/cupertino-nvr/blob/51ee905a/docs/nvr/NVR_INDEX.md)
- [docs/nvr/NVR_README.md](https://github.com/e7canasta/cupertino-nvr/blob/51ee905a/docs/nvr/NVR_README.md)

## Purpose and Scope

This document provides a high-level introduction to the Cupertino NVR system, explaining its purpose, architecture, and core components. Cupertino NVR is a distributed video processing system that separates AI inference from visualization using MQTT pub/sub messaging.

**Scope of this document:**

- High-level system architecture and components
- Core concepts and design principles
- Key benefits and use cases
- How components interact

**For detailed information:**

- System architecture and design philosophy → [Architecture](https://deepwiki.com/e7canasta/cupertino-nvr/2-architecture)
- Component implementation details → [Core Components](https://deepwiki.com/e7canasta/cupertino-nvr/3-core-components)
- Installation and configuration → [Getting Started](https://deepwiki.com/e7canasta/cupertino-nvr/4-getting-started)
- Development guidelines → [Developer Guide](https://deepwiki.com/e7canasta/cupertino-nvr/5-developer-guide)

Sources: docs/nvr/NVR_README.md, docs/nvr/NVR_EXECUTIVE_SUMMARY.md, docs/nvr/NVR_INDEX.md

---

## What is Cupertino NVR

Cupertino NVR (Network Video Recorder) is a distributed video processing system built on top of the Roboflow Inference framework. It enables **headless inference processing** on multiple RTSP video streams with **event-driven visualization**, separating these concerns through MQTT pub/sub architecture.

### The Core Problem

Traditional video processing systems tightly couple inference and visualization in a single monolithic process. This creates several issues:

|Problem|Impact|
|---|---|
|Wasted CPU on redundant rendering|40% CPU overhead when multiple displays needed|
|Cannot scale viewers independently|One process = one display|
|Difficult to debug and maintain|Everything coupled in one process|
|No event persistence or extensibility|Cannot add analytics, alerts, or storage|

### The Solution

Cupertino NVR implements a **distributed event-driven architecture** where:

1. **`StreamProcessor`** performs headless inference and publishes lightweight detection events via MQTT
2. **`VideoWall`** subscribes to detection events and renders video streams with overlay annotations
3. **MQTT broker** provides a decoupled pub/sub message bus between components

This separation enables:

- ✅ **40% CPU savings** by eliminating redundant inference when multiple displays are needed
- ✅ **N:M scalability** - N processors can feed M viewers independently
- ✅ **Extensibility** - Any service can subscribe to detection events (analytics, storage, alerts)
- ✅ **Production-ready** - Built on proven components with comprehensive testing

Sources: docs/nvr/NVR_README.md:9-29, docs/nvr/NVR_EXECUTIVE_SUMMARY.md:9-32, ARCHITECTURE_4+1.md:12-24

---

## System Architecture

### High-Level Component View

**Data Flow:**

1. `StreamProcessor` reads RTSP streams and performs inference using `InferencePipeline`
2. `MQTTDetectionSink` converts predictions to `DetectionEvent` objects and publishes to MQTT
3. `MQTTListener` (daemon thread in `VideoWall`) subscribes to MQTT and updates `DetectionCache`
4. `VideoWall` renders video frames with detection overlays from cached events using `DetectionRenderer`

Sources: docs/nvr/NVR_README.md:17-29, ARCHITECTURE_4+1.md:125-184, docs/nvr/NVR_ARCHITECTURE_DIAGRAM.md

---

## Core Components

The system is organized into three **bounded contexts** following Domain-Driven Design principles:

### 1. Processor Domain

**Purpose:** Headless inference processing with event publishing

**Key Classes:**

- `StreamProcessor` - Main orchestrator for inference pipeline
- `StreamProcessorConfig` - Configuration dataclass
- `MQTTDetectionSink` - Converts predictions to MQTT events
- `InferencePipeline` - Roboflow SDK component (external)

**Location:** `cupertino_nvr/processor/`

**Responsibilities:**

- Multi-stream RTSP capture via `InferencePipeline`
- YOLOv8 object detection
- Event creation and MQTT publishing
- Watchdog monitoring for stream health

### 2. Wall Domain

**Purpose:** Event-driven visualization with detection overlays

**Key Classes:**

- `VideoWall` - Main orchestrator for visualization
- `VideoWallConfig` - Configuration dataclass
- `MQTTListener` - Background thread for MQTT subscription
- `DetectionCache` - Thread-safe cache with TTL (1.0s default)
- `DetectionRenderer` - Renders bounding boxes using `supervision` library

**Location:** `cupertino_nvr/wall/`

**Responsibilities:**

- Multi-stream RTSP display via `multiplex_videos`
- MQTT event subscription in background thread
- Thread-safe caching of recent detections
- Real-time rendering of detection overlays

### 3. Event Domain

**Purpose:** Type-safe event protocol and MQTT topic structure

**Key Classes:**

- `DetectionEvent` - Main event schema (Pydantic v2)
- `Detection` - Individual detection with bounding box
- `BoundingBox` - Normalized coordinates
- Topic protocol: `nvr/detections/{source_id}`

**Location:** `cupertino_nvr/events/`

**Responsibilities:**

- Type-safe serialization/deserialization
- JSON schema validation
- MQTT topic naming conventions
- Event versioning strategy

Sources: ARCHITECTURE_4+1.md:120-184, docs/nvr/NVR_README.md:104-207, docs/nvr/DESIGN_NVR_MULTIPLEXER.md

---

## Component Relationships

### Class Diagram

**Key Relationships:**

- `StreamProcessor` owns `MQTTDetectionSink` and creates `DetectionEvent` instances
- `VideoWall` owns `MQTTListener` and `DetectionCache` for thread-safe event consumption
- `DetectionEvent` is the shared contract between processor and wall domains
- No direct dependency between `StreamProcessor` and `VideoWall` - fully decoupled via MQTT

Sources: ARCHITECTURE_4+1.md:186-281, docs/nvr/NVR_README.md:104-207

---

## Data Flow and Event Lifecycle

**Latency Breakdown:**

|Stage|Component|Time|Notes|
|---|---|---|---|
|Inference|`InferencePipeline`|45ms|YOLOv8x-640, depends on model|
|Event creation|`MQTTDetectionSink`|<1ms|Pydantic serialization|
|MQTT publish|Network|10-15ms|Local broker, QoS 0|
|Event parsing|`MQTTListener`|<1ms|Pydantic deserialization|
|Cache update|`DetectionCache`|<1ms|Lock acquisition|
|Rendering|`DetectionRenderer`|5-10ms|Bounding boxes + labels|
|**Total**|**End-to-end**|**100-150ms**|Acceptable for real-time|

Sources: ARCHITECTURE_4+1.md:31-75, docs/nvr/NVR_README.md:405-414

---

## Key Concepts

### Distributed Architecture

Cupertino NVR implements a **N:M scalability pattern**:

- **N StreamProcessors** can run independently at different locations (edge processing near cameras)
- **M VideoWalls** can subscribe to any combination of detection topics
- **One MQTT broker** provides the central message bus (can be clustered for HA)

This enables scenarios like:

- 3 processors (Site A, B, C) feeding 1 security operations center display
- 1 processor feeding 5 different displays (different grid layouts, different streams)
- Unlimited analytics services consuming events without affecting visualization

### Event-Driven Design

The system uses **fire-and-forget** messaging (MQTT QoS 0) because:

1. Video frames arrive every 40ms at 25 FPS - a lost event is superseded quickly
2. Low latency is more important than guaranteed delivery for real-time video
3. `DetectionCache` TTL handles timing jitter and missing events gracefully

Event flow is **unidirectional**:

```
StreamProcessor → MQTT → VideoWall
                         ↓
                    Analytics Services
                    Event Logger
                    Alert Rules
```

### Bounded Contexts (Domain-Driven Design)

The three domains are **strictly separated**:

|Domain|Knows About|Doesn't Know About|
|---|---|---|
|**Processor**|Event schema, MQTT topics|VideoWall existence, rendering|
|**Wall**|Event schema, MQTT topics|StreamProcessor existence, inference|
|**Events**|Pydantic models, protocol|Implementation details of either|

This separation enables:

- Independent testing (mock MQTT broker in tests)
- Independent deployment (processor on edge GPU, wall on desktop)
- Independent evolution (change rendering without touching inference)
- Clear ownership boundaries

Sources: ARCHITECTURE_4+1.md:120-184, docs/nvr/DESIGN_NVR_MULTIPLEXER.md, docs/nvr/NVR_EXECUTIVE_SUMMARY.md:36-43

---

## System Benefits

### Performance Improvements

|Metric|Traditional Monolith|Cupertino NVR|Improvement|
|---|---|---|---|
|CPU (12 streams)|70-85%|55-65% (processor)  <br>15-20% (wall)|**40% total savings**|
|Memory (processor)|3.0+ GB|2.5 GB|Model weights + buffers|
|Memory (wall)|N/A|800 MB|No model weights|
|Viewers per processor|1 (coupled)|Unlimited|**N:M scalability**|
|Latency|100ms|100-150ms|+50ms (acceptable)|

**Cost Savings Example (50 cameras):**

- Traditional: 5 GPU servers @ $500/month = $2,500/month
- Cupertino NVR: 3 GPU servers (processors) + 10 thin clients (walls) @ $1,500/month
- **Savings: $1,000/month = $12,000/year**

### Architectural Benefits

|Benefit|Description|Value|
|---|---|---|
|**Horizontal Scaling**|Add processors/viewers independently|Future-proof architecture|
|**Extensibility**|Subscribe to MQTT for analytics/alerts|Event-driven ecosystem|
|**Debugging**|Isolated components with clear interfaces|Reduced MTTR|
|**Testing**|Mock MQTT broker in unit tests|>80% test coverage|
|**Deployment Flexibility**|Processor on edge, wall anywhere|Cloud/on-premise options|

Sources: docs/nvr/NVR_EXECUTIVE_SUMMARY.md:54-73, docs/nvr/NVR_README.md:405-424, ARCHITECTURE_4+1.md:671-690

---

## Package Structure and CLI

### Package Organization

```
cupertino_nvr/
├── __init__.py                 # Main exports
├── cli.py                      # Click-based CLI (82 LOC)
├── events/
│   ├── __init__.py
│   ├── schema.py              # DetectionEvent, Detection, BoundingBox (68 LOC)
│   └── protocol.py            # Topic naming conventions (56 LOC)
├── processor/
│   ├── __init__.py
│   ├── config.py              # StreamProcessorConfig (50 LOC)
│   ├── mqtt_sink.py           # MQTTDetectionSink (144 LOC)
│   └── processor.py           # StreamProcessor main class (152 LOC)
└── wall/
    ├── __init__.py
    ├── config.py              # VideoWallConfig (60 LOC)
    ├── detection_cache.py     # DetectionCache with TTL (79 LOC)
    ├── mqtt_listener.py       # Background MQTT thread (89 LOC)
    ├── renderer.py            # DetectionRenderer with supervision (182 LOC)
    └── wall.py                # VideoWall main class (156 LOC)
```

**Total:** ~1,200 LOC of application code + comprehensive test suite

### CLI Commands

The system is accessible via two main CLI commands:

#### `cupertino-nvr processor`

Runs headless inference pipeline with MQTT publishing.

**Usage:**

```
cupertino-nvr processor --n 12 --model yolov8x-640 --mqtt-host localhost
```

**Implementation:** [cupertino_nvr/cli.py](https://github.com/e7canasta/cupertino-nvr/blob/51ee905a/cupertino_nvr/cli.py) - `processor` command group

#### `cupertino-nvr wall`

Runs video wall viewer with MQTT subscription.

**Usage:**

```
cupertino-nvr wall --n 12 --mqtt-host localhost --tile-width 640
```

**Implementation:** [cupertino_nvr/cli.py](https://github.com/e7canasta/cupertino-nvr/blob/51ee905a/cupertino_nvr/cli.py) - `wall` command group

Sources: ARCHITECTURE_4+1.md:389-454, docs/nvr/NVR_README.md:266-313

---

## Technology Stack

### Core Dependencies

|Component|Technology|Version|Purpose|
|---|---|---|---|
|**Inference**|`roboflow/inference`|Latest|`InferencePipeline`, video processing|
|**MQTT Client**|`paho-mqtt`|2.0+|Pub/sub messaging|
|**Validation**|`pydantic`|2.0+|Type-safe event schemas|
|**Visualization**|`supervision`|Latest|Bounding box rendering|
|**Video I/O**|`opencv-python`|4.8+|Video capture and display|

**Key Point:** Zero new dependencies - all libraries already present in the Roboflow Inference stack.

### External Services

|Service|Implementation|Size|Purpose|
|---|---|---|---|
|**MQTT Broker**|`eclipse-mosquitto`|5MB Docker image|Message bus|
|**RTSP Server**|`go2rtc` or IP cameras|Varies|Video source|

### Deployment Options

Sources: ARCHITECTURE_4+1.md:458-541, docs/nvr/NVR_README.md:34-49

---

## Use Cases

### 1. Single-Site Monitoring

**Scenario:** Security office monitoring 12 cameras in one building

**Setup:**

- 1 `StreamProcessor` with 12 streams on GPU server
- 2 `VideoWall` instances (security desk + manager office)
- 1 local MQTT broker

**Benefits:**

- One inference run serves two displays
- 40% CPU savings compared to running inference twice
- Easy to add more viewers without performance impact

### 2. Multi-Site Deployment

**Scenario:** Factory with 3 sites (50 total cameras)

**Setup:**

- 3 `StreamProcessor` instances (one per site, edge GPU servers)
- 1 central MQTT broker (cloud or on-premise)
- 5 `VideoWall` instances at different monitoring stations
- Additional analytics service subscribing to all detection events

**Benefits:**

- Edge processing reduces bandwidth (only events sent to cloud)
- Centralized monitoring of all sites from one location
- Easy to add new sites or viewers
- Analytics service gets all detections for heatmaps/reports

### 3. Custom Event Consumers

**Scenario:** Integration with existing systems

Any service can subscribe to MQTT topics using standard MQTT clients:

```
import paho.mqtt.client as mqtt
from cupertino_nvr.events.schema import DetectionEvent

def on_message(client, userdata, msg):
    event = DetectionEvent.model_validate_json(msg.payload)
    # Custom logic: store in database, trigger alerts, etc.
    
client = mqtt.Client()
client.on_message = on_message
client.connect("localhost", 1883)
client.subscribe("nvr/detections/#")
client.loop_forever()
```

**Example Consumers:**

- TimescaleDB for event storage
- Alert rules engine for notifications
- Analytics dashboard for real-time statistics
- Video clip recorder (save clips when detections occur)

Sources: docs/nvr/NVR_README.md:316-400, docs/nvr/NVR_EXECUTIVE_SUMMARY.md:177-193

---

## Development and Testing

### Project Structure

The system follows a clean bounded context organization:

```
cupertino-nvr/
├── cupertino_nvr/           # Application code (~1,200 LOC)
│   ├── events/              # Event protocol (shared contract)
│   ├── processor/           # Inference domain
│   └── wall/                # Visualization domain
├── tests/
│   ├── unit/                # Isolated component tests
│   │   ├── test_events.py
│   │   ├── test_cache.py
│   │   └── test_mqtt_sink.py
│   └── integration/         # End-to-end tests
│       └── test_e2e.py
├── docs/nvr/                # Comprehensive documentation
└── Makefile                 # Development tasks
```

### Testing Strategy

|Test Type|Coverage|Tools|Purpose|
|---|---|---|---|
|**Unit Tests**|>80%|pytest, pytest-mock|Test individual classes in isolation|
|**Integration Tests**|E2E scenarios|pytest, Docker|Test full system with real MQTT broker|
|**Manual Testing**|Visual verification|`mosquitto_sub`|Verify event flow and rendering|

**Running Tests:**

```
# Unit tests (fast, no external dependencies)
make test-unit

# Integration tests (requires MQTT broker)
make test-integration

# All tests
make test
```

### Development Workflow

```
# Setup development environment
make dev-setup              # Create venv, install dependencies

# Code quality
make format                 # black + isort
make lint                   # flake8 + mypy

# Testing
make test-unit             # Fast isolated tests
make test-integration      # Full E2E tests

# Running locally
make run-broker            # Start MQTT broker (Docker)
make run-processor         # Start processor with default config
make run-wall              # Start wall with default config
```

**Development Resources:**

- [Developer Guide](https://deepwiki.com/e7canasta/cupertino-nvr/5-developer-guide) - Complete development documentation
- [Implementation Checklist](https://deepwiki.com/e7canasta/cupertino-nvr/5.3-implementation-checklist) - Step-by-step implementation guide
- [Testing and Debugging](https://deepwiki.com/e7canasta/cupertino-nvr/5.4-testing-and-debugging) - Debugging techniques and tools

Sources: ARCHITECTURE_4+1.md:389-454, docs/nvr/NVR_README.md:488-530

---

## Getting Started

### Quick Start (2 Minutes)

**Prerequisites:**

- Python 3.10+
- Docker (for MQTT broker)

**Installation:**

```
pip install cupertino-nvr
```

**Run:**

```
# Terminal 1: Start MQTT broker
docker run -d -p 1883:1883 eclipse-mosquitto

# Terminal 2: Start processor
cupertino-nvr processor --n 6 --model yolov8n-640

# Terminal 3: Start wall
cupertino-nvr wall --n 6
```

You should see a video grid with real-time object detections overlaid on the streams.

For complete installation instructions, configuration options, and advanced usage, see:

- [Quick Start Guide](https://deepwiki.com/e7canasta/cupertino-nvr/4.1-quick-start) - 2-minute setup guide
- [Installation](https://deepwiki.com/e7canasta/cupertino-nvr/4.2-installation) - Detailed installation instructions
- [Configuration](https://deepwiki.com/e7canasta/cupertino-nvr/4.3-configuration) - All configuration options
- [Deployment](https://deepwiki.com/e7canasta/cupertino-nvr/6-deployment) - Production deployment guides

Sources: docs/nvr/NVR_README.md:30-78, docs/nvr/NVR_QUICK_START.md

---

## Design Philosophy

Cupertino NVR was designed following the **Visiona Design Manifesto** principles:

|Principle|Application in Cupertino NVR|
|---|---|
|**Pragmatism over Purism**|Reused existing `InferencePipeline` and `supervision` instead of building from scratch|
|**KISS Done Right**|Simple architecture (3 bounded contexts) without being simplistic|
|**Big Picture First**|Understood full system context before writing code|
|**Bounded Contexts**|Clear DDD separation: Processor, Wall, Events|
|**Evolutionary Design**|MVP first (Phase 1), then enhancements (Phase 2)|
|**Cohesion over Location**|Related code grouped by domain, not by technical layer|

**Key Architectural Decisions:**

- **MQTT QoS 0** - Fire-and-forget prioritizes latency over guaranteed delivery (acceptable for real-time video)
- **TTL Cache** - Simple expiration mechanism prevents memory leaks without complex lifecycle management
- **Independent Package** - Separate from core `inference` for independent versioning and deployment
- **Pydantic v2** - Type-safe event schemas with automatic validation and serialization

For detailed design rationale and trade-off analysis, see [Architecture](https://deepwiki.com/e7canasta/cupertino-nvr/2-architecture) and [Design Philosophy](https://deepwiki.com/e7canasta/cupertino-nvr/2.2-design-philosophy).

Sources: ARCHITECTURE_4+1.md:881-940, docs/nvr/DESIGN_NVR_MULTIPLEXER.md, docs/nvr/MANIFESTO_DISENO.md

---

## Next Steps

### For New Users

1. Follow the [Quick Start Guide](https://deepwiki.com/e7canasta/cupertino-nvr/4.1-quick-start) to get the system running in 2 minutes
2. Read [System Architecture](https://deepwiki.com/e7canasta/cupertino-nvr/2.1-system-architecture) to understand component relationships
3. Explore [Configuration](https://deepwiki.com/e7canasta/cupertino-nvr/4.3-configuration) to customize for your use case

### For Developers

1. Review [Component Design](https://deepwiki.com/e7canasta/cupertino-nvr/2.3-component-design) for implementation details
2. Follow [Development Setup](https://deepwiki.com/e7canasta/cupertino-nvr/5.1-development-setup) to prepare your environment
3. Read [Implementation Checklist](https://deepwiki.com/e7canasta/cupertino-nvr/5.3-implementation-checklist) for step-by-step guidance

### For Architects

1. Study [System Architecture](https://deepwiki.com/e7canasta/cupertino-nvr/2.1-system-architecture) for high-level design
2. Review [Design Philosophy](https://deepwiki.com/e7canasta/cupertino-nvr/2.2-design-philosophy) for architectural principles
3. Examine [Scaling and Performance](https://deepwiki.com/e7canasta/cupertino-nvr/6.3-scaling-and-performance) for production considerations

### For Operators

1. Review [Single-Site Deployment](https://deepwiki.com/e7canasta/cupertino-nvr/6.1-single-site-deployment) for basic setup
2. Study [Multi-Site Deployment](https://deepwiki.com/e7canasta/cupertino-nvr/6.2-multi-site-deployment) for distributed scenarios
3. Check [Troubleshooting](https://deepwiki.com/e7canasta/cupertino-nvr/8.2-troubleshooting) for common issues

Sources: docs/nvr/NVR_INDEX.md:233-281