# Discovery & Heartbeat Pattern

**Fecha:** 2025-10-25
**Tipo:** Architecture Pattern - Orchestrator Integration
**Estado:** Plan (integrates with Instance Identification)

---

## Objetivo

Permitir que **orchestrator** descubra processors vivos y sincronice su configuración actual mediante **PING/PONG protocol**.

**Use Cases:**
- Orchestrator startup → discover all alive processors
- Health check → verify specific processor is alive
- Config sync → rebuild registry after network partition
- Dead processor detection → detect cuando processor se muere

---

## Pattern: PING/PONG + Auto-Announce

### 1. Auto-Announce on Startup

**Processor publica "alive" al iniciar:**
```python
# processor.py - start()
def start(self):
    self._start_time = time.time()  # Track uptime

    # ... initialize pipeline ...

    # Auto-announce on startup
    if self.control_plane:
        self.control_plane.publish_status(
            "starting",
            uptime_seconds=0,
            config={
                "stream_uris": self.config.stream_uris,
                "source_id_mapping": self.config.source_id_mapping,
                "model_id": self.config.model_id,
                "max_fps": self.config.max_fps,
                "stream_server": self.config.stream_server,
            }
        )
```

**Orchestrator escucha announces:**
```python
# Orchestrator subscribes to all status messages
mqtt_sub("nvr/control/status/#", callback=register_processor)

# When processor starts:
# nvr/control/status/proc-a {"instance_id": "proc-a", "status": "starting", ...}
```

### 2. PING/PONG Protocol

**Orchestrator envía PING:**
```bash
# Broadcast - discover all
mosquitto_pub -t "nvr/control/commands" -m '{
  "command": "ping",
  "target_instances": ["*"]
}'

# Targeted - check specific processor
mosquitto_pub -t "nvr/control/commands" -m '{
  "command": "ping",
  "target_instances": ["emergency-room-2"]
}'

# Multi-target - check list
mosquitto_pub -t "nvr/control/commands" -m '{
  "command": "ping",
  "target_instances": ["proc-a", "proc-b", "proc-c"]
}'
```

**Processor responde PONG:**
```json
// Topic: nvr/control/status/{instance_id}
{
  "instance_id": "processor-hab-0-3",
  "status": "running",
  "uptime_seconds": 3600,
  "config": {
    "stream_uris": ["rtsp://localhost:8554/0", "rtsp://localhost:8554/1"],
    "source_id_mapping": [0, 1],
    "model_id": "yolov8x-640",
    "max_fps": 0.1,
    "stream_server": "rtsp://localhost:8554"
  },
  "health": {
    "is_paused": false,
    "pipeline_running": true,
    "mqtt_connected": true,
    "control_plane_connected": true
  },
  "timestamp": "2025-10-25T10:30:00.123456"
}
```

### 3. Optional: Periodic Heartbeat

**Processor publica heartbeat cada N segundos:**
```python
# processor.py
def _start_heartbeat_thread(self):
    """Start periodic heartbeat publishing"""
    def heartbeat_loop():
        while self.is_running:
            if self.control_plane:
                self.control_plane.publish_status(
                    self._get_current_status(),
                    uptime_seconds=time.time() - self._start_time,
                    heartbeat=True  # Flag: periodic heartbeat
                )
            time.sleep(self.config.heartbeat_interval)

    thread = threading.Thread(target=heartbeat_loop, daemon=True)
    thread.start()

# config.py
@dataclass
class StreamProcessorConfig:
    heartbeat_interval: int = 30  # 0 = disabled
```

**Beneficio:** Orchestrator detecta processors muertos sin hacer PING explícito.

---

## Implementation

### Phase 1: PING Command (30 min)

**processor.py:**
```python
def _handle_ping(self):
    """
    Handle PING command - respond with PONG (full status + config).

    Allows orchestrator to:
    - Discover alive processors
    - Sync configuration state
    - Health check
    """
    logger.info(
        "PING received",
        extra={
            "component": "processor",
            "event": "ping_received",
            "instance_id": self.config.instance_id
        }
    )

    # Calculate uptime
    uptime_seconds = time.time() - self._start_time

    # Build PONG response
    pong = {
        "instance_id": self.config.instance_id,
        "status": self._get_current_status(),
        "uptime_seconds": uptime_seconds,
        "config": {
            "stream_uris": self.config.stream_uris,
            "source_id_mapping": self.config.source_id_mapping,
            "model_id": self.config.model_id,
            "max_fps": self.config.max_fps,
            "stream_server": self.config.stream_server,
            "mqtt_topic_prefix": self.config.mqtt_topic_prefix,
        },
        "health": {
            "is_paused": self.is_paused,
            "pipeline_running": self.is_running and self.pipeline is not None,
            "mqtt_connected": self.mqtt_client.is_connected() if self.mqtt_client else False,
            "control_plane_connected": self.control_plane is not None,
        },
        "timestamp": datetime.now().isoformat()
    }

    # Publish PONG to status topic
    if self.control_plane:
        # publish_status already includes instance_id in topic
        self.control_plane.publish_status(
            status=pong["status"],
            uptime_seconds=pong["uptime_seconds"],
            config=pong["config"],
            health=pong["health"],
            pong=True  # Flag to indicate PING response
        )

    logger.info(
        "PONG sent",
        extra={
            "component": "processor",
            "event": "pong_sent",
            "instance_id": self.config.instance_id,
            "uptime_seconds": uptime_seconds
        }
    )

def _get_current_status(self) -> str:
    """Get current processor status"""
    if not self.is_running:
        return "stopped"
    if self.is_paused:
        return "paused"
    if hasattr(self, '_is_restarting') and self._is_restarting:
        return "restarting"
    return "running"

def start(self):
    """Start processor (existing method - enhance)"""
    import time

    # Track start time for uptime calculation
    self._start_time = time.time()

    # ... existing start logic ...

    # Auto-announce on startup
    if self.control_plane:
        self.control_plane.publish_status(
            "starting",
            uptime_seconds=0,
            config={
                "stream_uris": self.config.stream_uris,
                "source_id_mapping": self.config.source_id_mapping,
                "model_id": self.config.model_id,
                "max_fps": self.config.max_fps,
                "stream_server": self.config.stream_server,
            }
        )

def _setup_control_commands(self):
    """Register MQTT control commands (existing method - enhance)"""
    # ... existing commands ...

    # Add PING command
    registry.register(
        'ping',
        self._handle_ping,
        "Health check / discovery (responds with PONG + full config)"
    )
```

### Phase 2: Orchestrator Registry (Python Example)

**orchestrator/processor_registry.py:**
```python
"""
Processor Registry - Maintains list of alive processors.
"""

import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class ProcessorRegistry:
    """
    Maintains registry of alive processors.

    Features:
    - Auto-discovery on startup (PING broadcast)
    - Real-time updates from status messages
    - Dead processor detection (last_seen timeout)
    - Query by status, config, health
    """

    def __init__(self, mqtt_client: mqtt.Client, timeout_seconds: int = 60):
        self.mqtt_client = mqtt_client
        self.timeout_seconds = timeout_seconds
        self.processors: Dict[str, dict] = {}

        # Subscribe to all status messages
        self.mqtt_client.subscribe("nvr/control/status/#")
        self.mqtt_client.message_callback_add(
            "nvr/control/status/#",
            self._on_status_message
        )

        logger.info("ProcessorRegistry initialized")

    def _on_status_message(self, client, userdata, msg):
        """Update registry when processor publishes status"""
        try:
            payload = json.loads(msg.payload)
            instance_id = payload.get("instance_id")

            if not instance_id:
                return

            # Update registry
            self.processors[instance_id] = {
                "instance_id": instance_id,
                "status": payload.get("status"),
                "config": payload.get("config", {}),
                "health": payload.get("health", {}),
                "uptime_seconds": payload.get("uptime_seconds", 0),
                "last_seen": datetime.now(),
                "heartbeat": payload.get("heartbeat", False),
                "pong": payload.get("pong", False),
            }

            logger.debug(
                f"Processor updated: {instance_id}",
                extra={"instance_id": instance_id, "status": payload.get("status")}
            )

        except Exception as e:
            logger.error(f"Error processing status message: {e}")

    def discover_all(self, timeout: float = 2.0) -> Dict[str, dict]:
        """
        Discover all alive processors via PING broadcast.

        Args:
            timeout: Seconds to wait for PONG responses

        Returns:
            Dictionary of alive processors {instance_id: processor_data}
        """
        logger.info("Discovering processors (PING broadcast)...")

        # Send PING broadcast
        self.mqtt_client.publish(
            "nvr/control/commands",
            json.dumps({"command": "ping", "target_instances": ["*"]})
        )

        # Wait for PONG responses
        time.sleep(timeout)

        # Return alive processors
        alive = self.get_alive_processors()
        logger.info(f"Discovered {len(alive)} processors", extra={"count": len(alive)})

        return alive

    def ping(self, instance_id: str, timeout: float = 1.0) -> bool:
        """
        Check if specific processor is alive via targeted PING.

        Args:
            instance_id: Processor to check
            timeout: Seconds to wait for PONG

        Returns:
            True if processor responded, False otherwise
        """
        # Send targeted PING
        self.mqtt_client.publish(
            "nvr/control/commands",
            json.dumps({"command": "ping", "target_instances": [instance_id]})
        )

        # Wait for PONG
        start = time.time()
        initial_last_seen = self.processors.get(instance_id, {}).get("last_seen")

        while time.time() - start < timeout:
            processor = self.processors.get(instance_id)
            if processor:
                last_seen = processor.get("last_seen")
                # Check if last_seen updated (new PONG received)
                if last_seen and last_seen != initial_last_seen:
                    logger.info(f"Processor {instance_id} is alive")
                    return True

            time.sleep(0.1)

        logger.warning(f"Processor {instance_id} did not respond to PING")
        return False

    def get_alive_processors(self) -> Dict[str, dict]:
        """
        Get all alive processors (last_seen < timeout).

        Returns:
            Dictionary of alive processors
        """
        now = datetime.now()
        timeout_delta = timedelta(seconds=self.timeout_seconds)

        alive = {
            instance_id: proc
            for instance_id, proc in self.processors.items()
            if (now - proc.get("last_seen", now)) < timeout_delta
        }

        return alive

    def get_dead_processors(self) -> Dict[str, dict]:
        """
        Get all dead processors (last_seen > timeout).

        Returns:
            Dictionary of dead processors
        """
        now = datetime.now()
        timeout_delta = timedelta(seconds=self.timeout_seconds)

        dead = {
            instance_id: proc
            for instance_id, proc in self.processors.items()
            if (now - proc.get("last_seen", now)) >= timeout_delta
        }

        return dead

    def get_by_status(self, status: str) -> Dict[str, dict]:
        """Get processors with specific status (running, paused, etc)"""
        return {
            instance_id: proc
            for instance_id, proc in self.get_alive_processors().items()
            if proc.get("status") == status
        }

    def get_by_model(self, model_id: str) -> Dict[str, dict]:
        """Get processors using specific model"""
        return {
            instance_id: proc
            for instance_id, proc in self.get_alive_processors().items()
            if proc.get("config", {}).get("model_id") == model_id
        }

    def get_monitoring_source(self, source_id: int) -> List[str]:
        """Get list of processors monitoring specific source/camera"""
        monitoring = []

        for instance_id, proc in self.get_alive_processors().items():
            source_ids = proc.get("config", {}).get("source_id_mapping", [])
            if source_id in source_ids:
                monitoring.append(instance_id)

        return monitoring

    def summary(self) -> dict:
        """Get registry summary"""
        alive = self.get_alive_processors()
        dead = self.get_dead_processors()

        return {
            "total": len(self.processors),
            "alive": len(alive),
            "dead": len(dead),
            "by_status": {
                "running": len(self.get_by_status("running")),
                "paused": len(self.get_by_status("paused")),
                "stopped": len(self.get_by_status("stopped")),
                "restarting": len(self.get_by_status("restarting")),
            }
        }


# Usage example
if __name__ == "__main__":
    import paho.mqtt.client as mqtt

    # Setup MQTT
    client = mqtt.Client()
    client.connect("localhost", 1883)
    client.loop_start()

    # Create registry
    registry = ProcessorRegistry(client, timeout_seconds=60)

    # Discover all processors
    alive = registry.discover_all()
    print(f"Found {len(alive)} processors:")
    for instance_id, proc in alive.items():
        print(f"  - {instance_id}: {proc['status']}, model={proc['config']['model_id']}")

    # Check specific processor
    if registry.ping("emergency-room-2"):
        print("emergency-room-2 is alive")
    else:
        print("emergency-room-2 is dead or not responding")

    # Get processors by status
    running = registry.get_by_status("running")
    print(f"{len(running)} processors running")

    # Get processors monitoring camera 2
    monitoring_2 = registry.get_monitoring_source(2)
    print(f"Processors monitoring camera 2: {monitoring_2}")

    # Summary
    summary = registry.summary()
    print(f"Registry summary: {summary}")
```

---

## Use Cases

### 1. Orchestrator Startup (Discovery)

```python
# orchestrator.py

import paho.mqtt.client as mqtt
from processor_registry import ProcessorRegistry

# Setup
client = mqtt.Client()
client.connect("localhost", 1883)
client.loop_start()

registry = ProcessorRegistry(client)

# Discover all processors on startup
alive = registry.discover_all(timeout=2.0)

print(f"Orchestrator started - found {len(alive)} processors:")
for instance_id, proc in alive.items():
    config = proc['config']
    print(f"  {instance_id}:")
    print(f"    status: {proc['status']}")
    print(f"    model: {config['model_id']}")
    print(f"    streams: {config['source_id_mapping']}")
    print(f"    uptime: {proc['uptime_seconds']}s")
```

### 2. Emergency Spawn with Discovery

```python
def on_fall_detected(room_id: int):
    """Handle fall detection - spawn dedicated processor"""

    # Step 1: Check if emergency processor already exists
    monitoring = registry.get_monitoring_source(room_id)
    emergency_id = f"emergency-room-{room_id}"

    if emergency_id in monitoring:
        logger.warning(f"Emergency processor {emergency_id} already exists")
        return

    # Step 2: Remove from main processor
    main_procs = [p for p in monitoring if p.startswith("processor-main")]
    for proc_id in main_procs:
        mqtt_pub("nvr/control/commands", {
            "command": "remove_stream",
            "params": {"source_id": room_id},
            "target_instances": [proc_id]
        })

    # Step 3: Spawn dedicated processor
    proc = subprocess.Popen([
        "cupertino-nvr", "processor",
        "--streams", str(room_id),
        "--model", "yolov11x-640",
        "--max-fps", "1.0",
        "--enable-control"
    ])

    # Step 4: Wait for auto-announce (processor startup)
    time.sleep(2)

    # Step 5: Discover auto-generated instance_id
    alive = registry.get_alive_processors()
    new_processors = [
        p for p in alive.values()
        if room_id in p["config"]["source_id_mapping"]
        and p["instance_id"].startswith("processor-")  # Auto-generated
        and p["uptime_seconds"] < 10  # Recently started
    ]

    if not new_processors:
        logger.error("Failed to discover new processor")
        return

    auto_instance_id = new_processors[0]["instance_id"]

    # Step 6: Rename to semantic name
    mqtt_pub("nvr/control/commands", {
        "command": "rename_instance",
        "params": {"new_instance_id": emergency_id},
        "target_instances": [auto_instance_id]
    })

    logger.info(f"Emergency processor spawned: {emergency_id}")
```

### 3. Health Monitor (Periodic Check)

```python
def health_monitor_loop():
    """Periodic health check for all processors"""

    while True:
        # Get dead processors
        dead = registry.get_dead_processors()

        if dead:
            logger.warning(f"Detected {len(dead)} dead processors")
            for instance_id, proc in dead.items():
                last_seen = proc.get("last_seen")
                logger.error(
                    f"Processor {instance_id} is dead",
                    extra={
                        "instance_id": instance_id,
                        "last_seen": last_seen,
                        "config": proc.get("config")
                    }
                )

                # Alert / restart logic
                # ...

        # Summary log
        summary = registry.summary()
        logger.info("Health check", extra=summary)

        time.sleep(30)  # Check every 30 seconds
```

---

## Testing

```bash
# Terminal 1: Start orchestrator mock
python3 -c "
import paho.mqtt.client as mqtt
import json

def on_message(client, userdata, msg):
    payload = json.loads(msg.payload)
    print(f'{msg.topic}: {json.dumps(payload, indent=2)}')

client = mqtt.Client()
client.on_message = on_message
client.connect('localhost', 1883)
client.subscribe('nvr/control/status/#')
client.loop_forever()
"

# Terminal 2: Start processor 1
uv run cupertino-nvr processor --streams 0,1 --instance-id "proc-a" --enable-control

# Terminal 1 should see auto-announce:
# nvr/control/status/proc-a {"instance_id": "proc-a", "status": "starting", ...}

# Terminal 3: Start processor 2
uv run cupertino-nvr processor --streams 2,3 --instance-id "proc-b" --enable-control

# Terminal 4: Orchestrator discovers all
mosquitto_pub -t "nvr/control/commands" -m '{"command": "ping", "target_instances": ["*"]}'

# Terminal 1 should see PONG from both:
# nvr/control/status/proc-a {"instance_id": "proc-a", "status": "running", "config": {...}, ...}
# nvr/control/status/proc-b {"instance_id": "proc-b", "status": "running", "config": {...}, ...}

# Terminal 4: Check specific processor
mosquitto_pub -t "nvr/control/commands" -m '{"command": "ping", "target_instances": ["proc-a"]}'

# Terminal 1 should see PONG only from proc-a

# Terminal 4: Kill processor 2
pkill -f "processor.*proc-b"

# Wait 60 seconds (timeout)

# Terminal 4: Discover again
mosquitto_pub -t "nvr/control/commands" -m '{"command": "ping", "target_instances": ["*"]}'

# Terminal 1 should see PONG only from proc-a (proc-b is dead)
```

---

## Integration with Instance Identification

Este pattern se integra como **Phase 1.5** en el plan de Instance Identification:

**Timeline:**
1. Phase 1: Instance ID generation + auto-announce on startup
2. **Phase 1.5: PING/PONG command (30 min)**
3. Phase 2: Control plane single broadcast + filtering
4. Phase 3: Detection events with instance_id
5. Phase 4: Multi-target testing
6. Phase 5: Rename command

**Files:**
- `cupertino_nvr/processor/processor.py` - Add `_handle_ping()`, `_get_current_status()`, track `_start_time`
- Orchestrator example: `orchestrator/processor_registry.py` (separate repo/package)

---

## Benefits

### ✅ Zero-Config Discovery
Orchestrator descubre processors sin configuración previa

### ✅ Real-Time Registry
Registry se actualiza en tiempo real con status messages

### ✅ Dead Processor Detection
Detect processors muertos por timeout en last_seen

### ✅ Config Synchronization
PONG incluye configuración completa → orchestrator puede reconstruir estado

### ✅ Flexible Queries
- By status (running, paused, etc)
- By model (yolov8x-640, yolov11x-640, etc)
- By source (qué processors monitorean cámara X)

---

**Co-Authored-By:** Gaby <noreply@visiona.com>
