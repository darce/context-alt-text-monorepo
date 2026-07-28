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


class ClearanceStatus(StrEnum):
    """Clearance state for synthetic sources and assets."""

    ALLOWED = "allowed"
    DENIED = "denied"
    PENDING_LEGAL_CLEARANCE = "pending_legal_clearance"
    OPERATOR_CLEARED = "operator_cleared"
    UNCLEARED = "uncleared"


class CommercialUse(StrEnum):
    """Commercial-use classification for registered entries."""

    ALLOWED = "allowed"
    NON_COMMERCIAL = "non_commercial"
    FORBIDDEN = "forbidden"


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
# SPDX allow / deny lists
# ---------------------------------------------------------------------------

# Commercially usable SPDX identifiers accepted for training data, model ingest,
# and occluder assets (after other gates).
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


# ---------------------------------------------------------------------------
# PINNED non-commercial model pattern list (buffalo OUTPUT ban wall 1)
# ---------------------------------------------------------------------------

# Patterns are matched case-insensitively against ``derived_from_model``.
# Glob semantics:
#   - ``prefix/*``  → exact prefix + "/" + any non-empty suffix
#   - ``prefix*``   → prefix + any suffix (including empty)
#   - bare token    → exact match OR token + "/" + suffix
#
# ``dcface/*`` is intentionally ABSENT — operator clearance
# ``dcface_operator_clearance_20260723`` keeps it off this list.
NC_MODEL_PATTERNS: tuple[str, ...] = (
    "insightface/*",
    "insightface",
    "buffalo*",
    "buffalo",
)

# Models registered as non-commercial in the policy table; any
# ``derived_from_model`` whose first path segment equals one of these ids
# also FAILS (covers NC-tagged entries beyond the pinned pattern list).
NC_MODEL_IDS: frozenset[str] = frozenset(
    {
        "insightface",
        "buffalo",
        "buffalo_l",
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
    role: str  # "face_detector" | "person_detector"
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
        role="face_detector",
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
        role="face_detector",
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
        role="person_detector",
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
        role="person_detector",
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
        role="person_detector",
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
        role="face_detector",
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
        role="face_embedder",
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
            spdx_id="operator-cleared",
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


# ---------------------------------------------------------------------------
# Pure matching helpers
# ---------------------------------------------------------------------------


def _normalize_token(value: str) -> str:
    return value.strip().lower()


def match_nc_model_pattern(derived_from_model: str) -> str | None:
    """Return the pinned NC pattern that matches ``derived_from_model``, or None.

    Matching is case-insensitive. Patterns follow the pinned list semantics
    documented on ``NC_MODEL_PATTERNS``. Also fails ids in ``NC_MODEL_IDS``
    (first path segment) so NC-tagged registry entries are covered without
    relying on the pattern list alone.
    """
    if not derived_from_model or not str(derived_from_model).strip():
        return None
    text = _normalize_token(str(derived_from_model))
    head = text.split("/", 1)[0]

    # Registered NC model ids (first path segment).
    if head in {_normalize_token(m) for m in NC_MODEL_IDS}:
        # Prefer a pinned pattern when one also matches, else the bare id.
        for pattern in NC_MODEL_PATTERNS:
            if _pattern_matches(pattern, text):
                return pattern
        return head

    for pattern in NC_MODEL_PATTERNS:
        if _pattern_matches(pattern, text):
            return pattern
    return None


def _pattern_matches(pattern: str, text: str) -> bool:
    p = _normalize_token(pattern)
    if p.endswith("/*"):
        prefix = p[:-2]
        return text == prefix or text.startswith(prefix + "/")
    if p.endswith("*"):
        prefix = p[:-1]
        return text.startswith(prefix)
    return text == p or text.startswith(p + "/")


def _looks_like_research_source(value: str) -> bool:
    token = _normalize_token(value)
    if not token:
        return False
    if token in RESEARCH_ONLY_SOURCES:
        return True
    # Allow ``casia-webface`` style compounds already listed; also catch
    # path-ish tags like ``dataset/ffhq``.
    head = token.split("/", 1)[0]
    if head in RESEARCH_ONLY_SOURCES:
        return True
    for src in RESEARCH_ONLY_SOURCES:
        if token == src or token.startswith(src + "/") or token.startswith(src + "-"):
            return True
    return False


def _spdx_of(row: Mapping[str, Any]) -> str:
    raw = row.get("license") or row.get("spdx_id") or row.get("license_id") or ""
    return str(raw).strip()


def _source_of(row: Mapping[str, Any]) -> str:
    raw = row.get("source") or ""
    return str(raw).strip()


def _derived_of(row: Mapping[str, Any]) -> str:
    raw = row.get("derived_from_model") or ""
    return str(raw).strip()


# ---------------------------------------------------------------------------
# Public audit functions
# ---------------------------------------------------------------------------


def audit_derived_from_model(derived_from_model: str | None) -> LicenseAuditResult:
    """Audit a ``derived_from_model`` provenance tag (buffalo OUTPUT ban).

    Empty / missing is allowed (not every row is model-derived). Any match
    against the pinned NC pattern list or NC model ids FAILS with
    ``RejectionReason.NC_MODEL_DERIVED``.
    """
    if derived_from_model is None or not str(derived_from_model).strip():
        return _pass(detail="no derived_from_model tag")

    text = str(derived_from_model).strip()
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

    # Operator-cleared synthetic generators (dcface/*) pass this gate; other
    # synthetic first-segments are checked via synthetic-source clearance on
    # the full provenance row.
    return _pass(
        detail=f"derived_from_model={text!r} is not on the NC pattern list",
        category=PolicyCategory.TRAINING_DATA,
    )


def audit_spdx(spdx_id: str | None) -> LicenseAuditResult:
    """Audit a bare SPDX / license tag."""
    if spdx_id is None or not str(spdx_id).strip():
        return _fail(
            RejectionReason.MISSING_LICENSE_FIELD,
            detail="license / spdx_id field is required",
        )
    tag = str(spdx_id).strip()
    if tag in DENYLISTED_SPDX_IDS:
        reason = (
            RejectionReason.RESEARCH_ONLY_LICENSE
            if tag in {"research-only", "Non-Commercial", "non-commercial", "NC", "proprietary-nc"}
            or "NC" in tag.upper().replace("NON-COMMERCIAL", "NC")
            else RejectionReason.DENYLISTED_LICENSE
        )
        # Normalize NC-family to research/NC reason for clearer fixtures.
        if tag.lower() in {
            "research-only",
            "non-commercial",
            "nc",
            "proprietary-nc",
            "cc-by-nc-4.0",
            "cc-by-nc-sa-4.0",
            "cc-by-nc-nd-4.0",
        }:
            reason = RejectionReason.RESEARCH_ONLY_LICENSE
        return _fail(
            reason,
            detail=f"license {tag!r} is denylisted for commercial training use",
        )
    if tag in ALLOWED_SPDX_IDS:
        return _pass(detail=f"license {tag!r} is allowlisted")
    # operator-cleared is accepted only when paired with a clearance decision
    # on a synthetic source row — bare tag alone is unknown.
    if tag == "operator-cleared":
        return _pass(detail="operator-cleared license tag (requires clearance ref on row)")
    if tag == "PENDING-LEGAL-CLEARANCE":
        return _fail(
            RejectionReason.PENDING_LEGAL_CLEARANCE,
            detail="license is PENDING-LEGAL-CLEARANCE",
        )
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
    text = str(source).strip()
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
    key = _normalize_token(str(model_id)).replace("-", "_").replace(" ", "_")
    # Normalize common display-name aliases to registry keys.
    aliases = {
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
    resolved = aliases.get(key, key)

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
    key = _normalize_token(model_id).replace("-", "_").replace(" ", "_")
    aliases = {
        "blazeface": "mediapipe_blazeface",
        "blazeface_fpn_ssh": "paddle_blazeface_fpn_ssh",
        "rtdetr": "rt_detr",
        "dfine": "d_fine",
        "picodet": "pp_picodet",
    }
    resolved = aliases.get(key, key)
    entry = MODEL_INGEST_ENTRIES.get(resolved)
    if entry is None:
        # audit passed via alias path that maps into MODEL_INGEST_ENTRIES
        for candidate in MODEL_INGEST_ENTRIES.values():
            if _normalize_token(candidate.model_id) == resolved:
                return candidate
            if _normalize_token(candidate.display_name).replace(" ", "_").replace("-", "_") == key:
                return candidate
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
        # Also accept hyphen/underscore variants.
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

    Required: a license field on the allowlist, and a clearance status that is
    not uncleared / pending. Uncleared source photos FAIL pack-build.
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
    clearance = _normalize_token(str(clearance_raw)) if clearance_raw else ""
    # Pack-build requires an explicit positive clearance. Missing, uncleared,
    # pending, or denied status FAILS even when SPDX looks commercially clean.
    _OCCLUDER_ALLOWED_CLEARANCES = frozenset(
        {
            ClearanceStatus.ALLOWED.value,
            ClearanceStatus.OPERATOR_CLEARED.value,
            "cleared",
            "license_cleared",
        }
    )
    if clearance not in _OCCLUDER_ALLOWED_CLEARANCES:
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
    if source and _looks_like_research_source(source):
        return _fail(
            RejectionReason.RESEARCH_ONLY_SOURCE,
            detail=f"occluder asset source {source!r} is research-only",
            category=PolicyCategory.OCCLUDER_ASSET,
        )

    return _pass(
        detail="occluder asset license fields cleared for pack-build",
        category=PolicyCategory.OCCLUDER_ASSET,
    )


def audit_synthetic_source(source_id: str) -> LicenseAuditResult:
    """Audit a synthetic-identity source clearance entry."""
    if not source_id or not str(source_id).strip():
        return _fail(
            RejectionReason.UNKNOWN_SOURCE,
            detail="synthetic source_id is required",
            category=PolicyCategory.SYNTHETIC_SOURCE,
        )
    key = _normalize_token(source_id)
    # derived_from_model style: dcface/<generator-id> → dcface
    head = key.split("/", 1)[0]
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
    return _pass(
        detail=(
            f"synthetic source {entry.source_id!r} commercial-allowed "
            f"(clearance={entry.verification.clearance_decision or 'n/a'})"
        ),
        category=PolicyCategory.SYNTHETIC_SOURCE,
    )


def audit_provenance_row(row: Mapping[str, Any]) -> LicenseAuditResult:
    """Full provenance-row audit for a training-data (or synthetic) manifest row.

    Checks, in order:
      1. ``derived_from_model`` against the pinned NC pattern list
      2. ``source`` against research-only sources (NOT ``generator_lineage``)
      3. ``license`` / SPDX allow-deny
      4. synthetic-source clearance when ``source`` is a known synthetic id
         or when ``derived_from_model`` starts with a synthetic generator id

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

    derived = _derived_of(row)
    derived_result = audit_derived_from_model(derived or None)
    if not derived_result.ok:
        return derived_result

    source = _source_of(row)
    if source:
        source_result = audit_source(source)
        if not source_result.ok:
            return source_result
    else:
        # Training rows need a source; allow rows that are pure model-ingest
        # checks to omit it only when category says so.
        category = str(row.get("category") or PolicyCategory.TRAINING_DATA.value)
        if category == PolicyCategory.TRAINING_DATA.value:
            return _fail(
                RejectionReason.UNKNOWN_SOURCE,
                detail="training-data provenance row requires a source field",
                category=PolicyCategory.TRAINING_DATA,
            )

    spdx = _spdx_of(row)
    spdx_result = audit_spdx(spdx)
    if not spdx_result.ok:
        return spdx_result

    # Synthetic-source clearance: when source or derived head is a synthetic id.
    synthetic_keys = set(SYNTHETIC_SOURCE_ENTRIES)
    candidates: list[str] = []
    if source and _normalize_token(source).split("/", 1)[0] in synthetic_keys:
        candidates.append(source)
    if derived and _normalize_token(derived).split("/", 1)[0] in synthetic_keys:
        candidates.append(derived)
    for cand in candidates:
        synth_result = audit_synthetic_source(cand)
        if not synth_result.ok:
            return synth_result

    # generator_lineage is intentionally unread for rejection purposes.
    # Presence of FFHQ/CASIA there does not fail the row.
    return _pass(
        detail="provenance row passes license policy",
        category=PolicyCategory.TRAINING_DATA,
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
