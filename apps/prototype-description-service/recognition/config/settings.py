"""
Minimal settings for the recognition service (dev-only stub).
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel


class ThumbnailSettings(BaseModel):
    """Settings for serving generated thumbnails."""

    base_url: str | None = None
    storage_dir: Path = Path("logs/thumbnails")


class InsightFaceSettings(BaseModel):
    """Settings for InsightFace face detection and embedding."""

    model_name: str = "buffalo_l"
    device: str = "auto"  # "auto", "cpu", "cuda", "mps"
    cache_dir: Path = Path.home() / ".insightface" / "models"
    providers: list[str] = []  # Empty = auto-detect
    det_thresh: float = 0.5
    det_size: tuple[int, int] = (640, 640)


class RecognitionSettings(BaseModel):
    """Top-level recognition settings."""

    thumbnail: ThumbnailSettings = ThumbnailSettings()
    insightface: InsightFaceSettings = InsightFaceSettings()

    # Runtime mode: "production" uses real InsightFace, "test" uses stubs
    runtime_mode: str = os.environ.get("RECOGNITION_RUNTIME_MODE", "production")
