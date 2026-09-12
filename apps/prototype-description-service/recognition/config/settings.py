"""
Consolidated settings for the recognition service.

All algorithm thresholds and detection parameters are defined here with
type-safe defaults. Override by instantiating with explicit values in code.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from recognition.application.settings import (
    ENROLLMENT_NOOP_CEILING_OCCLUSION,
    ENROLLMENT_NOOP_FLOOR_EMBEDDING_NORM,
    ENROLLMENT_NOOP_FLOOR_SHARPNESS,
    ClusteringSettings,
    QualitySettings,
)
from recognition.application.settings.scan import ScanSettings
from recognition.infrastructure.face_pipeline._common import (
    DEFAULT_NMS_THRESHOLD,
    DEFAULT_SCORE_THRESHOLD,
    DEFAULT_TOP_K,
)
from recognition.infrastructure.face_pipeline.provenance import DEFAULT_MODELS_DIR

_FACE_PIPELINE_PROFILES: frozenset[str] = frozenset({"insightface", "face_pipeline"})

# Legacy insightface anchors (seeded onto FacePipelineSettings as dark placeholders;
# S4 replaces face_pipeline values via a calibration apply-commit — never mutate these).
_LEGACY_SIMILARITY_THRESHOLD = 0.55
_LEGACY_COMPLETE_LINK_THRESHOLD = 0.45
_LEGACY_SUGGESTION_FLOOR = 0.35
_LEGACY_SUGGESTION_CEILING = 0.55
_LEGACY_LIMITS_SIMILARITY_THRESHOLD = 0.6
_LEGACY_DETECTION_DEFAULT_THRESHOLD = 0.45

# No-op factor floors (aliases of the canonical enrollment triple — FIR6S3B-M-02).
_NOOP_FACTOR_FLOOR = ENROLLMENT_NOOP_FLOOR_SHARPNESS
_NOOP_OCCLUSION_CEILING = ENROLLMENT_NOOP_CEILING_OCCLUSION


def _resolve_insightface_cache_root() -> Path:
    """Resolve the InsightFace root cache dir from env or the legacy default."""
    explicit_cache_dir = os.environ.get("INSIGHTFACE_CACHE_DIR", "").strip()
    if explicit_cache_dir:
        return Path(explicit_cache_dir)

    explicit_home = os.environ.get("INSIGHTFACE_HOME", "").strip()
    if explicit_home:
        return Path(explicit_home)

    return Path.home() / ".insightface"


def _resolve_face_pipeline_profile() -> str:
    """Read RECOGNITION_FACE_PIPELINE_PROFILE; fail closed on unknown values (rg-008)."""
    raw = os.environ.get("RECOGNITION_FACE_PIPELINE_PROFILE", "insightface").strip()
    if raw not in _FACE_PIPELINE_PROFILES:
        raise ValueError(
            f"Invalid RECOGNITION_FACE_PIPELINE_PROFILE={raw!r}; allowed values: {sorted(_FACE_PIPELINE_PROFILES)}"
        )
    return raw


def _resolve_face_pipeline_models_dir() -> Path | None:
    """Optional models dir override; None means face_pipeline DEFAULT_MODELS_DIR."""
    raw = os.environ.get("RECOGNITION_FACE_PIPELINE_MODELS_DIR", "").strip()
    if not raw:
        return None
    return Path(raw)


def _resolve_embedding_dimension() -> int:
    """Bind identity_detection.embedding_dimension to DatabaseSettings.pgvector_dimension.

    PGVECTOR_DIM is the sole dimension root. RECOGNITION_EMBEDDING_DIMENSION is
    ignored so it cannot create a second root.
    """
    from db.settings import get_database_settings

    return int(get_database_settings().pgvector_dimension)


def _resolve_face_pipeline_timeout_s() -> float:
    """Default detector timeout matches the incumbent embedding timeout source."""
    from db.settings import get_database_settings

    return float(get_database_settings().embedding_timeout_s)


def _resolve_face_pipeline_max_workers() -> int:
    """Read RECOGNITION_FACE_PIPELINE_MAX_WORKERS; fail closed on empty/malformed/<=0."""
    raw = os.environ.get("RECOGNITION_FACE_PIPELINE_MAX_WORKERS")
    if raw is None:
        return 2
    stripped = raw.strip()
    if not stripped:
        raise ValueError(
            "Invalid RECOGNITION_FACE_PIPELINE_MAX_WORKERS: empty value; "
            "must be a positive integer"
        )
    # Reject floats ("1.5") and non-numeric tokens; only optional sign + digits.
    if stripped[0] in "+-" and not stripped[1:].isdigit():
        raise ValueError(
            f"Invalid RECOGNITION_FACE_PIPELINE_MAX_WORKERS={raw!r}; must be a positive integer"
        )
    if stripped[0] not in "+-" and not stripped.isdigit():
        raise ValueError(
            f"Invalid RECOGNITION_FACE_PIPELINE_MAX_WORKERS={raw!r}; must be a positive integer"
        )
    value = int(stripped)
    if value <= 0:
        raise ValueError(
            f"Invalid RECOGNITION_FACE_PIPELINE_MAX_WORKERS={value}; must be a positive integer"
        )
    return value


class InsightFaceSettings(BaseModel):
    """Settings for InsightFace face detection and embedding."""

    model_name: str = Field(default="buffalo_l", description="InsightFace model to use.")
    # NOTE: Changed from "auto" to "cpu" to bypass CoreML compilation errors on macOS
    device: str = Field(default="cpu", description="Device: 'auto', 'cpu', 'cuda', 'mps'.")
    cache_dir: Path = Field(
        default_factory=_resolve_insightface_cache_root, description="InsightFace root cache directory."
    )
    providers: list[str] = Field(default_factory=list, description="ONNX providers (empty = auto-detect).")
    det_thresh: float = Field(default=0.5, description="Face detection confidence threshold.")
    det_size: tuple[int, int] = Field(default=(640, 640), description="Detection input size.")

    @property
    def model_cache_dir(self) -> Path:
        """Return the bundle parent that should contain `<model_name>/`."""
        return self.cache_dir / "models"


def _parse_finite_float(value: object, *, field_name: str) -> float:
    """Parse a finite float; reject bool, non-numeric, NaN, and Inf (rg-008)."""
    if isinstance(value, bool):
        raise ValueError(f"Invalid face_pipeline {field_name}={value!r}; must be a finite number")
    if isinstance(value, str):
        stripped = value.strip()
        try:
            value = float(stripped)
        except ValueError as exc:
            raise ValueError(
                f"Invalid face_pipeline {field_name}={value!r}; must be a finite number"
            ) from exc
    if isinstance(value, int):
        value = float(value)
    if not isinstance(value, float):
        raise ValueError(f"Invalid face_pipeline {field_name}={value!r}; must be a finite number")
    if not math.isfinite(value):
        raise ValueError(f"Invalid face_pipeline {field_name}={value!r}; must be a finite number")
    return value


def _parse_unit_interval(value: object, *, field_name: str) -> float:
    """Parse a finite float in [0.0, 1.0] (rg-008 fail-closed)."""
    parsed = _parse_finite_float(value, field_name=field_name)
    if parsed < 0.0 or parsed > 1.0:
        raise ValueError(f"Invalid face_pipeline {field_name}={value!r}; must be in [0.0, 1.0]")
    return parsed


def _parse_non_negative_finite(value: object, *, field_name: str) -> float:
    """Parse a finite float >= 0 (rg-008 fail-closed)."""
    parsed = _parse_finite_float(value, field_name=field_name)
    if parsed < 0.0:
        raise ValueError(f"Invalid face_pipeline {field_name}={value!r}; must be >= 0")
    return parsed


def _parse_bool(value: object, *, field_name: str) -> bool:
    """Parse a strict bool; reject 0/1 and stringy truthiness (rg-008)."""
    if isinstance(value, bool):
        return value
    raise ValueError(f"Invalid face_pipeline {field_name}={value!r}; must be a boolean")


def _env_or_default_unit(env_key: str, default: float) -> float:
    """Read a unit-interval float env var; unset → default; empty/malformed → fail closed."""
    raw = os.environ.get(env_key)
    if raw is None:
        return default
    stripped = raw.strip()
    if not stripped:
        raise ValueError(f"Invalid {env_key}: empty value; must be a finite number in [0.0, 1.0]")
    return _parse_unit_interval(stripped, field_name=env_key)


def _env_or_default_finite(env_key: str, default: float) -> float:
    """Read a finite float env var; unset → default; empty/malformed → fail closed."""
    raw = os.environ.get(env_key)
    if raw is None:
        return default
    stripped = raw.strip()
    if not stripped:
        raise ValueError(f"Invalid {env_key}: empty value; must be a finite number")
    return _parse_finite_float(stripped, field_name=env_key)


def _env_or_default_nonneg(env_key: str, default: float) -> float:
    """Read a non-negative finite float env var; unset → default; empty/malformed → fail closed."""
    raw = os.environ.get(env_key)
    if raw is None:
        return default
    stripped = raw.strip()
    if not stripped:
        raise ValueError(f"Invalid {env_key}: empty value; must be a finite number >= 0")
    return _parse_non_negative_finite(stripped, field_name=env_key)


def _env_or_default_bool(env_key: str, default: bool) -> bool:
    """Read a strict true/false env var; unset → default; empty/other → fail closed."""
    raw = os.environ.get(env_key)
    if raw is None:
        return default
    stripped = raw.strip()
    if not stripped:
        raise ValueError(f"Invalid {env_key}: empty value; must be 'true' or 'false'")
    if stripped == "true":
        return True
    if stripped == "false":
        return False
    raise ValueError(f"Invalid {env_key}={raw!r}; must be 'true' or 'false'")


def _resolve_face_similarity_threshold() -> float:
    return _env_or_default_unit("RECOGNITION_FACE_SIMILARITY_THRESHOLD", _LEGACY_SIMILARITY_THRESHOLD)


def _resolve_face_complete_link_threshold() -> float:
    return _env_or_default_unit("RECOGNITION_FACE_COMPLETE_LINK_THRESHOLD", _LEGACY_COMPLETE_LINK_THRESHOLD)


def _resolve_face_suggestion_floor() -> float:
    return _env_or_default_unit("RECOGNITION_FACE_SUGGESTION_FLOOR", _LEGACY_SUGGESTION_FLOOR)


def _resolve_face_suggestion_ceiling() -> float:
    return _env_or_default_unit("RECOGNITION_FACE_SUGGESTION_CEILING", _LEGACY_SUGGESTION_CEILING)


def _resolve_face_limits_similarity_threshold() -> float:
    return _env_or_default_unit(
        "RECOGNITION_FACE_LIMITS_SIMILARITY_THRESHOLD", _LEGACY_LIMITS_SIMILARITY_THRESHOLD
    )


def _resolve_face_detection_default_threshold() -> float:
    return _env_or_default_unit(
        "RECOGNITION_FACE_DETECTION_DEFAULT_THRESHOLD", _LEGACY_DETECTION_DEFAULT_THRESHOLD
    )


def _resolve_face_oact_coefficient() -> float:
    # Non-negative only: negative would *reward* occlusion (FIR6S1-M-02).
    return _env_or_default_nonneg("RECOGNITION_FACE_OACT_COEFFICIENT", 0.0)


def _resolve_face_factor_floor_sharpness() -> float:
    return _env_or_default_nonneg("RECOGNITION_FACE_FACTOR_FLOOR_SHARPNESS", _NOOP_FACTOR_FLOOR)


def _resolve_face_factor_floor_embedding_norm() -> float:
    return _env_or_default_nonneg("RECOGNITION_FACE_FACTOR_FLOOR_EMBEDDING_NORM", _NOOP_FACTOR_FLOOR)


def _resolve_face_factor_ceiling_occlusion() -> float:
    return _env_or_default_unit("RECOGNITION_FACE_FACTOR_CEILING_OCCLUSION", _NOOP_OCCLUSION_CEILING)


def _resolve_face_joint_assignment_enabled() -> bool:
    return _env_or_default_bool("RECOGNITION_FACE_JOINT_ASSIGNMENT_ENABLED", True)


class FacePipelineSettings(BaseModel):
    """Dark-launch settings for the FIR-3 YuNet+SFace runtime (FIR-4 S2 / FIR-6 knobs).

    Production default profile remains ``insightface``. Flat env vars follow the
    existing ``RecognitionSettings`` convention (no nested pydantic-settings delimiter).

    Face-pipeline-scoped threshold overrides (seeded with legacy buffalo-era values)
    are resolved via :func:`resolve_face_pipeline_knobs`. Shared ClusteringSettings /
    IdentityDetectionSettings / ClusteringLimitsSettings anchors stay untouched until
    S6 switch-over.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    profile: Literal["insightface", "face_pipeline"] = Field(
        default_factory=_resolve_face_pipeline_profile,  # type: ignore[arg-type]
        validate_default=True,
        description="Active face pipeline profile (dark default: insightface).",
    )
    models_dir: Path | None = Field(
        default_factory=_resolve_face_pipeline_models_dir,
        description="Override for face_pipeline ONNX models dir (None → DEFAULT_MODELS_DIR).",
    )
    score_threshold: float = Field(
        default=DEFAULT_SCORE_THRESHOLD,
        description="YuNet score threshold pass-through (FIR-3 default).",
    )
    nms_threshold: float = Field(
        default=DEFAULT_NMS_THRESHOLD,
        description="YuNet NMS threshold pass-through (FIR-3 default).",
    )
    top_k: int = Field(
        default=DEFAULT_TOP_K,
        description="YuNet top-k pass-through (FIR-3 default).",
    )
    timeout_s: float = Field(
        default_factory=_resolve_face_pipeline_timeout_s,
        description="Per-image detect timeout (defaults to DB_EMBEDDING_TIMEOUT_SECONDS).",
    )
    max_workers: int = Field(
        default_factory=_resolve_face_pipeline_max_workers,
        description=(
            "Process-wide face_pipeline executor + admission capacity. "
            "Env: RECOGNITION_FACE_PIPELINE_MAX_WORKERS (default 2)."
        ),
    )

    # --- FIR-6 face_pipeline-scoped calibration surface (wave-0 precondition) ---
    # Defaults read RECOGNITION_FACE_* env (rg-008 fail-closed), same pattern as profile.
    face_similarity_threshold: float = Field(
        default_factory=_resolve_face_similarity_threshold,
        description=(
            "face_pipeline override for ClusteringSettings.similarity_threshold. "
            "Env: RECOGNITION_FACE_SIMILARITY_THRESHOLD."
        ),
    )
    face_complete_link_threshold: float = Field(
        default_factory=_resolve_face_complete_link_threshold,
        description=(
            "face_pipeline override for ClusteringSettings.complete_link_threshold. "
            "Env: RECOGNITION_FACE_COMPLETE_LINK_THRESHOLD."
        ),
    )
    face_suggestion_floor: float = Field(
        default_factory=_resolve_face_suggestion_floor,
        description=(
            "face_pipeline override for ClusteringSettings.suggestion_floor. "
            "Env: RECOGNITION_FACE_SUGGESTION_FLOOR."
        ),
    )
    face_suggestion_ceiling: float = Field(
        default_factory=_resolve_face_suggestion_ceiling,
        description=(
            "face_pipeline override for ClusteringSettings.suggestion_ceiling. "
            "Env: RECOGNITION_FACE_SUGGESTION_CEILING."
        ),
    )
    face_limits_similarity_threshold: float = Field(
        default_factory=_resolve_face_limits_similarity_threshold,
        description=(
            "face_pipeline override for ClusteringLimitsSettings.similarity_threshold. "
            "Env: RECOGNITION_FACE_LIMITS_SIMILARITY_THRESHOLD."
        ),
    )
    face_detection_default_threshold: float = Field(
        default_factory=_resolve_face_detection_default_threshold,
        description=(
            "face_pipeline override for IdentityDetectionSettings.default_threshold. "
            "Env: RECOGNITION_FACE_DETECTION_DEFAULT_THRESHOLD."
        ),
    )
    # FIR-17 S0: runtime applies this coefficient as tightening, matching the calibration harness.
    oact_coefficient: float = Field(
        default_factory=_resolve_face_oact_coefficient,
        description=(
            "OACT occlusion-adaptive coefficient (0.0 = dark no-op until S4; "
            "must be >= 0 — negative would reward occlusion). "
            "Env: RECOGNITION_FACE_OACT_COEFFICIENT."
        ),
    )
    factor_floor_sharpness: float = Field(
        default_factory=_resolve_face_factor_floor_sharpness,
        description=(
            "Enrollment sharpness floor (0.0 accepts everything until S4). "
            "Env: RECOGNITION_FACE_FACTOR_FLOOR_SHARPNESS."
        ),
    )
    factor_floor_embedding_norm: float = Field(
        default_factory=_resolve_face_factor_floor_embedding_norm,
        description=(
            "Enrollment embedding-norm floor (0.0 accepts everything until S4). "
            "Env: RECOGNITION_FACE_FACTOR_FLOOR_EMBEDDING_NORM."
        ),
    )
    factor_ceiling_occlusion: float = Field(
        default_factory=_resolve_face_factor_ceiling_occlusion,
        description=(
            "Enrollment occlusion ceiling (1.0 accepts full range until S4). "
            "Env: RECOGNITION_FACE_FACTOR_CEILING_OCCLUSION."
        ),
    )
    joint_assignment_enabled: bool = Field(
        default_factory=_resolve_face_joint_assignment_enabled,
        description=(
            "Within-photo one-to-one assignment under face_pipeline (S2 wiring). "
            "Env: RECOGNITION_FACE_JOINT_ASSIGNMENT_ENABLED (true|false)."
        ),
    )

    @field_validator("profile", mode="before")
    @classmethod
    def _validate_profile(cls, value: object) -> object:
        if isinstance(value, str) and value not in _FACE_PIPELINE_PROFILES:
            raise ValueError(
                f"Invalid face_pipeline profile={value!r}; allowed values: {sorted(_FACE_PIPELINE_PROFILES)}"
            )
        return value

    @field_validator("max_workers", mode="before")
    @classmethod
    def _validate_max_workers(cls, value: object) -> object:
        """Fail closed on non-positive or non-integral capacity ([CFG-01/02])."""
        if isinstance(value, bool):
            raise ValueError(f"Invalid face_pipeline max_workers={value!r}; must be a positive integer")
        if isinstance(value, float):
            if not value.is_integer():
                raise ValueError(f"Invalid face_pipeline max_workers={value!r}; must be a positive integer")
            value = int(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped or (stripped[0] in "+-" and not stripped[1:].isdigit()) or (
                stripped[0] not in "+-" and not stripped.isdigit()
            ):
                raise ValueError(f"Invalid face_pipeline max_workers={value!r}; must be a positive integer")
            value = int(stripped)
        if not isinstance(value, int):
            raise ValueError(f"Invalid face_pipeline max_workers={value!r}; must be a positive integer")
        if value <= 0:
            raise ValueError(f"Invalid face_pipeline max_workers={value}; must be a positive integer")
        return value

    @field_validator("timeout_s", mode="before")
    @classmethod
    def _validate_timeout_s(cls, value: object) -> object:
        """Fail closed on non-finite or non-positive detect timeouts ([CFG-01/02], [RES-03])."""
        if isinstance(value, bool):
            raise ValueError(f"Invalid face_pipeline timeout_s={value!r}; must be a finite positive number")
        if isinstance(value, str):
            stripped = value.strip()
            try:
                value = float(stripped)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid face_pipeline timeout_s={value!r}; must be a finite positive number"
                ) from exc
        if isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        if not isinstance(value, float):
            raise ValueError(f"Invalid face_pipeline timeout_s={value!r}; must be a finite positive number")
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"Invalid face_pipeline timeout_s={value!r}; must be a finite positive number")
        return value

    @field_validator(
        "face_similarity_threshold",
        "face_complete_link_threshold",
        "face_suggestion_floor",
        "face_suggestion_ceiling",
        "face_limits_similarity_threshold",
        "face_detection_default_threshold",
        "factor_ceiling_occlusion",
        mode="before",
    )
    @classmethod
    def _validate_unit_interval_knobs(cls, value: object, info: object) -> float:
        field_name = getattr(info, "field_name", "threshold")
        return _parse_unit_interval(value, field_name=str(field_name))

    @field_validator("oact_coefficient", mode="before")
    @classmethod
    def _validate_oact_coefficient(cls, value: object) -> float:
        # Finite + non-negative: sign is semantic (negative rewards occlusion).
        return _parse_non_negative_finite(value, field_name="oact_coefficient")

    @field_validator(
        "factor_floor_sharpness",
        "factor_floor_embedding_norm",
        mode="before",
    )
    @classmethod
    def _validate_factor_floors(cls, value: object, info: object) -> float:
        field_name = getattr(info, "field_name", "factor_floor")
        return _parse_non_negative_finite(value, field_name=str(field_name))

    @field_validator("joint_assignment_enabled", mode="before")
    @classmethod
    def _validate_joint_assignment_enabled(cls, value: object) -> bool:
        return _parse_bool(value, field_name="joint_assignment_enabled")

    @model_validator(mode="after")
    def _validate_suggestion_band(self) -> FacePipelineSettings:
        """Fail closed when suggestion_floor > suggestion_ceiling (rg-008)."""
        if self.face_suggestion_floor > self.face_suggestion_ceiling:
            raise ValueError(
                "Invalid face_pipeline suggestion band: "
                f"face_suggestion_floor ({self.face_suggestion_floor}) > "
                f"face_suggestion_ceiling ({self.face_suggestion_ceiling})"
            )
        return self

    @property
    def resolved_models_dir(self) -> Path:
        """Models directory used for verified load (None → package DEFAULT_MODELS_DIR)."""
        return self.models_dir if self.models_dir is not None else DEFAULT_MODELS_DIR


@dataclass(frozen=True, slots=True)
class ResolvedFacePipelineKnobs:
    """Effective face-pipeline knobs after profile resolution.

    Under ``insightface`` the threshold fields read the shared buffalo-era anchors;
    ``oact_coefficient`` is forced to 0.0 and factor floors are forced to the
    canonical no-op triple (profile gate — residual face_pipeline-scored rows /
    env-set floors must not activate OACT or enrollment gating under insightface;
    FIR6S3B-M-02 / EMB-07). Under ``face_pipeline`` they read the
    FacePipelineSettings overrides including OACT and floors.
    ``joint_assignment_enabled`` always comes from FacePipelineSettings
    (consumers under insightface must still treat joint assignment as un-wired until S2).
    """

    profile: Literal["insightface", "face_pipeline"]
    similarity_threshold: float
    complete_link_threshold: float
    suggestion_floor: float
    suggestion_ceiling: float
    limits_similarity_threshold: float
    detection_default_threshold: float
    oact_coefficient: float
    factor_floor_sharpness: float
    factor_floor_embedding_norm: float
    factor_ceiling_occlusion: float
    joint_assignment_enabled: bool


def resolve_face_pipeline_knobs(
    *,
    face_pipeline: FacePipelineSettings,
    clustering: ClusteringSettings,
    clustering_limits: ClusteringLimitsSettings,
    identity_detection: IdentityDetectionSettings,
) -> ResolvedFacePipelineKnobs:
    """Resolve effective thresholds for the active face-pipeline profile (rg-008).

    Single ownership for S1/S2 consumers: mutate FacePipelineSettings overrides and
    re-resolve; insightface anchors are never silently replaced. OACT is profile-gated:
    only ``face_pipeline`` can surface a non-zero coefficient.
    """
    profile = face_pipeline.profile
    if profile == "face_pipeline":
        return ResolvedFacePipelineKnobs(
            profile=profile,
            similarity_threshold=float(face_pipeline.face_similarity_threshold),
            complete_link_threshold=float(face_pipeline.face_complete_link_threshold),
            suggestion_floor=float(face_pipeline.face_suggestion_floor),
            suggestion_ceiling=float(face_pipeline.face_suggestion_ceiling),
            limits_similarity_threshold=float(face_pipeline.face_limits_similarity_threshold),
            detection_default_threshold=float(face_pipeline.face_detection_default_threshold),
            oact_coefficient=float(face_pipeline.oact_coefficient),
            factor_floor_sharpness=float(face_pipeline.factor_floor_sharpness),
            factor_floor_embedding_norm=float(face_pipeline.factor_floor_embedding_norm),
            factor_ceiling_occlusion=float(face_pipeline.factor_ceiling_occlusion),
            joint_assignment_enabled=bool(face_pipeline.joint_assignment_enabled),
        )
    if profile == "insightface":
        return ResolvedFacePipelineKnobs(
            profile=profile,
            similarity_threshold=float(clustering.similarity_threshold),
            complete_link_threshold=float(clustering.complete_link_threshold),
            suggestion_floor=float(clustering.suggestion_floor),
            suggestion_ceiling=float(clustering.suggestion_ceiling),
            limits_similarity_threshold=float(clustering_limits.similarity_threshold),
            detection_default_threshold=float(identity_detection.default_threshold),
            # Profile gate: never activate OACT or enrollment floors under insightface
            # (FIR6S1-M-02, FIR6S3B-M-02). Env-set floors on FacePipelineSettings are
            # ignored here so S6 profile rollback stays dark even with residual factors.
            oact_coefficient=0.0,
            factor_floor_sharpness=float(ENROLLMENT_NOOP_FLOOR_SHARPNESS),
            factor_floor_embedding_norm=float(ENROLLMENT_NOOP_FLOOR_EMBEDDING_NORM),
            factor_ceiling_occlusion=float(ENROLLMENT_NOOP_CEILING_OCCLUSION),
            joint_assignment_enabled=bool(face_pipeline.joint_assignment_enabled),
        )
    # Defensive: pydantic already restricts profile; keep fail-closed for callers.
    raise ValueError(
        f"Invalid face_pipeline profile={profile!r}; allowed values: {sorted(_FACE_PIPELINE_PROFILES)}"
    )


def apply_resolved_clustering_settings(
    clustering: ClusteringSettings,
    knobs: ResolvedFacePipelineKnobs,
) -> ClusteringSettings:
    """Return ClusteringSettings with profile-resolved threshold fields (S2 rebinding)."""
    return clustering.model_copy(
        update={
            "similarity_threshold": knobs.similarity_threshold,
            "complete_link_threshold": knobs.complete_link_threshold,
            "suggestion_floor": knobs.suggestion_floor,
            "suggestion_ceiling": knobs.suggestion_ceiling,
        }
    )


def apply_resolved_limits_settings(
    limits: ClusteringLimitsSettings,
    knobs: ResolvedFacePipelineKnobs,
) -> ClusteringLimitsSettings:
    """Return ClusteringLimitsSettings with profile-resolved similarity threshold."""
    return limits.model_copy(update={"similarity_threshold": knobs.limits_similarity_threshold})


def apply_resolved_detection_settings(
    detection: IdentityDetectionSettings,
    knobs: ResolvedFacePipelineKnobs,
) -> IdentityDetectionSettings:
    """Return IdentityDetectionSettings with profile-resolved default threshold."""
    return detection.model_copy(update={"default_threshold": knobs.detection_default_threshold})


def resolve_effective_clustering_settings(
    *,
    recognition: RecognitionSettings | None = None,
) -> ClusteringSettings:
    """Profile-resolved ClusteringSettings for gate/discovery construction (S2)."""
    settings = recognition if recognition is not None else RecognitionSettings()
    knobs = resolve_face_pipeline_knobs(
        face_pipeline=settings.face_pipeline,
        clustering=settings.clustering,
        clustering_limits=settings.clustering_limits,
        identity_detection=settings.identity_detection,
    )
    return apply_resolved_clustering_settings(settings.clustering, knobs)


def resolve_effective_limits_settings(
    *,
    recognition: RecognitionSettings | None = None,
) -> ClusteringLimitsSettings:
    """Profile-resolved ClusteringLimitsSettings for limits-threshold readers (S2)."""
    settings = recognition if recognition is not None else RecognitionSettings()
    knobs = resolve_face_pipeline_knobs(
        face_pipeline=settings.face_pipeline,
        clustering=settings.clustering,
        clustering_limits=settings.clustering_limits,
        identity_detection=settings.identity_detection,
    )
    return apply_resolved_limits_settings(settings.clustering_limits, knobs)


def resolve_effective_detection_settings(
    *,
    recognition: RecognitionSettings | None = None,
) -> IdentityDetectionSettings:
    """Profile-resolved IdentityDetectionSettings for detection-threshold readers (S2)."""
    settings = recognition if recognition is not None else RecognitionSettings()
    knobs = resolve_face_pipeline_knobs(
        face_pipeline=settings.face_pipeline,
        clustering=settings.clustering,
        clustering_limits=settings.clustering_limits,
        identity_detection=settings.identity_detection,
    )
    return apply_resolved_detection_settings(settings.identity_detection, knobs)

def bridge_oact_into_quality_settings(
    quality: QualitySettings,
    knobs: ResolvedFacePipelineKnobs,
) -> QualitySettings:
    """Bridge profile-resolved OACT + enrollment floors into QualitySettings.

    S1: ``oact_coefficient`` (profile-gated; insightface forces 0.0).
    S3b: factor floors copy from resolved knobs (insightface forces the canonical
    no-op triple; face_pipeline copies FacePipelineSettings including S4 values).
    Base quality band knobs stay on ``ClusteringSettings.quality``; threshold
    rebinding is S2.
    """
    coeff = float(knobs.oact_coefficient)
    if coeff < 0.0:
        raise ValueError(
            f"Invalid oact_coefficient={coeff!r}; must be >= 0 (negative rewards occlusion)"
        )
    floor_s = float(knobs.factor_floor_sharpness)
    floor_n = float(knobs.factor_floor_embedding_norm)
    ceil_o = float(knobs.factor_ceiling_occlusion)
    updates: dict[str, float] = {}
    if float(quality.oact_coefficient) != coeff:
        updates["oact_coefficient"] = coeff
    if float(quality.factor_floor_sharpness) != floor_s:
        updates["factor_floor_sharpness"] = floor_s
    if float(quality.factor_floor_embedding_norm) != floor_n:
        updates["factor_floor_embedding_norm"] = floor_n
    if float(quality.factor_ceiling_occlusion) != ceil_o:
        updates["factor_ceiling_occlusion"] = ceil_o
    if not updates:
        return quality
    return quality.model_copy(update=updates)


def apply_oact_bridge_to_clustering(
    clustering: ClusteringSettings,
    knobs: ResolvedFacePipelineKnobs,
) -> ClusteringSettings:
    """Return clustering settings with OACT + enrollment floors bridged.

    Wiring path for ``ConfidenceCheck`` / ``AssignmentGate`` / S3b enrollment:
    call after :func:`resolve_face_pipeline_knobs` so runtime knobs are profile-aware.
    """
    quality = bridge_oact_into_quality_settings(clustering.quality, knobs)
    if quality is clustering.quality:
        return clustering
    return clustering.model_copy(update={"quality": quality})


class IdentityDetectionSettings(BaseModel):
    """Settings for identity detection and embedding generation."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    default_threshold: float = Field(default=0.45, description="Default detection confidence threshold.")
    max_identities_per_image: int = Field(default=999, description="Maximum faces to detect per image.")
    embedding_dimension: int = Field(
        default_factory=_resolve_embedding_dimension,
        description=(
            "Embedding vector dimension (face identity only). "
            "Derived from PGVECTOR_DIM / DatabaseSettings.pgvector_dimension."
        ),
    )
    max_candidates: int = Field(default=10, description="Maximum candidate matches to consider.")


class ClusteringLimitsSettings(BaseModel):
    """Settings for cluster size limits (separate from threshold tuning)."""

    similarity_threshold: float = Field(default=0.6, description="Base similarity threshold for initial grouping.")
    min_cluster_size: int = Field(default=2, description="Minimum members for a valid cluster.")
    max_cluster_size: int = Field(default=1000, description="Maximum members per cluster.")


_DEFAULT_UPLOAD_MIME_TYPES: tuple[str, ...] = (
    "image/jpeg",
    "image/png",
    "image/webp",
)


def _parse_allowed_upload_mime_types(raw: str) -> list[str]:
    """Parse RECOGNITION_ALLOWED_UPLOAD_MIME_TYPES into a list.

    Comma-separated; per-item whitespace stripped; empty / whitespace-only
    input returns the safe default (so a misconfigured env var cannot
    silently disable every upload).
    """
    items = [chunk.strip() for chunk in raw.split(",") if chunk.strip()]
    if not items:
        return list(_DEFAULT_UPLOAD_MIME_TYPES)
    return items


class RecognitionSettings(BaseModel):
    """Top-level recognition settings container."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    insightface: InsightFaceSettings = Field(default_factory=InsightFaceSettings)
    face_pipeline: FacePipelineSettings = Field(default_factory=FacePipelineSettings)
    identity_detection: IdentityDetectionSettings = Field(default_factory=IdentityDetectionSettings)
    clustering_limits: ClusteringLimitsSettings = Field(default_factory=ClusteringLimitsSettings)
    clustering: ClusteringSettings = Field(default_factory=ClusteringSettings)
    scan: ScanSettings = Field(default_factory=ScanSettings)
    retention_export_max_identities: int = Field(
        default=50000,
        description="Max identities allowed for synchronous retention export responses.",
    )
    default_retention_mode: Literal["retain_all", "dispose_after_ack", "purge_on_demand"] = Field(
        default_factory=lambda: os.environ.get("RECOGNITION_DEFAULT_RETENTION_MODE", "retain_all"),
        validate_default=True,
    )

    # Runtime mode: "production" uses real InsightFace, "test" uses stubs
    runtime_mode: str = Field(default_factory=lambda: os.environ.get("RECOGNITION_RUNTIME_MODE", "production"))

    # E15-11: filesystem ObjectStore root. Multipart-uploaded image bytes are
    # written under <blob_root>/<tenant_id>/<job_id>/<media_id>.bin and
    # cleaned up by the worker after the scan completes or fails.
    blob_root: Path = Field(
        default_factory=lambda: Path(os.environ.get("RECOGNITION_BLOB_ROOT", "/tmp/acx-recognition-blobs")),
        description="Filesystem root for the ObjectStore (multipart upload transport).",
    )

    # E15-11: per-request body cap on the multipart variant of /recognition/analyze.
    max_upload_bytes: int = Field(
        default_factory=lambda: int(os.environ.get("RECOGNITION_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))),
        description="Reject multipart requests with Content-Length above this value.",
    )

    # E15-11: allowed image MIME types for multipart upload parts.
    # Override via comma-separated env var, e.g.
    # `RECOGNITION_ALLOWED_UPLOAD_MIME_TYPES=image/jpeg,image/heic,image/avif`.
    # Whitespace-only or unset values fall back to the safe default to avoid
    # accidentally rejecting every upload.
    allowed_upload_mime_types: list[str] = Field(
        default_factory=lambda: _parse_allowed_upload_mime_types(
            os.environ.get("RECOGNITION_ALLOWED_UPLOAD_MIME_TYPES", "")
        ),
        description="MIME allow-list for image_<media_id> parts on the multipart route.",
    )

    @model_validator(mode="after")
    def _check_embedding_pgvector_pair(self) -> RecognitionSettings:
        """Fail fast when identity embedding dim != DB pgvector dim (CR-09).

        Lazy-import db settings to avoid import cycles at module load.
        Pairing is profile-independent (insightface and face_pipeline).
        """
        from db.settings import get_database_settings

        pg_dim = int(get_database_settings().pgvector_dimension)
        id_dim = int(self.identity_detection.embedding_dimension)
        if id_dim != pg_dim:
            raise ValueError(f"identity_detection.embedding_dimension ({id_dim}) != pgvector_dimension ({pg_dim})")
        return self
