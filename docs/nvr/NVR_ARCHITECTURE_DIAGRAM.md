# NVR Multiplexer - Architecture Quick Reference

> **Visual companion to DESIGN_NVR_MULTIPLEXER.md**

---

## 🏗️ System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│                          🎥 RTSP Stream Sources                             │
│                     (go2rtc: 12 streams @ 1280x720)                         │
│                                                                             │
└────────────────┬────────────────────────────────────────┬───────────────────┘
                 │                                        │
                 │                                        │
                 ▼                                        ▼
┌──────────────────────────────────┐      ┌──────────────────────────────────┐
│   📊 StreamProcessor             │      │   🖥️  VideoWall                  │
│   (Headless Inference)           │      │   (Event-Driven Viewer)          │
│                                  │      │                                  │
│  ┌────────────────────────────┐  │      │  ┌────────────────────────────┐  │
│  │ InferencePipeline          │  │      │  │ multiplex_videos()         │  │
│  │  • VideoSource x12         │  │      │  │  • VideoSource x12         │  │
│  │  • YOLOv8x Model           │  │      │  │  • No Inference            │  │
│  │  • Batch processing        │  │      │  │  • Frame sync              │  │
│  └──────────┬─────────────────┘  │      │  └──────────┬─────────────────┘  │
│             │                     │      │             │                     │
│             ▼                     │      │             ▼                     │
│  ┌────────────────────────────┐  │      │  ┌────────────────────────────┐  │
│  │ MQTTDetectionSink          │  │      │  │ DetectionCache (TTL=1s)    │  │
│  │  • Serialize predictions   │  │      │  │  • Thread-safe Dict        │  │
│  │  • Publish to MQTT         │  │      │  │  • {source_id: event}      │  │
│  │  • QoS=0 (fire & forget)   │  │      │  └────────────▲───────────────┘  │
│  └──────────┬─────────────────┘  │      │               │                   │
│             │                     │      │               │ update()          │
└─────────────┼─────────────────────┘      │  ┌────────────┴───────────────┐  │
              │                            │  │ MQTTListener (Thread)      │  │
              │                            │  │  • Subscribe to topics     │  │
              │                            │  │  • Parse DetectionEvent    │  │
              │                            │  │  • Update cache            │  │
              │                            │  └────────────────────────────┘  │
              │                            │               ▲                   │
              │                            │               │                   │
              │                            │  ┌────────────┴───────────────┐  │
              │                            │  │ Renderer                   │  │
              │                            │  │  • Draw boxes from cache   │  │
              │                            │  │  • Supervision annotators  │  │
              │                            │  │  • 4x3 grid display        │  │
              │                            │  └────────────────────────────┘  │
              │                            │                                  │
              │                            └──────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        🔌 MQTT Broker (mosquitto)                           │
│                                                                             │
│  Topics:                                                                    │
│    nvr/detections/0  ───────> Stream 0 detection events                    │
│    nvr/detections/1  ───────> Stream 1 detection events                    │
│    ...                                                                      │
│    nvr/detections/N  ───────> Stream N detection events                    │
│                                                                             │
│  Subscribers:                                                               │
│    • VideoWall (nvr/detections/#)                                          │
│    • EventLogger (nvr/detections/#) - Optional                             │
│    • Analytics Service (nvr/detections/#) - Future                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 📦 Bounded Contexts (DDD)

```
┌─────────────────────────────────────────────────────────────────┐
│                     Inference Domain                            │
│                                                                 │
│  inference/core/interfaces/nvr/processor/                       │
│                                                                 │
│  • StreamProcessor      - Pipeline wrapper                      │
│  • MQTTDetectionSink    - Event publisher                       │
│  • StreamProcessorConfig - Configuration                        │
│                                                                 │
│  Dependencies:                                                  │
│    → InferencePipeline (existing)                               │
│    → paho-mqtt (MQTT client)                                    │
│                                                                 │
│  Output: DetectionEvent → MQTT                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                  Visualization Domain                           │
│                                                                 │
│  inference/core/interfaces/nvr/wall/                            │
│                                                                 │
│  • VideoWall          - Main viewer                             │
│  • MQTTListener       - Event subscriber (thread)               │
│  • DetectionCache     - Thread-safe cache with TTL              │
│  • Renderer           - Detection overlay                       │
│  • VideoWallConfig    - Configuration                           │
│                                                                 │
│  Dependencies:                                                  │
│    → multiplex_videos (existing)                                │
│    → supervision (existing)                                     │
│    → paho-mqtt (MQTT client)                                    │
│                                                                 │
│  Input: MQTT → DetectionEvent                                   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                  Integration Domain                             │
│                                                                 │
│  inference/core/interfaces/nvr/events/                          │
│                                                                 │
│  • DetectionEvent     - Pydantic schema                         │
│  • Detection          - Single detection                        │
│  • BoundingBox        - Bbox coordinates                        │
│  • protocol.py        - MQTT topic utilities                    │
│                                                                 │
│  Protocol:                                                      │
│    Topic: nvr/detections/{source_id}                            │
│    Payload: DetectionEvent (JSON)                               │
│    QoS: 0 (fire-and-forget)                                     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔄 Data Flow

### Detection Event Publishing (StreamProcessor)

```
 VideoFrame
     │
     ▼
┌─────────────────┐
│ Inference       │
│ (YOLOv8x)       │
└────────┬────────┘
         │
         ▼
  Predictions (dict)
         │
         ▼
┌─────────────────────────────┐
│ MQTTDetectionSink           │
│                             │
│  1. Extract predictions     │
│  2. Create DetectionEvent   │
│  3. Serialize to JSON       │
│  4. Publish to topic        │
└────────┬────────────────────┘
         │
         ▼
  MQTT Topic: nvr/detections/{source_id}
  Payload: {
    "source_id": 0,
    "timestamp": "2025-10-25T10:30:00.123Z",
    "detections": [
      {
        "class_name": "person",
        "confidence": 0.92,
        "bbox": {"x": 100, "y": 150, ...}
      }
    ]
  }
```

### Detection Event Consumption (VideoWall)

```
MQTT Topic: nvr/detections/#
     │
     ▼
┌─────────────────────────────┐
│ MQTTListener (Thread)       │
│                             │
│  on_message(topic, payload) │
│    1. Parse JSON            │
│    2. Validate schema       │
│    3. Update cache          │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│ DetectionCache              │
│                             │
│  cache[source_id] = event   │
│  (TTL = 1 second)           │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│ Renderer (Main Thread)      │
│                             │
│  for frame in multiplexer:  │
│    event = cache.get(id)    │
│    if event:                │
│      draw_boxes(frame)      │
└────────┬────────────────────┘
         │
         ▼
    OpenCV Display
    (4x3 Grid Layout)
```

---

## 🎬 Usage Examples

### Terminal 1: Start MQTT Broker

```bash
# Option 1: Docker
docker run -p 1883:1883 -p 9001:9001 eclipse-mosquitto

# Option 2: Local install
mosquitto -c mosquitto.conf
```

### Terminal 2: Start StreamProcessor

```bash
# Using CLI
inference nvr processor \
  --n 12 \
  --model yolov8x-640 \
  --mqtt-host localhost \
  --mqtt-port 1883 \
  --stream-server rtsp://localhost:8554

# Or using Python
python -c "
from inference.core.interfaces.nvr.processor import StreamProcessor, StreamProcessorConfig

config = StreamProcessorConfig(
    stream_uris=['rtsp://localhost:8554/live/{}.stream'.format(i) for i in range(12)],
    model_id='yolov8x-640',
    mqtt_host='localhost',
    mqtt_port=1883,
)

processor = StreamProcessor(config)
processor.start()
processor.join()
"
```

### Terminal 3: Start VideoWall

```bash
# Using CLI
inference nvr wall \
  --n 12 \
  --mqtt-host localhost \
  --mqtt-port 1883 \
  --stream-server rtsp://localhost:8554

# Or using Python
python -c "
from inference.core.interfaces.nvr.wall import VideoWall, VideoWallConfig

config = VideoWallConfig(
    stream_uris=['rtsp://localhost:8554/live/{}.stream'.format(i) for i in range(12)],
    mqtt_host='localhost',
    mqtt_port=1883,
    tile_size=(480, 360),
)

wall = VideoWall(config)
wall.start()
"
```

### Terminal 4: Monitor MQTT (Debug)

```bash
# Subscribe to all detection events
mosquitto_sub -h localhost -t "nvr/detections/#" -v

# Example output:
# nvr/detections/0 {"source_id": 0, "timestamp": "...", "detections": [...]}
# nvr/detections/1 {"source_id": 1, "timestamp": "...", "detections": [...]}
```

---

## ⚡ Performance Characteristics

### CPU Usage (12 streams @ 1280x720, 25 FPS)

| Component | CPU % | Notes |
|-----------|-------|-------|
| **StreamProcessor** | 55-65% | Inference dominates (40-50%), decoding (10-15%) |
| **VideoWall** | 15-20% | Decoding only, no inference |
| **MQTT Broker** | <1% | Negligible overhead |
| **Total Saved** | ~40% | By separating inference from viz |

### Memory Usage

| Component | RAM | Notes |
|-----------|-----|-------|
| **StreamProcessor** | ~2.5 GB | Model weights (~800MB) + buffers |
| **VideoWall** | ~800 MB | Frame buffers only |
| **MQTT Broker** | ~50 MB | mosquitto (minimal) |

### Latency Budget

| Stage | Latency | Notes |
|-------|---------|-------|
| RTSP Decode | 30-50 ms | Network + codec |
| Inference | 40-60 ms | YOLOv8x on GPU |
| MQTT Publish | 2-5 ms | Local broker |
| MQTT Receive | 2-5 ms | Local broker |
| Render | 10-15 ms | supervision annotators |
| **Total E2E** | **~100-150 ms** | Frame capture → display |

---

## 📊 Scalability Matrix

### Horizontal Scaling

| Scenario | Architecture | Benefits |
|----------|--------------|----------|
| **1 Processor + 1 Wall** | MVP setup | Simple, single machine |
| **1 Processor + N Walls** | Multiple viewers | Same detections, different displays |
| **M Processors + 1 Wall** | Multi-site NVR | Wall aggregates from multiple locations |
| **M Processors + N Walls** | Enterprise NVR | Full flexibility, load distribution |

### Example: Multi-Site Deployment

```
Site A (Factory Floor)
  └─ StreamProcessor (12 cameras) ──┐
                                    │
Site B (Warehouse)                  │    ┌──> VideoWall (Security Office)
  └─ StreamProcessor (8 cameras) ───┼───>│
                                    │    └──> VideoWall (Manager Desktop)
Site C (Parking Lot)                │
  └─ StreamProcessor (6 cameras) ───┘    
                                         
           All via MQTT broker (cloud or edge)
```

---

## 🔐 Security Considerations

### MQTT Authentication

```python
# StreamProcessorConfig
config = StreamProcessorConfig(
    ...
    mqtt_username="nvr_processor",
    mqtt_password=os.getenv("MQTT_PASSWORD"),
)

# VideoWallConfig
config = VideoWallConfig(
    ...
    mqtt_username="nvr_viewer",
    mqtt_password=os.getenv("MQTT_PASSWORD"),
)
```

### MQTT TLS/SSL

```python
# In future implementation
mqtt_client.tls_set(
    ca_certs="/path/to/ca.crt",
    certfile="/path/to/client.crt",
    keyfile="/path/to/client.key",
)
```

### Topic-Based Access Control

```
# Broker ACL (mosquitto.conf)
user nvr_processor
  topic write nvr/detections/#

user nvr_viewer
  topic read nvr/detections/#
```

---

## 🧪 Testing Strategy

### Unit Tests

```python
# Test event serialization
def test_detection_event_roundtrip():
    event = DetectionEvent(...)
    json_str = event.model_dump_json()
    parsed = DetectionEvent.model_validate_json(json_str)
    assert parsed == event

# Test MQTT sink with mock
def test_mqtt_sink_publishes():
    mock_client = MockMQTTClient()
    sink = MQTTDetectionSink(mock_client, "nvr/detections", "yolov8x")
    sink(predictions, video_frame)
    assert len(mock_client.published) == 1

# Test cache TTL
def test_cache_expires_old_events():
    cache = DetectionCache(ttl_seconds=0.1)
    cache.update(event)
    time.sleep(0.2)
    assert cache.get(event.source_id) is None
```

### Integration Tests

```python
# Test full pipeline with real MQTT broker
def test_processor_to_wall_flow():
    # Setup
    broker = start_mosquitto()
    processor = StreamProcessor(config)
    wall = VideoWall(config)
    
    # Run
    processor.start()
    wall.start()
    
    # Verify
    time.sleep(5)
    assert wall.cache.get(0) is not None  # Received events
    
    # Cleanup
    processor.terminate()
    wall.stop()
    broker.stop()
```

---

## 🐛 Troubleshooting

### Issue: No detections in VideoWall

**Symptoms**: Wall shows streams but no bounding boxes

**Debug Steps**:
1. Check MQTT broker logs: `docker logs <mosquitto_container>`
2. Subscribe manually: `mosquitto_sub -t "nvr/detections/#" -v`
3. Check processor logs for MQTT connection errors
4. Verify topic names match (processor publish = wall subscribe)

### Issue: High latency (>500ms)

**Symptoms**: Detections appear delayed on wall

**Debug Steps**:
1. Check network latency: `ping <mqtt_broker_host>`
2. Verify MQTT broker is local (not remote)
3. Check processor FPS (should be ~25 FPS)
4. Profile wall rendering (disable annotations to isolate)

### Issue: Memory leak in VideoWall

**Symptoms**: RAM usage grows over time

**Debug Steps**:
1. Check cache size: `print(len(wall.cache._cache))`
2. Verify TTL is working (expired events deleted)
3. Check MQTT listener thread (should not accumulate messages)
4. Profile with `memory_profiler` or `tracemalloc`

---

## 📚 Related Documentation

- **[DESIGN_NVR_MULTIPLEXER.md](./DESIGN_NVR_MULTIPLEXER.md)** - Full architecture design doc
- **[MANIFESTO_DISENO.md](./MANIFESTO_DISENO%20-%20Blues%20Style.md)** - Design philosophy
- **[multiplexer_demo.py](../development/stream_interface/multiplexer_demo.py)** - Reference implementation (no inference)
- **[multiplexer_pipeline_clean.py](../development/stream_interface/multiplexer_pipeline_clean.py)** - Reference implementation (with inference)

---

**Status:** 🟡 Design Phase  
**Next:** Implementation Phase 1 (MVP)  
**ETA:** 1 week

🎸 *"Tocar con conocimiento de las reglas, no seguir la partitura al pie de la letra"*

