"""ID generation using time-ordered UUIDv7.

UUIDv7 provides:
- Time-ordered IDs for chronological sorting and index locality
- Native PostgreSQL UUID support (no conversion needed)
- Standard 36-char hyphenated format (universally understood)
"""

from __future__ import annotations

import uuid

from uuid_extensions import uuid7  # noqa: E402


def generate_id() -> uuid.UUID:
    """Generate a time-ordered UUIDv7.

    Returns:
        uuid.UUID: A new UUIDv7 value, compatible with PostgreSQL UUID type.
    """
    result: uuid.UUID = uuid7()
    return result


def parse_id(value: str) -> uuid.UUID:
    """Parse a UUID string into a UUID object.

    Args:
        value: A standard UUID string (36 chars with hyphens, or 32 hex chars).

    Returns:
        uuid.UUID: The parsed UUID.

    Raises:
        ValueError: If the string is not a valid UUID.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("ID must be a non-empty string")
    return uuid.UUID(value.strip())


def parse_optional_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    """Parse a UUID safely, returning None if invalid or None."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


__all__ = ["generate_id", "parse_id", "parse_optional_uuid"]
