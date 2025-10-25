# NVR Multiplexer - Quick Start (2 minutes)

> **Get running in 2 minutes** | [Full Docs →](./NVR_INDEX.md)

---

## 🚀 Setup

```bash
# 1. Start MQTT broker
docker run -d -p 1883:1883 eclipse-mosquitto

# 2. Start test streams (optional)
go2rtc -config config/go2rtc/go2rtc.yaml
```

---

## 🎬 Run

### Terminal 1: Processor (Headless Inference)

```bash
inference nvr processor --n 6 --model yolov8x-640
```

### Terminal 2: Video Wall (Display)

```bash
inference nvr wall --n 6
```

**Done!** You should see 6 video streams with detections.

---

## ⚙️ Common Options

```bash
# More streams
inference nvr processor --n 12

# Lighter model (faster)
inference nvr processor --n 6 --model yolov8n-640

# Custom MQTT broker
inference nvr processor --mqtt-host 192.168.1.100

# Larger tiles
inference nvr wall --tile-width 640 --tile-height 480
```

---

## 🐛 Troubleshooting

### No detections showing?

```bash
# Check MQTT is working
mosquitto_sub -t "nvr/detections/#" -v
```

### High CPU?

```bash
# Use smaller model
inference nvr processor --model yolov8n-640

# Or fewer streams
inference nvr processor --n 4
```

---

## 📚 Learn More

- **[Full README](./NVR_README.md)** - Complete guide
- **[Architecture](./NVR_ARCHITECTURE_DIAGRAM.md)** - How it works
- **[All Docs](./NVR_INDEX.md)** - Documentation hub

---

**Questions?** See [Troubleshooting](./NVR_README.md#troubleshooting)

