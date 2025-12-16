from __future__ import annotations

import pytest

from recognition.domain.locator import IdentityLocator


def test_locator_to_dict_roundtrip() -> None:
    locator = IdentityLocator(media_id=41, bbox_x=10, bbox_y=20, bbox_width=30, bbox_height=40, crop_hash=None)
    payload = locator.to_dict()
    assert payload["media_id"] == 41
    assert payload["bbox_x"] == 10
    assert payload["bbox_y"] == 20
    assert payload["bbox_width"] == 30
    assert payload["bbox_height"] == 40
    assert payload["crop_hash"] is None

    parsed = IdentityLocator.from_dict(payload)
    assert parsed == locator


def test_locator_matches_by_crop_hash_when_present() -> None:
    left = IdentityLocator(media_id=41, bbox_x=0, bbox_y=0, bbox_width=10, bbox_height=10, crop_hash="abc")
    right_same = IdentityLocator(media_id=41, bbox_x=999, bbox_y=999, bbox_width=1, bbox_height=1, crop_hash="abc")
    right_diff = IdentityLocator(media_id=41, bbox_x=0, bbox_y=0, bbox_width=10, bbox_height=10, crop_hash="def")
    assert left.matches(right_same) is True
    assert left.matches(right_diff) is False


def test_locator_matches_with_bbox_tolerance() -> None:
    base = IdentityLocator(media_id=41, bbox_x=100, bbox_y=200, bbox_width=50, bbox_height=60, crop_hash=None)
    within = IdentityLocator(media_id=41, bbox_x=103, bbox_y=197, bbox_width=48, bbox_height=62, crop_hash=None)
    outside = IdentityLocator(media_id=41, bbox_x=120, bbox_y=200, bbox_width=50, bbox_height=60, crop_hash=None)
    different_media = IdentityLocator(
        media_id=42, bbox_x=100, bbox_y=200, bbox_width=50, bbox_height=60, crop_hash=None
    )

    assert base.matches(within, tolerance=5) is True
    assert base.matches(outside, tolerance=5) is False
    assert base.matches(different_media, tolerance=5) is False


def test_locator_from_dict_requires_expected_fields() -> None:
    with pytest.raises(ValueError):
        IdentityLocator.from_dict({"media_id": 41})
