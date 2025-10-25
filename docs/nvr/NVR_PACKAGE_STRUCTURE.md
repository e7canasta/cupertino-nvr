# Cupertino NVR - Package Structure

> **Independent package structure with Makefile-based development**

---

## 📦 Directory Layout

```
inference/
├── cupertino/                    # Cupertino namespace (Visiona projects)
│   ├── __init__.py
│   └── nvr/                      # NVR package
│       ├── __init__.py           # Package exports
│       ├── README.md             # Package documentation
│       ├── Makefile              # Development tasks ⭐
│       ├── pyproject.toml        # Package configuration
│       ├── .gitignore
│       │
│       ├── processor/            # StreamProcessor module
│       │   ├── __init__.py
│       │   ├── processor.py      # Main processor class
│       │   ├── mqtt_sink.py      # MQTT detection sink
│       │   └── config.py         # Configuration dataclass
│       │
│       ├── wall/                 # VideoWall module
│       │   ├── __init__.py
│       │   ├── wall.py           # Main wall class
│       │   ├── mqtt_listener.py  # MQTT subscriber thread
│       │   ├── detection_cache.py # Thread-safe cache with TTL
│       │   ├── renderer.py       # Detection overlay renderer
│       │   └── config.py         # Configuration dataclass
│       │
│       ├── events/               # Event protocol module
│       │   ├── __init__.py
│       │   ├── schema.py         # Pydantic event schemas
│       │   └── protocol.py       # MQTT topic utilities
│       │
│       ├── cli.py                # CLI entry point
│       │
│       └── tests/                # Test suite
│           ├── __init__.py
│           ├── unit/             # Unit tests
│           │   ├── test_events.py
│           │   ├── test_mqtt_sink.py
│           │   ├── test_cache.py
│           │   └── test_renderer.py
│           └── integration/      # Integration tests
│               └── test_e2e.py
│
└── wiki/                         # Documentation (project-wide)
    ├── NVR_INDEX.md
    ├── DESIGN_NVR_MULTIPLEXER.md
    └── ...
```

---

## 🎯 Design Rationale

### Why Independent Package?

| Aspect | Benefit |
|--------|---------|
| **Versioning** | Own release cycle (0.1.0, 0.2.0, ...) |
| **Ownership** | Clear Cupertino/Visiona namespace |
| **Deployment** | Can be distributed independently |
| **Development** | Makefile for quick tasks |
| **Testing** | Isolated test suite |
| **Documentation** | Self-contained README |

### Namespace Choice: `cupertino.nvr`

**Why `cupertino`?**
- Visiona's project namespace
- Clear separation from `inference` core
- Allows other Cupertino packages (e.g., `cupertino.analytics`)

**Why not `inference.core.interfaces.nvr`?**
- Too tightly coupled to Inference
- Hard to version independently
- Difficult to extract later

---

## 🛠️ Makefile Commands

The package includes a comprehensive Makefile for development:

### Installation

```bash
make install          # Install package
make install-dev      # Install with dev dependencies
make dev-setup        # Create venv + install
```

### Development

```bash
make format           # Format code (black + isort)
make lint             # Run linters (flake8 + mypy)
make test             # Run all tests
make test-unit        # Unit tests only
make test-integration # Integration tests only
make coverage         # Test coverage report
```

### Running

```bash
make run-processor N=6          # Start processor
make run-wall N=6               # Start wall
make run-broker                 # Start MQTT broker (Docker)
make run-streams                # Start test streams (go2rtc)
```

### Docker

```bash
make docker-build     # Build image
make docker-run       # Run in container
make docker-clean     # Remove images
```

### Cleanup

```bash
make clean            # Remove build artifacts
make clean-all        # Deep clean (including venv)
```

### Helpers

```bash
make demo             # Interactive demo
make ci               # CI pipeline (lint + test + coverage)
make docs             # Show documentation
make bump-patch       # Bump version (0.1.0 → 0.1.1)
make bump-minor       # Bump version (0.1.0 → 0.2.0)
make bump-major       # Bump version (0.1.0 → 1.0.0)
```

---

## 📝 Package Configuration

### pyproject.toml

```toml
[project]
name = "cupertino-nvr"
version = "0.1.0"
description = "Distributed Network Video Recorder with AI inference"

dependencies = [
    "inference>=0.9.18",
    "paho-mqtt>=1.6.1",
    "pydantic>=2.0.0",
    "supervision>=0.16.0",
    "opencv-python>=4.8.0",
]

[project.scripts]
cupertino-nvr = "cupertino.nvr.cli:main"
```

### CLI Entry Point

```python
# cupertino/nvr/cli.py
import click

@click.group()
def main():
    """Cupertino NVR - Distributed Video Recorder"""
    pass

@main.command()
@click.option("--n", type=int, default=6)
def processor(n):
    """Run headless stream processor"""
    # Implementation...

@main.command()
@click.option("--n", type=int, default=6)
def wall(n):
    """Run video wall viewer"""
    # Implementation...
```

---

## 🚀 Usage Examples

### Installation

```bash
# Clone repo
git clone <repo-url>
cd inference/cupertino/nvr

# Install in development mode
make install-dev

# Or manually
pip install -e ".[dev]"
```

### CLI Usage

```bash
# Using installed command
cupertino-nvr processor --n 12 --model yolov8x-640
cupertino-nvr wall --n 12

# Using Makefile (development)
cd cupertino/nvr
make run-processor N=12 MODEL=yolov8x-640
make run-wall N=12
```

### Python API

```python
from cupertino.nvr import StreamProcessor, StreamProcessorConfig

config = StreamProcessorConfig(
    stream_uris=["rtsp://..."],
    model_id="yolov8x-640",
    mqtt_host="localhost",
)

processor = StreamProcessor(config)
processor.start()
processor.join()
```

---

## 🧪 Testing

### Test Structure

```
tests/
├── unit/                     # Fast, isolated tests
│   ├── test_events.py        # Event schema tests
│   ├── test_mqtt_sink.py     # MQTT sink tests (mocked)
│   ├── test_cache.py         # Detection cache tests
│   └── test_renderer.py      # Renderer tests (mocked)
│
└── integration/              # Slow, end-to-end tests
    └── test_e2e.py           # Full pipeline test
```

### Running Tests

```bash
# All tests
make test

# Unit tests only (fast)
make test-unit

# Integration tests (requires MQTT broker)
make run-broker
make test-integration

# With coverage
make coverage
```

---

## 📦 Distribution

### Building Package

```bash
# Build distribution
python -m build

# Outputs:
# dist/cupertino_nvr-0.1.0-py3-none-any.whl
# dist/cupertino-nvr-0.1.0.tar.gz
```

### Publishing

```bash
# Test PyPI
python -m twine upload --repository testpypi dist/*

# Production PyPI
python -m twine upload dist/*
```

### Installation from PyPI

```bash
pip install cupertino-nvr
```

---

## 🔄 Version Management

```bash
# Bump patch version (0.1.0 → 0.1.1)
make bump-patch

# Bump minor version (0.1.0 → 0.2.0)
make bump-minor

# Bump major version (0.1.0 → 1.0.0)
make bump-major
```

---

## 🎯 Development Workflow

### 1. Setup Environment

```bash
cd cupertino/nvr
make dev-setup
source venv/bin/activate
```

### 2. Develop

```bash
# Edit code
vim cupertino/nvr/processor/processor.py

# Format
make format

# Lint
make lint

# Test
make test-unit
```

### 3. Test Integration

```bash
# Start dependencies
make run-broker

# Test
make test-integration

# Or manually
make run-processor N=2 &
make run-wall N=2
```

### 4. Commit

```bash
git add .
git commit -m "feat: Add new feature"
git push
```

---

## 📚 Documentation

Package-level documentation:
- **[README.md](../../cupertino/nvr/README.md)** - Package overview
- **[Makefile](../../cupertino/nvr/Makefile)** - Development tasks

Project-level documentation:
- **[NVR_INDEX.md](./NVR_INDEX.md)** - Documentation hub
- **[DESIGN_NVR_MULTIPLEXER.md](./DESIGN_NVR_MULTIPLEXER.md)** - Architecture
- **[NVR_IMPLEMENTATION_CHECKLIST.md](./NVR_IMPLEMENTATION_CHECKLIST.md)** - Implementation guide

---

## 🔗 Integration with Inference

The package uses Inference as a dependency, not as a parent:

```python
# cupertino/nvr/processor/processor.py
from inference import InferencePipeline  # Dependency

# cupertino/nvr/wall/wall.py
from inference.core.interfaces.camera.utils import multiplex_videos
from inference.core.interfaces.camera.video_source import VideoSource
```

**Benefits:**
- ✅ Clear dependency direction
- ✅ Can upgrade Inference independently
- ✅ Can package cupertino-nvr separately

---

## 📊 Comparison: Integrated vs Independent

| Aspect | Integrated (`inference/core/interfaces/nvr/`) | Independent (`cupertino/nvr/`) ✅ |
|--------|----------------------------------------------|----------------------------------|
| **Versioning** | Tied to Inference releases | Independent (0.1.0, 0.2.0, ...) |
| **Distribution** | Part of Inference package | Separate PyPI package |
| **Development** | Inference Makefile | Own Makefile ⭐ |
| **Testing** | Inference test suite | Own test suite |
| **Documentation** | Inference docs | Self-contained |
| **CLI** | `inference nvr processor` | `cupertino-nvr processor` |
| **Ownership** | Roboflow | Visiona/Cupertino |

---

**Status:** ✅ Implemented  
**Version:** 0.1.0  
**Next:** Implement modules (processor, wall, events)

🎸 *Independent package structure for maximum flexibility*

