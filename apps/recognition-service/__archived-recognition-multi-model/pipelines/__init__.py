"""
Recognition Service Pipelines
Backward compatibility layer for existing pipeline interface.
"""
from .pipeline_manager import (
    get_hf_pipeline, clear_pipeline_cache, get_pipeline_manager, PipelineManager
)

__all__ = [
    "get_hf_pipeline",
    "clear_pipeline_cache", 
    "get_pipeline_manager",
    "PipelineManager"
]
