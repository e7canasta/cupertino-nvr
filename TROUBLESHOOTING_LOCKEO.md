# Troubleshooting: Pipeline Lockeo

## Síntomas
El processor se queda colgado después de "Pipeline initialized, starting processing..." y nunca avanza.

## Diagnóstico Paso a Paso

### 1. Verificar Env Vars de Modelos Deshabilitados

Ejecutar con debug habilitado:

```bash
DEBUG_ENV_VARS=true uv run cupertino-nvr processor \
  --model yolov11s-640 \
  --max-fps 0.2 \
  --streams 3 \
  --enable-control \
  --json-logs
```

**Esperado**: Deberías ver logs como:
```
🔧 [DEBUG] Disabled models env vars:
   CORE_MODEL_SAM2_ENABLED = False
   CORE_MODEL_CLIP_ENABLED = False
   ...
🔧 [DEBUG] Importing inference with disabled models
```

**Si NO aparecen**: Las env vars no se están seteando correctamente → ir a Fix 1.

**Si aparecen**: El problema es otro → ir a paso 2.

---

### 2. Verificar Conectividad RTSP

El pipeline puede colgarse intentando conectar a streams RTSP que no existen.

```bash
# Verificar si el stream 3 existe
ffprobe rtsp://localhost:8554/live/3.stream
```

**Si falla**: El stream no está disponible → ir a Fix 2.

---

### 3. Verificar Lockeo en Download de Modelos

Incluso con env vars, inference puede intentar descargar YOLO si no está en cache.

```bash
# Ver logs de red durante startup
strace -e trace=network uv run cupertino-nvr processor --streams 3 2>&1 | grep -i "connect\|download"
```

**Si ves intentos de conexión externa**: Inference está descargando → ir a Fix 3.

---

## Fixes

### Fix 1: Env Vars No Aplicadas

**Problema**: cli.py setea env vars pero el import de inference no las ve.

**Solución**: Implementar InferenceLoader como Adeline.

```bash
# Crear cupertino_nvr/inference_loader.py
# (Copiar de referencias/adeline/inference/loader.py)
```

---

### Fix 2: RTSP Stream No Disponible

**Problema**: El stream 3 no existe en el servidor RTSP.

**Solución**: Usar solo streams que existan:

```bash
# Verificar qué streams existen
for i in {0..5}; do
  echo -n "Stream $i: "
  ffprobe -v quiet rtsp://localhost:8554/live/$i.stream && echo "✓ OK" || echo "✗ NO EXISTE"
done

# Usar solo streams disponibles
cupertino-nvr processor --streams 0,1,2 --enable-control
```

---

### Fix 3: Download de YOLO Lockea

**Problema**: Inference descarga yolov11s-640 y se lockea en el proceso.

**Solución Temporal**: Pre-descargar el modelo manualmente:

```python
# En un script separado (test_download.py)
import os
for model in ["PALIGEMMA", "FLORENCE2", "QWEN_2_5",
              "CORE_MODEL_SAM", "CORE_MODEL_SAM2", "CORE_MODEL_CLIP",
              "CORE_MODEL_GAZE", "SMOLVLM2", "DEPTH_ESTIMATION",
              "MOONDREAM2", "CORE_MODEL_TROCR", "CORE_MODEL_GROUNDINGDINO",
              "CORE_MODEL_YOLO_WORLD", "CORE_MODEL_PE"]:
    os.environ[f"{model}_ENABLED"] = "False"

from inference import InferencePipeline
# Si llega acá sin lockeo, el import está OK
print("✅ Inference imported successfully")
```

---

## Diferencias con Adeline (Conocidas)

### Adeline Tiene:
1. **InferenceLoader**: Lazy loading con singleton pattern
2. **env_setup.py**: Se ejecuta automáticamente al importar el paquete
3. **Makefile env vars**: Setea vars ANTES de ejecutar Python

### Processor NVR Tiene:
1. **cli.py env vars**: Setea vars al inicio del CLI
2. **Lazy import en start()**: Import de inference retrasado hasta start()
3. **No Makefile**: Ejecuta directamente con `uv run`

---

## Next Steps

### Corto Plazo (Quick Fix Extendido)
- [x] Deshabilitar modelos en cli.py
- [x] Debug logging de env vars
- [ ] Verificar RTSP availability antes de start()
- [ ] Pre-download de modelo YOLO

### Mediano Plazo (Solución Robusta)
- [ ] Implementar InferenceLoader completo
- [ ] env_setup.py que se ejecute al importar el paquete
- [ ] Health check de RTSP antes de pipeline.start()

---

## Testing Commands

```bash
# 1. Test con debug completo
DEBUG_ENV_VARS=true uv run cupertino-nvr processor \
  --model yolov11s-640 \
  --max-fps 0.2 \
  --streams 3 \
  --enable-control \
  --json-logs

# 2. Test con stream que sabemos que existe
uv run cupertino-nvr processor \
  --model yolov11s-640 \
  --max-fps 0.2 \
  --streams 0 \
  --enable-control

# 3. Test sin control plane (más simple)
uv run cupertino-nvr processor \
  --model yolov11s-640 \
  --max-fps 0.2 \
  --streams 0
```
