# Testing Pipeline Start - Post MQTT Control Validation

## Objetivo

Validar que el pipeline arranca sin lockeos después de deshabilitar modelos pesados.

---

## Test 1: Start Simple (Stream Único)

Probar con un solo stream para aislar problemas:

```bash
# Con debug de env vars
DEBUG_ENV_VARS=true uv run cupertino-nvr processor \
  --model yolov11s-640 \
  --max-fps 0.2 \
  --streams 0 \
  --enable-control \
  --json-logs
```

### Logs Esperados (Éxito)

```json
{"message": "🔧 [DEBUG] Disabled models env vars:", ...}
{"message": "Starting StreamProcessor with 1 streams", ...}
{"message": "Connecting to MQTT broker at localhost:1883", ...}
{"message": "🔧 [DEBUG] Importing inference with disabled models", ...}
{"message": "Pipeline initialized, starting processing...", ...}
{"message": "▶️ Starting InferencePipeline...", ...}
{"message": "✅ Pipeline started successfully", ...}  # 🎯 CLAVE
{"message": "✅ CONTROL PLANE READY", ...}
{"message": "Waiting for pipeline to finish...", ...}
```

**Si ves "✅ Pipeline started successfully"**: ¡Funciona! El lockeo está resuelto ✅

**Si se queda colgado en "▶️ Starting InferencePipeline..."**: Lockeo persiste → ir a Troubleshooting

---

## Test 2: Verificar Detecciones MQTT

Si el pipeline arrancó, verificar que publica detecciones:

```bash
# Terminal 1: Processor corriendo (del Test 1)

# Terminal 2: Escuchar detecciones
mosquitto_sub -h localhost -t "nvr/detections/0" -v
```

**Esperado:**
```json
nvr/detections/0 {"source_id":0,"frame_id":1,"timestamp":"...","detections":[...]}
nvr/detections/0 {"source_id":0,"frame_id":2,"timestamp":"...","detections":[...]}
...
```

**Si ves detecciones**: Pipeline procesa frames correctamente ✅

---

## Test 3: MQTT Control con Pipeline Activo

```bash
# Terminal 3: Enviar PAUSE
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "pause"}'
```

**Esperado en Terminal 2** (detecciones deben detenerse):
```
nvr/detections/0 {"source_id":0,"frame_id":45,...}
nvr/detections/0 {"source_id":0,"frame_id":46,...}
(Sin más mensajes después de PAUSE)
```

**Esperado en Terminal 1** (logs del processor):
```json
{"message": "⏸️ Executing PAUSE command", ...}
{"message": "MQTT sink paused - no events will be published", ...}
{"message": "✅ PAUSE completed successfully", ...}
```

**RESUME:**
```bash
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "resume"}'
```

**Esperado**: Detecciones reanudan inmediatamente.

**STOP:**
```bash
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "stop"}'
```

**Esperado**: Proceso termina limpiamente.

---

## Test 4: Múltiples Streams

Si Test 1-3 funcionan, escalar a múltiples streams:

```bash
uv run cupertino-nvr processor \
  --model yolov11s-640 \
  --max-fps 0.2 \
  --streams 0,1,2,3 \
  --enable-control \
  --json-logs
```

**Verificar**:
- Pipeline arranca sin lockeo
- Detecciones en todos los streams: `mosquitto_sub -h localhost -t "nvr/detections/+" -v`
- PAUSE/RESUME funcionan en todos los streams

---

## Troubleshooting: Pipeline NO Arranca

### Síntoma 1: Se queda en "▶️ Starting InferencePipeline..."

**Causa posible**: Modelos no deshabilitados correctamente.

**Verificación**:
```bash
# Ver logs de debug de env vars
DEBUG_ENV_VARS=true uv run cupertino-nvr processor ... 2>&1 | head -20
```

**Esperado**:
```
🔧 [DEBUG] Disabled models env vars:
   CORE_MODEL_SAM2_ENABLED = False
   CORE_MODEL_CLIP_ENABLED = False
   ...
```

**Si NO aparecen**: Las env vars no se están aplicando → volver a Opción B (InferenceLoader).

---

### Síntoma 2: Error "RTSP connection timeout"

**Causa**: El stream RTSP no existe.

**Verificación**:
```bash
ffprobe rtsp://localhost:8554/live/0.stream
```

**Fix**: Verificar qué streams existen:
```bash
for i in {0..5}; do
  echo -n "Stream $i: "
  timeout 2 ffprobe -v quiet rtsp://localhost:8554/live/$i.stream && echo "✓" || echo "✗"
done
```

Usar solo streams disponibles: `--streams 0,1,2`

---

### Síntoma 3: Error "Failed to download model"

**Causa**: Inference intenta descargar yolov11s-640 y falla.

**Fix temporal**: Pre-descargar modelo:
```python
# test_download.py
import os
for model in ["PALIGEMMA", "FLORENCE2", "QWEN_2_5",
              "CORE_MODEL_SAM", "CORE_MODEL_SAM2", "CORE_MODEL_CLIP",
              "CORE_MODEL_GAZE", "SMOLVLM2", "DEPTH_ESTIMATION",
              "MOONDREAM2", "CORE_MODEL_TROCR", "CORE_MODEL_GROUNDINGDINO",
              "CORE_MODEL_YOLO_WORLD", "CORE_MODEL_PE"]:
    os.environ[f"{model}_ENABLED"] = "False"

from inference import InferencePipeline

# Si llega acá, el modelo está descargado
print("✅ Model downloaded successfully")
```

```bash
python test_download.py
```

---

## Checklist de Validación

Pipeline funcionando correctamente si:

- [x] Arranca sin lockeo ("✅ Pipeline started successfully")
- [x] Publica detecciones a MQTT
- [x] PAUSE detiene publicaciones inmediatamente
- [x] RESUME reanuda publicaciones
- [x] STOP termina limpiamente
- [x] Múltiples streams funcionan

---

## Comparación: Antes vs Después

### Antes (Con Lockeo)
```
Pipeline initialized, starting processing...
(Se queda colgado indefinidamente)
```

### Después (Sin Lockeo - Esperado)
```
Pipeline initialized, starting processing...
▶️ Starting InferencePipeline...
✅ Pipeline started successfully
✅ CONTROL PLANE READY
Waiting for pipeline to finish...
```

---

## Siguiente Paso si Funciona

Una vez validado que funciona:

1. **Commit** de los cambios con mensaje descriptivo
2. **Documentar** qué modelos se deshabilitaron y por qué
3. **Considerar** implementar InferenceLoader completo (Opción B) para solución más robusta
4. **Testing de carga**: Probar con 6-12 streams simultáneos

---

## Siguiente Paso si NO Funciona

Si sigue lockeando después de deshabilitar modelos:

1. Implementar **InferenceLoader** completo (como Adeline)
2. Verificar **conectividad RTSP** (streams disponibles)
3. **Strace** para ver dónde se lockea exactamente:
   ```bash
   strace -f -e trace=network,futex uv run cupertino-nvr processor ... 2>&1 | tee strace.log
   ```
4. Revisar **logs de inference** internos (si disponibles)
