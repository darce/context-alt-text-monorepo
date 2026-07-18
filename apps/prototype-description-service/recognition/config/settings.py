"""
Consolidated settings for the recognition service.

All algorithm thresholds and detection parameters are defined here with
type-safe defaults. Override by instantiating with explicit values in code.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from recognition.application.settings import ClusteringSettings
from recognition.application.settings.scan import ScanSettings
from recognition.infrastructure.face_pipeline._common import (
    DEFAULT_NMS_THRESHOLD,
    DEFAULT_SCORE_THRESHOLD,
    DEFAULT_TOP_K,
)
from recognition.infrastructure.face_pipeline.provenance import DEFAULT_MODELS_DIR

_FACE_PIPELINE_PROFILES: frozenset[str] = frozenset({"insightface", "face_pipeline"})


def _resolve_insightface_cache_root() -> Path:
    """Resolve the InsightFace root cache dir from env or the legacy default."""
    explicit_cache_dir = os.environ.get("INSIGHTFACE_CACHE_DIR", "").strip()
    if explicit_cache_dir:
        return Path(explicit_cache_dir)

    explicit_home = os.environ.get("INSIGHTFACE_HOME", "").strip()
    if explicit_home:
        return Path(explicit_home)

    return Path.home() / ".insightface"


def _resolve_face_pipeline_profile() -> str:
    """Read RECOGNITION_FACE_PIPELINE_PROFILE; fail closed on unknown values (rg-008)."""
    raw = os.environ.get("RECOGNITION_FACE_PIPELINE_PROFILE", "insightface").strip()
    if raw not in _FACE_PIPELINE_PROFILES:
        raise ValueError(
            f"Invalid RECOGNITION_FACE_PIPELINE_PROFILE={raw!r}; allowed values: {sorted(_FACE_PIPELINE_PROFILES)}"
        )
    return raw


def _resolve_face_pipeline_models_dir() -> Path | None:
    """Optional models dir override; None means face_pipeline DEFAULT_MODELS_DIR."""
    raw = os.environ.get("RECOGNITION_FACE_PIPELINE_MODELS_DIR", "").strip()
    if not raw:
        return None
    return Path(raw)


def _resolve_embedding_dimension() -> int:
    """Bind identity_detection.embedding_dimension to RECOGNITION_EMBEDDING_DIMENSION."""
    return int(os.environ.get("RECOGNITION_EMBEDDING_DIMENSION", "512"))


def _resolve_face_pipeline_timeout_s() -> float:
    """Default detector timeout matches the incumbent embedding timeout source."""
    from db.settings import get_database_settings

    return float(get_database_settings().embedding_timeout_s)


def _resolve_face_pipeline_max_workers() -> int:
    """Read RECOGNITION_FACE_PIPELINE_MAX_WORKERS; fail closed on empty/malformed/<=0."""
    raw = os.environ.get("RECOGNITION_FACE_PIPELINE_MAX_WORKERS")
    if raw is None:
        return 2
    stripped = raw.strip()
    if not stripped:
        raise ValueError(
            "Invalid RECOGNITION_FACE_PIPELINE_MAX_WORKERS: empty value; "
            "must be a positive integer"
        )
    # Reject floats ("1.5") and non-numeric tokens; only optional sign + digits.
    if stripped[0] in "+-" and not stripped[1:].isdigit():
        raise ValueError(
            f"Invalid RECOGNITION_FACE_PIPELINE_MAX_WORKERS={raw!r}; must be a positive integer"
        )
    if stripped[0] not in "+-" and not stripped.isdigit():
        raise ValueError(
            f"Invalid RECOGNITION_FACE_PIPELINE_MAX_WORKERS={raw!r}; must be a positive integer"
        )
    value = int(stripped)
    if value <= 0:
        raise ValueError(
            f"Invalid RECOGNITION_FACE_PIPELINE_MAX_WORKERS={value}; must be a positive integer"
        )
    return value


class InsightFaceSettings(BaseModel):
    """Settings for InsightFace face detection and embedding."""

    model_name: str = Field(default="buffalo_l", description="InsightFace model to use.")
    # NOTE: Changed from "auto" to "cpu" to bypass CoreML compilation errors on macOS
    device: str = Field(default="cpu", description="Device: 'auto', 'cpu', 'cuda', 'mps'.")
    cache_dir: Path = Field(
        default_factory=_resolve_insightface_cache_root, description="InsightFace root cache directory."
    )
    providers: list[str] = Field(default_factory=list, description="ONNX providers (empty = auto-detect).")
    det_thresh: float = Field(default=0.5, description="Face detection confidence threshold.")
    det_size: tuple[int, int] = Field(default=(640, 640), description="Detection input size.")

    @property
    def model_cache_dir(self) -> Path:
        """Return the bundle parent that should contain `<model_name>/`."""
        return self.cache_dir / "models"


class FacePipelineSettings(BaseModel):
    """Dark-launch settings for the FIR-3 YuNet+SFace runtime (FIR-4 S2).

    Production default profile remains ``insightface``. Flat env vars follow the
    existing ``RecognitionSettings`` convention (no nested pydantic-settings delimiter).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    profile: Literal["insightface", "face_pipeline"] = Field(
        default_factory=_resolve_face_pipeline_profile,  # type: ignore[arg-type]
        validate_default=True,
        description="Active face pipeline profile (dark default: insightface).",
    )
    models_dir: Path | None = Field(
        default_factory=_resolve_face_pipeline_models_dir,
        description="Override for face_pipeline ONNX models dir (None → DEFAULT_MODELS_DIR).",
    )
    score_threshold: float = Field(
        default=DEFAULT_SCORE_THRESHOLD,
        description="YuNet score threshold pass-through (FIR-3 default).",
    )
    nms_threshold: float = Field(
        default=DEFAULT_NMS_THRESHOLD,
        description="YuNet NMS threshold pass-through (FIR-3 default).",
    )
    top_k: int = Field(
        default=DEFAULT_TOP_K,
        description="YuNet top-k pass-through (FIR-3 default).",
    )
    timeout_s: float = Field(
        default_factory=_resolve_face_pipeline_timeout_s,
        description="Per-image detect timeout (defaults to DB_EMBEDDING_TIMEOUT_SECONDS).",
    )
    max_workers: int = Field(
        default_factory=_resolve_face_pipeline_max_workers,
        description=(
            "Process-wide face_pipeline executor + admission capacity. "
            "Env: RECOGNITION_FACE_PIPELINE_MAX_WORKERS (default 2)."
        ),
    )

    @field_validator("profile", mode="before")
    @classmethod
    def _validate_profile(cls, value: object) -> object:
        if isinstance(value, str) and value not in _FACE_PIPELINE_PROFILES:
            raise ValueError(
                f"Invalid face_pipeline profile={value!r}; allowed values: {sorted(_FACE_PIPELINE_PROFILES)}"
            )
        return value

    @field_validator("max_workers", mode="before")
    @classmethod
    def _validate_max_workers(cls, value: object) -> object:
        """Fail closed on non-positive or non-integral capacity ([CFG-01/02])."""
        if isinstance(value, bool):
            raise ValueError(f"Invalid face_pipeline max_workers={value!r}; must be a positive integer")
        if isinstance(value, float):
            if not value.is_integer():
                raise ValueError(f"Invalid face_pipeline max_workers={value!r}; must be a positive integer")
            value = int(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped or (stripped[0] in "+-" and not stripped[1:].isdigit()) or (
                stripped[0] not in "+-" and not stripped.isdigit()
            ):
                raise ValueError(f"Invalid face_pipeline max_workers={value!r}; must be a positive integer")
            value = int(stripped)
        if not isinstance(value, int):
            raise ValueError(f"Invalid face_pipeline max_workers={value!r}; must be a positive integer")
        if value <= 0:
            raise ValueError(f"Invalid face_pipeline max_workers={value}; must be a positive integer")
        return value

    @property
    def resolved_models_dir(self) -> Path:
        """Models directory used for verified load (None → package DEFAULT_MODELS_DIR)."""
        return self.models_dir if self.models_dir is not None else DEFAULT_MODELS_DIR


class IdentityDetectionSettings(BaseModel):
    """Settings for identity detection and embedding generation."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    default_threshold: float = Field(default=0.45, description="Default detection confidence threshold.")
    max_identities_per_image: int = Field(default=999, description="Maximum faces to detect per image.")
    embedding_dimension: int = Field(
        default_factory=_resolve_embedding_dimension,
        description="Embedding vector dimension (face identity only). Env: RECOGNITION_EMBEDDING_DIMENSION.",
    )
    max_candidates: int = Field(default=10, description="Maximum candidate matches to consider.")


class ClusteringLimitsSettings(BaseModel):
    """Settings for cluster size limits (separate from threshold tuning)."""

    similarity_threshold: float = Field(default=0.6, description="Base similarity threshold for initial grouping.")
    min_cluster_size: int = Field(default=2, description="Minimum members for a valid cluster.")
    max_cluster_size: int = Field(default=1000, description="Maximum members per cluster.")


_DEFAULT_UPLOAD_MIME_TYPES: tuple[str, ...] = (
    "image/jpeg",
    "image/png",
    "image/webp",
)


def _parse_allowed_upload_mime_types(raw: str) -> list[str]:
    """Parse RECOGNITION_ALLOWED_UPLOAD_MIME_TYPES into a list.

    Comma-separated; per-item whitespace stripped; empty / whitespace-only
    input returns the safe default (so a misconfigured env var cannot
    silently disable every upload).
    """
    items = [chunk.strip() for chunk in raw.split(",") if chunk.strip()]
    if not items:
        return list(_DEFAULT_UPLOAD_MIME_TYPES)
    return items


class RecognitionSettings(BaseModel):
    """Top-level recognition settings container."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    insightface: InsightFaceSettings = Field(default_factory=InsightFaceSettings)
    face_pipeline: FacePipelineSettings = Field(default_factory=FacePipelineSettings)
    identity_detection: IdentityDetectionSettings = Field(default_factory=IdentityDetectionSettings)
    clustering_limits: ClusteringLimitsSettings = Field(default_factory=ClusteringLimitsSettings)
    clustering: ClusteringSettings = Field(default_factory=ClusteringSettings)
    scan: ScanSettings = Field(default_factory=ScanSettings)
    retention_export_max_identities: int = Field(
        default=50000,
        description="Max identities allowed for synchronous retention export responses.",
    )
    default_retention_mode: Literal["retain_all", "dispose_after_ack", "purge_on_demand"] = Field(
        default_factory=lambda: os.environ.get("RECOGNITION_DEFAULT_RETENTION_MODE", "retain_all"),
        validate_default=True,
    )

    # Runtime mode: "production" uses real InsightFace, "test" uses stubs
    runtime_mode: str = Field(default_factory=lambda: os.environ.get("RECOGNITION_RUNTIME_MODE", "production"))

    # E15-11: filesystem ObjectStore root. Multipart-uploaded image bytes are
    # written under <blob_root>/<tenant_id>/<job_id>/<media_id>.bin and
    # cleaned up by the worker after the scan completes or fails.
    blob_root: Path = Field(
        default_factory=lambda: Path(os.environ.get("RECOGNITION_BLOB_ROOT", "/tmp/acx-recognition-blobs")),
        description="Filesystem root for the ObjectStore (multipart upload transport).",
    )

    # E15-11: per-request body cap on the multipart variant of /recognition/analyze.
    max_upload_bytes: int = Field(
        default_factory=lambda: int(os.environ.get("RECOGNITION_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))),
        description="Reject multipart requests with Content-Length above this value.",
    )

    # E15-11: allowed image MIME types for multipart upload parts.
    # Override via comma-separated env var, e.g.
    # `RECOGNITION_ALLOWED_UPLOAD_MIME_TYPES=image/jpeg,image/heic,image/avif`.
    # Whitespace-only or unset values fall back to the safe default to avoid
    # accidentally rejecting every upload.
    allowed_upload_mime_types: list[str] = Field(
        default_factory=lambda: _parse_allowed_upload_mime_types(
            os.environ.get("RECOGNITION_ALLOWED_UPLOAD_MIME_TYPES", "")
        ),
        description="MIME allow-list for image_<media_id> parts on the multipart route.",
    )

    @model_validator(mode="after")
    def _check_embedding_pgvector_pair(self) -> RecognitionSettings:
        """Fail fast when identity embedding dim != DB pgvector dim (CR-09).

        Lazy-import db settings to avoid import cycles at module load.
        Pairing is profile-independent (insightface and face_pipeline).
        """
        from db.settings import get_database_settings

        pg_dim = int(get_database_settings().pgvector_dimension)
        id_dim = int(self.identity_detection.embedding_dimension)
        if id_dim != pg_dim:
            raise ValueError(f"identity_detection.embedding_dimension ({id_dim}) != pgvector_dimension ({pg_dim})")
        return self
