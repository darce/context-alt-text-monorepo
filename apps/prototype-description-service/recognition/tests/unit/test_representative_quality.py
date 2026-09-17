"""Contracts for the gated representative-quality score and wire components."""

from __future__ import annotations

import numpy as np

from recognition.application.assignment.quality import (
    compute_identity_quality,
    compute_representative_quality,
    representative_sort_key,
)
from recognition.application.persistence.representative_selector import (
    _compute_identity_quality,
    sort_identities_for_representative,
)
from recognition.application.settings import ClusteringSettings, QualitySettings
from recognition.domain.identity import MediaIdentity


def _identity(
    identity_id: str,
    *,
    confidence: float,
    bbox_width: int,
    bbox_height: int,
) -> MediaIdentity:
    return MediaIdentity(
        id=identity_id,
        tenant_id="tenant-1",
        media_id=f"media-{identity_id}",
        embedding=np.ones(512, dtype=np.float32),
        confidence=confidence,
        bbox_width=bbox_width,
        bbox_height=bbox_height,
    )


def test_composite_policy_is_disabled_by_default() -> None:
    settings = QualitySettings()

    assert settings.representative_quality_composite_enabled is False
    assert "enable only once the C1 calibration assessment is accepted by the operator" in (
        QualitySettings.model_fields["representative_quality_composite_enabled"].description or ""
    )


def test_default_policy_keeps_legacy_rank_and_persisted_score() -> None:
    settings = ClusteringSettings()
    wide = _identity("wide", confidence=0.9, bbox_width=40, bbox_height=200)
    square = _identity("square", confidence=0.8, bbox_width=80, bbox_height=80)

    # Legacy score: square=.8 beats wide=.45. C4 would reverse this ordering.
    expected = compute_identity_quality(
        confidence=wide.confidence,
        bbox_width=wide.bbox_width,
        bbox_height=wide.bbox_height,
        settings=settings.quality,
    ).score
    quality = compute_representative_quality(
        confidence=wide.confidence,
        bbox_width=wide.bbox_width,
        bbox_height=wide.bbox_height,
        settings=settings.quality,
    )

    assert quality.composite == expected == 0.45
    assert quality.score_policy == "legacy"
    assert _compute_identity_quality(wide, settings) == expected
    assert [identity.id for identity in sort_identities_for_representative([wide, square], settings)] == [
        "square",
        "wide",
    ]


def test_enabled_policy_uses_composite_for_rank_and_persisted_score() -> None:
    quality_settings = QualitySettings(representative_quality_composite_enabled=True)
    settings = ClusteringSettings(quality=quality_settings)
    wide = _identity("wide", confidence=0.9, bbox_width=40, bbox_height=200)
    square = _identity("square", confidence=0.8, bbox_width=80, bbox_height=80)

    quality = compute_representative_quality(
        confidence=wide.confidence,
        bbox_width=wide.bbox_width,
        bbox_height=wide.bbox_height,
        settings=quality_settings,
    )
    expected = quality.composite

    assert expected == 0.949
    assert quality.score_policy == "composite"
    assert _compute_identity_quality(wide, settings) == expected
    assert [identity.id for identity in sort_identities_for_representative([wide, square], settings)] == [
        "wide",
        "square",
    ]
    assert representative_sort_key(
        confidence=wide.confidence,
        bbox_width=wide.bbox_width,
        bbox_height=wide.bbox_height,
        settings=quality_settings,
        identity_id=wide.id,
    ) < representative_sort_key(
        confidence=square.confidence,
        bbox_width=square.bbox_width,
        bbox_height=square.bbox_height,
        settings=quality_settings,
        identity_id=square.id,
    )


def test_missing_sharpness_is_serialized_as_null() -> None:
    quality = compute_representative_quality(
        confidence=0.94,
        bbox_width=96,
        bbox_height=80,
        sharpness=None,
        occlusion_severity=0.12,
        settings=QualitySettings(representative_quality_composite_enabled=True),
    )

    assert quality.components() == {
        "confidence": 0.94,
        "bbox_area": 7680.0,
        "sharpness": None,
        "occlusion_severity": 0.12,
    }


def test_missing_occlusion_is_serialized_as_null() -> None:
    quality = compute_representative_quality(
        confidence=0.94,
        bbox_width=96,
        bbox_height=80,
        sharpness=42.5,
        occlusion_severity=None,
        settings=QualitySettings(representative_quality_composite_enabled=True),
    )

    assert quality.components() == {
        "confidence": 0.94,
        "bbox_area": 7680.0,
        "sharpness": 42.5,
        "occlusion_severity": None,
    }


def test_fully_measured_components_keep_numeric_values() -> None:
    quality = compute_representative_quality(
        confidence=0.94,
        bbox_width=96,
        bbox_height=80,
        sharpness=42.5,
        occlusion_severity=0.12,
        settings=QualitySettings(representative_quality_composite_enabled=True),
    )

    assert quality.components() == {
        "confidence": 0.94,
        "bbox_area": 7680.0,
        "sharpness": 42.5,
        "occlusion_severity": 0.12,
    }
