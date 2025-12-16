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
        raise NotImplementedError("TODO: implement IdentityLocator.to_dict")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> IdentityLocator:
        """Parse a locator from a JSON-friendly dict.

        Args:
            payload: Mapping with keys `media_id`, `bbox_x`, `bbox_y`, `bbox_width`, `bbox_height`, and optionally
                `crop_hash`.

        Returns:
            IdentityLocator: Parsed locator.
        """
        raise NotImplementedError("TODO: implement IdentityLocator.from_dict")

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
        raise NotImplementedError("TODO: implement IdentityLocator.matches")
