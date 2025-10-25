"""
Architectural Design Tests - Smart Coverage for Key Design Principles

These tests validate core architectural decisions and design invariants,
not exhaustive code coverage. Focus on:

1. Bounded Context Isolation
2. Pub/Sub Decoupling  
3. Thread Safety Guarantees
4. Callback Pattern Integrity
5. Configuration Flexibility
6. Supervision Integration Contract

Co-Authored-By: Gaby <noreply@visiona.com>
"""

import json
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from typing import List, Any

import pytest
import numpy as np

from cupertino_nvr.events import DetectionEvent, Detection, BoundingBox
from cupertino_nvr.processor import MQTTDetectionSink
from cupertino_nvr.wall.cache import DetectionCache
from cupertino_nvr.wall.renderer import DetectionRenderer


class MockVideoFrame:
    """Minimal VideoFrame mock matching Roboflow Inference interface"""
    
    def __init__(self, source_id: int, frame_id: int, timestamp: datetime):
        self.source_id = source_id
        self.frame_id = frame_id
        self.frame_timestamp = timestamp
        self.image = np.zeros((480, 640, 3), dtype=np.uint8)


class TestBoundedContextIsolation:
    """Verify that processor and wall are truly decoupled"""
    
    def test_processor_has_no_wall_dependencies(self):
        """Processor should not import anything from wall package"""
        from cupertino_nvr.processor import mqtt_sink, processor
        
        # Check imports don't reference wall
        import inspect
        
        sink_source = inspect.getsource(mqtt_sink)
        processor_source = inspect.getsource(processor)
        
        assert "wall" not in sink_source
        assert "wall" not in processor_source
        assert "DetectionCache" not in sink_source
        assert "renderer" not in sink_source
    
    def test_wall_only_depends_on_events(self):
        """Wall should only know about events, not processor internals"""
        from cupertino_nvr.wall import cache, renderer, wall
        
        import inspect
        
        cache_source = inspect.getsource(cache)
        renderer_source = inspect.getsource(renderer)  
        wall_source = inspect.getsource(wall)
        
        # Should not import processor modules
        assert "MQTTDetectionSink" not in cache_source
        assert "StreamProcessor" not in renderer_source
        assert "processor" not in wall_source
    
    def test_mqtt_is_only_coupling_point(self):
        """MQTT topics are the ONLY communication channel"""
        # This is validated by checking no shared memory/direct calls
        
        mock_client = MagicMock()
        sink = MQTTDetectionSink(mock_client, "test/prefix", "model")
        
        # Sink can only communicate via MQTT publish
        frame = MockVideoFrame(0, 123, datetime.now())
        prediction = {"predictions": [], "time": 0.1}
        
        sink(prediction, frame)
        
        # Verify MQTT is the only output channel
        mock_client.publish.assert_called_once()
        
        # No other side effects or shared state
        assert not hasattr(sink, '_shared_state')
        assert not hasattr(sink, '_callbacks')


class TestPubSubDecoupling:
    """Validate publish/subscribe architectural pattern"""
    
    def test_configurable_topic_prefixes(self):
        """Different deployments can use different topic spaces"""
        mock_client = MagicMock()
        
        # Production deployment
        prod_sink = MQTTDetectionSink(mock_client, "prod/nvr/detections", "model")
        
        # Development deployment  
        dev_sink = MQTTDetectionSink(mock_client, "dev/nvr/detections", "model")
        
        frame = MockVideoFrame(source_id=5, frame_id=100, timestamp=datetime.now())
        prediction = {"predictions": [], "time": 0.1}
        
        prod_sink(prediction, frame)
        dev_sink(prediction, frame)
        
        # Verify topics are isolated by prefix
        calls = mock_client.publish.call_args_list
        assert calls[0][0][0] == "prod/nvr/detections/5"
        assert calls[1][0][0] == "dev/nvr/detections/5" 
    
    def test_qos_0_fire_and_forget(self):
        """Real-time video should use QoS 0 for minimal latency"""
        mock_client = MagicMock()
        sink = MQTTDetectionSink(mock_client, "nvr/detections", "model")
        
        frame = MockVideoFrame(0, 123, datetime.now())
        prediction = {"predictions": [], "time": 0.1}
        
        sink(prediction, frame)
        
        # Verify QoS 0 (fire-and-forget)
        call_kwargs = mock_client.publish.call_args[1]
        assert call_kwargs["qos"] == 0
    
    def test_topic_protocol_consistency(self):
        """Topic format must be consistent: prefix/source_id"""
        from cupertino_nvr.events.protocol import topic_for_source, parse_source_id_from_topic
        
        # Test round-trip consistency
        for source_id in [0, 1, 42, 999]:
            for prefix in ["nvr/detections", "custom/events", "test/prefix"]:
                topic = topic_for_source(source_id, prefix=prefix)
                parsed_id = parse_source_id_from_topic(topic)
                
                assert parsed_id == source_id
                assert topic == f"{prefix}/{source_id}"


class TestThreadSafetyGuarantees:
    """Verify thread safety in concurrent scenarios"""
    
    def test_detection_cache_concurrent_access(self):
        """Cache must be thread-safe for MQTT listener + render thread"""
        cache = DetectionCache(ttl_seconds=1.0)
        
        # Simulate concurrent writers (MQTT listener threads)
        def writer(source_id: int, count: int):
            for i in range(count):
                event = DetectionEvent(
                    source_id=source_id,
                    frame_id=i,
                    timestamp=datetime.now(),
                    model_id="test",
                    inference_time_ms=10.0,
                    detections=[]
                )
                cache.put(source_id, event)
                time.sleep(0.001)  # Small delay to increase race conditions
        
        # Simulate concurrent readers (render thread)
        read_results = []
        def reader(source_id: int, count: int):
            for _ in range(count):
                result = cache.get(source_id)
                read_results.append(result)
                time.sleep(0.001)
        
        # Start multiple threads
        threads = []
        
        # Multiple writers
        for source_id in [0, 1, 2]:
            thread = threading.Thread(target=writer, args=(source_id, 10))
            threads.append(thread)
        
        # Multiple readers  
        for source_id in [0, 1, 2]:
            thread = threading.Thread(target=reader, args=(source_id, 10))
            threads.append(thread)
        
        # Start all threads
        for thread in threads:
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # No exceptions = thread safety maintained
        assert len(read_results) == 30  # 10 reads * 3 sources
    
    def test_cache_ttl_expiration_under_load(self):
        """TTL expiration should work correctly under concurrent load"""
        cache = DetectionCache(ttl_seconds=0.1)  # Very short TTL
        
        event = DetectionEvent(
            source_id=0,
            frame_id=123,
            timestamp=datetime.now(),
            model_id="test",
            inference_time_ms=10.0,
            detections=[]
        )
        
        # Store event
        cache.put(0, event)
        
        # Should be available immediately
        assert cache.get(0) is not None
        
        # Wait for expiration
        time.sleep(0.15)
        
        # Should be expired and auto-removed
        assert cache.get(0) is None


class TestCallbackPatternIntegrity:
    """Verify InferencePipeline callback contract is maintained"""
    
    def test_sink_callable_interface(self):
        """MQTTDetectionSink must be callable for InferencePipeline"""
        mock_client = MagicMock()
        sink = MQTTDetectionSink(mock_client, "nvr/detections", "model")
        
        # Should be callable
        assert callable(sink)
        
        # Should implement __call__ method
        assert hasattr(sink, '__call__')
    
    def test_single_prediction_signature(self):
        """Handle single prediction + single frame"""
        mock_client = MagicMock()
        sink = MQTTDetectionSink(mock_client, "nvr/detections", "model")
        
        prediction = {"predictions": [], "time": 0.1}
        frame = MockVideoFrame(0, 123, datetime.now())
        
        # Should not raise exception
        sink(prediction, frame)
        
        mock_client.publish.assert_called_once()
    
    def test_batch_prediction_signature(self):
        """Handle batch predictions + batch frames"""
        mock_client = MagicMock()
        sink = MQTTDetectionSink(mock_client, "nvr/detections", "model")
        
        predictions = [
            {"predictions": [], "time": 0.1},
            {"predictions": [], "time": 0.2}
        ]
        frames = [
            MockVideoFrame(0, 100, datetime.now()),
            MockVideoFrame(1, 200, datetime.now())
        ]
        
        # Should handle batch processing
        sink(predictions, frames)
        
        # Should publish for each frame
        assert mock_client.publish.call_count == 2
    
    def test_graceful_none_handling(self):
        """Must gracefully handle None frames (InferencePipeline can send None)"""
        mock_client = MagicMock()
        sink = MQTTDetectionSink(mock_client, "nvr/detections", "model")
        
        prediction = {"predictions": [], "time": 0.1}
        
        # Should not crash with None frame
        sink(prediction, None)
        
        # Should not publish for None frame
        mock_client.publish.assert_not_called()


class TestSupervisionIntegrationContract:
    """Verify supervision library integration maintains contracts"""
    
    def test_renderer_uses_supervision_annotators(self):
        """DetectionRenderer must use supervision, not raw OpenCV"""
        from supervision import BoxAnnotator, LabelAnnotator
        
        renderer = DetectionRenderer()
        
        # Should have supervision annotators
        assert hasattr(renderer, 'box_annotator')
        assert hasattr(renderer, 'label_annotator')
        
        # Should be supervision types
        assert isinstance(renderer.box_annotator, BoxAnnotator)
        assert isinstance(renderer.label_annotator, LabelAnnotator)
    
    def test_supervision_detection_conversion(self):
        """Must properly convert our Detection to supervision.Detections"""
        renderer = DetectionRenderer()
        
        # Mock frame
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        
        # Mock detection event
        bbox = BoundingBox(x=100, y=100, width=50, height=100)
        detection = Detection(class_name="person", confidence=0.9, bbox=bbox)
        event = DetectionEvent(
            source_id=0,
            frame_id=123,
            timestamp=datetime.now(),
            model_id="test",
            inference_time_ms=10.0,
            detections=[detection]
        )
        
        # Should not crash when rendering
        result_frame = renderer.render_frame(frame, event)
        
        # Result should be same shape
        assert result_frame.shape == frame.shape
        assert result_frame.dtype == frame.dtype
    
    @patch('cupertino_nvr.wall.renderer.Detections')
    def test_supervision_detections_format(self, mock_detections):
        """Verify we're using supervision.Detections correctly"""
        renderer = DetectionRenderer()
        
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        bbox = BoundingBox(x=100, y=100, width=50, height=100)
        detection = Detection(class_name="person", confidence=0.9, bbox=bbox)
        event = DetectionEvent(
            source_id=0,
            frame_id=123,  
            timestamp=datetime.now(),
            model_id="test",
            inference_time_ms=10.0,
            detections=[detection]
        )
        
        renderer.render_frame(frame, event)
        
        # Should call supervision.Detections constructor
        mock_detections.assert_called_once()
        
        # Verify the format of data passed to supervision
        call_args = mock_detections.call_args[1]  # keyword args
        
        # Should have proper numpy arrays
        assert 'xyxy' in call_args
        assert 'confidence' in call_args
        assert 'class_id' in call_args
        
        # Arrays should have correct shape
        assert call_args['xyxy'].shape == (1, 4)  # 1 detection, 4 coords
        assert call_args['confidence'].shape == (1,)  # 1 confidence score


class TestConfigurationFlexibility:
    """Verify configuration system supports different deployment scenarios"""
    
    def test_mqtt_broker_configuration(self):
        """MQTT broker should be configurable for different environments"""
        from cupertino_nvr.processor.config import StreamProcessorConfig
        from cupertino_nvr.wall.config import VideoWallConfig
        
        # Test different broker configurations
        configs = [
            ("localhost", 1883),  # Local development
            ("mqtt.production.com", 8883),  # Production 
            ("192.168.1.100", 1883),  # On-premise
        ]
        
        for host, port in configs:
            # Processor config
            proc_config = StreamProcessorConfig(
                mqtt_broker=host,
                mqtt_port=port,
                mqtt_topic_prefix="test/detections"
            )
            
            assert proc_config.mqtt_broker == host
            assert proc_config.mqtt_port == port
            
            # Wall config
            wall_config = VideoWallConfig(
                mqtt_broker=host,
                mqtt_port=port,
                mqtt_topic_prefix="test/detections"
            )
            
            assert wall_config.mqtt_broker == host
            assert wall_config.mqtt_port == port
    
    def test_topic_prefix_flexibility(self):
        """Topic prefixes should support multi-tenant scenarios"""
        prefixes = [
            "nvr/detections",      # Default
            "tenant1/events",      # Multi-tenant
            "prod/nvr/camera",     # Environment-specific
            "site_A/building_1/nvr" # Hierarchical
        ]
        
        mock_client = MagicMock()
        
        for prefix in prefixes:
            sink = MQTTDetectionSink(mock_client, prefix, "model")
            
            frame = MockVideoFrame(0, 123, datetime.now())
            prediction = {"predictions": [], "time": 0.1}
            
            sink(prediction, frame)
            
            # Verify topic follows prefix pattern
            expected_topic = f"{prefix}/0"
            actual_topic = mock_client.publish.call_args[0][0]
            assert actual_topic == expected_topic
            
            mock_client.reset_mock()


# Integration smoke test to verify overall design coherence
class TestArchitecturalCoherence:
    """High-level test that the architecture pieces work together correctly"""
    
    def test_end_to_end_event_flow(self):
        """Simulate complete event flow: Processor -> MQTT -> Wall"""
        
        # Step 1: Processor publishes event
        mock_client = MagicMock()
        sink = MQTTDetectionSink(mock_client, "nvr/detections", "yolov8x-640")
        
        prediction = {
            "predictions": [{
                "class": "person",
                "confidence": 0.92,
                "x": 100, "y": 150,
                "width": 80, "height": 200
            }],
            "time": 0.045
        }
        
        frame = MockVideoFrame(0, 123, datetime.now())
        sink(prediction, frame)
        
        # Step 2: Extract published event
        published_topic = mock_client.publish.call_args[0][0]
        published_payload = mock_client.publish.call_args[0][1]
        
        # Step 3: Wall receives and processes event
        event = DetectionEvent.model_validate_json(published_payload)
        
        cache = DetectionCache(ttl_seconds=1.0)
        cache.put(event.source_id, event)
        
        # Step 4: Wall renders frame with detections
        renderer = DetectionRenderer()
        test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        
        rendered_frame = renderer.render_frame(test_frame, event)
        
        # Verify complete flow
        assert published_topic == "nvr/detections/0"
        assert event.source_id == 0
        assert len(event.detections) == 1
        assert event.detections[0].class_name == "person"
        assert rendered_frame.shape == test_frame.shape
        
        # Verify cache retrieval
        cached_event = cache.get(0)
        assert cached_event.frame_id == event.frame_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])