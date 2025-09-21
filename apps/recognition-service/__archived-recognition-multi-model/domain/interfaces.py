"""
Recognition Service Domain Interfaces
Core business interfaces following hexagonal architecture.
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Union
import numpy as np
from PIL import Image

from .entities import (
    FaceDetection, FaceEmbedding, RecognitionMatch, 
    RecognitionResult, SceneAnalysisResult, ModelType, AlignmentStrategy
)


class FaceAligner(ABC):
    """Abstract face alignment interface."""
    
    @abstractmethod
    def align_face(self, image: Union[Image.Image, np.ndarray], 
                  detection: FaceDetection) -> Optional[np.ndarray]:
        """
        Align a detected face for recognition.
        
        Args:
            image: Input image containing the face
            detection: Face detection result with bbox and landmarks
            
        Returns:
            Aligned face image as numpy array, or None if alignment fails
        """
        pass


class QualityScorer(ABC):
    """Abstract quality scoring interface."""
    
    @abstractmethod
    def calculate_quality(self, face_image: np.ndarray, 
                         embedding: Optional[np.ndarray] = None) -> float:
        """
        Calculate quality score for a face image.
        
        Args:
            face_image: Aligned face image
            embedding: Optional face embedding for quality-aware scoring
            
        Returns:
            Quality score between 0.0 and 1.0
        """
        pass


class EmbeddingRouter(ABC):
    """Abstract embedding routing interface."""
    
    @abstractmethod
    def get_embeddings(self, model_type: ModelType) -> Dict[str, np.ndarray]:
        """
        Get embeddings for a specific model type.
        
        Args:
            model_type: Type of model requesting embeddings
            
        Returns:
            Dictionary mapping person names to embeddings
        """
        pass
    
    @abstractmethod
    def reload_embeddings(self, model_type: ModelType) -> bool:
        """
        Reload embeddings from storage for a model type.
        
        Args:
            model_type: Type of model to reload embeddings for
            
        Returns:
            True if reload successful, False otherwise
        """
        pass


class CVLFaceAdapter(ABC):
    """Abstract CVLFace adapter interface."""
    
    @abstractmethod
    def detect_faces(self, image: Union[Image.Image, np.ndarray]) -> List[FaceDetection]:
        """
        Detect faces in an image.
        
        Args:
            image: Input image
            
        Returns:
            List of face detections
        """
        pass
    
    @abstractmethod
    def extract_embedding(self, face_image: np.ndarray) -> Optional[FaceEmbedding]:
        """
        Extract face embedding from aligned face image.
        
        Args:
            face_image: Aligned face image
            
        Returns:
            Face embedding or None if extraction fails
        """
        pass
    
    @abstractmethod
    def get_model_type(self) -> ModelType:
        """Get the model type for this adapter."""
        pass
    
    @abstractmethod
    def get_alignment_strategy(self) -> AlignmentStrategy:
        """Get the alignment strategy for this adapter."""
        pass


class RecognitionPort(ABC):
    """Recognition service port interface."""
    
    @abstractmethod
    async def analyze_scene(self, image: Union[Image.Image, np.ndarray],
                           model_type: ModelType, threshold: float) -> SceneAnalysisResult:
        """
        Analyze a scene for face recognition.
        
        Args:
            image: Input image to analyze
            model_type: Model type to use for recognition
            threshold: Recognition threshold
            
        Returns:
            Complete scene analysis result
        """
        pass
