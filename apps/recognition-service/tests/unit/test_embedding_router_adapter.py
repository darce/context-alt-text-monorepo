import numpy as np
import pytest

from recognition_core.adapters.embedding_router_adapter import EmbeddingRouterAdapter
from recognition_core.domain.entities import EmbeddingEntry


@pytest.mark.asyncio
async def test_find_matches_returns_fallback_candidates_when_none_above_threshold():
    adapter = EmbeddingRouterAdapter()
    adapter._embeddings = [
        EmbeddingEntry(
            unique_id="fallback-1",
            name="Fallback User",
            display_name="Fallback User",
            aggregate_embedding=np.array([1.0, 0.0], dtype=np.float32),
            metadata={},
        )
    ]

    query = np.array([1.0, 0.0], dtype=np.float32)
    matches = await adapter.find_matches(query_embedding=query, threshold=1.1)

    assert len(matches) == 1
    match = matches[0]
    assert match.entry.unique_id == "fallback-1"
    assert match.is_match is False
    assert pytest.approx(match.similarity, rel=1e-5) == 1.0
