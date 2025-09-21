from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
import logging
from typing import Optional
from analysis.workflow.scene_composer import SceneComposer
from analysis.services.scene_analysis_service import SceneAnalysisService
from .roster import router as roster_router
from .entity_recognition import router as entity_recognition_router
from recognition.pipelines.pipeline_manager import get_hf_pipeline
from api.dependencies import get_roster_service
from api.schemas import AnalyzeSceneRequest, EmbeddingsRequest
from shared.utils.device_utils import get_available_device  # for device resolution if needed

router = APIRouter()
router.include_router(roster_router)
router.include_router(entity_recognition_router)

# Dependency to get scene composer - will be set by the main app
_scene_composer: Optional[SceneComposer] = None
_scene_analysis_service: Optional[SceneAnalysisService] = None

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

@router.post("/caption")
async def caption(
    image: UploadFile = File(...),
    reference_image: Optional[UploadFile] = File(None),
    caption: str = Form(""),
    post_body: str = Form(""),
    scene_analysis_service: SceneAnalysisService = Depends(get_scene_analysis_service),
):
    try:
        from PIL import Image
        import io

        async def _read_pil_image(file: UploadFile) -> Image.Image:
            data = await file.read()
            return Image.open(io.BytesIO(data)).convert("RGB")

        main_image = await _read_pil_image(image)
        ref_image = await _read_pil_image(reference_image) if reference_image else None
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
    except Exception as e:
        logging.error(f"Error generating caption: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/identify")
async def identify(
    image: UploadFile = File(...),
    reference_image: UploadFile = File(...),
    request: Request = None
):
    try:
        main_image = await _read_pil_image(image)
        ref_image = await _read_pil_image(reference_image)
        scene_composer = get_scene_composer(request)
        results = scene_composer.identify_persons_with_reference(main_image, ref_image)
        return {"results": results}
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
            detected_entity_dicts = [entity.to_dict() if hasattr(entity, 'to_dict') else entity.__dict__ for entity in scene_context.detected_entities]
            result = {
                "scene_description": description,
                "processing_time": proc_time,
                "detected_objects": [obj.to_dict() if hasattr(obj, 'to_dict') else obj.__dict__ for obj in scene_context.detected_objects],
                "detected_entities": detected_entity_dicts,
                # Parallel array of roster match details (None if no match)
                "roster_matches": [
                    (entity.roster_match.to_dict() if entity.roster_match else None)
                    for entity in scene_context.detected_entities
                ],
                "identified_roster_entities": [],
                "processing_metadata": scene_context.processing_metadata or {}
            }
            
            # Include detailed identified roster entities if any
            if scene_context.identified_roster_entities:
                # Return matched roster entries directly for client compatibility
                result["identified_roster_entities"] = [
                    entity.roster_match.roster_entry.to_dict()
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

        return response_data

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
            embedding_vector = face_embedding.embedding.tolist()
            candidate_matches = matches_per_face[idx] if idx < len(matches_per_face) else []

            response_faces.append(
                {
                    "bbox": list(detection.bbox),
                    "confidence": float(detection.confidence),
                    "embedding": embedding_vector,
                    "matches": [
                        {
                            "name": match.entry.name,
                            "unique_id": match.entry.unique_id,
                            "similarity": match.similarity,
                            "meets_threshold": match.is_match,
                            "metadata": match.entry.metadata,
                        }
                        for match in candidate_matches
                    ],
                }
            )

        return {
            "faces": response_faces,
            "processing_time_ms": recognition_result.processing_time_ms,
            "threshold": threshold or recognition_service.settings.recognition.default_threshold,
        }

    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        logging.error("Error in /embeddings endpoint: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

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
