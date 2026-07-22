"""FIR-6 wave-0: FacePipelineSettings knob surface + profile-resolution helper.

rg-008: fail-closed validation at load. Discrimination: face_pipeline overrides
move effective thresholds; insightface keeps shared anchors.
Legacy placeholder constants are pinned to shared-settings defaults via a
drift-guard (M-06 / TEST-15) — not by reading ClusteringSettings at runtime
into FacePipelineSettings defaults.
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

_KNOB_ENV_KEYS = (
    "RECOGNITION_FACE_SIMILARITY_THRESHOLD",
    "RECOGNITION_FACE_COMPLETE_LINK_THRESHOLD",
    "RECOGNITION_FACE_SUGGESTION_FLOOR",
    "RECOGNITION_FACE_SUGGESTION_CEILING",
    "RECOGNITION_FACE_LIMITS_SIMILARITY_THRESHOLD",
    "RECOGNITION_FACE_DETECTION_DEFAULT_THRESHOLD",
    "RECOGNITION_FACE_OACT_COEFFICIENT",
    "RECOGNITION_FACE_FACTOR_FLOOR_SHARPNESS",
    "RECOGNITION_FACE_FACTOR_FLOOR_EMBEDDING_NORM",
    "RECOGNITION_FACE_FACTOR_CEILING_OCCLUSION",
    "RECOGNITION_FACE_JOINT_ASSIGNMENT_ENABLED",
)


@pytest.fixture(autouse=True)
def _clear_knob_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate default-factory env reads from the ambient process environment."""
    for key in _KNOB_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("RECOGNITION_FACE_PIPELINE_PROFILE", raising=False)


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


def test_legacy_knob_placeholders_match_shared_anchor_defaults() -> None:
    """Drift-guard: FacePipelineSettings defaults pin buffalo-era shared anchors.

    _LEGACY_* constants are a second source of truth by design (S4 apply-commit
    replaces face_pipeline values without mutating ClusteringSettings). This test
    goes red if a shared anchor default changes without updating the placeholders —
    preserving the numeric no-op property of the pre-S4 switch-over (TEST-15 / M-06).
    """
    clustering = ClusteringSettings()
    limits = ClusteringLimitsSettings()
    detection = IdentityDetectionSettings()
    face = FacePipelineSettings()

    assert face.face_similarity_threshold == clustering.similarity_threshold
    assert face.face_complete_link_threshold == clustering.complete_link_threshold
    assert face.face_suggestion_floor == clustering.suggestion_floor
    assert face.face_suggestion_ceiling == clustering.suggestion_ceiling
    assert face.face_limits_similarity_threshold == limits.similarity_threshold
    assert face.face_detection_default_threshold == detection.default_threshold


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


def test_suggestion_band_floor_equals_ceiling_accepted() -> None:
    settings = FacePipelineSettings(face_suggestion_floor=0.5, face_suggestion_ceiling=0.5)
    assert settings.face_suggestion_floor == 0.5
    assert settings.face_suggestion_ceiling == 0.5


def test_valid_joint_assignment_bool_accepted() -> None:
    assert FacePipelineSettings(joint_assignment_enabled=False).joint_assignment_enabled is False
    assert FacePipelineSettings(joint_assignment_enabled=True).joint_assignment_enabled is True


@pytest.mark.parametrize(
    "env_key,attr,raw,expected",
    [
        ("RECOGNITION_FACE_SIMILARITY_THRESHOLD", "face_similarity_threshold", "0.71", 0.71),
        ("RECOGNITION_FACE_COMPLETE_LINK_THRESHOLD", "face_complete_link_threshold", "0.41", 0.41),
        ("RECOGNITION_FACE_SUGGESTION_FLOOR", "face_suggestion_floor", "0.32", 0.32),
        ("RECOGNITION_FACE_SUGGESTION_CEILING", "face_suggestion_ceiling", "0.62", 0.62),
        ("RECOGNITION_FACE_LIMITS_SIMILARITY_THRESHOLD", "face_limits_similarity_threshold", "0.77", 0.77),
        ("RECOGNITION_FACE_DETECTION_DEFAULT_THRESHOLD", "face_detection_default_threshold", "0.39", 0.39),
        ("RECOGNITION_FACE_OACT_COEFFICIENT", "oact_coefficient", "0.15", 0.15),
        ("RECOGNITION_FACE_FACTOR_FLOOR_SHARPNESS", "factor_floor_sharpness", "12.5", 12.5),
        ("RECOGNITION_FACE_FACTOR_FLOOR_EMBEDDING_NORM", "factor_floor_embedding_norm", "3.25", 3.25),
        ("RECOGNITION_FACE_FACTOR_CEILING_OCCLUSION", "factor_ceiling_occlusion", "0.88", 0.88),
        ("RECOGNITION_FACE_JOINT_ASSIGNMENT_ENABLED", "joint_assignment_enabled", "false", False),
        ("RECOGNITION_FACE_JOINT_ASSIGNMENT_ENABLED", "joint_assignment_enabled", "true", True),
    ],
)
def test_knob_env_ingestion(
    monkeypatch: pytest.MonkeyPatch,
    env_key: str,
    attr: str,
    raw: str,
    expected: object,
) -> None:
    monkeypatch.setenv(env_key, raw)
    settings = FacePipelineSettings()
    assert getattr(settings, attr) == expected


@pytest.mark.parametrize(
    "env_key,raw",
    [
        ("RECOGNITION_FACE_SIMILARITY_THRESHOLD", ""),
        ("RECOGNITION_FACE_SIMILARITY_THRESHOLD", "   "),
        ("RECOGNITION_FACE_SIMILARITY_THRESHOLD", "not-a-float"),
        ("RECOGNITION_FACE_SIMILARITY_THRESHOLD", "1.5"),
        ("RECOGNITION_FACE_OACT_COEFFICIENT", ""),
        ("RECOGNITION_FACE_OACT_COEFFICIENT", "nan"),
        ("RECOGNITION_FACE_FACTOR_FLOOR_SHARPNESS", "-1"),
        ("RECOGNITION_FACE_FACTOR_FLOOR_SHARPNESS", ""),
        ("RECOGNITION_FACE_JOINT_ASSIGNMENT_ENABLED", ""),
        ("RECOGNITION_FACE_JOINT_ASSIGNMENT_ENABLED", "1"),
        ("RECOGNITION_FACE_JOINT_ASSIGNMENT_ENABLED", "yes"),
        ("RECOGNITION_FACE_JOINT_ASSIGNMENT_ENABLED", "True"),
    ],
)
def test_knob_env_fail_closed(monkeypatch: pytest.MonkeyPatch, env_key: str, raw: str) -> None:
    monkeypatch.setenv(env_key, raw)
    with pytest.raises((ValidationError, ValueError)):
        FacePipelineSettings()
