# go2rtc Proxy Architecture

## Filosofía de Diseño

**"Los servicios solo conocen números, no URLs"**

Similar a DNS para nombres de dominio, go2rtc actúa como **proxy/router RTSP** que abstrae las URLs reales de las cámaras. Los servicios (processor, wall) solo conocen números de habitación (0-12).

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────────────┐
│                          Servicios                              │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐   │
│  │ Processor_A  │     │ Processor_B  │     │ VideoWall    │   │
│  │ Rooms: 0-3   │     │ Rooms: 4-7   │     │ Rooms: 0-7   │   │
│  └──────┬───────┘     └──────┬───────┘     └──────┬───────┘   │
│         │                    │                    │            │
│         │ rtsp://.../0      │ rtsp://.../4      │ rtsp://.../0│
│         └────────────────────┴────────────────────┘            │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │      go2rtc Proxy         │
                    │  (DNS/Router RTSP)        │
                    │                            │
                    │  Mapping:                  │
                    │  0 → rtsp://cam0/stream1   │
                    │  1 → rtsp://cam1/stream1   │
                    │  2 → rtsp://cam2/h264      │
                    │  ...                       │
                    │  12 → rtsp://cam12/live    │
                    └─────────────┬──────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │   Cámaras Físicas         │
                    │  (URLs reales, IPs, etc)  │
                    └───────────────────────────┘
```

---

## Beneficios del Patrón

### ✅ Desacoplamiento Completo
```python
# ❌ ANTES (servicios conocen IPs/rutas reales)
streams = [
    "rtsp://192.168.1.100:554/stream1?username=admin&password=...",
    "rtsp://camara-hab-2.local:8554/h264/ch01/main/av_stream",
    "rtsp://10.0.1.50/live/ch00_0"
]

# ✅ AHORA (servicios solo conocen números)
streams = [0, 1, 2]
# go2rtc resuelve las URLs reales
```

### ✅ Configuración Centralizada
```yaml
# go2rtc.yaml (único lugar con URLs reales)
streams:
  "0": rtsp://192.168.1.100:554/stream1?username=admin&password=secret
  "1": rtsp://camara-hab-2.local:8554/h264/ch01/main/av_stream
  "2": rtsp://10.0.1.50/live/ch00_0
  "3": rtsp://camara-hab-4:554/live.sdp
  ...
  "12": rtsp://camara-hab-13.local/stream
```

### ✅ Cambios Sin Downtime
```yaml
# Cambiar cámara de habitación 2 (solo en go2rtc)
# ANTES:
"2": rtsp://camara-vieja-hab-2.local:554/stream

# DESPUÉS:
"2": rtsp://camara-nueva-hab-2.local:554/stream

# Los servicios NO necesitan reiniciar - siguen usando "2"
```

### ✅ Simplicidad en Comandos MQTT
```bash
# ❌ ANTES (URL compleja en comando)
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{
    "command": "add_stream",
    "params": {
      "stream_uri": "rtsp://192.168.1.108:554/h264/ch01/main/av_stream?username=admin&password=secret",
      "source_id": 8
    }
  }'

# ✅ AHORA (solo número de habitación)
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "add_stream", "params": {"source_id": 8}}'
```

### ✅ Seguridad Mejorada
- Credenciales solo en go2rtc config (un lugar)
- Servicios no manejan credenciales
- Logs no exponen URLs/passwords

---

## Configuración go2rtc

### Instalación

```bash
# Docker (recomendado)
docker run -d \
  --name go2rtc \
  -p 8554:8554 \
  -p 1984:1984 \
  -v /path/to/go2rtc.yaml:/config/go2rtc.yaml \
  alexxit/go2rtc

# Binario standalone
wget https://github.com/AlexxIT/go2rtc/releases/latest/download/go2rtc_linux_amd64
chmod +x go2rtc_linux_amd64
./go2rtc_linux_amd64 -config go2rtc.yaml
```

### Configuración Ejemplo (Residencia Geriátrica)

```yaml
# /path/to/go2rtc.yaml

# API para management
api:
  listen: ":1984"

# RTSP server
rtsp:
  listen: ":8554"

# Stream mappings (0-12 = habitaciones)
streams:
  # Habitación 0 - Residente Juan
  "0":
    - rtsp://admin:password123@192.168.1.100:554/stream1
    - "ffmpeg:0#video=h264#hardware"  # Hardware transcode si es necesario

  # Habitación 1 - Residente María
  "1":
    - rtsp://admin:password123@camara-hab-2.local:8554/h264/ch01/main/av_stream

  # Habitación 2 - Residente Pedro
  "2":
    - rtsp://10.0.1.50/live/ch00_0

  # Habitación 3 - Residente Ana
  "3":
    - rtsp://admin:password123@192.168.1.103:554/live.sdp

  # Habitación 4 - Residente Luis
  "4":
    - rtsp://admin:password123@192.168.1.104:554/stream1

  # ... (continuar hasta habitación 12)

  # Habitación 12 - Residente Rosa
  "12":
    - rtsp://admin:password123@camara-hab-13.local:554/stream
```

### Verificación de Config

```bash
# Via API
curl http://localhost:1984/api/streams

# Debería retornar JSON con streams 0-12
{
  "0": {...},
  "1": {...},
  "2": {...},
  ...
  "12": {...}
}

# Test de stream individual
ffplay rtsp://localhost:8554/0
ffplay rtsp://localhost:8554/2
```

---

## Uso en Servicios

### CLI (processor/wall)

```bash
# Processor - Habitaciones 0-3
uv run cupertino-nvr processor \
  --streams 0,1,2,3 \
  --stream-server rtsp://localhost:8554 \
  --model yolov11n-640 \
  --max-fps 0.1

# Wall - Todas las habitaciones
uv run cupertino-nvr wall \
  --streams 0,1,2,3,4,5,6,7 \
  --stream-server rtsp://localhost:8554
```

**URLs generadas automáticamente:**
- `rtsp://localhost:8554/0`
- `rtsp://localhost:8554/1`
- `rtsp://localhost:8554/2`
- etc.

### Comandos MQTT Dinámicos

```bash
# Agregar habitación 8 al monitoreo
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "add_stream", "params": {"source_id": 8}}'

# Internamente:
# stream_uri = f"{stream_server}/8"
# → rtsp://localhost:8554/8
# → go2rtc resuelve a URL real de cámara 8
```

### Código (implementación)

```python
# processor.py - _handle_add_stream()

# Extraer stream_server de config actual
stream_server = self.config.stream_uris[0].rsplit('/', 1)[0]
# → "rtsp://localhost:8554"

# Construir URI simple
stream_uri = f"{stream_server}/{source_id}"
# → "rtsp://localhost:8554/8"

# go2rtc se encarga del resto (routing a cámara real)
```

---

## Troubleshooting

### Stream no aparece

```bash
# 1. Verificar go2rtc está corriendo
curl http://localhost:1984/api/streams

# 2. Verificar stream específico
curl http://localhost:1984/api/streams/2

# 3. Test directo con ffplay
ffplay rtsp://localhost:8554/2

# 4. Revisar logs go2rtc
docker logs go2rtc
```

### Cámara cambió IP

```yaml
# Actualizar solo en go2rtc.yaml
streams:
  "2":
    # ANTES:
    # - rtsp://admin:pass@192.168.1.50:554/stream1

    # DESPUÉS:
    - rtsp://admin:pass@192.168.1.150:554/stream1  # Nueva IP

# Reiniciar go2rtc
docker restart go2rtc

# Servicios NO necesitan cambios
```

### Agregar nueva habitación

**⚠️ IMPORTANTE: El stream DEBE existir en go2rtc ANTES de agregarlo al processor**

```yaml
# 1. Agregar en go2rtc.yaml
streams:
  "13":  # Nueva habitación
    - rtsp://admin:pass@camara-hab-14.local:554/stream1

# 2. Reiniciar go2rtc
docker restart go2rtc

# 3. Verificar que el stream funciona
ffplay rtsp://localhost:8554/13
# O via API:
curl http://localhost:1984/api/streams/13

# 4. AHORA SÍ agregar al processor vía MQTT
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "add_stream", "params": {"source_id": 13}}'
```

**Si el stream no existe en go2rtc (404 Not Found):**
- El pipeline intentará conectarse y fallará
- El processor terminará con error
- Config se quedará en estado inconsistente

**Workaround si agregaste un stream inválido:**
```bash
# Remover el stream inválido
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "remove_stream", "params": {"source_id": 13}}'

# O restart para volver al estado anterior
mosquitto_pub -h localhost -t "nvr/control/commands" \
  -m '{"command": "restart"}'
```

---

## Integración con Orchestrator

```python
# orchestrator.py

class RoomOrchestrator:
    """
    Orquesta processors según nivel de riesgo.

    Solo conoce números de habitación (0-12).
    go2rtc maneja el routing RTSP.
    """

    def on_fall_detected(self, room_id: int):
        """
        Caída detectada en habitación room_id.

        Spawn processor dedicado con alta precisión.
        """
        # Remover de processor principal
        mqtt_pub("nvr/control/commands", {
            "command": "remove_stream",
            "params": {"source_id": room_id}  # Solo número!
        })

        # Spawn processor dedicado
        # stream_server viene de config global
        # → rtsp://go2rtc-server/{room_id}
        spawn_processor(
            streams=[room_id],
            model="yolov11x-640",
            max_fps=1.0,
            priority="high"
        )

    def on_resident_recovered(self, room_id: int):
        """Residente asistido - volver a estado normal."""
        # Terminar processor dedicado
        kill_processor(f"processor_room_{room_id}")

        # Agregar de vuelta al processor principal
        mqtt_pub("nvr/control/commands", {
            "command": "add_stream",
            "params": {"source_id": room_id}
        })
```

---

## Comparación con Arquitectura Anterior

### ❌ ANTES (URLs en CLI)

```bash
# Cada servicio necesita URLs completas
cupertino-nvr processor \
  --stream-uris \
    "rtsp://192.168.1.100:554/stream1" \
    "rtsp://camara-hab-2.local:8554/h264" \
    "rtsp://10.0.1.50/live/ch00_0"

# Comandos MQTT complejos
{"command": "add_stream", "params": {
  "stream_uri": "rtsp://192.168.1.108:554/h264?username=admin&password=secret",
  "source_id": 8
}}
```

**Problemas:**
- URLs en múltiples lugares
- Cambio de cámara → actualizar todos los servicios
- Credenciales expuestas en CLI/logs
- Comandos MQTT verbosos

### ✅ AHORA (go2rtc proxy)

```bash
# Servicios solo conocen números
cupertino-nvr processor --streams 0,1,2

# Comandos MQTT simples
{"command": "add_stream", "params": {"source_id": 8}}
```

**Beneficios:**
- URLs centralizadas en go2rtc
- Cambio de cámara → solo actualizar go2rtc.yaml
- Sin credenciales en CLI/logs
- Comandos MQTT concisos

---

## Deployment Pattern

```yaml
# docker-compose.yml (producción)
version: '3.8'

services:
  # go2rtc - RTSP proxy/router
  go2rtc:
    image: alexxit/go2rtc
    ports:
      - "8554:8554"  # RTSP
      - "1984:1984"  # API
    volumes:
      - ./go2rtc.yaml:/config/go2rtc.yaml
    restart: unless-stopped

  # MQTT broker
  mosquitto:
    image: eclipse-mosquitto
    ports:
      - "1883:1883"
    restart: unless-stopped

  # Processor A - Habitaciones 0-3
  processor-a:
    build: .
    command: >
      cupertino-nvr processor
      --streams 0,1,2,3
      --stream-server rtsp://go2rtc:8554
      --model yolov11n-640
      --max-fps 0.1
      --enable-control
      --mqtt-host mosquitto
    depends_on:
      - go2rtc
      - mosquitto
    restart: unless-stopped

  # Processor B - Habitaciones 4-7
  processor-b:
    build: .
    command: >
      cupertino-nvr processor
      --streams 4,5,6,7
      --stream-server rtsp://go2rtc:8554
      --model yolov11n-640
      --max-fps 0.1
      --enable-control
      --mqtt-host mosquitto
      --control-topic nvr/control/commands/group-b
    depends_on:
      - go2rtc
      - mosquitto
    restart: unless-stopped

  # VideoWall
  wall:
    build: .
    command: >
      cupertino-nvr wall
      --streams 0,1,2,3,4,5,6,7
      --stream-server rtsp://go2rtc:8554
      --mqtt-host mosquitto
    depends_on:
      - go2rtc
      - mosquitto
    environment:
      - DISPLAY=$DISPLAY
    volumes:
      - /tmp/.X11-unix:/tmp/.X11-unix
```

---

## Referencias

- **go2rtc GitHub**: https://github.com/AlexxIT/go2rtc
- **go2rtc Docs**: https://github.com/AlexxIT/go2rtc/wiki
- **Configuración**: `go2rtc.yaml` (este proyecto)
- **Código**: `processor.py:987-990` (construcción automática de URI)

---

**Versión:** 1.0
**Fecha:** 2025-10-25
**Autor:** Visiona Team
