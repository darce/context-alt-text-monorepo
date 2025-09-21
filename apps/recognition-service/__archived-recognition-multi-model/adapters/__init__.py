"""
Recognition Service Adapters Layer
External adapters for face recognition models and infrastructure.
"""
from .face_aligner_impl import FaceAlignerImpl
from .quality_scorer_impl import QualityScorerImpl
from .embedding_router_impl import EmbeddingRouterImpl
from .base_cvlface_adapter import BaseCVLFaceAdapter
from .cvlface_adaface_adapter import CVLFaceAdaFaceAdapter
from .cvlface_insight_adapter import CVLFaceInsightAdapter
from .cvlface_arcface_adapter import CVLFaceArcFaceAdapter

__all__ = [
    # Domain implementations
    "FaceAlignerImpl",
    "QualityScorerImpl", 
    "EmbeddingRouterImpl",
    # Model adapters
    "BaseCVLFaceAdapter",
    "CVLFaceAdaFaceAdapter",
    "CVLFaceInsightAdapter",
    "CVLFaceArcFaceAdapter"
]
