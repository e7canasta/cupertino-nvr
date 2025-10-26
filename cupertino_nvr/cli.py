"""
CLI entry point for cupertino-nvr
"""

import logging
import os

import click

# ============================================================================
# DISABLE HEAVY MODELS - MUST RUN BEFORE IMPORTING INFERENCE
# ============================================================================
# Deshabilitar modelos pesados que no necesitamos para YOLO-only processing
# Esto previene lockeos en InferencePipeline por intentos de download/init
# (Same approach as Adeline - see referencias/adeline/env_setup.py)
DISABLED_MODELS = [
    "PALIGEMMA", "FLORENCE2", "QWEN_2_5",
    "CORE_MODEL_SAM", "CORE_MODEL_SAM2", "CORE_MODEL_CLIP",
    "CORE_MODEL_GAZE", "SMOLVLM2", "DEPTH_ESTIMATION",
    "MOONDREAM2", "CORE_MODEL_TROCR", "CORE_MODEL_GROUNDINGDINO",
    "CORE_MODEL_YOLO_WORLD", "CORE_MODEL_PE",
]

for model in DISABLED_MODELS:
    os.environ[f"{model}_ENABLED"] = "False"

# Debug: Verificar que env vars están seteadas
if os.getenv("DEBUG_ENV_VARS", "false").lower() == "true":
    import sys
    print("🔧 [DEBUG] Disabled models env vars:", file=sys.stderr)
    for model in DISABLED_MODELS:
        print(f"   {model}_ENABLED = {os.environ.get(f'{model}_ENABLED')}", file=sys.stderr)

from cupertino_nvr.logging_utils import setup_structured_logging

# Configure structured logging
# Use JSON format for production, human-readable for development
JSON_LOGS = os.getenv("JSON_LOGS", "false").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

setup_structured_logging(
    level=LOG_LEVEL,
    json_format=JSON_LOGS,
    output_file=None  # Can be set via env: LOG_FILE
)


@click.group()
def main():
    """Cupertino NVR - Distributed Network Video Recorder"""
    pass


@main.command()
@click.option("--n", type=int, default=6, help="Number of streams (used if --start/--end/--streams not specified)")
@click.option("--start", type=int, default=None, help="Start stream index (e.g., 1 for live/1.stream)")
@click.option("--end", type=int, default=None, help="End stream index (inclusive, e.g., 4 for live/4.stream)")
@click.option("--streams", type=str, default=None, help="Specific stream indices, comma-separated (e.g., '1,3,6' for live/1.stream, live/3.stream, live/6.stream)")
@click.option("--model", default="yolov8x-640", help="Model ID")
@click.option("--mqtt-host", default="localhost", help="MQTT broker host")
@click.option("--mqtt-port", type=int, default=1883, help="MQTT broker port")
@click.option("--max-fps", type=float, default=1.0, help="Maximum FPS (supports decimals, e.g., 0.2 for 1 frame every 5 seconds)")
@click.option(
    "--stream-server",
    default=None,
    help="RTSP server URL (default: $STREAM_SERVER or rtsp://localhost:8554/live)",
)
@click.option(
    "--enable-control",
    is_flag=True,
    default=False,
    help="Enable MQTT control plane for remote control (pause/resume/stop)",
)
@click.option(
    "--control-topic",
    default="nvr/control/commands",
    help="MQTT topic for control commands (default: nvr/control/commands)",
)
@click.option(
    "--status-topic",
    default="nvr/control/status",
    help="MQTT topic for status updates (default: nvr/control/status)",
)
@click.option(
    "--json-logs",
    is_flag=True,
    default=False,
    help="Output logs in JSON format for log aggregation (Elasticsearch, Loki, etc.)",
)
@click.option(
    "--metrics-interval",
    type=int,
    default=10,
    help="Interval in seconds for periodic metrics reporting (0 = disabled, default: 10)",
)
@click.option(
    "--instance-id",
    default=None,
    help="Instance identifier (default: auto-generated processor-{random})",
)
def processor(n, start, end, streams, model, mqtt_host, mqtt_port, max_fps, stream_server, enable_control, control_topic, status_topic, json_logs, metrics_interval, instance_id):
    """Run headless stream processor with MQTT event publishing"""
    from cupertino_nvr.processor import StreamProcessor, StreamProcessorConfig
    
    # Reconfigure logging based on --json-logs flag
    if json_logs:
        setup_structured_logging(level=LOG_LEVEL, json_format=True)

    if stream_server is None:
        stream_server = os.getenv("STREAM_SERVER", "rtsp://localhost:8554/live")

    # Determine stream indices
    if streams is not None:
        # Parse comma-separated list of specific streams
        stream_indices = [int(s.strip()) for s in streams.split(",")]
    elif start is not None and end is not None:
        # Use explicit range (inclusive)
        stream_indices = list(range(start, end + 1))
    elif start is not None:
        # Start specified, use n streams from start
        stream_indices = list(range(start, start + n))
    else:
        # Default: use first n streams starting from 0
        stream_indices = list(range(n))

    # Build config kwargs (omit instance_id if None to allow default_factory to work)
    config_kwargs = {
        "stream_uris": [f"{stream_server}/{i}" for i in stream_indices],  # go2rtc pattern: rtsp://server/{id}
        "model_id": model,
        "mqtt_host": mqtt_host,
        "mqtt_port": mqtt_port,
        "max_fps": max_fps,
        "source_id_mapping": stream_indices,  # Map internal indices to actual stream IDs
        "stream_server": stream_server,  # Store base URL for add_stream command
        "enable_control_plane": enable_control,
        "control_command_topic": control_topic,
        "control_status_topic": status_topic,
        "metrics_reporting_interval": metrics_interval,
    }
    
    # Only set instance_id if explicitly provided (allows default_factory to work)
    if instance_id is not None:
        config_kwargs["instance_id"] = instance_id
    
    config = StreamProcessorConfig(**config_kwargs)

    proc = StreamProcessor(config)
    proc.start()
    
    if enable_control:
        click.echo("\n" + "="*70)
        click.echo("🎬 StreamProcessor running with MQTT Control enabled")
        click.echo("="*70)
        click.echo(f"🆔 Instance ID: {config.instance_id}")
        click.echo(f"📡 Control Topic: {control_topic}")
        click.echo(f"📊 Status Topic: {status_topic}/{config.instance_id}")
        click.echo("\n💡 Available MQTT commands:")
        click.echo("\nBasic Control:")
        click.echo('   PAUSE:   {"command": "pause", "target_instances": ["*"]}')
        click.echo('   RESUME:  {"command": "resume", "target_instances": ["*"]}')
        click.echo('   STOP:    {"command": "stop", "target_instances": ["*"]}')
        click.echo('   STATUS:  {"command": "status", "target_instances": ["*"]}')
        click.echo('   METRICS: {"command": "metrics", "target_instances": ["*"]}')
        click.echo("\nDynamic Configuration:")
        click.echo('   RESTART:       {"command": "restart", "target_instances": ["*"]}')
        click.echo('   CHANGE_MODEL:  {"command": "change_model", "params": {"model_id": "yolov11x-640"}, "target_instances": ["*"]}')
        click.echo('   SET_FPS:       {"command": "set_fps", "params": {"max_fps": 1.0}, "target_instances": ["*"]}')
        click.echo('   ADD_STREAM:    {"command": "add_stream", "params": {"source_id": 8}, "target_instances": ["*"]}')
        click.echo('   REMOVE_STREAM: {"command": "remove_stream", "params": {"source_id": 2}, "target_instances": ["*"]}')
        click.echo("\nDiscovery & Orchestration:")
        click.echo('   PING:           {"command": "ping", "target_instances": ["*"]}')
        click.echo('   RENAME:         {"command": "rename_instance", "params": {"new_instance_id": "emergency-room-2"}, "target_instances": ["processor-xyz123"]}')
        click.echo("\n💡 Targeting:")
        click.echo('   Broadcast:      "target_instances": ["*"]')
        click.echo('   Single:         "target_instances": ["proc-a"]')
        click.echo('   Multi-target:   "target_instances": ["proc-a", "proc-b"]')
        click.echo("\n⌨️  Press Ctrl+C to exit")
        click.echo("="*70 + "\n")

    if metrics_interval > 0:
        click.echo(f"📊 Metrics auto-reporting: Every {metrics_interval}s on topic nvr/status/metrics")
    
    proc.join()


@main.command()
@click.option("--n", type=int, default=6, help="Number of streams (used if --start/--end/--streams not specified)")
@click.option("--start", type=int, default=None, help="Start stream index (e.g., 1 for live/1.stream)")
@click.option("--end", type=int, default=None, help="End stream index (inclusive, e.g., 4 for live/4.stream)")
@click.option("--streams", type=str, default=None, help="Specific stream indices, comma-separated (e.g., '1,3,6' for live/1.stream, live/3.stream, live/6.stream)")
@click.option("--mqtt-host", default="localhost", help="MQTT broker host")
@click.option("--mqtt-port", type=int, default=1883, help="MQTT broker port")
@click.option(
    "--stream-server",
    default=None,
    help="RTSP server URL (default: $STREAM_SERVER or rtsp://localhost:8554/live)",
)
@click.option("--tile-width", type=int, default=480, help="Tile width in pixels")
@click.option("--tile-height", type=int, default=360, help="Tile height in pixels")
def wall(n, start, end, streams, mqtt_host, mqtt_port, stream_server, tile_width, tile_height):
    """Run video wall viewer with MQTT event overlays"""
    from cupertino_nvr.wall import VideoWall, VideoWallConfig

    if stream_server is None:
        stream_server = os.getenv("STREAM_SERVER", "rtsp://localhost:8554/live")

    # Determine stream indices
    if streams is not None:
        # Parse comma-separated list of specific streams
        stream_indices = [int(s.strip()) for s in streams.split(",")]
    elif start is not None and end is not None:
        # Use explicit range (inclusive)
        stream_indices = list(range(start, end + 1))
    elif start is not None:
        # Start specified, use n streams from start
        stream_indices = list(range(start, start + n))
    else:
        # Default: use first n streams starting from 0
        stream_indices = list(range(n))

    config = VideoWallConfig(
        stream_uris=[f"{stream_server}/{i}" for i in stream_indices],  # go2rtc pattern: rtsp://server/{id}
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        tile_size=(tile_width, tile_height),
        source_id_mapping=stream_indices,  # Map internal indices to actual stream IDs
    )

    wall_app = VideoWall(config)
    wall_app.start()


if __name__ == "__main__":
    main()

