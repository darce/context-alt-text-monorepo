"""
Recognition Service Domain Entities
Core business entities for face recognition operations.
"""
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Union
from enum import Enum
import numpy as np


class ModelType(str, Enum):
    """Supported face recognition model types."""
    ADAFACE_IR101 = "adaface_ir101"
    INSIGHTFACE_W600K = "insightface_w600k"
    ARCFACE_IR101 = "arcface_ir101"


class AlignmentStrategy(str, Enum):
    """Face alignment strategies."""
    MTCNN = "mtcnn"
    BUILT_IN = "built_in"


@dataclass
class FaceDetection:
    """Face detection result."""
    bbox: List[float]  # [x, y, width, height]
    confidence: float
    landmarks: Optional[List[List[float]]] = None  # [[x1, y1], [x2, y2], ...]
    
    
@dataclass
class FaceEmbedding:
    """Face embedding with metadata."""
    embedding: np.ndarray
    confidence: float
    quality_score: Optional[float] = None
    model_type: Optional[ModelType] = None
    

@dataclass
class RecognitionMatch:
    """Face recognition match result."""
    person_name: str
    confidence: float
    distance: float
    embedding: Optional[FaceEmbedding] = None
    meets_threshold: bool = False  # Whether this match meets the threshold
    effective_threshold: Optional[float] = None  # The threshold used for evaluation
    

@dataclass
class RecognitionResult:
    """Complete recognition result for a single face."""
    detection: FaceDetection
    embedding: Optional[FaceEmbedding] = None
    matches: List[RecognitionMatch] = None
    
    def __post_init__(self):
        if self.matches is None:
            self.matches = []


@dataclass
class SceneAnalysisResult:
    """Analysis result for an entire scene/image."""
    faces: List[RecognitionResult]
    model_type: ModelType
    threshold: float
    processing_time_ms: float
    
    @property
    def total_faces(self) -> int:
        """Get total number of faces detected."""
        return len(self.faces)
    
    @property
    def identified_faces(self) -> int:
        """Get number of faces with at least one match."""
        return sum(1 for face in self.faces if face.matches)
