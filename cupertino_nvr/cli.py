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
@click.option("--n", type=int, default=6, help="Number of streams")
@click.option("--model", default="yolov8x-640", help="Model ID")
@click.option("--mqtt-host", default="localhost", help="MQTT broker host")
@click.option("--mqtt-port", type=int, default=1883, help="MQTT broker port")
@click.option(
    "--stream-server",
    default=None,
    help="RTSP server URL (default: $STREAM_SERVER or rtsp://localhost:8554)",
)
def processor(n, model, mqtt_host, mqtt_port, stream_server):
    """Run headless stream processor with MQTT event publishing"""
    from cupertino_nvr.processor import StreamProcessor, StreamProcessorConfig

    if stream_server is None:
        stream_server = os.getenv("STREAM_SERVER", "rtsp://localhost:8554")

    config = StreamProcessorConfig(
        stream_uris=[f"{stream_server}/live/{i}.stream" for i in range(n)],
        model_id=model,
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
    )

    proc = StreamProcessor(config)
    proc.start()
    proc.join()


@main.command()
@click.option("--n", type=int, default=6, help="Number of streams")
@click.option("--mqtt-host", default="localhost", help="MQTT broker host")
@click.option("--mqtt-port", type=int, default=1883, help="MQTT broker port")
@click.option(
    "--stream-server",
    default=None,
    help="RTSP server URL (default: $STREAM_SERVER or rtsp://localhost:8554)",
)
@click.option("--tile-width", type=int, default=480, help="Tile width in pixels")
@click.option("--tile-height", type=int, default=360, help="Tile height in pixels")
def wall(n, mqtt_host, mqtt_port, stream_server, tile_width, tile_height):
    """Run video wall viewer with MQTT event overlays"""
    from cupertino_nvr.wall import VideoWall, VideoWallConfig

    if stream_server is None:
        stream_server = os.getenv("STREAM_SERVER", "rtsp://localhost:8554")

    config = VideoWallConfig(
        stream_uris=[f"{stream_server}/live/{i}.stream" for i in range(n)],
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        tile_size=(tile_width, tile_height),
    )

    wall_app = VideoWall(config)
    wall_app.start()


if __name__ == "__main__":
    main()

