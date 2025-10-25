# Cupertino NVR - Quick Start

> **Get running in under 5 minutes**

---

## 🚀 Installation

```bash
cd cupertino/nvr
make install-dev
```

---

## 🎬 Run Demo

### Step 1: Start MQTT Broker

```bash
make run-broker
# MQTT running on localhost:1883
```

### Step 2: Start Processor (Terminal 1)

```bash
make run-processor N=4
# Processing 4 streams with YOLOv8x
```

### Step 3: Start Video Wall (Terminal 2)

```bash
make run-wall N=4
# Displaying 4 streams with detections
```

**Done!** Press `q` to quit the wall, `Ctrl+C` to stop processor.

---

## 📝 Development Commands

```bash
# Format code
make format

# Run tests
make test

# Check linting
make lint

# Full CI pipeline
make ci
```

---

## 📚 Next Steps

- **[README.md](./README.md)** - Complete documentation
- **[Makefile](./Makefile)** - All available commands
- **[../../wiki/NVR_INDEX.md](../../wiki/NVR_INDEX.md)** - Full docs

---

**Package:** `cupertino-nvr`  
**Version:** 0.1.0  
**License:** Apache 2.0

