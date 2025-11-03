import io
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends, Request
from PIL import Image
from analysis.workflow.scene_composer import SceneComposer
from analysis.services.scene_analysis_service import SceneAnalysisService
from .roster import router as roster_router
from .suggest import router as suggest_router
from .cluster_unknowns import router as cluster_router
from api.dependencies import (
    get_recognition_service,
    get_roster_service,
    set_recognition_service,
)
from api.schemas import AnalyzeSceneRequest, EmbeddingsRequest
from shared.config import get_config
from shared.utils.device_utils import get_available_device  # for device resolution if needed
from shared.metrics import update_roster_metrics, update_faiss_metrics, get_metrics_handler

router = APIRouter()
router.include_router(roster_router)
router.include_router(suggest_router)
router.include_router(cluster_router)

# Dependency to get scene composer - will be set by the main app
_scene_composer: Optional[SceneComposer] = None
_scene_analysis_service: Optional[SceneAnalysisService] = None

_media_config = get_config().get("media_storage", {}).get("config", {})
_max_caption_size_mb = int(_media_config.get("max_file_size_mb", 10))
_max_caption_size_bytes = _max_caption_size_mb * 1024 * 1024

try:  # numpy is present in the service environment but guard to keep import safe for tests.
    import numpy as _np  # type: ignore
except Exception:  # pragma: no cover - numpy always available in prod image but tests may stub
    _np = None


def _to_serializable(value: Any) -> Any:
    """Recursively convert numpy/scalar rich objects into JSON-safe primitives."""
    if _np is not None:
        if isinstance(value, (_np.integer,)):
            return int(value)
        if isinstance(value, (_np.floating,)):
            return float(value)
        if isinstance(value, _np.ndarray):
            return [_to_serializable(item) for item in value.tolist()]

    if isinstance(value, dict):
        return {key: _to_serializable(sub_value) for key, sub_value in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_to_serializable(item) for item in value]

    if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
        return _to_serializable(value.to_dict())

    if hasattr(value, "__dict__"):
        return _to_serializable(vars(value))

    return value


async def _read_pil_image(file: Optional[UploadFile]) -> Optional[Image.Image]:
    """Load an uploaded file into a RGB PIL image."""
    if file is None:
        return None

    data = await file.read()
    image = Image.open(io.BytesIO(data))
    return image.convert("RGB")


def _validate_upload_size(upload: Optional[UploadFile], field: str) -> None:
    """Ensure an uploaded file does not exceed the configured size budget."""
    if upload is None:
        return

    if upload.file is None:
        return

    upload.file.seek(0, os.SEEK_END)
    size = upload.file.tell()
    upload.file.seek(0)

    if size > _max_caption_size_bytes:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "caption_payload_too_large",
                "field": field,
                "max_mb": _max_caption_size_mb,
            },
        )

def get_scene_composer(request: Request) -> SceneComposer:
    if not getattr(request.app.state, "initialization_complete", False):
        if getattr(request.app.state, "is_initializing", True):
            raise HTTPException(
                status_code=503, 
                detail="Models are still loading. Please try again in a few moments."
            )
        else:
            raise HTTPException(
                status_code=503, 
                detail="Scene composer not initialized"
            )
    return _scene_composer

def set_scene_composer(scene_composer: SceneComposer):
    global _scene_composer
    _scene_composer = scene_composer

def get_scene_analysis_service(request: Request) -> SceneAnalysisService:
    if not getattr(request.app.state, "initialization_complete", False):
        if getattr(request.app.state, "is_initializing", True):
            raise HTTPException(
                status_code=503, 
                detail="Models are still loading. Please try again in a few moments."
            )
        else:
            raise HTTPException(
                status_code=503, 
                detail="Scene analysis service not initialized"
            )
    return _scene_analysis_service

def set_scene_analysis_service(scene_analysis_service: SceneAnalysisService):
    global _scene_analysis_service
    _scene_analysis_service = scene_analysis_service
    if scene_analysis_service and getattr(scene_analysis_service, "recognition_service", None):
        set_recognition_service(scene_analysis_service.recognition_service)

@router.post("/caption")
async def caption(
    image: UploadFile = File(...),
    reference_image: Optional[UploadFile] = File(None),
    caption: str = Form(""),
    post_body: str = Form(""),
    scene_analysis_service: SceneAnalysisService = Depends(get_scene_analysis_service),
):
    try:
        _validate_upload_size(image, "image")
        _validate_upload_size(reference_image, "reference_image")
        main_image = await _read_pil_image(image)
        ref_image = await _read_pil_image(reference_image)
        result = scene_analysis_service.generate_caption(
            image=main_image,
            reference_image=ref_image,
            context={"caption": caption, "post_body": post_body}
        )
        return {
            "caption": result.get("caption", ""),
            "detected_persons": result.get("detected_persons", []),
            "processing_info": result.get("processing_info", {})
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error generating caption: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/identify")
async def identify(
    request: Request,
    image: UploadFile = File(...),
    reference_image: UploadFile = File(...),
):
    try:
        _validate_upload_size(image, "image")
        _validate_upload_size(reference_image, "reference_image")
        main_image = await _read_pil_image(image)
        ref_image = await _read_pil_image(reference_image)
        scene_composer = get_scene_composer(request)
        results = scene_composer.identify_persons_with_reference(main_image, ref_image)
        return {"results": results}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error in /identify endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/analyze-scene")
async def analyze_scene(
    request_body: AnalyzeSceneRequest,
    scene_analysis_service: SceneAnalysisService = Depends(get_scene_analysis_service),
):
    """Analyze one or more images described by the request payload."""
    try:
        threshold = request_body.threshold
        use_roster = request_body.use_roster

        logging.info("📸 [SCENE] Starting analysis with %s images", len(request_body.images))
        if threshold is not None:
            logging.info("🎯 [SCENE] Using custom threshold: %s", threshold)

        results = []
        for idx, image_item in enumerate(request_body.images):
            filename = image_item.filename or f"image_{idx}"
            logging.info("📸 [SCENE] Processing image payload: %s", filename)

            try:
                pil_image = image_item.load_image()
            except NotImplementedError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Invalid image payload: {exc}") from exc

            # Generate a descriptive caption and measure processing time
            cap_result = scene_analysis_service.generate_caption(image=pil_image)
            description = cap_result.get("caption", "")
            proc_time = cap_result.get("processing_info", {}).get("processing_time", None)

            # Perform scene analysis with dynamic model/threshold parameters
            scene_context = await scene_analysis_service.analyze_scene(
                pil_image,
                threshold_override=threshold,
            )

            # Convert to serializable format
            # Build initial result with detected objects/entities
            detected_entity_dicts = [_to_serializable(entity) for entity in scene_context.detected_entities]
            result = {
                "scene_description": description,
                "processing_time": proc_time,
                "detected_objects": [_to_serializable(obj) for obj in scene_context.detected_objects],
                "detected_entities": detected_entity_dicts,
                # Parallel array of roster match details (None if no match)
                "roster_matches": [
                    _to_serializable(entity.roster_match) if entity.roster_match else None
                    for entity in scene_context.detected_entities
                ],
                "identified_roster_entities": [],
                "processing_metadata": _to_serializable(scene_context.processing_metadata or {}),
            }
            
            # Include detailed identified roster entities if any
            if scene_context.identified_roster_entities:
                # Return matched roster entries directly for client compatibility
                result["identified_roster_entities"] = [
                    _to_serializable(entity.roster_match.roster_entry)
                    for entity in scene_context.identified_roster_entities
                ]
            
            # Log completion of this image processing
            num_objects = len(scene_context.detected_objects)
            num_entities = len(scene_context.detected_entities)
            num_matches = len(scene_context.identified_roster_entities or [])
            logging.info(
                "✅ [SCENE] Completed processing %s: %s objects, %s entities, %s roster matches",
                filename,
                num_objects,
                num_entities,
                num_matches,
            )

            results.append(result)
            
        response_data = {
            "results": results,
            "total_images_processed": len(request_body.images),
            "roster_identification_enabled": use_roster
        }

        if threshold is not None:
            response_data["configuration_used"] = {"threshold": threshold}

        return _to_serializable(response_data)

    except Exception as e:
        logging.error(f"Error in /analyze-scene endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/embeddings")
async def generate_embeddings(
    request_body: EmbeddingsRequest,
    scene_analysis_service: SceneAnalysisService = Depends(get_scene_analysis_service),
):
    """Generate face embeddings for a single image."""
    try:
        try:
            pil_image = request_body.image.load_image()
        except NotImplementedError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid image payload: {exc}") from exc

        recognition_service = scene_analysis_service.recognition_service
        threshold = request_body.threshold

        recognition_result = await recognition_service.recognize_faces(
            image=pil_image,
            threshold=threshold,
        )

        response_faces = []
        matches_per_face = recognition_result.face_matches or []

        for idx, face_embedding in enumerate(recognition_result.face_embeddings):
            detection = face_embedding.detection
            embedding_vector = [float(value) for value in face_embedding.embedding.tolist()]
            candidate_matches = matches_per_face[idx] if idx < len(matches_per_face) else []

            response_faces.append(
                {
                    "bbox": [float(value) for value in detection.bbox],
                    "confidence": float(detection.confidence),
                    "embedding": embedding_vector,
                    "matches": [
                        {
                            "name": match.entry.name,
                            "unique_id": match.entry.unique_id,
                            "similarity": float(match.similarity),
                            "meets_threshold": bool(match.is_match),
                            "metadata": _to_serializable(match.entry.metadata or {}),
                        }
                        for match in candidate_matches
                    ],
                }
            )

        return _to_serializable({
            "faces": response_faces,
            "processing_time_ms": recognition_result.processing_time_ms,
            "threshold": threshold or recognition_service.settings.recognition.default_threshold,
        })

    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        logging.error("Error in /embeddings endpoint: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/service/reload-embeddings")
async def reload_embeddings_route(
    scene_analysis_service: SceneAnalysisService = Depends(get_scene_analysis_service),
):
    """Force a manual embedding reload for diagnostics."""
    recognition_service = scene_analysis_service.recognition_service
    result = await recognition_service.reload_embeddings()

    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result)
    return result


@router.get("/service/info")
async def service_info(
    scene_analysis_service: SceneAnalysisService = Depends(get_scene_analysis_service),
    roster_service = Depends(get_roster_service),
):
    """
    Expose model metadata, roster stats, and FAISS index stats for diagnostics.
    
    This endpoint provides comprehensive service health and observability data including:
    - Model configuration (device, providers, thresholds)
    - Roster statistics (entry count, embedding counts by type)
    - Progressive learning metrics (confirmations, quality distribution)
    - FAISS index statistics (vector count, last reload time)
    - Performance settings and cache configuration
    
    Used by WordPress dashboard to display system health and progressive learning status.
    """
    recognition_service = scene_analysis_service.recognition_service
    info = await recognition_service.get_service_info()
    
    # Add roster statistics from storage
    try:
        storage_info = roster_service.get_storage_info(model="insightface_w600k")
        roster_stats = storage_info.get("roster_stats", {})
        
        # Include etag and last_updated if available from roster cache
        roster_metadata = {}
        if hasattr(roster_service, "_etag_cache"):
            roster_metadata["etag"] = roster_service._etag_cache.get("etag")
            roster_metadata["last_updated"] = roster_service._etag_cache.get("timestamp")
        
        info["roster_stats"] = {
            **roster_stats,
            **roster_metadata
        }
        
        # Update Prometheus metrics
        update_roster_metrics(roster_stats, model="insightface_w600k")
        
    except Exception as exc:  # pragma: no cover - defensive
        logging.error(f"Failed to fetch roster stats: {exc}")
        info["roster_stats"] = {
            "entry_count": 0,
            "reference_embeddings": 0,
            "augmented_embeddings": 0,
            "total_embeddings": 0,
            "error": str(exc)
        }
    
        # Add progressive learning statistics
    try:
        # Check if storage adapter exists and has the method
        # RosterService uses 'roster_storage' attribute
        storage_adapter = getattr(roster_service, 'roster_storage', None) or getattr(roster_service, 'storage', None)
        
        if storage_adapter and hasattr(storage_adapter, 'get_progressive_learning_stats'):
            pl_stats = storage_adapter.get_progressive_learning_stats()
            
            info["progressive_learning"] = {
                "enabled": True,
                "confirmations_last_24h": pl_stats["confirmations_24h"],
                "avg_augmentations_per_entry": pl_stats["avg_augmentations"],
                "quality_distribution": {
                    "high": pl_stats["quality_high_pct"],
                    "medium": pl_stats["quality_medium_pct"],
                    "low": pl_stats["quality_low_pct"],
                },
                "aggregate_refresh_status": {
                    "last_full_refresh": pl_stats["last_full_refresh"],
                    "refresh_in_progress": pl_stats["refresh_in_progress"],
                    "pending_updates": pl_stats["pending_refresh_count"],
                }
            }
            
            # Include pgvector version in database info
            if "database" not in info:
                info["database"] = {}
            info["database"]["type"] = "postgresql"
            info["database"]["pgvector_version"] = pl_stats["pgvector_version"]
            
            # Update roster stats with progressive learning data
            info["roster_stats"]["total_entries"] = pl_stats["total_entries"]
            info["roster_stats"]["entries_with_augmentations"] = pl_stats["augmented_entries"]
            info["roster_stats"]["total_reference_embeddings"] = pl_stats["total_reference"]
            info["roster_stats"]["total_augmented_embeddings"] = pl_stats["total_augmented"]
            info["roster_stats"]["last_aggregate_refresh"] = pl_stats["last_mv_refresh"]
        else:
            info["progressive_learning"] = {"enabled": False, "message": "PostgreSQL storage adapter not available"}
            
    except Exception as exc:  # pragma: no cover - defensive
        logging.error(f"Failed to fetch progressive learning stats: {exc}")
        info["progressive_learning"] = {
            "enabled": False,
            "error": str(exc)
        }
    
    # Add FAISS index statistics from embedding router
    try:
        embedding_router_info = info.get("embedding_router", {})
        faiss_stats = {
            "total_vectors": embedding_router_info.get("loaded_embeddings", 0),
            "dimension": 512,  # From recognition settings
            "index_type": "Flat",  # Current implementation uses Flat index
        }
        
        # Include reload stats if available
        reload_stats = embedding_router_info.get("reload_stats", {})
        if reload_stats:
            faiss_stats["last_reload"] = reload_stats.get("reloaded_at")
            faiss_stats["last_reload_duration_ms"] = reload_stats.get("duration_ms")
        
        info["faiss_index_stats"] = faiss_stats
        
        # Update Prometheus metrics
        update_faiss_metrics(faiss_stats)
        
    except Exception as exc:  # pragma: no cover - defensive
        logging.error(f"Failed to build FAISS stats: {exc}")
        info["faiss_index_stats"] = {
            "total_vectors": 0,
            "dimension": 512,
            "index_type": "unknown",
            "error": str(exc)
        }
    
    return {"status": "ok", "data": info}


@router.get("/health")
async def health(
    scene_analysis_service: SceneAnalysisService = Depends(get_scene_analysis_service),
):
    """Simple readiness check used by deployment targets."""
    # If the dependency resolved, we consider the service healthy.
    _ = scene_analysis_service
    return {"status": "ok"}


@router.get("/metrics")
def metrics():
    """
    Prometheus metrics endpoint.
    
    Exposes application metrics in Prometheus format for scraping and monitoring.
    
    **Metrics Included:**
    - `augmented_embedding_requests_total`: Counter for augmentation requests (labeled by status, quality_tier)
    - `augmented_embedding_duration_seconds`: Histogram of augmentation operation latencies
    - `roster_entries_total`: Gauge of total roster entries
    - `roster_embeddings_by_type`: Gauge of embeddings by type (reference, augmented)
    - `faiss_index_vectors_total`: Gauge of total vectors in FAISS index
    
    **Usage:**
    Configure Prometheus to scrape this endpoint:
    ```yaml
    scrape_configs:
      - job_name: 'recognition-service'
        static_configs:
          - targets: ['recognition-service:7860']
        metrics_path: '/api/v0/metrics'
    ```
    
    **Returns:**
    - Prometheus text exposition format
    - Content-Type: text/plain; version=0.0.4
    """
    metrics_handler = get_metrics_handler()
    return metrics_handler()


@router.post("/identify-hf")  # Alias for ONNX AdaFace identification
async def identify_hf(
    image: UploadFile = File(...),
    roster_service=Depends(get_roster_service)
):
    """
    Identify faces using face recognition pipeline.
    Returns face identification results.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        logger.info("🔍 [IDENTIFY-HF] Starting AdaFace HF identification request")
        
        # Read image
        logger.info("📖 [IDENTIFY-HF] Reading uploaded image...")
        img = await _read_pil_image(image)
        logger.info(f"✅ [IDENTIFY-HF] Image loaded: {img.size} pixels")
        
        # Get pipeline instance with roster service
        logger.info("🔧 [IDENTIFY-HF] Getting HF pipeline instance...")
        hf_pipeline = get_hf_pipeline(roster_service)  # Pass roster service for comparison
        logger.info("✅ [IDENTIFY-HF] Pipeline instance obtained")
        
        # Run inference
        logger.info("🚀 [IDENTIFY-HF] Running AdaFace inference...")
        results = hf_pipeline.run(img)
        logger.info(f"✅ [IDENTIFY-HF] Inference complete, got {len(results)} results")
        
        return {"results": results}
        
    except Exception as e:
        logger.error(f"❌ [IDENTIFY-HF] Error during processing: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"AdaFace processing failed: {str(e)}")
