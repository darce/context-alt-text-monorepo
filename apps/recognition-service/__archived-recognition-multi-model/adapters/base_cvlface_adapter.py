"""
Base CVLFace Adapter Implementation
Abstract base class for CVLFace model adapters.
"""
import logging
from abc import ABC, abstractmethod
from typing import List, Optional, Union, Dict, Any
import numpy as np
from PIL import Image
import torch
import cv2

from ..domain import CVLFaceAdapter, ModelType, AlignmentStrategy, FaceDetection, FaceEmbedding

logger = logging.getLogger(__name__)


class BaseCVLFaceAdapter(CVLFaceAdapter, ABC):
    """
    Base class for CVLFace model adapters.
    
    Provides common functionality for face detection and embedding extraction
    while allowing specific models to override behavior as needed.
    """
    
    def __init__(self, model_id: str, device: str = "auto"):
        """
        Initialize base CVLFace adapter.
        
        Args:
            model_id: HuggingFace model identifier
            device: Device to use ('cpu', 'cuda', 'auto')
        """
        self.model_id = model_id
        self.device = self._resolve_device(device)
        self.model = None
        self.detector = None
        self.is_initialized = False
        
        logger.info(f"🔧 Initializing {self.__class__.__name__} with model: {model_id}")
        logger.info(f"🔧 Using device: {self.device}")
        
        # Initialize model lazily
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
    
    @abstractmethod
    def _initialize_model(self):
        """Initialize the specific model implementation."""
        pass
    
    @abstractmethod
    def get_model_type(self) -> ModelType:
        """Get the model type for this adapter."""
        pass
    
    @abstractmethod
    def get_alignment_strategy(self) -> AlignmentStrategy:
        """Get the alignment strategy for this adapter."""
        pass
    
    def detect_faces(self, image: Union[Image.Image, np.ndarray]) -> List[FaceDetection]:
        """
        Detect faces in an image.
        
        Args:
            image: Input image
            
        Returns:
            List of face detections
        """
        if not self.is_initialized:
            logger.error(f"Model not initialized for {self.__class__.__name__}")
            return []
        
        try:
            # Convert to appropriate format
            if isinstance(image, Image.Image):
                image_array = np.array(image)
            else:
                image_array = image
            
            # Ensure RGB format
            if len(image_array.shape) == 3 and image_array.shape[2] == 3:
                # Convert BGR to RGB if needed (OpenCV uses BGR)
                if self._is_bgr_format(image_array):
                    image_array = cv2.cvtColor(image_array, cv2.COLOR_BGR2RGB)
            
            # Perform detection
            detections = self._detect_faces_impl(image_array)
            
            logger.debug(f"Detected {len(detections)} faces")
            return detections
            
        except Exception as e:
            logger.error(f"Face detection failed: {e}")
            return []
    
    def extract_embedding(self, face_image: np.ndarray) -> Optional[FaceEmbedding]:
        """
        Extract face embedding from aligned face image.
        
        Args:
            face_image: Aligned face image
            
        Returns:
            Face embedding or None if extraction fails
        """
        if not self.is_initialized:
            logger.error(f"Model not initialized for {self.__class__.__name__}")
            return None
        
        try:
            # Ensure proper format and size
            if face_image.shape[:2] != (112, 112):
                face_image = cv2.resize(face_image, (112, 112))
            
            # Normalize if needed
            if face_image.dtype != np.float32:
                face_image = face_image.astype(np.float32) / 255.0
            
            # Extract embedding
            embedding = self._extract_embedding_impl(face_image)
            
            if embedding is not None:
                return FaceEmbedding(
                    embedding=embedding,
                    confidence=1.0,  # Default confidence
                    model_type=self.get_model_type()
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Embedding extraction failed: {e}")
            return None
    
    @abstractmethod
    def _detect_faces_impl(self, image: np.ndarray) -> List[FaceDetection]:
        """
        Concrete implementation of face detection.
        
        Args:
            image: Input image array
            
        Returns:
            List of face detections
        """
        pass
    
    @abstractmethod
    def _extract_embedding_impl(self, face_image: np.ndarray) -> Optional[np.ndarray]:
        """
        Concrete implementation of embedding extraction.
        
        Args:
            face_image: Aligned face image
            
        Returns:
            Face embedding array or None
        """
        pass
    
    def _is_bgr_format(self, image: np.ndarray) -> bool:
        """
        Heuristic to detect if image is in BGR format.
        
        Args:
            image: Input image
            
        Returns:
            True if likely BGR format
        """
        # Simple heuristic: check if blue channel has higher mean than red
        if len(image.shape) == 3 and image.shape[2] == 3:
            blue_mean = np.mean(image[:, :, 0])
            red_mean = np.mean(image[:, :, 2])
            return blue_mean > red_mean * 1.2
        return False
    
    def _preprocess_image(self, image: np.ndarray) -> torch.Tensor:
        """
        Preprocess image for model input.
        
        Args:
            image: Input image
            
        Returns:
            Preprocessed tensor
        """
        # Normalize to [0, 1] if needed
        if image.dtype != np.float32:
            image = image.astype(np.float32) / 255.0
        
        # Convert to tensor and add batch dimension
        tensor = torch.from_numpy(image).permute(2, 0, 1).unsqueeze(0)
        
        # Move to device
        tensor = tensor.to(self.device)
        
        return tensor
    
    def _postprocess_embedding(self, embedding: torch.Tensor) -> np.ndarray:
        """
        Postprocess embedding tensor to numpy array.
        
        Args:
            embedding: Embedding tensor
            
        Returns:
            Normalized embedding array
        """
        # Convert to numpy
        embedding_np = embedding.detach().cpu().numpy()
        
        # Normalize if needed
        if embedding_np.ndim > 1:
            embedding_np = embedding_np.flatten()
        
        # L2 normalize
        norm = np.linalg.norm(embedding_np)
        if norm > 0:
            embedding_np = embedding_np / norm
        
        return embedding_np
    
    def get_model_info(self) -> Dict[str, Any]:
        """
        Get model information.
        
        Returns:
            Dictionary with model information
        """
        return {
            'model_id': self.model_id,
            'model_type': self.get_model_type().value,
            'alignment_strategy': self.get_alignment_strategy().value,
            'device': self.device,
            'initialized': self.is_initialized
        }
