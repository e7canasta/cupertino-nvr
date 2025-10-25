"""
CLI entry point for cupertino-nvr
"""

import logging
import os

import click

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
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
    help="RTSP server URL (default: $STREAM_SERVER or rtsp://localhost:8554)",
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
def processor(n, start, end, streams, model, mqtt_host, mqtt_port, max_fps, stream_server, enable_control, control_topic, status_topic):
    """Run headless stream processor with MQTT event publishing"""
    from cupertino_nvr.processor import StreamProcessor, StreamProcessorConfig

    if stream_server is None:
        stream_server = os.getenv("STREAM_SERVER", "rtsp://localhost:8554")

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

    config = StreamProcessorConfig(
        stream_uris=[f"{stream_server}/live/{i}.stream" for i in stream_indices],
        model_id=model,
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        max_fps=max_fps,
        source_id_mapping=stream_indices,  # Map internal indices to actual stream IDs
        enable_control_plane=enable_control,
        control_command_topic=control_topic,
        control_status_topic=status_topic,
    )

    proc = StreamProcessor(config)
    proc.start()
    
    if enable_control:
        click.echo("\n" + "="*70)
        click.echo("🎬 StreamProcessor running with MQTT Control enabled")
        click.echo("="*70)
        click.echo(f"📡 Control Topic: {control_topic}")
        click.echo(f"📊 Status Topic: {status_topic}")
        click.echo("\n💡 Available MQTT commands:")
        click.echo('   PAUSE:  {"command": "pause"}   - Pause stream processing')
        click.echo('   RESUME: {"command": "resume"}  - Resume stream processing')
        click.echo('   STOP:   {"command": "stop"}    - Stop processor completely')
        click.echo('   STATUS: {"command": "status"}  - Query current status')
        click.echo("\n⌨️  Press Ctrl+C to exit")
        click.echo("="*70 + "\n")
    
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
    help="RTSP server URL (default: $STREAM_SERVER or rtsp://localhost:8554)",
)
@click.option("--tile-width", type=int, default=480, help="Tile width in pixels")
@click.option("--tile-height", type=int, default=360, help="Tile height in pixels")
def wall(n, start, end, streams, mqtt_host, mqtt_port, stream_server, tile_width, tile_height):
    """Run video wall viewer with MQTT event overlays"""
    from cupertino_nvr.wall import VideoWall, VideoWallConfig

    if stream_server is None:
        stream_server = os.getenv("STREAM_SERVER", "rtsp://localhost:8554")

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
        stream_uris=[f"{stream_server}/live/{i}.stream" for i in stream_indices],
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        tile_size=(tile_width, tile_height),
        source_id_mapping=stream_indices,  # Map internal indices to actual stream IDs
    )

    wall_app = VideoWall(config)
    wall_app.start()


if __name__ == "__main__":
    main()

