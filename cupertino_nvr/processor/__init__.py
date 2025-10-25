"""
Stream Processor - Headless Inference Pipeline
===============================================

Processes RTSP streams and publishes detection events to MQTT.
"""

from cupertino_nvr.processor.config import StreamProcessorConfig
from cupertino_nvr.processor.mqtt_sink import MQTTDetectionSink
from cupertino_nvr.processor.processor import StreamProcessor

__all__ = [
    "StreamProcessor",
    "StreamProcessorConfig",
    "MQTTDetectionSink",
]

