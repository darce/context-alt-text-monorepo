"""
Recognition Service Implementation

Main service that orchestrates face detection, embedding extraction, and matching.
Simplified for InsightFace-only pipeline.
"""

import logging
import time
from typing import Optional, List, Dict, Any
from PIL import Image

from recognition.domain.interfaces import (
    RecognitionServicePort,
    RecognitionModelPort,
    EmbeddingRouterPort,
)
from recognition.domain.entities import RecognitionResult, MatchResult
from recognition.adapters import InsightFaceAdapter, EmbeddingRouterAdapter
from recognition.config import get_settings

logger = logging.getLogger(__name__)


class RecognitionService(RecognitionServicePort):
    """
    Main recognition service that combines face detection, embedding extraction,
    and roster matching using InsightFace.
    """
    
    def __init__(
        self,
        model: Optional[RecognitionModelPort] = None,
        embedding_router: Optional[EmbeddingRouterPort] = None,
    ):
        self.settings = get_settings()
        self.model = model or InsightFaceAdapter()
        self.embedding_router = embedding_router or EmbeddingRouterAdapter()
        
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
        model_info: Dict[str, Any] = {}
        try:
            model_info = self.model.model_info()
        except AttributeError:
            model_info = {
                "model_name": getattr(self.settings.insightface, "model_name", "unknown"),
                "device": getattr(self.settings.insightface, "device", "cpu"),
            }

        return {
            **model_info,
            "default_threshold": self.settings.recognition.default_threshold,
            "loaded_embeddings": self.embedding_router.get_loaded_count(),
            "entity_names": self.embedding_router.get_loaded_names(),
            "auto_reload": self.settings.embedding_router.auto_reload,
        }
    
    async def reload_embeddings(self) -> bool:
        """Force reload embeddings from file."""
        try:
            embeddings = await self.embedding_router.load_embeddings()
            logger.info(f"🔄 Manually reloaded {len(embeddings)} embeddings")
            return len(embeddings) > 0
        except Exception as e:
            logger.error(f"❌ Failed to reload embeddings: {e}")
            return False
