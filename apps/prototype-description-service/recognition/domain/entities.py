"""Domain entities used by the recognition subsystem."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class IdentityDetection:
    """Detected identity (face) bounding box and confidence metadata."""

    bbox: tuple[int, int, int, int]
    confidence: float
    landmarks: np.ndarray | None = None

    def area(self) -> float:
        x_min, y_min, x_max, y_max = self.bbox
        return max(0, x_max - x_min) * max(0, y_max - y_min)


@dataclass(frozen=True)
class IdentityEmbedding:
    """Identity embedding combined with the original detection."""

    embedding: np.ndarray
    detection: IdentityDetection

    def to_list(self) -> list[float]:
        result = self.embedding.tolist()
        return result  # type: ignore[no-any-return]
