"""
Consolidated settings for the recognition service.

All algorithm thresholds and detection parameters are defined here with
type-safe defaults. Override by instantiating with explicit values in code.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from recognition.application.settings import ClusteringSettings
from recognition.application.settings.scan import ScanSettings


class InsightFaceSettings(BaseModel):
    """Settings for InsightFace face detection and embedding."""

    model_name: str = Field(default="buffalo_l", description="InsightFace model to use.")
    # NOTE: Changed from "auto" to "cpu" to bypass CoreML compilation errors on macOS
    device: str = Field(default="cpu", description="Device: 'auto', 'cpu', 'cuda', 'mps'.")
    cache_dir: Path = Field(default=Path.home() / ".insightface" / "models", description="Model cache directory.")
    providers: list[str] = Field(default_factory=list, description="ONNX providers (empty = auto-detect).")
    det_thresh: float = Field(default=0.5, description="Face detection confidence threshold.")
    det_size: tuple[int, int] = Field(default=(640, 640), description="Detection input size.")


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


class RecognitionSettings(BaseModel):
    """Top-level recognition settings container."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    insightface: InsightFaceSettings = Field(default_factory=InsightFaceSettings)
    identity_detection: IdentityDetectionSettings = Field(default_factory=IdentityDetectionSettings)
    clustering_limits: ClusteringLimitsSettings = Field(default_factory=ClusteringLimitsSettings)
    clustering: ClusteringSettings = Field(default_factory=ClusteringSettings)
    scan: ScanSettings = Field(default_factory=ScanSettings)

    # Runtime mode: "production" uses real InsightFace, "test" uses stubs
    runtime_mode: str = Field(default_factory=lambda: os.environ.get("RECOGNITION_RUNTIME_MODE", "production"))
