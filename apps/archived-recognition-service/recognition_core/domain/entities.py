"""
Recognition Domain Entities

Simplified domain entities for the InsightFace-only recognition service.
No quality scoring, occlusion handling, or multi-model complexity.
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any
import numpy as np


@dataclass
class FaceDetection:
    """Represents a detected face with bounding box and landmarks."""
    bbox: Tuple[int, int, int, int]  # (x_min, y_min, x_max, y_max)
    confidence: float
    landmarks: Optional[np.ndarray] = None  # 5-point landmarks
    
    def area(self) -> float:
        """Calculate the area of the bounding box."""
        x_min, y_min, x_max, y_max = self.bbox
        return max(0, x_max - x_min) * max(0, y_max - y_min)


@dataclass
class FaceEmbedding:
    """Represents a face embedding vector."""
    embedding: np.ndarray
    detection: FaceDetection
    
    def to_list(self) -> List[float]:
        """Convert embedding to list for serialization."""
        return self.embedding.tolist()


@dataclass
class EmbeddingEntry:
    """Represents a roster entry with embeddings for matching."""
    unique_id: str
    name: str
    display_name: str
    aggregate_embedding: np.ndarray
    metadata: Dict[str, Any]
    
    def cosine_similarity(self, query_embedding: np.ndarray) -> float:
        """Calculate cosine similarity with query embedding."""
        # Normalize vectors
        norm_aggregate = self.aggregate_embedding / np.linalg.norm(self.aggregate_embedding)
        norm_query = query_embedding / np.linalg.norm(query_embedding)
        
        # Compute cosine similarity
        return float(np.dot(norm_aggregate, norm_query))


@dataclass
class MatchResult:
    """Represents a matching result between query and roster entry."""
    entry: EmbeddingEntry
    similarity: float
    threshold: float
    is_match: bool
    
    @property
    def confidence_percentage(self) -> float:
        """Get confidence as percentage."""
        return self.similarity * 100


@dataclass
class RecognitionResult:
    """Complete recognition result for a single image."""
    face_detections: List[FaceDetection]
    face_embeddings: List[FaceEmbedding]
    matches: List[MatchResult]
    processing_time_ms: float
    face_matches: List[List[MatchResult]] = field(default_factory=list)

    def get_best_matches(self) -> List[MatchResult]:
        """Get matches that exceed threshold, sorted by similarity."""
        valid_matches = [match for match in self.matches if match.is_match]
        return sorted(valid_matches, key=lambda x: x.similarity, reverse=True)
