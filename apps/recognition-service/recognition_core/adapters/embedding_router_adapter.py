"""
Embedding Router Adapter

Loads embeddings from the database-backed roster storage and performs cosine
similarity matching. File-based loading has been removed to align with the
pgvector persistence architecture.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import numpy as np

from recognition_core.domain.interfaces import EmbeddingRouterPort
from recognition_core.domain.entities import EmbeddingEntry, MatchResult
from recognition_core.config import get_settings
from roster.domain.interfaces import RosterStoragePort
from recognition_core.services.hybrid_index_manager import HybridIndexManager

logger = logging.getLogger(__name__)


class EmbeddingRouterAdapter(EmbeddingRouterPort):
    """Loads embeddings from database storage and performs cosine similarity matching."""

    def __init__(self, storage_adapter: Optional[RosterStoragePort] = None):
        self.settings = get_settings()
        self._embeddings: List[EmbeddingEntry] = []
        self._last_reload: float = 0
        self._reload_lock = asyncio.Lock()
        self._reload_stats: Dict[str, Any] = {
            "entry_count": 0,
            "embedding_count": 0,
            "duration_ms": 0.0,
            "reloaded_at": None,
        }
        if storage_adapter is None:
            raise ValueError("EmbeddingRouterAdapter requires a database storage adapter")

        self._storage_adapter = storage_adapter
        self._hybrid_manager = HybridIndexManager(
            storage_adapter,
            auto_reload=self.settings.embedding_router.auto_reload,
            reload_interval=self.settings.embedding_router.reload_interval,
        )
        
    async def load_embeddings(self) -> List[EmbeddingEntry]:
        """Load embeddings from the underlying database-backed storage."""
        async with self._reload_lock:
            start = time.time()

            embeddings = await self._hybrid_manager.load_embeddings()
            duration_ms = (time.time() - start) * 1000

            self._embeddings = embeddings
            self._last_reload = time.time()
            stats = self._hybrid_manager.get_stats()
            self._reload_stats = {
                "entry_count": stats.get("entry_count", len(embeddings)),
                "embedding_count": stats.get("embedding_count", len(embeddings)),
                "duration_ms": stats.get("duration_ms", duration_ms),
                "reloaded_at": stats.get("reloaded_at", self._last_reload),
            }

            logger.info("📚 Loaded %s embeddings from database", len(embeddings))
            return self._embeddings.copy()
    
    async def find_matches(
        self, 
        query_embedding: np.ndarray, 
        threshold: float
    ) -> List[MatchResult]:
        """Find matching embeddings above the similarity threshold."""
        if not self._embeddings:
            await self.load_embeddings()
        
        if not self._embeddings:
            return []
        
        # Normalize query embedding
        norm = np.linalg.norm(query_embedding)
        if norm > 0:
            query_embedding = query_embedding / norm
        
        matches: List[MatchResult] = []
        fallback: List[MatchResult] = []
        
        for entry in self._embeddings:
            try:
                # Calculate cosine similarity
                similarity = entry.cosine_similarity(query_embedding)
                
                # Create match result
                is_match = similarity >= threshold
                match_result = MatchResult(
                    entry=entry,
                    similarity=similarity,
                    threshold=threshold,
                    is_match=is_match
                )

                if is_match:
                    matches.append(match_result)
                else:
                    fallback.append(match_result)
                    
            except Exception as e:
                logger.warning(f"⚠️ Error calculating similarity for {entry.unique_id}: {e}")
                continue
        
        # Sort by similarity (highest first)
        matches.sort(key=lambda x: x.similarity, reverse=True)
        fallback.sort(key=lambda x: x.similarity, reverse=True)

        max_candidates = max(1, getattr(self.settings.recognition, "max_candidates", 5))

        combined: List[MatchResult] = []
        combined.extend(matches)

        if len(combined) < max_candidates and fallback:
            needed = max_candidates - len(combined)
            combined.extend(fallback[:needed])

        combined = combined[:max_candidates]

        logger.info(
            "🎯 Found %s matches above threshold %s (returning %s candidates)",
            len(matches),
            threshold,
            len(combined),
        )

        return combined
    
    async def reload_if_needed(self) -> bool:
        """Check if embeddings need reloading and reload if necessary."""
        if self._hybrid_manager is not None:
            reloaded = await self._hybrid_manager.maybe_reload()
            if reloaded:
                self._embeddings = await self._hybrid_manager.load_embeddings()
                stats = self._hybrid_manager.get_stats()
                self._last_reload = time.time()
                self._reload_stats = {
                    "entry_count": stats.get("entry_count", len(self._embeddings)),
                    "embedding_count": stats.get("embedding_count", len(self._embeddings)),
                    "duration_ms": stats.get("duration_ms", 0.0),
                    "reloaded_at": stats.get("reloaded_at", self._last_reload),
                }
            return reloaded
        return False
    
    def get_loaded_count(self) -> int:
        """Get the number of loaded embeddings."""
        return len(self._embeddings)
    
    def get_loaded_names(self) -> List[str]:
        """Get the names of loaded entities."""
        return [entry.name for entry in self._embeddings]

    def get_embeddings_path(self) -> str:
        """Return a description of the backing storage."""
        return self._storage_adapter.get_storage_description()

    def get_reload_stats(self) -> Dict[str, Any]:
        """Expose last reload metadata for diagnostics."""
        stats = dict(self._reload_stats)
        if self._hybrid_manager is not None:
            stats.update(self._hybrid_manager.get_stats())
        return stats
