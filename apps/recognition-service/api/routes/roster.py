from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from typing import List, Optional
import logging
import os
from shared.dtos.roster import RosterEntryDTO
from roster.services.roster_service import RosterService
from api.dependencies import get_roster_service
from api.utils.api_utils import read_pil_image, parse_metadata

router = APIRouter()

@router.post("/roster")
async def add_to_roster(
    images: List[UploadFile] = File(...),
    names: List[str] = Form(...),
    metadata: Optional[str] = Form(None),
    roster_service: RosterService = Depends(get_roster_service),
):
    """
    Add entities to the roster with reference images.
    """
    try:
        # Read images and parse metadata using shared helpers
        pil_images = [await read_pil_image(image_file) for image_file in images]
        meta_dict = parse_metadata(metadata)
        successful_names = roster_service.add_entries_from_request(pil_images, names, meta_dict)
        
        # Create response in expected format
        results = []
        for name in names:
            # Check if this name was successfully added
            success = name in successful_names
            results.append({
                "name": name,
                "success": success,
                "message": f"Successfully added to roster" if success else f"Failed to add to roster"
            })
        
        # Get current roster count efficiently
        total_entries = roster_service.get_roster_count()
        
        return {
            "message": f"Processed {len(names)} entities, {len(successful_names)} successfully added to roster",
            "results": results,
            "roster_stats": {
                "total_entries": total_entries,
                "newly_added": len(successful_names)
            }
        }
    except Exception as e:
        logging.error(f"Error in /roster endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/roster")
async def get_roster(
    include_embeddings: bool = False,
    roster_service: RosterService = Depends(get_roster_service),
):
    """
    Retrieve the current roster entries.
    
    Args:
        include_embeddings: Whether to include embedding vectors in the response
    """
    try:
        entries = roster_service.get_roster_entries(include_embeddings=include_embeddings)
        
        # DEBUG: Check what we're about to return
        debug_log_path = os.path.join("data", "debug_roster.log")
        os.makedirs("data", exist_ok=True)
        with open(debug_log_path, "a") as f:
            f.write(f"[API-DEBUG] Returning {len(entries)} entries\n")
            if entries:
                first_entry = entries[0]
                f.write(f"[API-DEBUG] First entry type: {type(first_entry)}\n")
                if hasattr(first_entry, 'aggregate_embedding'):
                    f.write(f"[API-DEBUG] First entry has aggregate_embedding: {first_entry.aggregate_embedding is not None}\n")
                if hasattr(first_entry, 'model_dump'):
                    entry_dict = first_entry.model_dump()
                    f.write(f"[API-DEBUG] First entry dict keys: {list(entry_dict.keys())}\n")
                    f.write(f"[API-DEBUG] aggregate_embedding in dict: {'aggregate_embedding' in entry_dict}\n")
        
        return {
            "count": len(entries),
            "entries": entries
        }
    except Exception as e:
        logging.error(f"Error in GET /roster endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/roster/{id}")
async def remove_from_roster(
    id: str,
    roster_service: RosterService = Depends(get_roster_service),
):
    """
    Remove an entity from the roster by unique ID.
    """
    try:
        success = roster_service.remove_roster_entry_by_id(id)
        if success:
            return {"message": f"Successfully removed id '{id}' from roster"}
        else:
            raise HTTPException(status_code=404, detail=f"Entity with id '{id}' not found in roster")
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error in DELETE /roster/{{id}} endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/roster/{id}/roster-image")  # renamed to match service
async def add_reference_image_to_roster(
    id: str,
    image: UploadFile = File(...),
    metadata: Optional[str] = Form(None),
    roster_service: RosterService = Depends(get_roster_service),
):
    """
    Add a new reference image to an existing roster entity.
    """
    try:
        pil_image = await read_pil_image(image)
        meta_dict = parse_metadata(metadata)
        success = roster_service.add_roster_image(id, pil_image, meta_dict)
        if not success:
            raise HTTPException(status_code=404, detail=f"Could not add image to roster entry '{id}'")
        return {"message": f"Reference image added to roster entry '{id}'"}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error in /roster/{id}/roster-image endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/roster-hf")
async def add_to_roster_hf(
    images: List[UploadFile] = File(...),
    names: List[str] = Form(...),
    metadata: Optional[str] = Form(None),
    roster_service: RosterService = Depends(get_roster_service),
):
    """
    Add entities to the roster with reference images using AdaFace HF pipeline for embeddings.
    This ensures consistency with the identify-hf endpoint.
    """
    try:
        from recognition.pipelines.pipeline_manager import PipelineManager
        
        logger = logging.getLogger(__name__)
        logger.info(f"🔍 [ROSTER-HF] Adding {len(names)} entities using AdaFace HF pipeline")
        
        # Get AdaFace pipeline
        manager = PipelineManager()
        adaface_pipeline = manager.get_hf_pipeline()
        
        # Read images and parse metadata using shared helpers
        pil_images = [await read_pil_image(image_file) for image_file in images]
        parsed_metadata = parse_metadata(metadata)
        
        # Handle metadata as either dict or list
        if isinstance(parsed_metadata, list):
            # Metadata is a list of dicts (one per entity)
            meta_list = parsed_metadata
        else:
            # Metadata is a single dict, convert to list
            meta_list = [parsed_metadata] * len(names)
        
        logger.info(f"🧠 [ROSTER-HF] Processing {len(pil_images)} images with AdaFace...")
        
        # Process each image with AdaFace to get embeddings
        adaface_results = []
        for i, pil_image in enumerate(pil_images):
            try:
                results = adaface_pipeline.run(pil_image)
                if results and len(results) > 0:
                    # Use the first (best) face detection result
                    embedding = results[0]['embedding']
                    adaface_results.append({
                        'embedding': embedding,
                        'bbox': results[0].get('bbox'),
                        'detection_confidence': results[0].get('detection_confidence', 1.0)
                    })
                    logger.debug(f"✅ [ROSTER-HF] Image {i}: extracted embedding shape {len(embedding)}")
                else:
                    logger.warning(f"⚠️ [ROSTER-HF] Image {i}: no faces detected")
                    adaface_results.append(None)
            except Exception as e:
                logger.error(f"❌ [ROSTER-HF] Image {i}: error extracting embedding: {e}")
                adaface_results.append(None)
        
        # Add to roster with AdaFace embeddings
        successful_names = []
        results = []
        
        for i, name in enumerate(names):
            try:
                if i < len(adaface_results) and adaface_results[i] is not None:
                    # Create roster entry with AdaFace embedding
                    embedding = adaface_results[i]['embedding']
                    # Get metadata for this specific entity (ensure it's a dict)
                    metadata_for_entry = meta_list[i] if i < len(meta_list) else {}
                    if not isinstance(metadata_for_entry, dict):
                        metadata_for_entry = {}
                    
                    # Add additional metadata about the AdaFace processing
                    metadata_for_entry.update({
                        'embedding_method': 'adaface_hf',
                        'bbox': adaface_results[i].get('bbox'),
                        'detection_confidence': adaface_results[i].get('detection_confidence')
                    })
                    
                    # Add to roster using direct embedding
                    roster_service.add_entry_with_embedding(
                        name=name,
                        embedding=embedding,
                        metadata=metadata_for_entry
                    )
                    
                    successful_names.append(name)
                    results.append({
                        "name": name,
                        "success": True,
                        "message": "Successfully added to roster with AdaFace embedding"
                    })
                    logger.info(f"✅ [ROSTER-HF] Added {name} with AdaFace embedding")
                else:
                    results.append({
                        "name": name,
                        "success": False,
                        "message": "Failed to extract AdaFace embedding"
                    })
                    logger.warning(f"⚠️ [ROSTER-HF] Failed to add {name}: no embedding extracted")
                    
            except Exception as e:
                results.append({
                    "name": name,
                    "success": False,
                    "message": f"Error adding to roster: {str(e)}"
                })
                logger.error(f"❌ [ROSTER-HF] Error adding {name}: {e}")
        
        # Get current roster count
        total_entries = roster_service.get_roster_count()
        
        logger.info(f"✅ [ROSTER-HF] Completed: {len(successful_names)}/{len(names)} successfully added")
        
        return {
            "message": f"Processed {len(names)} entities using AdaFace HF, {len(successful_names)} successfully added to roster",
            "results": results,
            "roster_stats": {
                "total_entries": total_entries,
                "newly_added": len(successful_names)
            }
        }
    except Exception as e:
        logger.error(f"❌ [ROSTER-HF] Error in roster-hf endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to add to roster with AdaFace: {str(e)}")
