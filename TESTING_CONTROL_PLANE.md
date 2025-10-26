# Testing MQTT Control Plane

Guía completa para probar el control plane con todos los logs y ACKs visibles.

## Setup de Testing

### Terminal 1: Processor con Control Plane

```bash
uv run cupertino-nvr processor \
    --model yolov11s-640 \
    --max-fps 0.5 \
    --streams 3 \
    --enable-control
```

**Logs esperados al inicio:**

```
2025-10-25 03:30:00 | INFO     | cupertino_nvr.processor.processor | Starting StreamProcessor with 1 streams
2025-10-25 03:30:00 | INFO     | cupertino_nvr.processor.processor | Frame dropping enabled for optimal performance
2025-10-25 03:30:00 | INFO     | cupertino_nvr.processor.processor | Connecting to MQTT broker at localhost:1883
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.processor | Pipeline initialized, starting processing...
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.processor | ======================================================================
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.processor | 🎛️  MQTT CONTROL PLANE INITIALIZATION
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.processor | ======================================================================
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.control_plane | Connecting to MQTT broker at localhost:1883
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.control_plane | Control Plane connected to broker at localhost:1883
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.control_plane | Subscribed to command topic: nvr/control/commands
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.processor | ======================================================================
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.processor | ✅ CONTROL PLANE READY
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.processor | ======================================================================
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.processor | 📡 Command Topic: nvr/control/commands
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.processor | 📊 Status Topic:  nvr/control/status
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.processor | 📤 ACK Topic:     nvr/control/status/ack
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.processor | 
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.processor | 💡 Available commands:
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.processor |    • pause  - Pause stream processing (immediate)
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.processor |    • resume - Resume stream processing
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.processor |    • stop   - Stop processor completely
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.processor |    • status - Query current status
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.processor | 
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.processor | 📝 Example:
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.processor |    mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "pause"}'
2025-10-25 03:30:01 | INFO     | cupertino_nvr.processor.processor | ======================================================================
```

### Terminal 2: Monitor MQTT Topics

```bash
# Detecciones
mosquitto_sub -h localhost -t "nvr/detections/+" -v

# O todas las detecciones más control
mosquitto_sub -h localhost -t "nvr/#" -v
```

### Terminal 3: Monitor Status y ACKs

```bash
# Solo status y ACKs
mosquitto_sub -h localhost -t "nvr/control/#" -v
```

### Terminal 4: Enviar Comandos

```bash
# Pause
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "pause"}'

# Resume
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "resume"}'

# Status
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "status"}'

# Stop
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "stop"}'
```

## Flujo Completo de Testing

### Test 1: Comando PAUSE

**Terminal 4 - Enviar comando:**
```bash
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "pause"}'
```

**Terminal 1 - Logs del processor:**
```
2025-10-25 03:35:00 | INFO     | cupertino_nvr.processor.control_plane | 📥 MQTT Command Received: 'pause' on topic: nvr/control/commands
2025-10-25 03:35:00 | INFO     | cupertino_nvr.processor.control_plane |    Payload: {"command": "pause"}
2025-10-25 03:35:00 | INFO     | cupertino_nvr.processor.control_plane | 📤 ACK published: pause -> received
2025-10-25 03:35:00 | INFO     | cupertino_nvr.processor.control_plane | ⚙️  Executing command: pause
2025-10-25 03:35:00 | INFO     | cupertino_nvr.processor.processor | 
2025-10-25 03:35:00 | INFO     | cupertino_nvr.processor.processor | ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼
2025-10-25 03:35:00 | INFO     | cupertino_nvr.processor.processor | ⏸️  EXECUTING PAUSE COMMAND
2025-10-25 03:35:00 | INFO     | cupertino_nvr.processor.processor | ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼
2025-10-25 03:35:00 | INFO     | cupertino_nvr.processor.processor | → Step 1: Pausing MQTT sink (stops publishing immediately)
2025-10-25 03:35:00 | INFO     | cupertino_nvr.processor.mqtt_sink  | MQTT sink paused - no events will be published
2025-10-25 03:35:00 | INFO     | cupertino_nvr.processor.processor | ✓ Sink paused
2025-10-25 03:35:00 | INFO     | cupertino_nvr.processor.processor | → Step 2: Pausing pipeline stream (stops buffering)
2025-10-25 03:35:00 | INFO     | cupertino_nvr.processor.processor | ✓ Stream paused
2025-10-25 03:35:00 | INFO     | cupertino_nvr.processor.processor | → Step 3: Publishing status update
2025-10-25 03:35:00 | INFO     | cupertino_nvr.processor.control_plane | 📤 Status published: paused
2025-10-25 03:35:00 | INFO     | cupertino_nvr.processor.processor | ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲
2025-10-25 03:35:00 | INFO     | cupertino_nvr.processor.processor | ✅ PAUSE COMPLETED SUCCESSFULLY
2025-10-25 03:35:00 | INFO     | cupertino_nvr.processor.processor | ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲
2025-10-25 03:35:00 | INFO     | cupertino_nvr.processor.processor | 
2025-10-25 03:35:00 | INFO     | cupertino_nvr.processor.control_plane | 📤 ACK published: pause -> completed
2025-10-25 03:35:00 | INFO     | cupertino_nvr.processor.control_plane | ✅ Command 'pause' executed successfully
```

**Terminal 2 - Detecciones (deberían detenerse inmediatamente):**
```
nvr/detections/3 {"source_id":3,"frame_id":586,...}
nvr/detections/3 {"source_id":3,"frame_id":587,...}
(No más mensajes después del pause)
```

**Terminal 3 - Status y ACKs:**
```
nvr/control/status/ack {"command":"pause","ack_status":"received","timestamp":"2025-10-25T03:35:00.123456","client_id":"nvr_processor_control"}
nvr/control/status {"status":"paused","timestamp":"2025-10-25T03:35:00.234567","client_id":"nvr_processor_control"}
nvr/control/status/ack {"command":"pause","ack_status":"completed","timestamp":"2025-10-25T03:35:00.345678","client_id":"nvr_processor_control"}
```

### Test 2: Comando RESUME

**Terminal 4 - Enviar comando:**
```bash
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "resume"}'
```

**Terminal 1 - Logs del processor:**
```
2025-10-25 03:36:00 | INFO     | cupertino_nvr.processor.control_plane | 📥 MQTT Command Received: 'resume' on topic: nvr/control/commands
2025-10-25 03:36:00 | INFO     | cupertino_nvr.processor.control_plane |    Payload: {"command": "resume"}
2025-10-25 03:36:00 | INFO     | cupertino_nvr.processor.control_plane | 📤 ACK published: resume -> received
2025-10-25 03:36:00 | INFO     | cupertino_nvr.processor.control_plane | ⚙️  Executing command: resume
2025-10-25 03:36:00 | INFO     | cupertino_nvr.processor.processor | 
2025-10-25 03:36:00 | INFO     | cupertino_nvr.processor.processor | ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼
2025-10-25 03:36:00 | INFO     | cupertino_nvr.processor.processor | ▶️  EXECUTING RESUME COMMAND
2025-10-25 03:36:00 | INFO     | cupertino_nvr.processor.processor | ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼
2025-10-25 03:36:00 | INFO     | cupertino_nvr.processor.processor | → Step 1: Resuming pipeline stream (starts buffering)
2025-10-25 03:36:00 | INFO     | cupertino_nvr.processor.processor | ✓ Stream resumed
2025-10-25 03:36:00 | INFO     | cupertino_nvr.processor.processor | → Step 2: Resuming MQTT sink (starts publishing)
2025-10-25 03:36:00 | INFO     | cupertino_nvr.processor.mqtt_sink  | MQTT sink resumed - publishing events
2025-10-25 03:36:00 | INFO     | cupertino_nvr.processor.processor | ✓ Sink resumed
2025-10-25 03:36:00 | INFO     | cupertino_nvr.processor.processor | → Step 3: Publishing status update
2025-10-25 03:36:00 | INFO     | cupertino_nvr.processor.control_plane | 📤 Status published: running
2025-10-25 03:36:00 | INFO     | cupertino_nvr.processor.processor | ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲
2025-10-25 03:36:00 | INFO     | cupertino_nvr.processor.processor | ✅ RESUME COMPLETED SUCCESSFULLY
2025-10-25 03:36:00 | INFO     | cupertino_nvr.processor.processor | ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲
2025-10-25 03:36:00 | INFO     | cupertino_nvr.processor.processor | 
2025-10-25 03:36:00 | INFO     | cupertino_nvr.processor.control_plane | 📤 ACK published: resume -> completed
2025-10-25 03:36:00 | INFO     | cupertino_nvr.processor.control_plane | ✅ Command 'resume' executed successfully
```

**Terminal 2 - Detecciones (deberían reanudarse):**
```
(Sin mensajes durante pause)
nvr/detections/3 {"source_id":3,"frame_id":600,...}
nvr/detections/3 {"source_id":3,"frame_id":601,...}
(Mensajes continuos)
```

**Terminal 3 - Status y ACKs:**
```
nvr/control/status/ack {"command":"resume","ack_status":"received",...}
nvr/control/status {"status":"running",...}
nvr/control/status/ack {"command":"resume","ack_status":"completed",...}
```

### Test 3: Comando STATUS

**Terminal 4:**
```bash
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "status"}'
```

**Terminal 3 - Status actual:**
```
nvr/control/status/ack {"command":"status","ack_status":"received",...}
nvr/control/status {"status":"running",...}
nvr/control/status/ack {"command":"status","ack_status":"completed",...}
```

## Protocolo IoT: Request-ACK-Response

El control plane sigue el patrón estándar IoT de Request-ACK-Response:

```
┌──────────┐                    ┌──────────────┐
│ Cliente  │                    │  Processor   │
└────┬─────┘                    └──────┬───────┘
     │                                 │
     │  1. COMMAND                     │
     │  {"command": "pause"}           │
     ├────────────────────────────────>│
     │                                 │
     │  2. ACK (received)              │
     │<────────────────────────────────┤
     │                                 │ [Ejecuta comando]
     │                                 │
     │  3. STATUS UPDATE               │
     │<────────────────────────────────┤
     │  {"status": "paused"}           │
     │                                 │
     │  4. ACK (completed)             │
     │<────────────────────────────────┤
     │                                 │
```

### Topics:

1. **Command**: `nvr/control/commands` (QoS 1)
   - Cliente publica comandos aquí
   - QoS 1 garantiza entrega

2. **Status**: `nvr/control/status` (QoS 1, Retained)
   - Processor publica estado actual
   - Retained: Nuevos subscribers obtienen último estado

3. **ACK**: `nvr/control/status/ack` (QoS 1, No Retained)
   - Processor publica confirmaciones
   - `received`: Comando recibido (inmediato)
   - `completed`: Comando ejecutado (después de ejecutar)
   - `error`: Error en ejecución

## Troubleshooting

### No veo logs del control plane

**Verificar:**
1. Que se inició con `--enable-control`
2. Que el logging está en nivel INFO
3. Que el control plane se conectó correctamente

**Debug:**
```bash
# Ver todos los logs
uv run cupertino-nvr processor --model yolov11s-640 --streams 3 --enable-control 2>&1 | tee processor.log

# Filtrar solo control plane
grep "control_plane" processor.log
```

### No recibe comandos MQTT

**Verificar broker:**
```bash
# Test básico de MQTT
mosquitto_pub -h localhost -t "test" -m "hello"
mosquitto_sub -h localhost -t "test"
```

**Verificar subscripción:**
```bash
# Ver si processor está subscrito
mosquitto_sub -h localhost -t '$SYS/broker/clients/#' -v
```

**Enviar con verbose:**
```bash
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "status"}' -d
```

### Comando no ejecuta (recibe pero no hace nada)

**Verificar estado:**
- PAUSE solo funciona si `is_running=True` y `is_paused=False`
- RESUME solo funciona si `is_running=True` y `is_paused=True`

**Ver logs de estado:**
Los logs mostrarán:
```
⚠️  Cannot pause: Pipeline is not running or already paused
   is_running: True, is_paused: True
```

## Comparación con Adeline

| Feature | Cupertino NVR | Adeline |
|---------|---------------|---------|
| **ACKs** | ✅ (received, completed, error) | ❌ |
| **Logging Verboso** | ✅ (step-by-step) | ⚠️ (básico) |
| **Trace IDs** | ❌ | ✅ |
| **Structured Logging** | ⚠️ (básico) | ✅ (JSON) |

Cupertino NVR implementa ACKs explícitos (estándar IoT) que Adeline no tiene. Esto es mejor para debugging y monitoring externo.

## Scripts de Testing Automático

Ver `examples/mqtt_control_test.py` para testing automatizado con assertions.

