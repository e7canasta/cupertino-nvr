# MQTT Control Plane

The Cupertino NVR processor now supports remote control via MQTT commands.

## Overview

The MQTT Control Plane allows you to remotely control the stream processor using simple JSON commands published to an MQTT topic. This is useful for:

- **Remote Management**: Control processing from anywhere without direct access
- **Integration**: Integrate with home automation systems (Home Assistant, Node-RED, etc.)
- **Automation**: Build automated workflows that pause/resume processing based on events
- **Monitoring**: Query status and receive updates

## Enabling Control Plane

### Via CLI

```bash
cupertino-nvr processor \
    --n 6 \
    --model yolov8x-640 \
    --mqtt-host localhost \
    --enable-control \
    --control-topic nvr/control/commands \
    --status-topic nvr/control/status
```

### Via Python API

```python
from cupertino_nvr.processor import StreamProcessor, StreamProcessorConfig

config = StreamProcessorConfig(
    stream_uris=["rtsp://localhost:8554/live/0.stream"],
    model_id="yolov8x-640",
    mqtt_host="localhost",
    mqtt_port=1883,
    enable_control_plane=True,  # Enable control plane
    control_command_topic="nvr/control/commands",
    control_status_topic="nvr/control/status",
)

processor = StreamProcessor(config)
processor.start()
processor.join()
```

## Available Commands

All commands are sent as JSON payloads to the control topic.

### PAUSE

Temporarily pause stream processing (stops inference but keeps streams connected).

```bash
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "pause"}'
```

**Response**: Status update published to status topic: `{"status": "paused", ...}`

### RESUME

Resume processing after a pause.

```bash
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "resume"}'
```

**Response**: Status update published to status topic: `{"status": "running", ...}`

### STOP

Stop the processor completely (terminates the application).

```bash
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "stop"}'
```

**Response**: Status update published to status topic: `{"status": "stopped", ...}`

**Note**: After STOP, you need to restart the processor manually.

### STATUS

Query current processor status.

```bash
mosquitto_pub -h localhost -t "nvr/control/commands" -m '{"command": "status"}'
```

**Response**: Current status published to status topic.

Possible statuses:
- `running`: Processor is actively processing streams
- `paused`: Processor is paused (streams connected but no inference)
- `stopped`: Processor is stopped
- `connected`: Control plane connected (initial state)

## Status Messages

Status updates are published to the status topic with the following format:

```json
{
  "status": "running",
  "timestamp": "2025-10-25T10:30:00.123456",
  "client_id": "nvr_processor_control"
}
```

### Subscribing to Status Updates

```bash
mosquitto_sub -h localhost -t "nvr/control/status"
```

## Integration Examples

### Home Assistant

```yaml
# configuration.yaml
mqtt:
  sensor:
    - name: "NVR Processor Status"
      state_topic: "nvr/control/status"
      value_template: "{{ value_json.status }}"
      
  button:
    - name: "NVR Pause"
      command_topic: "nvr/control/commands"
      payload_press: '{"command": "pause"}'
      
    - name: "NVR Resume"
      command_topic: "nvr/control/commands"
      payload_press: '{"command": "resume"}'
      
    - name: "NVR Stop"
      command_topic: "nvr/control/commands"
      payload_press: '{"command": "stop"}'
```

### Node-RED

```json
// Inject node payload
{
  "command": "pause"
}

// MQTT out node
Topic: nvr/control/commands
QoS: 1
```

### Python Script

```python
import paho.mqtt.client as mqtt
import json

client = mqtt.Client()
client.connect("localhost", 1883)

# Pause processor
client.publish(
    "nvr/control/commands",
    json.dumps({"command": "pause"}),
    qos=1
)

# Query status
client.publish(
    "nvr/control/commands",
    json.dumps({"command": "status"}),
    qos=1
)

client.disconnect()
```

## Architecture

The control plane is based on the same architecture used in the Adeline inference service:

- **MQTTControlPlane**: Manages MQTT connection and message handling
- **CommandRegistry**: Explicit registry of available commands
- **QoS 1**: At-least-once delivery for reliable command execution
- **Retained Status**: Status messages are retained for new subscribers

## Comparison with Adeline

| Feature | Cupertino NVR | Adeline |
|---------|---------------|---------|
| PAUSE/RESUME | ✅ | ✅ |
| STOP | ✅ | ✅ |
| STATUS | ✅ | ✅ |
| METRICS | ❌ | ✅ |
| HEALTH | ❌ | ✅ |
| TOGGLE_CROP | ❌ | ✅ (adaptive ROI only) |
| STABILIZATION_STATS | ❌ | ✅ (if enabled) |

The Cupertino NVR implementation focuses on basic control commands for a headless processor. Adeline includes additional features like metrics, health checks, and adaptive ROI control.

## Troubleshooting

### Control plane not connecting

- Verify MQTT broker is running: `systemctl status mosquitto`
- Check broker connectivity: `mosquitto_pub -h localhost -t test -m "hello"`
- Check logs for connection errors

### Commands not working

- Verify control plane is enabled: `--enable-control` flag
- Check command topic matches: default is `nvr/control/commands`
- Verify JSON format is correct
- Check logs for command execution errors

### Status not updating

- Subscribe to status topic: `mosquitto_sub -h localhost -t "nvr/control/status"`
- Verify status topic matches: default is `nvr/control/status`
- Check QoS settings (should be 1 for control plane)

## Security Considerations

### Authentication

If your MQTT broker requires authentication, pass credentials via config:

```python
config = StreamProcessorConfig(
    # ... other config ...
    mqtt_username="your_username",
    mqtt_password="your_password",
)
```

Or via environment variables:
```bash
export MQTT_USERNAME=your_username
export MQTT_PASSWORD=your_password
```

### Access Control

Consider using MQTT ACLs to restrict who can publish to control topics:

```
# mosquitto.acl
user nvr_processor
topic write nvr/control/status

user control_client
topic write nvr/control/commands
topic read nvr/control/status
```

### TLS/SSL

For production deployments, use TLS encryption:

```python
# TODO: Add TLS support to control plane
# Currently supports plaintext only
```

## Future Enhancements

- [ ] Add METRICS command (publish watchdog stats)
- [ ] Add HEALTH command (system health check)
- [ ] TLS/SSL support
- [ ] Command authentication/authorization
- [ ] Graceful reconnection on broker disconnect
- [ ] Command history/audit log

