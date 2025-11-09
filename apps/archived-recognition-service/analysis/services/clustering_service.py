"""
Clustering service for grouping similar face embeddings.

Uses DBSCAN or Agglomerative clustering to group unknown faces that likely
belong to the same person. Supports configurable distance thresholds and
generates deterministic cluster IDs.

Related: CONSOLIDATED_FACE_DETECTION_PLAN.md Section 4.2
"""

import hashlib
import logging
from typing import List, Tuple, Optional
from enum import Enum

import numpy as np
from sklearn.cluster import DBSCAN, AgglomerativeClustering
from sklearn.metrics.pairwise import cosine_distances

logger = logging.getLogger(__name__)


class ClusterAlgorithm(str, Enum):
    """Supported clustering algorithms."""
    DBSCAN = "dbscan"
    AGGLOMERATIVE = "agglomerative"


class ClusteringService:
    """
    Service for clustering face embeddings.
    
    Clusters embeddings by cosine similarity to identify groups of faces
    that likely belong to the same person. Useful for cold start scenarios
    where no roster exists yet.
    """
    
    def __init__(
        self,
        algorithm: ClusterAlgorithm = ClusterAlgorithm.DBSCAN,
        distance_threshold: float = 0.6,
        min_samples: int = 2,
        linkage: str = "average"
    ):
        """
        Initialize clustering service.
        
        Args:
            algorithm: Clustering algorithm to use (dbscan or agglomerative)
            distance_threshold: Maximum distance between samples in same cluster
                              (lower = stricter clustering, higher = more permissive)
                              For cosine distance: 0.0 = identical, 2.0 = opposite
                              Typical range: 0.4-0.8
            min_samples: Minimum samples in cluster (DBSCAN only)
            linkage: Linkage method for agglomerative (average, complete, single)
        """
        self.algorithm = algorithm
        self.distance_threshold = distance_threshold
        self.min_samples = min_samples
        self.linkage = linkage
        
    def cluster_embeddings(
        self,
        embeddings: np.ndarray,
    ) -> List[str]:
        """
        Cluster embeddings and return cluster IDs.
        
        Args:
            embeddings: Array of shape (n_samples, n_features)
        
        Returns:
            List of cluster IDs (one per embedding)
            - Clustered faces get: "cluster-{hash}-{label}"
            - Noise points (DBSCAN) get: "cluster-{hash}-noise-{index}"
            - Single embeddings get: "cluster-{hash}-single-0"
        
        Example:
            >>> embeddings = np.array([[0.1, 0.2, ...], [0.1, 0.21, ...], [0.9, 0.8, ...]])
            >>> cluster_ids = service.cluster_embeddings(embeddings)
            >>> cluster_ids
            ['cluster-a1b2c3-0', 'cluster-a1b2c3-0', 'cluster-d4e5f6-1']
        """
        if len(embeddings) == 0:
            return []
        
        if len(embeddings) == 1:
            # Single embedding - create unique cluster ID
            embedding_hash = self._hash_embedding(embeddings[0])
            return [f"cluster-{embedding_hash}-single-0"]
        
        # Normalize embeddings for cosine distance
        embeddings_normalized = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
        
        # Compute pairwise cosine distances
        distances = cosine_distances(embeddings_normalized)
        
        # Run clustering algorithm
        if self.algorithm == ClusterAlgorithm.DBSCAN:
            labels = self._dbscan_cluster(distances)
        else:  # AGGLOMERATIVE
            labels = self._agglomerative_cluster(distances)
        
        # Generate deterministic cluster IDs
        cluster_ids = self._generate_cluster_ids(embeddings, labels)
        
        logger.info(
            f"Clustered {len(embeddings)} embeddings into {len(set(cluster_ids))} groups "
            f"using {self.algorithm.value} (threshold={self.distance_threshold})"
        )
        
        return cluster_ids
    
    def _dbscan_cluster(self, distance_matrix: np.ndarray) -> np.ndarray:
        """
        Run DBSCAN clustering on precomputed distance matrix.
        
        Args:
            distance_matrix: Pairwise distance matrix (n_samples, n_samples)
        
        Returns:
            Array of cluster labels (-1 for noise points)
        """
        dbscan = DBSCAN(
            eps=self.distance_threshold,
            min_samples=self.min_samples,
            metric="precomputed",
        )
        labels = dbscan.fit_predict(distance_matrix)
        
        # Count noise points
        n_noise = np.sum(labels == -1)
        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
        
        logger.debug(
            f"DBSCAN found {n_clusters} clusters and {n_noise} noise points "
            f"(eps={self.distance_threshold}, min_samples={self.min_samples})"
        )
        
        return labels
    
    def _agglomerative_cluster(self, distance_matrix: np.ndarray) -> np.ndarray:
        """
        Run Agglomerative clustering on precomputed distance matrix.
        
        Args:
            distance_matrix: Pairwise distance matrix (n_samples, n_samples)
        
        Returns:
            Array of cluster labels
        """
        agg = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=self.distance_threshold,
            linkage=self.linkage,
            metric="precomputed",
        )
        labels = agg.fit_predict(distance_matrix)
        
        n_clusters = len(set(labels))
        
        logger.debug(
            f"Agglomerative found {n_clusters} clusters "
            f"(threshold={self.distance_threshold}, linkage={self.linkage})"
        )
        
        return labels
    
    def _generate_cluster_ids(
        self,
        embeddings: np.ndarray,
        labels: np.ndarray
    ) -> List[str]:
        """
        Generate deterministic cluster IDs from labels.
        
        Args:
            embeddings: Original embeddings array
            labels: Cluster labels from algorithm (-1 for noise in DBSCAN)
        
        Returns:
            List of cluster ID strings
        """
        cluster_ids = []
        
        for idx, label in enumerate(labels):
            embedding_hash = self._hash_embedding(embeddings[idx])
            
            if label == -1:
                # DBSCAN noise point - unique ID
                cluster_id = f"cluster-{embedding_hash}-noise-{idx}"
            else:
                # Regular cluster - use label
                cluster_id = f"cluster-{embedding_hash[:8]}-{label}"
            
            cluster_ids.append(cluster_id)
        
        return cluster_ids
    
    def _hash_embedding(self, embedding: np.ndarray) -> str:
        """
        Create deterministic hash from embedding.
        
        Args:
            embedding: Single embedding vector
        
        Returns:
            Hex hash string (first 16 chars)
        """
        # Round to 4 decimals for stability
        rounded = np.round(embedding, decimals=4)
        # Convert to bytes and hash
        embedding_bytes = rounded.tobytes()
        hash_obj = hashlib.sha256(embedding_bytes)
        return hash_obj.hexdigest()[:16]
    
    def get_cluster_summary(
        self,
        cluster_ids: List[str]
    ) -> dict:
        """
        Get summary statistics about clustering results.
        
        Args:
            cluster_ids: List of cluster IDs from cluster_embeddings()
        
        Returns:
            Dictionary with cluster statistics
        """
        from collections import Counter
        
        cluster_counts = Counter(cluster_ids)
        
        # Separate noise from clusters
        noise_ids = [cid for cid in cluster_ids if "-noise-" in cid]
        cluster_only_ids = [cid for cid in cluster_ids if "-noise-" not in cid]
        
        unique_clusters = len(set(cluster_only_ids))
        
        return {
            "total_embeddings": len(cluster_ids),
            "num_clusters": unique_clusters,
            "num_noise_points": len(noise_ids),
            "largest_cluster_size": max(cluster_counts.values()) if cluster_counts else 0,
            "smallest_cluster_size": min(cluster_counts.values()) if cluster_counts else 0,
            "avg_cluster_size": len(cluster_ids) / unique_clusters if unique_clusters > 0 else 0,
            "cluster_sizes": dict(cluster_counts),
        }
