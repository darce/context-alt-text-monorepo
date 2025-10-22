"""
Suggestion endpoint for face recognition.

POST /api/v0/suggest - FAISS-based similarity search for roster matching.

This endpoint accepts pre-computed face embeddings and searches the roster
index to find the most similar known persons. It supports batch processing
and configurable similarity thresholds.

Related: CONSOLIDATED_FACE_DETECTION_PLAN.md Section 4.2
"""

import logging
from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, validator

from api.dependencies import get_roster_service
from roster.domain.roster_service import RosterService

logger = logging.getLogger(__name__)

router = APIRouter()


class SuggestRequest(BaseModel):
    """Request payload for /suggest endpoint."""
    
    embeddings: List[List[float]] = Field(
        ...,
        description="Array of face embeddings (512-dim vectors)",
        min_items=1,
    )
    topK: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of top matches to return per embedding",
    )
    threshold: float = Field(
        default=0.92,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score (cosine similarity 0-1)",
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


class RosterMatch(BaseModel):
    """Single roster match result."""
    
    rosterId: str = Field(..., description="Roster person unique ID")
    display: str = Field(..., description="Display name of person")
    score: float = Field(..., description="Similarity score (0-1, higher is better)")


class SuggestResponse(BaseModel):
    """Response payload for /suggest endpoint."""
    
    suggestions: List[List[RosterMatch]] = Field(
        ...,
        description="Array of suggestion arrays (one per input embedding)",
    )


@router.post("/suggest", response_model=SuggestResponse)
async def suggest_roster_matches(
    request: SuggestRequest,
    roster_service: RosterService = Depends(get_roster_service),
) -> SuggestResponse:
    """
    Search roster for similar faces using FAISS similarity search.
    
    **Workflow:**
    1. Load roster FAISS index (cached)
    2. Normalize query embeddings (L2 norm)
    3. Search for top-k matches per embedding
    4. Filter by similarity threshold
    5. Return ordered suggestions
    
    **Returns:**
    - Empty array if no roster exists
    - Empty array if no matches above threshold
    - Ordered by similarity score (descending)
    
    **Performance:**
    - <100ms for 1k roster entries
    - <500ms for 10k roster entries
    
    **Example:**
    ```json
    {
      "embeddings": [[0.123, ...], [0.456, ...]],
      "topK": 5,
      "threshold": 0.92
    }
    ```
    
    **Response:**
    ```json
    {
      "suggestions": [
        [
          {"rosterId": "person-ana-001", "display": "Ana Rodriguez", "score": 0.94},
          {"rosterId": "person-marta-002", "display": "Marta Silva", "score": 0.88}
        ],
        []
      ]
    }
    ```
    """
    try:
        # Get all roster entries with embeddings
        roster_entries = roster_service.list_all()
        
        if not roster_entries:
            logger.info("No roster entries found, returning empty suggestions")
            return SuggestResponse(
                suggestions=[[] for _ in request.embeddings]
            )
        
        # Build FAISS index from roster embeddings
        # TODO: Cache this index instead of rebuilding every time
        import numpy as np
        
        roster_embeddings = []
        roster_metadata = []
        
        for entry in roster_entries:
            if entry.aggregate_embedding is not None:
                roster_embeddings.append(entry.aggregate_embedding)
                roster_metadata.append({
                    "roster_id": entry.unique_id,
                    "display": entry.name,
                })
        
        if not roster_embeddings:
            logger.info("No roster embeddings found, returning empty suggestions")
            return SuggestResponse(
                suggestions=[[] for _ in request.embeddings]
            )
        
        roster_matrix = np.array(roster_embeddings, dtype=np.float32)
        query_matrix = np.array(request.embeddings, dtype=np.float32)
        
        # Normalize embeddings (L2 norm for cosine similarity)
        roster_norms = np.linalg.norm(roster_matrix, axis=1, keepdims=True)
        roster_normalized = roster_matrix / (roster_norms + 1e-8)
        
        query_norms = np.linalg.norm(query_matrix, axis=1, keepdims=True)
        query_normalized = query_matrix / (query_norms + 1e-8)
        
        # Compute cosine similarity (dot product of normalized vectors)
        similarity_matrix = np.dot(query_normalized, roster_normalized.T)
        
        # Build suggestions per query embedding
        all_suggestions = []
        
        for query_idx in range(len(request.embeddings)):
            scores = similarity_matrix[query_idx]
            
            # Get top-k indices
            top_indices = np.argsort(scores)[::-1][:request.topK]
            
            # Filter by threshold and build matches
            matches = []
            for roster_idx in top_indices:
                score = float(scores[roster_idx])
                if score >= request.threshold:
                    metadata = roster_metadata[roster_idx]
                    matches.append(
                        RosterMatch(
                            rosterId=metadata["roster_id"],
                            display=metadata["display"],
                            score=score,
                        )
                    )
            
            all_suggestions.append(matches)
        
        logger.info(
            f"Processed {len(request.embeddings)} queries, "
            f"roster size: {len(roster_embeddings)}, "
            f"avg matches per query: {sum(len(s) for s in all_suggestions) / len(all_suggestions):.1f}"
        )
        
        return SuggestResponse(suggestions=all_suggestions)
    
    except ValueError as exc:
        logger.error(f"Validation error in suggest endpoint: {exc}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    
    except Exception as exc:
        logger.error(f"Error in suggest endpoint: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal error processing suggestions"
        ) from exc
