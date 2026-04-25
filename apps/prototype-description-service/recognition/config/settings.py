"""
Consolidated settings for the recognition service.

All algorithm thresholds and detection parameters are defined here with
type-safe defaults. Override by instantiating with explicit values in code.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from recognition.application.settings import ClusteringSettings
from recognition.application.settings.scan import ScanSettings


def _resolve_insightface_cache_root() -> Path:
    """Resolve the InsightFace root cache dir from env or the legacy default."""
    explicit_cache_dir = os.environ.get("INSIGHTFACE_CACHE_DIR", "").strip()
    if explicit_cache_dir:
        return Path(explicit_cache_dir)

    explicit_home = os.environ.get("INSIGHTFACE_HOME", "").strip()
    if explicit_home:
        return Path(explicit_home)

    return Path.home() / ".insightface"


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


class IdentityDetectionSettings(BaseModel):
    """Settings for identity detection and embedding generation."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    default_threshold: float = Field(default=0.45, description="Default detection confidence threshold.")
    max_identities_per_image: int = Field(default=999, description="Maximum faces to detect per image.")
    embedding_dimension: int = Field(default=512, description="Embedding vector dimension (face identity only).")
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
