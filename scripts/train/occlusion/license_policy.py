"""FIR-7 Slice 0a: license allow/denylist as code constants + pure audit functions.

Pure constants and pure functions only. No network calls, no model downloads,
no filesystem scanning outside an explicitly passed-in manifest path.

Enforces commercial-clean provenance for occlusion training data, detector
ingest (Detector A/B + person→face cascade), occluder assets at pack-build,
and tooling dependencies (diagnostic, not training data).

Operator clearance: ``dcface_operator_clearance_20260723`` flips DCFace to
commercial-allowed; residual FFHQ/CASIA generator lineage is disclosed in the
informational ``generator_lineage`` field (exempt from research-source rejection).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


# ---------------------------------------------------------------------------
# Enums (sr-007 — no magic-string verdicts/categories)
# ---------------------------------------------------------------------------


class PolicyCategory(StrEnum):
    """Policy surface a row or package is evaluated under."""

    TRAINING_DATA = "training_data"
    TOOLING = "tooling"
    MODEL_INGEST = "model_ingest"
    OCCLUDER_ASSET = "occluder_asset"
    SYNTHETIC_SOURCE = "synthetic_source"


class LicenseVerdict(StrEnum):
    """Pass/fail outcome of a license audit."""

    PASS = "pass"
    FAIL = "fail"


class RejectionReason(StrEnum):
    """Machine-checkable rejection reasons (asserted by RED-capable tests)."""

    NC_MODEL_DERIVED = "nc_model_derived"
    RESEARCH_ONLY_SOURCE = "research_only_source"
    RESEARCH_ONLY_LICENSE = "research_only_license"
    PENDING_LEGAL_CLEARANCE = "pending_legal_clearance"
    UNCLEARED_OCCLUDER_ASSET = "uncleared_occluder_asset"
    DENYLISTED_LICENSE = "denylisted_license"
    DENYLISTED_PACKAGE = "denylisted_package"
    MISSING_INGEST_ENTRY = "missing_ingest_entry"
    MISSING_LICENSE_FIELD = "missing_license_field"
    UNKNOWN_SPDX = "unknown_spdx"
    UNKNOWN_SOURCE = "unknown_source"
    INVALID_ROW = "invalid_row"


class ClearanceStatus(StrEnum):
    """Clearance state for synthetic sources and assets."""

    ALLOWED = "allowed"
    DENIED = "denied"
    PENDING_LEGAL_CLEARANCE = "pending_legal_clearance"
    OPERATOR_CLEARED = "operator_cleared"
    UNCLEARED = "uncleared"
    CLEARED = "cleared"
    LICENSE_CLEARED = "license_cleared"


class CommercialUse(StrEnum):
    """Commercial-use classification for registered entries."""

    ALLOWED = "allowed"
    NON_COMMERCIAL = "non_commercial"
    FORBIDDEN = "forbidden"


class DetectorRole(StrEnum):
    """Role of a registered model-ingest entry."""

    FACE_DETECTOR = "face_detector"
    PERSON_DETECTOR = "person_detector"
    FACE_EMBEDDER = "face_embedder"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LicenseAuditResult:
    """Outcome of a pure license-policy check."""

    verdict: LicenseVerdict
    reason: RejectionReason | None = None
    detail: str = ""
    category: PolicyCategory | None = None

    @property
    def ok(self) -> bool:
        return self.verdict is LicenseVerdict.PASS


def _pass(
    *,
    detail: str = "",
    category: PolicyCategory | None = None,
) -> LicenseAuditResult:
    return LicenseAuditResult(
        verdict=LicenseVerdict.PASS,
        detail=detail,
        category=category,
    )


def _fail(
    reason: RejectionReason,
    *,
    detail: str = "",
    category: PolicyCategory | None = None,
) -> LicenseAuditResult:
    return LicenseAuditResult(
        verdict=LicenseVerdict.FAIL,
        reason=reason,
        detail=detail,
        category=category,
    )


class LicensePolicyError(Exception):
    """Raised when a caller requests a hard fail-closed audit (sr-006)."""

    def __init__(self, result: LicenseAuditResult) -> None:
        self.result = result
        message = result.detail or (
            result.reason.value if result.reason is not None else "license policy failure"
        )
        super().__init__(message)


# ---------------------------------------------------------------------------
# SPDX allow / deny lists (stored casefolded for SPDX case-insensitive rules)
# ---------------------------------------------------------------------------

# Commercially usable SPDX identifiers accepted for training data, model ingest,
# and occluder assets (after other gates). Canonical display forms kept for
# documentation; comparisons use the casefolded frozensets.
ALLOWED_SPDX_IDS: frozenset[str] = frozenset(
    {
        "Apache-2.0",
        "MIT",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "CC0-1.0",
        "CC-BY-4.0",
        "ISC",
        "Zlib",
        "Unlicense",
        "self-generated",  # operator-owned synthetic / internal renders
    }
)

# Explicitly rejected SPDX / license tags (AGPL, NC, research-only).
DENYLISTED_SPDX_IDS: frozenset[str] = frozenset(
    {
        "AGPL-3.0",
        "AGPL-3.0-only",
        "AGPL-3.0-or-later",
        "GPL-3.0",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
        "CC-BY-NC-4.0",
        "CC-BY-NC-SA-4.0",
        "CC-BY-NC-ND-4.0",
        "Non-Commercial",
        "non-commercial",
        "research-only",
        "NC",
        "proprietary-nc",
    }
)

ALLOWED_SPDX_IDS_CF: frozenset[str] = frozenset(x.casefold() for x in ALLOWED_SPDX_IDS)
DENYLISTED_SPDX_IDS_CF: frozenset[str] = frozenset(x.casefold() for x in DENYLISTED_SPDX_IDS)

# NC-family tags map to RESEARCH_ONLY_LICENSE rather than DENYLISTED_LICENSE.
_RESEARCH_ONLY_LICENSE_CF: frozenset[str] = frozenset(
    {
        "research-only",
        "non-commercial",
        "nc",
        "proprietary-nc",
        "cc-by-nc-4.0",
        "cc-by-nc-sa-4.0",
        "cc-by-nc-nd-4.0",
    }
)

# Training-data / corpus sources that taint commercial use when present in
# the row ``source`` (or ``license`` tag) field. ``generator_lineage`` is NOT
# checked against this set — it is informational only.
RESEARCH_ONLY_SOURCES: frozenset[str] = frozenset(
    {
        "widerface",
        "wider_face",
        "mfr",
        "rmfrd",
        "casia",
        "casia-webface",
        "ffhq",
        "webface",
        "webface260m",
        "vggface2",
        "celeba",
        "ms1m",
        "ms-celeb-1m",
        "glint360k",
        "deepglint",
    }
)

# Compact (separator-stripped) forms of research-only sources for matching.
_RESEARCH_ONLY_COMPACT: frozenset[str] = frozenset(
    re.sub(r"[^a-z0-9]+", "", s.casefold()) for s in RESEARCH_ONLY_SOURCES
)


# ---------------------------------------------------------------------------
# PINNED non-commercial model pattern list (buffalo OUTPUT ban wall 1)
# ---------------------------------------------------------------------------

# Patterns are matched case-insensitively against ``derived_from_model``.
# Glob semantics (applied to every path segment after NFKC + split):
#   - ``prefix/*``  → any segment equals prefix
#   - ``prefix*``   → any segment startswith prefix
#   - bare token    → any segment equals token
#
# ``dcface/*`` is intentionally ABSENT — operator clearance
# ``dcface_operator_clearance_20260723`` keeps it off this list.
NC_MODEL_PATTERNS: tuple[str, ...] = (
    "insightface/*",
    "insightface",
    "buffalo*",
    "buffalo",
)

# Extra pinned NC model ids beyond table-derived entries (ArcFace ecosystem
# weights that are non-commercial but not always present as registry rows).
_PINNED_NC_MODEL_IDS: frozenset[str] = frozenset(
    {
        "buffalo",
        "buffalo_s",
        "buffalo_sc",
        "retinaface",
        "arcface",
    }
)


# ---------------------------------------------------------------------------
# Registered entries (named ingest / tooling / synthetic)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VerificationMetadata:
    """Pinned verification metadata for a registered policy entry."""

    spdx_id: str
    commercial_use: CommercialUse
    source_url: str = ""
    source_ref: str = ""
    verified_at: str = ""
    notes: str = ""
    clearance_decision: str = ""


@dataclass(frozen=True, slots=True)
class ModelIngestEntry:
    """Named detector / cascade person-detector ingest registration."""

    model_id: str
    display_name: str
    role: DetectorRole
    verification: VerificationMetadata
    category: PolicyCategory = PolicyCategory.MODEL_INGEST


@dataclass(frozen=True, slots=True)
class ToolingEntry:
    """Diagnostic / offline tooling dependency (not training data)."""

    package_name: str
    verification: VerificationMetadata
    category: PolicyCategory = PolicyCategory.TOOLING


@dataclass(frozen=True, slots=True)
class SyntheticSourceEntry:
    """Synthetic-identity source clearance state."""

    source_id: str
    verification: VerificationMetadata
    category: PolicyCategory = PolicyCategory.SYNTHETIC_SOURCE


@dataclass(frozen=True, slots=True)
class PackageDenylistEntry:
    """Explicitly denylisted package / framework (e.g. Ultralytics AGPL)."""

    package_id: str
    display_name: str
    spdx_id: str
    reason: RejectionReason
    notes: str = ""


# Detector A/B (face detectors) + person→face cascade person-detectors.
# Each candidate has a named entry verified at ingest — not QA-doc prose alone.
MODEL_INGEST_ENTRIES: dict[str, ModelIngestEntry] = {
    "mediapipe_blazeface": ModelIngestEntry(
        model_id="mediapipe_blazeface",
        display_name="MediaPipe BlazeFace",
        role=DetectorRole.FACE_DETECTOR,
        verification=VerificationMetadata(
            spdx_id="Apache-2.0",
            commercial_use=CommercialUse.ALLOWED,
            source_url="https://github.com/google-ai-edge/mediapipe",
            source_ref="mediapipe-blazeface",
            verified_at="2026-07-23",
            notes="Detector A drop-in; Apache-2.0 MediaPipe face detector.",
        ),
    ),
    "paddle_blazeface_fpn_ssh": ModelIngestEntry(
        model_id="paddle_blazeface_fpn_ssh",
        display_name="Paddle BlazeFace-FPN-SSH",
        role=DetectorRole.FACE_DETECTOR,
        verification=VerificationMetadata(
            spdx_id="Apache-2.0",
            commercial_use=CommercialUse.ALLOWED,
            source_url="https://github.com/PaddlePaddle/PaddleDetection",
            source_ref="blazeface_fpn_ssh",
            verified_at="2026-07-23",
            notes="Detector B drop-in; PaddleDetection BlazeFace-FPN-SSH.",
        ),
    ),
    "rt_detr": ModelIngestEntry(
        model_id="rt_detr",
        display_name="RT-DETR",
        role=DetectorRole.PERSON_DETECTOR,
        verification=VerificationMetadata(
            spdx_id="Apache-2.0",
            commercial_use=CommercialUse.ALLOWED,
            source_url="https://github.com/lyuwenyu/RT-DETR",
            source_ref="rtdetr",
            verified_at="2026-07-23",
            notes="Cascade person-detector; Apache-verified route around Ultralytics.",
        ),
    ),
    "d_fine": ModelIngestEntry(
        model_id="d_fine",
        display_name="D-FINE",
        role=DetectorRole.PERSON_DETECTOR,
        verification=VerificationMetadata(
            spdx_id="Apache-2.0",
            commercial_use=CommercialUse.ALLOWED,
            source_url="https://github.com/Peterande/D-FINE",
            source_ref="d-fine",
            verified_at="2026-07-23",
            notes="Cascade person-detector; Apache-verified.",
        ),
    ),
    "pp_picodet": ModelIngestEntry(
        model_id="pp_picodet",
        display_name="PP-PicoDet",
        role=DetectorRole.PERSON_DETECTOR,
        verification=VerificationMetadata(
            spdx_id="Apache-2.0",
            commercial_use=CommercialUse.ALLOWED,
            source_url="https://github.com/PaddlePaddle/PaddleDetection",
            source_ref="picodet",
            verified_at="2026-07-23",
            notes="Cascade person-detector; PaddleDetection PicoDet Apache-2.0.",
        ),
    ),
    # Base stack (already owned; registered so ingest of the base path is explicit).
    "yunet": ModelIngestEntry(
        model_id="yunet",
        display_name="YuNet",
        role=DetectorRole.FACE_DETECTOR,
        verification=VerificationMetadata(
            spdx_id="MIT",
            commercial_use=CommercialUse.ALLOWED,
            source_url="https://github.com/opencv/opencv_zoo",
            source_ref="face_detection_yunet",
            verified_at="2026-07-23",
            notes="OpenCV Zoo YuNet base detector.",
        ),
    ),
    "sface": ModelIngestEntry(
        model_id="sface",
        display_name="SFace",
        role=DetectorRole.FACE_EMBEDDER,
        verification=VerificationMetadata(
            spdx_id="Apache-2.0",
            commercial_use=CommercialUse.ALLOWED,
            source_url="https://github.com/opencv/opencv_zoo",
            source_ref="face_recognition_sface",
            verified_at="2026-07-23",
            notes="OpenCV Zoo SFace base embedder.",
        ),
    ),
}

# Ultralytics and other AGPL / NC frameworks — route cascade around these.
PACKAGE_DENYLIST: dict[str, PackageDenylistEntry] = {
    "ultralytics": PackageDenylistEntry(
        package_id="ultralytics",
        display_name="Ultralytics YOLO",
        spdx_id="AGPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes="AGPL-3.0; person→face cascade must use RT-DETR / D-FINE / PP-PicoDet.",
    ),
    "yolov8": PackageDenylistEntry(
        package_id="yolov8",
        display_name="YOLOv8 (Ultralytics)",
        spdx_id="AGPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes="Ultralytics AGPL family; banned for cascade person-detection.",
    ),
    "insightface": PackageDenylistEntry(
        package_id="insightface",
        display_name="InsightFace / buffalo",
        spdx_id="Non-Commercial",
        reason=RejectionReason.NC_MODEL_DERIVED,
        notes="Non-commercial weights AND outputs banned from training paths.",
    ),
    "buffalo_l": PackageDenylistEntry(
        package_id="buffalo_l",
        display_name="InsightFace buffalo_l",
        spdx_id="Non-Commercial",
        reason=RejectionReason.NC_MODEL_DERIVED,
        notes="Buffalo weights and any output-derived data fail the audit.",
    ),
}

# TOOLING allowlist — diagnostic deps, not training data.
TOOLING_ALLOWLIST: dict[str, ToolingEntry] = {
    "umap-learn": ToolingEntry(
        package_name="umap-learn",
        verification=VerificationMetadata(
            spdx_id="BSD-3-Clause",
            commercial_use=CommercialUse.ALLOWED,
            source_url="https://github.com/lmcinnes/umap",
            verified_at="2026-07-23",
            notes="Slice-3 aligned-UMAP diagnostics; not training data.",
        ),
    ),
    "numba": ToolingEntry(
        package_name="numba",
        verification=VerificationMetadata(
            spdx_id="BSD-2-Clause",
            commercial_use=CommercialUse.ALLOWED,
            verified_at="2026-07-23",
            notes="UMAP runtime dependency.",
        ),
    ),
    "llvmlite": ToolingEntry(
        package_name="llvmlite",
        verification=VerificationMetadata(
            spdx_id="BSD-2-Clause",
            commercial_use=CommercialUse.ALLOWED,
            verified_at="2026-07-23",
            notes="UMAP/numba runtime dependency.",
        ),
    ),
    "tensorflow": ToolingEntry(
        package_name="tensorflow",
        verification=VerificationMetadata(
            spdx_id="Apache-2.0",
            commercial_use=CommercialUse.ALLOWED,
            verified_at="2026-07-23",
            notes="ParametricUMAP optional dep; aarch64 fallback may skip it.",
        ),
    ),
}

# Synthetic-identity sources. Default is PENDING until a per-source operator
# clearance decision flips the entry. DCFace is operator-cleared.
DCFACE_CLEARANCE_DECISION = "dcface_operator_clearance_20260723"

SYNTHETIC_SOURCE_ENTRIES: dict[str, SyntheticSourceEntry] = {
    "dcface": SyntheticSourceEntry(
        source_id="dcface",
        verification=VerificationMetadata(
            # Real allowlisted SPDX; commercial admission is via clearance_decision.
            spdx_id="Apache-2.0",
            commercial_use=CommercialUse.ALLOWED,
            source_url="https://github.com/mk-minchul/dcface",
            verified_at="2026-07-23",
            clearance_decision=DCFACE_CLEARANCE_DECISION,
            notes=(
                "Operator-cleared for commercial training use "
                f"({DCFACE_CLEARANCE_DECISION}). "
                "FFHQ/CASIA generator lineage disclosed via generator_lineage "
                "field only — not via source/license."
            ),
        ),
    ),
    "vec2face": SyntheticSourceEntry(
        source_id="vec2face",
        verification=VerificationMetadata(
            spdx_id="PENDING-LEGAL-CLEARANCE",
            commercial_use=CommercialUse.FORBIDDEN,
            verified_at="2026-07-23",
            notes="Synthetic source remains PENDING until per-source clearance.",
        ),
    ),
}

# Occluder pack-build: only these sources are registered for asset provenance.
OCCLUDER_REGISTERED_SOURCES: frozenset[str] = frozenset(
    {
        "self-generated",
        "operator-photo",
        "operator-phone",
        "operator-render",
    }
)

# Positive clearance statuses accepted at pack-build (module scope).
OCCLUDER_ALLOWED_CLEARANCES: frozenset[str] = frozenset(
    {
        ClearanceStatus.ALLOWED.value,
        ClearanceStatus.OPERATOR_CLEARED.value,
        ClearanceStatus.CLEARED.value,
        ClearanceStatus.LICENSE_CLEARED.value,
    }
)

# Shared model-id alias map (single source of truth for ingest resolution).
_MODEL_ALIASES: dict[str, str] = {
    "mediapipe_blazeface": "mediapipe_blazeface",
    "blazeface": "mediapipe_blazeface",
    "paddle_blazeface_fpn_ssh": "paddle_blazeface_fpn_ssh",
    "blazeface_fpn_ssh": "paddle_blazeface_fpn_ssh",
    "rt_detr": "rt_detr",
    "rtdetr": "rt_detr",
    "d_fine": "d_fine",
    "dfine": "d_fine",
    "pp_picodet": "pp_picodet",
    "picodet": "pp_picodet",
    "ultralytics": "ultralytics",
    "yolov8": "yolov8",
    "yolo": "ultralytics",
    "yunet": "yunet",
    "sface": "sface",
}


def _derive_nc_model_ids() -> frozenset[str]:
    """Build NC model-id set from registry tables ∪ pinned extras."""
    ids: set[str] = set(_PINNED_NC_MODEL_IDS)
    for key, entry in MODEL_INGEST_ENTRIES.items():
        if entry.verification.commercial_use is not CommercialUse.ALLOWED:
            ids.add(key)
            ids.add(entry.model_id)
    for key, entry in SYNTHETIC_SOURCE_ENTRIES.items():
        if entry.verification.commercial_use is not CommercialUse.ALLOWED:
            ids.add(key)
            ids.add(entry.source_id)
    for entry in PACKAGE_DENYLIST.values():
        if entry.reason is RejectionReason.NC_MODEL_DERIVED:
            ids.add(entry.package_id)
    # Pattern stems so NC_MODEL_IDS stays aligned with NC_MODEL_PATTERNS.
    for pattern in NC_MODEL_PATTERNS:
        p = pattern.casefold()
        if p.endswith("/*"):
            ids.add(p[:-2])
        elif p.endswith("*"):
            ids.add(p[:-1])
        else:
            ids.add(p)
    return frozenset(ids)


# Derived at import time — any non-ALLOWED table entry is denylisted for
# derived_from_model matching (plan: any model whose license_policy entry is NC).
NC_MODEL_IDS: frozenset[str] = _derive_nc_model_ids()


# ---------------------------------------------------------------------------
# Pure matching helpers
# ---------------------------------------------------------------------------


def _normalize_token(value: str) -> str:
    return value.strip().lower()


def _nfkc_lower(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _compact_alnum(value: str) -> str:
    """Strip all non-alphanumeric characters (research-source matching)."""
    return re.sub(r"[^a-z0-9]+", "", _nfkc_lower(value))


def _split_segments(value: str) -> list[str]:
    """NFKC-normalise then split on path/sep punctuation."""
    text = _nfkc_lower(value)
    if not text:
        return []
    return [s for s in re.split(r"[/\-_\s]+", text) if s]


def _resolve_model_key(model_id: str) -> str:
    """Normalise a model id / alias to a registry key."""
    key = _normalize_token(str(model_id)).replace("-", "_").replace(" ", "_")
    return _MODEL_ALIASES.get(key, key)


def _is_model_ingest_key(head: str) -> bool:
    """True when ``head`` resolves to a registered model-ingest entry."""
    resolved = _resolve_model_key(head)
    return resolved in MODEL_INGEST_ENTRIES


def match_nc_model_pattern(derived_from_model: str) -> str | None:
    """Return the pinned NC pattern / id that matches ``derived_from_model``.

    Matching is case-insensitive after NFKC normalisation. Every segment from
    splitting on ``[/-_\\s]+`` is tested against ``NC_MODEL_PATTERNS`` (so
    nested paths and underscore forms hit ``insightface/*`` / ``buffalo*``).

    ``NC_MODEL_IDS`` is applied to slash-path heads and exact full tokens only
    — not to every hyphen segment — so a synthetic successor like
    ``vec2face-successor/v1`` is not mis-classified as the table entry
    ``vec2face`` (that case is fail-closed via synthetic clearance instead).
    """
    if not derived_from_model or not str(derived_from_model).strip():
        return None
    text = _nfkc_lower(str(derived_from_model))
    segments = _split_segments(str(derived_from_model))
    if not segments and not text:
        return None

    nc_ids = {_normalize_token(m) for m in NC_MODEL_IDS}

    # Prefer a pinned pattern when one matches.
    for pattern in NC_MODEL_PATTERNS:
        if _pattern_matches(pattern, text, segments):
            return pattern

    # Table-derived / pinned ids: path heads (slash-separated) + exact token.
    if text in nc_ids:
        return text
    for part in text.split("/"):
        if part and part in nc_ids:
            return part
    return None


def _pattern_matches(pattern: str, text: str, segments: list[str]) -> bool:
    p = _normalize_token(pattern)
    if p.endswith("/*"):
        prefix = p[:-2]
        if any(seg == prefix for seg in segments):
            return True
        return text == prefix or text.startswith(prefix + "/")
    if p.endswith("*"):
        prefix = p[:-1]
        # Segment-prefix match for buffalo* (and similar) globs.
        if any(seg.startswith(prefix) for seg in segments):
            return True
        return text.startswith(prefix)
    # Bare token: exact segment or classic path prefix.
    if any(seg == p for seg in segments):
        return True
    return text == p or text.startswith(p + "/")


def _looks_like_research_source(value: str) -> bool:
    """True when any path segment compact-matches a research-only corpus name."""
    if not value or not str(value).strip():
        return False
    text = str(value).strip()
    segments = _split_segments(text)
    candidates = [_compact_alnum(text), *(_compact_alnum(s) for s in segments)]
    for cand in candidates:
        if not cand:
            continue
        if cand in _RESEARCH_ONLY_COMPACT:
            return True
        for src in _RESEARCH_ONLY_COMPACT:
            # Compound dir names: vggface2_train → vggface2train startswith vggface2
            if cand == src or cand.startswith(src):
                return True
    return False


def _require_string_field(
    row: Mapping[str, Any],
    key: str,
    *,
    required: bool,
    category: PolicyCategory,
) -> tuple[str | None, LicenseAuditResult | None]:
    """Validate optional/required string fields. Returns (value, error)."""
    if key not in row:
        if required:
            return None, _fail(
                RejectionReason.INVALID_ROW,
                detail=f"provenance row missing required field {key!r}",
                category=category,
            )
        return None, None
    raw = row[key]
    if raw is None:
        return None, _fail(
            RejectionReason.INVALID_ROW,
            detail=f"provenance row field {key!r} must be a string, got None",
            category=category,
        )
    if not isinstance(raw, str):
        return None, _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                f"provenance row field {key!r} must be a string, "
                f"got {type(raw).__name__}"
            ),
            category=category,
        )
    return raw, None


def _spdx_of(row: Mapping[str, Any]) -> str:
    raw = row.get("license") or row.get("spdx_id") or row.get("license_id") or ""
    if not isinstance(raw, str):
        return ""
    return raw.strip()


def _source_of(row: Mapping[str, Any]) -> str:
    raw = row.get("source") or ""
    if not isinstance(raw, str):
        return ""
    return raw.strip()


# ---------------------------------------------------------------------------
# Public audit functions
# ---------------------------------------------------------------------------


def audit_derived_from_model(derived_from_model: str | None) -> LicenseAuditResult:
    """Audit a ``derived_from_model`` provenance tag (buffalo OUTPUT ban).

    Empty string is allowed (not every row is model-derived). Any match
    against the pinned NC pattern list or NC model ids FAILS with
    ``RejectionReason.NC_MODEL_DERIVED``.
    """
    if derived_from_model is None:
        return _pass(detail="no derived_from_model tag")
    if not isinstance(derived_from_model, str):
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                "derived_from_model must be a string, "
                f"got {type(derived_from_model).__name__}"
            ),
            category=PolicyCategory.TRAINING_DATA,
        )
    if not derived_from_model.strip():
        return _pass(detail="no derived_from_model tag")

    text = derived_from_model.strip()
    matched = match_nc_model_pattern(text)
    if matched is not None:
        return _fail(
            RejectionReason.NC_MODEL_DERIVED,
            detail=(
                f"derived_from_model={text!r} matches non-commercial pattern "
                f"{matched!r}; buffalo weights and output-derived data are banned"
            ),
            category=PolicyCategory.TRAINING_DATA,
        )

    return _pass(
        detail=f"derived_from_model={text!r} is not on the NC pattern list",
        category=PolicyCategory.TRAINING_DATA,
    )


def audit_spdx(spdx_id: str | None) -> LicenseAuditResult:
    """Audit a bare SPDX / license tag (case-insensitive)."""
    if spdx_id is None or not str(spdx_id).strip():
        return _fail(
            RejectionReason.MISSING_LICENSE_FIELD,
            detail="license / spdx_id field is required",
        )
    if not isinstance(spdx_id, str):
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=f"license must be a string, got {type(spdx_id).__name__}",
        )
    tag = spdx_id.strip()
    tag_cf = tag.casefold()

    if tag_cf in DENYLISTED_SPDX_IDS_CF:
        if tag_cf in _RESEARCH_ONLY_LICENSE_CF:
            reason = RejectionReason.RESEARCH_ONLY_LICENSE
        else:
            reason = RejectionReason.DENYLISTED_LICENSE
        return _fail(
            reason,
            detail=f"license {tag!r} is denylisted for commercial training use",
        )
    if tag_cf in ALLOWED_SPDX_IDS_CF:
        return _pass(detail=f"license {tag!r} is allowlisted")
    if tag_cf == "pending-legal-clearance":
        return _fail(
            RejectionReason.PENDING_LEGAL_CLEARANCE,
            detail="license is PENDING-LEGAL-CLEARANCE",
        )
    # operator-cleared is NOT an SPDX value and is never an unconditional pass.
    return _fail(
        RejectionReason.UNKNOWN_SPDX,
        detail=f"license {tag!r} is not on the allowlist",
    )


def audit_source(source: str | None) -> LicenseAuditResult:
    """Audit a training-data ``source`` field against the research-only set.

    Does **not** inspect ``generator_lineage`` — that field is informational.
    """
    if source is None or not str(source).strip():
        return _fail(
            RejectionReason.UNKNOWN_SOURCE,
            detail="source field is required for training-data rows",
            category=PolicyCategory.TRAINING_DATA,
        )
    if not isinstance(source, str):
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=f"source must be a string, got {type(source).__name__}",
            category=PolicyCategory.TRAINING_DATA,
        )
    text = source.strip()
    if _looks_like_research_source(text):
        return _fail(
            RejectionReason.RESEARCH_ONLY_SOURCE,
            detail=f"source {text!r} is research-only and taints commercial use",
            category=PolicyCategory.TRAINING_DATA,
        )
    return _pass(
        detail=f"source {text!r} is not research-only",
        category=PolicyCategory.TRAINING_DATA,
    )


def audit_model_ingest(model_id: str) -> LicenseAuditResult:
    """Verify a detector / cascade model has a named commercial-allowed ingest entry.

    Missing entry → FAIL ``MISSING_INGEST_ENTRY``.
    Denylisted package (Ultralytics etc.) → FAIL with that package's reason.
    NC-tagged entry → FAIL ``NC_MODEL_DERIVED``.
    """
    if not model_id or not str(model_id).strip():
        return _fail(
            RejectionReason.MISSING_INGEST_ENTRY,
            detail="model_id is required for ingest",
            category=PolicyCategory.MODEL_INGEST,
        )
    resolved = _resolve_model_key(str(model_id))

    deny = PACKAGE_DENYLIST.get(resolved)
    if deny is not None:
        return _fail(
            deny.reason,
            detail=(
                f"package {deny.display_name!r} ({deny.spdx_id}) is denylisted: "
                f"{deny.notes}"
            ),
            category=PolicyCategory.MODEL_INGEST,
        )

    entry = MODEL_INGEST_ENTRIES.get(resolved)
    if entry is None:
        return _fail(
            RejectionReason.MISSING_INGEST_ENTRY,
            detail=f"no named license_policy ingest entry for model_id={model_id!r}",
            category=PolicyCategory.MODEL_INGEST,
        )
    if entry.verification.commercial_use is not CommercialUse.ALLOWED:
        return _fail(
            RejectionReason.NC_MODEL_DERIVED,
            detail=(
                f"ingest entry {entry.model_id!r} is "
                f"{entry.verification.commercial_use.value}, not commercially allowed"
            ),
            category=PolicyCategory.MODEL_INGEST,
        )
    spdx_result = audit_spdx(entry.verification.spdx_id)
    if not spdx_result.ok:
        return LicenseAuditResult(
            verdict=spdx_result.verdict,
            reason=spdx_result.reason,
            detail=spdx_result.detail,
            category=PolicyCategory.MODEL_INGEST,
        )
    return _pass(
        detail=f"ingest entry {entry.display_name!r} ({entry.verification.spdx_id}) allowed",
        category=PolicyCategory.MODEL_INGEST,
    )


def get_model_ingest_entry(model_id: str) -> ModelIngestEntry:
    """Return the named ingest entry or raise ``LicensePolicyError`` (sr-006)."""
    result = audit_model_ingest(model_id)
    if not result.ok:
        raise LicensePolicyError(result)
    resolved = _resolve_model_key(model_id)
    entry = MODEL_INGEST_ENTRIES.get(resolved)
    if entry is None:
        # audit_model_ingest already returned non-ok on a miss; unreachable.
        raise LicensePolicyError(result)
    return entry


def audit_tooling_dependency(package_name: str) -> LicenseAuditResult:
    """Audit a TOOLING dependency (diagnostic; not training data)."""
    if not package_name or not str(package_name).strip():
        return _fail(
            RejectionReason.UNKNOWN_SOURCE,
            detail="tooling package_name is required",
            category=PolicyCategory.TOOLING,
        )
    key = _normalize_token(package_name)
    deny = PACKAGE_DENYLIST.get(key)
    if deny is not None:
        return _fail(
            deny.reason,
            detail=f"tooling package {package_name!r} is denylisted ({deny.spdx_id})",
            category=PolicyCategory.TOOLING,
        )
    entry = TOOLING_ALLOWLIST.get(key)
    if entry is None:
        entry = TOOLING_ALLOWLIST.get(key.replace("_", "-"))
    if entry is None:
        entry = TOOLING_ALLOWLIST.get(key.replace("-", "_"))
    if entry is None:
        return _fail(
            RejectionReason.UNKNOWN_SOURCE,
            detail=f"tooling package {package_name!r} is not on the TOOLING allowlist",
            category=PolicyCategory.TOOLING,
        )
    return _pass(
        detail=(
            f"tooling package {entry.package_name!r} "
            f"({entry.verification.spdx_id}) is allowlisted"
        ),
        category=PolicyCategory.TOOLING,
    )


def is_tooling_allowlisted(package_name: str) -> bool:
    """Return True iff ``package_name`` is on the TOOLING allowlist."""
    return audit_tooling_dependency(package_name).ok


def audit_occluder_asset(asset: Mapping[str, Any]) -> LicenseAuditResult:
    """Gate an occluder-asset row at pack-build.

    Required: allowlisted license, positive clearance, and a non-empty
    **registered** source. Unknown sources FAIL (not only research names).
    """
    if not isinstance(asset, Mapping):
        raise LicensePolicyError(
            _fail(
                RejectionReason.UNCLEARED_OCCLUDER_ASSET,
                detail="occluder asset must be a mapping with license fields",
                category=PolicyCategory.OCCLUDER_ASSET,
            )
        )

    spdx = _spdx_of(asset)
    if not spdx:
        return _fail(
            RejectionReason.MISSING_LICENSE_FIELD,
            detail="occluder asset missing required license field",
            category=PolicyCategory.OCCLUDER_ASSET,
        )

    clearance_raw = asset.get("clearance") or asset.get("clearance_status") or ""
    if clearance_raw is not None and not isinstance(clearance_raw, str):
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                "occluder asset clearance must be a string, "
                f"got {type(clearance_raw).__name__}"
            ),
            category=PolicyCategory.OCCLUDER_ASSET,
        )
    clearance = _normalize_token(str(clearance_raw)) if clearance_raw else ""
    if clearance not in OCCLUDER_ALLOWED_CLEARANCES:
        return _fail(
            RejectionReason.UNCLEARED_OCCLUDER_ASSET,
            detail=(
                f"occluder asset source photo is uncleared "
                f"(clearance={clearance_raw!r}); pack-build refused"
            ),
            category=PolicyCategory.OCCLUDER_ASSET,
        )

    spdx_result = audit_spdx(spdx)
    if not spdx_result.ok:
        return LicenseAuditResult(
            verdict=spdx_result.verdict,
            reason=spdx_result.reason,
            detail=f"occluder asset: {spdx_result.detail}",
            category=PolicyCategory.OCCLUDER_ASSET,
        )

    source = _source_of(asset)
    if not source:
        return _fail(
            RejectionReason.UNKNOWN_SOURCE,
            detail="occluder asset requires a non-empty registered source",
            category=PolicyCategory.OCCLUDER_ASSET,
        )
    source_key = _normalize_token(source)
    if source_key not in {_normalize_token(s) for s in OCCLUDER_REGISTERED_SOURCES}:
        if _looks_like_research_source(source):
            return _fail(
                RejectionReason.RESEARCH_ONLY_SOURCE,
                detail=f"occluder asset source {source!r} is research-only",
                category=PolicyCategory.OCCLUDER_ASSET,
            )
        return _fail(
            RejectionReason.UNKNOWN_SOURCE,
            detail=(
                f"occluder asset source {source!r} is not a registered "
                "occluder provenance source"
            ),
            category=PolicyCategory.OCCLUDER_ASSET,
        )

    return _pass(
        detail="occluder asset license fields cleared for pack-build",
        category=PolicyCategory.OCCLUDER_ASSET,
    )


def audit_synthetic_source(
    source_id: str,
    *,
    row_clearance: str | None = None,
) -> LicenseAuditResult:
    """Audit a synthetic-identity source clearance entry.

    When the registered entry carries a ``clearance_decision``, the caller must
    supply a matching ``row_clearance`` value (PROV-04).
    """
    if not source_id or not str(source_id).strip():
        return _fail(
            RejectionReason.UNKNOWN_SOURCE,
            detail="synthetic source_id is required",
            category=PolicyCategory.SYNTHETIC_SOURCE,
        )
    key = _normalize_token(source_id)
    # derived_from_model style: dcface/<generator-id> → dcface
    head = key.split("/", 1)[0]
    # Also accept underscore-separated heads (synthface3_g1 → try full then head).
    entry = SYNTHETIC_SOURCE_ENTRIES.get(head)
    if entry is None:
        # Unknown synthetic sources default to pending (fail-closed).
        return _fail(
            RejectionReason.PENDING_LEGAL_CLEARANCE,
            detail=(
                f"synthetic source {source_id!r} has no clearance entry; "
                "defaults to PENDING-LEGAL-CLEARANCE"
            ),
            category=PolicyCategory.SYNTHETIC_SOURCE,
        )
    if entry.verification.commercial_use is not CommercialUse.ALLOWED:
        return _fail(
            RejectionReason.PENDING_LEGAL_CLEARANCE,
            detail=(
                f"synthetic source {entry.source_id!r} is "
                f"{entry.verification.spdx_id} / "
                f"{entry.verification.commercial_use.value}"
            ),
            category=PolicyCategory.SYNTHETIC_SOURCE,
        )
    decision = entry.verification.clearance_decision
    if decision:
        if not row_clearance or str(row_clearance).strip() != decision:
            return _fail(
                RejectionReason.PENDING_LEGAL_CLEARANCE,
                detail=(
                    f"synthetic source {entry.source_id!r} requires "
                    f"clearance={decision!r}; "
                    f"got {row_clearance!r}"
                ),
                category=PolicyCategory.SYNTHETIC_SOURCE,
            )
    return _pass(
        detail=(
            f"synthetic source {entry.source_id!r} commercial-allowed "
            f"(clearance={entry.verification.clearance_decision or 'n/a'})"
        ),
        category=PolicyCategory.SYNTHETIC_SOURCE,
    )


def _synthetic_audit_targets(
    *,
    source: str,
    derived: str,
    category: PolicyCategory,
    has_generator_lineage: bool,
) -> list[str]:
    """Collect synthetic source ids that must be fail-closed audited.

    Routes to ``audit_synthetic_source`` when:
      - caller category is SYNTHETIC_SOURCE, or
      - generator_lineage is present (and source is not pure self-generated), or
      - derived_from_model head is non-empty and absent from the ingest registry, or
      - source/derived head is a known SYNTHETIC_SOURCE_ENTRIES key.
    """
    targets: list[str] = []
    seen: set[str] = set()

    def _add(token: str) -> None:
        t = token.strip()
        if not t:
            return
        key = _normalize_token(t)
        if key in seen:
            return
        seen.add(key)
        targets.append(t)

    if category is PolicyCategory.SYNTHETIC_SOURCE and source:
        _add(source)

    if has_generator_lineage and source:
        # self-generated + lineage disclosure is informational (exemption path);
        # do not treat pure self-generated rows as synthetic generators.
        if _normalize_token(source) != "self-generated":
            _add(source)

    if derived:
        head = _normalize_token(derived).split("/", 1)[0]
        head = head.replace("-", "_")
        # Also try first underscore segment of bare tokens.
        if head and not _is_model_ingest_key(head):
            # derived_from_model absent from ingest registry → synthetic path.
            _add(derived)

    for token in (source, derived):
        if not token:
            continue
        head = _normalize_token(token).split("/", 1)[0]
        if head in SYNTHETIC_SOURCE_ENTRIES:
            _add(token)

    return targets


def audit_provenance_row(
    row: Mapping[str, Any],
    *,
    category: PolicyCategory | None = None,
) -> LicenseAuditResult:
    """Full provenance-row audit for a training-data (or synthetic) manifest row.

    ``category`` is supplied by the **caller**, never trusted from the row body
    for gate selection. A row-declared ``category`` is parsed through
    ``PolicyCategory`` and rejected when unknown; it does not waive ``source``.

    Checks, in order:
      0. structural field validation (types + required keys)
      1. ``derived_from_model`` against the pinned NC pattern list
      2. ``source`` against research-only sources (NOT ``generator_lineage``)
      3. ``license`` / SPDX allow-deny
      4. synthetic-source clearance (fail-closed for unknown synthetic claims)

    ``generator_lineage`` is informational and never causes research-source
    rejection by itself.
    """
    if not isinstance(row, Mapping):
        raise LicensePolicyError(
            _fail(
                RejectionReason.UNKNOWN_SOURCE,
                detail="provenance row must be a mapping",
                category=PolicyCategory.TRAINING_DATA,
            )
        )

    # Caller-owned category (default training_data). Row body cannot pick its gate.
    audit_category = category if category is not None else PolicyCategory.TRAINING_DATA
    if not isinstance(audit_category, PolicyCategory):
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=f"category parameter must be PolicyCategory, got {audit_category!r}",
            category=PolicyCategory.TRAINING_DATA,
        )

    # If the row declares a category, it must be a valid PolicyCategory value.
    if "category" in row:
        raw_cat = row["category"]
        if raw_cat is not None and not isinstance(raw_cat, str):
            return _fail(
                RejectionReason.INVALID_ROW,
                detail=(
                    "row category must be a string, "
                    f"got {type(raw_cat).__name__}"
                ),
                category=audit_category,
            )
        if isinstance(raw_cat, str) and raw_cat.strip():
            try:
                PolicyCategory(raw_cat.strip())
            except ValueError:
                return _fail(
                    RejectionReason.INVALID_ROW,
                    detail=f"unknown policy category {raw_cat!r}",
                    category=audit_category,
                )

    # Structural validation — require derived_from_model KEY ('' is valid opt-out).
    if "derived_from_model" not in row:
        return _fail(
            RejectionReason.INVALID_ROW,
            detail="provenance row missing required field 'derived_from_model'",
            category=audit_category,
        )

    for key in (
        "source",
        "license",
        "derived_from_model",
        "clearance",
        "generator_lineage",
    ):
        if key not in row:
            continue
        raw = row[key]
        if raw is None:
            return _fail(
                RejectionReason.INVALID_ROW,
                detail=f"provenance row field {key!r} must be a string, got None",
                category=audit_category,
            )
        if not isinstance(raw, str):
            return _fail(
                RejectionReason.INVALID_ROW,
                detail=(
                    f"provenance row field {key!r} must be a string, "
                    f"got {type(raw).__name__}"
                ),
                category=audit_category,
            )

    derived = str(row["derived_from_model"]).strip()
    derived_result = audit_derived_from_model(derived)
    if not derived_result.ok:
        return derived_result

    source = ""
    if "source" in row and isinstance(row["source"], str):
        source = row["source"].strip()

    # Training-data audits always require source (row cannot waive via category).
    if audit_category is PolicyCategory.TRAINING_DATA:
        if not source:
            return _fail(
                RejectionReason.UNKNOWN_SOURCE,
                detail="training-data provenance row requires a source field",
                category=PolicyCategory.TRAINING_DATA,
            )
        source_result = audit_source(source)
        if not source_result.ok:
            return source_result
    elif source:
        source_result = audit_source(source)
        if not source_result.ok:
            return source_result

    spdx = _spdx_of(row)
    spdx_result = audit_spdx(spdx)
    if not spdx_result.ok:
        return spdx_result

    has_lineage = bool(str(row.get("generator_lineage") or "").strip())
    # When caller marks synthetic, or row declares synthetic_source category value.
    effective_synth_category = audit_category
    if "category" in row and isinstance(row["category"], str):
        try:
            declared = PolicyCategory(row["category"].strip())
            if declared is PolicyCategory.SYNTHETIC_SOURCE:
                effective_synth_category = PolicyCategory.SYNTHETIC_SOURCE
        except ValueError:
            pass

    row_clearance_raw = row.get("clearance")
    row_clearance = (
        row_clearance_raw.strip()
        if isinstance(row_clearance_raw, str)
        else None
    )

    for cand in _synthetic_audit_targets(
        source=source,
        derived=derived,
        category=effective_synth_category,
        has_generator_lineage=has_lineage,
    ):
        synth_result = audit_synthetic_source(cand, row_clearance=row_clearance)
        if not synth_result.ok:
            return synth_result

    return _pass(
        detail="provenance row passes license policy",
        category=audit_category,
    )


def audit_tooling_row(row: Mapping[str, Any]) -> LicenseAuditResult:
    """Audit a tooling dependency row (caller-owned TOOLING category)."""
    return audit_provenance_row(row, category=PolicyCategory.TOOLING)


def require_pass(result: LicenseAuditResult) -> LicenseAuditResult:
    """Raise ``LicensePolicyError`` when ``result`` is not a PASS (sr-006)."""
    if not result.ok:
        raise LicensePolicyError(result)
    return result


# Convenience: ordered required named ingest display names for fixtures.
REQUIRED_DETECTOR_AB_DISPLAY_NAMES: tuple[str, ...] = (
    "MediaPipe BlazeFace",
    "Paddle BlazeFace-FPN-SSH",
)
REQUIRED_CASCADE_PERSON_DETECTOR_DISPLAY_NAMES: tuple[str, ...] = (
    "RT-DETR",
    "D-FINE",
    "PP-PicoDet",
)
REQUIRED_MODEL_INGEST_DISPLAY_NAMES: tuple[str, ...] = (
    *REQUIRED_DETECTOR_AB_DISPLAY_NAMES,
    *REQUIRED_CASCADE_PERSON_DETECTOR_DISPLAY_NAMES,
)
