"""
Entity Recognition Factory Compatibility Shim

Provides compatibility for the old entity recognition factory.
Now simplified to use the InsightFace-only recognition service.
"""

import logging
from typing import Optional, Any
from recognition.services import RecognitionService

logger = logging.getLogger(__name__)

# Global instance
_recognition_adapter: Optional[RecognitionService] = None


def get_entity_recognition_adapter(force_reload: bool = False) -> RecognitionService:
    """
    Get the entity recognition adapter (now the simplified recognition service).
    
    Args:
        force_reload: Whether to force reload the adapter (ignored for compatibility)
        
    Returns:
        RecognitionService instance
    """
    global _recognition_adapter
    
    if _recognition_adapter is None or force_reload:
        logger.info("🔧 Creating simplified InsightFace recognition adapter")
        _recognition_adapter = RecognitionService()
    
    return _recognition_adapter


def get_pipeline_info() -> dict:
    """Get information about the current pipeline."""
    service = get_entity_recognition_adapter()
    import asyncio
    
    try:
        # Run async method in sync context
        loop = None
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        if loop.is_running():
            # If we're in an async context, create a new thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, service.get_service_info())
                info = future.result()
        else:
            info = loop.run_until_complete(service.get_service_info())
        
        return {
            "current_pipeline": "insightface",
            "available_pipelines": ["insightface"],
            "adapter_loaded": True,
            "configuration": info,
            "loaded_entities": info.get("loaded_embeddings", 0),
            "entity_names": info.get("entity_names", [])
        }
    except Exception as e:
        logger.error(f"❌ Error getting pipeline info: {e}")
        return {
            "current_pipeline": "insightface",
            "available_pipelines": ["insightface"],
            "adapter_loaded": False,
            "configuration": {},
            "loaded_entities": 0,
            "entity_names": [],
            "error": str(e)
        }


def reload_embeddings() -> bool:
    """Reload embeddings for the current adapter."""
    service = get_entity_recognition_adapter()
    import asyncio
    
    try:
        loop = None
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, service.reload_embeddings())
                return future.result()
        else:
            return loop.run_until_complete(service.reload_embeddings())
    except Exception as e:
        logger.error(f"❌ Failed to reload embeddings: {e}")
        return False
