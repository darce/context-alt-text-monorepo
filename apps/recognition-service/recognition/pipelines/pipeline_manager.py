"""
Pipeline Manager Compatibility Shim

Provides compatibility for the old multi-model pipeline manager.
Now simplified to only provide the InsightFace pipeline.
"""

import logging
from typing import Optional, Any
from recognition.services import RecognitionService

logger = logging.getLogger(__name__)

# Global instance
_hf_pipeline: Optional[RecognitionService] = None


def get_hf_pipeline() -> RecognitionService:
    """
    Get the HuggingFace pipeline (now just the simplified recognition service).
    
    This is a compatibility function that maintains the same interface
    as the old multi-model pipeline manager.
    """
    global _hf_pipeline
    
    if _hf_pipeline is None:
        logger.info("🔧 Initializing simplified InsightFace recognition service")
        _hf_pipeline = RecognitionService()
    
    return _hf_pipeline


def get_pipeline_info() -> dict:
    """Get information about the current pipeline."""
    service = get_hf_pipeline()
    import asyncio
    
    # Run async method in sync context
    loop = None
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    if loop.is_running():
        # If we're in an async context, we need to create a new loop
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


def reload_embeddings() -> bool:
    """Reload embeddings for the current pipeline."""
    service = get_hf_pipeline()
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


class PipelineManager:
    """
    Compatibility class for the old PipelineManager.
    Now simplified to only manage the InsightFace pipeline.
    """
    
    def __init__(self):
        self.current_pipeline = "insightface"
        self.available_pipelines = ["insightface"]
    
    def get_current_pipeline(self) -> str:
        return self.current_pipeline
    
    def get_available_pipelines(self) -> list:
        return self.available_pipelines
    
    def switch_pipeline(self, pipeline_name: str) -> bool:
        if pipeline_name == "insightface":
            return True
        else:
            logger.warning(f"⚠️ Pipeline '{pipeline_name}' not supported, only InsightFace available")
            return False
    
    def get_pipeline_service(self) -> RecognitionService:
        return get_hf_pipeline()
