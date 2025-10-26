# Structured Logging

Cupertino NVR usa **structured logging en JSON** para máxima observability y compatibilidad con sistemas de agregación de logs como Elasticsearch, Loki, Grafana, etc.

## Overview

Los logs estructurados permiten:
- **Queries complejos**: Filtrar por component, event, command, etc.
- **Correlación de eventos**: Seguir flujo de un comando end-to-end
- **Dashboards**: Visualizar métricas y eventos en tiempo real
- **Alerting**: Crear alertas basadas en eventos específicos
- **Debugging**: Encontrar errores con contexto completo

## Formatos de Log

### 1. Human-Readable (Desarrollo)

**Por defecto** para desarrollo local:

```bash
uv run cupertino-nvr processor --model yolov11s-640 --streams 3 --enable-control
```

**Output:**
```
2025-10-25 03:35:00 | INFO     | control_plane        | command_received     | MQTT Command Received: 'pause' on topic: nvr/control/commands
2025-10-25 03:35:00 | INFO     | control_plane        | command_executing    | Command pause executing
2025-10-25 03:35:00 | INFO     | control_plane        | command_completed    | Command pause completed
```

### 2. JSON (Producción)

**Recomendado** para producción y log aggregation:

```bash
# Via flag
uv run cupertino-nvr processor --model yolov11s-640 --streams 3 --enable-control --json-logs

# Via env
JSON_LOGS=true uv run cupertino-nvr processor --model yolov11s-640 --streams 3 --enable-control
```

**Output:**
```json
{"timestamp":"2025-10-25T03:35:00.123456","level":"INFO","logger":"cupertino_nvr.processor.control_plane","message":"MQTT Command Received: 'pause' on topic: nvr/control/commands","component":"control_plane","event":"mqtt_received","command":"pause","mqtt_topic":"nvr/control/commands","payload":"{\"command\": \"pause\"}"}
{"timestamp":"2025-10-25T03:35:00.234567","level":"INFO","logger":"cupertino_nvr.processor.control_plane","message":"Command pause received","component":"control_plane","event":"command_received","command":"pause","command_status":"received"}
{"timestamp":"2025-10-25T03:35:00.345678","level":"INFO","logger":"cupertino_nvr.processor.control_plane","message":"Command pause executing","component":"control_plane","event":"command_executing","command":"pause","command_status":"executing"}
{"timestamp":"2025-10-25T03:35:00.456789","level":"INFO","logger":"cupertino_nvr.processor.mqtt_sink","message":"MQTT sink paused - no events will be published","component":"mqtt_sink","event":"sink_paused"}
{"timestamp":"2025-10-25T03:35:00.567890","level":"INFO","logger":"cupertino_nvr.processor.control_plane","message":"MQTT published: nvr/control/status","component":"control_plane","event":"mqtt_published","mqtt_topic":"nvr/control/status","status":"paused","retained":true}
{"timestamp":"2025-10-25T03:35:00.678901","level":"INFO","logger":"cupertino_nvr.processor.control_plane","message":"Command pause completed","component":"control_plane","event":"command_completed","command":"pause","command_status":"completed"}
```

## Estructura de Log Events

Todos los logs tienen campos base + campos específicos por evento:

### Campos Base

```json
{
  "timestamp": "2025-10-25T03:35:00.123456",  // ISO 8601 UTC
  "level": "INFO",                             // DEBUG, INFO, WARNING, ERROR
  "logger": "cupertino_nvr.processor.control_plane",
  "message": "Human readable message",
  "component": "control_plane",                // Component que generó el log
  "event": "command_received"                  // Tipo de evento
}
```

### Campos por Tipo de Evento

#### Command Events
```json
{
  "component": "control_plane",
  "event": "command_received",      // command_received, command_executing, command_completed, command_failed
  "command": "pause",                // pause, resume, stop, status
  "command_status": "received"       // received, executing, completed, failed
}
```

#### MQTT Events
```json
{
  "component": "control_plane",
  "event": "mqtt_published",         // mqtt_published, mqtt_received, mqtt_subscribed
  "mqtt_topic": "nvr/control/status",
  "qos": 1,
  "retained": true
}
```

#### State Changes
```json
{
  "component": "processor",
  "event": "state_changed",
  "old_state": "running",
  "new_state": "paused",
  "is_running": true,
  "is_paused": true
}
```

#### Error Events
```json
{
  "component": "control_plane",
  "event": "command_not_available",
  "command": "invalid",
  "error_type": "CommandNotAvailableError",
  "error_message": "Command 'invalid' not available",
  "available_commands": ["pause", "resume", "stop", "status"]
}
```

## Uso con Log Aggregation

### Elasticsearch

**1. Ship logs a Elasticsearch:**

```bash
# Con Filebeat
uv run cupertino-nvr processor --json-logs --enable-control 2>&1 | tee /var/log/nvr/processor.log

# filebeat.yml
filebeat.inputs:
  - type: log
    enabled: true
    paths:
      - /var/log/nvr/processor.log
    json.keys_under_root: true
    json.add_error_key: true

output.elasticsearch:
  hosts: ["localhost:9200"]
  index: "nvr-logs-%{+yyyy.MM.dd}"
```

**2. Queries en Kibana:**

```
# Todos los comandos PAUSE
component:control_plane AND event:command_received AND command:pause

# Errores en últimas 24h
level:ERROR AND timestamp:[now-24h TO now]

# Commands que fallaron
event:command_failed

# MQTT events para un topic específico
event:mqtt_published AND mqtt_topic:"nvr/control/status"

# Timeline de un comando específico
command:pause AND event:(command_received OR command_executing OR command_completed)
```

### Grafana Loki

**1. Ship logs a Loki:**

```bash
# Con Promtail
# promtail-config.yml
server:
  http_listen_port: 9080

clients:
  - url: http://localhost:3100/loki/api/v1/push

scrape_configs:
  - job_name: nvr_processor
    static_configs:
      - targets:
          - localhost
        labels:
          job: nvr_processor
          __path__: /var/log/nvr/processor.log
    pipeline_stages:
      - json:
          expressions:
            level: level
            component: component
            event: event
            command: command
      - labels:
          level:
          component:
          event:
```

**2. LogQL Queries:**

```logql
# Todos los comandos recibidos
{job="nvr_processor"} | json | event="command_received"

# Rate de comandos por minuto
rate({job="nvr_processor"} | json | event="command_received" [1m])

# Errores agrupados por component
sum by (component) (count_over_time({job="nvr_processor"} | json | level="ERROR" [5m]))

# Latencia de comandos (received → completed)
# (requiere parsing avanzado)
```

### Docker Logging

**Con Docker JSON driver:**

```bash
docker run \
  --log-driver=json-file \
  --log-opt max-size=10m \
  --log-opt max-file=3 \
  cupertino-nvr processor --json-logs --enable-control
```

**Con fluentd:**

```bash
docker run \
  --log-driver=fluentd \
  --log-opt fluentd-address=localhost:24224 \
  --log-opt tag="nvr.processor" \
  cupertino-nvr processor --json-logs --enable-control
```

## Análisis con jq

Para análisis local rápido, usa `jq`:

**Filtrar por component:**
```bash
cat processor.log | jq 'select(.component == "control_plane")'
```

**Contar eventos por tipo:**
```bash
cat processor.log | jq -r '.event' | sort | uniq -c
```

**Timeline de un comando:**
```bash
cat processor.log | jq 'select(.command == "pause") | {timestamp, event, command_status}'
```

**Errores con contexto:**
```bash
cat processor.log | jq 'select(.level == "ERROR") | {timestamp, component, event, error_type, error_message}'
```

**Rate de comandos por minuto:**
```bash
cat processor.log | jq -r 'select(.event == "command_received") | .timestamp' | awk -F: '{print $1":"$2}' | sort | uniq -c
```

## Dashboard Metrics

Eventos clave para dashboards:

### Command Metrics
- `command_received`: Counter por comando
- `command_completed`: Counter por comando
- `command_failed`: Counter por comando
- Latencia: `command_received` → `command_completed` (timestamp diff)

### MQTT Metrics
- `mqtt_published`: Counter por topic
- `mqtt_received`: Counter por topic
- `mqtt_subscribed`: Counter

### State Metrics
- `state_changed`: Counter + Last value por state
- `is_running`: Gauge (true/false)
- `is_paused`: Gauge (true/false)

### Error Metrics
- `level:ERROR`: Counter por component
- `event:command_not_available`: Counter
- `event:json_decode_error`: Counter

## Prometheus Exporter (Futuro)

Próximo paso: Exportar métricas a Prometheus desde logs estructurados:

```python
# prometheus_exporter.py
from prometheus_client import Counter, Gauge, Histogram

command_received = Counter('nvr_command_received_total', 'Commands received', ['command'])
command_duration = Histogram('nvr_command_duration_seconds', 'Command duration', ['command'])
pipeline_state = Gauge('nvr_pipeline_state', 'Pipeline state', ['state'])
```

## Comparación: JSON vs Human-Readable

| Feature | JSON Logs | Human-Readable |
|---------|-----------|----------------|
| **Parseable** | ✅ | ❌ |
| **Elasticsearch** | ✅ | ⚠️ (needs grok) |
| **Grafana Loki** | ✅ | ⚠️ (regex) |
| **Local Debug** | ⚠️ (usa jq) | ✅ |
| **Dashboard** | ✅ | ❌ |
| **Alerting** | ✅ | ❌ |
| **Performance** | ⚠️ (más CPU) | ✅ |

**Recomendación:**
- **Desarrollo**: Human-readable (default)
- **Staging/Production**: JSON logs
- **CI/CD**: JSON logs → Elasticsearch/Loki

## Environment Variables

```bash
# Log level
LOG_LEVEL=DEBUG  # DEBUG, INFO, WARNING, ERROR

# JSON format
JSON_LOGS=true   # true para JSON, false para human-readable

# Log file (opcional)
LOG_FILE=/var/log/nvr/processor.log  # Siempre JSON format
```

## Ejemplo Completo: Pause Command Flow

**Command:**
```bash
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "pause"}'
```

**Logs (JSON):**
```json
{"timestamp":"2025-10-25T03:35:00.123","level":"INFO","logger":"cupertino_nvr.processor.control_plane","message":"MQTT received: nvr/control/commands","component":"control_plane","event":"mqtt_received","command":"pause","mqtt_topic":"nvr/control/commands","payload":"{\"command\": \"pause\"}"}
{"timestamp":"2025-10-25T03:35:00.124","level":"INFO","logger":"cupertino_nvr.processor.control_plane","message":"Command pause received","component":"control_plane","event":"command_received","command":"pause","command_status":"received"}
{"timestamp":"2025-10-25T03:35:00.125","level":"INFO","logger":"cupertino_nvr.processor.control_plane","message":"MQTT published: nvr/control/status/ack","component":"control_plane","event":"mqtt_published","mqtt_topic":"nvr/control/status/ack","command":"pause","ack_status":"received"}
{"timestamp":"2025-10-25T03:35:00.126","level":"INFO","logger":"cupertino_nvr.processor.control_plane","message":"Command pause executing","component":"control_plane","event":"command_executing","command":"pause","command_status":"executing"}
{"timestamp":"2025-10-25T03:35:00.127","level":"INFO","logger":"cupertino_nvr.processor.mqtt_sink","message":"MQTT sink paused","component":"mqtt_sink","event":"sink_paused"}
{"timestamp":"2025-10-25T03:35:00.128","level":"INFO","logger":"cupertino_nvr.processor.mqtt_sink","message":"Pipeline stream paused","component":"processor","event":"stream_paused"}
{"timestamp":"2025-10-25T03:35:00.129","level":"INFO","logger":"cupertino_nvr.processor.control_plane","message":"MQTT published: nvr/control/status","component":"control_plane","event":"mqtt_published","mqtt_topic":"nvr/control/status","status":"paused","retained":true}
{"timestamp":"2025-10-25T03:35:00.130","level":"INFO","logger":"cupertino_nvr.processor.control_plane","message":"MQTT published: nvr/control/status/ack","component":"control_plane","event":"mqtt_published","mqtt_topic":"nvr/control/status/ack","command":"pause","ack_status":"completed"}
{"timestamp":"2025-10-25T03:35:00.131","level":"INFO","logger":"cupertino_nvr.processor.control_plane","message":"Command pause completed","component":"control_plane","event":"command_completed","command":"pause","command_status":"completed"}
```

**Timeline:** 8ms total (received → completed)

## Resources

- **JSON Logging Best Practices**: https://www.loggly.com/ultimate-guide/json-logging-best-practices/
- **Elasticsearch Index Design**: https://www.elastic.co/guide/en/elasticsearch/reference/current/index-modules.html
- **Grafana Loki LogQL**: https://grafana.com/docs/loki/latest/logql/
- **Structured Logging in Python**: https://docs.python.org/3/howto/logging-cookbook.html#implementing-structured-logging

