import logging
from typing import List, Dict, Any, Optional
from PIL import Image

from analysis.ports.object_detection_base import IObjectDetector
from shared.infrastructure.model_loaders.yolo_model_loader import load_yolo_model

class YoloAdapter(IObjectDetector):
    """YOLO adapter for object detection (version-agnostic)."""
    
    def __init__(self, model_path: str, device: str, confidence_threshold: float = 0.5, config: dict = None):
        self.model_path = model_path
        self.device = device
        self.confidence_threshold = confidence_threshold
        self.config = config or {}
        self.model = None
        self._model_loaded = False
        logging.info(f"YOLO adapter initialized with model path: {model_path}")

    def _load_model(self):
        """Lazy load the YOLO model only when needed."""
        if self._model_loaded:
            return
        try:
            self.model, self.device = load_yolo_model(self.model_path, self.device, self.config)
            self._model_loaded = True
            logging.info("YOLO model loaded successfully")
        except Exception as e:
            logging.error(f"Failed to load YOLO model: {e}")
            raise RuntimeError(f"Could not load YOLO model from {self.model_path}: {e}")
    
    def detect_objects(self, image: Image.Image) -> List[Dict[str, Any]]:
        """
        Detect objects in the image using YOLO.
        
        Args:
            image: PIL Image object
            
        Returns:
            List of detected objects with bounding boxes, confidence, and class names
        """
        # Lazy load model
        if not self._model_loaded:
            self._load_model()
            
        if self.model is None:
            raise RuntimeError("YOLO model not loaded")
            
        try:
            # Get verbosity from config
            verbose = self.config.get('settings', {}).get('verbose', False)
            
            # Run YOLO inference with configurable verbosity
            results = self.model(image, verbose=verbose)
            
            detections = []
            for result in results:
                boxes = result.boxes
                if boxes is not None:
                    for box in boxes:
                        # Extract detection information
                        conf = float(box.conf[0].cpu().numpy())
                        
                        # Filter by confidence threshold
                        if conf < self.confidence_threshold:
                            continue
                            
                        xyxy = box.xyxy[0].cpu().numpy()  # Bounding box coordinates
                        cls = int(box.cls[0].cpu().numpy())  # Class index
                        
                        # Get class name from YOLO model
                        class_name = self.model.names[cls] if hasattr(self.model, 'names') else f"class_{cls}"
                        
                        # Calculate area from bounding box coordinates [x1, y1, x2, y2]
                        x1, y1, x2, y2 = xyxy.tolist()
                        area = float((x2 - x1) * (y2 - y1))
                        
                        detection = {
                            "bbox": [float(x) for x in xyxy.tolist()],  # Convert to float list
                            "confidence": float(conf),
                            "class_id": int(cls),
                            "class_name": class_name,
                            "area": area
                        }
                        detections.append(detection)
            
            logging.info(f"YOLO detected {len(detections)} objects")
            return detections
            
        except Exception as e:
            logging.error(f"YOLO object detection failed: {e}")
            return []
    
    def crop_objects(
            self,
            image: Image.Image,
            detections: List[Dict[str, float]],
            labels: Optional[List[str]] = None
        ) -> List[Image.Image]:
        """
        Crop detected objects from the image.
        
        Args:
            image: The input image to process
            detections: List of detected objects with bounding boxes
            labels: Optional list of labels to filter by
            
        Returns:
            List of cropped images of the detected objects
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
    
    def is_ready(self) -> bool:
        """Return True if the YOLO model is loaded and ready for inference."""
        return self._model_loaded and self.model is not None
