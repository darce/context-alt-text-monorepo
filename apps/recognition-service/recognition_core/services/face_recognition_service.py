"""Face recognition orchestrator for the InsightFace-only pipeline."""

import logging
import time
from typing import Optional, List, Dict, Any
from PIL import Image

from recognition_core.domain.interfaces import (
    RecognitionServicePort,
    RecognitionModelPort,
    EmbeddingRouterPort,
)
from recognition_core.domain.entities import RecognitionResult, MatchResult
from recognition_core.adapters import InsightFaceAdapter, EmbeddingRouterAdapter
from recognition_core.config import get_settings

logger = logging.getLogger(__name__)


class FaceRecognitionService(RecognitionServicePort):
    """Combine detection, embedding extraction, and roster matching via InsightFace."""
    
    def __init__(
        self,
        model: Optional[RecognitionModelPort] = None,
        embedding_router: Optional[EmbeddingRouterPort] = None,
    ):
        self.settings = get_settings()
        self.model = model or InsightFaceAdapter()
        if embedding_router is None:
            raise ValueError("FaceRecognitionService requires an embedding router")
        self.embedding_router = embedding_router
        
    async def recognize_faces(
        self, 
        image: Image.Image, 
        threshold: Optional[float] = None
    ) -> RecognitionResult:
        """
        Perform complete face recognition pipeline.
        
        Args:
            image: PIL Image to analyze
            threshold: Optional threshold override (uses config default if None)
            
        Returns:
            RecognitionResult with detections, embeddings, and matches
        """
        start_time = time.time()
        
        # Use provided threshold or default from config
        similarity_threshold = threshold or self.settings.recognition.default_threshold
        
        try:
            # Step 1: Check if embeddings need reloading
            await self.embedding_router.reload_if_needed()
            
            # Step 2: Detect faces and extract embeddings in one call (more efficient)
            face_embeddings = await self.model.analyze(image)
            
            if not face_embeddings:
                logger.info("🔍 No faces detected in image")
                return RecognitionResult(
                    face_detections=[],
                    face_embeddings=[],
                    matches=[],
                    processing_time_ms=(time.time() - start_time) * 1000
                )
            
            # Step 3: Find matches for each detected face
            matches_per_face: List[List[MatchResult]] = []
            best_matches: List[MatchResult] = []

            for face_embedding in face_embeddings:
                matches = await self.embedding_router.find_matches(
                    face_embedding.embedding,
                    similarity_threshold
                )
                matches_per_face.append(matches)

                if matches:
                    best_matches.append(matches[0])
            
            # Create result
            result = RecognitionResult(
                face_detections=[emb.detection for emb in face_embeddings],
                face_embeddings=face_embeddings,
                matches=best_matches,
                processing_time_ms=(time.time() - start_time) * 1000,
                face_matches=matches_per_face,
            )
            
            logger.info(
                "✅ Recognition complete: %s faces, %s matches in %.1fms",
                len(face_embeddings),
                len(best_matches),
                result.processing_time_ms,
            )
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Recognition failed: {e}")
            return RecognitionResult(
                face_detections=[],
                face_embeddings=[],
                matches=[],
                processing_time_ms=(time.time() - start_time) * 1000
            )

    async def get_service_info(self) -> dict:
        """Get information about the current service state."""
        settings = self.settings

        # Model metadata (fallbacks ensure we always expose reasonable defaults)
        model_info: Dict[str, Any]
        try:
            model_info = self.model.model_info()
        except AttributeError:
            model_info = {}
        if not isinstance(model_info, dict):
            model_info = {}

        providers_value = model_info.get("providers", getattr(settings.insightface, "providers", []))
        if isinstance(providers_value, str):
            providers_value = [providers_value]

        model_data = {
            "name": model_info.get("model_name", getattr(settings.insightface, "model_name", "unknown")),
            "device": model_info.get("device", getattr(settings.insightface, "device", "cpu")),
            "providers": providers_value,
        }

        # Recognition runtime configuration
        recognition_data = {
            "default_threshold": settings.recognition.default_threshold,
            "max_faces_per_image": settings.recognition.max_faces_per_image,
            "embedding_dimension": settings.recognition.embedding_dimension,
        }

        # Embedding router observability info
        get_count = getattr(self.embedding_router, "get_loaded_count", lambda: 0)
        get_names = getattr(self.embedding_router, "get_loaded_names", lambda: [])
        get_path = getattr(self.embedding_router, "get_embeddings_path", None)
        get_stats = getattr(self.embedding_router, "get_reload_stats", lambda: {})

        embeddings_path = "database"
        if callable(get_path):
            try:
                embeddings_path = get_path()
            except Exception:  # pragma: no cover - diagnostics only
                embeddings_path = "database"

        embedding_router_data = {
            "auto_reload": settings.embedding_router.auto_reload,
            "reload_interval_seconds": settings.embedding_router.reload_interval,
            "embeddings_source": embeddings_path,
            "loaded_embeddings": get_count() or 0,
            "loaded_entities": get_names() or [],
            "reload_stats": get_stats() or {},
        }

        performance_data = {
            "batch_size": settings.performance.batch_size,
            "max_concurrent_requests": settings.performance.max_concurrent_requests,
        }

        cache_data = {
            "hf_home": settings.cache.hf_home,
            "hf_datasets_cache": settings.cache.hf_datasets_cache,
            "torch_home": settings.cache.torch_home,
        }

        return {
            "model": model_data,
            "recognition": recognition_data,
            "embedding_router": embedding_router_data,
            "performance": performance_data,
            "cache": cache_data,
        }
    
    async def reload_embeddings(self) -> Dict[str, Any]:
        """Force reload embeddings from the backing storage."""
        start = time.time()
        try:
            embeddings = await self.embedding_router.load_embeddings()
            stats_getter = getattr(self.embedding_router, "get_reload_stats", lambda: {})
            stats = stats_getter() or {}
            entry_count = len(embeddings)
            duration_ms = stats.get("duration_ms", (time.time() - start) * 1000)

            payload = {
                "status": "reloaded" if entry_count else "empty",
                "entry_count": entry_count,
                "embedding_count": entry_count,
                "duration_ms": duration_ms,
            }
            if "reloaded_at" in stats:
                payload["reloaded_at"] = stats["reloaded_at"]

            logger.info("🔄 Manually reloaded %s embeddings (%.2fms)", entry_count, duration_ms)
            return payload
        except Exception as exc:
            logger.error("❌ Failed to reload embeddings: %s", exc)
            return {
                "status": "error",
                "entry_count": 0,
                "embedding_count": 0,
                "duration_ms": (time.time() - start) * 1000,
                "error": str(exc),
            }
