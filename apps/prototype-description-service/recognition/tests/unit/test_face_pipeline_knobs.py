"""FIR-6 wave-0: FacePipelineSettings knob surface + profile-resolution helper.

rg-008: fail-closed validation at load. Discrimination: face_pipeline overrides
move effective thresholds; insightface keeps shared anchors.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from recognition.application.settings import ClusteringSettings
from recognition.config.settings import (
    ClusteringLimitsSettings,
    FacePipelineSettings,
    IdentityDetectionSettings,
    resolve_face_pipeline_knobs,
)


def _resolve(
    face_pipeline: FacePipelineSettings,
    *,
    clustering: ClusteringSettings | None = None,
    clustering_limits: ClusteringLimitsSettings | None = None,
    identity_detection: IdentityDetectionSettings | None = None,
):
    return resolve_face_pipeline_knobs(
        face_pipeline=face_pipeline,
        clustering=clustering or ClusteringSettings(),
        clustering_limits=clustering_limits or ClusteringLimitsSettings(),
        identity_detection=identity_detection or IdentityDetectionSettings(),
    )


def test_default_knobs_seed_legacy_placeholders() -> None:
    settings = FacePipelineSettings()
    assert settings.profile == "insightface"
    assert settings.face_similarity_threshold == 0.55
    assert settings.face_complete_link_threshold == 0.45
    assert settings.face_suggestion_floor == 0.35
    assert settings.face_suggestion_ceiling == 0.55
    assert settings.face_limits_similarity_threshold == 0.6
    assert settings.face_detection_default_threshold == 0.45
    assert settings.oact_coefficient == 0.0
    assert settings.factor_floor_sharpness == 0.0
    assert settings.factor_floor_embedding_norm == 0.0
    assert settings.factor_ceiling_occlusion == 1.0
    assert settings.joint_assignment_enabled is True


def test_resolve_insightface_uses_shared_anchors_not_face_overrides() -> None:
    clustering = ClusteringSettings(
        similarity_threshold=0.61,
        complete_link_threshold=0.41,
        suggestion_floor=0.31,
        suggestion_ceiling=0.51,
    )
    limits = ClusteringLimitsSettings(similarity_threshold=0.71)
    detection = IdentityDetectionSettings(default_threshold=0.41)
    face = FacePipelineSettings(
        profile="insightface",
        face_similarity_threshold=0.99,
        face_complete_link_threshold=0.98,
        face_suggestion_floor=0.10,
        face_suggestion_ceiling=0.20,
        face_limits_similarity_threshold=0.97,
        face_detection_default_threshold=0.96,
        oact_coefficient=0.25,
        joint_assignment_enabled=False,
    )

    knobs = _resolve(
        face,
        clustering=clustering,
        clustering_limits=limits,
        identity_detection=detection,
    )

    assert knobs.profile == "insightface"
    assert knobs.similarity_threshold == 0.61
    assert knobs.complete_link_threshold == 0.41
    assert knobs.suggestion_floor == 0.31
    assert knobs.suggestion_ceiling == 0.51
    assert knobs.limits_similarity_threshold == 0.71
    assert knobs.detection_default_threshold == 0.41
    # Non-threshold surface always from FacePipelineSettings.
    assert knobs.oact_coefficient == 0.25
    assert knobs.joint_assignment_enabled is False


def test_resolve_face_pipeline_uses_overrides_not_shared_anchors() -> None:
    clustering = ClusteringSettings(
        similarity_threshold=0.61,
        complete_link_threshold=0.41,
        suggestion_floor=0.31,
        suggestion_ceiling=0.51,
    )
    limits = ClusteringLimitsSettings(similarity_threshold=0.71)
    detection = IdentityDetectionSettings(default_threshold=0.41)
    face = FacePipelineSettings(
        profile="face_pipeline",
        face_similarity_threshold=0.72,
        face_complete_link_threshold=0.52,
        face_suggestion_floor=0.42,
        face_suggestion_ceiling=0.62,
        face_limits_similarity_threshold=0.82,
        face_detection_default_threshold=0.48,
        oact_coefficient=0.1,
        factor_floor_sharpness=12.0,
        factor_floor_embedding_norm=3.0,
        factor_ceiling_occlusion=0.8,
        joint_assignment_enabled=True,
    )

    knobs = _resolve(
        face,
        clustering=clustering,
        clustering_limits=limits,
        identity_detection=detection,
    )

    assert knobs.profile == "face_pipeline"
    assert knobs.similarity_threshold == 0.72
    assert knobs.complete_link_threshold == 0.52
    assert knobs.suggestion_floor == 0.42
    assert knobs.suggestion_ceiling == 0.62
    assert knobs.limits_similarity_threshold == 0.82
    assert knobs.detection_default_threshold == 0.48
    assert knobs.oact_coefficient == 0.1
    assert knobs.factor_floor_sharpness == 12.0
    assert knobs.factor_floor_embedding_norm == 3.0
    assert knobs.factor_ceiling_occlusion == 0.8
    assert knobs.joint_assignment_enabled is True


@pytest.mark.parametrize(
    "field_name,bad",
    [
        ("face_similarity_threshold", -0.01),
        ("face_similarity_threshold", 1.01),
        ("face_similarity_threshold", math.nan),
        ("face_similarity_threshold", math.inf),
        ("face_similarity_threshold", "abc"),
        ("face_complete_link_threshold", 2.0),
        ("face_suggestion_floor", -1.0),
        ("face_suggestion_ceiling", 1.5),
        ("face_limits_similarity_threshold", math.nan),
        ("face_detection_default_threshold", "nope"),
        ("factor_ceiling_occlusion", 1.1),
        ("oact_coefficient", math.nan),
        ("oact_coefficient", math.inf),
        ("oact_coefficient", "x"),
        ("factor_floor_sharpness", -1.0),
        ("factor_floor_embedding_norm", math.nan),
        ("joint_assignment_enabled", 1),
        ("joint_assignment_enabled", "true"),
        ("joint_assignment_enabled", 0),
    ],
)
def test_knob_validation_fail_closed(field_name: str, bad: object) -> None:
    with pytest.raises(ValidationError):
        FacePipelineSettings(**{field_name: bad})


def test_suggestion_band_floor_above_ceiling_rejected() -> None:
    with pytest.raises(ValidationError):
        FacePipelineSettings(face_suggestion_floor=0.8, face_suggestion_ceiling=0.4)


def test_valid_joint_assignment_bool_accepted() -> None:
    assert FacePipelineSettings(joint_assignment_enabled=False).joint_assignment_enabled is False
    assert FacePipelineSettings(joint_assignment_enabled=True).joint_assignment_enabled is True
