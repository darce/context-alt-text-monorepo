"""Typed embedding-model manifest (plain value — no registry service).

Incumbent production value describes InsightFace buffalo_l @ settings dim / l2 / cosine.
Adapters stamp ``FaceDetection.model_id`` from ``model_id``.

The InsightFace name folds the OpenCV runtime into a space token so a
``cv2.warpAffine`` numeric move partitions FIR23-01 rather than silently
re-baselining 512d vectors under a byte-identical id.

Example model_id: ``insightface-buffalo_l+cv5.0@512d/l2/cosine``
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from recognition.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EmbeddingModelManifest:
    """Model provenance for a detection/embedding seam emission.

    Validated at construction (FIR23-03): empty / non-positive fields fail closed
    so adapters cannot stamp a silent garbage ``model_id``.
    """

    framework: str
    name: str
    dimensions: int
    normalization: str
    metric: str

    def __post_init__(self) -> None:
        framework = str(self.framework).strip() if self.framework is not None else ""
        name = str(self.name).strip() if self.name is not None else ""
        normalization = str(self.normalization).strip() if self.normalization is not None else ""
        metric = str(self.metric).strip() if self.metric is not None else ""
        if not framework:
            raise ValueError("EmbeddingModelManifest.framework must be a non-empty string")
        if not name:
            raise ValueError("EmbeddingModelManifest.name must be a non-empty string")
        if not isinstance(self.dimensions, int) or isinstance(self.dimensions, bool) or self.dimensions <= 0:
            raise ValueError(f"EmbeddingModelManifest.dimensions must be a positive int, got {self.dimensions!r}")
        if not normalization:
            raise ValueError("EmbeddingModelManifest.normalization must be a non-empty string")
        if not metric:
            raise ValueError("EmbeddingModelManifest.metric must be a non-empty string")
        # Normalize whitespace so model_id is stable for equal logical inputs.
        object.__setattr__(self, "framework", framework)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "normalization", normalization)
        object.__setattr__(self, "metric", metric)

    @property
    def model_id(self) -> str:
        """Stable identifier stamped onto FaceDetection.model_id."""
        return f"{self.framework}-{self.name}@{self.dimensions}d/{self.normalization}/{self.metric}"


def _opencv_major_minor(version: str) -> str:
    """Stable OpenCV space id: major.minor, not the live wheel patch string.

    A token change is a FIR23-01 space migration and must not ride a silent
    patch/rebuild bump of ``cv2.__version__`` (for example 5.0.0 → 5.0.0.93).
    """
    parts = [part for part in str(version).split(".") if part]
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{parts[0]}.{parts[1]}"
    return str(version)


def _insightface_space_token() -> str:
    """OpenCV major.minor folded into InsightFace ``model_id`` (CVUP1-GR-03).

    buffalo_l alignment runs through ``cv2.warpAffine`` (InsightFace ``norm_crop``).
    That is the same numeric surface whose 4.13→5.0 move forced SFace golden
    regeneration; without this token the incumbent ``model_id`` stays
    byte-identical across the bump and clustering treats old/new 512d vectors
    as co-spatial. Major.minor (not the full ``cv2.__version__``) is the
    intended partition: a patch or wheel rebuild must not fragment the tenant.
    Lazy import keeps the module importable when cv2 is absent in narrow unit
    tests — those tests must not claim a deployed space id.
    """
    import cv2

    return f"cv{_opencv_major_minor(cv2.__version__)}"


def incumbent_embedding_model_manifest() -> EmbeddingModelManifest:
    """Resolve the currently wired production model from recognition settings."""
    settings = get_settings()
    return EmbeddingModelManifest(
        framework="insightface",
        name=f"{settings.insightface.model_name}+{_insightface_space_token()}",
        dimensions=settings.identity_detection.embedding_dimension,
        normalization="l2",
        metric="cosine",
    )


def active_embedding_model_id() -> str:
    """Resolve the runtime embedding space id for the active profile (FIR23-01).

    Fail-closed: returns a non-empty model_id or raises. Single-model tenants
    that already stamp this id see a no-op filter on read paths.
    """
    settings = get_settings()
    if settings.runtime_mode == "test":
        model_id = "stub-detector@test"
    elif settings.face_pipeline.profile == "face_pipeline":
        # Lazy import: keep insightface dark-default free of face_pipeline graph.
        from recognition.infrastructure.embeddings.face_pipeline_adapter import (
            sface_embedding_model_manifest,
        )

        model_id = sface_embedding_model_manifest().model_id
    else:
        model_id = incumbent_embedding_model_manifest().model_id
    if not model_id or not str(model_id).strip():
        raise RuntimeError("active embedding_model unresolved (empty model_id)")
    return str(model_id).strip()


def try_active_embedding_model_id() -> str | None:
    """Return the active space id, or None after logging if resolve fails."""
    try:
        return active_embedding_model_id()
    except (RuntimeError, ImportError, ValueError, AttributeError, OSError) as exc:
        logger.warning("active embedding_model unresolved (FIR23-01): %s", exc)
        return None


__all__ = [
    "EmbeddingModelManifest",
    "active_embedding_model_id",
    "incumbent_embedding_model_manifest",
    "try_active_embedding_model_id",
]
