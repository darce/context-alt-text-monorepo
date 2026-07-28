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
    UNREGISTERED_DERIVED_MODEL = "unregistered_derived_model"


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
        # NOTE: ``self-generated`` is a *source* value, not an SPDX licence tag.
        # It must not appear here (BR-25); see OCCLUDER_REGISTERED_SOURCES /
        # _POSITIVE_TRAINING_SOURCES.
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

# Patterns are matched case-insensitively against ``derived_from_model``
# after shared normalisation (NFKC → strip Cf → casefold). Glob semantics
# (slash-components; see ``_pattern_matches``):
#   - ``prefix/*``  → slash-component equals prefix (or insightface+buffalo*)
#   - ``prefix*``   → component == prefix or ^prefix[_-]?[a-z]{0,3}\d*$
#   - bare token    → same as path-head / constrained exact
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

# Positive allowlist for TRAINING_DATA source axis (BR-22 / SECD-05).
# Operator-owned provenance sources; model-ingest keys and synthetic registry
# heads are recognised separately. Anything else defaults to
# PENDING-LEGAL-CLEARANCE rather than falling through to PASS.
_POSITIVE_TRAINING_SOURCES: frozenset[str] = frozenset(
    s.strip().lower() for s in OCCLUDER_REGISTERED_SOURCES
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
    """Build NC model-id set from registry tables ∪ pinned extras.

    Sources (all unioned):
      * ``_PINNED_NC_MODEL_IDS`` — ArcFace-ecosystem weights not always registered
      * ``MODEL_INGEST_ENTRIES`` whose ``commercial_use`` is not ALLOWED
        (currently every stock ingest entry is ALLOWED; the loop is kept so a
        future NC-tagged ingest row is denylisted automatically — BR-38)
      * ``SYNTHETIC_SOURCE_ENTRIES`` whose commercial_use is not ALLOWED
      * ``PACKAGE_DENYLIST`` entries tagged ``NC_MODEL_DERIVED``
      * stems extracted from ``NC_MODEL_PATTERNS``
    """
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


# Version-ish slash-component suffix admitted after an NC id head
# (retinaface_r50, buffalo_l, mnet025, g1, …) — rejects free-form product words.
_NC_VERSION_SEG_RE = re.compile(r"^(?:[a-z]{1,3}|[a-z]*\d+[a-z0-9]*)$")

# Constrained buffalo* (and similar) glob: buffalo_l / buffalo_sc / buffalo_l2
# but not buffalo_bill_detector or buffalo-wings-detector.
_PREFIX_GLOB_VERSION_RE = re.compile(r"[_-]?[a-z]{0,3}\d*$")

# Research-corpus variant suffixes for unsplit compounds (ffhq256, widerfacehd).
_RESEARCH_UNSPLIT_SUFFIXES: tuple[str, ...] = (
    "train",
    "val",
    "test",
    "aligned",
    "hq",
    "extra",
    "hd",
    "dev",
    "full",
    "crop",
    "raw",
    "orig",
    "clean",
)
_RESEARCH_VERSION_SEGS: frozenset[str] = frozenset(
    {
        "train",
        "val",
        "test",
        "aligned",
        "hq",
        "extra",
        "hd",
        "dev",
        "full",
        "crop",
        "raw",
        "orig",
        "clean",
    }
)


@dataclass(frozen=True, slots=True)
class _MatchNorm:
    """Shared normalisation result for NC + research matchers (BR-21)."""

    text: str
    slash_parts: tuple[str, ...]
    segments: tuple[str, ...]
    compact: str
    has_non_ascii: bool
    has_separators: bool


def _normalize_token(value: str) -> str:
    return value.strip().lower()


def _nfkc_lower(value: str) -> str:
    """Legacy helper — prefers :func:`_normalize_for_match` for new call sites."""
    text, _ = _prepare_match_text(value)
    return text


def _prepare_match_text(value: str) -> tuple[str, bool]:
    """NFKC → strip unicode category Cf → casefold.

    Returns ``(text, has_non_ascii_residue)``. Non-ASCII residue after NFKC is
    fail-closed by audit callers (``invalid_row``) so confusable scripts cannot
    launder banned names by compacting away non-Latin letters.
    """
    text = unicodedata.normalize("NFKC", str(value))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    text = text.strip().casefold()
    has_non_ascii = any(ord(ch) > 127 for ch in text)
    return text, has_non_ascii


def _normalize_for_match(value: str) -> _MatchNorm:
    """Single shared normalisation used by both NC and research matchers."""
    text, has_non_ascii = _prepare_match_text(value)
    if not text:
        return _MatchNorm(
            text="",
            slash_parts=(),
            segments=(),
            compact="",
            has_non_ascii=has_non_ascii,
            has_separators=False,
        )
    # Normalise any residual path separators to ``/`` (NFKC already folds
    # fullwidth solidus); split slash components independently of ``_``/``-``.
    slash_text = text.replace("\\", "/")
    slash_parts = tuple(p for p in re.split(r"/+", slash_text) if p)
    segments = tuple(s for s in re.split(r"[^a-z0-9]+", text) if s)
    # Only build compact when pure ASCII — otherwise confusables would drop out.
    compact = "" if has_non_ascii else re.sub(r"[^a-z0-9]+", "", text)
    has_separators = bool(re.search(r"[^a-z0-9]", text))
    return _MatchNorm(
        text=text,
        slash_parts=slash_parts,
        segments=segments,
        compact=compact,
        has_non_ascii=has_non_ascii,
        has_separators=has_separators,
    )


def _compact_alnum(value: str) -> str:
    """Strip all non-alphanumeric characters (research-source matching)."""
    return _normalize_for_match(value).compact


def _split_segments(value: str) -> list[str]:
    """NFKC-normalise then split on non-alphanumeric runs."""
    return list(_normalize_for_match(value).segments)


def _part_segments(part: str) -> list[str]:
    """Split a single slash-component on non-alphanumeric runs."""
    return [s for s in re.split(r"[^a-z0-9]+", part) if s]


def _resolve_model_key(model_id: str) -> str:
    """Normalise a model id / alias to a registry key."""
    key = _normalize_token(str(model_id)).replace("-", "_").replace(" ", "_")
    return _MODEL_ALIASES.get(key, key)


def _is_model_ingest_key(head: str) -> bool:
    """True when ``head`` resolves to a registered model-ingest entry."""
    resolved = _resolve_model_key(head)
    return resolved in MODEL_INGEST_ENTRIES


def _is_nc_version_seg(seg: str) -> bool:
    return bool(_NC_VERSION_SEG_RE.fullmatch(seg))


def _glob_prefix_component_match(prefix: str, component: str) -> bool:
    """``prefix*`` against one slash-component (not micro-segments).

    Admits ``buffalo``, ``buffalo_l``, ``buffalo-sc``, ``buffalo_l2``;
    rejects ``buffalo-wings-detector`` and ``buffalo_bill_detector``.
    """
    if component == prefix:
        return True
    if not component.startswith(prefix):
        return False
    return bool(_PREFIX_GLOB_VERSION_RE.fullmatch(component[len(prefix) :]))


def _match_insightface_style(prefix: str, norm: _MatchNorm) -> bool:
    """Match ``insightface`` as a slash-component head / whole token only.

    Mid-token hyphen segments (``not-insightface``) and free suffixes
    (``insightface-free``) do not match. Underscore model forms such as
    ``insightface_buffalo_l`` still match when the continuation is buffalo*.
    Compact equality (``insight face`` → ``insightface``) also matches.
    """
    if norm.text == prefix or norm.text.startswith(prefix + "/"):
        return True
    if norm.compact == prefix:
        return True
    for part in norm.slash_parts:
        if part == prefix:
            return True
        part_segs = _part_segments(part)
        if not part_segs or part_segs[0] != prefix:
            continue
        rest = part_segs[1:]
        if not rest:
            return True
        # Continuation must look like an NC sub-model (buffalo family), not
        # an unrelated product suffix such as ``free``.
        if rest[0] == "buffalo" or _glob_prefix_component_match(
            "buffalo", "_".join(rest)
        ):
            return True
        if rest[0] == "buffalo" or _glob_prefix_component_match("buffalo", rest[0]):
            return True
    return False


def _match_prefix_glob(prefix: str, norm: _MatchNorm) -> bool:
    """Constrained ``prefix*`` glob over slash-components and the full token."""
    if _glob_prefix_component_match(prefix, norm.text):
        return True
    for part in norm.slash_parts:
        if _glob_prefix_component_match(prefix, part):
            return True
    return False


def _match_nc_ids(norm: _MatchNorm, nc_ids: set[str]) -> str | None:
    """Match ``NC_MODEL_IDS`` via slash parts + progressive ``_``-joined prefixes.

    A progressive head matches only when the remaining segments are all
    version-ish (``r50``, ``g1``, ``mnet025``, ``l`` …), so
    ``arcface_alternative_v2`` and ``not-retinaface`` stay clean while
    ``retinaface_r50`` / ``vec2face_g1`` fail.
    """
    if norm.text in nc_ids:
        return norm.text
    # Also accept hyphen form of full text normalised to underscores.
    text_us = norm.text.replace("-", "_")
    if text_us in nc_ids:
        return text_us

    for part in norm.slash_parts:
        part_us = part.replace("-", "_")
        if part in nc_ids:
            return part
        if part_us in nc_ids:
            return part_us
        part_segs = _part_segments(part)
        for k in range(1, len(part_segs) + 1):
            joined = "_".join(part_segs[:k])
            if joined not in nc_ids:
                continue
            rest = part_segs[k:]
            if not rest or all(_is_nc_version_seg(s) for s in rest):
                return joined
    return None


def match_nc_model_pattern(derived_from_model: str) -> str | None:
    """Return the pinned NC pattern / id that matches ``derived_from_model``.

    Matching uses the shared :func:`_normalize_for_match` pipeline (NFKC,
    strip Cf, casefold). ``NC_MODEL_PATTERNS`` and ``NC_MODEL_IDS`` share
    slash-component + progressive-prefix semantics so versioned forms like
    ``retinaface_r50`` hit while free-form names like ``buffalo-wings-detector``
    do not.

    Compact alnum form is also checked so ``insight face`` / ``insight.face``
    collapse to the pinned ``insightface`` id (BR-21).

    ``vec2face-successor/v1`` is not classified as the table entry ``vec2face``
    (rest segment is not version-ish); that case is fail-closed via synthetic
    clearance instead.
    """
    if not derived_from_model or not str(derived_from_model).strip():
        return None
    norm = _normalize_for_match(str(derived_from_model))
    if norm.has_non_ascii or (not norm.segments and not norm.text):
        return None

    nc_ids = {_normalize_token(m) for m in NC_MODEL_IDS}

    for pattern in NC_MODEL_PATTERNS:
        if _pattern_matches(pattern, norm):
            return pattern

    hit = _match_nc_ids(norm, nc_ids)
    if hit is not None:
        return hit

    # Compact form: "insight face" / "insight.face" → insightface (BR-21).
    if norm.compact and norm.compact in nc_ids:
        return norm.compact
    if norm.compact and _glob_prefix_component_match("buffalo", norm.compact):
        return "buffalo*"
    return None


def _pattern_matches(pattern: str, norm: _MatchNorm) -> bool:
    p = _normalize_token(pattern)
    if p.endswith("/*"):
        return _match_insightface_style(p[:-2], norm)
    if p.endswith("*"):
        return _match_prefix_glob(p[:-1], norm)
    # Bare token: treat like path-head (insightface) and constrained exact.
    if _match_insightface_style(p, norm):
        return True
    return _match_prefix_glob(p, norm)


def _is_research_version_seg(seg: str) -> bool:
    if seg in _RESEARCH_VERSION_SEGS:
        return True
    if re.fullmatch(r"v\d+[a-z0-9]*", seg):
        return True
    if re.fullmatch(r"r\d+[a-z0-9]*", seg):
        return True
    if re.fullmatch(r"\d+[a-z0-9]*", seg):
        return True
    return False


def _research_unsplit_remainder_ok(remainder: str) -> bool:
    """True when unsplit compact remainder is a version/variant suffix (BR-31)."""
    if not remainder:
        return True
    if remainder[0].isdigit():
        return True
    for suf in _RESEARCH_UNSPLIT_SUFFIXES:
        if remainder == suf or remainder.startswith(suf):
            return True
    if re.match(r"^(?:v|r)\d+", remainder):
        return True
    return False


def _research_segments_match(segs: list[str] | tuple[str, ...]) -> bool:
    """Prefix-match progressive joins from the start; rest must be version-ish.

    Mid-token stems (``our_widerface_replacement``) do not match. Bare ``mfr``
    is exact-only.
    """
    if not segs:
        return False
    # Longer stems first when comparing joined forms.
    stems = sorted(_RESEARCH_ONLY_COMPACT, key=len, reverse=True)
    for k in range(1, len(segs) + 1):
        joined = "".join(segs[:k])
        for src in stems:
            if src == "mfr":
                if joined != "mfr":
                    continue
            elif joined != src:
                continue
            rest = list(segs[k:])
            if not rest or all(_is_research_version_seg(s) for s in rest):
                return True
    return False


def _looks_like_research_source(value: str) -> bool:
    """True when value identifies a research-only corpus (segment-precise).

    Separated forms match progressive segment joins terminated by version-ish
    tails (``vggface2_train``) or exact compact equality (``casia_webface`` →
    ``casiawebface``). Unsplit compounds keep a constrained startswith for
    version suffixes (``ffhq256``) without sweeping ``celebase`` / ``ffhq-tools``.
    """
    if not value or not str(value).strip():
        return False
    norm = _normalize_for_match(str(value))
    if norm.has_non_ascii:
        # Caller audits as invalid_row; treat as tainted if asked raw.
        return True
    if not norm.compact and not norm.segments:
        return False

    # Exact compact equality (covers casia_webface → casiawebface, wider_face).
    if norm.compact in _RESEARCH_ONLY_COMPACT:
        return True

    if not norm.has_separators:
        for src in sorted(_RESEARCH_ONLY_COMPACT, key=len, reverse=True):
            if src == "mfr":
                if norm.compact == "mfr":
                    return True
                continue
            if norm.compact == src:
                return True
            if norm.compact.startswith(src) and _research_unsplit_remainder_ok(
                norm.compact[len(src) :]
            ):
                return True
        return False

    # Slash components: exact compact or progressive head + version rest.
    for part in norm.slash_parts:
        part_compact = re.sub(r"[^a-z0-9]+", "", part)
        if part_compact in _RESEARCH_ONLY_COMPACT:
            return True
        part_segs = _part_segments(part)
        if _research_segments_match(part_segs):
            return True
        # Unsplit-style on a single slash component (dataset/ffhq256).
        if not re.search(r"[^a-z0-9]", part):
            for src in sorted(_RESEARCH_ONLY_COMPACT, key=len, reverse=True):
                if src == "mfr":
                    continue
                if part_compact.startswith(src) and _research_unsplit_remainder_ok(
                    part_compact[len(src) :]
                ):
                    return True

    return _research_segments_match(norm.segments)


def _resolve_registry_head(
    token: str,
    registry: Mapping[str, Any],
) -> str | None:
    """Longest registry key matching slash parts / progressive segment prefixes.

    Resolves ``dcface_v2`` → ``dcface``, ``myorg/dcface`` → ``dcface``,
    ``dcface/v2`` → ``dcface`` (BR-36).
    """
    if not token or not str(token).strip():
        return None
    norm = _normalize_for_match(str(token))
    if norm.has_non_ascii or not norm.text:
        return None

    best: str | None = None
    best_len = -1

    def _consider(candidate: str) -> None:
        nonlocal best, best_len
        key = candidate.replace("-", "_")
        if key in registry and len(key) > best_len:
            best = key
            best_len = len(key)

    _consider(norm.text)
    for part in norm.slash_parts:
        _consider(part)
        part_segs = _part_segments(part)
        # Progressive prefixes, longest first.
        for k in range(len(part_segs), 0, -1):
            _consider("_".join(part_segs[:k]))
        for seg in part_segs:
            _consider(seg)
    return best


# Licence-bearing keys examined together so a denylisted secondary cannot hide
# behind an allowlisted primary (BR-35).
_LICENSE_FIELD_KEYS: tuple[str, ...] = ("license", "spdx_id", "license_id")


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
    """First non-empty licence field (legacy helper; prefer ``_license_values_of``)."""
    values = _license_values_of(row)
    return values[0] if values else ""


def _license_values_of(row: Mapping[str, Any]) -> list[str]:
    """Collect every non-empty licence-bearing field present on ``row`` (BR-35)."""
    values: list[str] = []
    seen: set[str] = set()
    for key in _LICENSE_FIELD_KEYS:
        if key not in row:
            continue
        raw = row[key]
        if raw is None or not isinstance(raw, str):
            continue
        tag = raw.strip()
        if not tag:
            continue
        # Preserve declaration order; de-dupe exact strings only.
        if tag not in seen:
            seen.add(tag)
            values.append(tag)
    return values


def _audit_row_licenses(
    row: Mapping[str, Any],
    *,
    category: PolicyCategory,
    required: bool = True,
) -> LicenseAuditResult:
    """Audit every licence field; fail closed on ambiguity or any denylist hit.

    Distinct licence *values* on the same row are ``invalid_row`` (BR-35).
    When values agree, a single ``audit_spdx`` runs. When they disagree, the
    row is rejected rather than silently preferring the first-truthy key.
    """
    # Type-check every present licence key first.
    for key in _LICENSE_FIELD_KEYS:
        if key not in row:
            continue
        raw = row[key]
        if raw is None:
            return _fail(
                RejectionReason.INVALID_ROW,
                detail=f"provenance row field {key!r} must be a string, got None",
                category=category,
            )
        if not isinstance(raw, str):
            return _fail(
                RejectionReason.INVALID_ROW,
                detail=(
                    f"provenance row field {key!r} must be a string, "
                    f"got {type(raw).__name__}"
                ),
                category=category,
            )

    values = _license_values_of(row)
    if not values:
        if required:
            return _fail(
                RejectionReason.MISSING_LICENSE_FIELD,
                detail="license / spdx_id field is required",
                category=category,
            )
        return _pass(detail="no license field present", category=category)

    # Normalise for comparison (casefold) — disagreeing SPDX ids fail closed.
    folded = {v.casefold() for v in values}
    if len(folded) > 1:
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                "provenance row declares disagreeing licence values "
                f"{values!r}; fail-closed on ambiguity"
            ),
            category=category,
        )

    # Values agree (possibly different case) — audit the first declaration.
    spdx_result = audit_spdx(values[0])
    if not spdx_result.ok:
        return LicenseAuditResult(
            verdict=spdx_result.verdict,
            reason=spdx_result.reason,
            detail=spdx_result.detail,
            category=category,
        )
    return _pass(detail=spdx_result.detail, category=category)


def _source_of(row: Mapping[str, Any]) -> str:
    raw = row.get("source") or ""
    if not isinstance(raw, str):
        return ""
    return raw.strip()


def _parse_row_category(
    row: Mapping[str, Any],
    *,
    audit_category: PolicyCategory,
) -> tuple[PolicyCategory | None, LicenseAuditResult | None]:
    """Parse row-declared ``category`` once (BR-38). Non-dispatching (BR-34).

    Returns ``(declared_or_None, error_or_None)``. Unknown values fail
    ``invalid_row``; empty/absent yields ``(None, None)``.
    """
    if "category" not in row:
        return None, None
    raw_cat = row["category"]
    if raw_cat is None:
        return None, None
    if not isinstance(raw_cat, str):
        return None, _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                "row category must be a string, "
                f"got {type(raw_cat).__name__}"
            ),
            category=audit_category,
        )
    text = raw_cat.strip()
    if not text:
        return None, None
    try:
        return PolicyCategory(text), None
    except ValueError:
        return None, _fail(
            RejectionReason.INVALID_ROW,
            detail=f"unknown policy category {raw_cat!r}",
            category=audit_category,
        )


def _is_operator_owned_source(source: str) -> bool:
    """True for self-generated / operator-* provenance sources."""
    return _normalize_token(source) in _POSITIVE_TRAINING_SOURCES


def _is_positive_or_registered_source(source: str) -> bool:
    """Source is on the positive allowlist, model-ingest registry, or synthetic registry."""
    if not source or not str(source).strip():
        return False
    if _is_operator_owned_source(source):
        return True
    if _is_model_ingest_key(source) or _resolve_model_key(source) in MODEL_INGEST_ENTRIES:
        return True
    if _resolve_registry_head(source, SYNTHETIC_SOURCE_ENTRIES) is not None:
        return True
    # Alias forms (blazeface, rtdetr, …).
    resolved = _resolve_model_key(source)
    if resolved in MODEL_INGEST_ENTRIES:
        return True
    return False


def _derived_ingest_key(derived: str) -> str | None:
    """Return the MODEL_INGEST registry key for ``derived``'s head, or None.

    Uses the full first slash-component (``rt-detr`` → ``rt_detr``) and
    progressive segment prefixes so multi-token heads resolve correctly.
    """
    if not derived or not str(derived).strip():
        return None
    norm = _normalize_for_match(str(derived))
    if norm.has_non_ascii or not norm.text:
        return None

    candidates: list[str] = []
    if norm.slash_parts:
        head = norm.slash_parts[0].replace("-", "_")
        candidates.append(head)
        segs = _part_segments(head)
        for k in range(len(segs), 0, -1):
            candidates.append("_".join(segs[:k]))
    candidates.append(norm.text.replace("-", "_"))

    seen: set[str] = set()
    for cand in candidates:
        if not cand or cand in seen:
            continue
        seen.add(cand)
        resolved = _resolve_model_key(cand)
        if resolved in MODEL_INGEST_ENTRIES:
            return resolved
    return None


def _common_provenance_checks(
    row: Mapping[str, Any],
    *,
    category: PolicyCategory,
) -> LicenseAuditResult | None:
    """Unconditional rules shared by every row-shaped entry point (BR-26).

    Currently: ``derived_from_model`` NC ban. Returns a FAIL result when a
    common rule fires; ``None`` means the caller may continue with
    category-specific gates.
    """
    if "derived_from_model" not in row:
        return None
    raw = row["derived_from_model"]
    if raw is None:
        return _fail(
            RejectionReason.INVALID_ROW,
            detail="provenance row field 'derived_from_model' must be a string, got None",
            category=category,
        )
    if not isinstance(raw, str):
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                "provenance row field 'derived_from_model' must be a string, "
                f"got {type(raw).__name__}"
            ),
            category=category,
        )
    derived_result = audit_derived_from_model(raw)
    if not derived_result.ok:
        # Preserve NC / invalid reasons; re-tag category for the calling door.
        return LicenseAuditResult(
            verdict=derived_result.verdict,
            reason=derived_result.reason,
            detail=derived_result.detail,
            category=category,
        )
    return None


# ---------------------------------------------------------------------------
# Public audit functions
# ---------------------------------------------------------------------------


def audit_derived_from_model(derived_from_model: str | None) -> LicenseAuditResult:
    """Audit a ``derived_from_model`` provenance tag (buffalo OUTPUT ban).

    Empty string is allowed (not every row is model-derived). Any match
    against the pinned NC pattern list or NC model ids FAILS with
    ``RejectionReason.NC_MODEL_DERIVED``. Non-ASCII residue after shared
    normalisation FAILS ``invalid_row`` (BR-21 fail-closed).
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
    norm = _normalize_for_match(text)
    if norm.has_non_ascii:
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                f"derived_from_model={text!r} contains non-ASCII residue after "
                "NFKC/Cf normalisation; confusable scripts are fail-closed"
            ),
            category=PolicyCategory.TRAINING_DATA,
        )
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
    """Audit a training-data ``source`` field against NC models + research-only.

    NC model patterns/ids take precedence over research-only (BR-20): banned
    weights named as ``source`` fail with ``nc_model_derived`` just as they
    do in ``derived_from_model``. Does **not** inspect ``generator_lineage``.
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
    norm = _normalize_for_match(text)
    if norm.has_non_ascii:
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                f"source {text!r} contains non-ASCII residue after "
                "NFKC/Cf normalisation; confusable scripts are fail-closed"
            ),
            category=PolicyCategory.TRAINING_DATA,
        )
    # BR-20: NC matcher over source (precedence over research_only_source).
    matched = match_nc_model_pattern(text)
    if matched is not None:
        return _fail(
            RejectionReason.NC_MODEL_DERIVED,
            detail=(
                f"source={text!r} matches non-commercial pattern {matched!r}; "
                "NC weights are banned regardless of which field carries them"
            ),
            category=PolicyCategory.TRAINING_DATA,
        )
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

    Unconditional NC provenance (``derived_from_model``) is applied via
    :func:`_common_provenance_checks` before category-specific gates (BR-26).
    """
    if not isinstance(asset, Mapping):
        raise LicensePolicyError(
            _fail(
                RejectionReason.UNCLEARED_OCCLUDER_ASSET,
                detail="occluder asset must be a mapping with license fields",
                category=PolicyCategory.OCCLUDER_ASSET,
            )
        )

    cat = PolicyCategory.OCCLUDER_ASSET

    # BR-26: NC ban is unconditional across every entry point.
    common = _common_provenance_checks(asset, category=cat)
    if common is not None:
        return common

    license_result = _audit_row_licenses(asset, category=cat, required=True)
    if not license_result.ok:
        return LicenseAuditResult(
            verdict=license_result.verdict,
            reason=license_result.reason,
            detail=(
                license_result.detail
                if license_result.reason is RejectionReason.INVALID_ROW
                else f"occluder asset: {license_result.detail}"
            ),
            category=cat,
        )

    clearance_raw = asset.get("clearance") or asset.get("clearance_status") or ""
    if clearance_raw is not None and not isinstance(clearance_raw, str):
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                "occluder asset clearance must be a string, "
                f"got {type(clearance_raw).__name__}"
            ),
            category=cat,
        )
    clearance = _normalize_token(str(clearance_raw)) if clearance_raw else ""
    if clearance not in OCCLUDER_ALLOWED_CLEARANCES:
        return _fail(
            RejectionReason.UNCLEARED_OCCLUDER_ASSET,
            detail=(
                f"occluder asset source photo is uncleared "
                f"(clearance={clearance_raw!r}); pack-build refused"
            ),
            category=cat,
        )

    source = _source_of(asset)
    if not source:
        return _fail(
            RejectionReason.UNKNOWN_SOURCE,
            detail="occluder asset requires a non-empty registered source",
            category=cat,
        )
    source_key = _normalize_token(source)
    if source_key not in {_normalize_token(s) for s in OCCLUDER_REGISTERED_SOURCES}:
        if _looks_like_research_source(source):
            return _fail(
                RejectionReason.RESEARCH_ONLY_SOURCE,
                detail=f"occluder asset source {source!r} is research-only",
                category=cat,
            )
        return _fail(
            RejectionReason.UNKNOWN_SOURCE,
            detail=(
                f"occluder asset source {source!r} is not a registered "
                "occluder provenance source"
            ),
            category=cat,
        )

    return _pass(
        detail="occluder asset license fields cleared for pack-build",
        category=cat,
    )


def audit_synthetic_source(
    source_id: str,
    *,
    row_clearance: str | None = None,
) -> LicenseAuditResult:
    """Audit a synthetic-identity source clearance entry.

    When the registered entry carries a ``clearance_decision``, the caller must
    supply a matching ``row_clearance`` value (PROV-04).

    Registry head resolution uses segment normalisation + progressive prefixes
    (BR-36): ``dcface_v2``, ``dcface/v2``, and ``myorg/dcface`` all resolve to
    the ``dcface`` clearance entry.
    """
    if not source_id or not str(source_id).strip():
        return _fail(
            RejectionReason.UNKNOWN_SOURCE,
            detail="synthetic source_id is required",
            category=PolicyCategory.SYNTHETIC_SOURCE,
        )
    resolved = _resolve_registry_head(source_id, SYNTHETIC_SOURCE_ENTRIES)
    entry = (
        SYNTHETIC_SOURCE_ENTRIES.get(resolved) if resolved is not None else None
    )
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

    Routes to ``audit_synthetic_source`` when (BR-33 / BR-34):
      - **caller** category is SYNTHETIC_SOURCE (and source is not the
        operator-owned ``self-generated`` tag), or
      - generator_lineage is present (and source is not pure self-generated), or
      - source/derived resolves to a known SYNTHETIC_SOURCE_ENTRIES key
        (segment / progressive-prefix resolve — BR-36), including the
        no-lineage path so clearance cannot be skipped by omitting lineage.

    Unregistered ``derived_from_model`` values that are **not** synthetic-registry
    heads are NOT routed here — they use ``UNREGISTERED_DERIVED_MODEL`` (or pass
    for operator-owned sources) instead of the synthetic clearance gate (BR-33).
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
        # BR-34: self-generated is an operator source, not a synthetic generator.
        if _normalize_token(source) != "self-generated":
            _add(source)

    if has_generator_lineage and source:
        # self-generated + lineage disclosure is informational (exemption path);
        # do not treat pure self-generated rows as synthetic generators.
        if _normalize_token(source) != "self-generated":
            _add(source)

    # BR-36: registry resolve on source/derived even without lineage, so
    # dcface_v2 cannot skip clearance by omitting generator_lineage.
    # BR-33: only actual synthetic-registry heads — not every unregistered
    # derived_from_model token.
    for token in (source, derived):
        if not token:
            continue
        if _resolve_registry_head(token, SYNTHETIC_SOURCE_ENTRIES) is not None:
            _add(token)

    return targets


def _audit_derived_registration(
    *,
    source: str,
    derived: str,
    category: PolicyCategory,
) -> LicenseAuditResult | None:
    """BR-33: split unregistered derived from the synthetic clearance path.

    Returns a FAIL when ``derived`` is non-empty, not NC (already checked),
    not a registered model-ingest head, not a synthetic-registry head, and
    the row source is not operator-owned. Operator-owned self-generated rows
    may declare an internal renderer without registering it as a synthetic
    identity source. Returns ``None`` when no dedicated derived gate fires.
    """
    if not derived:
        return None
    # Registered commercial ingest head → fine.
    if _derived_ingest_key(derived) is not None:
        return None
    # Synthetic registry head → handled by _synthetic_audit_targets.
    if _resolve_registry_head(derived, SYNTHETIC_SOURCE_ENTRIES) is not None:
        return None
    # Operator-owned sources may reference internal tools/renderers (contract 3).
    if source and _is_operator_owned_source(source):
        return None
    return _fail(
        RejectionReason.UNREGISTERED_DERIVED_MODEL,
        detail=(
            f"derived_from_model={derived!r} is not a registered model-ingest "
            "or synthetic-source entry; register the model or remove the tag"
        ),
        category=category,
    )


def audit_provenance_row(
    row: Mapping[str, Any],
    *,
    category: PolicyCategory | None = None,
) -> LicenseAuditResult:
    """Full provenance-row audit for a training-data (or synthetic) manifest row.

    ``category`` is supplied by the **caller**, never trusted from the row body
    for gate selection (BR-34). A row-declared ``category`` is parsed once
    through ``PolicyCategory`` and rejected when unknown; it is validated but
    **non-dispatching**. Caller-supplied ``category`` *does* dispatch (BR-23):

      * ``OCCLUDER_ASSET``  → :func:`audit_occluder_asset`
      * ``MODEL_INGEST``    → :func:`audit_model_ingest`
      * ``SYNTHETIC_SOURCE``→ :func:`audit_synthetic_source`
      * ``TOOLING``         → :func:`audit_tooling_row`
      * ``TRAINING_DATA``   → training-data path below

    Checks on the training-data path, in order:
      0. structural field validation (types + required keys)
      1. shared unconditional rules via :func:`_common_provenance_checks` (NC)
      2. ``source`` against research-only / NC (NOT ``generator_lineage``)
      3. fail-closed unknown source → PENDING-LEGAL-CLEARANCE (BR-22 / SECD-05)
      4. every licence-bearing field (BR-35)
      5. synthetic-source clearance for registry heads only (BR-33)
      6. unregistered ``derived_from_model`` gate (BR-33)

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

    # Parse row-declared category once (BR-38). Validated, never used for dispatch.
    _declared_cat, cat_err = _parse_row_category(row, audit_category=audit_category)
    if cat_err is not None:
        return cat_err
    del _declared_cat  # non-dispatching by design (BR-34)

    # ------------------------------------------------------------------
    # BR-23: caller-supplied category dispatches to the matching gate.
    # ------------------------------------------------------------------
    if audit_category is PolicyCategory.OCCLUDER_ASSET:
        return audit_occluder_asset(row)

    if audit_category is PolicyCategory.TOOLING:
        return audit_tooling_row(row)

    if audit_category is PolicyCategory.MODEL_INGEST:
        # Prefer explicit model_id; fall back to source (row-shaped ingest).
        model_id = ""
        for key in ("model_id", "source", "package_name", "package"):
            raw = row.get(key)
            if isinstance(raw, str) and raw.strip():
                model_id = raw.strip()
                break
        common = _common_provenance_checks(row, category=PolicyCategory.MODEL_INGEST)
        if common is not None:
            return common
        return audit_model_ingest(model_id)

    if audit_category is PolicyCategory.SYNTHETIC_SOURCE:
        source_raw = row.get("source")
        if not isinstance(source_raw, str) or not source_raw.strip():
            return _fail(
                RejectionReason.UNKNOWN_SOURCE,
                detail="synthetic_source category requires a non-empty source field",
                category=PolicyCategory.SYNTHETIC_SOURCE,
            )
        common = _common_provenance_checks(row, category=PolicyCategory.SYNTHETIC_SOURCE)
        if common is not None:
            return common
        row_clearance_raw = row.get("clearance")
        row_clearance = (
            row_clearance_raw.strip()
            if isinstance(row_clearance_raw, str)
            else None
        )
        return audit_synthetic_source(source_raw.strip(), row_clearance=row_clearance)

    # ------------------------------------------------------------------
    # TRAINING_DATA path (default)
    # ------------------------------------------------------------------

    # Structural validation — require derived_from_model KEY ('' is valid opt-out).
    _derived_val, derived_err = _require_string_field(
        row, "derived_from_model", required=True, category=audit_category
    )
    if derived_err is not None:
        return derived_err

    for key in ("source", "clearance", "generator_lineage"):
        _val, field_err = _require_string_field(
            row, key, required=False, category=audit_category
        )
        if field_err is not None:
            return field_err
        del _val

    # Licence keys type-checked inside _audit_row_licenses.

    # BR-26: shared unconditional NC (and type) checks.
    common = _common_provenance_checks(row, category=audit_category)
    if common is not None:
        return common

    derived = (_derived_val or "").strip() if _derived_val is not None else ""

    source = ""
    if "source" in row and isinstance(row["source"], str):
        source = row["source"].strip()

    # Training-data audits always require source (row cannot waive via category).
    if not source:
        return _fail(
            RejectionReason.UNKNOWN_SOURCE,
            detail="training-data provenance row requires a source field",
            category=PolicyCategory.TRAINING_DATA,
        )
    source_result = audit_source(source)
    if not source_result.ok:
        return source_result

    # Licence before the fail-closed source allowlist so a pseudo-licence tag
    # (e.g. ``self-generated`` as SPDX — BR-25) is reported rather than masked
    # by the later PENDING-LEGAL-CLEARANCE default.
    license_result = _audit_row_licenses(
        row, category=audit_category, required=True
    )
    if not license_result.ok:
        return license_result

    # BR-22 / SECD-05: fail closed on the source axis. Research / NC already
    # handled by audit_source; remaining unknowns are PENDING-LEGAL-CLEARANCE
    # unless positively allowlisted or registered.
    if not _is_positive_or_registered_source(source):
        return _fail(
            RejectionReason.PENDING_LEGAL_CLEARANCE,
            detail=(
                f"source {source!r} is not on the positive allowlist or a "
                "registered ingest/synthetic entry; defaults to "
                "PENDING-LEGAL-CLEARANCE"
            ),
            category=PolicyCategory.TRAINING_DATA,
        )

    has_lineage = bool(str(row.get("generator_lineage") or "").strip())
    # BR-34: only the *caller-supplied* category participates in synthetic
    # routing — never the row-declared value.
    row_clearance_raw = row.get("clearance")
    row_clearance = (
        row_clearance_raw.strip()
        if isinstance(row_clearance_raw, str)
        else None
    )

    for cand in _synthetic_audit_targets(
        source=source,
        derived=derived,
        category=audit_category,
        has_generator_lineage=has_lineage,
    ):
        synth_result = audit_synthetic_source(cand, row_clearance=row_clearance)
        if not synth_result.ok:
            return synth_result

    # BR-33: unregistered derived (after NC + synthetic-head routing).
    unreg = _audit_derived_registration(
        source=source, derived=derived, category=audit_category
    )
    if unreg is not None:
        return unreg

    return _pass(
        detail="provenance row passes license policy",
        category=audit_category,
    )


def audit_tooling_row(row: Mapping[str, Any]) -> LicenseAuditResult:
    """Audit a tooling dependency row (caller-owned TOOLING category).

    Resolves a package identifier from ``package`` / ``package_name`` /
    ``source`` and runs :func:`audit_tooling_dependency` **before** any
    row-declared SPDX check so a self-declared licence cannot launder a
    denylisted package (BR-24). Missing package identifier fails closed.
    """
    if not isinstance(row, Mapping):
        raise LicensePolicyError(
            _fail(
                RejectionReason.UNKNOWN_SOURCE,
                detail="tooling row must be a mapping",
                category=PolicyCategory.TOOLING,
            )
        )

    cat = PolicyCategory.TOOLING

    common = _common_provenance_checks(row, category=cat)
    if common is not None:
        return common

    package = ""
    for key in ("package", "package_name", "source"):
        raw = row.get(key)
        if isinstance(raw, str) and raw.strip():
            package = raw.strip()
            break

    if not package:
        return _fail(
            RejectionReason.UNKNOWN_SOURCE,
            detail=(
                "tooling row requires a package identifier "
                "(package / package_name / source)"
            ),
            category=cat,
        )

    # Authoritative package gate — denylist / allowlist pin wins over row SPDX.
    dep_result = audit_tooling_dependency(package)
    if not dep_result.ok:
        return dep_result

    # Optional extra: if the row self-declares a licence, it must not be
    # denylisted. The pinned allowlist entry remains authoritative for PASS.
    license_values = _license_values_of(row)
    if license_values:
        license_result = _audit_row_licenses(row, category=cat, required=False)
        if not license_result.ok:
            # Denylisted / research / unknown SPDX on the row still fails, but
            # denylisted *packages* already returned above.
            return license_result

    return _pass(
        detail=dep_result.detail,
        category=cat,
    )


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
