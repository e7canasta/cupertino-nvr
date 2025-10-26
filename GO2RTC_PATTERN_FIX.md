# go2rtc Pattern Fix

**Fecha:** 2025-10-25
**Tipo:** Bug Fix + Architecture Alignment

---

## Problema Detectado

Al ejecutar `add_stream`, el processor generaba URIs incorrectas:

```bash
# Comando:
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "add_stream", "params": {"source_id": 7}}'

# URI generada (INCORRECTA):
rtsp://localhost:8554/live/7  # 404 Not Found

# URI esperada (CORRECTA):
rtsp://localhost:8554/7  # go2rtc pattern
```

**Root Cause:**

El CLI generaba URIs estilo MediaMTX (`rtsp://server/live/{i}.stream`), pero el proyecto usa **go2rtc** como proxy RTSP, que usa patrón simple (`rtsp://server/{i}`).

---

## Cambios Implementados

### 1. CLI Pattern Update

**ANTES:**
```python
# cli.py
stream_uris=[f"{stream_server}/live/{i}.stream" for i in stream_indices]
# → rtsp://localhost:8554/live/0.stream (MediaMTX pattern)
```

**AHORA:**
```python
# cli.py
stream_uris=[f"{stream_server}/{i}" for i in stream_indices]
# → rtsp://localhost:8554/0 (go2rtc pattern)
```

### 2. Config Enhancement

```python
# config.py
@dataclass
class StreamProcessorConfig:
    # ... existing fields ...

    stream_server: str = "rtsp://localhost:8554"
    """Base RTSP server URL (go2rtc proxy)"""
```

**Beneficio:** No más inferencia de `stream_server` desde URIs existentes (que podía fallar).

### 3. ADD_STREAM Simplificado

**ANTES:**
```python
# Inferir stream_server de URI existente
stream_server = self.config.stream_uris[0].rsplit('/', 1)[0]
# → rtsp://localhost:8554/live (INCORRECTO!)
stream_uri = f"{stream_server}/{source_id}"
```

**AHORA:**
```python
# Usar stream_server de config
stream_uri = f"{self.config.stream_server}/{source_id}"
# → rtsp://localhost:8554/7 (CORRECTO!)
```

---

## Testing

### Test 1: Processor con go2rtc

```bash
# Terminal 1: Start go2rtc (asumiendo que ya tenés streams configurados)
docker run -d --name go2rtc \
  -p 8554:8554 -p 1984:1984 \
  -v $(pwd)/go2rtc.yaml:/config/go2rtc.yaml \
  alexxit/go2rtc

# Terminal 2: Start processor
uv run cupertino-nvr processor \
  --streams 0 \
  --stream-server rtsp://localhost:8554 \
  --enable-control

# Verificar logs:
# stream_uris: ["rtsp://localhost:8554/0"]  ✅ Correcto
```

### Test 2: ADD_STREAM Command

```bash
# Prerequisito: Stream 8 debe existir en go2rtc.yaml
# streams:
#   "8": rtsp://camara-real/stream

# Verificar stream existe:
ffplay rtsp://localhost:8554/8
# O via API:
curl http://localhost:1984/api/streams/8

# Ahora agregar al processor:
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "add_stream", "params": {"source_id": 8}}'

# Logs esperados:
# event: "add_stream_command_start"
# stream_uri: "rtsp://localhost:8554/8"  ✅ Correcto
# stream_server: "rtsp://localhost:8554"
```

### Test 3: VideoWall con go2rtc

```bash
uv run cupertino-nvr wall \
  --streams 0,1,2 \
  --stream-server rtsp://localhost:8554

# Debería mostrar 3 streams en grid
# URIs: rtsp://localhost:8554/0, rtsp://localhost:8554/1, rtsp://localhost:8554/2
```

---

## Compatibilidad con MediaMTX

Si estás usando MediaMTX en vez de go2rtc, necesitás configurar go2rtc como proxy:

```yaml
# go2rtc.yaml
streams:
  "0": rtsp://mediamtx:8554/live/0.stream
  "1": rtsp://mediamtx:8554/live/1.stream
  "2": rtsp://mediamtx:8554/live/2.stream
```

Luego los servicios usan go2rtc:
```bash
cupertino-nvr processor --streams 0,1,2 --stream-server rtsp://go2rtc:8554
```

---

## Troubleshooting

### Error: "404 Not Found" al agregar stream

**Causa:** Stream no existe en go2rtc.

**Solución:**
```yaml
# 1. Agregar en go2rtc.yaml
streams:
  "7": rtsp://camara-real-hab-7/stream

# 2. Reiniciar go2rtc
docker restart go2rtc

# 3. Verificar
curl http://localhost:1984/api/streams/7

# 4. Ahora agregar al processor
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "add_stream", "params": {"source_id": 7}}'
```

### Error: "Cannot connect to video source"

**Causa:** go2rtc no puede conectarse a la cámara real.

**Debug:**
```bash
# Ver logs de go2rtc
docker logs go2rtc

# Test directo a cámara
ffplay rtsp://camara-real:554/stream

# Verificar credenciales en go2rtc.yaml
streams:
  "7": rtsp://admin:PASSWORD@camara-real:554/stream
```

---

## Migration Checklist

Si tenías servicios corriendo con el patrón anterior:

- [ ] Actualizar código (`git pull` o reinstalar)
- [ ] Configurar go2rtc.yaml con tus cámaras
- [ ] Iniciar go2rtc
- [ ] Verificar streams disponibles: `curl http://localhost:1984/api/streams`
- [ ] Reiniciar processor/wall con `--stream-server rtsp://go2rtc-host:8554`
- [ ] Verificar logs muestran URIs correctas (`rtsp://server/{i}`)

---

## Referencias

- `docs/nvr/GO2RTC_PROXY_ARCHITECTURE.md` - Arquitectura completa
- `go2rtc.yaml.example` - Configuración ejemplo
- `cupertino_nvr/processor/config.py:59` - stream_server config
- `cupertino_nvr/cli.py:122` - Pattern go2rtc
- `cupertino_nvr/processor/processor.py:989` - ADD_STREAM implementation

---

**Co-Authored-By:** Gaby <noreply@visiona.com>
