# Test de Diagnóstico: Comando PAUSE no detiene publicaciones

## Problema Reportado

El comando `pause` se envía via MQTT pero el processor sigue publicando eventos de detección.

```
nvr/detections/0 {"source_id":0,"frame_id":188,...}
nvr/control/commands {"command": "pause"}
nvr/detections/0 {"source_id":0,"frame_id":218,...}  # ← SIGUE PUBLICANDO!
```

## Hipótesis

1. ❓ Control plane no está habilitado
2. ❓ Control plane no se conectó correctamente
3. ❓ Control plane no está subscrito al topic correcto
4. ❓ Handler de pause está fallando
5. ❓ Race condition en el sink

## Test de Diagnóstico

### Setup

**Terminal 1 - Processor con logs humanos (sin --json-logs):**
```bash
uv run cupertino-nvr processor \
    --model yolov11s-640 \
    --max-fps 0.5 \
    --streams 0 \
    --enable-control
```

**Logs esperados al inicio:**
```
2025-10-25 XX:XX:XX | INFO | cupertino_nvr.processor.processor | Starting StreamProcessor with 1 streams
...
2025-10-25 XX:XX:XX | INFO | cupertino_nvr.processor.processor | ▶️ Starting InferencePipeline...
2025-10-25 XX:XX:XX | INFO | cupertino_nvr.processor.processor | ✅ Pipeline started successfully
2025-10-25 XX:XX:XX | INFO | cupertino_nvr.processor.processor | 🎛️  Initializing MQTT Control Plane
2025-10-25 XX:XX:XX | INFO | cupertino_nvr.processor.control_plane | Control Plane connected to MQTT broker
2025-10-25 XX:XX:XX | INFO | cupertino_nvr.processor.control_plane | Subscribed to command topic: nvr/control/commands
2025-10-25 XX:XX:XX | INFO | cupertino_nvr.processor.processor | ✅ CONTROL PLANE READY
```

**🔍 CHECKPOINT 1:** ¿Ves "✅ CONTROL PLANE READY"?
- ✅ SI → Continuar
- ❌ NO → El control plane NO se inicializó correctamente

---

**Terminal 2 - Monitor detecciones:**
```bash
mosquitto_sub -h localhost -t "nvr/detections/+" -v
```

**Terminal 3 - Monitor control (status + ACKs):**
```bash
mosquitto_sub -h localhost -t "nvr/control/#" -v
```

---

### Test 1: Comando PAUSE

**Terminal 4 - Enviar PAUSE:**
```bash
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "pause"}'
```

**Logs esperados en Terminal 1 (processor):**
```
2025-10-25 XX:XX:XX | INFO | cupertino_nvr.processor.control_plane | 📥 MQTT Command Received: 'pause' on topic: nvr/control/commands
2025-10-25 XX:XX:XX | INFO | cupertino_nvr.processor.control_plane |    Payload: {"command": "pause"}
2025-10-25 XX:XX:XX | INFO | cupertino_nvr.processor.control_plane | ⚙️  Executing command: pause
2025-10-25 XX:XX:XX | INFO | cupertino_nvr.processor.processor | ⏸️  EXECUTING PAUSE COMMAND
2025-10-25 XX:XX:XX | INFO | cupertino_nvr.processor.mqtt_sink  | MQTT sink paused - no events will be published
2025-10-25 XX:XX:XX | INFO | cupertino_nvr.processor.processor | ✅ PAUSE COMPLETED SUCCESSFULLY
```

**🔍 CHECKPOINT 2:** ¿Ves "📥 MQTT Command Received: 'pause'"?
- ✅ SI → El comando llegó al processor
- ❌ NO → El control plane NO está recibiendo comandos

**🔍 CHECKPOINT 3:** ¿Ves "MQTT sink paused"?
- ✅ SI → El sink se pausó correctamente
- ❌ NO → El handler de pause falló

**Logs esperados en Terminal 3 (control):**
```
nvr/control/status/ack {"command":"pause","ack_status":"received",...}
nvr/control/status {"status":"paused",...}
nvr/control/status/ack {"command":"pause","ack_status":"completed",...}
```

**🔍 CHECKPOINT 4:** ¿Ves los ACKs?
- ✅ SI → El control plane está funcionando
- ❌ NO → El control plane NO está publicando ACKs

**Logs esperados en Terminal 2 (detecciones):**
```
nvr/detections/0 {"source_id":0,"frame_id":100,...}
nvr/detections/0 {"source_id":0,"frame_id":101,...}
(PAUSA - NO más mensajes)
```

**🔍 CHECKPOINT 5:** ¿Las detecciones se DETIENEN inmediatamente (<1 segundo)?
- ✅ SI → PAUSE funciona correctamente ✅
- ❌ NO, siguen por 5+ segundos → Problema de buffer (race condition)
- ❌ NO, nunca se detienen → **EL BUG QUE REPORTASTE** 🐛

---

### Test 2: Comando RESUME

**Terminal 4:**
```bash
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "resume"}'
```

**Logs esperados en Terminal 1:**
```
2025-10-25 XX:XX:XX | INFO | cupertino_nvr.processor.control_plane | 📥 MQTT Command Received: 'resume'
2025-10-25 XX:XX:XX | INFO | cupertino_nvr.processor.processor | ▶️  EXECUTING RESUME COMMAND
2025-10-25 XX:XX:XX | INFO | cupertino_nvr.processor.mqtt_sink  | MQTT sink resumed - publishing events
2025-10-25 XX:XX:XX | INFO | cupertino_nvr.processor.processor | ✅ RESUME COMPLETED SUCCESSFULLY
```

**Terminal 2 (detecciones deberían volver):**
```
(sin mensajes durante pause)
nvr/detections/0 {"source_id":0,"frame_id":120,...}
nvr/detections/0 {"source_id":0,"frame_id":121,...}
```

**🔍 CHECKPOINT 6:** ¿Las detecciones VUELVEN inmediatamente?
- ✅ SI → RESUME funciona correctamente ✅
- ❌ NO → Bug en resume

---

## Análisis de Resultados

### Caso 1: Control Plane no se inicializa
**Síntomas:**
- NO aparece "✅ CONTROL PLANE READY" en logs
- NO hay ACKs en Terminal 3
- NO aparece "📥 MQTT Command Received" cuando se envía pause

**Causa probable:**
- Processor iniciado sin `--enable-control`
- Fallo en conexión MQTT (broker no disponible)

**Fix:**
```bash
# Verificar broker
nc -z localhost 1883

# Verificar flag en comando
uv run cupertino-nvr processor ... --enable-control  # ← DEBE estar presente
```

---

### Caso 2: Control Plane inicializado pero no recibe comandos
**Síntomas:**
- ✅ Aparece "✅ CONTROL PLANE READY"
- ❌ NO aparece "📥 MQTT Command Received" cuando se envía pause
- ❌ NO hay ACKs en Terminal 3

**Causa probable:**
- Topic incorrecto
- QoS issue (poco probable)
- Dos brokers diferentes (muy raro)

**Debug:**
```bash
# Ver clientes conectados
mosquitto_sub -h localhost -t '$SYS/broker/clients/#' -v

# Ver subscripciones
mosquitto_sub -h localhost -t '$SYS/broker/subscriptions/#' -v
```

---

### Caso 3: Comando recibido pero sink NO se pausa
**Síntomas:**
- ✅ Aparece "📥 MQTT Command Received: 'pause'"
- ✅ Aparece "⏸️ EXECUTING PAUSE COMMAND"
- ❌ NO aparece "MQTT sink paused"
- ❌ Detecciones SIGUEN publicándose

**Causa probable:**
- Exception en `_handle_pause()` (silenciada)
- Bug en `mqtt_sink.pause()`

**Debug:** Ver logs completos con traceback

---

### Caso 4: Sink se pausa pero detecciones siguen
**Síntomas:**
- ✅ Aparece "MQTT sink paused"
- ✅ Aparece "✅ PAUSE COMPLETED SUCCESSFULLY"
- ❌ Detecciones SIGUEN publicándose por 5+ segundos (o nunca paran)

**Causa probable:**
- Race condition: frames en buffer se publican antes de que `_paused` flag se active
- Bug en `__call__()`: no está verificando el flag `_paused`

**Debug:** Agregar print statement en `mqtt_sink.py`:
```python
def __call__(self, predictions, video_frame):
    print(f"[DEBUG] __call__ invoked, _paused={self._paused}")  # ← ADD THIS
    if self._paused:
        print("[DEBUG] Skipping publish (paused)")  # ← ADD THIS
        return
```

---

## Resumen de Checkpoints

| Checkpoint | Qué verifica | Si FALLA, causa probable |
|------------|--------------|--------------------------|
| 1 | Control plane inicializado | Sin `--enable-control` o broker down |
| 2 | Comando llega a processor | Topic incorrecto o no subscrito |
| 3 | Sink se pausa | Exception en handler |
| 4 | ACKs se publican | Control plane no publica status |
| 5 | Detecciones se detienen | **EL BUG** - sink no está pausando |
| 6 | Detecciones vuelven | Bug en resume |

---

## Próximos Pasos

Una vez que completes este test, reportá:

1. **¿En qué checkpoint falló?**
2. **Logs completos** del processor desde inicio hasta comando pause
3. **Todos los mensajes** en Terminal 2 y 3 durante el test

Con esa información podemos diagnosticar exactamente dónde está el problema.
