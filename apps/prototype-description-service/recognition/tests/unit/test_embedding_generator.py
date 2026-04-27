"""TDD tests for embedding generator adapter.

Tests cover:
- StubEmbeddingGenerator: Deterministic hash-based embeddings for tests
- EmbeddingGeneratorProtocol: Interface contract verification
- InsightFaceEmbeddingGenerator: Real embeddings (with mocked adapter)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from recognition.application.embedding.generator import (
    EmbeddingGenerator,
    EmbeddingGeneratorProtocol,
    EmbeddingTimeoutError,
    InsightFaceEmbeddingGenerator,
    StubEmbeddingGenerator,
)
import recognition.application.embedding.generator as generator_module
from recognition.infrastructure.embeddings import DetectedFace, InsightFaceAdapter


class TestStubEmbeddingGenerator:
    """Tests for the deterministic stub generator."""

    @pytest.mark.asyncio
    async def test_outputs_expected_dimension(self) -> None:
        """Embeddings should match the configured dimensionality."""
        generator = StubEmbeddingGenerator(embedding_dim=512)

        results = await generator.generate([b"face-1"])

        assert len(results) == 1
        assert results[0].embedding.shape[0] == 512
        assert results[0].confidence >= 0

    @pytest.mark.asyncio
    async def test_embeddings_are_normalized(self) -> None:
        """Embeddings should be unit-length vectors."""
        generator = StubEmbeddingGenerator(embedding_dim=512)

        results = await generator.generate([b"face-1", b"face-2"])

        for result in results:
            norm = float(np.linalg.norm(result.embedding))
            assert np.isclose(norm, 1.0, atol=1e-3)

    @pytest.mark.asyncio
    async def test_embeddings_are_deterministic(self) -> None:
        """Same input should produce same embedding (hash-based)."""
        generator = StubEmbeddingGenerator(embedding_dim=512)
        face_bytes = b"test-face-crop"

        result1 = await generator.generate([face_bytes])
        result2 = await generator.generate([face_bytes])

        np.testing.assert_array_equal(result1[0].embedding, result2[0].embedding)

    @pytest.mark.asyncio
    async def test_different_inputs_produce_different_embeddings(self) -> None:
        """Different inputs should produce different embeddings."""
        generator = StubEmbeddingGenerator(embedding_dim=512)

        result1 = await generator.generate([b"face-a"])
        result2 = await generator.generate([b"face-b"])

        # Embeddings should differ
        assert not np.allclose(result1[0].embedding, result2[0].embedding)

    @pytest.mark.asyncio
    async def test_handles_multiple_faces(self) -> None:
        """Should generate embeddings for multiple face crops."""
        generator = StubEmbeddingGenerator(embedding_dim=512)

        results = await generator.generate([b"face-1", b"face-2", b"face-3"])

        assert len(results) == 3
        for result in results:
            assert result.embedding.shape[0] == 512

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

    @pytest.fixture
    def mock_adapter(self) -> MagicMock:
        adapter = MagicMock(spec=InsightFaceAdapter)

        # Helper to create fake detected faces
        def create_face(confidence: float = 0.99, embedding_dim: int = 512) -> DetectedFace:
            # Note: We don't populate bbox/pose/etc for these tests as they aren't used by generator
            return DetectedFace(
                bbox=(0, 0, 100, 100),
                confidence=confidence,
                embedding_512=np.random.rand(embedding_dim).astype(np.float32),
                pose=None,
                age=None,
                gender=None,
                landmarks=None,
            )

        # Default behavior: return one face per call
        adapter.analyze.return_value = [create_face()]
        return adapter

    @pytest.mark.asyncio
    async def test_calls_adapter_analyze(self, mock_adapter: MagicMock) -> None:
        """Should call adapter.analyze for each image."""
        mock_face = mock_adapter.analyze.return_value[0]
        # Explicitly set mock attributes to ensure we assert on the right values
        expected_embedding = np.random.randn(512).astype(np.float32)
        mock_face.embedding_512 = expected_embedding
        mock_face.confidence = 0.92

        generator = InsightFaceEmbeddingGenerator(mock_adapter)
        results = await generator.generate([b"real-face-image"])

        mock_adapter.analyze.assert_called_once()
        assert len(results) == 1
        np.testing.assert_array_equal(results[0].embedding, expected_embedding)
        assert results[0].confidence == 0.92

    @pytest.mark.asyncio
    async def test_handles_multiple_faces_per_image(self, mock_adapter: MagicMock) -> None:
        """Should return embeddings for all faces found in image."""
        mock_face1 = DetectedFace(
            bbox=(0, 0, 1, 1),
            confidence=0.95,
            embedding_512=np.random.randn(512).astype(np.float32),
            pose=None,
            age=None,
            gender=None,
            landmarks=None,
        )
        mock_face2 = DetectedFace(
            bbox=(0, 0, 1, 1),
            confidence=0.88,
            embedding_512=np.random.randn(512).astype(np.float32),
            pose=None,
            age=None,
            gender=None,
            landmarks=None,
        )
        mock_adapter.analyze = AsyncMock(return_value=[mock_face1, mock_face2])

        generator = InsightFaceEmbeddingGenerator(mock_adapter)
        results = await generator.generate([b"image-with-two-faces"])

        assert len(results) == 2
        assert results[0].confidence == 0.95
        assert results[1].confidence == 0.88
        np.testing.assert_array_equal(results[0].embedding, mock_face1.embedding_512)
        np.testing.assert_array_equal(results[1].embedding, mock_face2.embedding_512)

    @pytest.mark.asyncio
    async def test_handles_adapter_exception_gracefully(self, mock_adapter: MagicMock) -> None:
        """Should log error and continue if adapter raises exception."""
        mock_adapter.analyze = AsyncMock(side_effect=RuntimeError("Model failed"))

        generator = InsightFaceEmbeddingGenerator(mock_adapter)
        results = await generator.generate([b"bad-image"])

        # Should return empty list, not raise
        assert results == []

    @pytest.mark.asyncio
    async def test_times_out_slow_adapter_calls(self) -> None:
        """Should fail fast when the adapter analyze call exceeds the configured timeout."""

        async def slow_analyze(_image_bytes: bytes) -> list[DetectedFace]:
            await asyncio.sleep(0.05)
            return []

        slow_adapter = MagicMock(spec=InsightFaceAdapter)
        slow_adapter.analyze = AsyncMock(side_effect=slow_analyze)

        generator = InsightFaceEmbeddingGenerator(slow_adapter, timeout=0.01)

        with pytest.raises(EmbeddingTimeoutError):
            await generator.generate([b"slow-image"])

    def test_reads_default_timeout_lazily(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default timeout should come from get_database_settings() at construction time."""

        class Settings:
            embedding_timeout_s = 7.5

        monkeypatch.setattr(generator_module, "get_database_settings", lambda: Settings())

        generator = InsightFaceEmbeddingGenerator(MagicMock(spec=InsightFaceAdapter))

        assert generator._timeout == 7.5

    @pytest.mark.asyncio
    async def test_processes_multiple_images(self, mock_adapter: MagicMock) -> None:
        """Should process multiple images sequentially."""
        mock_face = DetectedFace(
            bbox=(0, 0, 1, 1),
            confidence=0.9,
            embedding_512=np.random.randn(512).astype(np.float32),
            pose=None,
            age=None,
            gender=None,
            landmarks=None,
        )

        mock_adapter.analyze = AsyncMock(return_value=[mock_face])

        generator = InsightFaceEmbeddingGenerator(mock_adapter)
        results = await generator.generate([b"img1", b"img2", b"img3"])

        assert mock_adapter.analyze.call_count == 3
        assert len(results) == 3


# Backwards compatibility alias tests
@pytest.mark.asyncio
async def test_embedding_generator_outputs_expected_dimension() -> None:
    """Legacy test: EmbeddingGenerator alias should work."""
    generator = EmbeddingGenerator(embedding_dim=512)

    results = await generator.generate([b"face-1"])

    assert len(results) == 1
    assert results[0].embedding.shape[0] == 512
    assert results[0].confidence >= 0


@pytest.mark.asyncio
async def test_embeddings_are_normalized() -> None:
    """Legacy test: EmbeddingGenerator embeddings should be normalized."""
    generator = EmbeddingGenerator(embedding_dim=512)

    results = await generator.generate([b"face-1", b"face-2"])

    for result in results:
        norm = float(np.linalg.norm(result.embedding))
        assert np.isclose(norm, 1.0, atol=1e-3)
