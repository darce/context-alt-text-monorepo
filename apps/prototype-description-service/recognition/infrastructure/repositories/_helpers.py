"""Shared repository helper utilities."""

from __future__ import annotations

import uuid
from typing import Literal


def coerce_uuid(
    value: str | uuid.UUID | None,
    *,
    on_failure: Literal["deterministic", "none"] = "deterministic",
) -> uuid.UUID | None:
    """Convert a string/UUID to ``uuid.UUID`` with configurable failure behavior."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        if on_failure == "none":
            return None
        # Keep short legacy identifiers storable by deriving a deterministic UUID.
        return uuid.uuid5(uuid.NAMESPACE_URL, str(value))
