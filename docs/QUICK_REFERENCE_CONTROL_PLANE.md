# Quick Reference: InferencePipeline + Control Plane

## Setup (Orden Correcto)

```python
class YourService:
    def start(self):
        # 1. Setup MQTT + Sink
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.connect(host, port)
        self.mqtt_client.loop_start()

        self.sink = YourSink(self.mqtt_client)

        # 2. Create Pipeline (NO start!)
        from inference import InferencePipeline
        self.pipeline = InferencePipeline.init(
            video_reference=streams,
            model_id=model_id,
            on_prediction=self.sink,
        )

        # 3. Control Plane (ANTES de pipeline.start!)
        if enable_control:
            self.control_plane = MQTTControlPlane(...)
            self._setup_commands()
            self.control_plane.connect()
            logger.info("✅ CONTROL PLANE READY")

        # 4. Start Pipeline (puede bloquear 20+ segundos)
        self.pipeline.start()
        self.is_running = True
```

---

## Sink Pauseable (Thread-Safe)

```python
import threading

class YourSink:
    def __init__(self, mqtt_client):
        self.client = mqtt_client
        # Thread-safe pause control (NOT boolean!)
        self._running = threading.Event()
        self._running.set()

    def __call__(self, predictions, video_frame):
        # Check pause FIRST
        if not self._running.is_set():
            return

        # Publish...
        self.client.publish(topic, data)

    def pause(self):
        self._running.clear()  # Memory barrier

    def resume(self):
        self._running.set()  # Memory barrier
```

---

## Command Handlers

```python
def _handle_pause(self):
    # Check pipeline EXISTS (not is_running!)
    if self.pipeline and not self.is_paused:
        # 1. Sink first (immediate)
        self.sink.pause()

        # 2. Pipeline second (gradual)
        self.pipeline.pause_stream()

        self.is_paused = True
        self.control_plane.publish_status("paused")

def _handle_resume(self):
    if self.pipeline and self.is_paused:
        # 1. Pipeline first (start buffering)
        self.pipeline.resume_stream()

        # 2. Sink second (start publishing)
        self.sink.resume()

        self.is_paused = False
        self.control_plane.publish_status("running")

def _handle_stop(self):
    if self.pipeline:
        self.pipeline.terminate()
        self.control_plane.publish_status("stopped")
```

---

## Los 3 Pitfalls

### ❌ 1. Control Plane Después de pipeline.start()
```python
self.pipeline.start()  # Bloquea 20s
self.control_plane = ...  # Nunca llega a tiempo
```
**Fix:** Control plane ANTES

### ❌ 2. Verificar is_running en Handlers
```python
if self.is_running:  # False durante startup!
    self.pipeline.pause()
```
**Fix:** Verificar `if self.pipeline`

### ❌ 3. Boolean Flag para Pause
```python
self._paused = False  # Memory visibility issue
if self._paused:
    return
```
**Fix:** Usar `threading.Event`

---

## Checklist

**Setup:**
- [ ] Sink con `threading.Event`
- [ ] Control plane ANTES de `pipeline.start()`
- [ ] Log "✅ CONTROL PLANE READY"

**Handlers:**
- [ ] Check `if self.pipeline` (no `is_running`)
- [ ] PAUSE: sink first, pipeline second
- [ ] RESUME: pipeline first, sink second

**Testing:**
- [ ] Control plane ready ANTES de ver detecciones
- [ ] PAUSE detiene en <1 segundo
- [ ] Comandos durante startup funcionan

---

**Ver:** `docs/nvr/BLUEPRINT_INFERENCE_PIPELINE_CONTROL.md` para guía completa
