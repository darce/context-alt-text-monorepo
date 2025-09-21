"""
Recognition Domain Interfaces

Port interfaces for the hexagonal architecture.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from PIL import Image
import numpy as np

from .entities import FaceDetection, FaceEmbedding, EmbeddingEntry, RecognitionResult


class FaceDetectorPort(ABC):
    """Port for face detection operations."""
    
    @abstractmethod
    async def detect_faces(self, image: Image.Image) -> List[FaceDetection]:
        """Detect faces in an image."""
        pass


class FaceEmbedderPort(ABC):
    """Port for face embedding extraction."""
    
    @abstractmethod
    async def extract_embeddings(
        self, 
        image: Image.Image, 
        detections: List[FaceDetection]
    ) -> List[FaceEmbedding]:
        """Extract embeddings for detected faces."""
        pass


class EmbeddingRouterPort(ABC):
    """Port for embedding routing and matching."""
    
    @abstractmethod
    async def load_embeddings(self) -> List[EmbeddingEntry]:
        """Load embeddings from storage."""
        pass
    
    @abstractmethod
    async def find_matches(
        self, 
        query_embedding: np.ndarray, 
        threshold: float
    ) -> List[EmbeddingEntry]:
        """Find matching embeddings above threshold."""
        pass
    
    @abstractmethod
    async def reload_if_needed(self) -> bool:
        """Check if embeddings need reloading and reload if necessary."""
        pass


class RecognitionModelPort(ABC):
    """Port for concrete recognition model implementations (InsightFace, etc.)."""

    @abstractmethod
    async def analyze(self, image: Image.Image) -> List[FaceEmbedding]:
        """Run detection + embedding extraction for the given image."""
        pass

    @abstractmethod
    def model_info(self) -> Dict[str, Any]:
        """Return metadata about the underlying model (name, device, version)."""
        pass


class RecognitionServicePort(ABC):
    """Main recognition service port."""
    
    @abstractmethod
    async def recognize_faces(
        self, 
        image: Image.Image, 
        threshold: Optional[float] = None
    ) -> RecognitionResult:
        """Perform complete face recognition pipeline."""
        pass


# Alias for backward compatibility
RecognitionPort = RecognitionServicePort
