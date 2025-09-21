"""
Recognition Service Dependencies
Dependency injection for the recognition service.
"""
import logging
from typing import Dict, Optional
import os

from ..domain import (
    ModelType, RecognitionPort, RecognitionService, 
    FaceAligner, QualityScorer, EmbeddingRouter, CVLFaceAdapter
)
from ..adapters.face_aligner_impl import FaceAlignerImpl
from ..adapters.quality_scorer_impl import QualityScorerImpl
from ..adapters.embedding_router_impl import EmbeddingRouterImpl
from ..adapters.cvlface_adaface_adapter import CVLFaceAdaFaceAdapter
from ..adapters.cvlface_insight_adapter import CVLFaceInsightAdapter
from ..adapters.cvlface_arcface_adapter import CVLFaceArcFaceAdapter

logger = logging.getLogger(__name__)

# Global service instance
_recognition_service: Optional[RecognitionService] = None


def get_recognition_service() -> RecognitionPort:
    """
    Get or create recognition service instance.
    
    Returns:
        Recognition service singleton
    """
    global _recognition_service
    
    if _recognition_service is None:
        _recognition_service = create_recognition_service()
    
    return _recognition_service


def create_recognition_service() -> RecognitionService:
    """
    Create and configure recognition service.
    
    Returns:
        Configured recognition service
    """
    logger.info("🚀 Creating recognition service...")
    
    # Create domain services
    face_aligner = create_face_aligner()
    quality_scorer = create_quality_scorer()
    embedding_router = create_embedding_router()
    
    # Create model adapters
    adapters = create_model_adapters()
    
    # Create recognition service
    service = RecognitionService(
        face_aligner=face_aligner,
        quality_scorer=quality_scorer,
        embedding_router=embedding_router,
        adapters=adapters
    )
    
    logger.info(f"✅ Recognition service created with {len(adapters)} adapters")
    return service


def create_face_aligner() -> FaceAligner:
    """Create face aligner implementation."""
    return FaceAlignerImpl()


def create_quality_scorer() -> QualityScorer:
    """Create quality scorer implementation."""
    return QualityScorerImpl()


def create_embedding_router() -> EmbeddingRouter:
    """Create embedding router implementation."""
    # Get roster data directory from environment
    roster_dir = os.getenv('ROSTER_DATA_DIR', '/Users/daniel/Development/__hugging-face/entity-identifier-api/roster/data')
    return EmbeddingRouterImpl(roster_dir=roster_dir)


def create_model_adapters() -> Dict[ModelType, CVLFaceAdapter]:
    """
    Create model adapters for all supported models.
    
    Returns:
        Dictionary mapping model types to adapters
    """
    adapters = {}
    
    # Get device from environment
    device = os.getenv('DEVICE', 'auto')
    
    try:
        # AdaFace IR101 WebFace12M
        adapters[ModelType.ADAFACE_IR101] = CVLFaceAdaFaceAdapter(
            model_id="minchul/cvlface_adaface_ir101_webface12m",
            device=device
        )
        logger.info("✅ AdaFace IR101 adapter created")
    except Exception as e:
        logger.error(f"❌ Failed to create AdaFace IR101 adapter: {e}")
    
    try:
        # InsightFace W600K
        adapters[ModelType.INSIGHTFACE_W600K] = CVLFaceInsightAdapter(
            model_id="deepinsight/insightface-scrfd-arcface-w600k",
            device=device
        )
        logger.info("✅ InsightFace W600K adapter created")
    except Exception as e:
        logger.error(f"❌ Failed to create InsightFace adapter: {e}")
    
    try:
        # ArcFace IR50 WebFace4M
        adapters[ModelType.ARCFACE_IR50] = CVLFaceArcFaceAdapter(
            model_id="minchul/cvlface_arcface_ir50_webface4m",
            device=device
        )
        logger.info("✅ ArcFace IR50 adapter created")
    except Exception as e:
        logger.error(f"❌ Failed to create ArcFace adapter: {e}")
    
    if not adapters:
        raise RuntimeError("No model adapters could be created")
    
    return adapters


def clear_recognition_service():
    """Clear the recognition service singleton for testing."""
    global _recognition_service
    _recognition_service = None
