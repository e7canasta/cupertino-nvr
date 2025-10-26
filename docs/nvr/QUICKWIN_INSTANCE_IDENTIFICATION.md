# Quick Win: Instance Identification

**Fecha:** 2025-10-25
**Tipo:** Architecture Enhancement - Multi-Instance Support
**Estado:** Plan

---

## Objetivo

Permitir múltiples processors corriendo simultáneamente con:
- **Identificación única** por instancia (instance_id)
- **Comandos dirigidos** a instancia específica o broadcast
- **Detecciones etiquetadas** con instance_id
- **Métricas etiquetadas** con instance_id

**Use Case (Residencia Geriátrica):**
```
Processor_A (instance_id: "processor-hab-0-3")
  ├─ Habitaciones: 0, 1, 2, 3
  └─ Model: yolov11n-640, FPS: 0.1

Processor_B (instance_id: "processor-hab-4-7")
  ├─ Habitaciones: 4, 5, 6, 7
  └─ Model: yolov11n-640, FPS: 0.1

Processor_C_Room2 (instance_id: "emergency-room-2")  ← Spawned on-demand
  ├─ Habitación: 2 (exclusivo)
  └─ Model: yolov11x-640, FPS: 1.0 (high precision)

Orchestrator necesita:
  - Pausar solo Processor_A
  - Cambiar FPS de Processor_B a 0.05 (liberar CPU)
  - Obtener métricas de Processor_C_Room2
  - Broadcast "status" a todos
```

---

## Arquitectura

### 1. Instance ID Generation

**Config (processor/config.py):**
```python
@dataclass
class StreamProcessorConfig:
    # ... existing fields ...

    instance_id: str = field(default_factory=lambda: f"processor-{uuid.uuid4().hex[:8]}")
    """
    Unique instance identifier.

    Default: Random 8-char hex (e.g., "processor-a3f2b1c0")
    CLI: --instance-id "processor-hab-0-3"
    Orchestrator: Can rename via MQTT command
    """
```

**CLI (cli.py):**
```python
@click.option(
    "--instance-id",
    default=None,
    help="Instance identifier (default: auto-generated processor-{random})",
)
def processor(..., instance_id):
    config = StreamProcessorConfig(
        instance_id=instance_id or f"processor-{uuid.uuid4().hex[:8]}",
        ...
    )
```

### 2. MQTT Topic Hierarchy

**Schema corregido (smart endpoints, dumb pipes):**

```
Commands (single broadcast topic):
  nvr/control/commands                    ← TODOS subscriben aquí
                                           Filtering por target_instances en payload

Status:
  nvr/control/status/{instance_id}        ← Cada instancia publica su status

Detections (agregación por cámara):
  nvr/detections/{source_id}              ← Solo source_id en topic
                                           instance_id en payload (metadata)

Metrics:
  nvr/status/metrics/{instance_id}        ← Métricas por instancia
```

**Design Rationale:**

1. **Detections topic = source_id only**
   - Agregación conceptual: "Qué se ve en la cámara", NO "quién lo detecta"
   - Wall/consumers subscriben a `nvr/detections/2` y ven TODAS las detecciones de cámara 2
   - Si 2 processors monitorean misma cámara (transición emergency) → mismo topic
   - `instance_id` en payload para metadata/debugging, NO para routing

2. **Commands = single broadcast + payload filtering**
   - TODOS los processors subscriben a `nvr/control/commands`
   - Payload lleva `target_instances: ["*"]` (broadcast) o `["proc-a", "proc-b"]` (targeted)
   - Filtering en application layer (smart endpoints)
   - Más flexible: soporta N-to-M communication (lista de destinatarios)

**Ejemplos:**
```bash
# Broadcast - todos procesan
mosquitto_pub -t "nvr/control/commands" -m '{
  "command": "status",
  "target_instances": ["*"]
}'
→ nvr/control/status/processor-hab-0-3 {"instance_id": "processor-hab-0-3", "status": "running"}
→ nvr/control/status/processor-hab-4-7 {"instance_id": "processor-hab-4-7", "status": "running"}
→ nvr/control/status/emergency-room-2 {"instance_id": "emergency-room-2", "status": "running"}

# Targeted - solo processor-hab-0-3 procesa
mosquitto_pub -t "nvr/control/commands" -m '{
  "command": "pause",
  "target_instances": ["processor-hab-0-3"]
}'
→ nvr/control/status/processor-hab-0-3 {"instance_id": "processor-hab-0-3", "status": "paused"}

# Lista de processors - proc-a y proc-b procesan
mosquitto_pub -t "nvr/control/commands" -m '{
  "command": "set_fps",
  "params": {"max_fps": 0.05},
  "target_instances": ["processor-hab-0-3", "processor-hab-4-7"]
}'

# Detecciones: topic por source_id, instance_id en payload
mosquitto_sub -t "nvr/detections/2"
→ {"instance_id": "processor-main", "source_id": 2, "model_id": "yolov8x-640", ...}
→ {"instance_id": "emergency-room-2", "source_id": 2, "model_id": "yolov11x-640", ...}
# ↑ Dos processors detectando en misma cámara (transición) → mismo topic
```

### 3. Control Plane Updates

**control_plane.py:**
```python
class ControlPlane:
    def __init__(self, mqtt_client, instance_id, ...):
        self.instance_id = instance_id

        # Single subscription to broadcast topic
        self.command_topic = "nvr/control/commands"
        self.mqtt_client.subscribe(self.command_topic)

        # Status topic includes instance_id
        self.status_topic = f"nvr/control/status/{instance_id}"

    def _on_message(self, client, userdata, msg):
        """Handle commands with target_instances filtering"""
        # Parse command
        payload = json.loads(msg.payload)
        command = payload.get("command")
        params = payload.get("params", {})
        target_instances = payload.get("target_instances", ["*"])  # Default: broadcast

        # Check if this instance should process the command
        if not self._should_process_command(target_instances):
            logger.debug(
                "Command ignored (not targeted to this instance)",
                extra={
                    "component": "control_plane",
                    "event": "command_filtered",
                    "target_instances": target_instances,
                    "this_instance": self.instance_id
                }
            )
            return

        logger.info(
            "Command received",
            extra={
                "component": "control_plane",
                "event": "command_received",
                "command": command,
                "target_instances": target_instances,
                "this_instance": self.instance_id
            }
        )

        # Execute command
        self._execute_command(command, params, msg.topic)

    def _should_process_command(self, target_instances: List[str]) -> bool:
        """
        Check if this instance should process the command.

        Args:
            target_instances: List of instance IDs or ["*"] for broadcast

        Returns:
            True if command should be processed, False otherwise
        """
        # Broadcast: process if target_instances is ["*"], None, or empty
        if not target_instances or target_instances == ["*"]:
            return True

        # Targeted: process if this instance_id is in the list
        return self.instance_id in target_instances

    def publish_status(self, status: str, **extra_fields):
        """Publish status to instance-specific topic"""
        payload = {
            "instance_id": self.instance_id,
            "status": status,
            "timestamp": datetime.now().isoformat(),
            **extra_fields
        }
        self.mqtt_client.publish(self.status_topic, json.dumps(payload))
```

### 4. Event Schema Updates

**events/schema.py:**
```python
class DetectionEvent(BaseModel):
    instance_id: str = Field(..., description="Processor instance identifier (metadata)")
    source_id: int = Field(..., description="Stream/camera source ID (aggregation key)")
    frame_id: int
    timestamp: datetime
    model_id: str
    inference_time_ms: float
    detections: List[Detection]
    fps: Optional[float] = None
    latency_ms: Optional[float] = None
```

**mqtt_sink.py:**
```python
def _create_event(self, prediction: dict, frame: object, actual_source_id: int) -> DetectionEvent:
    return DetectionEvent(
        instance_id=self.config.instance_id,  # Metadata: quién detectó
        source_id=actual_source_id,           # Agregación: qué cámara
        frame_id=frame.frame_id,
        timestamp=frame.frame_timestamp,
        model_id=self.config.model_id,
        inference_time_ms=prediction.get("time", 0) * 1000,
        detections=detections,
        fps=None,
        latency_ms=None,
    )
```

**Detection topic: source_id ONLY (no instance_id in topic):**
```python
# protocol.py - NO CHANGES!
def topic_for_source(source_id: int, prefix: str = "nvr/detections") -> str:
    """
    Generate MQTT topic for detection events.

    Topic aggregates by source_id (camera), NOT by instance_id (processor).
    instance_id is metadata in payload for debugging/analytics.
    """
    return f"{prefix}/{source_id}"
```

**Rationale:**
- Topic = agregación semántica → "Qué se ve en cámara 2"
- Payload.instance_id = metadata → "Quién lo detectó" (debugging, analytics)
- Si 2 processors monitorean cámara 2 → mismo topic, consumers ven ambos

### 5. Metrics Updates

**processor.py - _publish_metrics():**
```python
def _publish_metrics(self, topic: str, payload: dict, retained: bool = False):
    """Publish metrics with instance_id"""
    enriched_payload = {
        "instance_id": self.config.instance_id,
        "timestamp": datetime.now().isoformat(),
        **payload
    }

    # Topic includes instance_id
    full_topic = f"nvr/status/metrics/{self.config.instance_id}"

    self.mqtt_client.publish(
        full_topic,
        json.dumps(enriched_payload),
        qos=0,
        retain=retained
    )
```

### 6. Rename Instance Command (Orchestrator Integration)

**processor.py:**
```python
def _handle_rename_instance(self, params: dict):
    """
    Handle RENAME_INSTANCE command.

    Allows orchestrator to rename instance after spawn.

    Params:
        new_instance_id (str): New instance identifier

    Note:
        With single broadcast topic design, rename is trivial:
        - No need to reconnect control plane (same subscription)
        - Only update config.instance_id
        - Status/metrics topics will use new instance_id automatically
    """
    new_instance_id = params.get('new_instance_id')
    if not new_instance_id:
        raise ValueError("Missing required parameter: new_instance_id")

    old_instance_id = self.config.instance_id

    logger.info(
        "RENAME_INSTANCE command executing",
        extra={
            "component": "processor",
            "event": "rename_instance_start",
            "old_instance_id": old_instance_id,
            "new_instance_id": new_instance_id
        }
    )

    # Update config (simple!)
    self.config.instance_id = new_instance_id

    logger.info(
        "RENAME_INSTANCE completed successfully",
        extra={
            "component": "processor",
            "event": "rename_instance_completed",
            "new_instance_id": new_instance_id
        }
    )

    # Publish status to NEW topic (nvr/control/status/{new_instance_id})
    if self.control_plane:
        self.control_plane.publish_status(
            "running",
            renamed_from=old_instance_id
        )
```

**Beneficio del diseño single broadcast:**
- Rename es **trivial** - solo actualiza `config.instance_id`
- Control plane NO necesita reconnect (sigue subscrito a `nvr/control/commands`)
- Status/metrics usan instance_id dinámicamente del config
- Zero downtime durante rename

---

## Implementation Plan

### Phase 1: Instance ID Generation (Quick Win ⚡)

**Tiempo estimado:** 30 min

**Changes:**
1. Add `instance_id` field to `StreamProcessorConfig` with default factory
2. Add `--instance-id` CLI option
3. Log instance_id on processor start

**Testing:**
```bash
# Auto-generated ID
uv run cupertino-nvr processor --streams 0
# → instance_id: processor-a3f2b1c0

# Custom ID
uv run cupertino-nvr processor --streams 0 --instance-id "processor-hab-0-3"
# → instance_id: processor-hab-0-3
```

**Files:**
- `cupertino_nvr/processor/config.py` - Add field
- `cupertino_nvr/cli.py` - Add CLI option
- `cupertino_nvr/processor/processor.py` - Log on start

### Phase 2: Control Plane Single Broadcast (45 min)

**Changes:**
1. Update `ControlPlane.__init__()` to subscribe only to `nvr/control/commands`
2. Add `_should_process_command()` method for target_instances filtering
3. Update `_on_message()` to check target_instances before executing
4. Update status publishing to include instance_id in topic path

**Testing:**
```bash
# Start 2 processors
uv run cupertino-nvr processor --streams 0,1 --instance-id "proc-a" --enable-control &
uv run cupertino-nvr processor --streams 2,3 --instance-id "proc-b" --enable-control &

# Broadcast status query
mosquitto_pub -t "nvr/control/commands" -m '{
  "command": "status",
  "target_instances": ["*"]
}'
mosquitto_sub -t "nvr/control/status/#" -C 2

# Should see:
# nvr/control/status/proc-a {"instance_id": "proc-a", "status": "running", ...}
# nvr/control/status/proc-b {"instance_id": "proc-b", "status": "running", ...}

# Targeted command
mosquitto_pub -t "nvr/control/commands" -m '{
  "command": "pause",
  "target_instances": ["proc-a"]
}'
mosquitto_sub -t "nvr/control/status/#" -C 1
# Should see only:
# nvr/control/status/proc-a {"instance_id": "proc-a", "status": "paused"}
```

**Files:**
- `cupertino_nvr/processor/control_plane.py` - Single subscription + filtering
- `cupertino_nvr/processor/processor.py` - Status/metrics topics

### Phase 3: Detection Events with Instance ID (20 min)

**Changes:**
1. Add `instance_id` field to `DetectionEvent` schema
2. Update `mqtt_sink._create_event()` to include instance_id in payload
3. **NO CHANGES** to `protocol.py` - topic remains `nvr/detections/{source_id}`

**Testing:**
```bash
# Start 2 processors monitoring SAME camera (transición emergency)
uv run cupertino-nvr processor --streams 2 --instance-id "proc-main" --enable-control &
uv run cupertino-nvr processor --streams 2 --instance-id "emergency-room-2" --model yolov11x-640 --enable-control &

# Subscribe to camera 2 detections (single topic!)
mosquitto_sub -t "nvr/detections/2"

# Should see BOTH processors publishing to same topic:
# {"instance_id": "proc-main", "source_id": 2, "model_id": "yolov8x-640", ...}
# {"instance_id": "emergency-room-2", "source_id": 2, "model_id": "yolov11x-640", ...}

# Topic = aggregation by camera
# Payload.instance_id = metadata for debugging
```

**Files:**
- `cupertino_nvr/events/schema.py` - Add instance_id field
- `cupertino_nvr/processor/mqtt_sink.py` - Include instance_id in payload
- `cupertino_nvr/events/protocol.py` - **NO CHANGES** (topic stays as-is)

### Phase 4: Multi-Target Commands (30 min)

**Changes:**
1. Test list of target_instances (already implemented in Phase 2!)
2. Add integration test for N-to-M communication pattern

**Testing:**
```bash
# Start 3 processors
uv run cupertino-nvr processor --streams 0,1 --instance-id "proc-a" --enable-control &
uv run cupertino-nvr processor --streams 2,3 --instance-id "proc-b" --enable-control &
uv run cupertino-nvr processor --streams 4,5 --instance-id "proc-c" --enable-control &

# Command to specific list (proc-a and proc-c, NOT proc-b)
mosquitto_pub -t "nvr/control/commands" -m '{
  "command": "set_fps",
  "params": {"max_fps": 0.05},
  "target_instances": ["proc-a", "proc-c"]
}'

# Verify only proc-a and proc-c changed FPS
mosquitto_pub -t "nvr/control/commands" -m '{"command": "status"}'
mosquitto_sub -t "nvr/control/status/#" -C 3

# Should see:
# proc-a: max_fps: 0.05 ✅
# proc-b: max_fps: 1.0  ✅ (no cambió)
# proc-c: max_fps: 0.05 ✅
```

**Files:**
- No code changes (functionality implemented in Phase 2)
- Add integration tests for multi-target scenarios

### Phase 5: Rename Command (Orchestrator Integration) (30 min)

**Changes:**
1. Add `rename_instance` command handler
2. Register command in `_setup_control_commands()`
3. Test orchestrator workflow

**Testing:**
```bash
# Start processor with auto-generated ID
uv run cupertino-nvr processor --streams 2 --enable-control
# → instance_id: processor-a3f2b1c0

# Orchestrator gets instance_id from status
mosquitto_sub -t "nvr/control/status/#" -C 1
# nvr/control/status/processor-a3f2b1c0 {"instance_id": "processor-a3f2b1c0", ...}

# Orchestrator renames it (targeted command)
mosquitto_pub -t "nvr/control/commands" -m '{
  "command": "rename_instance",
  "params": {"new_instance_id": "emergency-room-2"},
  "target_instances": ["processor-a3f2b1c0"]
}'

# Verify new instance_id in status
mosquitto_sub -t "nvr/control/status/#" -C 1
# nvr/control/status/emergency-room-2 {"instance_id": "emergency-room-2", "renamed_from": "processor-a3f2b1c0", ...}

# Verify new instance_id in detections
mosquitto_sub -t "nvr/detections/2" -C 1
# {"instance_id": "emergency-room-2", "source_id": 2, ...}

# Verify can still control with new name
mosquitto_pub -t "nvr/control/commands" -m '{
  "command": "pause",
  "target_instances": ["emergency-room-2"]
}'
```

**Beneficio del diseño:**
- Rename es trivial (solo actualiza `config.instance_id`)
- No reconnect needed (single broadcast topic)
- Zero downtime
- Status/metrics/detections usan instance_id dinámicamente

**Files:**
- `cupertino_nvr/processor/processor.py` - Add `_handle_rename_instance()`

---

## Use Case: Emergency Spawn Workflow

```python
# Orchestrator (pseudo-code)

def on_fall_detected(room_id: int):
    """Handle fall detection in room_id"""

    # Step 1: Remove from main processor
    mqtt_pub("nvr/control/commands/processor-main", {
        "command": "remove_stream",
        "params": {"source_id": room_id}
    })

    # Step 2: Reduce FPS on other processors (free CPU)
    mqtt_pub("nvr/control/commands", {  # Broadcast
        "command": "set_fps",
        "params": {"max_fps": 0.05}
    })

    # Step 3: Spawn dedicated high-precision processor
    proc = subprocess.Popen([
        "cupertino-nvr", "processor",
        "--streams", str(room_id),
        "--model", "yolov11x-640",
        "--max-fps", "1.0",
        "--enable-control"
        # instance_id auto-generated: processor-xyz123
    ])

    # Step 4: Wait for processor to start
    time.sleep(2)

    # Step 5: Get auto-generated instance_id from status
    status = mqtt_sub_wait("nvr/control/status/#", timeout=5)
    auto_instance_id = status["instance_id"]  # "processor-xyz123"

    # Step 6: Rename to semantic name
    mqtt_pub(f"nvr/control/commands/{auto_instance_id}", {
        "command": "rename_instance",
        "params": {"new_instance_id": f"emergency-room-{room_id}"}
    })

    # Step 7: Monitor metrics from emergency processor
    mqtt_sub(f"nvr/status/metrics/emergency-room-{room_id}", callback=log_metrics)

    # Step 8: Monitor detections from emergency processor
    mqtt_sub(f"nvr/detections/emergency-room-{room_id}/#", callback=handle_detections)

def on_resident_assisted(room_id: int):
    """Resident assisted, return to normal"""

    # Step 1: Stop emergency processor
    mqtt_pub(f"nvr/control/commands/emergency-room-{room_id}", {
        "command": "stop"
    })

    # Step 2: Add back to main processor
    mqtt_pub("nvr/control/commands/processor-main", {
        "command": "add_stream",
        "params": {"source_id": room_id}
    })

    # Step 3: Restore FPS on all processors
    mqtt_pub("nvr/control/commands", {  # Broadcast
        "command": "set_fps",
        "params": {"max_fps": 0.1}
    })
```

---

## Benefits

### ✅ Multi-Instance Orchestration
- Orchestrator puede controlar N processors independientemente
- Spawn/kill processors dinámicamente según carga
- Assign semantic names (emergency-room-2, processor-hab-0-3, etc.)
- Single broadcast topic = simple subscription pattern

### ✅ Broadcast + Targeted + Multi-Target Flexibility
```bash
# Broadcast: "All processors, report status"
mosquitto_pub -t "nvr/control/commands" -m '{
  "command": "status",
  "target_instances": ["*"]
}'

# Targeted: "Only emergency-room-2, change to high precision"
mosquitto_pub -t "nvr/control/commands" -m '{
  "command": "change_model",
  "params": {"model_id": "yolov11x-640"},
  "target_instances": ["emergency-room-2"]
}'

# Multi-target: "proc-a and proc-c, lower FPS"
mosquitto_pub -t "nvr/control/commands" -m '{
  "command": "set_fps",
  "params": {"max_fps": 0.05},
  "target_instances": ["proc-a", "proc-c"]
}'
```

### ✅ Camera-Centric Detection Aggregation
Dos processors pueden monitorear la misma cámara (transición emergency):
```bash
# Topic agregado por cámara (NO por processor)
mosquitto_sub -t "nvr/detections/2"

# Recibe detecciones de AMBOS processors:
{"instance_id": "processor-main", "source_id": 2, "model_id": "yolov8x-640", ...}
{"instance_id": "emergency-room-2", "source_id": 2, "model_id": "yolov11x-640", ...}

# Wall/Orchestrator ve TODAS las detecciones de cámara 2
# instance_id en payload para distinguir origen (debugging/analytics)
```

### ✅ Metrics per Instance
```bash
# Comparar performance de processors
mosquitto_sub -t "nvr/status/metrics/#"

# processor-main: inference_throughput: 1.2 fps
# emergency-room-2: inference_throughput: 0.95 fps (high precision = slower)
```

### ✅ Zero Downtime Rename
- Orchestrator puede renombrar processors después de spawn
- Single broadcast = no need to reconnect
- Trivial implementation (solo actualizar `config.instance_id`)

---

## Migration Path

### Backward Compatibility

**Default behavior (no instance_id specified):**
- Auto-generates instance_id: `processor-{random}`
- Topics include instance_id
- Existing code works sin cambios

**Transition period:**
- Phase 1-2: Instance ID en logs y status (no breaking changes)
- Phase 3: Detection events con instance_id (schema change - version bump)
- Phase 4-5: Full orchestration support

**Wall compatibility:**
Wall necesita actualizar para parsear nuevos topics:
```python
# ANTES
topic_pattern = "nvr/detections/#"
# Parseaba: nvr/detections/{source_id}

# AHORA
topic_pattern = "nvr/detections/#"
# Parsea: nvr/detections/{instance_id}/{source_id}
```

---

## Testing Strategy

### Unit Tests
- `test_instance_id_generation()` - Verify auto-generation + custom
- `test_control_plane_dual_subscription()` - Broadcast + targeted
- `test_targeted_command_filtering()` - Verify target_instance filtering
- `test_detection_event_with_instance_id()` - Schema validation
- `test_rename_instance()` - Verify reconnection logic

### Integration Tests
- Multi-processor scenario (2+ processors)
- Broadcast vs targeted commands
- Emergency spawn workflow (remove → spawn → rename → monitor)
- Detection topic parsing with instance_id

### Manual Testing Checklist
- [ ] Start processor with auto-generated instance_id
- [ ] Start processor with custom instance_id
- [ ] Broadcast status command to 2 processors
- [ ] Targeted pause command to 1 processor
- [ ] Verify detection topics include instance_id
- [ ] Verify metrics topics include instance_id
- [ ] Rename instance via MQTT
- [ ] Verify topics update after rename

---

## References

- **IoT Device Identification Patterns** - AWS IoT Core, Azure IoT Hub
- **MQTT Topic Design** - https://www.hivemq.com/blog/mqtt-essentials-part-5-mqtt-topics-best-practices/
- **GO2RTC_PROXY_ARCHITECTURE.md** - Similar abstraction pattern
- **DYNAMIC_ORCHESTRATION_SUMMARY.md** - Foundation for multi-instance control

---

## Summary: Design Wins

**Smart Endpoints, Dumb Pipes:**
- Single broadcast topic (`nvr/control/commands`) para comandos
- Filtering en application layer (payload `target_instances`)
- Topic hierarchy simple y estable

**Camera-Centric Aggregation:**
- Detection topics por `source_id` (cámara), no por `instance_id` (processor)
- Natural aggregation: "Qué se ve en cámara 2"
- `instance_id` como metadata en payload

**Trivial Rename:**
- No reconnect needed (single broadcast)
- Solo actualizar `config.instance_id`
- Zero downtime

**N-to-M Communication:**
- Broadcast: `target_instances: ["*"]`
- Single target: `target_instances: ["proc-a"]`
- Multi-target: `target_instances: ["proc-a", "proc-c"]`

---

**Tiempo total estimado:** 2.5 horas (simplified with single broadcast design)

**Breakdown:**
- Phase 1 (instance_id generation): 30 min
- Phase 2 (control plane broadcast + filtering): 45 min
- Phase 3 (detection events with instance_id): 20 min
- Phase 4 (multi-target testing): 30 min
- Phase 5 (rename command): 30 min

**Co-Authored-By:** Gaby <noreply@visiona.com>
