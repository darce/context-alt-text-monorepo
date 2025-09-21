"""
CVLFace InsightFace Adapter Implementation
Adapter for InsightFace models with built-in alignment.
"""
import logging
from typing import List, Optional, Dict, Any
import numpy as np
import torch
import cv2

from ..domain import ModelType, AlignmentStrategy, FaceDetection
from .base_cvlface_adapter import BaseCVLFaceAdapter

logger = logging.getLogger(__name__)


class CVLFaceInsightAdapter(BaseCVLFaceAdapter):
    """
    CVLFace InsightFace adapter with built-in alignment.
    
    Features:
    - Built-in face alignment
    - SCRFD face detection
    - ArcFace embedding extraction
    """
    
    def __init__(self, model_id: str = "deepinsight/insightface-scrfd-arcface-w600k", 
                 device: str = "auto", **kwargs):
        """
        Initialize InsightFace adapter.
        
        Args:
            model_id: HuggingFace model identifier (not used, placeholder)
            device: Device to use
            **kwargs: Additional configuration
        """
        self.detection_threshold = kwargs.get('detection_threshold', 0.3)  # Lowered from 0.5 to 0.3
        self.min_face_size = kwargs.get('min_face_size', 40)
        self.max_faces = kwargs.get('max_faces', 10)
        
        # Override model_id for InsightFace
        self.insightface_model = kwargs.get('insightface_model', 'buffalo_l')
        
        super().__init__(model_id, device)
    
    def get_model_type(self) -> ModelType:
        """Get the model type for this adapter."""
        return ModelType.INSIGHTFACE_W600K
    
    def get_alignment_strategy(self) -> AlignmentStrategy:
        """Get the alignment strategy for this adapter."""
        return AlignmentStrategy.BUILT_IN
    
    def _initialize_model(self):
        """Initialize the InsightFace model."""
        try:
            logger.info(f"🔧 Loading InsightFace model: {self.insightface_model}")
            
            # Import InsightFace
            import insightface
            
            # Initialize InsightFace app
            self.model = insightface.app.FaceAnalysis(
                name=self.insightface_model,
                providers=['CUDAExecutionProvider', 'CPUExecutionProvider'] if self.device == 'cuda' else ['CPUExecutionProvider']
            )
            
            # Prepare model with detection threshold
            self.model.prepare(ctx_id=0 if self.device == 'cuda' else -1, det_size=(640, 640))
            
            # Set detection threshold on the model if possible
            if hasattr(self.model, 'det_model') and hasattr(self.model.det_model, 'det_thresh'):
                self.model.det_model.det_thresh = self.detection_threshold
                logger.info(f"🎯 Set InsightFace detection threshold to {self.detection_threshold}")
            elif hasattr(self.model, 'models') and 'detection' in self.model.models:
                # Try accessing detection model through models dict
                det_model = self.model.models['detection']
                if hasattr(det_model, 'det_thresh'):
                    det_model.det_thresh = self.detection_threshold
                    logger.info(f"🎯 Set InsightFace detection threshold to {self.detection_threshold}")
            else:
                logger.warning(f"⚠️ Could not set detection threshold on InsightFace model")
            
            self.is_initialized = True
            logger.info(f"✅ InsightFace model loaded successfully")
            
        except ImportError as e:
            logger.warning(f"⚠️ InsightFace not available: {e}")
            logger.info("🔧 Using mock InsightFace model for testing")
            self._initialize_mock_model()
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize InsightFace model: {e}")
            logger.info("🔧 Falling back to mock model")
            self._initialize_mock_model()
    
    def _initialize_mock_model(self):
        """Initialize a mock InsightFace model for testing."""
        import torch.nn as nn
        
        class MockInsightFaceModel:
            def __init__(self):
                # Simple mock that mimics InsightFace interface
                self.det_model = None
                self.rec_model = None
            
            def get(self, image, max_num=0):
                # Mock face detection and recognition
                # Return mock faces for testing
                height, width = image.shape[:2]
                
                # Mock detection: assume one face in center
                mock_face = type('obj', (object,), {})()
                mock_face.bbox = [width*0.2, height*0.2, width*0.8, height*0.8]
                mock_face.kps = [[width*0.3, height*0.4], [width*0.7, height*0.4], 
                               [width*0.5, height*0.5], [width*0.4, height*0.7], [width*0.6, height*0.7]]
                mock_face.embedding = np.random.randn(512).astype(np.float32)
                mock_face.det_score = 0.9
                
                return [mock_face]
        
        self.model = MockInsightFaceModel()
        self.is_initialized = True
        logger.info("✅ Mock InsightFace model initialized")
    
    def _detect_faces_impl(self, image: np.ndarray) -> List[FaceDetection]:
        """
        Detect faces using InsightFace SCRFD detector.
        
        Args:
            image: Input image array
            
        Returns:
            List of face detections
        """
        if not self.is_initialized:
            return []
        
        try:
            # Convert to RGB if needed (InsightFace expects RGB)
            if len(image.shape) == 3 and image.shape[2] == 3:
                if self._is_bgr_format(image):
                    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                else:
                    image_rgb = image
            else:
                image_rgb = image
            
            # Detect faces
            faces = self.model.get(image_rgb)
            
            detections = []
            for face in faces[:self.max_faces]:
                # Extract bounding box
                bbox = face.bbox.astype(int)
                x, y, x2, y2 = bbox
                w, h = x2 - x, y2 - y
                
                # Calculate confidence (use detection score)
                confidence = float(face.det_score)
                
                if confidence < self.detection_threshold:
                    continue
                
                # Extract landmarks (InsightFace provides 5 landmarks)
                landmarks = None
                if hasattr(face, 'kps') and face.kps is not None:
                    landmarks = face.kps.tolist()
                
                detection = FaceDetection(
                    bbox=[x, y, w, h],
                    confidence=confidence,
                    landmarks=landmarks
                )
                
                detections.append(detection)
            
            return detections
            
        except Exception as e:
            logger.error(f"InsightFace detection failed: {e}")
            return []
    
    def _extract_embedding_impl(self, face_image: np.ndarray) -> Optional[np.ndarray]:
        """
        Extract InsightFace embedding from aligned face image.
        
        Args:
            face_image: Aligned face image (112x112)
            
        Returns:
            Face embedding array or None
        """
        try:
            # InsightFace handles its own alignment, so we use the original detection
            # For now, we'll work with the aligned face image
            
            # Ensure proper format
            if face_image.shape[:2] != (112, 112):
                face_image = cv2.resize(face_image, (112, 112))
            
            # Convert to RGB if needed
            if len(face_image.shape) == 3 and face_image.shape[2] == 3:
                if self._is_bgr_format(face_image):
                    face_image = cv2.cvtColor(face_image, cv2.COLOR_BGR2RGB)
            
            # For InsightFace, we need to simulate the detection process
            # to get the embedding. This is a simplified approach.
            
            # Detect faces in the aligned image
            faces = self.model.get(face_image)
            
            if faces and len(faces) > 0:
                # Get the first face's embedding
                face = faces[0]
                embedding = face.embedding
                
                # Normalize embedding
                embedding = embedding / np.linalg.norm(embedding)
                
                return embedding
            
            return None
            
        except Exception as e:
            logger.error(f"InsightFace embedding extraction failed: {e}")
            return None
    
    def extract_embedding_from_detection(self, image: np.ndarray, 
                                        detection: FaceDetection) -> Optional[np.ndarray]:
        """
        Extract embedding directly from detection (preferred for InsightFace).
        
        Args:
            image: Original image
            detection: Face detection result
            
        Returns:
            Face embedding or None
        """
        try:
            # Convert to RGB if needed
            if len(image.shape) == 3 and image.shape[2] == 3:
                if self._is_bgr_format(image):
                    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                else:
                    image_rgb = image
            else:
                image_rgb = image
            
            # Get faces from InsightFace
            faces = self.model.get(image_rgb)
            
            if not faces:
                return None
            
            # Find the face that matches our detection
            bbox = detection.bbox
            x, y, w, h = bbox
            detection_center = (x + w/2, y + h/2)
            
            best_face = None
            min_distance = float('inf')
            
            for face in faces:
                face_bbox = face.bbox.astype(int)
                fx, fy, fx2, fy2 = face_bbox
                face_center = ((fx + fx2)/2, (fy + fy2)/2)
                
                # Calculate distance between centers
                distance = np.sqrt((detection_center[0] - face_center[0])**2 + 
                                 (detection_center[1] - face_center[1])**2)
                
                if distance < min_distance:
                    min_distance = distance
                    best_face = face
            
            if best_face is not None:
                embedding = best_face.embedding
                embedding = embedding / np.linalg.norm(embedding)
                return embedding
            
            return None
            
        except Exception as e:
            logger.error(f"InsightFace embedding extraction from detection failed: {e}")
            return None
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get InsightFace model information."""
        info = super().get_model_info()
        info.update({
            'quality_adaptive': False,
            'insightface_model': self.insightface_model,
            'detection_threshold': self.detection_threshold,
            'min_face_size': self.min_face_size,
            'max_faces': self.max_faces,
            'detector_type': 'SCRFD',
            'built_in_alignment': True
        })
        return info
