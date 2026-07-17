"""Typed embedding-model manifest (plain value — no registry service).

Incumbent production value describes InsightFace buffalo_l @ settings dim / l2 / cosine.
Adapters stamp ``FaceDetection.model_id`` from ``model_id``.
"""

from __future__ import annotations

from dataclasses import dataclass

from recognition.config import get_settings


@dataclass(frozen=True, slots=True)
class EmbeddingModelManifest:
    """Model provenance for a detection/embedding seam emission."""

    name: str
    version: str
    dimensions: int
    normalization: str
    metric: str

    @property
    def model_id(self) -> str:
        """Stable identifier stamped onto FaceDetection.model_id."""
        return f"{self.name}@{self.version}"


def incumbent_embedding_model_manifest() -> EmbeddingModelManifest:
    """Resolve the currently wired production model from recognition settings."""
    settings = get_settings()
    return EmbeddingModelManifest(
        name=settings.insightface.model_name,
        version="insightface",
        dimensions=settings.identity_detection.embedding_dimension,
        normalization="l2",
        metric="cosine",
    )


__all__ = [
    "EmbeddingModelManifest",
    "incumbent_embedding_model_manifest",
]
