# Dynamic Model Change Fix

**Fecha:** 2025-10-25
**Tipo:** Bug Fix - MQTT Control Plane

---

## Problema Detectado

Al ejecutar `change_model`, el restart completaba exitosamente pero el `model_id` en las detecciones **NO cambiaba**:

```bash
# Comando:
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "change_model", "params": {"model_id": "yolov11x-640"}}'

# Logs: ✅ restart_completed, change_model_completed

# Pero detecciones seguían con modelo viejo:
nvr/detections/0 {"source_id":0, "model_id":"yolov8x-640", ...}
#                                            ^^^^^^^^^^^^^^ ¡Debería ser yolov11x-640!
```

**Contexto:** Además, el fix de restart (PR anterior) tenía una **race condition** donde el proceso terminaba después de restart en vez de continuar corriendo.

---

## Root Causes

### Bug 1: Sink con model_id estático

**Código problemático (mqtt_sink.py):**
```python
# Constructor
def __init__(self, mqtt_client, topic_prefix, model_id, source_id_mapping):
    self.model_id = model_id  # ← Captura valor en construcción

# Método _create_event
def _create_event(...):
    return DetectionEvent(
        model_id=self.model_id,  # ← Usa valor capturado (nunca actualiza)
        ...
    )
```

**Diseño problemático (processor.py):**
```python
# El sink se crea UNA VEZ y persiste entre restarts
self.mqtt_sink = MQTTDetectionSink(..., model_id=self.config.model_id)

# En restart:
self.pipeline = InferencePipeline.init(
    on_prediction=self.mqtt_sink,  # ← Reusa mismo sink!
    model_id=self.config.model_id  # ← Pipeline usa modelo nuevo...
)
# → Pipeline usa modelo nuevo, pero sink sigue publicando model_id viejo
```

**Problema conceptual:**
- El sink captura `model_id` como **valor** en el constructor
- Cuando cambiamos `config.model_id`, el sink NO se entera
- El pipeline se recrea (usa modelo nuevo), pero el sink sigue con el viejo

### Bug 2: Race condition en restart detection

**Código problemático (join loop):**
```python
# Thread MQTT ejecuta change_model
def _handle_restart(self):
    self._is_restarting = True
    # ... terminate pipeline, recreate, start ...
    self._is_restarting = False  # ← Setea flag ANTES de que thread principal checkee

# Thread principal
def join(self):
    while True:
        self.pipeline.join()  # ← Despierta DESPUÉS de que flag ya es False

        if self._is_restarting:  # ← Flag ya es False → no detecta restart
            continue
        else:
            break  # ← Termina proceso por error
```

**Problema conceptual:**
- Race condition entre thread MQTT (setea flag) y thread principal (lee flag)
- Flag se baja antes de que join() retorne
- Thread principal no detecta el restart

---

## Cambios Implementados

### Fix 1: Sink con referencia dinámica a config

**mqtt_sink.py:**
```python
# ANTES
def __init__(self, mqtt_client, topic_prefix, model_id, source_id_mapping):
    self.model_id = model_id  # Valor estático

def _create_event(...):
    return DetectionEvent(
        model_id=self.model_id  # Usa valor capturado
    )

# AHORA
def __init__(self, mqtt_client, topic_prefix, config, source_id_mapping):
    self.config = config  # Referencia al config (no copia)

def _create_event(...):
    return DetectionEvent(
        model_id=self.config.model_id  # Lookup dinámico!
    )
```

**processor.py:**
```python
# ANTES
self.mqtt_sink = MQTTDetectionSink(
    mqtt_client=self.mqtt_client,
    topic_prefix=self.config.mqtt_topic_prefix,
    model_id=self.config.model_id,  # Pasa valor
    source_id_mapping=self.config.source_id_mapping,
)

# AHORA
self.mqtt_sink = MQTTDetectionSink(
    mqtt_client=self.mqtt_client,
    topic_prefix=self.config.mqtt_topic_prefix,
    config=self.config,  # Pasa referencia completa
    source_id_mapping=self.config.source_id_mapping,
)
```

**Beneficio:**
- Sink hace lookup dinámico de `config.model_id` en cada evento
- Cuando `change_model` actualiza `config.model_id`, el sink ve el nuevo valor
- No necesita recrear el sink en restart

### Fix 2: Detección dual de restart (flag + pipeline reference)

**processor.py - join():**
```python
# ANTES
while True:
    self.pipeline.join()

    if hasattr(self, '_is_restarting') and self._is_restarting:
        continue  # Restart detected
    else:
        break  # Shutdown

# AHORA
while True:
    # Guardar referencia ANTES de join
    current_pipeline = self.pipeline

    current_pipeline.join()  # Wait for THIS pipeline

    # Detección dual: flag OR pipeline cambió
    is_restart = (
        (hasattr(self, '_is_restarting') and self._is_restarting) or
        (self.pipeline is not None and self.pipeline is not current_pipeline)
    )

    if is_restart:
        # Wait for restart to complete
        while (hasattr(self, '_is_restarting') and self._is_restarting):
            time.sleep(0.1)
        continue  # Rejoin new pipeline
    else:
        break  # Real shutdown
```

**Beneficio:**
- Incluso si `_is_restarting` flag ya es `False`, detecta restart por cambio de referencia
- `self.pipeline is not current_pipeline` → pipeline fue reemplazado → restart
- Elimina race condition

---

## Testing

### Test 1: change_model con proceso persistente

```bash
# Terminal 1: Start processor
uv run cupertino-nvr processor \
  --streams 0 \
  --stream-server rtsp://localhost:8554 \
  --model yolov8x-640 \
  --enable-control \
  --metrics-interval 60

# Terminal 2: Subscribe to detections
mosquitto_sub -h localhost -t "nvr/detections/0" | jq .model_id

# Debería mostrar:
# "yolov8x-640"
# "yolov8x-640"
# ...

# Terminal 3: Change model
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "change_model", "params": {"model_id": "yolov11x-640"}}'

# Terminal 2: Ahora debería mostrar (después del restart):
# "yolov11x-640"  ✅
# "yolov11x-640"
# ...

# Terminal 1: Verificar logs
# restart_completed ✅
# change_model_completed ✅
# join_restart_completed ✅ (nuevo log)
# pipeline_join_start (rejoin exitoso) ✅
# NO shutdown_cleanup_start ✅ (proceso sigue corriendo)
```

### Test 2: Múltiples cambios de modelo

```bash
# Cambiar modelo varias veces
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "change_model", "params": {"model_id": "yolov11n-640"}}'

# Wait 10 seconds

mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "change_model", "params": {"model_id": "yolov11x-640"}}'

# Wait 10 seconds

mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "change_model", "params": {"model_id": "yolov8x-640"}}'

# Verificar en terminal 2 que model_id cambia en cada restart:
# "yolov11n-640" → "yolov11x-640" → "yolov8x-640"
```

### Test 3: Verificar restart detection logs

```bash
# En logs del processor, buscar:

# Antes de restart:
# event: "pipeline_join_start", pipeline_id: 140123456789

# Después de restart:
# event: "pipeline_join_returned"
# event: "join_waiting_restart", detection_method: "pipeline_changed"
# event: "join_restart_completed", new_pipeline_id: 140987654321  ← Nuevo ID!
# event: "pipeline_join_start", pipeline_id: 140987654321  ← Rejoin con nuevo ID
```

---

## Diseño Explicado

### Pattern: Reference-Based Dynamic Configuration

**Filosofía:**
Para componentes que **persisten entre reconfigurations** (como el sink), pasar **referencias** en vez de **valores** permite que vean cambios dinámicos sin recrearse.

```python
# ❌ Anti-pattern: Value capture
class Sink:
    def __init__(self, value):
        self.value = value  # Captura valor en construcción

    def use(self):
        return self.value  # Nunca cambia

# ✅ Pattern: Reference-based
class Sink:
    def __init__(self, config):
        self.config = config  # Referencia al contenedor

    def use(self):
        return self.config.value  # Lookup dinámico
```

**Aplicado a NVR:**
- `MQTTDetectionSink` persiste entre restarts (evita reconexión MQTT)
- Guarda referencia a `config` (no copia de `model_id`)
- Cada evento hace lookup de `config.model_id` → ve cambios

**Trade-offs:**
- ✅ Simplicidad: No necesita recrear sink en restart
- ✅ Performance: Evita reconexión MQTT
- ⚠️ Coupling: Sink depende de estructura de config (pero es estable)

### Pattern: Dual-Condition Restart Detection

**Filosofía:**
Para sincronización entre threads, usar **redundancia en detección** elimina race conditions sin locks complejos.

```python
# ❌ Single condition (race-prone)
if self._is_restarting:
    continue  # Puede fallar si flag cambia antes de check

# ✅ Dual condition (race-proof)
is_restart = (
    self._is_restarting or  # Primary signal
    self.pipeline is not current_pipeline  # Backup signal
)
```

**Beneficio:**
- Flag puede tener race condition → referencia detecta cambio de objeto
- Referencia puede no cambiar en algunos casos → flag lo detecta
- Combinación es **robust** contra timing issues

---

## Arquitectura Actualizada

### Component Lifecycle en Change Model

```
change_model command
    ↓
_handle_change_model()
    ├─ Update config.model_id = "yolov11x-640"
    ├─ publish_status("reconfiguring")
    └─ _handle_restart()
           ├─ _is_restarting = True
           ├─ pipeline.terminate()
           ├─ pipeline = NEW InferencePipeline(model_id="yolov11x-640")
           │     └─ on_prediction=self.mqtt_sink  ← REUSA SINK!
           ├─ pipeline.start()
           ├─ publish_status("running")
           └─ _is_restarting = False
                  ↓
join() loop detecta restart
    ├─ current_pipeline.join() returns
    ├─ Detect: self.pipeline != current_pipeline  ← Pipeline cambió!
    ├─ Wait for _is_restarting = False
    └─ continue → rejoin new pipeline
           ↓
mqtt_sink.__call__() con nuevo frame
    └─ model_id = self.config.model_id  ← Lee "yolov11x-640"!
```

**Componentes que persisten:**
- ✅ `mqtt_sink` - Reusado (conexión MQTT persiste)
- ✅ `mqtt_client` - Reusado
- ✅ `control_plane` - Reusado
- ✅ `config` - Actualizado (no recreado)

**Componentes recreados:**
- 🔄 `pipeline` - Nuevo objeto InferencePipeline
- 🔄 `watchdog` - Nuevo objeto BasePipelineWatchDog

---

## Referencias

- **mqtt_sink.py:62-72** - Constructor con config reference
- **mqtt_sink.py:169** - Dynamic model_id lookup
- **processor.py:84-90** - Sink creation con config
- **processor.py:264-331** - Dual-condition join loop
- **processor.py:814-883** - change_model handler
- **DYNAMIC_ORCHESTRATION_SUMMARY.md** - Overall architecture

---

**Co-Authored-By:** Gaby <noreply@visiona.com>
