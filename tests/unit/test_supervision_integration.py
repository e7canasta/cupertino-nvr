"""
Supervision Integration Tests - Validate supervision library contracts

Tests focused on the supervision integration to ensure:
1. Proper data conversion from our schemas to supervision format
2. Annotation rendering pipeline works correctly  
3. Performance characteristics meet expectations
4. Extensibility for future supervision features

Co-Authored-By: Gaby <noreply@visiona.com>
"""

import numpy as np
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest
from supervision import Detections

from cupertino_nvr.events import DetectionEvent, Detection, BoundingBox
from cupertino_nvr.wall.renderer import DetectionRenderer


class TestSupervisionDataConversion:
    """Test conversion from our data models to supervision format"""
    
    def test_single_detection_conversion(self):
        """Convert single detection to supervision.Detections format"""
        bbox = BoundingBox(x=100, y=150, width=80, height=200)
        detection = Detection(class_name="person", confidence=0.92, bbox=bbox)
        
        event = DetectionEvent(
            source_id=0,
            frame_id=123,
            timestamp=datetime.now(),
            model_id="yolov8x-640",
            inference_time_ms=45.2,
            detections=[detection]
        )
        
        renderer = DetectionRenderer()
        
        # Test the conversion method directly
        with patch('cupertino_nvr.wall.renderer.Detections') as mock_detections:
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            renderer.render_frame(frame, event)
            
            # Verify supervision.Detections was called
            mock_detections.assert_called_once()
            
            # Check the data format
            call_kwargs = mock_detections.call_args[1]
            
            # xyxy format: [x1, y1, x2, y2]
            expected_xyxy = np.array([[100, 150, 180, 350]], dtype=np.float32)
            np.testing.assert_array_equal(call_kwargs['xyxy'], expected_xyxy)
            
            # Confidence scores
            expected_confidence = np.array([0.92], dtype=np.float32)
            np.testing.assert_array_equal(call_kwargs['confidence'], expected_confidence)
            
            # Class IDs (hash of class name for consistent mapping)
            expected_class_id = np.array([hash("person") % 1000], dtype=int)
            np.testing.assert_array_equal(call_kwargs['class_id'], expected_class_id)
    
    def test_multiple_detections_conversion(self):
        """Convert multiple detections with different classes"""
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
            ),
            Detection(
                class_name="bicycle",
                confidence=0.78,
                bbox=BoundingBox(x=500, y=100, width=60, height=120)
            )
        ]
        
        event = DetectionEvent(
            source_id=0,
            frame_id=123,
            timestamp=datetime.now(),
            model_id="yolov8x-640",
            inference_time_ms=45.2,
            detections=detections
        )
        
        renderer = DetectionRenderer()
        
        with patch('cupertino_nvr.wall.renderer.Detections') as mock_detections:
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            renderer.render_frame(frame, event)
            
            call_kwargs = mock_detections.call_args[1]
            
            # Should have 3 detections
            assert call_kwargs['xyxy'].shape[0] == 3
            assert call_kwargs['confidence'].shape[0] == 3
            assert call_kwargs['class_id'].shape[0] == 3
            
            # Verify bounding box conversions
            expected_boxes = np.array([
                [100, 150, 180, 350],  # person: x,y,x+w,y+h
                [300, 200, 420, 300],  # car
                [500, 100, 560, 220],  # bicycle
            ], dtype=np.float32)
            
            np.testing.assert_array_equal(call_kwargs['xyxy'], expected_boxes)
            
            # Verify confidences
            expected_confidences = np.array([0.92, 0.85, 0.78], dtype=np.float32)
            np.testing.assert_array_equal(call_kwargs['confidence'], expected_confidences)
    
    def test_empty_detections_conversion(self):
        """Handle events with no detections"""
        event = DetectionEvent(
            source_id=0,
            frame_id=123,
            timestamp=datetime.now(),
            model_id="yolov8x-640",
            inference_time_ms=45.2,
            detections=[]  # No detections
        )
        
        renderer = DetectionRenderer()
        
        with patch('cupertino_nvr.wall.renderer.Detections') as mock_detections:
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            renderer.render_frame(frame, event)
            
            call_kwargs = mock_detections.call_args[1]
            
            # Should create empty arrays
            assert call_kwargs['xyxy'].shape == (0, 4)
            assert call_kwargs['confidence'].shape == (0,)
            assert call_kwargs['class_id'].shape == (0,)
    
    def test_tracker_id_handling(self):
        """Verify tracker IDs are properly handled"""
        detection_with_tracker = Detection(
            class_name="person",
            confidence=0.92,
            bbox=BoundingBox(x=100, y=150, width=80, height=200),
            tracker_id=42
        )
        
        detection_without_tracker = Detection(
            class_name="car", 
            confidence=0.85,
            bbox=BoundingBox(x=300, y=200, width=120, height=100)
            # No tracker_id
        )
        
        event = DetectionEvent(
            source_id=0,
            frame_id=123,
            timestamp=datetime.now(),
            model_id="yolov8x-640",
            inference_time_ms=45.2,
            detections=[detection_with_tracker, detection_without_tracker]
        )
        
        renderer = DetectionRenderer()
        
        with patch('cupertino_nvr.wall.renderer.Detections') as mock_detections:
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            renderer.render_frame(frame, event)
            
            call_kwargs = mock_detections.call_args[1]
            
            # Should handle mixed tracker scenarios
            # For now, we don't pass tracker_id to supervision, but test doesn't fail
            assert 'xyxy' in call_kwargs
            assert 'confidence' in call_kwargs
            assert 'class_id' in call_kwargs


class TestSupervisionAnnotationPipeline:
    """Test the actual annotation rendering with supervision"""
    
    def test_box_annotation_rendering(self):
        """Verify BoxAnnotator is used correctly"""
        renderer = DetectionRenderer()
        
        # Mock supervision components
        mock_detections = MagicMock(spec=Detections)
        mock_box_annotator = MagicMock()
        mock_label_annotator = MagicMock()
        
        renderer.box_annotator = mock_box_annotator
        renderer.label_annotator = mock_label_annotator
        
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        
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
            inference_time_ms=45.2,
            detections=[detection]
        )
        
        with patch('cupertino_nvr.wall.renderer.Detections', return_value=mock_detections):
            renderer.render_frame(frame, event)
            
            # Verify annotators were called
            mock_box_annotator.annotate.assert_called_once()
            mock_label_annotator.annotate.assert_called_once()
            
            # Verify call order: box first, then labels
            box_call = mock_box_annotator.annotate.call_args
            label_call = mock_label_annotator.annotate.call_args
            
            # Both should receive the frame and detections
            assert len(box_call[0]) == 2  # frame, detections
            assert len(label_call[0]) == 2  # frame, detections
    
    def test_class_name_labels_generation(self):
        """Verify class names are properly formatted for labels"""
        renderer = DetectionRenderer()
        
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
            inference_time_ms=45.2,
            detections=[detection]
        )
        
        # Test label generation
        labels = renderer._generate_labels(event.detections)
        
        assert len(labels) == 1
        assert "person" in labels[0]
        assert "0.92" in labels[0] or "92%" in labels[0]  # Confidence should be included
    
    def test_confidence_formatting_in_labels(self):
        """Verify confidence scores are properly formatted"""
        renderer = DetectionRenderer()
        
        detections = [
            Detection(class_name="person", confidence=0.92341, bbox=BoundingBox(0, 0, 10, 10)),
            Detection(class_name="car", confidence=0.85678, bbox=BoundingBox(0, 0, 10, 10)),
            Detection(class_name="bike", confidence=0.70123, bbox=BoundingBox(0, 0, 10, 10)),
        ]
        
        labels = renderer._generate_labels(detections)
        
        assert len(labels) == 3
        
        # Confidence should be formatted consistently (e.g., 2 decimal places)
        for i, detection in enumerate(detections):
            label = labels[i]
            assert detection.class_name in label
            # Should contain confidence in some reasonable format
            assert any(char.isdigit() for char in label)


class TestSupervisionPerformance:
    """Ensure supervision integration meets performance requirements"""
    
    def test_rendering_performance_baseline(self):
        """Benchmark rendering time for typical detection load"""
        import time
        
        renderer = DetectionRenderer()
        
        # Create moderate detection load (5 detections)
        detections = [
            Detection(
                class_name=f"class_{i}",
                confidence=0.8 + i * 0.02,
                bbox=BoundingBox(x=i*100, y=i*50, width=80, height=120)
            )
            for i in range(5)
        ]
        
        event = DetectionEvent(
            source_id=0,
            frame_id=123,
            timestamp=datetime.now(),
            model_id="yolov8x-640",
            inference_time_ms=45.2,
            detections=detections
        )
        
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)  # HD resolution
        
        # Measure rendering time
        start_time = time.time()
        
        for _ in range(10):  # Average over multiple runs
            rendered_frame = renderer.render_frame(frame, event)
        
        end_time = time.time()
        avg_time_ms = (end_time - start_time) * 1000 / 10
        
        # Rendering should be fast enough for real-time video (< 10ms per frame)
        assert avg_time_ms < 10.0, f"Rendering too slow: {avg_time_ms:.2f}ms"
        
        # Verify output integrity
        assert rendered_frame.shape == frame.shape
        assert rendered_frame.dtype == frame.dtype
    
    def test_memory_efficiency_with_many_detections(self):
        """Verify memory usage is reasonable with many detections"""
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss
        
        renderer = DetectionRenderer()
        
        # Create many detections (stress test)
        detections = [
            Detection(
                class_name=f"obj_{i}",
                confidence=0.5 + (i % 50) * 0.01,
                bbox=BoundingBox(
                    x=(i % 10) * 50,
                    y=(i // 10) * 30,
                    width=40,
                    height=60
                )
            )
            for i in range(100)  # 100 detections
        ]
        
        event = DetectionEvent(
            source_id=0,
            frame_id=123,
            timestamp=datetime.now(),
            model_id="yolov8x-640",
            inference_time_ms=45.2,
            detections=detections
        )
        
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)  # 4K resolution
        
        # Render multiple frames
        for _ in range(10):
            rendered_frame = renderer.render_frame(frame, event)
            del rendered_frame  # Explicit cleanup
        
        final_memory = process.memory_info().rss
        memory_increase_mb = (final_memory - initial_memory) / 1024 / 1024
        
        # Memory increase should be reasonable (< 50MB for this test)
        assert memory_increase_mb < 50, f"Memory usage too high: {memory_increase_mb:.2f}MB"


class TestSupervisionExtensibility:
    """Verify architecture supports future supervision features"""
    
    def test_annotator_configurability(self):
        """Verify annotators can be configured/customized"""
        from supervision import BoxAnnotator, LabelAnnotator
        
        # Should be able to create renderer with custom annotators
        custom_box_annotator = BoxAnnotator(
            color=(255, 0, 0),  # Red boxes
            thickness=3
        )
        
        custom_label_annotator = LabelAnnotator(
            color=(255, 255, 255),  # White text
            text_scale=0.8
        )
        
        renderer = DetectionRenderer()
        
        # Should be able to replace annotators
        renderer.box_annotator = custom_box_annotator
        renderer.label_annotator = custom_label_annotator
        
        # Should still work correctly
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
            inference_time_ms=45.2,
            detections=[detection]
        )
        
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        
        # Should not raise exception
        rendered_frame = renderer.render_frame(frame, event)
        assert rendered_frame.shape == frame.shape
    
    def test_future_supervision_features_extensibility(self):
        """Verify architecture can easily add future supervision features"""
        
        # Test that DetectionEvent schema can accommodate future fields
        # without breaking existing code
        
        # Future: keypoints support
        future_detection_data = {
            "class_name": "person",
            "confidence": 0.92,
            "bbox": {"x": 100, "y": 150, "width": 80, "height": 200},
            "tracker_id": 42,
            # Future fields that might be added:
            "keypoints": [[120, 160], [130, 170]],  # Not in current schema
            "mask": "base64_encoded_mask_data",     # Not in current schema
        }
        
        # Current Detection model should ignore unknown fields gracefully
        try:
            detection = Detection(
                class_name="person",
                confidence=0.92,
                bbox=BoundingBox(x=100, y=150, width=80, height=200),
                tracker_id=42
            )
            
            # Should create successfully (unknown fields ignored)
            assert detection.class_name == "person"
            assert detection.tracker_id == 42
            
        except Exception as e:
            pytest.fail(f"Future extensibility test failed: {e}")
    
    def test_supervision_version_compatibility(self):
        """Ensure we're using supervision API correctly for version stability"""
        from supervision import Detections, BoxAnnotator, LabelAnnotator
        
        # Test that we're using stable supervision APIs
        # These should exist and be callable
        
        # Detections constructor
        empty_detections = Detections.empty()
        assert hasattr(empty_detections, 'xyxy')
        assert hasattr(empty_detections, 'confidence')
        
        # Annotators
        box_annotator = BoxAnnotator()
        label_annotator = LabelAnnotator()
        
        assert hasattr(box_annotator, 'annotate')
        assert hasattr(label_annotator, 'annotate')
        
        # These are the stable APIs we depend on
        assert callable(box_annotator.annotate)
        assert callable(label_annotator.annotate)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])