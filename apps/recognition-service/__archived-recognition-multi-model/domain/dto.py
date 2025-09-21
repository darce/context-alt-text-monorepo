"""
Data Transfer Objects (DTOs) for Recognition Service
Clean interface between services with proper serialization/deserialization
"""
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime
import json

from .entities import ModelType


@dataclass
class MatchResultDTO:
    """DTO for entity match result."""
    entity_name: str
    confidence: float
    embedding_distance: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MatchResultDTO':
        return cls(**data)


@dataclass
class FaceResultDTO:
    """DTO for single face recognition result."""
    bbox: List[float]  # [x1, y1, x2, y2]
    confidence: float  # Face detection confidence
    matches: List[MatchResultDTO]
    landmarks: Optional[List[List[float]]] = None
    quality_score: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['matches'] = [match.to_dict() for match in self.matches]
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FaceResultDTO':
        matches = [MatchResultDTO.from_dict(m) for m in data.get('matches', [])]
        return cls(
            bbox=data['bbox'],
            confidence=data['confidence'],
            matches=matches,
            landmarks=data.get('landmarks'),
            quality_score=data.get('quality_score')
        )


@dataclass
class SceneAnalysisDTO:
    """DTO for scene analysis result - clean interface for external consumers."""
    faces: List[FaceResultDTO]
    model_type: str  # String representation for JSON serialization
    threshold: float
    processing_time_ms: float
    timestamp: str
    
    @property
    def total_faces(self) -> int:
        """Get total number of faces detected."""
        return len(self.faces)
    
    @property
    def identified_faces(self) -> List[FaceResultDTO]:
        """Get faces with at least one match above threshold."""
        return [face for face in self.faces if any(m.confidence >= self.threshold for m in face.matches)]
    
    @property
    def identified_faces_count(self) -> int:
        """Get count of faces with at least one match above threshold."""
        return len(self.identified_faces)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'faces': [face.to_dict() for face in self.faces],
            'model_type': self.model_type,
            'threshold': self.threshold,
            'processing_time_ms': self.processing_time_ms,
            'timestamp': self.timestamp,
            'total_faces': self.total_faces,
            'identified_faces_count': self.identified_faces_count
        }
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SceneAnalysisDTO':
        """Create from dictionary."""
        faces = [FaceResultDTO.from_dict(f) for f in data.get('faces', [])]
        return cls(
            faces=faces,
            model_type=data['model_type'],
            threshold=data['threshold'],
            processing_time_ms=data['processing_time_ms'],
            timestamp=data['timestamp']
        )
    
    @classmethod
    def from_json(cls, json_str: str) -> 'SceneAnalysisDTO':
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))


# Conversion utilities
def scene_analysis_result_to_dto(result, model_type: ModelType, threshold: float) -> SceneAnalysisDTO:
    """Convert internal SceneAnalysisResult to DTO."""
    from .entities import RecognitionResult
    
    face_dtos = []
    
    # Handle both cases: result.faces (list) or result as RecognitionResult
    faces_list = getattr(result, 'faces', [result] if hasattr(result, 'detection') else [])
    
    for face in faces_list:
        # Check if it's a RecognitionResult with detection attribute
        if hasattr(face, 'detection') and hasattr(face, 'matches'):
            # Convert matches - only include matches that meet the threshold
            match_dtos = []
            if face.matches:
                for match in face.matches:
                    # Apply threshold filtering here since we have access to the threshold
                    if match.confidence >= threshold:
                        match_dto = MatchResultDTO(
                            entity_name=match.person_name,
                            confidence=match.confidence,
                            embedding_distance=getattr(match, 'distance', None)
                        )
                        match_dtos.append(match_dto)
            
            # Create face DTO using detection bbox
            detection = face.detection
            face_dto = FaceResultDTO(
                bbox=list(detection.bbox) if hasattr(detection, 'bbox') else [0, 0, 0, 0],
                confidence=getattr(detection, 'confidence', 1.0),
                matches=match_dtos,
                landmarks=getattr(detection, 'landmarks', None),
                quality_score=getattr(face, 'quality_score', None)
            )
            face_dtos.append(face_dto)
        # Legacy support: face with direct bbox attribute
        elif hasattr(face, 'bbox') and hasattr(face, 'matches'):
            # Convert matches
            match_dtos = []
            if face.matches:
                for match in face.matches:
                    if match.confidence >= threshold:
                        match_dto = MatchResultDTO(
                            entity_name=match.person_name,
                            confidence=match.confidence,
                            embedding_distance=getattr(match, 'distance', None)
                        )
                        match_dtos.append(match_dto)
            
            # Create face DTO
            face_dto = FaceResultDTO(
                bbox=face.bbox if isinstance(face.bbox, list) else list(face.bbox),
                confidence=getattr(face, 'detection_confidence', 1.0),
                matches=match_dtos,
                landmarks=getattr(face, 'landmarks', None),
                quality_score=getattr(face, 'quality_score', None)
            )
            face_dtos.append(face_dto)
    
    return SceneAnalysisDTO(
        faces=face_dtos,
        model_type=model_type.value if hasattr(model_type, 'value') else str(model_type),
        threshold=threshold,
        processing_time_ms=getattr(result, 'processing_time_ms', 0.0),
        timestamp=datetime.now().isoformat()
    )
