import numpy as np
import pytest

from recognition_core.adapters.embedding_router_adapter import EmbeddingRouterAdapter
from recognition_core.domain.entities import EmbeddingEntry
from roster.domain.entities import RosterEntry


class StubStorageAdapter:
    """Minimal storage adapter stub for tests."""

    def __init__(self, entries):
        self.entries = entries

    def load_roster_entries(self, model: str):
        return self.entries


@pytest.mark.asyncio
async def test_find_matches_returns_fallback_candidates_when_none_above_threshold():
    storage = StubStorageAdapter(entries=[])
    adapter = EmbeddingRouterAdapter(storage_adapter=storage)
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


@pytest.mark.asyncio
async def test_load_embeddings_records_reload_stats():
    roster_entry = RosterEntry(
        name="Test User",
        unique_id="test-1",
        reference_images=[],
        aggregate_embedding=[1.0, 0.0],
        metadata={},
    )
    storage = StubStorageAdapter(entries=[roster_entry])
    adapter = EmbeddingRouterAdapter(storage_adapter=storage)

    embeddings = await adapter.load_embeddings()
    stats = adapter.get_reload_stats()

    assert len(embeddings) == 1
    assert stats["entry_count"] == 1
    assert stats["embedding_count"] == 1
    assert stats["duration_ms"] >= 0.0
