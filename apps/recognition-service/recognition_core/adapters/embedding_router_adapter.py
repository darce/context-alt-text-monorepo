"""
Embedding Router Adapter

Handles loading and matching against roster embeddings.
Simplified from multi-model approach - only handles InsightFace embeddings.
"""

import json
import logging
import os
import time
from typing import List, Optional, Dict, Any
from pathlib import Path
import numpy as np

from recognition_core.domain.interfaces import EmbeddingRouterPort
from recognition_core.domain.entities import EmbeddingEntry, MatchResult
from recognition_core.config import get_settings
from roster.config import get_config as get_roster_config

logger = logging.getLogger(__name__)


class EmbeddingRouterAdapter(EmbeddingRouterPort):
    """
    Simplified embedding router that loads InsightFace embeddings from JSON
    and performs cosine similarity matching.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self._embeddings: List[EmbeddingEntry] = []
        self._last_mtime: Optional[float] = None
        self._last_reload: float = 0
        
    async def load_embeddings(self) -> List[EmbeddingEntry]:
        """Load embeddings from the configured JSON file."""
        embeddings_path = self._get_embeddings_path()
        
        if not os.path.exists(embeddings_path):
            logger.warning(f"⚠️ Embeddings file not found: {embeddings_path}")
            return []
        
        try:
            with open(embeddings_path, 'r') as f:
                data = json.load(f)
            
            embeddings = []
            
            # Handle different JSON formats
            if isinstance(data, dict):
                # Format: {"embeddings": [...]} or {"entities": [...]} or single entity dict
                if 'embeddings' in data and isinstance(data['embeddings'], list):
                    entities_data = data['embeddings']
                else:
                    entities_data = data.get('entities', [data] if 'unique_id' in data else [])
            elif isinstance(data, list):
                # Format: [{"unique_id": ...}, ...]
                entities_data = data
            else:
                logger.error(f"❌ Invalid embeddings file format: {embeddings_path}")
                return []
            
            for entity_data in entities_data:
                try:
                    embedding_entry = self._parse_embedding_entry(entity_data)
                    if embedding_entry:
                        embeddings.append(embedding_entry)
                except Exception as e:
                    logger.warning(f"⚠️ Failed to parse embedding entry: {e}")
                    continue
            
            # Update file modification time
            self._last_mtime = os.path.getmtime(embeddings_path)
            self._embeddings = embeddings
            
            logger.info(f"📚 Loaded {len(embeddings)} embeddings from {embeddings_path}")
            return embeddings
            
        except Exception as e:
            logger.error(f"❌ Failed to load embeddings: {e}")
            return []
    
    def _get_embeddings_path(self) -> str:
        """Get the path to the embeddings file."""
        embeddings_file = self.settings.embedding_router.embeddings_file
        candidates = []

        if os.path.isabs(embeddings_file):
            candidates.append(Path(embeddings_file))
        else:
            project_root = Path(__file__).parent.parent.parent
            candidates.append((project_root / embeddings_file.lstrip("/")).resolve())

        # Fallback to roster storage embedding path if configured
        try:
            roster_config = get_roster_config()
            model = self._infer_model_from_path(embeddings_file)
            if model:
                roster_path = Path(roster_config.get_embeddings_file_path(model))
                candidates.append(roster_path)
        except Exception as exc:
            logger.debug(f"⚠️ Unable to resolve roster embedding path fallback: {exc}")

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

        return str(candidates[0])

    def _infer_model_from_path(self, embeddings_file: str) -> Optional[str]:
        """
        Best-effort model inference from embeddings filename.
        Expected patterns like insightface_w600k_embeddings.json.
        """
        basename = os.path.basename(embeddings_file)
        if basename.endswith("_embeddings.json"):
            return basename.replace("_embeddings.json", "")
        if basename.endswith(".json"):
            return basename.replace(".json", "")
        return None
    
    def _parse_embedding_entry(self, entity_data: Dict[str, Any]) -> Optional[EmbeddingEntry]:
        """Parse a single embedding entry from JSON data."""
        try:
            # Extract required fields
            unique_id = entity_data.get('unique_id')
            name = entity_data.get('name')
            
            if not unique_id or not name:
                logger.warning(f"⚠️ Missing required fields in entity: {entity_data}")
                return None
            
            # Extract embedding - could be in different fields
            embedding_data = None
            for field in ['aggregate_embedding', 'embedding', 'embeddings']:
                if field in entity_data and entity_data[field]:
                    embedding_data = entity_data[field]
                    break
            
            if embedding_data is None:
                logger.warning(f"⚠️ No embedding found for entity {unique_id}")
                return None
            
            # Convert to numpy array
            if isinstance(embedding_data, list):
                embedding_array = np.array(embedding_data, dtype=np.float32)
            else:
                logger.warning(f"⚠️ Invalid embedding format for entity {unique_id}")
                return None
            
            # Normalize the embedding
            norm = np.linalg.norm(embedding_array)
            if norm > 0:
                embedding_array = embedding_array / norm
            
            return EmbeddingEntry(
                unique_id=unique_id,
                name=name,
                display_name=entity_data.get('display_name', name),
                aggregate_embedding=embedding_array,
                metadata=entity_data.get('metadata', {})
            )
            
        except Exception as e:
            logger.error(f"❌ Error parsing embedding entry: {e}")
            return None
    
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
        if not self.settings.embedding_router.auto_reload:
            return False
        
        # Check reload interval
        current_time = time.time()
        if (current_time - self._last_reload) < self.settings.embedding_router.reload_interval:
            return False
        
        self._last_reload = current_time
        
        # Check file modification time
        embeddings_path = self._get_embeddings_path()
        
        if not os.path.exists(embeddings_path):
            return False
        
        try:
            current_mtime = os.path.getmtime(embeddings_path)
            
            if self._last_mtime is None or current_mtime > self._last_mtime:
                logger.info("🔄 Embeddings file updated, reloading...")
                await self.load_embeddings()
                return True
                
        except Exception as e:
            logger.warning(f"⚠️ Error checking file modification time: {e}")
        
        return False
    
    def get_loaded_count(self) -> int:
        """Get the number of loaded embeddings."""
        return len(self._embeddings)
    
    def get_loaded_names(self) -> List[str]:
        """Get the names of loaded entities."""
        return [entry.name for entry in self._embeddings]

    def get_embeddings_path(self) -> str:
        """Return the resolved embeddings file path for observability."""
        return self._get_embeddings_path()
