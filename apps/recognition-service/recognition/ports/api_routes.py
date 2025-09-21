"""
Recognition API Routes

FastAPI routes for the InsightFace-only recognition service.
Maintains compatibility with existing API contracts.
"""

import logging
from typing import Optional, List
from fastapi import APIRouter, File, UploadFile, Form, HTTPException, Depends
from PIL import Image
import io

from recognition.services import RecognitionService
from recognition.utils.conversion import convert_to_analysis_format

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v0", tags=["recognition"])

# Global service instance (will be initialized on first use)
_recognition_service: Optional[RecognitionService] = None


def get_recognition_service() -> RecognitionService:
    """Dependency to get the recognition service instance."""
    global _recognition_service
    if _recognition_service is None:
        _recognition_service = RecognitionService()
    return _recognition_service


async def _read_pil_image(file: UploadFile) -> Image.Image:
    """Convert uploaded file to PIL Image."""
    try:
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))
        
        # Convert to RGB if needed
        if image.mode != 'RGB':
            image = image.convert('RGB')
            
        return image
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image file: {e}")


@router.post("/analyze-scene")
async def analyze_scene(
    images: List[UploadFile] = File(...),
    use_roster: bool = Form(True),
    threshold: Optional[float] = Form(None),
    model: Optional[str] = Form(None),
    service: RecognitionService = Depends(get_recognition_service)
):
    """
    Analyze scene(s) to detect faces and identify persons against the roster.
    
    This endpoint maintains compatibility with the existing API contract
    while using the simplified InsightFace-only pipeline.
    
    Args:
        images: List of image files to analyze
        use_roster: Whether to use roster for identification (always True for this service)
        threshold: Optional recognition threshold (overrides config default)
        model: Optional model name (ignored - always uses InsightFace)
    """
    if model and model != "insightface":
        logger.warning(f"⚠️ Model '{model}' requested but only InsightFace is supported")
    
    try:
        results = []
        
        for i, image_file in enumerate(images):
            filename = getattr(image_file, 'filename', f'image_{i}') or f'unnamed_image_{i}'
            logger.info(f"📸 Processing image: {filename}")
            
            # Convert to PIL Image (this can raise HTTPException with 400)
            try:
                pil_image = await _read_pil_image(image_file)
            except HTTPException:
                # Re-raise HTTPException as-is (maintains 400 status code)
                raise
            
            # Run recognition
            recognition_result = await service.recognize_faces(pil_image, threshold)
            
            # Convert to analysis service format for compatibility
            analysis_result = convert_to_analysis_format(
                recognition_result, 
                use_roster=use_roster
            )
            
            results.append(analysis_result)
            
            logger.info(
                f"✅ Processed {filename}: {len(recognition_result.face_detections)} faces, "
                f"{len(recognition_result.matches)} matches"
            )
        
        return {
            "results": results,
            "total_images_processed": len(images),
            "roster_identification_enabled": use_roster,
            "configuration_used": {
                "threshold": threshold,
                "model": "insightface"
            }
        }
        
    except HTTPException:
        # Re-raise HTTPException as-is (preserves status code)
        raise
    except Exception as e:
        logger.error(f"❌ Error in analyze-scene: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-scene/{threshold}")
async def analyze_scene_with_threshold(
    threshold: float,
    images: List[UploadFile] = File(...),
    use_roster: bool = Form(True),
    model: Optional[str] = Form(None),
    service: RecognitionService = Depends(get_recognition_service)
):
    """
    Analyze scene with threshold as path parameter.
    Alternative endpoint format for backward compatibility.
    """
    return await analyze_scene(
        images=images,
        use_roster=use_roster,
        threshold=threshold,
        model=model,
        service=service
    )


@router.get("/service/info")
async def get_service_info(
    service: RecognitionService = Depends(get_recognition_service)
):
    """Get information about the recognition service."""
    try:
        info = await service.get_service_info()
        return {
            "status": "success",
            "data": info
        }
    except Exception as e:
        logger.error(f"❌ Error getting service info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/service/reload-embeddings")
async def reload_embeddings(
    service: RecognitionService = Depends(get_recognition_service)
):
    """Force reload embeddings from file."""
    try:
        success = await service.reload_embeddings()
        if success:
            info = await service.get_service_info()
            return {
                "status": "success",
                "message": "Embeddings reloaded successfully",
                "data": {
                    "loaded_embeddings": info["loaded_embeddings"],
                    "entity_names": info["entity_names"]
                }
            }
        else:
            return {
                "status": "failed",
                "message": "Failed to reload embeddings"
            }
    except Exception as e:
        logger.error(f"❌ Error reloading embeddings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check(
    service: RecognitionService = Depends(get_recognition_service)
):
    """Health check for the recognition service."""
    try:
        info = await service.get_service_info()
        is_healthy = info["loaded_embeddings"] > 0
        
        return {
            "status": "healthy" if is_healthy else "warning",
            "model": info["model"],
            "loaded_embeddings": info["loaded_embeddings"],
            "message": "Service operational" if is_healthy else "No embeddings loaded"
        }
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        return {
            "status": "unhealthy",
            "message": f"Health check failed: {str(e)}"
        }
