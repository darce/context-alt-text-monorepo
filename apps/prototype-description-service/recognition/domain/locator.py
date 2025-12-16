"""
Stable identity locator used for regression testing.

The regression harness must match identities across DB resets. `media_identities.id` is not stable, so we match faces
using a stable locator derived from the media item + bounding box.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class IdentityLocator:
    """Stable identifier for matching identities across DB resets.

    Args:
        media_id: Media item identifier (stable across DB resets).
        bbox_x: Bounding box X coordinate in pixels.
        bbox_y: Bounding box Y coordinate in pixels.
        bbox_width: Bounding box width in pixels.
        bbox_height: Bounding box height in pixels.
        crop_hash: Optional SHA256 (or similar) hash of the face crop bytes for robust matching.
    """

    media_id: int
    bbox_x: int
    bbox_y: int
    bbox_width: int
    bbox_height: int
    crop_hash: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Serialize the locator to a JSON-friendly dict."""
        return {
            "media_id": self.media_id,
            "bbox_x": self.bbox_x,
            "bbox_y": self.bbox_y,
            "bbox_width": self.bbox_width,
            "bbox_height": self.bbox_height,
            "crop_hash": self.crop_hash,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> IdentityLocator:
        """Parse a locator from a JSON-friendly dict.

        Args:
            payload: Mapping with keys `media_id`, `bbox_x`, `bbox_y`, `bbox_width`, `bbox_height`, and optionally
                `crop_hash`.

        Returns:
            IdentityLocator: Parsed locator.
        """
        required_fields = ("media_id", "bbox_x", "bbox_y", "bbox_width", "bbox_height")
        missing = [field for field in required_fields if field not in payload]
        if missing:
            raise ValueError(f"Missing identity locator fields: {', '.join(missing)}")

        try:
            media_id = int(payload["media_id"])
            bbox_x = int(payload["bbox_x"])
            bbox_y = int(payload["bbox_y"])
            bbox_width = int(payload["bbox_width"])
            bbox_height = int(payload["bbox_height"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid identity locator field types") from exc

        crop_hash_value = payload.get("crop_hash")
        crop_hash = str(crop_hash_value) if crop_hash_value is not None else None

        return cls(
            media_id=media_id,
            bbox_x=bbox_x,
            bbox_y=bbox_y,
            bbox_width=bbox_width,
            bbox_height=bbox_height,
            crop_hash=crop_hash,
        )

    def matches(self, other: IdentityLocator, *, tolerance: int = 5) -> bool:
        """Return True if two locators refer to the same face, allowing bbox drift.

        Matching rules:
        - If both locators have `crop_hash`, they must match exactly.
        - Otherwise, require same `media_id` and bbox fields within `tolerance` pixels.

        Args:
            other: Locator to compare against.
            tolerance: Maximum absolute pixel drift allowed for bbox fields.

        Returns:
            bool: True when the two locators are considered a match.
        """
        if tolerance < 0:
            raise ValueError("tolerance must be >= 0")

        if self.crop_hash and other.crop_hash:
            return self.crop_hash == other.crop_hash

        return (
            self.media_id == other.media_id
            and abs(self.bbox_x - other.bbox_x) <= tolerance
            and abs(self.bbox_y - other.bbox_y) <= tolerance
            and abs(self.bbox_width - other.bbox_width) <= tolerance
            and abs(self.bbox_height - other.bbox_height) <= tolerance
        )
