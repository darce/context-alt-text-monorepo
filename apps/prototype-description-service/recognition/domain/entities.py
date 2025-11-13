"""Domain entities used by the recognition subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np


@dataclass(frozen=True)
class FaceDetection:
    """Detected face bounding box and confidence metadata."""

    bbox: Tuple[int, int, int, int]
    confidence: float
    landmarks: Optional[np.ndarray] = None

    def area(self) -> float:
        x_min, y_min, x_max, y_max = self.bbox
        return max(0, x_max - x_min) * max(0, y_max - y_min)


@dataclass(frozen=True)
class FaceEmbedding:
    """Face embedding combined with the original detection."""

    embedding: np.ndarray
    detection: FaceDetection

    def to_list(self) -> list[float]:
        return self.embedding.tolist()
