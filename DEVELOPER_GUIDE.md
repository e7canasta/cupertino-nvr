# Cupertino NVR - Developer Guide

Quick reference for developers working on the NVR system.

---

## 🚀 Quick Setup

```bash
# 1. Navigate to package
cd cupertino/nvr

# 2. Create virtual environment (optional)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 3. Install in development mode
pip install -e ".[dev]"

# 4. Install parent inference package (required dependency)
cd ../..  # Back to repo root
pip install -e .
cd cupertino/nvr
```

---

## 🧪 Running Tests

```bash
# Run all unit tests
pytest tests/unit/ -v

# Run specific test file
pytest tests/unit/test_events.py -v

# Run with coverage
pytest tests/unit/ --cov=cupertino_nvr --cov-report=html

# Open coverage report
open htmlcov/index.html  # On macOS
```

---

## 🔍 Code Quality

```bash
# Format code
black cupertino_nvr/ tests/
isort cupertino_nvr/ tests/

# Check linting
flake8 cupertino_nvr/ tests/

# Type checking
mypy cupertino_nvr/
```

---

## 🏃 Running Locally

### Prerequisites

```bash
# 1. Start MQTT broker
docker run -d --name mosquitto -p 1883:1883 eclipse-mosquitto

# 2. Start test RTSP streams (optional - for testing)
# Install go2rtc: https://github.com/AlexxIT/go2rtc
go2rtc -config config/go2rtc/go2rtc.yaml
```

### Run Processor

```bash
# Using CLI
cupertino-nvr processor --n 2 --model yolov8n-640

# Using Python
python -c "
from cupertino_nvr import StreamProcessor, StreamProcessorConfig

config = StreamProcessorConfig(
    stream_uris=['rtsp://localhost:8554/live/0.stream'],
    model_id='yolov8n-640',
    mqtt_host='localhost',
)

processor = StreamProcessor(config)
processor.start()
processor.join()
"
```

### Run Video Wall

```bash
# Using CLI
cupertino-nvr wall --n 2

# Using Python
python -c "
from cupertino_nvr import VideoWall, VideoWallConfig

config = VideoWallConfig(
    stream_uris=['rtsp://localhost:8554/live/0.stream'],
    mqtt_host='localhost',
)

wall = VideoWall(config)
wall.start()
"
```

---

## 📝 Code Structure

### Adding a New Event Field

1. Update `cupertino_nvr/events/schema.py`:
```python
class DetectionEvent(BaseModel):
    # ... existing fields ...
    new_field: Optional[str] = Field(default=None, description="New field")
```

2. Update `cupertino_nvr/processor/mqtt_sink.py`:
```python
def _create_event(self, prediction: dict, frame: object) -> DetectionEvent:
    return DetectionEvent(
        # ... existing fields ...
        new_field=prediction.get("new_field"),
    )
```

3. Add test in `tests/unit/test_events.py`:
```python
def test_event_with_new_field():
    event = DetectionEvent(
        # ... existing fields ...
        new_field="test_value",
    )
    assert event.new_field == "test_value"
```

### Adding a New CLI Command

1. Update `cupertino_nvr/cli.py`:
```python
@main.command()
@click.option("--option", help="Option description")
def new_command(option):
    """Command description"""
    # Implementation
    pass
```

### Adding a New Configuration Option

1. Update config dataclass:
```python
@dataclass
class StreamProcessorConfig:
    # ... existing fields ...
    new_option: str = "default_value"
    """Option description"""
```

2. Use in implementation:
```python
def __init__(self, config: StreamProcessorConfig):
    self.config = config
    # Use self.config.new_option
```

---

## 🐛 Debugging

### Enable Debug Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Monitor MQTT Messages

```bash
# Subscribe to all detection events
mosquitto_sub -h localhost -t "nvr/detections/#" -v

# Pretty print JSON
mosquitto_sub -h localhost -t "nvr/detections/#" | jq
```

### Check MQTT Connection

```bash
# Test MQTT connection
mosquitto_pub -h localhost -t "test" -m "hello"
mosquitto_sub -h localhost -t "test"
```

---

## 🔧 Common Issues

### Issue: "ModuleNotFoundError: No module named 'inference'"

**Solution:** Install parent inference package:
```bash
cd ../..  # Go to repo root
pip install -e .
```

### Issue: "Connection refused" when connecting to MQTT

**Solution:** Start MQTT broker:
```bash
docker run -d -p 1883:1883 eclipse-mosquitto
```

### Issue: "No video sources found"

**Solution:** Check RTSP streams are running:
```bash
# Test stream with ffplay
ffplay rtsp://localhost:8554/live/0.stream
```

### Issue: Import errors with relative imports

**Solution:** Use absolute imports:
```python
# ✅ Good
from cupertino_nvr.events import DetectionEvent

# ❌ Bad
from .events import DetectionEvent  # Only works inside package
```

---

## 📊 Performance Profiling

### Profile CPU Usage

```python
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()

# Run your code
processor.start()

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)  # Top 20 functions
```

### Profile Memory Usage

```python
from memory_profiler import profile

@profile
def my_function():
    # Your code
    pass
```

### Monitor MQTT Throughput

```bash
# Count messages per second
mosquitto_sub -h localhost -t "nvr/detections/#" | pv -l > /dev/null
```

---

## 🚢 Building and Distribution

### Build Package

```bash
# Build wheel and source distribution
python -m build

# Output:
# dist/cupertino_nvr-0.1.0-py3-none-any.whl
# dist/cupertino-nvr-0.1.0.tar.gz
```

### Install from Wheel

```bash
pip install dist/cupertino_nvr-0.1.0-py3-none-any.whl
```

---

## 📚 Architecture Reference

### Data Flow

```
VideoFrame → InferencePipeline → MQTTDetectionSink → MQTT Broker
                                                          ↓
                                                    MQTTListener
                                                          ↓
                                                   DetectionCache
                                                          ↓
                                                  DetectionRenderer
                                                          ↓
                                                      VideoWall
```

### Component Responsibilities

| Component | Responsibility | Dependencies |
|-----------|----------------|--------------|
| **StreamProcessor** | Orchestrate inference pipeline | InferencePipeline, MQTT |
| **MQTTDetectionSink** | Publish events to MQTT | paho-mqtt, events |
| **VideoWall** | Display video grid | multiplex_videos, MQTT |
| **DetectionCache** | Cache events with TTL | events |
| **MQTTListener** | Subscribe to MQTT events | paho-mqtt, cache |
| **DetectionRenderer** | Draw detection overlays | OpenCV, supervision |

---

## 🤝 Contributing Workflow

1. **Create feature branch**
```bash
git checkout -b feature/my-feature
```

2. **Make changes**
```bash
# Edit files
vim cupertino_nvr/processor/processor.py
```

3. **Add tests**
```bash
# Edit test files
vim tests/unit/test_processor.py
```

4. **Format and lint**
```bash
black cupertino_nvr/ tests/
isort cupertino_nvr/ tests/
flake8 cupertino_nvr/ tests/
```

5. **Run tests**
```bash
pytest tests/unit/ -v
```

6. **Commit**
```bash
git add .
git commit -m "feat: Add new feature"
```

7. **Push and create PR**
```bash
git push origin feature/my-feature
```

---

## 📖 Further Reading

- **[DESIGN_NVR_MULTIPLEXER.md](../../wiki/DESIGN_NVR_MULTIPLEXER.md)** - Complete architecture
- **[NVR_IMPLEMENTATION_CHECKLIST.md](../../wiki/NVR_IMPLEMENTATION_CHECKLIST.md)** - Implementation guide
- **[MANIFESTO_DISENO.md](../../wiki/MANIFESTO_DISENO%20-%20Blues%20Style.md)** - Design principles
- **[IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md)** - Current implementation status

---

**Questions?** Check the [README.md](./README.md) or open an issue.

🎸 *Built with the Visiona Design Manifesto*

