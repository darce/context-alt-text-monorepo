"""Tests for ID helpers (UUIDv7 generation and parsing)."""

from __future__ import annotations

import uuid

import pytest

from recognition.shared.ids import generate_id, parse_id


def test_generate_id_is_uuidv7() -> None:
    """Generated IDs should be valid UUID objects."""
    value = generate_id()
    assert isinstance(value, uuid.UUID)


def test_generate_id_is_unique() -> None:
    """Each generated ID should be unique."""
    ids = [generate_id() for _ in range(100)]
    assert len(set(ids)) == 100


def test_parse_id_accepts_hyphenated_uuid() -> None:
    """parse_id should accept standard hyphenated UUID strings."""
    original = generate_id()
    parsed = parse_id(str(original))
    assert parsed == original


def test_parse_id_accepts_hex_uuid() -> None:
    """parse_id should accept 32-char hex UUID strings (no hyphens)."""
    original = generate_id()
    hex_str = original.hex
    parsed = parse_id(hex_str)
    assert parsed == original


def test_parse_id_rejects_invalid_string() -> None:
    """parse_id should reject non-UUID strings."""
    with pytest.raises(ValueError):
        parse_id("not-a-uuid")


def test_parse_id_rejects_empty_string() -> None:
    """parse_id should reject empty strings."""
    with pytest.raises(ValueError):
        parse_id("")


def test_parse_id_rejects_short_string() -> None:
    """parse_id should reject strings too short to be UUIDs."""
    with pytest.raises(ValueError):
        parse_id("abc123")
