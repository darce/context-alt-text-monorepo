"""
Recognition Service API Router
FastAPI endpoints for face recognition service.
"""
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, UploadFile, File, Path, Query, Depends
from fastapi.responses import JSONResponse
from PIL import Image
import io
import numpy as np

from ..domain import ModelType, RecognitionPort, SceneAnalysisResult
from .models import AnalyzeSceneRequest, AnalyzeSceneResponse
from .dependencies import get_recognition_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v0", tags=["recognition"])


@router.post("/analyze-scene/{model}-{threshold}")
async def analyze_scene(
    model: str = Path(..., description="Model type: adaface_ir101, insightface_w600k, or arcface_ir50"),
    threshold: float = Path(..., description="Recognition threshold", ge=0.0, le=1.0),
    file: UploadFile = File(..., description="Image file to analyze"),
    override_threshold: Optional[float] = Query(None, description="Override default threshold", ge=0.0, le=1.0),
    recognition_service: RecognitionPort = Depends(get_recognition_service)
) -> AnalyzeSceneResponse:
    """
    Analyze a scene for face recognition.
    
    Args:
        model: Model type to use (adaface_ir101, insightface_w600k, arcface_ir50)
        threshold: Default recognition threshold from path
        file: Image file to analyze
        override_threshold: Optional threshold override via query parameter
        recognition_service: Injected recognition service
        
    Returns:
        Scene analysis result with detected faces and matches
    """
    try:
        # Validate model type
        try:
            model_type = ModelType(model)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid model type: {model}. Must be one of: {', '.join([m.value for m in ModelType])}"
            )
        
        # Use override threshold if provided
        effective_threshold = override_threshold if override_threshold is not None else threshold
        
        # Validate file type
        if file.content_type and not file.content_type.startswith('image/'):
            raise HTTPException(
                status_code=400,
                detail="File must be an image"
            )
        
        # Read and process image
        image_data = await file.read()
        image = Image.open(io.BytesIO(image_data))
        
        # Convert to RGB if needed
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        logger.info(f"Processing image with {model_type} model, threshold={effective_threshold}")
        
        # Analyze scene
        result = await recognition_service.analyze_scene(
            image=image,
            model_type=model_type,
            threshold=effective_threshold
        )
        
        # Convert to response model
        response = AnalyzeSceneResponse.from_domain_result(result)
        
        logger.info(f"Analysis complete: {result.total_faces} faces, {result.identified_faces} identified")
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error analyzing scene: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    Health check endpoint.
    
    Returns:
        Service health status
    """
    return {
        "status": "healthy",
        "service": "recognition-service",
        "version": "1.0.0"
    }


@router.get("/models")
async def list_models() -> Dict[str, Any]:
    """
    List available models.
    
    Returns:
        Available models and their configurations
    """
    return {
        "models": [
            {
                "name": ModelType.ADAFACE_IR101.value,
                "description": "AdaFace IR101 WebFace12M - Quality-adaptive margin",
                "hf_repo": "minchul/cvlface_adaface_ir101_webface12m",
                "alignment": "mtcnn",
                "quality_aware": True
            },
            {
                "name": ModelType.INSIGHTFACE_W600K.value,
                "description": "InsightFace SCRFD ArcFace W600K - Built-in alignment",
                "hf_repo": "deepinsight/insightface-scrfd-arcface-w600k",
                "alignment": "built_in",
                "quality_aware": False
            },
            {
                "name": ModelType.ARCFACE_IR50.value,
                "description": "ArcFace IR50 WebFace4M - MTCNN alignment",
                "hf_repo": "minchul/cvlface_arcface_ir50_webface4m",
                "alignment": "mtcnn",
                "quality_aware": False
            }
        ]
    }
