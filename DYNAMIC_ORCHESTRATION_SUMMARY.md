# Dynamic Orchestration - Implementation Summary

**Fecha:** 2025-10-25
**Versión:** 1.0
**Status:** ✅ Completado

---

## Objetivo

Implementar orquestación dinámica de recursos para sistema NVR geriátrico:
- Ajustar modelos y FPS según nivel de riesgo de habitación
- Agregar/quitar habitaciones del monitoreo sin reiniciar servicio
- Todo controlado vía comandos MQTT en tiempo real

---

## Escenario de Uso

### Residencia Geriátrica - 8 Habitaciones

**Estado Normal:**
```
Processor_A: Habitaciones 0-3 → yolov11n-640, max-fps=0.1 (bajo consumo)
Processor_B: Habitaciones 4-7 → yolov11n-640, max-fps=0.1 (bajo consumo)
```

**Evento: Caída detectada en Habitación 2**
```
Orchestrator:
  1. Processor_A: remove_stream(2)
  2. Processor_A: set_fps(0.05)  # Liberar CPU
  3. Spawn Processor_A_1:
     - add_stream(2)
     - change_model(yolov11x-640)  # Alta precisión
     - set_fps(1.0)  # Máxima frecuencia
```

**Resultado:**
- Habitación 2: Análisis con máxima precisión (yolov11x-640 @ 1 FPS)
- Otras habitaciones: Monitoreo de rutina (yolov11n-640 @ 0.05 FPS)
- **Sin interrumpir el servicio** - Todo vía comandos MQTT

---

## Comandos Implementados

### 1. RESTART
Reiniciar pipeline manteniendo config actual.

```bash
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "restart"}'
```

**Casos de uso:**
- Recuperación de error RTSP
- Aplicar cambios de red
- Testing de reconexión

### 2. CHANGE_MODEL
Cambiar modelo de inferencia dinámicamente.

```bash
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "change_model", "params": {"model_id": "yolov11x-640"}}'
```

**Casos de uso:**
- Habitación de riesgo → modelo pesado (yolov11x)
- Habitación normal → modelo ligero (yolov11n)

### 3. SET_FPS
Ajustar FPS de inferencia.

```bash
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "set_fps", "params": {"max_fps": 1.0}}'
```

**Casos de uso:**
- Emergencia → 1 FPS (máxima precisión)
- Rutina → 0.1 FPS (bajo consumo)

### 4. ADD_STREAM
Agregar habitación al monitoreo.

```bash
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "add_stream", "params": {"source_id": 8}}'
```

**Stream URI generado automáticamente:**
```python
# Internamente:
stream_uri = f"{stream_server}/{source_id}"
# → rtsp://go2rtc-server/8
# go2rtc resuelve a URL real de cámara
```

**Casos de uso:**
- Nuevo residente ingresa
- Activar monitoreo temporal

### 5. REMOVE_STREAM
Quitar habitación del monitoreo.

```bash
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "remove_stream", "params": {"source_id": 2}}'
```

**Casos de uso:**
- Residente dado de alta
- Liberar recursos para habitación prioritaria

---

## Arquitectura go2rtc (RTSP Proxy/DNS)

Los servicios **solo conocen números de habitación (0-12)**, no URLs reales.

```
Processor --streams 0,1,2--> go2rtc (DNS/Router) --> Cámaras Reales
                              ├─ 0 → rtsp://cam0/stream1
                              ├─ 1 → rtsp://cam1/h264
                              ├─ 2 → rtsp://cam2/live
                              ...
                              └─ 12 → rtsp://cam12/stream
```

**Beneficios:**
- ✅ URLs centralizadas (solo en go2rtc.yaml)
- ✅ Cambio de cámara sin reiniciar servicios
- ✅ Comandos MQTT simples (solo source_id)
- ✅ Sin credenciales en CLI/logs

Ver: `docs/nvr/GO2RTC_PROXY_ARCHITECTURE.md`

---

## Arquitectura Implementada

### Patrón IoT Completo

```
Cliente → MQTT Broker → Control Plane → Processor
   ↓                         ↓              ↓
Comando                   ACK "received"  Status "reconfiguring"
                             ↓              ↓
                          Execute       Modify config
                             ↓              ↓
                          ACK "completed" Restart pipeline
                                            ↓
                                         Status "running"
```

### Estados MQTT

```json
// Normal → Reconfiguring → Normal (success)
{"status": "running", "timestamp": "...", "client_id": "..."}
{"status": "reconfiguring", "timestamp": "...", "client_id": "..."}
{"status": "running", "timestamp": "...", "client_id": "..."}

// Normal → Reconfiguring → Error (failure + rollback)
{"status": "running", "timestamp": "...", "client_id": "..."}
{"status": "reconfiguring", "timestamp": "...", "client_id": "..."}
{"status": "error", "timestamp": "...", "client_id": "..."}
```

### Structured Logging

**Todos los eventos son estructurados para Elasticsearch:**

```json
{
  "timestamp": "2025-10-25T06:40:18.000000",
  "level": "INFO",
  "logger": "processor",
  "message": "CHANGE_MODEL command executing",
  "component": "processor",
  "event": "change_model_command_start",
  "old_model_id": "yolov11n-640",
  "new_model_id": "yolov11x-640"
}
```

**No más logs narrativos** - Solo events parseables.

---

## Características Clave

### ✅ Rollback Automático

Si un comando falla (ej: modelo inválido), config se revierte automáticamente:

```python
try:
    self.config.model_id = new_model_id
    self._handle_restart()
except Exception as e:
    self.config.model_id = old_model_id  # Rollback
    logger.error("CHANGE_MODEL failed, rolled back", ...)
    raise
```

### ✅ Idempotencia

Comandos rechazados si ya está en progreso:

```python
if hasattr(self, '_is_restarting') and self._is_restarting:
    logger.warning("Restart already in progress")
    return
```

### ✅ Thread Safety

Pipeline restart no bloquea el servicio:

```python
# join() loop detecta restart y espera al nuevo pipeline
while True:
    self.pipeline.join()
    if self._is_restarting:
        while self._is_restarting:
            time.sleep(0.1)
        continue  # Rejoin new pipeline
    else:
        break  # Real shutdown
```

### ✅ Validación de Parámetros

```python
if not new_model_id:
    raise ValueError("Missing required parameter: model_id")

if source_id in self.config.source_id_mapping:
    raise ValueError(f"Stream {source_id} already exists")
```

---

## Testing

### Test Script Incluido

```bash
./test_dynamic_config.sh
```

**Tests cubiertos:**
1. CHANGE_MODEL (yolov11s → yolov11x)
2. SET_FPS (0.1 → 1.0)
3. ADD_STREAM (agregar habitación)
4. REMOVE_STREAM (quitar habitación)
5. Error handling (modelo inválido)
6. Error handling (params faltantes)

### Monitoreo en Vivo

```bash
# Terminal 1: Processor
uv run cupertino-nvr processor --streams 0 --enable-control --max-fps 0.1

# Terminal 2: Status updates
mosquitto_sub -h localhost -t "nvr/control/status" -v

# Terminal 3: ACKs
mosquitto_sub -h localhost -t "nvr/control/status/ack" -v

# Terminal 4: Enviar comandos
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "change_model", "params": {"model_id": "yolov11x-640"}}'
```

---

## Próximos Pasos

### Sprint Siguiente: Orchestrator Service

```python
# orchestrator.py
class RoomOrchestrator:
    """
    Orquesta processors según eventos de caída.

    Workflow:
    1. Escucha eventos: nvr/events/fall_detected
    2. Identifica habitación de riesgo
    3. Spawn processor dedicado (alta precisión)
    4. Reduce recursos en processors de habitaciones normales
    """

    def on_fall_detected(self, room_id: int):
        # Remove room from main processor
        mqtt_pub("nvr/control/commands", {
            "command": "remove_stream",
            "params": {"source_id": room_id}
        })

        # Spawn dedicated processor
        spawn_processor(
            streams=[room_id],
            model="yolov11x-640",
            max_fps=1.0,
            priority="high"
        )
```

### Features Adicionales Posibles

1. **RECONFIGURE (atomic)**: Cambiar múltiples params en un comando
2. **CHANGE_STREAM_URI**: Actualizar URI sin quitar/agregar stream
3. **SET_CONFIDENCE**: Ajustar threshold de detección
4. **ENABLE_TRACKING**: Activar/desactivar ByteTrack
5. **BATCH_COMMANDS**: Ejecutar múltiples comandos atomically

---

## Archivos Modificados/Creados

### Código
- `cupertino_nvr/processor/processor.py` (+470 líneas)
  - `_handle_restart()` - Primitiva de restart
  - `_handle_change_model()` - Cambio de modelo
  - `_handle_set_fps()` - Cambio de FPS
  - `_handle_add_stream()` - Agregar stream
  - `_handle_remove_stream()` - Quitar stream
  - `join()` refactored - Loop para restart handling

- `cupertino_nvr/processor/control_plane.py` (+30 líneas)
  - `CommandRegistry.execute()` - Support params
  - `_on_message()` - Parse & pass params

- `cupertino_nvr/logging_utils.py` (+7 líneas)
  - `AutoFlushStreamHandler` - Real-time logging

- `cupertino_nvr/cli.py` (+10 líneas)
  - Updated help text con nuevos comandos

### Documentación
- `docs/nvr/IOT_COMMAND_PATTERN.md` (nuevo)
- `DYNAMIC_ORCHESTRATION_SUMMARY.md` (este archivo)
- `test_dynamic_config.sh` (test script)
- `test_restart_command.sh` (test script)

### Testing
- `test_dynamic_config.sh` - Automated testing
- Manual testing con mosquitto_pub/sub

---

## Lecciones del Blues 🎸

**"Complejidad por diseño, no por accidente"**

- ✅ Primitiva de restart reutilizada por todos los comandos
- ✅ Structured logging desde el inicio (no logs narrativos)
- ✅ IoT pattern consistente en todos los comandos
- ✅ Rollback automático en failures
- ✅ Thread safety sin over-engineering

**"Pragmatismo > Purismo"**

- ✅ Restart via terminate + recreate (simple, funciona)
- ✅ join() loop en vez de event queue complejo
- ✅ Validation con ValueError (Python standard)
- ✅ Signature inspection para backward compatibility

**"Simple para leer, NO simple para escribir una vez"**

- Handlers verbosos pero claros
- Logs estructurados parseable
- Rollback explícito en cada comando
- Comments que explican "por qué"

---

## Conclusión

**✅ Objetivo Cumplido:**

Sistema NVR con orquestación dinámica completa vía MQTT. Listo para escenario geriátrico con:
- Ajuste de recursos según nivel de riesgo
- Agregado/quitado de habitaciones en caliente
- Cambio de modelos y FPS sin downtime
- IoT pattern production-ready
- Structured logging para monitoring

**Próximo paso:** Implementar Orchestrator que consume eventos de caída y orquesta processors automáticamente.

---

**Mantenedor:** Visiona Team
**Co-Authored-By:** Gaby <noreply@visiona.com>
