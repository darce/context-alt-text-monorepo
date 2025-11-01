"""Tests for HybridIndexManager (FAISS + database synchronization)."""

import numpy as np
import pytest

from recognition_core.services.hybrid_index_manager import HybridIndexManager
from roster.domain.entities import RosterEntry, RosterImage


class MockStorageAdapter:
    """Mock storage adapter for testing."""
    
    def __init__(self):
        self.entries = []
    
    def load_roster_entries(self, model: str):
        """Return mock roster entries with embeddings."""
        return self.entries
    
    def add_entry(self, name: str, embedding: list):
        """Helper to add test entries with reference images."""
        # Create a reference image with the embedding
        ref_image = RosterImage(
            embedding=embedding,
            metadata={"source": "test"}
        )
        
        entry = RosterEntry(
            name=name,
            unique_id=f"test-{len(self.entries)}",
            reference_images=[ref_image],  # Provide reference images so aggregate is computed
            metadata={"type": "person"}
        )
        self.entries.append(entry)


@pytest.mark.asyncio
async def test_hybrid_manager_rebuild_from_database():
    """Test that manager rebuilds FAISS index from database."""
    storage = MockStorageAdapter()
    
    # Add test entries
    storage.add_entry("Alice", [0.5] * 512)
    storage.add_entry("Bob", [0.3] * 512)
    storage.add_entry("Charlie", [0.7] * 512)
    
    manager = HybridIndexManager(storage, auto_reload=False)
    
    # Rebuild index
    count = await manager.rebuild_index()
    
    assert count == 3
    assert len(manager._embeddings) == 3
    
    # Check stats
    stats = manager.get_stats()
    assert stats["entry_count"] == 3
    assert stats["embedding_count"] == 3
    assert stats["source"] == "database"
    assert stats["duration_ms"] > 0


@pytest.mark.asyncio
async def test_hybrid_manager_search():
    """Test cosine similarity search."""
    storage = MockStorageAdapter()
    
    # Create normalized embeddings
    alice_emb = np.random.randn(512).astype(np.float32)
    alice_emb = alice_emb / np.linalg.norm(alice_emb)
    
    bob_emb = np.random.randn(512).astype(np.float32)
    bob_emb = bob_emb / np.linalg.norm(bob_emb)
    
    storage.add_entry("Alice", alice_emb.tolist())
    storage.add_entry("Bob", bob_emb.tolist())
    
    manager = HybridIndexManager(storage, auto_reload=False)
    await manager.rebuild_index()
    
    # Search with Alice's embedding (should match herself)
    results = await manager.search(alice_emb, top_k=2, threshold=0.5)
    
    assert len(results) >= 1
    assert results[0]["label"] == "Alice"
    assert results[0]["score"] > 0.99  # Should be almost perfect match


@pytest.mark.asyncio
async def test_hybrid_manager_empty_index():
    """Test handling of empty database."""
    storage = MockStorageAdapter()
    manager = HybridIndexManager(storage, auto_reload=False)
    
    # Rebuild with no entries
    count = await manager.rebuild_index()
    
    assert count == 0
    assert len(manager._embeddings) == 0
    
    # Search should return empty
    query = np.random.randn(512).astype(np.float32)
    results = await manager.search(query, top_k=5)
    
    assert len(results) == 0


@pytest.mark.asyncio
async def test_hybrid_manager_auto_reload():
    """Test automatic reload on first access."""
    storage = MockStorageAdapter()
    storage.add_entry("Test", [0.5] * 512)
    
    manager = HybridIndexManager(storage, auto_reload=True, reload_interval=0)
    
    # First maybe_reload should trigger rebuild
    reloaded = await manager.maybe_reload()
    
    assert reloaded is True
    assert len(manager._embeddings) == 1


@pytest.mark.asyncio
async def test_hybrid_manager_threshold_filtering():
    """Test that search respects similarity threshold."""
    storage = MockStorageAdapter()
    
    # Create orthogonal embeddings (low similarity)
    emb1 = np.zeros(512, dtype=np.float32)
    emb1[0] = 1.0  # [1, 0, 0, ...]
    
    emb2 = np.zeros(512, dtype=np.float32)
    emb2[1] = 1.0  # [0, 1, 0, ...]
    
    storage.add_entry("Person1", emb1.tolist())
    storage.add_entry("Person2", emb2.tolist())
    
    manager = HybridIndexManager(storage, auto_reload=False)
    await manager.rebuild_index()
    
    # Search with emb1, high threshold should exclude emb2
    results = await manager.search(emb1, top_k=10, threshold=0.9)
    
    assert len(results) == 1
    assert results[0]["label"] == "Person1"
