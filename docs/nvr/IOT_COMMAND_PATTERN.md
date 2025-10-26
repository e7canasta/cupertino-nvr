# IoT Command Pattern - MQTT Control Plane

## Filosofía

**Logs para máquinas, no humanos**
- Structured logging con `extra={}` fields
- Events con nombres consistentes (snake_case)
- Parseable por Elasticsearch, Loki, agentes de monitoreo
- No emojis, no mensajes narrativos en logs estructurados

**IoT ACK Pattern**
- ACK inmediato: "received"
- Estados intermedios: "restarting", "pausing", etc.
- ACK final: "completed" o "error"
- Status publicado: "running", "paused", "stopped", "error"

---

## Flujo de Comandos

### 1. Cliente → Broker (Comando MQTT)

```json
Topic: nvr/control/commands
Payload: {"command": "restart"}
```

### 2. Control Plane → ACK Inmediato

```json
Topic: nvr/control/status/ack
Payload: {
  "command": "restart",
  "ack_status": "received",
  "timestamp": "2025-10-25T06:15:30.123456",
  "client_id": "nvr_processor_control"
}
```

**Tiempo:** <100ms

### 3. Processor → Status Intermedio

```json
Topic: nvr/control/status
Payload: {
  "status": "restarting",
  "timestamp": "2025-10-25T06:15:30.200000",
  "client_id": "nvr_processor_control"
}
```

**Retained:** true (para nuevos suscriptores)

### 4. Processor → Ejecución

```
[Logs estructurados - para Elasticsearch]

{
  "timestamp": "2025-10-25T06:15:30.250000",
  "level": "INFO",
  "logger": "processor",
  "message": "RESTART command executing",
  "component": "processor",
  "event": "restart_command_start",
  "current_state": "running",
  "stream_count": 1,
  "model_id": "yolov11s-640"
}

{
  "timestamp": "2025-10-25T06:15:30.300000",
  "level": "INFO",
  "logger": "processor",
  "message": "Terminating current pipeline",
  "component": "processor",
  "event": "restart_pipeline_terminate_start"
}

{
  "timestamp": "2025-10-25T06:15:32.500000",
  "level": "INFO",
  "logger": "processor",
  "message": "Pipeline terminated",
  "component": "processor",
  "event": "restart_pipeline_terminated"
}

{
  "timestamp": "2025-10-25T06:15:32.600000",
  "level": "INFO",
  "logger": "processor",
  "message": "Recreating pipeline from current config",
  "component": "processor",
  "event": "restart_pipeline_recreate_start",
  "stream_count": 1,
  "model_id": "yolov11s-640",
  "max_fps": 0.1
}

... [20+ segundos reconectando streams RTSP] ...

{
  "timestamp": "2025-10-25T06:15:55.100000",
  "level": "INFO",
  "logger": "processor",
  "message": "RESTART completed successfully",
  "component": "processor",
  "event": "restart_completed",
  "new_state": "running",
  "stream_count": 1,
  "model_id": "yolov11s-640"
}
```

### 5. Processor → Status Final

```json
Topic: nvr/control/status
Payload: {
  "status": "running",
  "timestamp": "2025-10-25T06:15:55.150000",
  "client_id": "nvr_processor_control"
}
```

**Retained:** true

### 6. Control Plane → ACK Completado

```json
Topic: nvr/control/status/ack
Payload: {
  "command": "restart",
  "ack_status": "completed",
  "timestamp": "2025-10-25T06:15:55.200000",
  "client_id": "nvr_processor_control"
}
```

**Tiempo total:** ~25 segundos (depende de reconexión RTSP)

---

## Flujo en Caso de Error

### Error durante ejecución

```json
# Status
Topic: nvr/control/status
Payload: {
  "status": "error",
  "timestamp": "2025-10-25T06:15:35.000000",
  "client_id": "nvr_processor_control"
}

# ACK error
Topic: nvr/control/status/ack
Payload: {
  "command": "restart",
  "ack_status": "error",
  "message": "Failed to connect to RTSP stream",
  "timestamp": "2025-10-25T06:15:35.100000",
  "client_id": "nvr_processor_control"
}
```

**Log estructurado:**
```json
{
  "timestamp": "2025-10-25T06:15:35.000000",
  "level": "ERROR",
  "logger": "processor",
  "message": "RESTART failed",
  "component": "processor",
  "event": "restart_failed",
  "error_type": "ConnectionError",
  "error_message": "Failed to connect to RTSP stream",
  "new_state": "error"
}
```

---

## Monitoring con Elasticsearch

### Query: Find all restart events

```json
GET /logs-nvr-*/_search
{
  "query": {
    "bool": {
      "must": [
        {"term": {"component": "processor"}},
        {"wildcard": {"event": "restart_*"}}
      ]
    }
  },
  "sort": [{"timestamp": "asc"}]
}
```

### Query: Find failed restarts

```json
GET /logs-nvr-*/_search
{
  "query": {
    "bool": {
      "must": [
        {"term": {"component": "processor"}},
        {"term": {"event": "restart_failed"}}
      ]
    }
  }
}
```

### Query: Average restart duration

```json
GET /logs-nvr-*/_search
{
  "query": {
    "term": {"event": "restart_command_start"}
  },
  "aggs": {
    "avg_duration": {
      "avg": {
        "script": {
          "source": """
            def start = doc['timestamp'].value;
            def completed = params._source.find(e -> e.event == 'restart_completed');
            if (completed != null) {
              return completed.timestamp - start;
            }
            return null;
          """
        }
      }
    }
  }
}
```

---

## Testing de Comandos Dinámicos

### Test: CHANGE_MODEL (Orquestación para habitación de riesgo)

```bash
# Escenario: Habitación 2 detectó caída, cambiar a modelo de alta precisión

# Terminal 1: Processor inicial (modelo ligero)
uv run cupertino-nvr processor \
  --streams 0,1,2,3 \
  --model yolov11n-640 \
  --max-fps 0.1 \
  --enable-control

# Terminal 2: Cambiar a modelo pesado
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "change_model", "params": {"model_id": "yolov11x-640"}}'
```

**Secuencia esperada:**
```json
Status: "running" → "reconfiguring" → "running"
ACK: "received" → "completed"
Logs:
  - change_model_command_start (old: yolov11n-640, new: yolov11x-640)
  - change_model_config_updated
  - restart_command_start
  - restart_completed
  - change_model_completed
```

### Test: SET_FPS (Aumentar precisión)

```bash
# Aumentar FPS de 0.1 a 1.0 para análisis detallado
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "set_fps", "params": {"max_fps": 1.0}}'
```

**Logs estructurados:**
```json
{"event": "set_fps_command_start", "old_fps": 0.1, "new_fps": 1.0}
{"event": "set_fps_config_updated", "new_fps": 1.0}
{"event": "restart_command_start", ...}
{"event": "set_fps_completed", "old_fps": 0.1, "new_fps": 1.0}
```

### Test: ADD_STREAM (Agregar habitación)

```bash
# Agregar habitación 8 al monitoreo
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "add_stream", "params": {"source_id": 8}}'
```

**Stream URI generado automáticamente:**
```
Internamente: stream_uri = f"{stream_server}/8"
→ rtsp://go2rtc-server/8
→ go2rtc resuelve a URL real de cámara habitación 8
```

**Resultado:**
- Pipeline se reinicia con 5 streams (0,1,2,3,8)
- Detecciones empiezan a publicarse para `source_id: 8`
- URI real manejada por go2rtc proxy (ver docs/nvr/GO2RTC_PROXY_ARCHITECTURE.md)

### Test: REMOVE_STREAM (Quitar habitación)

```bash
# Quitar habitación 2 del monitoreo
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "remove_stream", "params": {"source_id": 2}}'
```

**Resultado:**
- Pipeline se reinicia con 3 streams (0,1,3)
- Detecciones de `source_id: 2` dejan de publicarse

### Test: Error Handling (Rollback)

```bash
# Intentar cambiar a modelo inválido
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "change_model", "params": {"model_id": "invalid-model"}}'
```

**Resultado esperado:**
```json
ACK: "error"
Status: "error"
Logs: {"event": "change_model_failed", "rolled_back_to": "yolov11x-640"}
```

**Config debe permanecer sin cambios** (rollback exitoso).

---

## Testing del Comando RESTART

### Test 1: Restart Exitoso

```bash
# Terminal 1: Start processor
uv run cupertino-nvr processor --streams 0 --enable-control --max-fps 0.1

# Terminal 2: Subscribe a status
mosquitto_sub -h localhost -t "nvr/control/status" -v

# Terminal 3: Subscribe a ACKs
mosquitto_sub -h localhost -t "nvr/control/status/ack" -v

# Terminal 4: Enviar comando
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "restart"}'
```

**Secuencia esperada en Terminal 2 (status):**
```
nvr/control/status {"status": "running", ...}         # Estado inicial
nvr/control/status {"status": "restarting", ...}      # Restart inicia
nvr/control/status {"status": "running", ...}         # Restart completado
```

**Secuencia esperada en Terminal 3 (ACKs):**
```
nvr/control/status/ack {"command": "restart", "ack_status": "received", ...}
nvr/control/status/ack {"command": "restart", "ack_status": "completed", ...}
```

### Test 2: Restart Durante Restart (Idempotencia)

```bash
# Enviar dos comandos seguidos
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "restart"}'
sleep 1
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "restart"}'
```

**Resultado esperado:**
- Primer comando: Se ejecuta normalmente
- Segundo comando: Se rechaza con log:
  ```json
  {
    "event": "restart_rejected",
    "reason": "restart_in_progress"
  }
  ```

### Test 3: Restart con Error (Stream no disponible)

```bash
# Start processor con stream inexistente
uv run cupertino-nvr processor \
  --stream-server rtsp://invalid.host \
  --streams 999 \
  --enable-control

# Enviar restart
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "restart"}'
```

**Resultado esperado:**
```
Status: "restarting" → "error"
ACK: "received" → "error"
Log: event="restart_failed", error_type="ConnectionError"
```

---

## Patterns para Comandos Futuros

### Comando con Parámetros: `change_model`

```python
def _handle_change_model(self, new_model_id: str):
    """Handle CHANGE_MODEL command"""
    logger.info(
        "CHANGE_MODEL command executing",
        extra={
            "component": "processor",
            "event": "change_model_command_start",
            "old_model_id": self.config.model_id,
            "new_model_id": new_model_id
        }
    )

    # Publish intermediate status
    if self.control_plane:
        self.control_plane.publish_status("reconfiguring")

    try:
        # Update config
        old_model = self.config.model_id
        self.config.model_id = new_model_id

        # Restart pipeline (internal primitive)
        self._restart_pipeline()

        logger.info(
            "CHANGE_MODEL completed successfully",
            extra={
                "component": "processor",
                "event": "change_model_completed",
                "old_model_id": old_model,
                "new_model_id": new_model_id
            }
        )

        # Publish final status
        if self.control_plane:
            self.control_plane.publish_status("running")

    except Exception as e:
        # Rollback on error
        self.config.model_id = old_model

        logger.error(
            "CHANGE_MODEL failed",
            extra={
                "component": "processor",
                "event": "change_model_failed",
                "error_type": type(e).__name__,
                "error_message": str(e),
                "rolled_back_to": old_model
            },
            exc_info=True
        )

        if self.control_plane:
            self.control_plane.publish_status("error")

        raise
```

**Registro en Control Plane:**
```python
# control_plane.py - _on_message()
command_data = json.loads(payload)
command = command_data.get('command', '')
params = command_data.get('params', {})

if command == 'change_model':
    handler = lambda: self.command_registry.handlers['change_model'](
        params.get('model_id')
    )
    handler()
```

**Uso:**
```bash
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "change_model", "params": {"model_id": "yolov11x-640"}}'
```

---

## Checklist para Nuevos Comandos

Al implementar un nuevo comando, asegurar:

- [ ] **Structured logging**: Todos los logs con `extra={"component": ..., "event": ...}`
- [ ] **Event naming**: snake_case, consistente (ej: `{command}_command_start`, `{command}_completed`, `{command}_failed`)
- [ ] **IoT status**: Publicar estados intermedios ("reconfiguring", "restarting", etc.)
- [ ] **Error handling**: Try/catch con rollback si es necesario
- [ ] **Idempotencia**: Rechazar comando si ya está en progreso
- [ ] **ACK automático**: Control Plane maneja ACKs, handler solo ejecuta
- [ ] **Final status**: Publicar "running" o "error" al terminar
- [ ] **Re-raise exception**: Para que Control Plane publique ACK error
- [ ] **Testing**: Caso exitoso + caso error + caso idempotencia

---

## Referencias

- `cupertino_nvr/processor/processor.py:557-732` - Implementación de `_handle_restart()`
- `cupertino_nvr/processor/control_plane.py:174-233` - IoT ACK pattern
- `cupertino_nvr/logging_utils.py` - Structured logging setup
- `docs/nvr/BLUEPRINT_INFERENCE_PIPELINE_CONTROL.md` - Control plane architecture

---

**Versión:** 1.0
**Fecha:** 2025-10-25
**Autor:** Visiona Team
