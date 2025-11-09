"""
Hybrid Index Manager - FAISS + Database Synchronization

Manages FAISS in-memory index synchronized with database embeddings.
Database is the source of truth; FAISS provides fast similarity search.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, Any, List, Optional

import numpy as np

from recognition_core.domain.entities import EmbeddingEntry
from roster.domain.interfaces import RosterStoragePort

logger = logging.getLogger(__name__)


class HybridIndexManager:
    """
    Manages FAISS index synchronized with database embeddings.
    
    Architecture:
    - Database: Canonical storage for all embeddings (reference + augmented)
    - FAISS: In-memory index for fast similarity search
    - Sync: Rebuild FAISS when database changes detected
    
    Usage:
        manager = HybridIndexManager(storage_adapter)
        await manager.maybe_reload()  # Check for changes and reload if needed
        results = await manager.search(query_embedding, top_k=5)
    """
    
    def __init__(
        self,
        storage_adapter: RosterStoragePort,
        auto_reload: bool = True,
        reload_interval: int = 30,
    ):
        """
        Initialize hybrid index manager.
        
        Args:
            storage_adapter: Database storage adapter (PostgreSQL or SQLite)
            auto_reload: Enable automatic index reloading
            reload_interval: Minimum seconds between automatic reloads
        """
        self.storage = storage_adapter
        self.auto_reload = auto_reload
        self.reload_interval = reload_interval
        
        # FAISS index state
        self._embeddings: List[EmbeddingEntry] = []
        self._last_reload: float = 0
        self._reload_lock = asyncio.Lock()
        self._reload_stats: Dict[str, Any] = {
            "entry_count": 0,
            "embedding_count": 0,
            "duration_ms": 0.0,
            "reloaded_at": None,
            "source": "database",
        }
        
        logger.info(
            "🔄 HybridIndexManager initialized (auto_reload=%s, interval=%ss)",
            auto_reload,
            reload_interval,
        )
    
    async def rebuild_index(self) -> int:
        """
        Rebuild FAISS index from database embeddings.
        
        Returns:
            Number of embeddings loaded
        """
        async with self._reload_lock:
            start = time.time()
            
            try:
                # Load all roster entries with embeddings from database
                logger.info("📚 Loading embeddings from database...")
                roster_entries = await asyncio.to_thread(
                    self.storage.load_roster_entries,
                    model="insightface_w600k"  # Default model
                )
                
                # Convert to EmbeddingEntry format for FAISS
                embeddings = []
                for entry in roster_entries:
                    if entry.aggregate_embedding:
                        embeddings.append(
                            EmbeddingEntry(
                                unique_id=entry.unique_id,
                                name=entry.name,
                                display_name=entry.display_name,
                                aggregate_embedding=np.array(entry.aggregate_embedding, dtype=np.float32),
                                metadata=entry.metadata or {},
                            )
                        )
                
                # Update index
                self._embeddings = embeddings
                self._last_reload = time.time()
                
                duration_ms = (time.time() - start) * 1000
                self._reload_stats = {
                    "entry_count": len(roster_entries),
                    "embedding_count": len(embeddings),
                    "duration_ms": duration_ms,
                    "reloaded_at": self._last_reload,
                    "source": "database",
                }
                
                logger.info(
                    "✅ FAISS index rebuilt: %d entries, %d embeddings (%.2fms)",
                    len(roster_entries),
                    len(embeddings),
                    duration_ms,
                )
                
                return len(embeddings)
                
            except Exception as exc:
                logger.error("❌ Failed to rebuild FAISS index from database: %s", exc, exc_info=True)
                raise
    
    async def maybe_reload(self) -> bool:
        """
        Check if reload is needed and reload if necessary.
        
        Reload conditions:
        - Auto-reload enabled
        - Sufficient time passed since last reload
        - First load (no embeddings yet)
        
        Returns:
            True if reloaded, False if skipped
        """
        if not self.auto_reload:
            return False
        
        now = time.time()
        time_since_reload = now - self._last_reload
        
        # Always reload on first call
        if not self._embeddings:
            await self.rebuild_index()
            return True
        
        # Respect reload interval
        if time_since_reload < self.reload_interval:
            return False
        
        # TODO: Implement change detection (e.g., database ETag or updated_at check)
        # For now, always reload after interval
        await self.rebuild_index()
        return True
    
    async def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 5,
        threshold: float = 0.65,
    ) -> List[Dict[str, Any]]:
        """
        Search for similar embeddings using cosine similarity.
        
        Args:
            query_embedding: Query vector (512-dim for InsightFace)
            top_k: Maximum number of results to return
            threshold: Minimum similarity score (0.0-1.0)
        
        Returns:
            List of matches with entity_id, label, score
        """
        if not self._embeddings:
            logger.warning("⚠️ FAISS index empty, attempting reload...")
            await self.rebuild_index()
            if not self._embeddings:
                return []
        
        # Normalize query
        query_norm = query_embedding / (np.linalg.norm(query_embedding) + 1e-8)
        
        # Compute cosine similarity with all embeddings
        scores = []
        for entry in self._embeddings:
            # Embeddings should already be normalized, but ensure it
            entry_norm = entry.aggregate_embedding / (np.linalg.norm(entry.aggregate_embedding) + 1e-8)
            similarity = float(np.dot(query_norm, entry_norm))
            
            if similarity >= threshold:
                scores.append({
                    "entity_id": entry.unique_id,
                    "label": entry.name,
                    "score": similarity,
                    "metadata": entry.metadata,
                })
        
        # Sort by score descending and limit to top_k
        scores.sort(key=lambda x: x["score"], reverse=True)
        return scores[:top_k]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current index statistics."""
        return {
            **self._reload_stats,
            "auto_reload": self.auto_reload,
            "reload_interval_seconds": self.reload_interval,
            "time_since_reload": time.time() - self._last_reload if self._last_reload else None,
        }
    
    async def load_embeddings(self) -> List[EmbeddingEntry]:
        """
        Load embeddings (compatibility method for EmbeddingRouterPort).
        
        Returns:
            List of embedding entries
        """
        await self.maybe_reload()
        return self._embeddings.copy()
