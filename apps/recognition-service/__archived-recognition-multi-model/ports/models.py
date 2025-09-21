"""
Recognition Service API Models
Pydantic models for request/response serialization.
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum

from ..domain import ModelType, SceneAnalysisResult, RecognitionResult, RecognitionMatch, FaceDetection


class ModelTypeAPI(str, Enum):
    """API model type enum."""
    ADAFACE_IR101 = "adaface_ir101"
    INSIGHTFACE_W600K = "insightface_w600k"
    ARCFACE_IR50 = "arcface_ir50"


class AnalyzeSceneRequest(BaseModel):
    """Request model for scene analysis."""
    model_type: ModelTypeAPI = Field(..., description="Model type to use")
    threshold: float = Field(..., description="Recognition threshold", ge=0.0, le=1.0)


class FaceDetectionAPI(BaseModel):
    """API model for face detection."""
    bbox: List[float] = Field(..., description="Bounding box [x, y, width, height]")
    confidence: float = Field(..., description="Detection confidence")
    landmarks: Optional[List[List[float]]] = Field(None, description="Face landmarks")


class RecognitionMatchAPI(BaseModel):
    """API model for recognition match."""
    person_name: str = Field(..., description="Identified person name")
    confidence: float = Field(..., description="Recognition confidence")
    distance: float = Field(..., description="Embedding distance")


class FaceResultAPI(BaseModel):
    """API model for face recognition result."""
    detection: FaceDetectionAPI = Field(..., description="Face detection result")
    embedding_available: bool = Field(..., description="Whether embedding was extracted")
    quality_score: Optional[float] = Field(None, description="Quality score (for AdaFace)")
    matches: List[RecognitionMatchAPI] = Field(..., description="Recognition matches")


class AnalyzeSceneResponse(BaseModel):
    """Response model for scene analysis."""
    faces: List[FaceResultAPI] = Field(..., description="Detected faces and matches")
    model_type: ModelTypeAPI = Field(..., description="Model type used")
    threshold: float = Field(..., description="Recognition threshold used")
    processing_time_ms: float = Field(..., description="Processing time in milliseconds")
    total_faces: int = Field(..., description="Total number of faces detected")
    identified_faces: int = Field(..., description="Number of faces with matches")
    
    @classmethod
    def from_domain_result(cls, result: SceneAnalysisResult) -> "AnalyzeSceneResponse":
        """
        Convert domain result to API response.
        
        Args:
            result: Domain scene analysis result
            
        Returns:
            API response model
        """
        faces = []
        for face_result in result.faces:
            # Convert detection
            detection = FaceDetectionAPI(
                bbox=face_result.detection.bbox,
                confidence=face_result.detection.confidence,
                landmarks=face_result.detection.landmarks
            )
            
            # Convert matches
            matches = []
            for match in face_result.matches:
                matches.append(RecognitionMatchAPI(
                    person_name=match.person_name,
                    confidence=match.confidence,
                    distance=match.distance
                ))
            
            # Create face result
            face_api = FaceResultAPI(
                detection=detection,
                embedding_available=face_result.embedding is not None,
                quality_score=face_result.embedding.quality_score if face_result.embedding else None,
                matches=matches
            )
            faces.append(face_api)
        
        return cls(
            faces=faces,
            model_type=ModelTypeAPI(result.model_type.value),
            threshold=result.threshold,
            processing_time_ms=result.processing_time_ms,
            total_faces=result.total_faces,
            identified_faces=result.identified_faces
        )


class ErrorResponse(BaseModel):
    """API error response."""
    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Error details")
    
    
class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(..., description="Service status")
    service: str = Field(..., description="Service name")
    version: str = Field(..., description="Service version")


class ModelInfo(BaseModel):
    """Model information."""
    name: str = Field(..., description="Model name")
    description: str = Field(..., description="Model description")
    hf_repo: str = Field(..., description="HuggingFace repository")
    alignment: str = Field(..., description="Alignment strategy")
    quality_aware: bool = Field(..., description="Whether model supports quality-aware matching")


class ModelsResponse(BaseModel):
    """Models list response."""
    models: List[ModelInfo] = Field(..., description="Available models")
