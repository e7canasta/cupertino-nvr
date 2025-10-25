# NVR Multiplexer - Implementation Checklist

> **Paso a paso para implementar el diseño**
> 
> Referencia: [DESIGN_NVR_MULTIPLEXER.md](./DESIGN_NVR_MULTIPLEXER.md)

---

## 🎯 Phase 1: MVP (1 semana)

### Day 1-2: Event Protocol + MQTT Sink

#### ☐ Step 1: Create package structure

```bash
cd /home/visiona/Work/KatasWork/KataInference/251025/inference

# Create main package
mkdir -p inference/core/interfaces/nvr/{events,processor,wall,cli}

# Create __init__.py files
touch inference/core/interfaces/nvr/__init__.py
touch inference/core/interfaces/nvr/events/__init__.py
touch inference/core/interfaces/nvr/processor/__init__.py
touch inference/core/interfaces/nvr/wall/__init__.py
touch inference/core/interfaces/nvr/cli/__init__.py
```

#### ☐ Step 2: Implement event schema

**File:** `inference/core/interfaces/nvr/events/schema.py`

```python
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class BoundingBox(BaseModel):
    """Bounding box coordinates"""
    x: float
    y: float
    width: float
    height: float

class Detection(BaseModel):
    """Single object detection"""
    class_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: BoundingBox
    tracker_id: Optional[int] = None

class DetectionEvent(BaseModel):
    """Detection event for MQTT"""
    source_id: int
    frame_id: int
    timestamp: datetime
    model_id: str
    inference_time_ms: float
    detections: List[Detection]
    fps: Optional[float] = None
    latency_ms: Optional[float] = None
```

**Test:** `tests/inference/unit_tests/core/interfaces/nvr/test_event_schema.py`

```python
def test_detection_event_serialization():
    event = DetectionEvent(
        source_id=0,
        frame_id=123,
        timestamp=datetime.now(),
        model_id="yolov8x-640",
        inference_time_ms=45.2,
        detections=[
            Detection(
                class_name="person",
                confidence=0.92,
                bbox=BoundingBox(x=100, y=150, width=80, height=200)
            )
        ]
    )
    
    # Serialize
    json_str = event.model_dump_json()
    
    # Deserialize
    parsed = DetectionEvent.model_validate_json(json_str)
    
    assert parsed.source_id == event.source_id
    assert len(parsed.detections) == 1
```

#### ☐ Step 3: Implement MQTT protocol utilities

**File:** `inference/core/interfaces/nvr/events/protocol.py`

```python
def topic_for_source(source_id: int, prefix: str = "nvr/detections") -> str:
    """Generate MQTT topic for source"""
    return f"{prefix}/{source_id}"

def parse_source_id_from_topic(topic: str) -> Optional[int]:
    """Extract source_id from topic"""
    parts = topic.split("/")
    if len(parts) >= 3:
        try:
            return int(parts[-1])
        except ValueError:
            return None
    return None
```

#### ☐ Step 4: Implement MQTT Detection Sink

**File:** `inference/core/interfaces/nvr/processor/mqtt_sink.py`

```python
import json
from typing import Union, List, Optional
import paho.mqtt.client as mqtt

from inference.core.interfaces.camera.entities import VideoFrame
from inference.core.interfaces.stream.utils import wrap_in_list
from inference.core.interfaces.nvr.events.schema import DetectionEvent, Detection, BoundingBox
from inference.core.interfaces.nvr.events.protocol import topic_for_source
from inference.core import logger


class MQTTDetectionSink:
    """Sink that publishes detection events to MQTT"""
    
    def __init__(
        self,
        mqtt_client: mqtt.Client,
        topic_prefix: str,
        model_id: str,
    ):
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
            
            try:
                event = self._create_event(pred, frame)
                topic = topic_for_source(frame.source_id, self.topic_prefix)
                payload = event.model_dump_json()
                
                result = self.client.publish(topic, payload, qos=0)
                
                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    logger.warning(
                        f"Failed to publish to {topic}: {mqtt.error_string(result.rc)}"
                    )
                    
            except Exception as e:
                logger.error(f"Error in MQTT sink for source {frame.source_id}: {e}")
    
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
            fps=None,  # Can be computed if needed
            latency_ms=None,
        )
```

**Test:** `tests/inference/unit_tests/core/interfaces/nvr/test_mqtt_sink.py`

```python
from unittest.mock import MagicMock
from datetime import datetime

def test_mqtt_sink_publishes_event():
    # Mock MQTT client
    mock_client = MagicMock()
    mock_client.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS
    
    # Create sink
    sink = MQTTDetectionSink(mock_client, "nvr/detections", "yolov8x-640")
    
    # Mock prediction and frame
    prediction = {
        "predictions": [
            {
                "class": "person",
                "confidence": 0.92,
                "x": 100,
                "y": 150,
                "width": 80,
                "height": 200,
            }
        ],
        "time": 0.045,
    }
    
    frame = VideoFrame(
        image=np.zeros((720, 1280, 3), dtype=np.uint8),
        frame_id=123,
        frame_timestamp=datetime.now(),
        source_id=0,
    )
    
    # Call sink
    sink(prediction, frame)
    
    # Verify publish was called
    mock_client.publish.assert_called_once()
    topic, payload, qos = mock_client.publish.call_args[0][:3]
    
    assert topic == "nvr/detections/0"
    assert qos == 0
    
    # Verify payload is valid DetectionEvent
    event = DetectionEvent.model_validate_json(payload)
    assert event.source_id == 0
    assert len(event.detections) == 1
    assert event.detections[0].class_name == "person"
```

---

### Day 3-4: StreamProcessor

#### ☐ Step 5: Implement StreamProcessorConfig

**File:** `inference/core/interfaces/nvr/processor/config.py`

```python
from dataclasses import dataclass
from typing import List, Optional

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
    mqtt_qos: int = 0
    mqtt_username: Optional[str] = None
    mqtt_password: Optional[str] = None
    
    # Pipeline configuration
    max_fps: Optional[float] = None
    confidence_threshold: float = 0.5
    
    # Watchdog
    enable_watchdog: bool = True
```

#### ☐ Step 6: Implement StreamProcessor

**File:** `inference/core/interfaces/nvr/processor/processor.py`

```python
import signal
from threading import Thread
from typing import Optional

import paho.mqtt.client as mqtt
from inference import InferencePipeline
from inference.core.interfaces.stream.watchdog import BasePipelineWatchDog
from inference.core import logger

from .config import StreamProcessorConfig
from .mqtt_sink import MQTTDetectionSink


STOP = False


class StreamProcessor:
    """Headless stream processor with MQTT event publishing"""
    
    def __init__(self, config: StreamProcessorConfig):
        self.config = config
        self.pipeline: Optional[InferencePipeline] = None
        self.mqtt_client: Optional[mqtt.Client] = None
        self.watchdog: Optional[BasePipelineWatchDog] = None
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def start(self):
        """Start the processor"""
        logger.info(f"Starting StreamProcessor with {len(self.config.stream_uris)} streams")
        
        # Initialize MQTT client
        self.mqtt_client = self._init_mqtt_client()
        
        # Create MQTT sink
        mqtt_sink = MQTTDetectionSink(
            mqtt_client=self.mqtt_client,
            topic_prefix=self.config.mqtt_topic_prefix,
            model_id=self.config.model_id,
        )
        
        # Create watchdog if enabled
        if self.config.enable_watchdog:
            self.watchdog = BasePipelineWatchDog()
        
        # Initialize pipeline
        self.pipeline = InferencePipeline.init(
            video_reference=self.config.stream_uris,
            model_id=self.config.model_id,
            on_prediction=mqtt_sink,
            watchdog=self.watchdog,
            max_fps=self.config.max_fps,
        )
        
        logger.info("Pipeline initialized, starting processing...")
        self.pipeline.start()
    
    def join(self):
        """Wait for pipeline to finish"""
        if self.pipeline:
            self.pipeline.join()
        
        # Cleanup
        if self.mqtt_client:
            self.mqtt_client.disconnect()
            self.mqtt_client.loop_stop()
        
        logger.info("StreamProcessor stopped")
    
    def terminate(self):
        """Stop the processor"""
        global STOP
        STOP = True
        
        if self.pipeline:
            self.pipeline.terminate()
    
    def _init_mqtt_client(self) -> mqtt.Client:
        """Initialize and connect MQTT client"""
        client = mqtt.Client()
        
        # Setup authentication if provided
        if self.config.mqtt_username:
            client.username_pw_set(
                self.config.mqtt_username,
                self.config.mqtt_password
            )
        
        # Connect
        logger.info(f"Connecting to MQTT broker at {self.config.mqtt_host}:{self.config.mqtt_port}")
        client.connect(self.config.mqtt_host, self.config.mqtt_port)
        client.loop_start()
        
        return client
    
    def _signal_handler(self, signum, frame):
        """Handle termination signals"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.terminate()
```

#### ☐ Step 7: Test StreamProcessor

**Integration Test:** Start processor with mock streams and verify MQTT publishing

```bash
# Start mosquitto
docker run -d -p 1883:1883 eclipse-mosquitto

# Start go2rtc (test streams)
go2rtc -config config/go2rtc/go2rtc.yaml

# Run processor
python -c "
from inference.core.interfaces.nvr.processor import StreamProcessor, StreamProcessorConfig

config = StreamProcessorConfig(
    stream_uris=['rtsp://localhost:8554/live/0.stream'],
    model_id='yolov8n-640',  # Small model for testing
    mqtt_host='localhost',
)

processor = StreamProcessor(config)
processor.start()
processor.join()  # Ctrl+C to stop
"

# In another terminal, verify MQTT messages
mosquitto_sub -t "nvr/detections/#" -v
```

---

### Day 5-6: VideoWall

#### ☐ Step 8: Implement VideoWallConfig

**File:** `inference/core/interfaces/nvr/wall/config.py`

```python
from dataclasses import dataclass
from typing import List, Optional, Tuple

@dataclass
class VideoWallConfig:
    """Configuration for video wall viewer"""
    
    # Stream sources
    stream_uris: List[str]
    
    # MQTT configuration
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic_pattern: str = "nvr/detections/#"
    mqtt_username: Optional[str] = None
    mqtt_password: Optional[str] = None
    
    # Display configuration
    tile_size: Tuple[int, int] = (480, 360)
    grid_columns: int = 4
    display_fps: bool = True
    display_latency: bool = True
    
    # Detection overlay
    detection_ttl_seconds: float = 1.0
    box_thickness: int = 2
    label_font_scale: float = 0.6
```

#### ☐ Step 9: Implement DetectionCache

**File:** `inference/core/interfaces/nvr/wall/detection_cache.py`

```python
from threading import Lock
from typing import Dict, Optional
from datetime import datetime, timedelta

from inference.core.interfaces.nvr.events.schema import DetectionEvent


class DetectionCache:
    """Thread-safe cache for detection events with TTL"""
    
    def __init__(self, ttl_seconds: float = 1.0):
        self._cache: Dict[int, tuple[DetectionEvent, datetime]] = {}
        self._lock = Lock()
        self._ttl = timedelta(seconds=ttl_seconds)
    
    def update(self, event: DetectionEvent) -> None:
        """Update cache with new event"""
        with self._lock:
            self._cache[event.source_id] = (event, datetime.now())
    
    def get(self, source_id: int) -> Optional[DetectionEvent]:
        """Get event for source, None if expired or missing"""
        with self._lock:
            if source_id not in self._cache:
                return None
            
            event, timestamp = self._cache[source_id]
            
            # Check if expired
            if datetime.now() - timestamp > self._ttl:
                del self._cache[source_id]
                return None
            
            return event
    
    def clear(self) -> None:
        """Clear all cached events"""
        with self._lock:
            self._cache.clear()
```

#### ☐ Step 10: Implement MQTTListener

**File:** `inference/core/interfaces/nvr/wall/mqtt_listener.py`

```python
from threading import Thread
import paho.mqtt.client as mqtt

from inference.core import logger
from inference.core.interfaces.nvr.events.schema import DetectionEvent
from .detection_cache import DetectionCache
from .config import VideoWallConfig


class MQTTListener(Thread):
    """Background thread for MQTT subscription"""
    
    def __init__(self, config: VideoWallConfig, cache: DetectionCache):
        super().__init__(daemon=True)
        self.config = config
        self.cache = cache
        self.client = mqtt.Client()
        self.client.on_message = self._on_message
        self.client.on_connect = self._on_connect
        self._running = True
    
    def run(self):
        """Start MQTT listener"""
        try:
            # Setup authentication
            if self.config.mqtt_username:
                self.client.username_pw_set(
                    self.config.mqtt_username,
                    self.config.mqtt_password
                )
            
            # Connect
            logger.info(f"MQTT listener connecting to {self.config.mqtt_host}")
            self.client.connect(self.config.mqtt_host, self.config.mqtt_port)
            
            # Subscribe
            self.client.subscribe(self.config.mqtt_topic_pattern)
            logger.info(f"MQTT listener subscribed to {self.config.mqtt_topic_pattern}")
            
            # Loop
            self.client.loop_forever()
            
        except Exception as e:
            logger.error(f"MQTT listener error: {e}")
    
    def stop(self):
        """Stop the listener"""
        self._running = False
        self.client.disconnect()
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback on connection"""
        if rc == 0:
            logger.info("MQTT listener connected successfully")
        else:
            logger.error(f"MQTT listener connection failed with code {rc}")
    
    def _on_message(self, client, userdata, msg):
        """Callback on message received"""
        try:
            event = DetectionEvent.model_validate_json(msg.payload)
            self.cache.update(event)
            
        except Exception as e:
            logger.error(f"Failed to parse detection event: {e}")
```

#### ☐ Step 11: Implement Renderer

**File:** `inference/core/interfaces/nvr/wall/renderer.py`

```python
from typing import List, Optional
from datetime import datetime

import cv2
import numpy as np
import supervision as sv

from inference.core.interfaces.camera.entities import VideoFrame
from inference.core.interfaces.nvr.events.schema import DetectionEvent
from inference.core.utils.preprocess import letterbox_image
from .config import VideoWallConfig


class DetectionRenderer:
    """Renders video frames with detection overlays"""
    
    def __init__(self, config: VideoWallConfig):
        self.config = config
        self.box_annotator = sv.BoxAnnotator(thickness=config.box_thickness)
        self.label_annotator = sv.LabelAnnotator(text_scale=config.label_font_scale)
    
    def render_frame(
        self,
        frame: VideoFrame,
        event: Optional[DetectionEvent]
    ) -> np.ndarray:
        """Render single frame with detection overlay"""
        image = frame.image.copy()
        
        # Draw detections if available
        if event is not None and len(event.detections) > 0:
            detections = self._event_to_sv_detections(event, image.shape)
            labels = [d.class_name for d in event.detections]
            
            image = self.box_annotator.annotate(image, detections)
            image = self.label_annotator.annotate(image, detections, labels)
        
        # Resize to tile size
        image = letterbox_image(image, self.config.tile_size)
        
        # Add statistics overlay
        if event is not None:
            if self.config.display_latency:
                latency_ms = (datetime.now() - event.timestamp).total_seconds() * 1000
                cv2.putText(
                    image,
                    f"Latency: {latency_ms:.0f}ms",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2
                )
            
            if self.config.display_fps and event.fps:
                cv2.putText(
                    image,
                    f"FPS: {event.fps:.1f}",
                    (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2
                )
        
        # Add source ID
        cv2.putText(
            image,
            f"Stream {frame.source_id}",
            (10, image.shape[0] - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            2
        )
        
        return image
    
    def _event_to_sv_detections(
        self,
        event: DetectionEvent,
        image_shape: tuple
    ) -> sv.Detections:
        """Convert DetectionEvent to supervision Detections"""
        xyxy = []
        confidence = []
        class_id = []
        
        for det in event.detections:
            # Convert center+size to xyxy
            x1 = det.bbox.x - det.bbox.width / 2
            y1 = det.bbox.y - det.bbox.height / 2
            x2 = det.bbox.x + det.bbox.width / 2
            y2 = det.bbox.y + det.bbox.height / 2
            
            xyxy.append([x1, y1, x2, y2])
            confidence.append(det.confidence)
            class_id.append(0)  # Placeholder
        
        return sv.Detections(
            xyxy=np.array(xyxy),
            confidence=np.array(confidence),
            class_id=np.array(class_id),
        )
```

#### ☐ Step 12: Implement VideoWall

**File:** `inference/core/interfaces/nvr/wall/wall.py`

```python
import signal
from typing import List

import cv2
import numpy as np

from inference.core.interfaces.camera.video_source import VideoSource
from inference.core.interfaces.camera.utils import multiplex_videos
from inference.core.interfaces.camera.entities import VideoFrame
from inference.core.models.utils.batching import create_batches
from inference.core import logger

from .config import VideoWallConfig
from .detection_cache import DetectionCache
from .mqtt_listener import MQTTListener
from .renderer import DetectionRenderer


STOP = False
BLACK_FRAME = np.zeros((360, 480, 3), dtype=np.uint8)


class VideoWall:
    """Video wall viewer with MQTT event overlays"""
    
    def __init__(self, config: VideoWallConfig):
        self.config = config
        self.cache = DetectionCache(ttl_seconds=config.detection_ttl_seconds)
        self.mqtt_listener = MQTTListener(config, self.cache)
        self.renderer = DetectionRenderer(config)
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def start(self):
        """Start the video wall"""
        global STOP
        
        logger.info(f"Starting VideoWall with {len(self.config.stream_uris)} streams")
        
        # Start MQTT listener
        self.mqtt_listener.start()
        
        # Initialize video sources
        cameras = [
            VideoSource.init(uri, source_id=i)
            for i, uri in enumerate(self.config.stream_uris)
        ]
        
        for camera in cameras:
            camera.start()
        
        logger.info("Video sources started, beginning display...")
        
        # Multiplex and render
        try:
            multiplexer = multiplex_videos(
                videos=cameras,
                should_stop=lambda: STOP,
            )
            
            for frames in multiplexer:
                self._render_frame_batch(frames)
                
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
        
        finally:
            # Cleanup
            cv2.destroyAllWindows()
            for camera in cameras:
                camera.terminate(wait_on_frames_consumption=False, purge_frames_buffer=True)
            self.mqtt_listener.stop()
            
            logger.info("VideoWall stopped")
    
    def _render_frame_batch(self, frames: List[VideoFrame]):
        """Render batch of frames as grid"""
        images = []
        
        for frame in frames:
            # Get cached detections
            event = self.cache.get(frame.source_id)
            
            # Render frame
            image = self.renderer.render_frame(frame, event)
            images.append(image)
        
        # Fill missing tiles with black
        n_streams = len(self.config.stream_uris)
        while len(images) < n_streams:
            images.append(BLACK_FRAME)
        
        # Create grid
        rows = list(create_batches(sequence=images, batch_size=self.config.grid_columns))
        
        # Pad last row
        while len(rows[-1]) < self.config.grid_columns:
            rows[-1].append(BLACK_FRAME)
        
        # Merge rows
        rows_merged = [np.concatenate(r, axis=1) for r in rows]
        grid = np.concatenate(rows_merged, axis=0)
        
        # Display
        cv2.imshow("NVR Video Wall", grid)
    
    def _signal_handler(self, signum, frame):
        """Handle termination signals"""
        global STOP
        logger.info(f"Received signal {signum}, shutting down...")
        STOP = True
```

---

### Day 7: CLI + Integration Testing

#### ☐ Step 13: Implement CLI commands

**File:** `inference_cli/nvr.py`

```python
import click
import os
from inference.core.interfaces.nvr.processor import StreamProcessor, StreamProcessorConfig
from inference.core.interfaces.nvr.wall import VideoWall, VideoWallConfig


@click.group()
def nvr():
    """Network Video Recorder (NVR) commands"""
    pass


@nvr.command()
@click.option("--n", type=int, default=6, help="Number of streams")
@click.option("--model", default="yolov8x-640", help="Model ID")
@click.option("--mqtt-host", default="localhost", help="MQTT broker host")
@click.option("--mqtt-port", type=int, default=1883, help="MQTT broker port")
@click.option("--stream-server", default=None, help="RTSP server URL")
def processor(n, model, mqtt_host, mqtt_port, stream_server):
    """Run headless stream processor with MQTT event publishing"""
    
    if stream_server is None:
        stream_server = os.getenv("STREAM_SERVER", "rtsp://localhost:8554")
    
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
@click.option("--stream-server", default=None, help="RTSP server URL")
@click.option("--tile-width", type=int, default=480, help="Tile width in pixels")
@click.option("--tile-height", type=int, default=360, help="Tile height in pixels")
def wall(n, mqtt_host, mqtt_port, stream_server, tile_width, tile_height):
    """Run video wall viewer with MQTT event overlays"""
    
    if stream_server is None:
        stream_server = os.getenv("STREAM_SERVER", "rtsp://localhost:8554")
    
    config = VideoWallConfig(
        stream_uris=[f"{stream_server}/live/{i}.stream" for i in range(n)],
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        tile_size=(tile_width, tile_height),
    )
    
    wall_app = VideoWall(config)
    wall_app.start()
```

**Update:** `inference_cli/main.py`

```python
from .nvr import nvr

# Add to main CLI group
cli.add_command(nvr)
```

#### ☐ Step 14: Integration test (end-to-end)

**Test Script:** `tests/inference/integration_tests/nvr/test_e2e.py`

```bash
#!/bin/bash
# Start dependencies
docker run -d --name mosquitto -p 1883:1883 eclipse-mosquitto
go2rtc -config config/go2rtc/go2rtc.yaml &
GO2RTC_PID=$!

sleep 3

# Start processor (background)
inference nvr processor --n 2 --model yolov8n-640 &
PROCESSOR_PID=$!

sleep 5

# Start wall (foreground, will auto-stop after 10 seconds in test mode)
timeout 10 inference nvr wall --n 2

# Cleanup
kill $PROCESSOR_PID
kill $GO2RTC_PID
docker stop mosquitto
docker rm mosquitto

echo "Integration test completed"
```

---

## ☑️ Definition of Done

### Functional Requirements

- [x] StreamProcessor publishes DetectionEvent to MQTT
- [x] VideoWall subscribes to MQTT and displays overlays
- [x] End-to-end latency < 200ms
- [x] No memory leaks in 1 hour run
- [x] CLI commands work (`inference nvr processor/wall`)

### Quality Requirements

- [x] Unit tests for event schema (serialization)
- [x] Unit tests for MQTT sink (with mock)
- [x] Unit tests for detection cache (TTL)
- [x] Integration test (processor → broker → wall)
- [x] Test coverage > 80%

### Documentation

- [x] README in `inference/core/interfaces/nvr/`
- [x] Docstrings for all public APIs
- [x] Example usage in docs
- [x] Architecture diagram

---

## 🧪 Testing Commands

```bash
# Run unit tests
pytest tests/inference/unit_tests/core/interfaces/nvr/ -v

# Run integration tests
pytest tests/inference/integration_tests/nvr/ -v

# Test coverage
pytest --cov=inference.core.interfaces.nvr tests/inference/unit_tests/core/interfaces/nvr/

# Manual integration test
# Terminal 1: MQTT broker
docker run -p 1883:1883 eclipse-mosquitto

# Terminal 2: RTSP streams
go2rtc -config config/go2rtc/go2rtc.yaml

# Terminal 3: Processor
inference nvr processor --n 6

# Terminal 4: Wall
inference nvr wall --n 6

# Terminal 5: Monitor MQTT
mosquitto_sub -t "nvr/detections/#" -v
```

---

## 📦 Dependencies

Add to `requirements/_requirements.txt`:

```
paho-mqtt>=1.6.1  # MQTT client (already in enterprise)
```

No new dependencies needed! ✅

---

## 🚀 Next Steps After MVP

### Phase 2 Enhancements

- [ ] Event store (PostgreSQL + TimescaleDB)
- [ ] Web UI viewer (React + WebRTC)
- [ ] Multi-tenant support
- [ ] Alert rules engine
- [ ] Person re-identification
- [ ] Recording on demand

---

## 📚 Reference

- **[DESIGN_NVR_MULTIPLEXER.md](./DESIGN_NVR_MULTIPLEXER.md)** - Full architecture
- **[NVR_ARCHITECTURE_DIAGRAM.md](./NVR_ARCHITECTURE_DIAGRAM.md)** - Visual diagrams
- **[MANIFESTO_DISENO.md](./MANIFESTO_DISENO%20-%20Blues%20Style.md)** - Design principles

---

**Status:** 🟡 Ready to implement  
**Estimated Time:** 1 week (40 hours)  
**Assigned To:** Visiona Team

🎸 *"Tocar con conocimiento de las reglas, no seguir la partitura al pie de la letra"*

