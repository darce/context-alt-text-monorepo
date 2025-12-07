"""Validation helpers for HTTP layer."""

from __future__ import annotations

import re
import uuid

from fastapi import HTTPException, status

from recognition.shared.ids import parse_id


def is_uuid(value: str) -> bool:
    """Check if value is a valid UUID string."""
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError):
        return False


def validate_entity_id(value: str, field_name: str = "id") -> str:
    """Validate entity identifiers (standard UUIDs).

    Args:
        value: A UUID string or UUID object.
        field_name: Name of the field for error messages.

    Returns:
        The canonical UUID string (lowercase, hyphenated).

    Raises:
        HTTPException: 400 if the value is not a valid UUID.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if not isinstance(value, str) or not value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"invalid {field_name} format")
    try:
        parsed = parse_id(value)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"invalid {field_name} format")
    return str(parsed)


def validate_paging(limit: int, offset: int, max_limit: int) -> None:
    """Enforce paging bounds with 400 responses instead of 422."""
    if limit < 1 or limit > max_limit:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="limit out of range")
    if offset < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="offset must be non-negative")


def validate_label(label: str | None) -> str | None:
    """Reject labels containing HTML/script content."""
    if label is None:
        return None
    if "<" in label or ">" in label:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="label contains invalid characters")
    stripped = label.strip()
    if not stripped:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="label cannot be empty")
    if len(stripped) > 255:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="label too long")
    if re.search(r"<[^>]+>", stripped):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="label contains HTML")
    return stripped


__all__ = ["validate_entity_id", "validate_paging", "validate_label", "is_uuid"]
