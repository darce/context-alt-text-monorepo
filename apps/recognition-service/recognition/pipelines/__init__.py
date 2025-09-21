"""
Pipelines module for compatibility
"""

from .pipeline_manager import get_hf_pipeline, get_pipeline_info, reload_embeddings, PipelineManager

__all__ = [
    "get_hf_pipeline",
    "get_pipeline_info", 
    "reload_embeddings",
    "PipelineManager"
]
