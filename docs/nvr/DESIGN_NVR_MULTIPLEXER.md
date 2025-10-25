# NVR Multiplexer Architecture Design
**Distributed Video Processing & Visualization System**

> *"El diablo sabe por diablo, no por viejo"* - Diseño pragmático para NVR de IA
>
> **Versión:** 1.0  
> **Fecha:** 2025-10-25  
> **Autores:** Visiona Team  

---

## 🎯 Executive Summary

Diseño de sistema NVR (Network Video Recorder) moderno con IA que **separa procesamiento de visualización** mediante arquitectura distribuida basada en MQTT pub/sub.

### Problema a Resolver

**Actualmente** (`multiplexer_demo.py` y `multiplexer_pipeline_clean.py`):
- Procesamiento e inference acoplados a visualización
- No se puede escalar horizontalmente (1 proceso = N streams + GUI)
- Overhead de rendering (10-15% CPU) aunque no se necesite visualización
- Imposible tener múltiples viewers de mismos streams
- Difícil debugging (todo en un solo proceso)

**Solución propuesta**:
```
┌─────────────────────┐         MQTT          ┌─────────────────────┐
│  StreamProcessor    │ ───────────────────>  │   VideoWall         │
│  (Headless)         │  Detection Events     │   (Viewer)          │
│                     │                       │                     │
│  - RTSP decode      │                       │  - RTSP decode      │
│  - Inference        │                       │  - Event listening  │
│  - MQTT publish     │                       │  - Render boxes     │
└─────────────────────┘                       └─────────────────────┘
```

### Bounded Contexts (DDD)

| Context | Responsabilidad | Deployment |
|---------|----------------|------------|
| **StreamProcessor** | Inference + Event publishing | Headless server (CPU/GPU) |
| **VideoWall** | Visualization + Event consumption | Desktop/Browser |
| **EventBus** | Detection event routing (MQTT) | Broker (mosquitto) |

### Quick Win Strategy

✅ **Phase 1** (MVP - Este diseño):
- StreamProcessor: Pipeline headless + MQTT sink
- VideoWall: Multiplexer viewer + MQTT listener
- Protocolo de eventos simple (JSON)

🔄 **Phase 2** (Futuro):
- Event store (time series DB)
- Web UI viewer (WebRTC)
- Multi-tenant support

---

## 📐 Architecture Overview

### System Context

```
┌─────────────────────────────────────────────────────────────────────┐
│                          NVR IA System                               │
│                                                                      │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │   Camera 1   │    │   Camera 2   │    │   Camera N   │          │
│  │  (RTSP src)  │    │  (RTSP src)  │    │  (RTSP src)  │          │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘          │
│         │                   │                   │                   │
│         └───────────────────┴───────────────────┘                   │
│                             │                                        │
│                             ▼                                        │
│              ┌──────────────────────────────┐                        │
│              │   StreamProcessor (N=12)     │                        │
│              │   ┌──────────────────────┐   │                        │
│              │   │ InferencePipeline    │   │                        │
│              │   │  - VideoSource x12   │   │                        │
│              │   │  - YOLO Model        │   │                        │
│              │   │  - MQTT Sink         │   │                        │
│              │   └──────────┬───────────┘   │                        │
│              └──────────────┼───────────────┘                        │
│                             │                                        │
│                             ▼                                        │
│              ┌──────────────────────────────┐                        │
│              │   MQTT Broker                │                        │
│              │   Topic: nvr/detections/#    │                        │
│              └──────────────┬───────────────┘                        │
│                             │                                        │
│                   ┌─────────┴─────────┐                              │
│                   │                   │                              │
│                   ▼                   ▼                              │
│       ┌──────────────────┐  ┌──────────────────┐                    │
│       │  VideoWall       │  │  EventLogger     │                    │
│       │  (OpenCV GUI)    │  │  (Optional)      │                    │
│       │  - Render 4x3    │  │  - Store events  │                    │
│       │  - Draw boxes    │  │  - Analytics     │                    │
│       └──────────────────┘  └──────────────────┘                    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Component Boundaries

```python
# Bounded Context 1: Stream Processing (inference/core/interfaces/nvr/processor/)
├── processor.py         # Main headless pipeline
├── mqtt_sink.py         # Detection event publisher
└── config.py            # Processor configuration

# Bounded Context 2: Visualization (inference/core/interfaces/nvr/wall/)
├── wall.py              # Video wall viewer
├── mqtt_listener.py     # Event subscriber
├── renderer.py          # Detection overlay renderer
└── config.py            # Wall configuration

# Bounded Context 3: Event Protocol (inference/core/interfaces/nvr/events/)
├── schema.py            # Detection event schema (Pydantic)
└── protocol.py          # MQTT topic structure
```

---

## 🏗️ Component Design

### 1. StreamProcessor (Headless Inference Pipeline)

**Responsabilidad**: Procesar streams RTSP y publicar detecciones vía MQTT

#### Architecture

```python
┌─────────────────────────────────────────────────────────────────┐
│ StreamProcessor                                                 │
│                                                                 │
│  ┌────────────────────────────────────────────────────────┐    │
│  │ InferencePipeline                                       │    │
│  │  video_reference = [stream_1, ..., stream_N]           │    │
│  │  model_id = "yolov8x-640"                              │    │
│  │  on_prediction = mqtt_detection_sink                   │    │
│  └─────────────────────┬──────────────────────────────────┘    │
│                        │                                        │
│                        ▼                                        │
│  ┌────────────────────────────────────────────────────────┐    │
│  │ MQTTDetectionSink                                       │    │
│  │                                                         │    │
│  │  def on_prediction(predictions, video_frames):         │    │
│  │      for pred, frame in zip(predictions, video_frames):│    │
│  │          event = DetectionEvent(                       │    │
│  │              source_id=frame.source_id,                │    │
│  │              timestamp=frame.frame_timestamp,          │    │
│  │              detections=pred['predictions'],           │    │
│  │          )                                              │    │
│  │          topic = f"nvr/detections/{frame.source_id}"   │    │
│  │          mqtt_client.publish(topic, event.json())      │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### Key Design Decisions

✅ **Usar InferencePipeline existente** (no reinventar la rueda)
- ✓ Multiplexing ya resuelto
- ✓ Reconnection logic incluida
- ✓ Watchdog y health monitoring
- ✓ Model loading optimizado

✅ **Sink es stateless** (KISS principle)
- ✓ No cache de eventos
- ✓ Fire-and-forget publishing (QoS 0 por defecto)
- ✓ Fácil testing (solo mock MQTT client)

✅ **MQTT over otros protocolos**
- ✓ Pub/sub nativo (múltiples consumers)
- ✓ Topic hierarchy (`nvr/detections/{source_id}`)
- ✓ Standard en IoT/Industrial
- ✓ Broker ligero (mosquitto ~5MB RAM)

❌ **No hacer**:
- ❌ No serializar frames en MQTT (demasiado pesado)
- ❌ No almacenar eventos en memoria (memory leak)
- ❌ No esperar ACK por cada publish (latency)

#### Configuration

```python
@dataclass
class StreamProcessorConfig:
    """Configuration for headless stream processor"""
    
    # Stream sources
    stream_uris: List[str]
    model_id: str = "yolov8x-640"
    
    # MQTT configuration
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic_prefix: str = "nvr/detections"
    mqtt_qos: int = 0  # Fire-and-forget
    mqtt_username: Optional[str] = None
    mqtt_password: Optional[str] = None
    
    # Pipeline configuration
    max_fps: Optional[float] = None
    confidence_threshold: float = 0.5
    
    # Watchdog
    enable_watchdog: bool = True
```

#### Usage

```python
from inference.core.interfaces.nvr.processor import StreamProcessor

# Configure
config = StreamProcessorConfig(
    stream_uris=[f"rtsp://localhost:8554/live/{i}.stream" for i in range(12)],
    model_id="yolov8x-640",
    mqtt_host="localhost",
    mqtt_port=1883,
)

# Run
processor = StreamProcessor(config)
processor.start()
processor.join()  # Blocks until stopped
```

---

### 2. VideoWall (Event-Driven Viewer)

**Responsabilidad**: Mostrar streams RTSP + overlay de detecciones recibidas vía MQTT

#### Architecture

```python
┌─────────────────────────────────────────────────────────────────┐
│ VideoWall                                                       │
│                                                                 │
│  ┌────────────────────────────────────────────────────────┐    │
│  │ VideoSource Multiplexer (No Inference)                 │    │
│  │  cameras = [VideoSource(uri) for uri in stream_uris]   │    │
│  │  frames = multiplex_videos(cameras)                    │    │
│  └─────────────────────┬──────────────────────────────────┘    │
│                        │                                        │
│                        ▼                                        │
│  ┌────────────────────────────────────────────────────────┐    │
│  │ DetectionCache (Thread-Safe)                           │    │
│  │                                                         │    │
│  │  cache: Dict[int, DetectionEvent] = {}                 │    │
│  │                                                         │    │
│  │  def update(source_id, event):                         │    │
│  │      with lock:                                        │    │
│  │          cache[source_id] = event                      │    │
│  │                                                         │    │
│  │  def get(source_id) -> Optional[DetectionEvent]:       │    │
│  │      with lock:                                        │    │
│  │          return cache.get(source_id)                   │    │
│  └────────────────────┬───────────────────────────────────┘    │
│                       │                                         │
│                       │  ┌──────────────────────────────┐      │
│                       │  │ MQTT Listener (Thread)       │      │
│                       │  │                               │      │
│                       │◄─┤ def on_message(topic, payload):│    │
│                       │  │   event = parse(payload)      │      │
│                       │  │   cache.update(event)         │      │
│                       │  └──────────────────────────────┘      │
│                       │                                         │
│                       ▼                                         │
│  ┌────────────────────────────────────────────────────────┐    │
│  │ Renderer                                                │    │
│  │                                                         │    │
│  │  for frames in multiplexer:                            │    │
│  │      for frame in frames:                              │    │
│  │          event = cache.get(frame.source_id)            │    │
│  │          if event and not expired(event):              │    │
│  │              frame = draw_boxes(frame, event)          │    │
│  │          tiles.append(frame)                           │    │
│  │      display(tiles)                                    │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### Key Design Decisions

✅ **VideoWall NO hace inference** (separación de concerns)
- ✓ Solo consume eventos MQTT
- ✓ Más ligero (no carga modelo)
- ✓ Múltiples walls pueden ver mismo processor

✅ **DetectionCache con TTL** (pragmatismo)
- ✓ Última detección por stream (Dict[source_id, event])
- ✓ TTL de 1 segundo (evita overlay de detecciones antiguas)
- ✓ Thread-safe (lock para updates desde MQTT thread)

✅ **Reutilizar multiplex_videos** (no reinventar)
- ✓ Ya existe en `inference.core.interfaces.camera.utils`
- ✓ Maneja reconnection, frame sync, etc.

✅ **Reutilizar render_boxes** (o adaptarlo)
- ✓ Ya dibuja bounding boxes con supervision
- ✓ Modificar para NO esperar predictions inline
- ✓ Leer de cache en vez de recibir directo

#### Configuration

```python
@dataclass
class VideoWallConfig:
    """Configuration for video wall viewer"""
    
    # Stream sources (same URIs as processor)
    stream_uris: List[str]
    
    # MQTT configuration
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic_pattern: str = "nvr/detections/#"  # Subscribe to all
    mqtt_username: Optional[str] = None
    mqtt_password: Optional[str] = None
    
    # Display configuration
    tile_size: Tuple[int, int] = (480, 360)
    grid_columns: int = 4
    display_fps: bool = True
    display_latency: bool = True
    
    # Detection overlay
    detection_ttl_seconds: float = 1.0  # Expire old detections
    box_thickness: int = 2
    label_font_scale: float = 0.6
```

#### Usage

```python
from inference.core.interfaces.nvr.wall import VideoWall

# Configure
config = VideoWallConfig(
    stream_uris=[f"rtsp://localhost:8554/live/{i}.stream" for i in range(12)],
    mqtt_host="localhost",
    mqtt_port=1883,
    tile_size=(480, 360),
)

# Run
wall = VideoWall(config)
wall.start()  # Blocks, shows OpenCV window
```

---

### 3. Event Protocol (MQTT Messages)

**Responsabilidad**: Schema y serialización de eventos de detección

#### DetectionEvent Schema

```python
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class BoundingBox(BaseModel):
    """Bounding box coordinates (normalized or absolute)"""
    x: float = Field(description="Top-left X coordinate")
    y: float = Field(description="Top-left Y coordinate")
    width: float = Field(description="Box width")
    height: float = Field(description="Box height")

class Detection(BaseModel):
    """Single object detection"""
    class_name: str = Field(description="Detected class")
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
    inference_time_ms: float = Field(description="Inference duration in ms")
    detections: List[Detection] = Field(description="List of detections")
    
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
                        "tracker_id": 42
                    }
                ],
                "fps": 25.3,
                "latency_ms": 120.5
            }
        }
```

#### MQTT Topic Structure

```
nvr/
├── detections/
│   ├── 0              # Stream 0 detections
│   ├── 1              # Stream 1 detections
│   ├── ...
│   └── N              # Stream N detections
│
├── stats/
│   ├── processor      # Processor health/stats
│   └── wall           # Wall viewer stats
│
└── control/
    ├── processor      # Control commands (pause, resume, etc.)
    └── wall           # Wall commands (mute stream, etc.)
```

**Topic naming convention**:
- `nvr/detections/{source_id}` - Detection events (retained=False, QoS=0)
- `nvr/stats/processor` - Processor stats (retained=True, QoS=0)
- `nvr/control/#` - Control plane (retained=False, QoS=1)

**Rationale**:
- ✓ Hierarchical topics enable selective subscription
- ✓ Wall puede subscribirse solo a streams de interés
- ✓ EventLogger puede subscribirse a `nvr/detections/#` (wildcard)
- ✓ Control plane separado del data plane

---

## 📦 Package Structure

### Independent Package (Recommended ✅)

```
cupertino/nvr/
├── __init__.py               # Package exports
├── README.md                 # Package documentation
├── Makefile                  # Development tasks
├── pyproject.toml            # Package configuration
│
├── processor/
│   ├── __init__.py
│   ├── processor.py          # StreamProcessor main class
│   ├── mqtt_sink.py          # MQTTDetectionSink
│   └── config.py             # StreamProcessorConfig
│
├── wall/
│   ├── __init__.py
│   ├── wall.py               # VideoWall main class
│   ├── mqtt_listener.py      # MQTT subscriber thread
│   ├── detection_cache.py    # Thread-safe cache with TTL
│   ├── renderer.py           # Detection overlay renderer
│   └── config.py             # VideoWallConfig
│
├── events/
│   ├── __init__.py
│   ├── schema.py             # Pydantic event schemas
│   └── protocol.py           # MQTT topic utilities
│
├── cli.py                    # CLI entry point
│
└── tests/
    ├── unit/                 # Unit tests
    │   ├── test_events.py
    │   ├── test_mqtt_sink.py
    │   └── test_cache.py
    └── integration/          # Integration tests
        └── test_e2e.py
```

**Rationale**:
- ✅ **Independent lifecycle** - Own versioning and releases
- ✅ **Clear ownership** - Cupertino namespace (Visiona project)
- ✅ **Flexible deployment** - Can be packaged separately
- ✅ **Own build system** - Makefile for development tasks
- ✅ **Easy integration** - `pip install cupertino-nvr`
- ✅ **Not tied to Inference** - Uses it as dependency, not part of it

**Installation**:
```bash
# Development mode
cd cupertino/nvr
make install-dev

# Or directly
pip install -e .

# Production
pip install cupertino-nvr
```

**CLI Usage**:
```bash
# Using installed package
cupertino-nvr processor --n 12
cupertino-nvr wall --n 12

# Using Makefile (development)
make run-processor N=12
make run-wall N=12
```

---

## 🔧 Implementation Plan

### Phase 1: MVP (Este Sprint)

#### 1.1 Event Protocol
```bash
inference/core/interfaces/nvr/events/
├── schema.py         # DetectionEvent, BoundingBox, Detection (Pydantic)
└── protocol.py       # topic_for_source(id), parse_topic(), etc.
```

**Validation**: Unit tests con pytest
```python
def test_detection_event_serialization():
    event = DetectionEvent(...)
    json_str = event.model_dump_json()
    parsed = DetectionEvent.model_validate_json(json_str)
    assert parsed == event
```

#### 1.2 StreamProcessor
```bash
inference/core/interfaces/nvr/processor/
├── config.py         # StreamProcessorConfig
├── mqtt_sink.py      # MQTTDetectionSink (sink function)
└── processor.py      # StreamProcessor (wrapper around InferencePipeline)
```

**Dependencies**:
- `InferencePipeline` (already exists)
- `paho-mqtt` (already used in enterprise MQTT sink)

**Key code**:
```python
# mqtt_sink.py
class MQTTDetectionSink:
    def __init__(self, mqtt_client, topic_prefix: str, model_id: str):
        self.client = mqtt_client
        self.topic_prefix = topic_prefix
        self.model_id = model_id
    
    def __call__(
        self,
        predictions: Union[dict, List[Optional[dict]]],
        video_frame: Union[VideoFrame, List[Optional[VideoFrame]]],
    ) -> None:
        """Sink compatible with InferencePipeline signature"""
        predictions = wrap_in_list(predictions)
        video_frame = wrap_in_list(video_frame)
        
        for pred, frame in zip(predictions, video_frame):
            if frame is None or pred is None:
                continue
            
            event = self._create_event(pred, frame)
            topic = f"{self.topic_prefix}/{frame.source_id}"
            self.client.publish(topic, event.model_dump_json(), qos=0)
    
    def _create_event(self, prediction: dict, frame: VideoFrame) -> DetectionEvent:
        """Convert Roboflow prediction to DetectionEvent"""
        detections = []
        for p in prediction.get("predictions", []):
            detections.append(Detection(
                class_name=p["class"],
                confidence=p["confidence"],
                bbox=BoundingBox(
                    x=p["x"],
                    y=p["y"],
                    width=p["width"],
                    height=p["height"],
                ),
                tracker_id=p.get("tracker_id"),
            ))
        
        return DetectionEvent(
            source_id=frame.source_id,
            frame_id=frame.frame_id,
            timestamp=frame.frame_timestamp,
            model_id=self.model_id,
            inference_time_ms=prediction.get("time", 0) * 1000,
            detections=detections,
        )
```

**Testing**:
```python
# Mock MQTT client
class MockMQTTClient:
    def __init__(self):
        self.published = []
    
    def publish(self, topic, payload, qos):
        self.published.append((topic, payload, qos))

def test_mqtt_sink_publishes_events():
    client = MockMQTTClient()
    sink = MQTTDetectionSink(client, "nvr/detections", "yolov8x-640")
    
    # Create mock prediction and frame
    prediction = {"predictions": [...]}
    frame = VideoFrame(...)
    
    sink(prediction, frame)
    
    assert len(client.published) == 1
    topic, payload, qos = client.published[0]
    assert topic == "nvr/detections/0"
    event = DetectionEvent.model_validate_json(payload)
    assert event.source_id == 0
```

#### 1.3 VideoWall
```bash
inference/core/interfaces/nvr/wall/
├── config.py             # VideoWallConfig
├── detection_cache.py    # DetectionCache (thread-safe dict with TTL)
├── mqtt_listener.py      # MQTTListener (subscriber thread)
├── renderer.py           # render_detections_from_cache()
└── wall.py               # VideoWall main class
```

**Key code**:
```python
# detection_cache.py
from threading import Lock
from typing import Dict, Optional
from datetime import datetime, timedelta

class DetectionCache:
    """Thread-safe cache for detection events with TTL"""
    
    def __init__(self, ttl_seconds: float = 1.0):
        self._cache: Dict[int, tuple[DetectionEvent, datetime]] = {}
        self._lock = Lock()
        self._ttl = timedelta(seconds=ttl_seconds)
    
    def update(self, event: DetectionEvent) -> None:
        with self._lock:
            self._cache[event.source_id] = (event, datetime.now())
    
    def get(self, source_id: int) -> Optional[DetectionEvent]:
        with self._lock:
            if source_id not in self._cache:
                return None
            event, timestamp = self._cache[source_id]
            if datetime.now() - timestamp > self._ttl:
                del self._cache[source_id]  # Expired
                return None
            return event
```

```python
# mqtt_listener.py
from threading import Thread
import paho.mqtt.client as mqtt

class MQTTListener(Thread):
    """Background thread for MQTT subscription"""
    
    def __init__(self, config: VideoWallConfig, cache: DetectionCache):
        super().__init__(daemon=True)
        self.config = config
        self.cache = cache
        self.client = mqtt.Client()
        self.client.on_message = self._on_message
    
    def run(self):
        if self.config.mqtt_username:
            self.client.username_pw_set(
                self.config.mqtt_username,
                self.config.mqtt_password
            )
        self.client.connect(self.config.mqtt_host, self.config.mqtt_port)
        self.client.subscribe(self.config.mqtt_topic_pattern)
        self.client.loop_forever()
    
    def _on_message(self, client, userdata, msg):
        try:
            event = DetectionEvent.model_validate_json(msg.payload)
            self.cache.update(event)
        except Exception as e:
            logger.error(f"Failed to parse detection event: {e}")
```

```python
# wall.py
class VideoWall:
    def __init__(self, config: VideoWallConfig):
        self.config = config
        self.cache = DetectionCache(ttl_seconds=config.detection_ttl_seconds)
        self.mqtt_listener = MQTTListener(config, self.cache)
    
    def start(self):
        # Start MQTT listener
        self.mqtt_listener.start()
        
        # Initialize video sources
        cameras = [
            VideoSource.init(uri, source_id=i)
            for i, uri in enumerate(self.config.stream_uris)
        ]
        
        for camera in cameras:
            camera.start()
        
        # Multiplex and render
        multiplexer = multiplex_videos(
            videos=cameras,
            should_stop=lambda: STOP,
        )
        
        for frames in multiplexer:
            self._render_frame_batch(frames)
    
    def _render_frame_batch(self, frames: List[VideoFrame]):
        images = []
        for frame in frames:
            # Get cached detections for this source
            event = self.cache.get(frame.source_id)
            
            # Render frame with detections overlay
            image = self._render_frame_with_detections(frame, event)
            images.append(image)
        
        # Create grid and display
        tiles = create_tiles(images, self.config.grid_columns)
        cv2.imshow("NVR Video Wall", tiles)
        cv2.waitKey(1)
    
    def _render_frame_with_detections(
        self,
        frame: VideoFrame,
        event: Optional[DetectionEvent]
    ) -> np.ndarray:
        """Render frame with detection overlay"""
        image = frame.image.copy()
        
        if event is None:
            return letterbox_image(image, self.config.tile_size)
        
        # Convert detections to supervision format
        detections = self._event_to_sv_detections(event)
        
        # Annotate (reuse supervision annotators)
        image = sv.BoxAnnotator().annotate(image, detections)
        labels = [d.class_name for d in event.detections]
        image = sv.LabelAnnotator().annotate(image, detections, labels)
        
        # Add statistics overlay
        if self.config.display_latency:
            latency_ms = (datetime.now() - event.timestamp).total_seconds() * 1000
            cv2.putText(image, f"Latency: {latency_ms:.0f}ms", ...)
        
        return letterbox_image(image, self.config.tile_size)
```

#### 1.4 CLI Integration
```bash
inference_cli/nvr.py      # New CLI module
```

```python
# inference_cli/nvr.py
import click
from inference.core.interfaces.nvr.processor import StreamProcessor, StreamProcessorConfig
from inference.core.interfaces.nvr.wall import VideoWall, VideoWallConfig

@click.group()
def nvr():
    """Network Video Recorder commands"""
    pass

@nvr.command()
@click.option("--n", type=int, default=6, help="Number of streams")
@click.option("--model", default="yolov8x-640", help="Model ID")
@click.option("--mqtt-host", default="localhost", help="MQTT broker host")
@click.option("--mqtt-port", type=int, default=1883, help="MQTT broker port")
@click.option("--stream-server", default="rtsp://localhost:8554", help="RTSP server URL")
def processor(n, model, mqtt_host, mqtt_port, stream_server):
    """Run headless stream processor"""
    config = StreamProcessorConfig(
        stream_uris=[f"{stream_server}/live/{i}.stream" for i in range(n)],
        model_id=model,
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
    )
    proc = StreamProcessor(config)
    proc.start()
    proc.join()

@nvr.command()
@click.option("--n", type=int, default=6, help="Number of streams")
@click.option("--mqtt-host", default="localhost", help="MQTT broker host")
@click.option("--mqtt-port", type=int, default=1883, help="MQTT broker port")
@click.option("--stream-server", default="rtsp://localhost:8554", help="RTSP server URL")
def wall(n, mqtt_host, mqtt_port, stream_server):
    """Run video wall viewer"""
    config = VideoWallConfig(
        stream_uris=[f"{stream_server}/live/{i}.stream" for i in range(n)],
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
    )
    wall_app = VideoWall(config)
    wall_app.start()
```

**Usage**:
```bash
# Terminal 1: Start processor
inference nvr processor --n 12 --model yolov8x-640

# Terminal 2: Start wall
inference nvr wall --n 12

# Terminal 3: Monitor MQTT (debug)
mosquitto_sub -t "nvr/detections/#" -v
```

---

### Phase 2: Enhancements (Futuro)

#### 2.1 Event Store (Time Series)
- PostgreSQL + TimescaleDB para eventos históricos
- Query API: "Dame detecciones de stream 5 entre 10:00-11:00"
- Analytics: heatmaps, dwell time, traffic flow

#### 2.2 Web UI Viewer
- React + WebRTC para streaming
- Multiple layouts (1x1, 2x2, 4x3, custom)
- PTZ controls (si cámaras lo soportan)

#### 2.3 Multi-Tenant
- MQTT topic: `nvr/{tenant_id}/detections/{source_id}`
- Auth & isolation por tenant
- Quota enforcement

#### 2.4 Advanced Features
- **Person re-identification**: Track across cameras
- **Alert rules**: MQTT publish to `nvr/alerts/{rule_id}`
- **Recording on demand**: Save clips when detections occur
- **Thermal overlays**: Integration with thermal cameras

---

## 🎸 Design Principles (Manifesto Compliance)

### ✅ Bounded Contexts Claros
- **Processor**: Inference domain (model, predictions)
- **Wall**: Visualization domain (rendering, UI)
- **EventBus**: Integration domain (MQTT protocol)

### ✅ Pragmatismo > Purismo
- Reutilizamos `InferencePipeline` (no reimplementamos)
- Usamos `supervision` para rendering (no custom annotators)
- MQTT sin garantías (QoS=0) es suficiente para video en tiempo real

### ✅ KISS ≠ Simplicidad Ingenua
- DetectionCache tiene TTL (previene memory leaks)
- MQTT listener en thread separado (no bloquea rendering)
- Versioning de eventos (permite evolución del protocolo)

### ✅ Diseño Evolutivo
- Phase 1 (MVP): Funcional con OpenCV
- Phase 2: Web UI, analytics, multi-tenant
- Extensible sin breaking changes (versioned events)

### ✅ Testing como Feedback
- Unit tests con mocks (MQTT client, VideoFrame)
- Integration tests con mosquitto local
- Property tests para event serialization

---

## 📊 Trade-offs Evaluation

### Pros ✅

| Aspecto | Beneficio |
|---------|-----------|
| **Escalabilidad** | N processors + M walls independientes |
| **Performance** | Wall sin inference = 50% menos CPU |
| **Debugging** | Logs separados, fácil troubleshooting |
| **Flexibility** | Wall puede consumir eventos de múltiples processors |
| **Extensibility** | Fácil agregar event consumers (logger, analytics) |

### Cons ❌

| Aspecto | Costo |
|---------|-------|
| **Latency** | +50-100ms por hop MQTT (processor → broker → wall) |
| **Complexity** | +1 dependency (MQTT broker) |
| **Sync issues** | Wall puede perder eventos si MQTT falla |
| **Bandwidth** | MQTT traffic proporcional a detecciones/sec |

### Mitigations 🛡️

| Problema | Solución |
|----------|----------|
| **MQTT latency** | QoS=0 (fire-and-forget), broker local |
| **Event loss** | Acceptable para real-time video (TTL=1s en wall) |
| **Broker SPOF** | Monitor con watchdog, auto-restart |
| **Bandwidth** | Comprimir payloads (JSON → MessagePack opcional) |

---

## 🚀 Success Metrics

### MVP Definition of Done

✅ **Functional**:
- [ ] Processor procesa 12 streams @ 25 FPS sin drops
- [ ] Wall muestra 12 streams con detections overlay
- [ ] End-to-end latency < 200ms (frame capture → display)
- [ ] No memory leaks en runs de 1 hora

✅ **Quality**:
- [ ] Test coverage > 80% (events, cache, sink)
- [ ] Integration test con mosquitto + go2rtc
- [ ] CLI funcional (`inference nvr processor/wall`)
- [ ] Documentación en README con ejemplos

✅ **Performance**:
- [ ] Processor CPU < 60% en 12 streams (mini PC i5)
- [ ] Wall CPU < 20% (sin inference)
- [ ] MQTT broker RAM < 50MB

---

## 📚 References

### Existing Code
- `inference/core/interfaces/stream/sinks.py` - render_boxes, UDPSink
- `inference/core/interfaces/stream/inference_pipeline.py` - InferencePipeline
- `inference/core/interfaces/camera/utils.py` - multiplex_videos
- `inference/enterprise/workflows/enterprise_blocks/sinks/mqtt_writer/v1.py` - MQTT patterns
- `development/stream_interface/multiplexer_demo.py` - Multiplexer sin inference
- `development/stream_interface/multiplexer_pipeline_clean.py` - Multiplexer con inference

### External
- [paho-mqtt](https://github.com/eclipse/paho.mqtt.python) - MQTT client library
- [mosquitto](https://mosquitto.org/) - MQTT broker (5MB Docker image)
- [supervision](https://github.com/roboflow/supervision) - Annotation utilities
- [go2rtc](https://github.com/AlexxIT/go2rtc) - RTSP server for testing

---

## 🎯 Next Steps

1. **Review & Feedback** (Ernesto + Visiona Team)
   - ¿Bounded contexts correctos?
   - ¿Package structure apropiada (core vs enterprise)?
   - ¿Algún concern de seguridad/performance?

2. **Spike: MQTT Latency** (1 día)
   - Medir latency real con mosquitto local
   - Validar que QoS=0 es suficiente
   - Test con 12 streams @ 25 FPS

3. **Implementation: Phase 1** (1 semana)
   - Día 1-2: Events + MQTTDetectionSink
   - Día 3-4: StreamProcessor + tests
   - Día 5-6: VideoWall + DetectionCache
   - Día 7: Integration test + CLI

4. **Documentation** (paralelo)
   - README en `inference/core/interfaces/nvr/`
   - Actualizar wiki con arquitectura
   - Tutorial en `docs/` con go2rtc setup

---

## 📝 Open Questions

1. **¿Ubicación del package?**
   - **Opción A**: `inference/core/interfaces/nvr/` (recomendada)
   - **Opción B**: `inference/enterprise/nvr/` (si es enterprise-only)

2. **¿Event versioning strategy?**
   - **Opción A**: Topic suffix (`nvr/detections/v1/{source_id}`)
   - **Opción B**: Payload field (`event.version = "1.0"`)

3. **¿Wall necesita inference capability?**
   - **Ahora**: No (solo consume eventos)
   - **Futuro**: ¿Hybrid mode? (inference local + eventos remotos)

4. **¿Control plane scope?**
   - **MVP**: Sin control plane (solo data)
   - **Phase 2**: Control topics para pause/resume/restart

5. **¿Integration con stream_management existente?**
   - `inference/enterprise/stream_management/` ya existe
   - ¿NVR debería usar ese o ser independiente?

---

**🎸 "El diablo sabe por diablo, no por viejo"**

Este diseño prioriza **aprendizaje rápido** (MVP funcional en 1 semana) sobre **diseño especulativo** (arquitectura perfecta que nunca se usa). Vamos a tocar buen blues con este código. 🚀

**Versión:** 1.0  
**Estado:** 🟡 Awaiting Review  
**Próximo paso:** Feedback + Spike MQTT latency

---

**Para futuros Claudes:**
Este diseño sigue el MANIFESTO - pragmático, evolutivo, con bounded contexts claros. Si vas a implementar Phase 2, lee primero este doc y el MANIFESTO. No sobre-diseñes, itera basado en feedback real del MVP.

¡Buen código, compañeros! 🚀

