"""
Entity Recognition Pipeline API Routes

This module provides API endpoints for managing entity recognition pipelines,
including getting current pipeline info, switching pipelines, and reloading embeddings.
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any
import logging

from recognition.services.entity_recognition_factory import (
    get_pipeline_info, 
    reload_embeddings,
    get_entity_recognition_adapter
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/entity-recognition", tags=["entity-recognition"])


@router.get("/pipeline/info", response_model=Dict[str, Any])
async def get_pipeline_information():
    """
    Get information about the current entity recognition pipeline.
    
    Returns:
        Dictionary containing pipeline information including:
        - current_pipeline: The active pipeline name
        - available_pipelines: List of available pipelines
        - adapter_loaded: Whether an adapter is currently loaded
        - configuration: Current pipeline configuration
        - loaded_entities: Number of entities loaded (if applicable)
        - entity_names: List of loaded entity names (if applicable)
    """
    try:
        info = get_pipeline_info()
        return {
            "status": "success",
            "data": info
        }
    except Exception as e:
        logger.error(f"❌ Error getting pipeline info: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get pipeline information: {str(e)}")


@router.post("/embeddings/reload")
async def reload_pipeline_embeddings():
    """
    Reload embeddings for the current pipeline.
    
    This will reload the latest embeddings file for the current pipeline
    without changing the pipeline configuration.
    
    Returns:
        Success status and information about the reload operation.
    """
    try:
        success = reload_embeddings()
        
        if success:
            # Get updated info
            info = get_pipeline_info()
            return {
                "status": "success",
                "message": "Embeddings reloaded successfully",
                "data": {
                    "loaded_entities": info.get("loaded_entities", 0),
                    "entity_names": info.get("entity_names", [])
                }
            }
        else:
            return {
                "status": "failed",
                "message": "Failed to reload embeddings",
                "data": {}
            }
            
    except Exception as e:
        logger.error(f"❌ Error reloading embeddings: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reload embeddings: {str(e)}")


@router.post("/adapter/reload")
async def reload_adapter():
    """
    Force reload of the entity recognition adapter.
    
    This will reload the adapter and its embeddings, useful after
    configuration changes or new embeddings generation.
    
    Returns:
        Success status and information about the adapter.
    """
    try:
        # Force reload the adapter
        adapter = get_entity_recognition_adapter(force_reload=True)
        
        if adapter:
            info = get_pipeline_info()
            return {
                "status": "success",
                "message": "Adapter reloaded successfully",
                "data": {
                    "adapter_type": type(adapter).__name__,
                    "loaded_entities": info.get("loaded_entities", 0),
                    "entity_names": info.get("entity_names", [])
                }
            }
        else:
            return {
                "status": "failed",
                "message": "Failed to reload adapter",
                "data": {}
            }
            
    except Exception as e:
        logger.error(f"❌ Error reloading adapter: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reload adapter: {str(e)}")


@router.get("/embeddings/files")
async def list_embeddings_files():
    """
    List available embeddings files for all pipelines.
    
    Returns:
        Dictionary with embeddings files organized by pipeline type.
    """
    try:
        from pathlib import Path
        import re
        from datetime import datetime
        
        # Get project root and data directory
        project_root = Path(__file__).parent.parent.parent
        data_dir = project_root / "data"
        
        if not data_dir.exists():
            return {
                "status": "success",
                "data": {
                    "insightface": [],
                    "adaface": []
                }
            }
        
        # Find InsightFace embeddings
        insightface_pattern = re.compile(r"insightface_embeddings_augmented_(\d{8}_\d{6})\.json")
        insightface_files = []
        
        for file_path in data_dir.glob("insightface_embeddings_augmented_*.json"):
            match = insightface_pattern.match(file_path.name)
            if match:
                timestamp_str = match.group(1)
                # Parse timestamp
                try:
                    timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                    insightface_files.append({
                        "filename": file_path.name,
                        "path": str(file_path),
                        "timestamp": timestamp.isoformat(),
                        "size_bytes": file_path.stat().st_size
                    })
                except ValueError:
                    # Skip files with invalid timestamps
                    continue
        
        # Sort by timestamp (most recent first)
        insightface_files.sort(key=lambda x: x["timestamp"], reverse=True)
        
        # Find AdaFace embeddings (when implemented)
        adaface_pattern = re.compile(r"adaface_embeddings_augmented_(\d{8}_\d{6})\.json")
        adaface_files = []
        
        for file_path in data_dir.glob("adaface_embeddings_augmented_*.json"):
            match = adaface_pattern.match(file_path.name)
            if match:
                timestamp_str = match.group(1)
                try:
                    timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                    adaface_files.append({
                        "filename": file_path.name,
                        "path": str(file_path),
                        "timestamp": timestamp.isoformat(),
                        "size_bytes": file_path.stat().st_size
                    })
                except ValueError:
                    continue
        
        # Sort by timestamp (most recent first)
        adaface_files.sort(key=lambda x: x["timestamp"], reverse=True)
        
        return {
            "status": "success",
            "data": {
                "insightface": insightface_files,
                "adaface": adaface_files
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Error listing embeddings files: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list embeddings files: {str(e)}")


@router.get("/health")
async def pipeline_health_check():
    """
    Health check for the entity recognition pipeline.
    
    Returns:
        Status of the current pipeline and adapter.
    """
    try:
        adapter = get_entity_recognition_adapter()
        info = get_pipeline_info()
        
        is_healthy = adapter is not None
        
        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "pipeline": info.get("current_pipeline"),
            "adapter_loaded": info.get("adapter_loaded", False),
            "loaded_entities": info.get("loaded_entities", 0),
            "message": "Pipeline is operational" if is_healthy else "Pipeline adapter not loaded"
        }
        
    except Exception as e:
        logger.error(f"❌ Error in health check: {e}")
        return {
            "status": "unhealthy",
            "message": f"Health check failed: {str(e)}"
        }
