"""TDD tests for embedding generator adapter.

Tests cover:
- StubEmbeddingGenerator: Deterministic hash-based embeddings for tests
- EmbeddingGeneratorProtocol: Interface contract verification
- InsightFaceEmbeddingGenerator: Real embeddings (with mocked adapter)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from recognition.application.embedding.generator import (
    EmbeddingGenerator,
    EmbeddingGeneratorProtocol,
    InsightFaceEmbeddingGenerator,
    StubEmbeddingGenerator,
)


class TestStubEmbeddingGenerator:
    """Tests for the deterministic stub generator."""

    @pytest.mark.asyncio
    async def test_outputs_expected_dimension(self) -> None:
        """Embeddings should match the configured dimensionality."""
        generator = StubEmbeddingGenerator(embedding_dim=1024)

        results = await generator.generate([b"face-1"])

        assert len(results) == 1
        assert results[0].embedding.shape[0] == 1024
        assert results[0].confidence >= 0

    @pytest.mark.asyncio
    async def test_embeddings_are_normalized(self) -> None:
        """Embeddings should be unit-length vectors."""
        generator = StubEmbeddingGenerator(embedding_dim=1024)

        results = await generator.generate([b"face-1", b"face-2"])

        for result in results:
            norm = float(np.linalg.norm(result.embedding))
            assert np.isclose(norm, 1.0, atol=1e-3)

    @pytest.mark.asyncio
    async def test_embeddings_are_deterministic(self) -> None:
        """Same input should produce same embedding (hash-based)."""
        generator = StubEmbeddingGenerator(embedding_dim=1024)
        face_bytes = b"test-face-crop"

        result1 = await generator.generate([face_bytes])
        result2 = await generator.generate([face_bytes])

        np.testing.assert_array_equal(result1[0].embedding, result2[0].embedding)

    @pytest.mark.asyncio
    async def test_different_inputs_produce_different_embeddings(self) -> None:
        """Different inputs should produce different embeddings."""
        generator = StubEmbeddingGenerator(embedding_dim=1024)

        result1 = await generator.generate([b"face-a"])
        result2 = await generator.generate([b"face-b"])

        # Embeddings should differ
        assert not np.allclose(result1[0].embedding, result2[0].embedding)

    @pytest.mark.asyncio
    async def test_handles_multiple_faces(self) -> None:
        """Should generate embeddings for multiple face crops."""
        generator = StubEmbeddingGenerator(embedding_dim=1024)

        results = await generator.generate([b"face-1", b"face-2", b"face-3"])

        assert len(results) == 3
        for result in results:
            assert result.embedding.shape[0] == 1024

    @pytest.mark.asyncio
    async def test_respects_custom_dimension(self) -> None:
        """Should respect the configured embedding dimension."""
        generator = StubEmbeddingGenerator(embedding_dim=512)

        results = await generator.generate([b"face"])

        assert results[0].embedding.shape[0] == 512


class TestEmbeddingGeneratorProtocol:
    """Tests verifying protocol compliance."""

    def test_stub_implements_protocol(self) -> None:
        """StubEmbeddingGenerator should implement EmbeddingGeneratorProtocol."""
        generator = StubEmbeddingGenerator()
        assert isinstance(generator, EmbeddingGeneratorProtocol)

    def test_insightface_implements_protocol(self) -> None:
        """InsightFaceEmbeddingGenerator should implement EmbeddingGeneratorProtocol."""
        mock_adapter = MagicMock()
        generator = InsightFaceEmbeddingGenerator(mock_adapter)
        assert isinstance(generator, EmbeddingGeneratorProtocol)


class TestInsightFaceEmbeddingGenerator:
    """Tests for InsightFace-backed generator (with mocked adapter)."""

    @pytest.mark.asyncio
    async def test_calls_adapter_analyze(self) -> None:
        """Should call adapter.analyze for each image."""
        mock_adapter = MagicMock()
        mock_face = MagicMock(confidence=0.92)
        mock_embedding = np.random.randn(1024).astype(np.float32)
        mock_adapter.analyze = AsyncMock(return_value=[(mock_face, mock_embedding)])

        generator = InsightFaceEmbeddingGenerator(mock_adapter)
        results = await generator.generate([b"real-face-image"])

        mock_adapter.analyze.assert_called_once()
        assert len(results) == 1
        np.testing.assert_array_equal(results[0].embedding, mock_embedding)
        assert results[0].confidence == 0.92

    @pytest.mark.asyncio
    async def test_handles_multiple_faces_per_image(self) -> None:
        """Should return embeddings for all faces found in image."""
        mock_adapter = MagicMock()
        mock_face1 = MagicMock(confidence=0.95)
        mock_face2 = MagicMock(confidence=0.88)
        mock_emb1 = np.random.randn(1024).astype(np.float32)
        mock_emb2 = np.random.randn(1024).astype(np.float32)
        mock_adapter.analyze = AsyncMock(return_value=[(mock_face1, mock_emb1), (mock_face2, mock_emb2)])

        generator = InsightFaceEmbeddingGenerator(mock_adapter)
        results = await generator.generate([b"image-with-two-faces"])

        assert len(results) == 2
        assert results[0].confidence == 0.95
        assert results[1].confidence == 0.88

    @pytest.mark.asyncio
    async def test_handles_adapter_exception_gracefully(self) -> None:
        """Should log error and continue if adapter raises exception."""
        mock_adapter = MagicMock()
        mock_adapter.analyze = AsyncMock(side_effect=RuntimeError("Model failed"))

        generator = InsightFaceEmbeddingGenerator(mock_adapter)
        results = await generator.generate([b"bad-image"])

        # Should return empty list, not raise
        assert results == []

    @pytest.mark.asyncio
    async def test_processes_multiple_images(self) -> None:
        """Should process multiple images sequentially."""
        mock_adapter = MagicMock()
        mock_face = MagicMock(confidence=0.9)
        mock_emb = np.random.randn(1024).astype(np.float32)
        mock_adapter.analyze = AsyncMock(return_value=[(mock_face, mock_emb)])

        generator = InsightFaceEmbeddingGenerator(mock_adapter)
        results = await generator.generate([b"img1", b"img2", b"img3"])

        assert mock_adapter.analyze.call_count == 3
        assert len(results) == 3


# Backwards compatibility alias tests
@pytest.mark.asyncio
async def test_embedding_generator_outputs_expected_dimension() -> None:
    """Legacy test: EmbeddingGenerator alias should work."""
    generator = EmbeddingGenerator(embedding_dim=1024)

    results = await generator.generate([b"face-1"])

    assert len(results) == 1
    assert results[0].embedding.shape[0] == 1024
    assert results[0].confidence >= 0


@pytest.mark.asyncio
async def test_embeddings_are_normalized() -> None:
    """Legacy test: EmbeddingGenerator embeddings should be normalized."""
    generator = EmbeddingGenerator(embedding_dim=1024)

    results = await generator.generate([b"face-1", b"face-2"])

    for result in results:
        norm = float(np.linalg.norm(result.embedding))
        assert np.isclose(norm, 1.0, atol=1e-3)
