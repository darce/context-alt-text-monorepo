"""
Cluster representative value object used for similarity comparisons.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np


@dataclass
class ClusterRepresentative:
    """Represents a curated embedding that stands in for a cluster."""

    id: str
    cluster_id: str
    identity_id: str
    embedding: np.ndarray
    created_at: datetime
    tenant_id: str | None = None
    pose_pitch: float | None = None
    pose_yaw: float | None = None
    pose_roll: float | None = None
    quality_score: float = 1.0
    diversity_score: float | None = None
    media_id: int | None = None  # For HTTP response serialization
    media_url: str | None = None  # Source media URL for client-side face crop fallback
    bbox_x: int | None = None
    bbox_y: int | None = None
    bbox_width: int | None = None
    bbox_height: int | None = None
    image_phash: str | None = None
    is_user_selected: bool = False  # User pinned this rep
    is_provisional: bool = False  # Added during batch, pending confirmation
    debug_metrics: dict[str, Any] | None = None
    # FIR23-01 / R3-G2-2: provenance for the embedding space this vector belongs to.
    # Appended last so existing positional construction sites keep working.
    embedding_model: str | None = None
