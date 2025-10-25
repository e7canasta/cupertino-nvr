"""
MQTT Listener
=============

Background thread for subscribing to MQTT detection events.
"""

import logging
from threading import Thread

import paho.mqtt.client as mqtt

from cupertino_nvr.events.schema import DetectionEvent
from cupertino_nvr.wall.config import VideoWallConfig
from cupertino_nvr.wall.detection_cache import DetectionCache

logger = logging.getLogger(__name__)


class MQTTListener(Thread):
    """
    Background thread for MQTT subscription.

    Subscribes to MQTT topics and updates detection cache when
    new events are received. Runs as daemon thread.

    Args:
        config: VideoWallConfig instance
        cache: DetectionCache instance to update

    Example:
        >>> config = VideoWallConfig(stream_uris=[...], mqtt_host="localhost")
        >>> cache = DetectionCache()
        >>> listener = MQTTListener(config, cache)
        >>> listener.start()  # Runs in background
        >>> # ... later ...
        >>> listener.stop()
    """

    def __init__(self, config: VideoWallConfig, cache: DetectionCache):
        super().__init__(daemon=True)
        self.config = config
        self.cache = cache
        self.client = mqtt.Client()
        self.client.on_message = self._on_message
        self.client.on_connect = self._on_connect
        self._running = True

    def run(self):
        """Start MQTT listener (called by Thread.start())"""
        try:
            # Setup authentication if provided
            if self.config.mqtt_username:
                self.client.username_pw_set(
                    self.config.mqtt_username, self.config.mqtt_password
                )

            # Connect
            logger.info(f"MQTT listener connecting to {self.config.mqtt_host}")
            self.client.connect(self.config.mqtt_host, self.config.mqtt_port)

            # Subscribe to detection events
            self.client.subscribe(self.config.mqtt_topic_pattern)
            logger.info(
                f"MQTT listener subscribed to {self.config.mqtt_topic_pattern}"
            )

            # Loop forever (blocks until disconnect)
            self.client.loop_forever()

        except Exception as e:
            logger.error(f"MQTT listener error: {e}")

    def stop(self):
        """Stop the listener"""
        self._running = False
        self.client.disconnect()

    def _on_connect(self, client, userdata, flags, rc):
        """Callback when connected to MQTT broker"""
        if rc == 0:
            logger.info("MQTT listener connected successfully")
        else:
            logger.error(f"MQTT listener connection failed with code {rc}")

    def _on_message(self, client, userdata, msg):
        """Callback when message received from MQTT broker"""
        try:
            # Parse JSON payload into DetectionEvent
            event = DetectionEvent.model_validate_json(msg.payload)

            # Update cache
            self.cache.update(event)

        except Exception as e:
            logger.error(f"Failed to parse detection event: {e}")

