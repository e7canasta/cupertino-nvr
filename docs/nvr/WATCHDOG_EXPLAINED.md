# InferencePipeline Watchdog - Qué Es y Por Qué No Lo Usamos

## Qué Es

**Watchdog** es un monitor de observabilidad built-in de InferencePipeline. Recolecta métricas de performance en tiempo real.

### Métricas que Recolecta

```python
@dataclass
class PipelineStateReport:
    video_source_status_updates: List[StatusUpdate]  # Errores de conexión RTSP, etc
    latency_reports: List[LatencyMonitorReport]      # Latencias por stream
    inference_throughput: float                       # FPS del modelo (no de video)
    sources_metadata: List[SourceMetadata]            # Info de streams

@dataclass
class LatencyMonitorReport:
    source_id: int
    frame_decoding_latency: float  # Tiempo de decodificar frame (ms)
    inference_latency: float        # Tiempo de inferencia pura (ms)
    e2e_latency: float              # End-to-end (decode → predict) (ms)
```

### Cómo Funciona

```python
from inference import InferencePipeline
from inference.core.interfaces.stream.watchdog import BasePipelineWatchDog

# Crear watchdog
watchdog = BasePipelineWatchDog()

# Pasarlo a pipeline
pipeline = InferencePipeline.init(
    video_reference=streams,
    model_id="yolov8x-640",
    on_prediction=sink,
    watchdog=watchdog,  # ← InferencePipeline lo usa internamente
)

pipeline.start()

# Después (en cualquier momento)
report = watchdog.get_report()

print(f"FPS de inferencia: {report.inference_throughput}")
print(f"Latencia promedio: {report.latency_reports[0].e2e_latency * 1000} ms")
```

**Internamente, InferencePipeline llama a:**
- `watchdog.on_model_inference_started(frames)` - Antes de inferir
- `watchdog.on_model_prediction_ready(frames)` - Después de inferir
- `watchdog.on_status_update(status)` - Cuando hay errores RTSP, etc

El watchdog acumula estas métricas en buffers circulares (últimos 64 frames).

---

## Por Qué NO Lo Estamos Usando (Actualmente)

### 1. Lo Habilitamos Pero NO Consultamos

**En nuestro código actual:**
```python
# processor/config.py
enable_watchdog: bool = True  # ✅ Habilitado por default

# processor/processor.py
if self.config.enable_watchdog:
    self.watchdog = BasePipelineWatchDog()  # ✅ Se crea

self.pipeline = InferencePipeline.init(
    watchdog=self.watchdog,  # ✅ Se pasa
    ...
)
```

**Problema:** Nunca llamamos `self.watchdog.get_report()` 🤦

El watchdog está recolectando métricas pero **no las usamos para nada**:
- ❌ No las logueamos
- ❌ No las publicamos via MQTT
- ❌ No las exponemos via comando STATUS

**Es como tener un termómetro pegado pero nunca mirarlo.**

---

### 2. No Hay Comando METRICS

En Adeline tienen comando `METRICS` que retorna el report del watchdog:

```python
# Adeline
def _handle_metrics(self):
    if self.watchdog:
        report = self.watchdog.get_report()
        # Publish via MQTT
        self.control_plane.publish_metrics(report)
```

**Nosotros NO tenemos esto.** Solo tenemos PAUSE/RESUME/STOP/STATUS.

---

### 3. No Publicamos en DetectionEvent

Podríamos agregar métricas a cada evento de detección:

```python
@dataclass
class DetectionEvent:
    source_id: int
    frame_id: int
    detections: List[Detection]
    fps: Optional[float]         # ← Actualmente None
    latency_ms: Optional[float]  # ← Actualmente None
```

**Actualmente seteamos estos a None:**
```python
# mqtt_sink.py
return DetectionEvent(
    ...
    fps=None,  # ← Podríamos obtener de watchdog
    latency_ms=None,  # ← Podríamos obtener de watchdog
)
```

---

## Por Qué DEBERÍAMOS Usarlo

### Use Case 1: Monitoring de Performance

```bash
# Via comando MQTT
mosquitto_pub -t "nvr/control/commands" -m '{"command": "metrics"}'

# Respuesta
{
  "inference_throughput": 28.5,  # FPS de inferencia (no video)
  "latency_reports": [
    {
      "source_id": 0,
      "frame_decoding_latency": 0.015,  # 15ms decode
      "inference_latency": 0.032,        # 32ms inferencia
      "e2e_latency": 0.047               # 47ms total
    }
  ],
  "video_source_status_updates": [
    "RTSP stream 3 reconnecting..."
  ]
}
```

**Beneficio:** Visibility de si el sistema está performando bien o tiene bottlenecks.

---

### Use Case 2: Alertas de Degradación

```python
# En un loop periódico (cada 10 segundos)
def _monitor_performance(self):
    report = self.watchdog.get_report()

    # Alert si FPS baja
    if report.inference_throughput < 10:
        logger.warning(f"⚠️ Throughput degraded: {report.inference_throughput} FPS")
        self.control_plane.publish_alert("low_throughput")

    # Alert si latencia sube
    avg_latency = sum(r.e2e_latency for r in report.latency_reports) / len(report.latency_reports)
    if avg_latency > 0.2:  # 200ms
        logger.warning(f"⚠️ High latency: {avg_latency * 1000} ms")
```

**Beneficio:** Detectar problemas antes de que el usuario se queje.

---

### Use Case 3: Debugging de Latencia

Cuando un stream está lagueado:

```python
report = self.watchdog.get_report()

for stream_report in report.latency_reports:
    print(f"Stream {stream_report.source_id}:")
    print(f"  Decode: {stream_report.frame_decoding_latency * 1000:.1f} ms")
    print(f"  Inference: {stream_report.inference_latency * 1000:.1f} ms")
    print(f"  Total: {stream_report.e2e_latency * 1000:.1f} ms")
```

**Output:**
```
Stream 0:
  Decode: 15.2 ms
  Inference: 32.1 ms  ← Bottleneck!
  Total: 47.3 ms

Stream 1:
  Decode: 14.8 ms
  Inference: 180.5 ms  ← ¡Problema! Mucho más lento
  Total: 195.3 ms
```

**Beneficio:** Identificar cuál stream o qué parte (decode vs inference) es el bottleneck.

---

### Use Case 4: Incluir Métricas en Eventos

```python
class MQTTDetectionSink:
    def __init__(self, mqtt_client, watchdog):
        self.watchdog = watchdog  # ← Pasar watchdog

    def __call__(self, predictions, video_frame):
        # Obtener métricas actuales
        report = self.watchdog.get_report() if self.watchdog else None

        fps = report.inference_throughput if report else None
        latency_ms = None
        if report:
            # Buscar latencia del stream actual
            for r in report.latency_reports:
                if r.source_id == video_frame.source_id:
                    latency_ms = r.e2e_latency * 1000
                    break

        event = DetectionEvent(
            ...
            fps=fps,           # ← Ahora tiene valor!
            latency_ms=latency_ms,  # ← Ahora tiene valor!
        )
```

**Beneficio:** Cada evento MQTT incluye métricas de performance. Útil para dashboards.

---

## Cómo Deberíamos Usarlo

### Opción 1: Comando METRICS (Recomendado)

```python
# En processor.py
def _setup_control_commands(self):
    registry.register('pause', self._handle_pause)
    registry.register('resume', self._handle_resume)
    registry.register('stop', self._handle_stop)
    registry.register('status', self._handle_status)
    registry.register('metrics', self._handle_metrics)  # ← Nuevo

def _handle_metrics(self):
    """Handle METRICS command"""
    if self.watchdog:
        report = self.watchdog.get_report()

        # Serializar a dict
        metrics = {
            "inference_throughput": report.inference_throughput,
            "latency_reports": [
                {
                    "source_id": r.source_id,
                    "frame_decoding_latency_ms": r.frame_decoding_latency * 1000 if r.frame_decoding_latency else None,
                    "inference_latency_ms": r.inference_latency * 1000 if r.inference_latency else None,
                    "e2e_latency_ms": r.e2e_latency * 1000 if r.e2e_latency else None,
                }
                for r in report.latency_reports
            ],
            "sources": [
                {"source_id": m.source_id, "fps": m.fps, "resolution": f"{m.width}x{m.height}"}
                for m in report.sources_metadata
            ],
            "errors": [
                {"source_id": u.source_id, "message": u.payload["message"]}
                for u in report.video_source_status_updates
                if u.severity == UpdateSeverity.ERROR
            ]
        }

        # Publicar via MQTT
        self.control_plane.publish(
            topic=f"{self.config.control_status_topic}/metrics",
            payload=json.dumps(metrics),
            qos=0,
            retain=False
        )

        logger.info("📊 Metrics published", extra={"metrics": metrics})
    else:
        logger.warning("⚠️ Watchdog not enabled")
```

**Uso:**
```bash
# Query metrics
mosquitto_pub -t "nvr/control/commands" -m '{"command": "metrics"}'

# Monitor metrics
mosquitto_sub -t "nvr/control/status/metrics"
```

---

### Opción 2: Logging Periódico

```python
# En processor.py
def start(self):
    # ... setup normal ...

    # Start metrics logging thread
    if self.watchdog:
        self._start_metrics_logging()

def _start_metrics_logging(self):
    """Log metrics every 10 seconds"""
    import threading
    import time

    def log_metrics():
        while self.is_running:
            time.sleep(10)

            if not self.is_running:
                break

            report = self.watchdog.get_report()
            logger.info(
                f"📊 Performance Metrics",
                extra={
                    "component": "processor",
                    "event": "metrics_snapshot",
                    "inference_throughput": report.inference_throughput,
                    "avg_latency_ms": sum(
                        r.e2e_latency * 1000 for r in report.latency_reports
                    ) / len(report.latency_reports) if report.latency_reports else None,
                }
            )

    thread = threading.Thread(target=log_metrics, daemon=True)
    thread.start()
```

**Beneficio:** Logs automáticos sin necesidad de query MQTT. Útil para debugging.

---

### Opción 3: Incluir en DetectionEvent (Más Overhead)

Ver "Use Case 4" arriba.

**Trade-off:**
- ✅ Métricas en cada evento (útil para dashboards)
- ❌ Overhead de llamar `get_report()` en cada frame (~microsegundos)
- ❌ MQTT payloads más grandes

**Recomendación:** NO hacer esto. Usar comando METRICS es mejor.

---

## Comparación con Adeline

| Feature | Cupertino NVR (Actual) | Adeline | Recomendación |
|---------|------------------------|---------|---------------|
| Watchdog habilitado | ✅ | ✅ | ✅ Keep |
| Comando METRICS | ❌ | ✅ | ✅ Implementar |
| Logging periódico | ❌ | ✅ | ✅ Implementar |
| Métricas en eventos | ❌ | ❌ | ❌ No necesario |
| Alert de degradación | ❌ | ⚠️ Básico | 🟡 Considerar |

---

## Recomendación Final

### Quick Win 1: Comando METRICS (30 minutos)

Implementar `_handle_metrics()` para exponer watchdog data via MQTT.

**Beneficio:** Visibility inmediata de performance sin cambios mayores.

**Complejidad:** Baja (solo agregar handler + serialización)

---

### Quick Win 2: Logging Periódico (15 minutos)

Log automático de métricas cada 10-30 segundos.

**Beneficio:** Debugging más fácil (métricas en logs)

**Complejidad:** Muy baja (thread daemon simple)

---

### Future Enhancement: Alertas (1-2 horas)

Monitor de degradación con thresholds configurables.

**Beneficio:** Detectar problemas proactivamente

**Complejidad:** Media (necesita config de thresholds + lógica de alertas)

---

## Conclusión

**Pregunta de Ernesto:** "¿Por qué no lo usamos?"

**Respuesta:** Lo habilitamos pero nunca consultamos. Es como tener un speedometer pero nunca mirar.

**Acción recomendada:**
1. Implementar comando METRICS (quick win)
2. Agregar logging periódico (quick win)
3. Considerar alertas después (si hay necesidad)

**ROI:**
- Tiempo: 45 minutos (ambos quick wins)
- Beneficio: Visibility de performance + debugging más fácil
- Sin impacto en performance existente (watchdog ya está corriendo)

---

**Filosofía Blues:** "El watchdog ya está tocando, solo necesitamos escuchar" 🎸

---

*Documentado: 2025-10-25*
*Para: cupertino-nvr*
