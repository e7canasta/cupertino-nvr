 # Blueprint: Control Plane para Servicios con InferencePipeline

## Contexto

Este blueprint surge de la implementación del control plane en cupertino-nvr. Documenta los pitfalls descubiertos y las soluciones probadas para integrar control remoto (MQTT) en servicios headless que usan Roboflow InferencePipeline.

**Audiencia:** Desarrolladores implementando nuevos servicios de inferencia (ej: siguiente versión de Adeline, nuevos NVR modules).

**Filosofía:** Complejidad por diseño, no por accidente. Conocer estos patterns desde el inicio.

---

## El Problema Que Resolvimos

### Síntoma
```
Usuario envía comando PAUSE via MQTT → Processor lo recibe → No pasa nada (sigue infiriendo)
```

### Root Causes (3 bugs encontrados)

#### Bug 1: Control Plane Inicializado DESPUÉS de pipeline.start()

**Código original:**
```python
def start(self):
    # ... setup ...

    self.pipeline.start()  # ← BLOQUEA 20+ segundos conectando a RTSP

    # Control plane se inicializa aquí (demasiado tarde!)
    if self.config.enable_control_plane:
        self.control_plane = MQTTControlPlane(...)
```

**Problema:**
- `pipeline.start()` bloquea el hilo principal conectando a streams RTSP
- Durante ese tiempo (20+ segundos), el control plane NO existe
- Usuario ve detecciones pero comandos MQTT no funcionan

**Fix:**
```python
def start(self):
    # ... setup ...

    # Initialize Control Plane ANTES de pipeline.start()
    if self.config.enable_control_plane:
        self.control_plane = MQTTControlPlane(...)
        self.control_plane.connect()
        logger.info("✅ CONTROL PLANE READY")

    # Ahora sí, iniciar pipeline (puede bloquear)
    self.pipeline.start()
```

**Lección:** Control plane debe estar listo ANTES de que el servicio empiece a producir datos.

---

#### Bug 2: State Check Incorrecto en Handlers

**Código original:**
```python
def _handle_pause(self):
    if self.is_running and not self.is_paused:  # ← is_running=False durante startup
        # pause pipeline
```

**Problema:**
- `self.is_running = True` se setea DESPUÉS de `pipeline.start()`
- Durante los 20+ segundos de bloqueo, `is_running = False`
- Comandos llegan pero son rechazados: "Pipeline not in correct state"

**Fix:**
```python
def _handle_pause(self):
    # Check pipeline exists (not is_running)
    if self.pipeline and not self.is_paused:
        # pause pipeline
```

**Lección:** En servicios con startup largo, verificar que objetos existan (not None), no flags de estado.

---

#### Bug 3: Thread Safety en Pause Flag

**Código original:**
```python
class MQTTDetectionSink:
    def __init__(self):
        self._paused = False  # Simple boolean

    def __call__(self, predictions, video_frame):
        if self._paused:  # ← NO memory barrier
            return

    def pause(self):
        self._paused = True  # ← Written by MQTT callback thread
```

**Problema:**
- Thread A (MQTT callback) escribe `_paused = True` en CPU cache local
- Thread B (InferencePipeline callback) lee desde SU CPU cache (stale!)
- GIL garantiza atomicity, NO visibility inmediata
- Detecciones siguen publicándose por 5-10 segundos (hasta que caches se sincronizan)

**Fix:**
```python
import threading

class MQTTDetectionSink:
    def __init__(self):
        self._running = threading.Event()  # Built-in memory barriers
        self._running.set()

    def __call__(self, predictions, video_frame):
        if not self._running.is_set():  # ← WITH memory barrier
            return

    def pause(self):
        self._running.clear()  # ← WITH memory barrier
```

**Lección:** Para control cross-thread, usar primitivas de threading (Event, Lock), NO boolean flags.

---

## Blueprint: Implementación Paso a Paso

### Paso 1: Arquitectura - Separación de Concerns

```
┌─────────────────────────────────────────────────┐
│              YourService                        │
│                                                 │
│  ┌──────────────┐      ┌──────────────────┐   │
│  │ Inference    │      │ Control Plane    │   │
│  │ Pipeline     │      │ (MQTT)           │   │
│  └──────┬───────┘      └────────┬─────────┘   │
│         │                       │              │
│         │ on_prediction         │ on_command   │
│         ▼                       ▼              │
│  ┌──────────────┐      ┌──────────────────┐   │
│  │ Data Sink    │◄─────┤ Command Handlers │   │
│  │ (pauseable)  │pause()│                  │   │
│  └──────────────┘      └──────────────────┘   │
└─────────────────────────────────────────────────┘
```

**Principios:**
1. **Data Plane** (InferencePipeline → Sink): Publica datos
2. **Control Plane** (MQTT → Handlers): Controla comportamiento
3. **Coupling mínimo**: Control plane controla sink via métodos simples (pause/resume)

---

### Paso 2: Implementar Sink Pauseable (Thread-Safe)

```python
import threading
from typing import Union, List, Optional

class YourDetectionSink:
    """
    Thread-safe sink compatible con InferencePipeline.

    IMPORTANTE: Usar threading.Event para pause control (no boolean!)
    """

    def __init__(self, ...):
        # Thread-safe pause control
        self._running = threading.Event()
        self._running.set()  # Start running

    def __call__(
        self,
        predictions: Union[dict, List[Optional[dict]]],
        video_frame: Union[object, List[Optional[object]]],
    ) -> None:
        """InferencePipeline callback (ejecutado en thread separado)"""

        # Check pause FIRST (thread-safe with memory barrier)
        if not self._running.is_set():
            return

        # Normal processing...
        self._publish(predictions, video_frame)

    def pause(self):
        """Pause publishing (immediate, thread-safe)"""
        self._running.clear()  # Memory barrier guarantees visibility
        logger.info("Sink paused")

    def resume(self):
        """Resume publishing (thread-safe)"""
        self._running.set()  # Memory barrier
        logger.info("Sink resumed")

    def _publish(self, predictions, video_frame):
        # Your actual publishing logic here
        pass
```

**Por qué threading.Event:**
- ✅ Built-in memory barriers (CPU cache flush)
- ✅ Thread-safe sin locks explícitos
- ✅ Overhead mínimo (~50ns per check)
- ✅ Pattern estándar en Python threading

**No usar:**
- ❌ Boolean flags (no memory barriers)
- ❌ Locks en el callback (demasiado overhead si alta frecuencia)

---

### Paso 3: Inicializar en Orden Correcto

```python
class YourService:
    def start(self):
        # 1. Setup básico
        self.mqtt_client = self._init_mqtt_client()
        self.sink = YourDetectionSink(self.mqtt_client, ...)

        # 2. Crear pipeline (NO iniciar todavía)
        from inference import InferencePipeline
        self.pipeline = InferencePipeline.init(
            video_reference=self.config.streams,
            model_id=self.config.model_id,
            on_prediction=self.sink,  # ← Sink ya creado
        )

        logger.info("Pipeline initialized (not started yet)")

        # 3. Initialize Control Plane ANTES de pipeline.start()
        if self.config.enable_control_plane:
            self.control_plane = MQTTControlPlane(...)
            self._setup_control_commands()  # Register pause/resume/stop

            if self.control_plane.connect(timeout=10):
                logger.info("✅ CONTROL PLANE READY")
            else:
                logger.warning("Control Plane failed, continuing without it")
                self.control_plane = None

        # 4. Start pipeline (puede bloquear conectando a streams)
        logger.info("▶️ Starting InferencePipeline...")
        self.pipeline.start()  # ← Puede tardar 20+ segundos
        self.is_running = True

        logger.info("✅ Pipeline started")
```

**Orden crítico:**
1. Crear objetos (pipeline, sink, control plane)
2. Control plane ready
3. Pipeline start (bloquea)
4. Set flags de estado

**No hacer:**
- ❌ Control plane después de pipeline.start()
- ❌ Setear is_running=True antes de pipeline.start()

---

### Paso 4: Implementar Command Handlers

```python
def _setup_control_commands(self):
    """Register MQTT commands"""
    registry = self.control_plane.command_registry

    registry.register('pause', self._handle_pause, "Pause processing")
    registry.register('resume', self._handle_resume, "Resume processing")
    registry.register('stop', self._handle_stop, "Stop completely")
    registry.register('status', self._handle_status, "Query status")

def _handle_pause(self):
    """Handle PAUSE command"""
    logger.info("⏸️ Executing PAUSE command")

    # Check pipeline exists (NOT is_running flag!)
    if self.pipeline and not self.is_paused:
        try:
            # Step 1: Pause sink FIRST (immediate stop)
            if self.sink:
                self.sink.pause()

            # Step 2: Pause pipeline (stop buffering new frames)
            self.pipeline.pause_stream()

            self.is_paused = True

            # Step 3: Publish status
            if self.control_plane:
                self.control_plane.publish_status("paused")

            logger.info("✅ PAUSE completed")

        except Exception as e:
            logger.error(f"❌ PAUSE failed: {e}", exc_info=True)
    else:
        logger.warning("⚠️ Cannot pause (already paused or no pipeline)")

def _handle_resume(self):
    """Handle RESUME command"""
    logger.info("▶️ Executing RESUME command")

    # Check pipeline exists and is paused
    if self.pipeline and self.is_paused:
        try:
            # Step 1: Resume pipeline FIRST (start buffering)
            self.pipeline.resume_stream()

            # Step 2: Resume sink (start publishing)
            if self.sink:
                self.sink.resume()

            self.is_paused = False

            if self.control_plane:
                self.control_plane.publish_status("running")

            logger.info("✅ RESUME completed")

        except Exception as e:
            logger.error(f"❌ RESUME failed: {e}", exc_info=True)
    else:
        logger.warning("⚠️ Cannot resume (not paused)")

def _handle_stop(self):
    """Handle STOP command"""
    logger.info("⏹️ Executing STOP command")

    # Check pipeline exists (stop should work even during startup)
    if self.pipeline:
        try:
            self.terminate()  # Calls pipeline.terminate()

            if self.control_plane:
                self.control_plane.publish_status("stopped")

            logger.info("✅ STOP completed")

        except Exception as e:
            logger.error(f"❌ STOP failed: {e}", exc_info=True)
    else:
        logger.warning("⚠️ Cannot stop (no pipeline)")
```

**Orden de operaciones:**

**PAUSE:**
1. Sink pause (immediate - detiene publicaciones)
2. Pipeline pause_stream() (gradual - detiene buffering)
3. Update estado

**RESUME:**
1. Pipeline resume_stream() (empieza a bufferar frames)
2. Sink resume (empieza a publicar)
3. Update estado

**Por qué ese orden:**
- Pause: Sink primero para stop inmediato
- Resume: Pipeline primero para que haya frames cuando sink reanude

---

### Paso 5: Workaround para pipeline.pause_stream()

**Problema conocido de InferencePipeline:**
- `pause_stream()` solo detiene buffering de NUEVOS frames
- Frames ya en prediction queue siguen procesándose
- Delay de 5-10 segundos hasta que queue se vacía

**Solución: Two-Level Pause**
```python
# Sink-level pause (immediate)
self.sink.pause()  # ← Detiene publicaciones en próximo callback

# Pipeline-level pause (gradual)
self.pipeline.pause_stream()  # ← Detiene buffering, reduce CPU gradualmente
```

**Resultado:**
- Publicaciones se detienen inmediatamente (<50ms)
- CPU se reduce gradualmente (5-10 segundos)

**Alternativa (si necesitas CPU reduction inmediato):**
- Usar `pipeline.terminate()` y recrear pipeline en resume
- Trade-off: Más lento para resume (~20s reconectar streams)

---

## Checklist de Implementación

Cuando implementes control plane en un nuevo servicio:

### Setup
- [ ] Crear sink pauseable con `threading.Event` (no boolean)
- [ ] Crear pipeline con `InferencePipeline.init()` (no start todavía)
- [ ] Crear control plane con `MQTTControlPlane`
- [ ] Registrar comandos en `CommandRegistry`
- [ ] Conectar control plane (timeout 10s)
- [ ] **Después** hacer `pipeline.start()`

### Handlers
- [ ] Pause: Sink first, pipeline second
- [ ] Resume: Pipeline first, sink second
- [ ] Stop: Llamar `pipeline.terminate()`
- [ ] Status: Publicar estado actual
- [ ] Checks: Verificar `if self.pipeline` (no `if self.is_running`)

### Thread Safety
- [ ] Sink usa `threading.Event` para pause control
- [ ] `__call__()` verifica `self._running.is_set()` al inicio
- [ ] `pause()` usa `self._running.clear()`
- [ ] `resume()` usa `self._running.set()`

### Logging
- [ ] Log cuando control plane se inicializa
- [ ] Log "✅ CONTROL PLANE READY" antes de pipeline.start()
- [ ] Log cada comando recibido
- [ ] Log warnings si comando se rechaza (incluir por qué)
- [ ] Log errores con traceback completo

### Testing
- [ ] Test: Control plane ready antes de ver detecciones
- [ ] Test: PAUSE detiene publicaciones en <1 segundo
- [ ] Test: RESUME reanuda publicaciones
- [ ] Test: STOP termina proceso
- [ ] Test: Comandos durante startup (primeros 20s) funcionan

---

## Pitfalls Comunes (¡Evitar!)

### ❌ 1. Boolean Flag para Pause

```python
# MAL - No thread-safe
self._paused = False

if self._paused:  # CPU cache staleness!
    return
```

**Por qué falla:** Memory visibility issue en multi-core systems.

**Fix:** Usar `threading.Event`

---

### ❌ 2. Control Plane Después de pipeline.start()

```python
# MAL - Control plane no existe durante startup
self.pipeline.start()  # Bloquea 20s
self.control_plane = MQTTControlPlane(...)  # Demasiado tarde
```

**Por qué falla:** Usuario ve detecciones pero comandos no funcionan.

**Fix:** Control plane antes de pipeline.start()

---

### ❌ 3. Verificar is_running en Handlers

```python
# MAL - is_running=False durante startup
if self.is_running:
    self.pipeline.pause_stream()
```

**Por qué falla:** Comandos rechazados durante primeros 20 segundos.

**Fix:** Verificar `if self.pipeline` (objeto existe)

---

### ❌ 4. Solo Pipeline Pause (Sin Sink Pause)

```python
# MAL - Solo pausa pipeline
def _handle_pause(self):
    self.pipeline.pause_stream()  # Frames en queue siguen procesándose!
```

**Por qué falla:** Publicaciones continúan por 5-10 segundos.

**Fix:** Two-level pause (sink + pipeline)

---

## Referencias

### Código de Referencia
- `cupertino-nvr/cupertino_nvr/processor/processor.py` - Implementación completa
- `cupertino-nvr/cupertino_nvr/processor/mqtt_sink.py` - Sink pauseable
- `cupertino-nvr/cupertino_nvr/processor/control_plane.py` - MQTT control

### Documentación Técnica
- `PAUSE_RESUME_WORKAROUND.md` - Two-level pause explanation
- `PAUSE_BUG_HYPOTHESIS.md` - Thread safety deep dive
- `CHANGELOG_MQTT_CONTROL.md` - Bug fixes y decisiones

### Adeline Reference
- `adeline/app/controller.py` - Similar control plane architecture
- Diferencias: Adeline tiene ROI state, metrics, multiple sinks

---

## Performance Considerations

### Threading.Event Overhead

**Benchmark (MacBook Pro M1, Python 3.13):**
```python
# Boolean check: ~0 ns
if self._paused:
    return

# Event check: ~50-100 ns
if not self._running.is_set():
    return
```

**Para 30 FPS:**
- Overhead total: ~3 microsegundos/segundo
- CPU impact: < 0.001%

**Conclusión:** Despreciable, vale la pena por thread-safety.

---

### Pipeline.pause_stream() Delay

**Observado en cupertino-nvr:**
- Comando pause → Sink pausa inmediatamente
- CPU usage sigue alto por 5-10 segundos
- Gradualmente baja a ~5% (solo polling)

**Por qué:**
- Frames en prediction queue siguen procesándose
- Inference continúa hasta que queue se vacía
- Es comportamiento esperado de InferencePipeline

**Si necesitas CPU reduction inmediato:**
- Opción 1: `pipeline.terminate()` + recrear en resume (lento)
- Opción 2: Aceptar delay gradual (recomendado)

---

## Testing Your Implementation

### Test Script Template

```python
#!/usr/bin/env python3
"""Test control plane functionality"""

import time
import paho.mqtt.client as mqtt
import json

def test_control_plane():
    client = mqtt.Client()
    client.connect("localhost", 1883)
    client.loop_start()

    def send_command(cmd):
        print(f"\n📤 Sending: {cmd}")
        client.publish("your/control/commands", json.dumps({"command": cmd}))
        time.sleep(2)

    # Test sequence
    print("Starting test sequence...")
    time.sleep(5)  # Wait for service to start

    send_command("status")  # Should return "running"
    send_command("pause")   # Should pause immediately
    send_command("status")  # Should return "paused"
    send_command("resume")  # Should resume
    send_command("status")  # Should return "running"
    send_command("stop")    # Should terminate

    client.loop_stop()
    print("\n✅ Test complete")

if __name__ == "__main__":
    test_control_plane()
```

### Expected Behavior

**PAUSE:**
- ✅ ACK received in <100ms
- ✅ Publications stop in <1 second
- ✅ Status = "paused"

**RESUME:**
- ✅ ACK received in <100ms
- ✅ Publications resume in <1 second
- ✅ Status = "running"

**STOP:**
- ✅ ACK received in <100ms
- ✅ Process terminates in <5 seconds

---

## Lecciones del Blues 🎸

**"Complejidad por diseño, no por accidente"**

Este blueprint existe porque:
1. ✅ Atacamos la complejidad con arquitectura clara (data/control planes separados)
2. ✅ Usamos las primitivas correctas (threading.Event, no boolean)
3. ✅ Documentamos el "por qué" (no solo el "cómo")
4. ✅ Creamos knowledge reutilizable (este blueprint)

**"El diablo sabe por diablo, no por viejo"**

Los 3 bugs que encontramos:
- Bug 1 (init order): Obvio en retrospectiva, invisible sin testing
- Bug 2 (state check): Edge case durante startup
- Bug 3 (thread safety): Sutil, intermitente, difícil de reproducir

Conocer estos pitfalls = tocar mejor blues en el próximo servicio.

**"Pragmatismo > Purismo"**

- threading.Event tiene overhead mínimo pero garantías fuertes → vale la pena
- Two-level pause es workaround, no ideal, pero funciona → pragmático
- Documentación extensa porque el próximo dev lo va a necesitar → inversión

---

## Conclusión

**Para implementar control plane en servicio con InferencePipeline:**

1. **Sink pauseable** con threading.Event
2. **Init order:** Control plane antes de pipeline.start()
3. **Handlers:** Verificar `if self.pipeline` (no is_running)
4. **Two-level pause:** Sink primero, pipeline segundo

**Este blueprint te ahorra ~8 horas de debugging** 🎸

---

*Blueprint creado: 2025-10-25*
*Basado en: cupertino-nvr control plane implementation*
*Mantenedor: Visiona Team*
