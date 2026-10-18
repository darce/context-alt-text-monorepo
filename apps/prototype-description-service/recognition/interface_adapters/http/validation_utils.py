"""
Shared validation utilities for recognition HTTP API.

This module provides common validation functions used across schemas.
"""

from __future__ import annotations

import uuid


def validate_uuid_format(value: str) -> str:
    """Validate and normalize UUID to standard hyphenated lowercase format.

    Accepts both 32-char hex strings (no dashes) and 36-char UUID strings (with dashes).
    Also accepts integers (converted to string).
    Always returns the standard 36-char lowercase UUID format when valid,
    or lowercase string for non-UUID identifiers.

    Args:
        value: The value to validate (string or int).

    Returns:
        Normalized UUID string or lowercase identifier.

    Raises:
        TypeError: If value is not a string or int.
        ValueError: If value is empty or contains invalid characters.
    """
    if isinstance(value, int):
        return str(value)
    if not isinstance(value, str):
        raise TypeError("id must be a string")
    if len(value) < 1:
        raise ValueError("id must be at least 1 character")
    if not all(ch.isalnum() or ch == "-" for ch in value):
        raise ValueError("id must contain only alphanumeric characters or dashes")
    # Normalize to standard UUID format (lowercase with dashes)
    try:
        return str(uuid.UUID(value))
    except ValueError:
        # Fall back to lowercase for non-UUID identifiers
        return value.lower()


__all__ = ["validate_uuid_format"]
