"""
Recognition Adapters Module

Adapter implementations for the InsightFace-only recognition service.
"""

from .insightface_adapter import InsightFaceAdapter
from .embedding_router_adapter import EmbeddingRouterAdapter

__all__ = [
    "InsightFaceAdapter",
    "EmbeddingRouterAdapter"
]
