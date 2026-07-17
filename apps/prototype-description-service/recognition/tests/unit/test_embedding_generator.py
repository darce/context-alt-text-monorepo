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

import recognition.application.embedding.generator as generator_module
from recognition.application.embedding.detector import FaceDetection
from recognition.application.embedding.generator import (
    EmbeddingAdapterError,
    EmbeddingGenerator,
    EmbeddingGeneratorProtocol,
    EmbeddingTimeoutError,
    InsightFaceEmbeddingGenerator,
    StubEmbeddingGenerator,
)
from recognition.application.integrations import AdapterBreakerConfig, AdapterBreakerOpenError, AdapterCircuitBreaker
from recognition.config import get_settings
from recognition.infrastructure.embeddings import InsightFaceAdapter

_EMBEDDING_DIM = get_settings().identity_detection.embedding_dimension


def _face_detection(
    *,
    confidence: float = 0.99,
    embedding_dim: int | None = None,
    embedding: np.ndarray | None = None,
) -> FaceDetection:
    dim = embedding_dim if embedding_dim is not None else _EMBEDDING_DIM
    vector = embedding if embedding is not None else np.random.rand(dim).astype(np.float32)
    return FaceDetection(
        media_id="",
        bbox=(0, 0, 100, 100),
        confidence=confidence,
        embedding=vector,
        pose_pitch=None,
        pose_yaw=None,
        pose_roll=None,
        model_id="buffalo_l@insightface",
    )


class TestStubEmbeddingGenerator:
    """Tests for the deterministic stub generator."""

    @pytest.mark.asyncio
    async def test_outputs_expected_dimension(self) -> None:
        """Embeddings should match the configured dimensionality."""
        generator = StubEmbeddingGenerator(embedding_dim=_EMBEDDING_DIM)

        results = await generator.generate([b"face-1"])

        assert len(results) == 1
        assert results[0].embedding.shape[0] == _EMBEDDING_DIM
        assert results[0].confidence >= 0

    @pytest.mark.asyncio
    async def test_embeddings_are_normalized(self) -> None:
        """Embeddings should be unit-length vectors."""
        generator = StubEmbeddingGenerator(embedding_dim=_EMBEDDING_DIM)

        results = await generator.generate([b"face-1", b"face-2"])

        for result in results:
            norm = float(np.linalg.norm(result.embedding))
            assert np.isclose(norm, 1.0, atol=1e-3)

    @pytest.mark.asyncio
    async def test_embeddings_are_deterministic(self) -> None:
        """Same input should produce same embedding (hash-based)."""
        generator = StubEmbeddingGenerator(embedding_dim=_EMBEDDING_DIM)
        face_bytes = b"test-face-crop"

        result1 = await generator.generate([face_bytes])
        result2 = await generator.generate([face_bytes])

        np.testing.assert_array_equal(result1[0].embedding, result2[0].embedding)

    @pytest.mark.asyncio
    async def test_different_inputs_produce_different_embeddings(self) -> None:
        """Different inputs should produce different embeddings."""
        generator = StubEmbeddingGenerator(embedding_dim=_EMBEDDING_DIM)

        result1 = await generator.generate([b"face-a"])
        result2 = await generator.generate([b"face-b"])

        # Embeddings should differ
        assert not np.allclose(result1[0].embedding, result2[0].embedding)

    @pytest.mark.asyncio
    async def test_handles_multiple_faces(self) -> None:
        """Should generate embeddings for multiple face crops."""
        generator = StubEmbeddingGenerator(embedding_dim=_EMBEDDING_DIM)

        results = await generator.generate([b"face-1", b"face-2", b"face-3"])

        assert len(results) == 3
        for result in results:
            assert result.embedding.shape[0] == _EMBEDDING_DIM

    @pytest.mark.asyncio
    async def test_respects_custom_dimension(self) -> None:
        """Should respect the configured embedding dimension."""
        generator = StubEmbeddingGenerator(embedding_dim=_EMBEDDING_DIM)

        results = await generator.generate([b"face"])

        assert results[0].embedding.shape[0] == _EMBEDDING_DIM

    def test_default_dim_reads_settings(self) -> None:
        """Default embedding_dim comes from recognition settings."""
        generator = StubEmbeddingGenerator()
        assert generator.embedding_dim == _EMBEDDING_DIM


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
        adapter.analyze.return_value = [_face_detection()]
        return adapter

    @pytest.mark.asyncio
    async def test_calls_adapter_analyze(self, mock_adapter: MagicMock) -> None:
        """Should call adapter.analyze for each image."""
        expected_embedding = np.random.randn(_EMBEDDING_DIM).astype(np.float32)
        mock_adapter.analyze = AsyncMock(
            return_value=[_face_detection(confidence=0.92, embedding=expected_embedding)]
        )

        generator = InsightFaceEmbeddingGenerator(mock_adapter)
        results = await generator.generate([b"real-face-image"])

        mock_adapter.analyze.assert_called_once()
        assert len(results) == 1
        np.testing.assert_array_equal(results[0].embedding, expected_embedding)
        assert results[0].confidence == 0.92

    @pytest.mark.asyncio
    async def test_handles_multiple_faces_per_image(self, mock_adapter: MagicMock) -> None:
        """Should return embeddings for all faces found in image."""
        mock_face1 = _face_detection(confidence=0.95)
        mock_face2 = _face_detection(confidence=0.88)
        mock_adapter.analyze = AsyncMock(return_value=[mock_face1, mock_face2])

        generator = InsightFaceEmbeddingGenerator(mock_adapter)
        results = await generator.generate([b"image-with-two-faces"])

        assert len(results) == 2
        assert results[0].confidence == 0.95
        assert results[1].confidence == 0.88
        np.testing.assert_array_equal(results[0].embedding, mock_face1.embedding)
        np.testing.assert_array_equal(results[1].embedding, mock_face2.embedding)

    @pytest.mark.asyncio
    async def test_raises_typed_error_for_adapter_exception(self, mock_adapter: MagicMock) -> None:
        """Generic adapter failures should propagate as typed embedding errors."""
        mock_adapter.analyze = AsyncMock(side_effect=RuntimeError("Model failed"))

        generator = InsightFaceEmbeddingGenerator(mock_adapter)

        with pytest.raises(EmbeddingAdapterError, match="Model failed"):
            await generator.generate([b"bad-image"])

    @pytest.mark.asyncio
    async def test_times_out_slow_adapter_calls(self) -> None:
        """Should fail fast when the adapter analyze call exceeds the configured timeout."""

        async def slow_analyze(_image_bytes: bytes) -> list[FaceDetection]:
            await asyncio.sleep(0.05)
            return []

        slow_adapter = MagicMock(spec=InsightFaceAdapter)
        slow_adapter.analyze = AsyncMock(side_effect=slow_analyze)

        generator = InsightFaceEmbeddingGenerator(slow_adapter, timeout=0.01)

        with pytest.raises(EmbeddingTimeoutError):
            await generator.generate([b"slow-image"])

    @pytest.mark.asyncio
    async def test_fast_fails_when_breaker_is_open(self) -> None:
        """Breaker-open state should surface as a fast failure on the generator seam."""

        breaker = AdapterCircuitBreaker(
            adapter_name="insightface.analyze",
            config=AdapterBreakerConfig(
                failure_count_threshold=1,
                failure_window_seconds=60.0,
                half_open_probe_count=1,
                success_close_threshold=1,
                open_state_cooldown_seconds=30.0,
            ),
        )

        failing_adapter = MagicMock(spec=InsightFaceAdapter)
        failing_adapter.analyze = AsyncMock(side_effect=RuntimeError("Model failed"))
        generator = InsightFaceEmbeddingGenerator(failing_adapter, breaker=breaker)

        with pytest.raises(EmbeddingAdapterError):
            await generator.generate([b"first-image"])

        with pytest.raises(AdapterBreakerOpenError):
            await generator.generate([b"second-image"])

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
        mock_face = _face_detection(confidence=0.9)
        mock_adapter.analyze = AsyncMock(return_value=[mock_face])

        generator = InsightFaceEmbeddingGenerator(mock_adapter)
        results = await generator.generate([b"img1", b"img2", b"img3"])

        assert mock_adapter.analyze.call_count == 3
        assert len(results) == 3


# Backwards compatibility alias tests
@pytest.mark.asyncio
async def test_embedding_generator_outputs_expected_dimension() -> None:
    """Legacy test: EmbeddingGenerator alias should work."""
    generator = EmbeddingGenerator(embedding_dim=_EMBEDDING_DIM)

    results = await generator.generate([b"face-1"])

    assert len(results) == 1
    assert results[0].embedding.shape[0] == _EMBEDDING_DIM
    assert results[0].confidence >= 0


@pytest.mark.asyncio
async def test_embeddings_are_normalized() -> None:
    """Legacy test: EmbeddingGenerator embeddings should be normalized."""
    generator = EmbeddingGenerator(embedding_dim=_EMBEDDING_DIM)

    results = await generator.generate([b"face-1", b"face-2"])

    for result in results:
        norm = float(np.linalg.norm(result.embedding))
        assert np.isclose(norm, 1.0, atol=1e-3)
