"""
Pipeline Manager for Recognition Service
Provides backward compatibility with existing pipeline interface.
"""
import logging
from typing import Optional, Dict, Any
from ..ports.dependencies import get_recognition_service
from ..domain import RecognitionPort

logger = logging.getLogger(__name__)


class PipelineManager:
    """Pipeline manager for backward compatibility."""
    
    def __init__(self):
        """Initialize pipeline manager."""
        self._recognition_service: Optional[RecognitionPort] = None
    
    def get_hf_pipeline(self, roster_service=None):
        """
        Get the recognition service pipeline.
        
        Args:
            roster_service: Roster service (ignored, handled by embedding router)
            
        Returns:
            Recognition service instance
        """
        if self._recognition_service is None:
            self._recognition_service = get_recognition_service()
        
        return self._recognition_service
    
    def clear_cache(self):
        """Clear pipeline cache."""
        from ..ports.dependencies import clear_recognition_service
        clear_recognition_service()
        self._recognition_service = None
        logger.info("🧹 Pipeline cache cleared")


# Global pipeline manager instance
_pipeline_manager = PipelineManager()


def get_hf_pipeline(roster_service=None):
    """
    Get the HuggingFace pipeline (backward compatibility).
    
    Args:
        roster_service: Roster service (ignored)
        
    Returns:
        Recognition service instance
    """
    return _pipeline_manager.get_hf_pipeline(roster_service)


def clear_pipeline_cache():
    """Clear pipeline cache."""
    _pipeline_manager.clear_cache()


def get_pipeline_manager() -> PipelineManager:
    """Get the pipeline manager instance."""
    return _pipeline_manager
