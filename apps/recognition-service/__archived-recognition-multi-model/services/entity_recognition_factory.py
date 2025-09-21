"""Entity recognition factory for backward compatibility."""

import logging
from typing import Optional, Any, Dict

logger = logging.getLogger(__name__)


def get_entity_recognition_adapter(
    pipeline_override: Optional[str] = None, 
    threshold_override: Optional[float] = None, 
    force_reload: bool = False
) -> Optional[Any]:
    """
    Get entity recognition adapter for backward compatibility.
    
    This is a simplified version that returns None for now.
    The actual recognition is handled by the new recognition service.
    
    Args:
        pipeline_override: Override pipeline type
        threshold_override: Override threshold value
        force_reload: Force reload of adapter
        
    Returns:
        None (for backward compatibility)
    """
    logger.warning(
        "get_entity_recognition_adapter is deprecated. "
        "Use the new recognition service instead."
    )
    return None


def get_pipeline_info() -> Dict[str, Any]:
    """Get information about the current pipeline configuration."""
    return {
        "default_pipeline": "insightface",
        "available_pipelines": ["adaface_ir101", "insightface_w600k", "arcface_ir50"],
        "cached_adapters": [],
        "total_cached_adapters": 0,
        "configuration": {
            "pipeline": "insightface",
            "threshold": 0.5
        }
    }


def reload_embeddings() -> bool:
    """Reload embeddings for the current pipeline."""
    logger.warning("reload_embeddings is deprecated. Use the new recognition service instead.")
    return True
