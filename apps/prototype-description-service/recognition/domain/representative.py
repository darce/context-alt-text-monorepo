"""
Cluster representative value object used for similarity comparisons.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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
    quality_score: float = 1.0
    diversity_score: float | None = None
