#!/usr/bin/env python3
"""
MTCNN Face Detection Adapter

Simple MTCNN-based face detection adapter for face alignment.
Uses facenet-pytorch MTCNN with CPU-only mode for compatibility.
"""

import os
import sys
import cv2
import numpy as np
from typing import List, Dict, Any, Optional, Tuple, Union
from PIL import Image
import logging
import torch

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(project_root)

from recognition.domain.entities import FaceDetection, FaceEmbedding, ModelType, AlignmentStrategy
from recognition.domain.interfaces import CVLFaceAdapter

logger = logging.getLogger(__name__)

class MTCNNFaceAdapter(CVLFaceAdapter):
    """MTCNN-based face detection adapter for face alignment."""
    
    def __init__(self, model_id: str = "mtcnn", device: str = "auto", **kwargs):
        """
        Initialize MTCNN Face Detection Adapter.
        
        Args:
            model_id: Model identifier (kept for compatibility)
            device: Device to use ('auto', 'cuda', 'cpu')
            **kwargs: Additional configuration
        """
        self.model_id = model_id
        self.device = self._resolve_device(device)
        self.detection_threshold = kwargs.get('detection_threshold', 0.6)
        self.min_face_size = kwargs.get('min_face_size', 15)  # Reduced from 20 to 15
        self.max_faces = kwargs.get('max_faces', 10)
        self.crop_size = kwargs.get('crop_size', (112, 112))
        
        # MTCNN thresholds for P-Net, R-Net, O-Net - relaxed for better detection
        self.thresholds = kwargs.get('thresholds', [0.5, 0.6, 0.7])  # Relaxed from [0.6, 0.7, 0.9]
        self.nms_thresholds = kwargs.get('nms_thresholds', [0.7, 0.7, 0.7])
        self.factor = kwargs.get('factor', 0.85)
        
        self.mtcnn = None
        self.is_initialized = False
        
        # Initialize model
        self._initialize_model()
    
    def _resolve_device(self, device: str) -> str:
        """
        Resolve device specification to actual device.
        
        Args:
            device: Device specification
            
        Returns:
            Resolved device string
        """
        if device == "auto":
            if torch.cuda.is_available():
                return "cuda"
            elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                return "mps"
            else:
                return "cpu"
        return device
    
    def get_model_type(self) -> ModelType:
        """Get the model type for this adapter."""
        return ModelType.INSIGHTFACE_W600K  # Use same as insight for compatibility
    
    def get_alignment_strategy(self) -> AlignmentStrategy:
        """Get the alignment strategy for this adapter."""
        return AlignmentStrategy.MTCNN
    
    def detect_faces(self, image: Union[Image.Image, np.ndarray]) -> List[FaceDetection]:
        """
        Detect faces in an image.
        
        Args:
            image: Input image
            
        Returns:
            List of face detections
        """
        # For PIL Images, call MTCNN directly to avoid conversion issues
        if isinstance(image, Image.Image):
            return self._detect_faces_from_pil(image)
        else:
            # For numpy arrays, convert to PIL and process
            image_np = image
            return self._detect_faces_impl(image_np)
    
    def extract_embedding(self, face_image: np.ndarray) -> Optional[FaceEmbedding]:
        """
        Extract face embedding from aligned face image.
        MTCNN is primarily for face detection and alignment, not embedding extraction.
        This method returns the aligned face data.
        
        Args:
            face_image: Aligned face image
            
        Returns:
            FaceEmbedding with the aligned face data
        """
        try:
            # MTCNN is used for alignment, return the aligned face as embedding data
            # This will be used by other models for actual embedding extraction
            return FaceEmbedding(
                embedding=face_image.flatten(),  # Flatten to 1D array for compatibility
                model_type=self.get_model_type(),
                confidence=1.0  # Alignment confidence
            )
        except Exception as e:
            logger.error(f"❌ Error creating face embedding: {e}")
            return None

    def extract_embedding_from_detection(self, image: np.ndarray, detection: FaceDetection) -> Optional[np.ndarray]:
        """
        Extract aligned face from detection for use by other models.
        
        Args:
            image: Input image
            detection: Face detection result
            
        Returns:
            Aligned face as numpy array or None if alignment fails
        """
        try:
            # Extract face region using bbox
            x1, y1, x2, y2 = detection.bbox
            
            # Get image dimensions
            img_height, img_width = image.shape[:2]
            
            # Clamp coordinates to image boundaries
            x1_clamped = max(0, int(x1))
            y1_clamped = max(0, int(y1))
            x2_clamped = min(img_width, int(x2))
            y2_clamped = min(img_height, int(y2))
            
            # Ensure valid box dimensions after clamping
            if x2_clamped <= x1_clamped or y2_clamped <= y1_clamped:
                logger.warning(f"Invalid bbox dimensions after clamping: ({x1}, {y1}, {x2}, {y2})")
                return None
            
            # Check if the clamped region is too small (less than 20x20 pixels)
            width = x2_clamped - x1_clamped
            height = y2_clamped - y1_clamped
            if width < 20 or height < 20:
                logger.warning(f"Face region too small after clamping: {width}x{height}")
                return None
            
            face_region = image[y1_clamped:y2_clamped, x1_clamped:x2_clamped]
            
            if face_region.size == 0:
                logger.warning(f"Empty face region extracted from bbox ({x1}, {y1}, {x2}, {y2}) in image {image.shape}")
                return None
            
            # Resize to standard size for compatibility
            aligned_face = cv2.resize(face_region, (112, 112))
            
            return aligned_face
            
        except Exception as e:
            logger.error(f"❌ Error extracting aligned face: {e}")
            return None
    
    def _initialize_model(self) -> None:
        """Initialize MTCNN model."""
        try:
            logger.info(f"🔧 Initializing MTCNN face detector")
            logger.info(f"🔧 Using device: {self.device}")
            
            # Try to import MTCNN - we'll implement a simple version
            self._initialize_simple_mtcnn()
            
            self.is_initialized = True
            logger.info(f"✅ MTCNN face detector loaded successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize MTCNN: {e}")
            logger.info("🔧 Falling back to mock model")
            self._initialize_mock_model()
    
    def _initialize_simple_mtcnn(self):
        """Initialize a simplified MTCNN implementation."""
        try:
            # Try to use facenet-pytorch MTCNN if available
            from facenet_pytorch import MTCNN as FacenetMTCNN
            
            # Force CPU usage for MTCNN to avoid MPS compatibility issues
            device = torch.device('cpu')
            
            self.mtcnn = FacenetMTCNN(
                image_size=160,
                margin=0,
                min_face_size=self.min_face_size,
                thresholds=self.thresholds,
                factor=self.factor,
                post_process=True,
                device=device,
                keep_all=True
            )
            
            logger.info(f"✅ Using facenet-pytorch MTCNN (CPU only for compatibility)")
            
        except ImportError:
            logger.warning("facenet-pytorch not available, using mock MTCNN")
            self._initialize_mock_model()
    
    def _initialize_mock_model(self):
        """Initialize a mock MTCNN for testing."""
        class MockMTCNN:
            def __init__(self, min_face_size, thresholds):
                self.min_face_size = min_face_size
                self.thresholds = thresholds
            
            def detect(self, image):
                # Mock detection that finds a centered face
                w, h = image.size
                face_size = min(w, h) // 3
                center_x, center_y = w // 2, h // 2
                
                # Mock bbox (x1, y1, x2, y2)
                bbox = [
                    center_x - face_size // 2,  # x1
                    center_y - face_size // 2,  # y1
                    center_x + face_size // 2,  # x2
                    center_y + face_size // 2,  # y2
                    0.95  # confidence
                ]
                
                # Mock landmarks (5 points)
                landmarks = [
                    [center_x - face_size // 4, center_y - face_size // 4],  # left eye
                    [center_x + face_size // 4, center_y - face_size // 4],  # right eye
                    [center_x, center_y],  # nose
                    [center_x - face_size // 6, center_y + face_size // 4],  # left mouth
                    [center_x + face_size // 6, center_y + face_size // 4],  # right mouth
                ]
                
                return [bbox], [landmarks]
        
        self.mtcnn = MockMTCNN(self.min_face_size, self.thresholds)
        logger.info(f"✅ Using mock MTCNN (for testing)")
    
    def _detect_faces_from_pil(self, pil_image: Image.Image) -> List[FaceDetection]:
        """
        Detect faces directly from PIL Image, avoiding conversion issues.
        
        Args:
            pil_image: PIL Image in RGB format
            
        Returns:
            List of face detections
        """
        if not self.is_initialized:
            return []
        
        try:
            # Call MTCNN directly on the PIL image - no conversion dance!
            if hasattr(self.mtcnn, 'detect'):
                # facenet-pytorch MTCNN returns (boxes, probs)
                boxes, probs = self.mtcnn.detect(pil_image)
                logger.debug(f"Direct PIL MTCNN detect() returned: boxes={boxes}, probs={probs}")
                if boxes is None:
                    logger.debug("No faces detected by direct PIL MTCNN")
                    return []
                # facenet-pytorch doesn't return landmarks from detect(), set to None
                landmarks = None
            else:
                # Custom MTCNN implementation
                boxes, landmarks = self._detect_with_custom_mtcnn(pil_image)
                probs = None
            
            detections = []
            
            # Process detections (same logic as _detect_faces_impl)
            if boxes is not None and len(boxes) > 0:
                logger.debug(f"Processing {len(boxes)} detected faces from PIL")
                for i, bbox in enumerate(boxes[:self.max_faces]):
                    if bbox is None:
                        logger.debug(f"Skipping face {i}: bbox is None")
                        continue
                    
                    logger.debug(f"Processing face {i}: bbox={bbox}")
                    
                    # Convert bbox format
                    if len(bbox) >= 4:
                        x1, y1, x2, y2 = bbox[:4]
                        # Get confidence from probs array if available, otherwise from bbox or default
                        if probs is not None and i < len(probs):
                            confidence = float(probs[i])
                        elif len(bbox) > 4:
                            confidence = float(bbox[4])
                        else:
                            confidence = 0.9  # Default confidence
                        
                        logger.debug(f"Face {i}: coords=({x1}, {y1}, {x2}, {y2}), confidence={confidence}")
                        
                        # Relax validation - allow faces that extend beyond image boundaries
                        # Only check that we have reasonable coordinates
                        if x2 <= x1 or y2 <= y1:
                            logger.warning(f"Invalid bbox dimensions: ({x1}, {y1}, {x2}, {y2})")
                            continue
                            
                    else:
                        logger.warning(f"Bbox {i} has insufficient coordinates: {bbox}")
                        continue
                    
                    # Apply confidence threshold
                    if confidence < self.detection_threshold:
                        logger.debug(f"Face {i} rejected due to low confidence: {confidence} < {self.detection_threshold}")
                        continue
                    
                    logger.debug(f"Face {i} passed all validations - creating FaceDetection")
                    
                    # Generate default landmarks based on bbox
                    face_landmarks = self._generate_default_landmarks(x1, y1, x2, y2)
                    
                    detection = FaceDetection(
                        bbox=(int(x1), int(y1), int(x2), int(y2)),  # Keep (x1, y1, x2, y2) format
                        confidence=float(confidence),
                        landmarks=face_landmarks
                    )
                    
                    logger.debug(f"Created FaceDetection {i}: {detection}")
                    detections.append(detection)
            
            logger.debug(f"Returning {len(detections)} detections from _detect_faces_from_pil")
            return detections
            
        except Exception as e:
            logger.error(f"❌ Direct PIL MTCNN face detection failed: {e}")
            return []
    
    def _detect_faces_impl(self, image: np.ndarray) -> List[FaceDetection]:
        """
        Detect faces using MTCNN.
        
        Args:
            image: Input image array
            
        Returns:
            List of face detections
        """
        if not self.is_initialized:
            return []
        
        try:
            # Convert numpy array to PIL Image for MTCNN
            if isinstance(image, np.ndarray):
                if len(image.shape) == 3 and image.shape[2] == 3:
                    # Ensure RGB format
                    if self._is_bgr_format(image):
                        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                    else:
                        image_rgb = image
                    pil_image = Image.fromarray(image_rgb.astype(np.uint8))
                else:
                    pil_image = Image.fromarray(image.astype(np.uint8))
            else:
                pil_image = image
            
            # Detect faces with MTCNN
            if hasattr(self.mtcnn, 'detect'):
                # facenet-pytorch MTCNN returns (boxes, probs)
                boxes, probs = self.mtcnn.detect(pil_image)
                logger.debug(f"Raw MTCNN detect() returned: boxes={boxes}, probs={probs}")
                if boxes is None:
                    logger.debug("No faces detected by raw MTCNN")
                    return []
                # facenet-pytorch doesn't return landmarks from detect(), set to None
                landmarks = None
            else:
                # Custom MTCNN implementation
                boxes, landmarks = self._detect_with_custom_mtcnn(pil_image)
                probs = None
            
            detections = []
            
            # Process detections
            if boxes is not None and len(boxes) > 0:
                logger.debug(f"Processing {len(boxes)} detected faces")
                for i, bbox in enumerate(boxes[:self.max_faces]):
                    if bbox is None:
                        logger.debug(f"Skipping face {i}: bbox is None")
                        continue
                    
                    logger.debug(f"Processing face {i}: bbox={bbox}")
                    
                    # Convert bbox format
                    if len(bbox) >= 4:
                        x1, y1, x2, y2 = bbox[:4]
                        # Get confidence from probs array if available, otherwise from bbox or default
                        if probs is not None and i < len(probs):
                            confidence = float(probs[i])
                        elif len(bbox) > 4:
                            confidence = float(bbox[4])
                        else:
                            confidence = 0.9  # Default confidence
                        
                        logger.debug(f"Face {i}: coords=({x1}, {y1}, {x2}, {y2}), confidence={confidence}")
                        
                        # Relax validation - allow faces that extend beyond image boundaries
                        # Only check that we have reasonable coordinates
                        if x2 <= x1 or y2 <= y1:
                            logger.warning(f"Invalid bbox dimensions: ({x1}, {y1}, {x2}, {y2})")
                            continue
                            
                    else:
                        logger.warning(f"Bbox {i} has insufficient coordinates: {bbox}")
                        continue
                    
                    # Apply confidence threshold
                    if confidence < self.detection_threshold:
                        logger.debug(f"Face {i} rejected due to low confidence: {confidence} < {self.detection_threshold}")
                        continue
                    
                    logger.debug(f"Face {i} passed all validations - creating FaceDetection")
                    
                    # Calculate width and height
                    w, h = x2 - x1, y2 - y1
                    
                    # Create face detection with proper landmarks if available
                    face_landmarks = None
                    if landmarks is not None and i < len(landmarks) and landmarks[i] is not None:
                        # Convert landmarks to the expected format
                        lm = landmarks[i]
                        if hasattr(lm, 'shape') and len(lm.shape) == 2:
                            # landmarks is a 2D array (N, 2)
                            face_landmarks = lm.flatten().tolist()
                        elif isinstance(lm, (list, tuple)) and len(lm) >= 10:
                            # landmarks is already flattened
                            face_landmarks = list(lm)[:10]  # Take first 10 points
                        else:
                            # Generate default landmarks
                            face_landmarks = self._generate_default_landmarks(x1, y1, x2, y2)
                    else:
                        # Generate default landmarks based on bbox
                        face_landmarks = self._generate_default_landmarks(x1, y1, x2, y2)
                    
                    detection = FaceDetection(
                        bbox=(int(x1), int(y1), int(x2), int(y2)),  # Keep (x1, y1, x2, y2) format
                        confidence=float(confidence),
                        landmarks=face_landmarks
                    )
                    
                    logger.debug(f"Created FaceDetection {i}: {detection}")
                    detections.append(detection)
            
            logger.debug(f"Returning {len(detections)} detections from _detect_faces_impl")
            return detections
            
        except Exception as e:
            logger.error(f"❌ MTCNN face detection failed: {e}")
            return []
    
    def _is_bgr_format(self, image: np.ndarray) -> bool:
        """
        Heuristic to detect if image is in BGR format.
        """
        # Simple heuristic: assume BGR if blue channel has higher mean than red
        if len(image.shape) == 3 and image.shape[2] == 3:
            blue_mean = np.mean(image[:, :, 0])
            red_mean = np.mean(image[:, :, 2])
            return blue_mean > red_mean * 1.1
        return False
    
    def _generate_default_landmarks(self, x1: float, y1: float, x2: float, y2: float) -> List[float]:
        """Generate default facial landmarks based on bounding box."""
        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2
        width = x2 - x1
        height = y2 - y1
        
        # Standard facial landmark positions (relative to bbox)
        landmarks = [
            center_x - width * 0.2, center_y - height * 0.2,  # left eye
            center_x + width * 0.2, center_y - height * 0.2,  # right eye
            center_x, center_y,                               # nose
            center_x - width * 0.15, center_y + height * 0.2, # left mouth
            center_x + width * 0.15, center_y + height * 0.2, # right mouth
        ]
        
        return landmarks


# Test script
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test MTCNN Face Detection")
    parser.add_argument("--image", default="scripts/mock_entities/entity-bea-burke.jpg", 
                       help="Path to test image")
    args = parser.parse_args()
    
    print("🔧 Testing MTCNN Face Detection")
    
    # Test the adapter
    adapter = MTCNNFaceAdapter()
    
    if os.path.exists(args.image):
        image = cv2.imread(args.image)
        detections = adapter._detect_faces_impl(image)
        
        print(f"📸 Image: {args.image}")
        print(f"🔍 Detected {len(detections)} faces:")
        
        for i, detection in enumerate(detections):
            print(f"  Face {i+1}: bbox={detection.bbox}, confidence={detection.confidence:.3f}")
    else:
        print(f"❌ Image not found: {args.image}")
