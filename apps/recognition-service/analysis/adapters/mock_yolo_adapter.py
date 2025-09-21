import logging
from typing import List, Dict, Any, Optional
from PIL import Image
import random

from analysis.ports.object_detection_base import IObjectDetector

class MockYoloAdapter(IObjectDetector):
    """Mock YOLO adapter that simulates object detection without loading real models."""
    
    def __init__(self, model_path: str, device: str, confidence_threshold: float = 0.5):
        self.model_path = model_path
        self.device = device
        self.confidence_threshold = confidence_threshold
        self.model = None
        self._model_loaded = True  # Always "loaded" for mock
        
        # Common COCO classes that YOLO typically detects
        self.class_names = {
            0: 'person', 1: 'bicycle', 2: 'car', 3: 'motorcycle', 4: 'airplane',
            5: 'bus', 6: 'train', 7: 'truck', 8: 'boat', 9: 'traffic light',
            10: 'fire hydrant', 11: 'stop sign', 12: 'parking meter', 13: 'bench',
            14: 'bird', 15: 'cat', 16: 'dog', 17: 'horse', 18: 'sheep', 19: 'cow',
            20: 'elephant', 21: 'bear', 22: 'zebra', 23: 'giraffe', 24: 'backpack',
            25: 'umbrella', 26: 'handbag', 27: 'tie', 28: 'suitcase', 29: 'frisbee',
            30: 'skis', 31: 'snowboard', 32: 'sports ball', 33: 'kite', 34: 'baseball bat',
            35: 'baseball glove', 36: 'skateboard', 37: 'surfboard', 38: 'tennis racket',
            39: 'bottle', 40: 'wine glass', 41: 'cup', 42: 'fork', 43: 'knife',
            44: 'spoon', 45: 'bowl', 46: 'banana', 47: 'apple', 48: 'sandwich',
            49: 'orange', 50: 'broccoli', 51: 'carrot', 52: 'hot dog', 53: 'pizza',
            54: 'donut', 55: 'cake', 56: 'chair', 57: 'couch', 58: 'potted plant',
            59: 'bed', 60: 'dining table', 61: 'toilet', 62: 'tv', 63: 'laptop',
            64: 'mouse', 65: 'remote', 66: 'keyboard', 67: 'cell phone', 68: 'microwave',
            69: 'oven', 70: 'toaster', 71: 'sink', 72: 'refrigerator', 73: 'book',
            74: 'clock', 75: 'vase', 76: 'scissors', 77: 'teddy bear', 78: 'hair drier',
            79: 'toothbrush'
        }
        
        logging.info(f"Mock YOLO adapter initialized (simulating {model_path})")

    def detect_objects(self, image: Image.Image) -> List[Dict[str, Any]]:
        """
        Simulate object detection with realistic mock data.
        """
        logging.info(f"Mock detection on image size: {image.size}")
        
        # Simulate realistic detections based on image characteristics
        detections = []
        
        # Generate 1-5 random detections
        num_detections = random.randint(1, 5)
        
        # Common objects likely to be in photos
        likely_classes = [0, 56, 39, 63, 73, 62, 58, 57]  # person, chair, bottle, laptop, book, tv, potted plant, couch
        
        for i in range(num_detections):
            # Random confidence above our threshold
            confidence = random.uniform(self.confidence_threshold, 0.95)
            
            # Random class from likely classes
            class_id = random.choice(likely_classes)
            class_name = self.class_names[class_id]
            
            # Random bounding box within image bounds
            x1 = random.randint(0, image.width // 2)
            y1 = random.randint(0, image.height // 2)
            x2 = random.randint(x1 + 50, min(image.width, x1 + 200))
            y2 = random.randint(y1 + 50, min(image.height, y1 + 200))
            
            detection = {
                "bbox": [float(x1), float(y1), float(x2), float(y2)],
                "confidence": confidence,
                "class_id": class_id,
                "class_name": class_name
            }
            detections.append(detection)
        
        logging.info(f"Mock detected {len(detections)} objects")
        return detections
    
    def crop_objects(
            self,
            image: Image.Image,
            detections: List[Dict[str, Any]],
            labels: Optional[List[str]] = None
        ) -> List[Image.Image]:
        """
        Crop detected objects from the image.
        """
        cropped_images = []
        
        for detection in detections:
            # Filter by labels if specified
            if labels and detection.get('class_name') not in labels:
                continue
                
            # Get bounding box coordinates [x1, y1, x2, y2]
            bbox = detection.get('bbox')
            if not bbox or len(bbox) != 4:
                continue
                
            x1, y1, x2, y2 = map(int, bbox)
            
            # Ensure coordinates are within image bounds
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(image.width, x2)
            y2 = min(image.height, y2)
            
            # Crop the object from the image
            if x2 > x1 and y2 > y1:  # Valid bounding box
                cropped = image.crop((x1, y1, x2, y2))
                cropped_images.append(cropped)
        
        logging.info(f"Cropped {len(cropped_images)} objects from image")
        return cropped_images
