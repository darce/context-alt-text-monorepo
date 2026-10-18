"""Versioned exact inference-input evidence. Measurement conveys no binding authority."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from typing import Any

import numpy as np


class FaceEvidenceStatus(StrEnum):
    UNAVAILABLE = "unavailable"
    MEASURED_LIFECYCLE_UNAVAILABLE = "measured_lifecycle_unavailable"


@dataclass(frozen=True)
class FaceEvidence:
    source_sha256: str
    raster_sha256: str
    decode_recipe_id: str
    raster_width: int
    raster_height: int
    region: tuple[int, int, int, int]
    raster_serialization: str = "face-raster-v1:BGR:uint8:HWC:C"

    def __post_init__(self) -> None:
        for digest in (self.source_sha256, self.raster_sha256):
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise ValueError("invalid evidence SHA256")
        if (
            type(self.raster_width) is not int
            or type(self.raster_height) is not int
            or self.raster_width <= 0
            or self.raster_height <= 0
        ):
            raise ValueError("invalid evidence raster dimensions")
        if (
            self.decode_recipe_id != "pil-rgb-no-exif-cv2-bgr-v1"
            or self.raster_serialization != "face-raster-v1:BGR:uint8:HWC:C"
        ):
            raise ValueError("unsupported face evidence recipe")
        if len(self.region) != 4 or any(type(v) is not int for v in self.region):
            raise ValueError("invalid evidence region")
        x, y, width, height = self.region
        if not (0 <= x < x + width <= self.raster_width and 0 <= y < y + height <= self.raster_height):
            raise ValueError("invalid evidence region")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def for_bbox(self, bbox: tuple[int, int, int, int]) -> FaceEvidence | None:
        x, y, right, bottom = bbox
        if not (0 <= x < right <= self.raster_width and 0 <= y < bottom <= self.raster_height):
            return None
        return replace(self, region=(x, y, right - x, bottom - y))


def measure_input(image_bytes: bytes, raster: np.ndarray) -> FaceEvidence:
    """Hash the full BGR array *before* handing that same object to inference.

    Recipe v1 is PIL open/convert RGB, no EXIF transpose, cv2 RGB2BGR.
    Serialization is canonical ASCII JSON header, LF, row-major pixel bytes.
    """
    if raster.dtype != np.uint8 or raster.ndim != 3 or raster.shape[2] != 3:
        raise ValueError("face evidence requires HWC BGR uint8 raster")
    height, width, _ = raster.shape
    header = json.dumps(
        {"version": 1, "width": width, "height": height, "channels": "BGR", "dtype": "uint8", "order": "C"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    digest = hashlib.sha256(header + b"\n" + raster.tobytes(order="C")).hexdigest()
    return FaceEvidence(
        hashlib.sha256(image_bytes).hexdigest(),
        digest,
        "pil-rgb-no-exif-cv2-bgr-v1",
        width,
        height,
        (0, 0, width, height),
    )
