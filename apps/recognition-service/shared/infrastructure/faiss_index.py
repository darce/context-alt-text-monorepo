from typing import List, Dict, Optional
import logging
import numpy as np
from recognition.utils.face_utils import normalize_vec


class MatchResult:
    """Simple match result for similarity search."""
    def __init__(self, entity_name: str, unique_id: str, similarity_score: float, 
                 metadata: Dict = None, embedding: np.ndarray = None):
        self.entity_name = entity_name
        self.unique_id = unique_id
        self.similarity_score = similarity_score
        self.metadata = metadata or {}
        self.embedding = embedding


class FaissIndex:
    """Infrastructure for similarity search using Faiss with fallback to numpy-based search."""
    
    def __init__(self, index_path: str = None, roster_service=None):
        """
        Initialize the FaissIndex with optional roster service for dynamic updates.
        
        Args:
            index_path: Path to stored Faiss index (not implemented yet)
            roster_service: Service to access roster embeddings
        """
        self.index_path = index_path
        self.roster_service = roster_service
        self.use_faiss = False  # Set to True when actual Faiss is implemented
        
        # Cache for roster embeddings
        self._cached_embeddings = None
        self._cached_metadata = None
        self._cache_valid = False
        
        logging.info("FaissIndex initialized with numpy fallback")

    def search(self, embedding: List[float], k: int) -> List[MatchResult]:
        """
        Search for top-k nearest neighbors to the embedding.
        
        Args:
            embedding: List of floats representing the face embedding
            k: Number of nearest neighbors to retrieve
            
        Returns:
            List of MatchResult objects
        """
        if self.use_faiss:
            return self._search_with_faiss(embedding, k)
        else:
            return self._search_with_numpy(embedding, k)
    
    def _search_with_numpy(self, embedding: List[float], k: int) -> List[MatchResult]:
        """Fallback search using numpy and cosine similarity."""
        # Always obtain the roster_service from DI if not set
        try:
            from api.dependencies import get_roster_service
            roster_service = self.roster_service or get_roster_service()
        except ImportError:
            roster_service = self.roster_service
        if not roster_service:
            logging.warning("[FAISS] No roster service available for search")
            return []
        # Use roster_service for getting embeddings
        self.roster_service = roster_service

        try:
            # Get roster embeddings
            roster_entries = roster_service.get_roster_images()
            logging.info(f"[FAISS] Retrieved {len(roster_entries) if roster_entries else 0} roster entries")
            if not roster_entries:
                logging.debug("No roster entries available for search")
                return []
            
            # Fuse multiple embeddings per entity into a single embedding
            groups = {}
            for entry in roster_entries:
                uid = entry.get('unique_id') or entry.get('name')
                if uid not in groups:
                    groups[uid] = {
                        'entity_name': entry['name'],
                        'metadata': entry.get('metadata', {}).copy(),
                        'embeddings': []
                    }
                # collect normalized embeddings using face_utils helper
                emb_arr = np.array(entry['embedding'], dtype=np.float32)
                groups[uid]['embeddings'].append(normalize_vec(emb_arr))
            # build fused entries list
            fused_entries = []
            for uid, g in groups.items():
                # average embeddings
                stacked = np.stack(g['embeddings'], axis=0)
                fused = np.mean(stacked, axis=0)
                # normalize fused embedding using face_utils helper
                fused = normalize_vec(fused)
                # update metadata with count
                fused_meta = g['metadata']
                fused_meta['fused_count'] = len(g['embeddings'])
                fused_entries.append({'unique_id': uid, 'entity_name': g['entity_name'], 'embedding': fused, 'metadata': fused_meta})

            # Convert query embedding to numpy array and normalize using face_utils helper
            query_embedding = np.array(embedding, dtype=np.float32)
            query_embedding = normalize_vec(query_embedding)

            results = []

            # Compare against fused entity embeddings
            for entry in fused_entries:
                try:
                    ref_embedding = entry['embedding']

                    # Calculate cosine similarity
                    similarity = float(np.dot(query_embedding, ref_embedding))

                    logging.info(f"[FAISS] Similarity to {entry['entity_name']}: {similarity:.4f}")
                    
                    # Create match result
                    match_result = MatchResult(
                        entity_name=entry['entity_name'],
                        unique_id=entry.get('unique_id'),
                        similarity_score=similarity,
                        metadata=entry.get('metadata', {}),
                        embedding=entry['embedding']
                    )
                    results.append(match_result)
                    
                except Exception as e:
                    logging.error(f"Error processing roster entry {entry.get('entity_name', 'unknown')}: {e}")
                    continue
            
            # Sort by similarity (descending) and return top-k
            results.sort(key=lambda x: x.similarity_score, reverse=True)
            return results[:k]
            
        except Exception as e:
            logging.error(f"Error in numpy-based search: {e}")
            return []
    
    def _search_with_faiss(self, embedding: List[float], k: int) -> List[MatchResult]:
        """Future implementation with actual Faiss library."""
        # TODO: Implement when Faiss is added to dependencies
        raise NotImplementedError("Faiss-based search not yet implemented")
    
    def rebuild_index(self, embeddings: List[List[float]], metadata: List[Dict]):
        """Rebuild the index with new embeddings and metadata."""
        if self.use_faiss:
            self._rebuild_faiss_index(embeddings, metadata)
        else:
            # For numpy fallback, we just invalidate the cache
            # The roster service will be queried fresh on next search
            self._cache_valid = False
            logging.info("Index rebuild completed (numpy fallback)")
    
    def _rebuild_faiss_index(self, embeddings: List[List[float]], metadata: List[Dict]):
        """Future implementation for rebuilding actual Faiss index."""
        # TODO: Implement when Faiss is added
        pass
