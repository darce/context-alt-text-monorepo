"""
Embedding generator adapter interface.

This module provides the EmbeddingGenerator interface and implementations:
- StubEmbeddingGenerator: Deterministic stub for tests (hash-based)
- InsightFaceEmbeddingGenerator: Real embedding using InsightFace

The ScanService depends on this interface for embedding generation.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from db.settings import get_database_settings

if TYPE_CHECKING:
    from recognition.infrastructure.embeddings import InsightFaceAdapter

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingResult:
    """Embedding output for a detected face."""

    media_id: str
    embedding: np.ndarray
    confidence: float


class EmbeddingTimeoutError(TimeoutError):
    """Raised when the embedding adapter exceeds the configured deadline."""

    def __init__(self, media_id: str, timeout_s: float) -> None:
        super().__init__(f"Embedding generation timed out for {media_id[:20]} after {timeout_s:.2f}s")
        self.media_id = media_id
        self.timeout_s = timeout_s


class EmbeddingGeneratorProtocol(ABC):
    """Protocol for embedding generation adapters."""

    @abstractmethod
    async def generate(self, face_images: Iterable[bytes]) -> list[EmbeddingResult]:
        """Generate embeddings for provided face crops.

        Args:
            face_images: Iterable of face image byte payloads.

        Returns:
            List of embedding results with vectors and confidence scores.
        """
        ...


class StubEmbeddingGenerator(EmbeddingGeneratorProtocol):
    """Deterministic stub generator for tests - generates fake embeddings from hashes."""

    def __init__(self, embedding_dim: int = 512) -> None:
        self.embedding_dim = embedding_dim

    async def generate(self, face_images: Iterable[bytes]) -> list[EmbeddingResult]:
        """Return deterministic fake embeddings based on input hashes."""
        results: list[EmbeddingResult] = []
        for image in face_images:
            seed = hashlib.sha256(image).digest()
            vector = np.frombuffer(seed * ((self.embedding_dim // len(seed)) + 1), dtype=np.uint8)[
                : self.embedding_dim
            ].astype(np.float32)
            norm = float(np.linalg.norm(vector))
            embedding = vector / norm if norm else vector
            confidence = 0.99
            results.append(
                EmbeddingResult(
                    media_id=hashlib.md5(image).hexdigest(),  # nosec - deterministic test seed
                    embedding=embedding,
                    confidence=confidence,
                )
            )
        return results


class InsightFaceEmbeddingGenerator(EmbeddingGeneratorProtocol):
    """Real embedding generator using InsightFace."""

    def __init__(
        self,
        adapter: InsightFaceAdapter,
        embedding_dim: int = 512,
        timeout: float | None = None,
    ) -> None:
        self._adapter = adapter
        self.embedding_dim = embedding_dim
        self._timeout = timeout if timeout is not None else get_database_settings().embedding_timeout_s

    async def generate(self, face_images: Iterable[bytes]) -> list[EmbeddingResult]:
        """Generate real embeddings using InsightFace.

        Note: This method expects raw image bytes. For each image, it runs
        full detection + embedding. For efficiency, use InsightFaceAdapter.analyze()
        directly when you have already detected faces.
        """
        results: list[EmbeddingResult] = []

        for image_bytes in face_images:
            media_id = hashlib.sha256(image_bytes).hexdigest()

            try:
                # Run detection and embedding in one pass
                face_results = await asyncio.wait_for(
                    self._adapter.analyze(image_bytes),
                    timeout=self._timeout,
                )

                for _face in face_results:
                    results.append(
                        EmbeddingResult(
                            media_id=media_id,
                            embedding=_face.embedding_512,  # Use 512D embedding
                            confidence=_face.confidence,
                        )
                    )
            except TimeoutError as exc:
                logger.error(
                    "Embedding generation timed out for %s after %.2fs",
                    media_id[:20],
                    self._timeout,
                )
                raise EmbeddingTimeoutError(media_id=media_id, timeout_s=self._timeout) from exc
            except Exception as e:
                logger.error("Embedding generation failed for %s: %s", media_id[:20], e)

        return results


# Backwards compatibility alias - defaults to stub
class EmbeddingGenerator(StubEmbeddingGenerator):
    """Default embedding generator (stub for backwards compatibility)."""

    pass


__all__ = [
    "EmbeddingTimeoutError",
    "EmbeddingGeneratorProtocol",
    "StubEmbeddingGenerator",
    "InsightFaceEmbeddingGenerator",
    "EmbeddingGenerator",
]
