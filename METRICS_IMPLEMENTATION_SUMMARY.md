# Metrics Implementation Summary

## Lo Que Implementamos

### 1. Dos Canales de Métricas

**Canal 1: On-Demand (Comando METRICS)**
```bash
# Request
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "metrics"}'

# Response (nvr/control/status/metrics)
{
  "timestamp": "2025-10-25T...",
  "inference_throughput": 28.5,
  "latency_reports": [
    {
      "source_id": 0,
      "frame_decoding_latency_ms": 15.2,
      "inference_latency_ms": 32.1,
      "e2e_latency_ms": 47.3
    }
  ],
  "sources_metadata": [
    {
      "source_id": 0,
      "fps": 30.0,
      "resolution": "640x480"
    }
  ],
  "status_updates": [
    {
      "source_id": 0,
      "severity": "INFO",
      "message": "Stream connected"
    }
  ]
}
```

**Canal 2: Periódico (Auto-Reporting)**
```bash
# Monitor (nvr/status/metrics - retained)
mosquitto_sub -h localhost -t "nvr/status/metrics" -v

# Output cada 10 segundos (default):
{
  "timestamp": "2025-10-25T...",
  "inference_throughput": 28.5,
  "avg_latency_ms": 47.3,
  "sources": [
    {"source_id": 0, "latency_ms": 45.2},
    {"source_id": 1, "latency_ms": 49.4}
  ]
}
```

---

## Arquitectura

### Decisiones de Diseño

**1. Processor = Reporter (NO Decision Maker)**
- ✅ Processor publica métricas periódicamente
- ❌ Processor NO decide si hay problemas
- ✅ Orquestador superior (dashboard/alerting) analiza métricas

**2. Separación de Canales**
- `nvr/control/status/metrics` - Respuestas a comandos (control plane)
- `nvr/status/metrics` - Auto-reporting (observability channel, separado de control)

**3. Dos Niveles de Detalle**
- Comando: Full report (debug on-demand)
- Periódico: Lightweight (solo throughput + latencias)
- Razón: Periódico puede ser alta frecuencia, no saturar MQTT

---

## Archivos Modificados

### Config
**`cupertino_nvr/processor/config.py`**
```python
# Nuevo
metrics_reporting_interval: int = 10  # segundos (0 = disabled)
metrics_topic: str = "nvr/status/metrics"
```

### Processor
**`cupertino_nvr/processor/processor.py`**
- `_handle_metrics()` - Handler para comando METRICS
- `_get_full_metrics_report()` - Serializa reporte completo
- `_get_lightweight_metrics()` - Serializa lightweight
- `_publish_metrics()` - Helper para publicar
- `_start_metrics_reporting_thread()` - Thread periódico
- Registro de comando 'metrics' en `_setup_control_commands()`
- Start del thread en `start()` (después de pipeline.start())

### CLI
**`cupertino_nvr/cli.py`**
```bash
--metrics-interval 10  # Default 10s, 0 = disabled
```

---

## Uso

### Comando (On-Demand)

```bash
# Terminal 1: Start processor con control
uv run cupertino-nvr processor --model yolov11s-640 --streams 0 --enable-control

# Terminal 2: Monitor respuestas
mosquitto_sub -h localhost -t "nvr/control/status/metrics" -v

# Terminal 3: Query metrics
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "metrics"}'
```

### Periódico (Auto-Reporting)

```bash
# Terminal 1: Start processor
uv run cupertino-nvr processor --model yolov11s-640 --streams 0 --metrics-interval 10

# Terminal 2: Monitor métricas (recibirás update cada 10s)
mosquitto_sub -h localhost -t "nvr/status/metrics" -v
```

### Deshabilitar Reporting

```bash
uv run cupertino-nvr processor --model yolov11s-640 --streams 0 --metrics-interval 0
```

---

## Contenido de Métricas

### Full Report (Comando METRICS)

```json
{
  "timestamp": "2025-10-25T04:40:00.123456",
  "inference_throughput": 28.5,
  "latency_reports": [
    {
      "source_id": 0,
      "frame_decoding_latency_ms": 15.2,
      "inference_latency_ms": 32.1,
      "e2e_latency_ms": 47.3
    }
  ],
  "sources_metadata": [
    {
      "source_id": 0,
      "fps": 30.0,
      "resolution": "640x480"
    }
  ],
  "status_updates": [
    {
      "source_id": 0,
      "severity": "INFO",
      "message": "Stream connected"
    }
  ]
}
```

**Campos:**
- `inference_throughput` - FPS de inferencia (cuántos frames/s procesa el modelo)
- `latency_reports[]` - Latencias por stream:
  - `frame_decoding_latency_ms` - Tiempo de decodificar frame
  - `inference_latency_ms` - Tiempo de inferencia pura
  - `e2e_latency_ms` - End-to-end (decode → predict)
- `sources_metadata[]` - Metadata de streams (FPS real, resolución)
- `status_updates[]` - Errores RTSP, reconexiones, etc

### Lightweight (Periódico)

```json
{
  "timestamp": "2025-10-25T04:40:00.123456",
  "inference_throughput": 28.5,
  "avg_latency_ms": 47.3,
  "sources": [
    {"source_id": 0, "latency_ms": 45.2},
    {"source_id": 1, "latency_ms": 49.4}
  ]
}
```

**Campos:**
- `inference_throughput` - FPS de inferencia
- `avg_latency_ms` - Latencia promedio across all streams
- `sources[]` - Latencia por stream (e2e)

---

## Diferencias: Full vs Lightweight

| Feature | Full (Comando) | Lightweight (Periódico) |
|---------|----------------|-------------------------|
| **Throughput** | ✅ | ✅ |
| **Latencias detalladas** | ✅ (decode, inference, e2e) | ❌ (solo e2e) |
| **Latencia promedio** | ❌ | ✅ |
| **Sources metadata** | ✅ (FPS, resolución) | ❌ |
| **Status updates** | ✅ (errores RTSP) | ❌ |
| **Payload size** | Grande (~500 bytes) | Pequeño (~150 bytes) |
| **Frecuencia** | On-demand | Cada 10s (default) |
| **Retained** | ❌ | ✅ |

---

## Performance Impact

**Thread periódico:**
- CPU: Despreciable (<0.01%)
- Sleep entre iteraciones (no busy-wait)
- Daemon thread (termina automáticamente)

**Watchdog overhead:**
- Ya estaba habilitado (no nuevo overhead)
- Solo agregamos serialización JSON (~microsegundos)

**MQTT overhead:**
- Lightweight: ~150 bytes cada 10s = 15 bytes/s
- Full (on-demand): Solo cuando se pide

---

## Testing

### Test Script

```bash
./test_metrics.sh
```

### Manual Testing

**1. Verificar periódico funciona:**
```bash
# Start processor
uv run cupertino-nvr processor --model yolov11s-640 --streams 0 --metrics-interval 5

# Monitor (deberías ver mensajes cada 5s)
mosquitto_sub -h localhost -t "nvr/status/metrics" -v
```

**2. Verificar comando funciona:**
```bash
# Start processor con control
uv run cupertino-nvr processor --model yolov11s-640 --streams 0 --enable-control

# Monitor respuestas
mosquitto_sub -h localhost -t "nvr/control/status/metrics" -v

# Query (en otra terminal)
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "metrics"}'
```

**3. Verificar deshabilitar funciona:**
```bash
# Start sin reporting
uv run cupertino-nvr processor --model yolov11s-640 --streams 0 --metrics-interval 0

# No deberían aparecer mensajes en:
mosquitto_sub -h localhost -t "nvr/status/metrics" -v
```

---

## Logs Esperados

### Startup (Periódico Habilitado)

```
2025-10-25 XX:XX:XX | INFO | processor | pipeline_started | ✅ Pipeline started successfully
2025-10-25 XX:XX:XX | INFO | processor | metrics_reporting_started | 📊 Metrics reporting started (interval: 10s)
```

### Startup (Periódico Deshabilitado)

```
2025-10-25 XX:XX:XX | INFO | processor | metrics_reporting_disabled | Metrics reporting disabled (interval = 0)
```

### Comando METRICS Recibido

```
2025-10-25 XX:XX:XX | INFO | processor | metrics_query | 📊 METRICS query
2025-10-25 XX:XX:XX | INFO | processor | metrics_published | ✅ METRICS report published
```

### Periódico (Debug Level)

```
2025-10-25 XX:XX:XX | DEBUG | processor | metrics_periodic | 📊 Periodic metrics published
```

---

## Próximos Pasos (Opcional)

### 1. Dashboard Integration
Consumir `nvr/status/metrics` en dashboard (Grafana, custom UI).

### 2. Alerting
Crear servicio que consume metrics y alerta si:
- `inference_throughput` < threshold
- `avg_latency_ms` > threshold

### 3. Métricas Adicionales
Agregar al watchdog report:
- Memory usage
- CPU usage
- Dropped frames count

---

## Filosofía de Diseño

✅ **Processor = Reporter (NO Decision Maker)**
- Processor solo publica datos
- Orquestador superior decide qué es "malo"

✅ **Separation of Concerns**
- Control plane: Comandos
- Observability channel: Métricas periódicas

✅ **Two Levels of Detail**
- On-demand: Full debug info
- Periodic: Lightweight para monitoring continuo

✅ **Pragmatismo > Purismo**
- Reusa watchdog existente (no re-inventar)
- Simple JSON serialization (no Protobuf)
- Thread daemon simple (no frameworks complejos)

---

*Implementado: 2025-10-25*
*Por: Ernesto + Gaby*
