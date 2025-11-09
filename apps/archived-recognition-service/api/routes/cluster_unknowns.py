"""
Clustering endpoint for grouping unknown faces.

POST /api/v0/cluster-unknowns - Groups similar face embeddings using DBSCAN or
Agglomerative clustering. Used in cold start scenarios to identify faces that
likely belong to the same person.

Related: CONSOLIDATED_FACE_DETECTION_PLAN.md Section 4.2
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, validator
import numpy as np

from analysis.services.clustering_service import ClusteringService, ClusterAlgorithm

logger = logging.getLogger(__name__)

router = APIRouter()


class ClusterRequest(BaseModel):
    """Request payload for /cluster-unknowns endpoint."""
    
    embeddings: List[List[float]] = Field(
        ...,
        description="Array of face embeddings (512-dim vectors)",
        min_items=1,
    )
    algorithm: Optional[ClusterAlgorithm] = Field(
        default=ClusterAlgorithm.DBSCAN,
        description="Clustering algorithm (dbscan or agglomerative)",
    )
    distanceThreshold: Optional[float] = Field(
        default=0.6,
        ge=0.0,
        le=2.0,
        description="Maximum distance between samples in cluster (cosine distance, 0-2)",
    )
    minSamples: Optional[int] = Field(
        default=2,
        ge=1,
        le=10,
        description="Minimum samples in cluster (DBSCAN only)",
    )
    linkage: Optional[str] = Field(
        default="average",
        description="Linkage method for agglomerative (average, complete, single)",
    )
    
    @validator("embeddings")
    def validate_embedding_dimensions(cls, v: List[List[float]]) -> List[List[float]]:
        """Ensure all embeddings are 512-dimensional."""
        for idx, emb in enumerate(v):
            if len(emb) != 512:
                raise ValueError(
                    f"Embedding at index {idx} has {len(emb)} dimensions, expected 512"
                )
        return v
    
    @validator("linkage")
    def validate_linkage(cls, v: str) -> str:
        """Ensure linkage method is valid."""
        valid_linkage = ["average", "complete", "single"]
        if v not in valid_linkage:
            raise ValueError(
                f"Invalid linkage '{v}', must be one of: {', '.join(valid_linkage)}"
            )
        return v


class ClusterResponse(BaseModel):
    """Response payload for /cluster-unknowns endpoint."""
    
    clusterIds: List[str] = Field(
        ...,
        description="Array of cluster IDs (one per input embedding)",
    )
    summary: dict = Field(
        ...,
        description="Summary statistics about clustering results",
    )


@router.post("/cluster-unknowns", response_model=ClusterResponse)
async def cluster_unknown_faces(
    request: ClusterRequest,
) -> ClusterResponse:
    """
    Cluster unknown face embeddings by similarity.
    
    Groups embeddings that likely belong to the same person using density-based
    or hierarchical clustering. Returns deterministic cluster IDs that can be
    used to group faces in the UI.
    
    **Workflow:**
    1. Normalize embeddings (L2 norm)
    2. Compute pairwise cosine distances
    3. Run clustering algorithm (DBSCAN or Agglomerative)
    4. Generate deterministic cluster IDs
    5. Return cluster IDs and summary stats
    
    **Example Request:**
    ```json
    {
      "embeddings": [[0.1, 0.2, ...], [0.1, 0.21, ...], [0.9, 0.8, ...]],
      "algorithm": "dbscan",
      "distanceThreshold": 0.6,
      "minSamples": 2
    }
    ```
    
    **Example Response:**
    ```json
    {
      "clusterIds": [
        "cluster-a1b2c3d4-0",
        "cluster-a1b2c3d4-0",
        "cluster-e5f6g7h8-1"
      ],
      "summary": {
        "total_embeddings": 3,
        "num_clusters": 2,
        "num_noise_points": 0,
        "largest_cluster_size": 2,
        "smallest_cluster_size": 1,
        "avg_cluster_size": 1.5
      }
    }
    ```
    
    **Cluster ID Format:**
    - Regular cluster: `cluster-{hash}-{label}` (e.g., `cluster-a1b2c3d4-0`)
    - Noise point (DBSCAN): `cluster-{hash}-noise-{index}` (e.g., `cluster-a1b2c3d4-noise-5`)
    - Single embedding: `cluster-{hash}-single-0` (e.g., `cluster-a1b2c3d4-single-0`)
    
    **Algorithm Selection:**
    - **DBSCAN:** Better for finding dense regions, handles noise, requires tuning `minSamples`
    - **Agglomerative:** More consistent, no noise points, simpler to tune
    
    **Distance Threshold Guide:**
    - 0.4-0.5: Very strict (same person, similar pose/lighting)
    - 0.6-0.7: Moderate (same person, different conditions) **← Recommended**
    - 0.8-1.0: Permissive (may group different people)
    """
    try:
        # Convert embeddings to numpy array
        embeddings_array = np.array(request.embeddings, dtype=np.float32)
        
        logger.info(
            f"Clustering {len(request.embeddings)} embeddings using {request.algorithm.value} "
            f"(threshold={request.distanceThreshold}, minSamples={request.minSamples})"
        )
        
        # Initialize clustering service
        clustering_service = ClusteringService(
            algorithm=request.algorithm,
            distance_threshold=request.distanceThreshold,
            min_samples=request.minSamples,
            linkage=request.linkage,
        )
        
        # Perform clustering
        cluster_ids = clustering_service.cluster_embeddings(embeddings_array)
        
        # Get summary statistics
        summary = clustering_service.get_cluster_summary(cluster_ids)
        
        logger.info(
            f"Clustering complete: {summary['num_clusters']} clusters, "
            f"{summary['num_noise_points']} noise points"
        )
        
        return ClusterResponse(
            clusterIds=cluster_ids,
            summary=summary,
        )
    
    except ValueError as e:
        logger.error(f"Validation error in cluster-unknowns endpoint: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    
    except Exception as e:
        logger.error(f"Error in cluster-unknowns endpoint: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error during clustering"
        )
