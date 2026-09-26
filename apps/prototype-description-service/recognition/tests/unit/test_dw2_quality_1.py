"""Regression coverage for deferred representative quality and calibration findings."""

from __future__ import annotations

from copy import deepcopy
from math import inf, nan

import pytest
from pydantic import ValidationError

from recognition.application.assignment.quality import (
    compute_identity_quality,
    compute_representative_quality,
    min_bbox_area_from_settings,
)
from recognition.application.settings import QualitySettings
from recognition.application.settings.clustering import (
    CLUSTER_RECOVERY_CALIBRATION_POLICY_BLOCK,
    FalseNameAcceptanceEvidence,
    false_name_acceptance_passes,
    load_cluster_recovery_calibration_policy,
)


def test_representative_area_floor_is_independent_of_assignment_size_threshold() -> None:
    settings = QualitySettings(
        min_face_size=80.0,
        min_bbox_area=1600.0,
        representative_quality_composite_enabled=True,
    )

    representative = compute_representative_quality(
        confidence=0.81,
        bbox_width=40,
        bbox_height=40,
        settings=settings,
    )
    assignment = compute_identity_quality(
        confidence=0.81,
        bbox_width=40,
        bbox_height=40,
        settings=settings,
    )
    larger_area_floor = QualitySettings(
        min_face_size=80.0,
        min_bbox_area=6400.0,
        representative_quality_composite_enabled=True,
    )
    larger_floor_representative = compute_representative_quality(
        confidence=0.81,
        bbox_width=40,
        bbox_height=40,
        settings=larger_area_floor,
    )
    larger_floor_assignment = compute_identity_quality(
        confidence=0.81,
        bbox_width=40,
        bbox_height=40,
        settings=larger_area_floor,
    )

    assert min_bbox_area_from_settings(settings) == 1600.0
    assert representative.bbox_term == 1.0
    assert assignment.score == 0.405
    assert larger_floor_representative.bbox_term == 0.25
    assert larger_floor_assignment.score == assignment.score


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("confidence", nan),
        ("confidence", inf),
        ("bbox_width", nan),
        ("bbox_height", inf),
        ("sharpness", nan),
        ("occlusion_severity", inf),
    ],
)
def test_representative_quality_rejects_non_finite_inputs(field: str, invalid: float) -> None:
    values: dict[str, float | int | None] = {
        "confidence": 0.9,
        "bbox_width": 80,
        "bbox_height": 80,
        "sharpness": 10.0,
        "occlusion_severity": 0.2,
    }
    values[field] = invalid

    with pytest.raises(ValueError, match=field):
        compute_representative_quality(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("settings", "sharpness", "error_field"),
    [
        (QualitySettings(oact_coefficient=inf), None, "oact_coefficient"),
        (QualitySettings(factor_floor_sharpness=inf), 10.0, "factor_floor_sharpness"),
    ],
)
def test_representative_quality_rejects_non_finite_factor_settings(
    settings: QualitySettings,
    sharpness: float | None,
    error_field: str,
) -> None:
    with pytest.raises(ValueError, match=error_field):
        compute_representative_quality(
            confidence=0.9,
            bbox_width=80,
            bbox_height=80,
            sharpness=sharpness,
            settings=settings,
        )


def test_calibration_policy_uses_structured_abstention_and_false_name_acceptance() -> None:
    raw = deepcopy(CLUSTER_RECOVERY_CALIBRATION_POLICY_BLOCK)
    raw["abstain"] = {
        "clauses": [
            "quality_stratum_abstained",
            "insufficient_labelled_pairs",
            "cell_pair_floor_not_met",
            "insufficient_distinct_media_exemplars",
            "intra_similarity_below_tau",
            "recovery_margin_below_floor",
            "confirmed_named_identity_conflict",
        ]
    }
    policy = load_cluster_recovery_calibration_policy(raw)

    assert len(policy.abstain.clauses) == 7
    assert false_name_acceptance_passes(
        policy,
        FalseNameAcceptanceEvidence(
            automatic_false_name_accepts=0,
            observed_rate=0.0,
            every_non_abstained_stratum_has_interval=True,
        ),
    )
    assert not false_name_acceptance_passes(
        policy,
        FalseNameAcceptanceEvidence(
            automatic_false_name_accepts=1,
            observed_rate=0.0,
            every_non_abstained_stratum_has_interval=True,
        ),
    )
    assert not false_name_acceptance_passes(
        policy,
        FalseNameAcceptanceEvidence(
            automatic_false_name_accepts=0,
            observed_rate=0.0,
            every_non_abstained_stratum_has_interval=False,
        ),
    )


@pytest.mark.parametrize(
    ("path", "key"),
    [
        ("abstain", "clauses"),
        ("false_name_acceptance_gate", "require_interval_for_every_non_abstained_stratum"),
    ],
)
def test_calibration_policy_rejects_missing_structured_acceptance_fields(path: str, key: str) -> None:
    raw = deepcopy(CLUSTER_RECOVERY_CALIBRATION_POLICY_BLOCK)
    raw["abstain"] = {"clauses": ["quality_stratum_abstained"]}
    raw[path].pop(key)

    with pytest.raises(ValidationError):
        load_cluster_recovery_calibration_policy(raw)
