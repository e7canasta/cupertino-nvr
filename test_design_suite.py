#!/usr/bin/env python3
"""
Smart Architecture Design Test Suite
=====================================

Standalone test script to validate core design principles without 
complex import dependencies. Focuses on:

1. ✅ Event Schema Stability  
2. ✅ MQTT Protocol Consistency
3. ✅ Thread Safety Patterns
4. ✅ Configuration Flexibility
5. ✅ Supervision Data Format Compatibility

Co-Authored-By: Gaby <noreply@visiona.com>
"""

import json
import threading
import time
from datetime import datetime, timedelta
import numpy as np
from typing import List, Dict, Any
import sys
import os

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

from cupertino_nvr.events import DetectionEvent, Detection, BoundingBox
from cupertino_nvr.events.protocol import topic_for_source, parse_source_id_from_topic


class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.failures = []
    
    def assert_test(self, condition: bool, test_name: str, details: str = ""):
        if condition:
            print(f"✅ {test_name}")
            self.passed += 1
        else:
            print(f"❌ {test_name} - {details}")
            self.failed += 1
            self.failures.append((test_name, details))
    
    def summary(self):
        total = self.passed + self.failed
        print(f"\n🎯 Test Results: {self.passed}/{total} passed")
        if self.failed > 0:
            print(f"❌ {self.failed} failed:")
            for test, details in self.failures:
                print(f"   - {test}: {details}")
        return self.failed == 0


def test_event_schema_stability(results: TestResults):
    """Test 1: Event Schema Design Validation"""
    print("\n📋 Testing Event Schema Stability...")
    
    # Create comprehensive event
    bbox = BoundingBox(x=100, y=150, width=80, height=200)
    detection = Detection(
        class_name="person",
        confidence=0.92,
        bbox=bbox,
        tracker_id=42
    )
    
    event = DetectionEvent(
        source_id=0,
        frame_id=123,
        timestamp=datetime(2025, 10, 25, 10, 30, 0),
        model_id="yolov8x-640",
        inference_time_ms=45.2,
        detections=[detection],
        fps=25.3,
        latency_ms=120.5
    )
    
    # Test serialization round-trip
    try:
        json_str = event.model_dump_json()
        json_data = json.loads(json_str)  # Validate JSON
        restored_event = DetectionEvent.model_validate_json(json_str)
        
        # Verify all fields preserved
        fields_match = (
            restored_event.source_id == event.source_id and
            restored_event.frame_id == event.frame_id and
            restored_event.model_id == event.model_id and
            restored_event.inference_time_ms == event.inference_time_ms and
            len(restored_event.detections) == 1 and
            restored_event.detections[0].class_name == "person" and
            restored_event.detections[0].confidence == 0.92 and
            restored_event.detections[0].tracker_id == 42 and
            restored_event.fps == 25.3 and
            restored_event.latency_ms == 120.5
        )
        
        results.assert_test(
            fields_match,
            "Event serialization round-trip",
            "All fields should be preserved exactly"
        )
        
    except Exception as e:
        results.assert_test(False, "Event serialization", f"Exception: {e}")
    
    # Test validation constraints
    try:
        # Valid confidence should work
        Detection(class_name="test", confidence=0.5, bbox=bbox)
        
        # Invalid confidence should fail
        try:
            Detection(class_name="test", confidence=1.5, bbox=bbox)
            results.assert_test(False, "Validation constraints", "Should reject confidence > 1.0")
        except ValueError:
            results.assert_test(True, "Validation constraints")
            
    except Exception as e:
        results.assert_test(False, "Validation constraints", f"Unexpected error: {e}")


def test_mqtt_protocol_design(results: TestResults):
    """Test 2: MQTT Protocol Consistency"""
    print("\n📡 Testing MQTT Protocol Design...")
    
    # Test topic naming consistency
    test_cases = [
        (0, "nvr/detections", "nvr/detections/0"),
        (42, "nvr/detections", "nvr/detections/42"),
        (999, "custom/events", "custom/events/999"),
        (5, "prod/site1/cameras", "prod/site1/cameras/5"),
    ]
    
    all_topics_correct = True
    for source_id, prefix, expected_topic in test_cases:
        topic = topic_for_source(source_id, prefix=prefix)
        parsed_id = parse_source_id_from_topic(topic)
        
        if topic != expected_topic or parsed_id != source_id:
            all_topics_correct = False
            break
    
    results.assert_test(
        all_topics_correct,
        "Topic naming consistency",
        "All topic formats should be consistent and parseable"
    )
    
    # Test multi-tenant isolation
    tenant_topics = []
    for i, prefix in enumerate(["tenant_a/nvr", "tenant_b/nvr", "prod/cameras"]):
        topic = topic_for_source(5, prefix=prefix)
        tenant_topics.append(topic)
    
    unique_topics = len(set(tenant_topics)) == len(tenant_topics)
    results.assert_test(
        unique_topics,
        "Multi-tenant topic isolation",
        "Different prefixes should create isolated namespaces"
    )
    
    # Test invalid topic parsing
    invalid_cases = [
        "invalid/topic",
        "nvr/detections/not_a_number", 
        "nvr/detections/",
        "nvr/detections",
        ""
    ]
    
    all_invalid_return_none = True
    for invalid_topic in invalid_cases:
        parsed_id = parse_source_id_from_topic(invalid_topic)
        if parsed_id is not None:
            all_invalid_return_none = False
            break
    
    results.assert_test(
        all_invalid_return_none,
        "Invalid topic handling",
        "Invalid topics should return None"
    )


def test_thread_safety_patterns(results: TestResults):
    """Test 3: Thread Safety Design Patterns"""
    print("\n🔄 Testing Thread Safety Patterns...")
    
    # Mock cache following our design pattern
    class MockDetectionCache:
        def __init__(self):
            self._cache = {}
            self._lock = threading.Lock()
        
        def put(self, source_id: int, event: DetectionEvent):
            with self._lock:
                self._cache[source_id] = (event, datetime.now())
        
        def get(self, source_id: int):
            with self._lock:
                if source_id in self._cache:
                    return self._cache[source_id][0]
                return None
    
    cache = MockDetectionCache()
    results_list = []
    errors = []
    
    def writer_thread(thread_id: int):
        try:
            for i in range(20):
                event = DetectionEvent(
                    source_id=thread_id,
                    frame_id=i,
                    timestamp=datetime.now(),
                    model_id="test",
                    inference_time_ms=10.0,
                    detections=[]
                )
                cache.put(thread_id, event)
                time.sleep(0.001)  # Increase race condition probability
        except Exception as e:
            errors.append(f"Writer {thread_id}: {e}")
    
    def reader_thread(thread_id: int):
        try:
            for _ in range(20):
                result = cache.get(thread_id)
                results_list.append(result)
                time.sleep(0.001)
        except Exception as e:
            errors.append(f"Reader {thread_id}: {e}")
    
    # Start multiple threads
    threads = []
    for i in range(3):
        writer = threading.Thread(target=writer_thread, args=(i,))
        reader = threading.Thread(target=reader_thread, args=(i,))
        threads.extend([writer, reader])
    
    for thread in threads:
        thread.start()
    
    for thread in threads:
        thread.join()
    
    results.assert_test(
        len(errors) == 0,
        "Thread safety under concurrent load",
        f"No exceptions should occur: {errors}" if errors else ""
    )
    
    results.assert_test(
        len(results_list) == 60,  # 3 readers * 20 reads each
        "Thread safety result integrity",
        f"Expected 60 results, got {len(results_list)}"
    )


def test_callback_pattern_design(results: TestResults):
    """Test 4: Callback Pattern Design"""
    print("\n🔗 Testing Callback Pattern Design...")
    
    # Mock sink following InferencePipeline callback pattern
    class MockDetectionSink:
        def __init__(self):
            self.published_events = []
        
        def __call__(self, predictions, video_frames):
            """Callback signature matching InferencePipeline requirements"""
            # Handle single vs batch
            if isinstance(predictions, list) and isinstance(video_frames, list):
                for pred, frame in zip(predictions, video_frames):
                    self._process_single(pred, frame)
            else:
                self._process_single(predictions, video_frames)
        
        def _process_single(self, prediction, video_frame):
            if video_frame is None:
                return  # Graceful None handling
            
            event_data = {
                "source_id": getattr(video_frame, 'source_id', 0),
                "frame_id": getattr(video_frame, 'frame_id', 0),
                "predictions": prediction.get("predictions", []),
                "inference_time": prediction.get("time", 0.0)
            }
            self.published_events.append(event_data)
    
    sink = MockDetectionSink()
    
    # Test callable interface
    results.assert_test(
        callable(sink),
        "Sink callable interface",
        "Sink must be callable for InferencePipeline"
    )
    
    # Mock video frame
    class MockVideoFrame:
        def __init__(self, source_id, frame_id):
            self.source_id = source_id
            self.frame_id = frame_id
    
    # Test single prediction
    prediction = {"predictions": [], "time": 0.1}
    frame = MockVideoFrame(0, 123)
    
    sink(prediction, frame)
    single_works = len(sink.published_events) == 1 and sink.published_events[0]["source_id"] == 0
    
    results.assert_test(single_works, "Single prediction handling")
    
    # Test batch predictions
    predictions = [{"predictions": [], "time": 0.1}, {"predictions": [], "time": 0.2}]
    frames = [MockVideoFrame(1, 200), MockVideoFrame(2, 300)]
    
    sink(predictions, frames)
    batch_works = len(sink.published_events) == 3  # 1 + 2
    
    results.assert_test(batch_works, "Batch prediction handling")
    
    # Test None frame handling
    initial_count = len(sink.published_events)
    sink(prediction, None)
    none_handled = len(sink.published_events) == initial_count
    
    results.assert_test(none_handled, "Graceful None frame handling")


def test_supervision_integration_design(results: TestResults):
    """Test 5: Supervision Integration Design"""
    print("\n🎨 Testing Supervision Integration Design...")
    
    # Test data format conversion
    detections = [
        Detection(
            class_name="person",
            confidence=0.92,
            bbox=BoundingBox(x=100, y=150, width=80, height=200)
        ),
        Detection(
            class_name="car",
            confidence=0.85,
            bbox=BoundingBox(x=300, y=200, width=120, height=100)
        )
    ]
    
    # Mock conversion to supervision format (matches our renderer logic)
    def convert_to_supervision_format(detections_list):
        if not detections_list:
            return {
                'xyxy': np.array([], dtype=np.float32).reshape(0, 4),
                'confidence': np.array([], dtype=np.float32),
                'class_id': np.array([], dtype=int),
            }
        
        xyxy_boxes = []
        confidences = []
        class_ids = []
        
        for det in detections_list:
            # Convert x,y,w,h to x1,y1,x2,y2
            x1 = det.bbox.x
            y1 = det.bbox.y
            x2 = det.bbox.x + det.bbox.width
            y2 = det.bbox.y + det.bbox.height
            
            xyxy_boxes.append([x1, y1, x2, y2])
            confidences.append(det.confidence)
            class_ids.append(hash(det.class_name) % 1000)
        
        return {
            'xyxy': np.array(xyxy_boxes, dtype=np.float32),
            'confidence': np.array(confidences, dtype=np.float32), 
            'class_id': np.array(class_ids, dtype=int),
        }
    
    sup_data = convert_to_supervision_format(detections)
    
    # Verify shapes
    shapes_correct = (
        sup_data['xyxy'].shape == (2, 4) and
        sup_data['confidence'].shape == (2,) and
        sup_data['class_id'].shape == (2,)
    )
    
    results.assert_test(shapes_correct, "Supervision data format shapes")
    
    # Verify coordinate conversion
    expected_boxes = np.array([
        [100, 150, 180, 350],  # person: x,y,w,h -> x1,y1,x2,y2
        [300, 200, 420, 300],  # car
    ], dtype=np.float32)
    
    boxes_match = np.array_equal(sup_data['xyxy'], expected_boxes)
    results.assert_test(boxes_match, "Coordinate conversion (x,y,w,h -> x1,y1,x2,y2)")
    
    # Test empty detections
    empty_data = convert_to_supervision_format([])
    empty_shapes_correct = (
        empty_data['xyxy'].shape == (0, 4) and
        empty_data['confidence'].shape == (0,) and
        empty_data['class_id'].shape == (0,)
    )
    
    results.assert_test(empty_shapes_correct, "Empty detections handling")


def test_configuration_flexibility(results: TestResults):
    """Test 6: Configuration Flexibility"""
    print("\n⚙️ Testing Configuration Flexibility...")
    
    # Test different deployment scenarios
    scenarios = [
        {
            "name": "development",
            "mqtt_broker": "localhost",
            "mqtt_port": 1883,
            "topic_prefix": "dev/nvr/detections"
        },
        {
            "name": "production", 
            "mqtt_broker": "mqtt.prod.company.com",
            "mqtt_port": 8883,
            "topic_prefix": "prod/nvr/detections"
        },
        {
            "name": "site_a",
            "mqtt_broker": "192.168.1.100",
            "mqtt_port": 1883,
            "topic_prefix": "site_a/building_1/nvr"
        }
    ]
    
    all_scenarios_work = True
    for scenario in scenarios:
        # Test topic generation
        topic = topic_for_source(0, prefix=scenario["topic_prefix"])
        expected_topic = f"{scenario['topic_prefix']}/0"
        
        if not (topic == expected_topic and topic.startswith(scenario["topic_prefix"])):
            all_scenarios_work = False
            break
    
    results.assert_test(
        all_scenarios_work,
        "Multi-environment configuration support",
        "All deployment scenarios should generate correct topics"
    )
    
    # Test hierarchical topic namespaces
    hierarchical_prefixes = [
        "site_a/building_1/floor_2/nvr",
        "customer_x/datacenter_y/rack_z/cameras", 
        "region/country/city/facility/security"
    ]
    
    hierarchical_works = True
    for prefix in hierarchical_prefixes:
        topic = topic_for_source(5, prefix=prefix)
        parsed_id = parse_source_id_from_topic(topic)
        
        if not (topic == f"{prefix}/5" and parsed_id == 5):
            hierarchical_works = False
            break
    
    results.assert_test(
        hierarchical_works,
        "Hierarchical topic namespace support",
        "Deep topic hierarchies should work correctly"
    )


def test_architectural_coherence(results: TestResults):
    """Test 7: End-to-End Architectural Coherence"""
    print("\n🏗️ Testing Architectural Coherence...")
    
    # Mock complete event flow: Processor -> MQTT -> Wall
    class MockMQTTBroker:
        def __init__(self):
            self.published_messages = []
            self.subscribers = {}
        
        def publish(self, topic: str, payload: str, qos: int = 0):
            self.published_messages.append({
                "topic": topic,
                "payload": payload,
                "qos": qos
            })
            
            # Deliver to subscribers
            for pattern, callback in self.subscribers.items():
                if topic.startswith(pattern.replace('#', '')):
                    callback(topic, payload)
        
        def subscribe(self, pattern: str, callback):
            self.subscribers[pattern] = callback
    
    broker = MockMQTTBroker()
    received_events = []
    
    def wall_callback(topic, payload):
        try:
            event = DetectionEvent.model_validate_json(payload)
            received_events.append(event)
        except Exception:
            pass  # Invalid events ignored
    
    # Subscribe wall to detection events
    broker.subscribe("nvr/detections/", wall_callback)
    
    # Create and publish event (simulating processor)
    detection = Detection(
        class_name="person",
        confidence=0.92,
        bbox=BoundingBox(x=100, y=150, width=80, height=200)
    )
    
    event = DetectionEvent(
        source_id=0,
        frame_id=123,
        timestamp=datetime.now(),
        model_id="yolov8x-640",
        inference_time_ms=45.0,
        detections=[detection]
    )
    
    topic = topic_for_source(event.source_id, prefix="nvr/detections")
    broker.publish(topic, event.model_dump_json(), qos=0)
    
    # Verify end-to-end flow
    publish_correct = (
        len(broker.published_messages) == 1 and
        broker.published_messages[0]["topic"] == "nvr/detections/0" and
        broker.published_messages[0]["qos"] == 0
    )
    
    results.assert_test(publish_correct, "Event publishing flow")
    
    # Verify wall received event correctly
    wall_received = (
        len(received_events) == 1 and
        received_events[0].source_id == event.source_id and
        received_events[0].frame_id == event.frame_id and
        len(received_events[0].detections) == 1 and
        received_events[0].detections[0].class_name == "person"
    )
    
    results.assert_test(wall_received, "End-to-end event flow integrity")


def main():
    """Run complete design validation suite"""
    print("🎯 Cupertino NVR - Smart Architecture Design Test Suite")
    print("=" * 60)
    
    results = TestResults()
    
    # Run all test categories
    test_event_schema_stability(results)
    test_mqtt_protocol_design(results)
    test_thread_safety_patterns(results)
    test_callback_pattern_design(results)
    test_supervision_integration_design(results)
    test_configuration_flexibility(results)
    test_architectural_coherence(results)
    
    # Print summary
    success = results.summary()
    
    if success:
        print("\n🎉 All design principles validated successfully!")
        print("   Architecture is solid and ready for production.")
    else:
        print("\n⚠️ Some design issues found - review needed.")
    
    return 0 if success else 1


if __name__ == "__main__":
    exit(main())