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
#
# Matching is exact membership against the import-time expanded frozenset
# ``RESEARCH_SOURCE_IDS_EXPANDED`` (B4b / WEB-24 / SECD-05). Shape-inference
# (progressive prefixes, startswith, version-segment regexes) is intentionally
# absent: expand the trusted registry, never the untrusted input.
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
# PINNED non-commercial model id seeds (buffalo OUTPUT ban wall 1)
# ---------------------------------------------------------------------------

# Patterns retained as declarative seeds for documentation + M2 discrimination.
# Matching no longer walks glob/prefix shape on untrusted input (B4b); seeds
# feed ``NC_MODEL_IDS`` / ``NC_MODEL_IDS_EXPANDED`` at import time.
NC_MODEL_PATTERNS: tuple[str, ...] = (
    "insightface/*",
    "insightface",
    "buffalo*",
    "buffalo",
)

# Extra pinned NC model ids beyond table-derived entries (ArcFace ecosystem
# weights that are non-commercial but not always present as registry rows).
# Explicit multi-segment variants live in ``_NC_EXPLICIT_VARIANTS`` so the
# matcher never infers them from spelling shape.
_PINNED_NC_MODEL_IDS: frozenset[str] = frozenset(
    {
        "buffalo",
        "buffalo_s",
        "buffalo_sc",
        "buffalo_l",
        "buffalo_l2",
        "retinaface",
        "arcface",
        "antelopev2",
        "insightface",
    }
)

# Explicit NC forms that must fail but are not a single common-suffix hop from
# a seed (multi-segment InsightFace pack / backbone tags).
_NC_EXPLICIT_VARIANTS: frozenset[str] = frozenset(
    {
        "insightface_buffalo_l",
        "insightface_buffalo_s",
        "insightface_buffalo_sc",
        "insightface_buffalo_l2",
        "retinaface_r50",
        "retinaface_mnet025",
        "retinaface_mnet025_v2",
        "arcface_r100",
        "arcface_glint360k_r100",
        "vec2face_g1",
        "antelope_v2",
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
    "yolo": PackageDenylistEntry(
        package_id="yolo",
        display_name="YOLO (Ultralytics family)",
        spdx_id="AGPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes="Ultralytics AGPL family alias; banned for cascade person-detection.",
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

# Operator-owned *lineage* tags (GATE-21 / NAME-03). Distinct from the
# training-data provenance namespace in ``source`` / ``_POSITIVE_TRAINING_SOURCES``.
# Registration exemption answers "is this lineage operator-owned?" from the
# lineage value itself — never from a door-dependent ``source`` field.
# Operator-controlled registry; fails closed for anything not listed (BR-24).
OPERATOR_OWNED_LINEAGE: frozenset[str] = frozenset(
    {
        "acx/occluder-renderer-v1",
        "acx_internal_projector",
    }
)
# GATE-24: resolution here is whole-token exact (modulo case/separator
# canonicalisation) -- deliberately NOT :func:`_resolve_registry_head`, whose
# slash-component and variant-suffix vocabulary would let a row author mint
# bypass tokens the operator never registered (``evilcorp/acx_internal_projector``,
# ``acx_internal_projector_r50``). This registry is a pure exemption, so
# over-resolution is a laundering hole, not a naming convenience (BR-24 /
# SECD-05). Matches :func:`_derived_ingest_key`'s exact-only discipline (BR-52).

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
    "yolo": "yolo",
    "yunet": "yunet",
    "sface": "sface",
}


# ---------------------------------------------------------------------------
# Import-time registry expansion (B4b inversion)
# ---------------------------------------------------------------------------

# Bounded variant suffixes cross-producted with registry base ids at import.
# Applied to the *registry*, never walked as a grammar over untrusted input.
_COMMON_VARIANT_SUFFIXES: tuple[str, ...] = (
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
    "r50",
    "r100",
    "l",
    "s",
    "sc",
    "l2",
    "g1",
    "mnet025",
    "v1",
    "v2",
    "v3",
    "v4",
    "256",
    "512",
    "1024",
)

# Research sources that must stay exact-only after expansion (BR-58).
_RESEARCH_EXACT_ONLY: frozenset[str] = frozenset({"mfr"})

# Known model-file extensions stripped before canonicalisation (BR-54).
_MODEL_FILE_EXTENSIONS: tuple[str, ...] = (
    ".onnx",
    ".pt",
    ".pth",
    ".bin",
    ".safetensors",
    ".pkl",
    ".pb",
    ".tflite",
    ".params",
)


def canonical(value: str) -> str | None:
    """NFKC → strip Cf/format chars → casefold → unify separators → collapse.

    Separators unified to ``_``: runs of ``[-_.\\s]+``. Slash (``/``) and
    backslash are preserved as path separators so slash-components can be
    exact-matched independently. Returns ``None`` when any non-ASCII residue
    survives (untrusted / undecidable — callers treat as ``invalid_row``).
    """
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", str(value))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    text = text.strip().casefold()
    if not text:
        return ""
    # Preserve path separators; normalise backslash to slash.
    text = text.replace("\\", "/")
    # Strip known model-file extensions on each slash component (BR-54).
    parts = text.split("/")
    stripped_parts: list[str] = []
    for part in parts:
        p = part
        for ext in _MODEL_FILE_EXTENSIONS:
            if p.endswith(ext):
                p = p[: -len(ext)]
                break
        stripped_parts.append(p)
    text = "/".join(stripped_parts)
    # Unify non-slash separators to underscore; collapse runs; trim.
    text = re.sub(r"[-_.\s]+", "_", text)
    text = re.sub(r"_+", "_", text)
    text = "/".join(seg.strip("_") for seg in text.split("/"))
    text = text.strip("_")
    if any(ord(ch) > 127 for ch in text):
        return None
    return text


def _compact_canonical(value: str) -> str:
    """Drop underscores from a canonical id (``casia_webface`` → ``casiawebface``)."""
    return value.replace("_", "")


def _expand_id_forms(
    base: str,
    *,
    exact_only: bool = False,
    extra_variants: tuple[str, ...] | frozenset[str] = (),
    suffixes: tuple[str, ...] = _COMMON_VARIANT_SUFFIXES,
) -> set[str]:
    """Expand one registry base id into exact membership forms.

    Produces the canonical form, its compact form, optional explicit variants,
    and (unless ``exact_only``) a cross-product with ``suffixes`` as both
    ``base_suf`` and unsplit ``basesuf`` (plus compact equivalents).
    """
    out: set[str] = set()
    c = canonical(base)
    if c is None or c == "":
        return out
    out.add(c)
    out.add(_compact_canonical(c))
    for raw in extra_variants:
        vc = canonical(raw)
        if vc is None or vc == "":
            continue
        out.add(vc)
        out.add(_compact_canonical(vc))
    if exact_only:
        return out
    # Separated and unsplit suffix forms (registry-side expansion only).
    for suf in suffixes:
        # Separated form (vggface2_train, ffhq_aligned, casia_webface_extra).
        separated = f"{c}_{suf}"
        out.add(separated)
        # M8 discrimination anchor: unsplit compound (ffhq256, widerfacehd,
        # casiawebfaceextra). Built from compact base so it is NOT a duplicate
        # of compact(separated) for multi-segment bases.
        unsplit = f"{_compact_canonical(c)}{suf}"  # unsplit compound startswith-equivalent
        out.add(unsplit)
    return out


def _expand_ids(
    ids: frozenset[str] | set[str] | tuple[str, ...],
    *,
    exact_only_ids: frozenset[str] = frozenset(),
    extra_variants: frozenset[str] = frozenset(),
) -> frozenset[str]:
    """Expand a set of base ids with common suffixes + compact forms."""
    out: set[str] = set()
    for raw in ids:
        c = canonical(raw)
        if c is None or not c:
            continue
        exact = c in exact_only_ids or raw in exact_only_ids
        out |= _expand_id_forms(c, exact_only=exact)
    for raw in extra_variants:
        vc = canonical(raw)
        if vc is None or not vc:
            continue
        out.add(vc)
        out.add(_compact_canonical(vc))
        # Also expand explicit variants with one suffix hop (retinaface_mnet025 + v2).
        out |= _expand_id_forms(vc, exact_only=False)
    return frozenset(out)


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
      * ``_NC_EXPLICIT_VARIANTS`` multi-segment pack ids
    """
    ids: set[str] = set(_PINNED_NC_MODEL_IDS)
    ids.update(_NC_EXPLICIT_VARIANTS)
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
    # Canonicalise seed forms.
    out: set[str] = set()
    for i in ids:
        c = canonical(i)
        if c:
            out.add(c)
    return frozenset(out)


# Derived at import time — any non-ALLOWED table entry is denylisted for
# derived_from_model matching (plan: any model whose license_policy entry is NC).
NC_MODEL_IDS: frozenset[str] = _derive_nc_model_ids()

# Expanded denial sets — exact membership only (B4b / WEB-24).
# Built solely from NC_MODEL_IDS so M3 (empty NC_MODEL_IDS) is discrimination-complete.
NC_MODEL_IDS_EXPANDED: frozenset[str] = _expand_ids(NC_MODEL_IDS)

RESEARCH_SOURCE_IDS_EXPANDED: frozenset[str] = _expand_ids(
    RESEARCH_ONLY_SOURCES,
    exact_only_ids=_RESEARCH_EXACT_ONLY,
)

# Synthetic registry: base ids + bounded version suffixes (dcface_v2, …).
_SYNTHETIC_BASE_IDS: frozenset[str] = frozenset(SYNTHETIC_SOURCE_ENTRIES.keys())
SYNTHETIC_SOURCE_IDS_EXPANDED: frozenset[str] = _expand_ids(_SYNTHETIC_BASE_IDS)

# Map every expanded synthetic id back to its registry entry key (exact only).
_SYNTHETIC_EXPANDED_TO_HEAD: dict[str, str] = {}
for _sk, _sentry in SYNTHETIC_SOURCE_ENTRIES.items():
    _sc = canonical(_sk)
    if _sc is None:
        continue
    for _form in _expand_id_forms(_sc, exact_only=False):
        _SYNTHETIC_EXPANDED_TO_HEAD.setdefault(_form, _sc)


# Clean-name corpus that must never land in denial sets (import-time safety).
_MUST_PASS_CORPUS: frozenset[str] = frozenset(
    {
        "buffalo-wings-detector",
        "buffalo_bill_detector",
        "insightface-free",
        "not-insightface",
        "ffhq-tools",
        "celebase",
        "webfaces-r-us",
        "our_widerface_replacement",
        "arcface_alternative_v2",
        "not-retinaface",
        "mfr_train",
        "mfr/tools",
        "buffalos-eye/v1",
        "my-buffalo-free",
        "retinaface-free-reimpl",
        "insightfaces-r-us/model",
        "casiaset-detector",
        "mfrx-vendor",
        "ffhq_free_internal",
        "glint360k_free",
        "commercial-ffhq-alternative",
        "dataset_not_ffhq",
        "notffhq",
        "casia-device",
        "casiadevice",
        "deepglint-clean",
        "casia-clean",
        "ms1m-clean",
        "arcface_mit",
        "arcface_bsd",
    }
)


def _assert_no_must_pass_collisions() -> None:
    """Import-time guard: expanded denial sets must not contain clean names."""
    denial_nc = NC_MODEL_IDS_EXPANDED
    denial_rs = RESEARCH_SOURCE_IDS_EXPANDED
    exact_only = frozenset(
        x
        for raw in _RESEARCH_EXACT_ONLY
        for x in filter(
            None,
            (
                canonical(raw),
                _compact_canonical(canonical(raw) or ""),
            ),
        )
    )
    collisions: set[str] = set()
    for name in _MUST_PASS_CORPUS:
        c = canonical(name)
        if c is None:
            continue
        # whole-string
        if c in denial_nc or _compact_canonical(c) in denial_nc:
            collisions.add(name)
            continue
        if c in denial_rs or _compact_canonical(c) in denial_rs:
            collisions.add(name)
            continue
        if "/" in c:
            for part in c.split("/"):
                if not part:
                    continue
                if part in denial_nc or _compact_canonical(part) in denial_nc:
                    collisions.add(name)
                    break
                if part in exact_only or _compact_canonical(part) in exact_only:
                    continue
                if part in denial_rs or _compact_canonical(part) in denial_rs:
                    collisions.add(name)
                    break
    if collisions:
        raise AssertionError(
            f"registry expansion over-rejects clean names: {sorted(collisions)}"
        )


_assert_no_must_pass_collisions()


# ---------------------------------------------------------------------------
# Pure matching helpers — exact set membership only (B4b / WEB-24 / SECD-05)
# ---------------------------------------------------------------------------


def _normalize_token(value: str) -> str:
    """Normalise a token with unbound builtins (GATE-15).

    ``str.strip`` / ``str.lower`` so a ``str`` subclass cannot launder a dirty
    payload through overridden instance methods. Honest subclasses
    (``numpy.str_`` shape) still evaluate correctly.
    """
    return str.lower(str.strip(value))


def _resolve_model_key(model_id: str) -> str:
    """Normalise a model id / alias to a registry key (exact, no prefix walk)."""
    c = canonical(str(model_id))
    if c is None or not c:
        key = _normalize_token(str(model_id)).replace("-", "_").replace(" ", "_")
        return _MODEL_ALIASES.get(key, key)
    # Use final slash component for path-shaped ids.
    head = c.split("/")[-1] if "/" in c else c
    return _MODEL_ALIASES.get(head, head)


def _is_model_ingest_key(head: str) -> bool:
    """True when ``head`` resolves to a registered model-ingest entry."""
    resolved = _resolve_model_key(head)
    return resolved in MODEL_INGEST_ENTRIES


# Whole-string-only ids (BR-58): never match as a mere slash component.
_EXACT_ONLY_MEMBERSHIP: frozenset[str] = frozenset(
    {
        x
        for raw in _RESEARCH_EXACT_ONLY
        for x in (
            {canonical(raw) or "", _compact_canonical(canonical(raw) or "")}
        )
        if x
    }
)


def _membership_hit(
    c: str,
    expanded: frozenset[str],
    *,
    exact_only: frozenset[str] = frozenset(),
) -> str | None:
    """Exact membership of canonical form or any slash component (WEB-24).

    ``exact_only`` ids match the whole string only — never as a path component
    of a longer token (BR-58: ``mfr/tools`` must not trip on bare ``mfr``).
    """
    if not c:
        return None
    if c in expanded:
        return c
    compact = _compact_canonical(c)
    if compact and compact in expanded:
        return compact
    # Slash components only — never progressive underscore prefixes (BR-50/52).
    if "/" in c:
        for part in c.split("/"):
            if not part:
                continue
            if part in exact_only or _compact_canonical(part) in exact_only:
                continue
            if part in expanded:
                return part
            pc = _compact_canonical(part)
            if pc and pc in expanded:
                return pc
    return None


def _live_nc_expanded() -> frozenset[str]:
    """NC expanded set, honouring monkeypatched ``NC_MODEL_IDS`` (BR-38)."""
    return _expand_ids(NC_MODEL_IDS)


def match_nc_model_pattern(derived_from_model: str) -> str | None:
    """Return the pinned NC id that matches ``derived_from_model``, or None.

    Exact set membership against ``NC_MODEL_IDS_EXPANDED`` after
    :func:`canonical` (B4b / WEB-24). Non-ASCII residue yields ``None``;
    callers must treat that as ``invalid_row`` via their own canonical check.
    """
    if not derived_from_model or not str.strip(str(derived_from_model)):
        return None
    c = canonical(str(derived_from_model))
    if c is None:
        return None
    return _membership_hit(c, _live_nc_expanded())


def _looks_like_research_source(value: str) -> bool:
    """True when value identifies a research-only corpus (exact membership).

    Uses ``RESEARCH_SOURCE_IDS_EXPANDED`` only — no startswith / progressive
    prefix / version-segment grammar over the input (B4b / WEB-24 / BR-47).
    Non-ASCII residue is treated as tainted so callers fail closed.

    **The slash/underscore asymmetry is deliberate (BR-56, resolved wontfix).**
    A slash is a hierarchical separator, so each path component is an identity
    token in its own right and is matched as one; an underscore is not, so
    underscore forms match whole-string only. Reconciling the two shapes is not
    available in either direction: segment-matching underscore forms is the
    progressive-prefix grammar that BR-50/BR-52 removed for over-matching, and
    relaxing slash components to whole-string matching flips 637 currently
    rejected sources to PASS (measured), including ``vendor/casia/subset`` and
    ``acme/celeba/mirror`` — a subset or a mirror of a research corpus is still
    that corpus. Consistency does not outrank fail-safe defaults [SECD-05].
    """
    if not value or not str.strip(str(value)):
        return False
    c = canonical(str(value))
    if c is None:
        # Caller audits as invalid_row; treat as tainted if asked raw.
        return True
    if not c:
        return False
    return _membership_hit(
        c, RESEARCH_SOURCE_IDS_EXPANDED, exact_only=_EXACT_ONLY_MEMBERSHIP
    ) is not None


def _resolve_registry_head(
    token: str,
    registry: Mapping[str, Any],
) -> str | None:
    """Exact registry-head resolve (B4b / BR-50 / BR-52 / BR-36).

    A token matches when its canonical form (or a slash component) is an
    expanded form of a registry key. Progressive underscore-prefix resolution
    is intentionally absent — ``dcface_evil`` / ``not_dcface`` / ``yunet_evil``
    do not inherit clearance or ingest registration from a substring head.
    """
    if not token or not str.strip(str(token)):
        return None
    c = canonical(str(token))
    if c is None or not c:
        return None

    # Prefer the synthetic expanded→head map when auditing synthetic entries.
    if registry is SYNTHETIC_SOURCE_ENTRIES or set(registry.keys()) <= set(
        SYNTHETIC_SOURCE_ENTRIES.keys()
    ):
        hit = _membership_hit(c, SYNTHETIC_SOURCE_IDS_EXPANDED)
        if hit is not None:
            return _SYNTHETIC_EXPANDED_TO_HEAD.get(hit) or _SYNTHETIC_EXPANDED_TO_HEAD.get(
                _compact_canonical(hit)
            )
        return None

    # Generic: exact key or slash-component key (no progressive prefixes).
    keys_expanded: dict[str, str] = {}
    for key in registry:
        kc = canonical(key)
        if kc is None:
            continue
        for form in _expand_id_forms(kc, exact_only=False):
            keys_expanded.setdefault(form, kc)

    hit = _membership_hit(c, frozenset(keys_expanded))
    if hit is None:
        return None
    return keys_expanded.get(hit) or keys_expanded.get(_compact_canonical(hit))


# Licence-bearing keys examined together so a denylisted secondary cannot hide
# behind an allowlisted primary (BR-35).
_LICENSE_FIELD_KEYS: tuple[str, ...] = ("license", "spdx_id", "license_id")

# GATE-04: matching these keys exactly and case-sensitively let a denylisted
# licence declared as "License" or "licence" slip past the floor unexamined.
# Accept the spelling/casing variants, and treat any OTHER licence-shaped key
# as invalid_row -- a caller who declares a licence must never have it ignored.
_LICENSE_KEY_ALIASES: dict[str, str] = {
    "license": "license",
    "licence": "license",
    "spdx_id": "spdx_id",
    "spdxid": "spdx_id",
    "spdx": "spdx_id",
    "license_id": "license_id",
    "licence_id": "license_id",
    "licenseid": "license_id",
    "licenceid": "license_id",
}
_LICENSE_KEY_SHAPED = re.compile(r"licen[sc]e|spdx")


def _normalise_field_key(key: str) -> str:
    """Fold casing and separators so 'SPDX-ID' and 'spdx_id' agree."""
    return re.sub(r"[^a-z0-9]+", "_", str.lower(str.strip(key))).strip("_")


def _unrecognised_license_keys(row: Mapping[str, Any]) -> list[str]:
    """Licence-shaped keys the collector would silently ignore (GATE-04)."""
    return sorted(
        key
        for key in row
        if isinstance(key, str)
        and _normalise_field_key(key) not in _LICENSE_KEY_ALIASES
        and _LICENSE_KEY_SHAPED.search(_normalise_field_key(key))
    )


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


def _license_values_of(row: Mapping[str, Any]) -> list[str]:
    """Collect every non-empty licence-bearing field present on ``row`` (BR-35)."""
    by_canonical: dict[str, list[str]] = {key: [] for key in _LICENSE_FIELD_KEYS}
    for key, raw in row.items():
        if not isinstance(key, str):
            continue
        canonical_key = _LICENSE_KEY_ALIASES.get(_normalise_field_key(key))
        if canonical_key is None:
            continue
        if raw is None or not isinstance(raw, str):
            continue
        tag = str.strip(raw)
        if tag:
            by_canonical[canonical_key].append(tag)

    values: list[str] = []
    seen: set[str] = set()
    # Emit in canonical field order; de-dupe exact strings only.
    for key in _LICENSE_FIELD_KEYS:
        for tag in by_canonical[key]:
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
    # GATE-04: a licence-shaped key we would not collect must fail closed, not
    # be ignored -- otherwise `License: AGPL-3.0` launders into a pass.
    unrecognised = _unrecognised_license_keys(row)
    if unrecognised:
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                f"provenance row declares licence under unrecognised key(s) "
                f"{unrecognised!r}; use one of {list(_LICENSE_FIELD_KEYS)!r}"
            ),
            category=category,
        )

    # Type-check every present licence key first, aliases included -- a
    # non-string under `License` must fail the same way as under `license`.
    for key in sorted(k for k in row if isinstance(k, str)):
        if _normalise_field_key(key) not in _LICENSE_KEY_ALIASES:
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
    # Unbound casefold: values may still be str subclasses (GATE-15).
    folded = {str.casefold(v) for v in values}
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
    return str.strip(raw)


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
    text = str.strip(raw_cat)
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
    """True for self-generated / operator-* *provenance* sources.

    Training-data provenance namespace only. Not the registration-exemption
    predicate — that is :func:`_is_operator_owned_lineage` (GATE-21).
    """
    return _normalize_token(source) in _POSITIVE_TRAINING_SOURCES


def _operator_owned_lineage_forms() -> frozenset[str]:
    """Canonical exact forms of :data:`OPERATOR_OWNED_LINEAGE` (GATE-24).

    Recomputed per call so a test may substitute the registry; the set is two
    entries wide and this runs once per row, not per image.
    """
    forms: set[str] = set()
    for key in OPERATOR_OWNED_LINEAGE:
        kc = canonical(key)
        if kc is None or not kc:
            continue
        forms.update(_expand_id_forms(kc, exact_only=True))
    return frozenset(forms)


def _is_operator_owned_lineage(derived: str) -> bool:
    """True when ``derived`` is exactly an :data:`OPERATOR_OWNED_LINEAGE` tag.

    Whole-token exact match after canonicalisation (GATE-21 / GATE-24). Fails
    closed for anything not listed. Does **not** accept a row-author naming
    convention (bare ``acx/`` prefix), a foreign org prefix
    (``evilcorp/acx_internal_projector``), or a variant suffix
    (``acx_internal_projector_r50``) -- the operator registers the exact
    lineage or the row does not clear registration.
    """
    if not derived or not str.strip(str(derived)):
        return False
    c = canonical(str(derived))
    if c is None or not c:
        return False
    return c in _operator_owned_lineage_forms()


def _is_positive_or_registered_source(source: str) -> bool:
    """Source is on the positive allowlist, model-ingest registry, or synthetic registry."""
    if not source or not str.strip(str(source)):
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
    """Return the MODEL_INGEST registry key for ``derived``, or None.

    Exact only (B4b / BR-52): the whole canonical form or a slash component
    must resolve to a registered key / alias. Progressive underscore-prefix
    laundering (``yunet_evil`` → ``yunet``) is intentionally absent.
    """
    if not derived or not str.strip(str(derived)):
        return None
    c = canonical(str(derived))
    if c is None or not c:
        return None

    candidates: list[str] = [c]
    if "/" in c:
        # First path component and each component (exact).
        candidates.append(c.split("/")[0])
        candidates.extend(p for p in c.split("/") if p)

    seen: set[str] = set()
    for cand in candidates:
        if not cand or cand in seen:
            continue
        seen.add(cand)
        resolved = _resolve_model_key(cand)
        if resolved in MODEL_INGEST_ENTRIES:
            return resolved
    return None


def _source_axis_taint(
    row_or_source: Mapping[str, Any] | str,
    *,
    category: PolicyCategory,
) -> LicenseAuditResult | None:
    """NC / research taint on the ``source`` axis, re-tagged for the calling door.

    Wraps :func:`audit_source` — the training-data reference implementation —
    so every row-shaped door enforces the same source rules, including its
    confusable fail-closed check. An absent or blank source is not an error
    here; doors that require a source enforce that themselves.
    """
    if isinstance(row_or_source, str):
        text = str.strip(row_or_source)
    else:
        raw = row_or_source.get("source")
        if not isinstance(raw, str):
            return None
        text = str.strip(raw)
    if not text:
        return None
    result = audit_source(text)
    if result.ok:
        return None
    return LicenseAuditResult(
        verdict=result.verdict,
        reason=result.reason,
        detail=result.detail,
        category=category,
    )


def _row_clearance_decision_token(row: Mapping[str, Any]) -> str | None:
    """Return the stripped synthetic-lineage ``clearance_decision`` from ``row``.

    Distinct from :func:`_row_photo_clearance_token` (occluder photo-release).
    One key must not carry both axes (BR-65 / NAME-03).
    """
    raw = row.get("clearance_decision")
    if not isinstance(raw, str):
        return None
    text = str.strip(raw)
    return text if text else None


def _row_photo_clearance_token(row: Mapping[str, Any]) -> str | None:
    """Return the stripped occluder ``photo_clearance`` from ``row``, or None."""
    raw = row.get("photo_clearance")
    if not isinstance(raw, str):
        return None
    text = str.strip(raw)
    return text if text else None


def _audit_clearance_decision(
    entry: SyntheticSourceEntry,
    *,
    row_clearance: str | None,
    category: PolicyCategory,
    source_label: str | None = None,
) -> LicenseAuditResult | None:
    """Compare row ``clearance_decision`` against a registry entry's token.

    Shared by :func:`audit_synthetic_source` and the content-triggered floor
    in :func:`_common_provenance_checks` (GATE-11 / PROV-04). Returns a FAIL
    when the entry requires a decision token that is missing or mismatched;
    ``None`` when no clearance is required or the token matches.
    """
    decision = entry.verification.clearance_decision
    if not decision:
        return None
    if row_clearance and str.strip(str(row_clearance)) == decision:
        return None
    label = source_label or entry.source_id
    return _fail(
        RejectionReason.PENDING_LEGAL_CLEARANCE,
        detail=(
            f"synthetic source {label!r} requires "
            f"clearance_decision={decision!r}; "
            f"got {row_clearance!r}"
        ),
        category=category,
    )


def _content_triggered_clearance_check(
    row: Mapping[str, Any],
    *,
    category: PolicyCategory,
) -> LicenseAuditResult | None:
    """Content-triggered synthetic-lineage clearance floor (GATE-11 / SECD-03).

    Fires only when the row names a ``source`` or ``derived_from_model`` whose
    synthetic-registry entry carries a non-empty ``clearance_decision``, and
    the row does not supply a matching ``clearance_decision`` field token.
    Rows with no such signal are unaffected — this is not an unconditional
    clearance demand.

    Runs on **every** door, including ``OCCLUDER_ASSET`` (BR-65 / WEB-33 /
    SECD-03). The occluder door ADDs a separate photo-release obligation on
    the independent ``photo_clearance`` field (``uncleared_occluder_asset``);
    that restriction is additive and must never waive this floor. The two
    axes use distinct keys so a generic photo token cannot satisfy synthetic
    lineage clearance and a lineage decision token cannot satisfy photo
    release (NAME-03).
    """
    row_clearance = _row_clearance_decision_token(row)
    # Walk source then derived_from_model; first mismatch wins (short-circuit).
    # Non-string values are rejected by the floor type check before this runs
    # (BR-68); blank strings are absence, not a synthetic signal.
    for key in ("source", "derived_from_model"):
        raw = row.get(key)
        if not isinstance(raw, str) or not str.strip(raw):
            continue
        token = str.strip(raw)
        resolved = _resolve_registry_head(token, SYNTHETIC_SOURCE_ENTRIES)
        if resolved is None:
            continue
        entry = SYNTHETIC_SOURCE_ENTRIES.get(resolved)
        if entry is None:
            continue
        mismatch = _audit_clearance_decision(
            entry,
            row_clearance=row_clearance,
            category=category,
            source_label=entry.source_id,
        )
        if mismatch is not None:
            return mismatch
    return None


def _floor_string_field(
    row: Mapping[str, Any],
    key: str,
    *,
    category: PolicyCategory,
) -> tuple[str | None, LicenseAuditResult | None]:
    """Floor-side optional string validation (BR-68 / SECD-05).

    Absent key → ``(None, None)``. Present non-string (including ``None``) →
    ``invalid_row``. The floor must never ``continue`` past a value it cannot
    validate — an unparseable field is a rejection, not an absence.
    """
    if key not in row:
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


def _floor_taint_and_clearance(
    row: Mapping[str, Any],
    *,
    category: PolicyCategory,
) -> LicenseAuditResult | None:
    """Taint + clearance + registration half of the complete-mediation floor.

    Precedence within this half (BR-64 / GATE-01 / GATE-11 / BR-66 / BR-68):

      1. ``derived_from_model`` type + taint (NC, research-corpus, invalid type)
      2. ``source`` type + axis taint (NC / research; SYNTHETIC_SOURCE exempt
         only for synthetic-registry heads so its door can report a more
         specific clearance reason, with a PASS backstop re-applying the taint
         — FIR-7-RV-11)
      3. content-triggered synthetic ``clearance_decision`` (GATE-11 / BR-65):
         fires on every door when source/derived resolves to a registry entry
         that carries a decision token

    Registration (BR-33 / BR-66) is a separate half — :func:`_floor_registration`
    — so the TOOLING door can order package denylist ahead of it (GATE-22 /
    BR-24) without a flag that drops an axis (BR-69).

    Callers that must interleave axes with their own gates (e.g. TOOLING
    package denylist before registration and row SPDX — BR-24 / GATE-05 /
    GATE-22) call this half, then their door gate, then
    :func:`_floor_registration` / :func:`_floor_licenses`. They never get a
    floor call that silently omits an axis (BR-69 / ARCH-13).
    """
    # Taint outranks licence: a row that is both NC-derived and badly licensed
    # must report the NC reason. Swapping the licence field would clear a
    # licence reason while the banned lineage survives, so reporting the
    # licence first understates the problem (BR-64 / GATE-01).
    if "derived_from_model" in row:
        raw, type_err = _floor_string_field(
            row, "derived_from_model", category=category
        )
        if type_err is not None:
            return type_err
        assert raw is not None  # key present and string
        derived_result = audit_derived_from_model(raw)
        if not derived_result.ok:
            # Preserve NC / research / invalid reasons; re-tag for the calling door.
            return LicenseAuditResult(
                verdict=derived_result.verdict,
                reason=derived_result.reason,
                detail=derived_result.detail,
                category=category,
            )

    # BR-68: non-string source fails closed on every door before any axis that
    # would otherwise skip it as "absence".
    if "source" in row:
        raw_src, src_type_err = _floor_string_field(
            row, "source", category=category
        )
        if src_type_err is not None:
            return src_type_err
        assert raw_src is not None

    # BR-53: the `source` axis is category-independent too -- model_ingest and
    # tooling accepted an NC/research source outright while training_data has
    # always rejected it. Registry membership stays a category-specific rule, so
    # doors that legitimately accept an unregistered source are unaffected (the
    # floor may only ADD).
    #
    # FIR-7-RV-11: SYNTHETIC_SOURCE is exempt *only* for tokens that resolve to
    # a synthetic-registry head, so that door can report a more specific
    # clearance reason. Research / NC sources that are not registry heads still
    # report their source-axis taint (research_only_source / nc_model_derived)
    # rather than the generic pending_legal_clearance unknown-head default.
    # The dispatcher re-applies this taint to any PASS from that door, so
    # exempting registry heads cannot widen a verdict.
    if category is PolicyCategory.SYNTHETIC_SOURCE:
        raw_for_taint = row.get("source") if "source" in row else None
        if isinstance(raw_for_taint, str) and str.strip(raw_for_taint):
            head = _resolve_registry_head(
                str.strip(raw_for_taint), SYNTHETIC_SOURCE_ENTRIES
            )
            if head is None:
                source_taint = _source_axis_taint(row, category=category)
                if source_taint is not None:
                    return source_taint
    else:
        source_taint = _source_axis_taint(row, category=category)
        if source_taint is not None:
            return source_taint

    # GATE-11 / BR-65: content-triggered synthetic-lineage clearance on every
    # door. Occluder photo-release is a separate additive axis on photo_clearance.
    clearance_hit = _content_triggered_clearance_check(row, category=category)
    if clearance_hit is not None:
        return clearance_hit

    return None


def _floor_registration(
    row: Mapping[str, Any],
    *,
    category: PolicyCategory,
) -> LicenseAuditResult | None:
    """Registration half of the complete-mediation floor (BR-33 / BR-66).

    Content-triggered on every door. Split from :func:`_floor_taint_and_clearance`
    so TOOLING can run the package denylist first (GATE-22 / BR-24) without a
    flag that drops this axis (BR-69 / ARCH-13).
    """
    derived_text = ""
    if "derived_from_model" in row:
        raw = row.get("derived_from_model")
        if isinstance(raw, str):
            derived_text = str.strip(raw)
    source_text = ""
    if "source" in row:
        raw_src = row.get("source")
        if isinstance(raw_src, str):
            source_text = str.strip(raw_src)
    return _audit_derived_registration(
        source=source_text,
        derived=derived_text,
        category=category,
    )


def _floor_licenses(
    row: Mapping[str, Any],
    *,
    category: PolicyCategory,
) -> LicenseAuditResult | None:
    """Licence half of the complete-mediation floor (present values only).

    Runs on every row-shaped door when composed via
    :func:`_common_provenance_checks`. Doors that require a licence field
    still enforce ``required=True`` later. TOOLING calls this half *after*
    its package denylist gate so a self-declared licence cannot launder a
    denylisted package (BR-24 / GATE-05).
    """
    license_result = _audit_row_licenses(row, category=category, required=False)
    if not license_result.ok:
        # GATE-08: re-tag licence failures with door context so a
        # present-but-invalid value caught here reads the same as a
        # missing field caught later by the door's required=True call.
        # INVALID_ROW is left unprefixed (matches the door branch).
        if (
            category is PolicyCategory.OCCLUDER_ASSET
            and license_result.reason is not RejectionReason.INVALID_ROW
        ):
            detail = license_result.detail
            prefix = "occluder asset: "
            if not detail.startswith(prefix):
                detail = f"{prefix}{detail}"
            return LicenseAuditResult(
                verdict=license_result.verdict,
                reason=license_result.reason,
                detail=detail,
                category=category,
            )
        return license_result
    return None


def _common_provenance_checks(
    row: Mapping[str, Any],
    *,
    category: PolicyCategory,
) -> LicenseAuditResult | None:
    """Category-independent floor shared by every row-shaped entry point (BR-26).

    Complete-mediation floor: category-specific doors may only ADD
    restrictions, never subtract (BR-53 / BR-69). There is no parameter that
    can disable an axis — the structure makes subtraction unrepresentable
    (ARCH-13). Callers that legitimately need the licence axis at a different
    point in their own precedence chain call :func:`_floor_taint_and_clearance`
    and :func:`_floor_licenses` explicitly; they never get a floor call that
    silently omits either half.

    Exactly one reason is reported per call (short-circuit). Precedence order
    when a row trips multiple axes:

      1. ``derived_from_model`` type + taint (NC, research-corpus, invalid type)
      2. ``source`` type + axis taint (NC / research; SYNTHETIC_SOURCE exempt
         only for synthetic-registry heads so its door can report a more
         specific clearance reason, with a PASS backstop re-applying the taint
         — FIR-7-RV-11)
      3. content-triggered synthetic ``clearance_decision`` on every door
         (GATE-11 / BR-65); occluder photo-release is a separate additive axis
      4. unregistered ``derived_from_model`` registration (BR-33 / BR-66)
      5. licence values (denylist + allowlist, present values only; doors that
         require a licence field still enforce ``required=True`` later)

    TOOLING does **not** use this composition: it interleaves the package
    denylist between clearance and registration (GATE-22 / BR-24).

    Returns a FAIL result when a floor rule fires; ``None`` means the caller
    may continue with category-specific gates.
    """
    taint = _floor_taint_and_clearance(row, category=category)
    if taint is not None:
        return taint
    unreg = _floor_registration(row, category=category)
    if unreg is not None:
        return unreg
    return _floor_licenses(row, category=category)


# ---------------------------------------------------------------------------
# Public audit functions
# ---------------------------------------------------------------------------


def _reject_non_string(
    value: Any,
    *,
    field: str,
    category: PolicyCategory | None = None,
) -> LicenseAuditResult | None:
    """Shared type contract for public scalar ``audit_*`` entry points (BR-46).

    ``None`` and ``str`` are not type errors — each door documents its own
    empty/missing handling. Every other type returns ``invalid_row`` with a
    detail that names the offending type, so callers never see a policy
    outcome (or an exception) for a programming error.
    """
    if value is None or isinstance(value, str):
        return None
    return _fail(
        RejectionReason.INVALID_ROW,
        detail=f"{field} must be a string, got {type(value).__name__}",
        category=category,
    )


def _package_denylist_hit(value: str) -> PackageDenylistEntry | None:
    """Exact PACKAGE_DENYLIST lookup on canonical form / slash components (BR-51)."""
    c = canonical(value)
    if c is None or not c:
        return None
    candidates = [c]
    if "/" in c:
        candidates.extend(p for p in c.split("/") if p)
    seen: set[str] = set()
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        resolved = _resolve_model_key(cand)
        deny = PACKAGE_DENYLIST.get(resolved) or PACKAGE_DENYLIST.get(cand)
        if deny is not None:
            return deny
    return None


def audit_derived_from_model(derived_from_model: str | None) -> LicenseAuditResult:
    """Audit a ``derived_from_model`` provenance tag (buffalo OUTPUT ban).

    Empty string is allowed (not every row is model-derived). Any match
    against the expanded NC id set FAILS with ``RejectionReason.NC_MODEL_DERIVED``.
    PACKAGE_DENYLIST hits (Ultralytics family) FAIL with their denylist reason
    (BR-51). Non-ASCII residue after :func:`canonical` FAILS ``invalid_row``
    (BR-21 fail-closed). Non-string inputs FAIL ``invalid_row`` (BR-46).
    """
    type_err = _reject_non_string(
        derived_from_model,
        field="derived_from_model",
        category=PolicyCategory.TRAINING_DATA,
    )
    if type_err is not None:
        return type_err
    if derived_from_model is None:
        return _pass(detail="no derived_from_model tag")
    if not str.strip(derived_from_model):
        return _pass(detail="no derived_from_model tag")

    text = str.strip(derived_from_model)
    c = canonical(text)
    if c is None:
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                f"derived_from_model={text!r} contains non-ASCII residue after "
                "NFKC/Cf normalisation; confusable scripts are fail-closed"
            ),
            category=PolicyCategory.TRAINING_DATA,
        )

    # NC ban first (reason precedence for InsightFace family).
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

    # BR-64: research-only corpus as derived_from_model taint (after NC so
    # InsightFace family keeps NC_MODEL_DERIVED precedence).
    if _looks_like_research_source(text):
        return _fail(
            RejectionReason.RESEARCH_ONLY_SOURCE,
            detail=(
                f"derived_from_model={text!r} is a research-only corpus; "
                "research-tainted lineage is banned for commercial use"
            ),
            category=PolicyCategory.TRAINING_DATA,
        )

    # BR-51: PACKAGE_DENYLIST (AGPL family etc.) on derived_from_model.
    # NC_MODEL_DERIVED package entries are enforced via NC_MODEL_IDS expansion
    # only — keeps M2 discrimination on the NC seed set single-sourced.
    deny = _package_denylist_hit(text)
    if deny is not None and deny.reason is RejectionReason.DENYLISTED_PACKAGE:
        return _fail(
            deny.reason,
            detail=(
                f"derived_from_model={text!r} hits PACKAGE_DENYLIST entry "
                f"{deny.package_id!r} ({deny.spdx_id}): {deny.notes}"
            ),
            category=PolicyCategory.TRAINING_DATA,
        )

    return _pass(
        detail=f"derived_from_model={text!r} is not on the NC pattern list",
        category=PolicyCategory.TRAINING_DATA,
    )


# SPDX expression joiners (GATE-10). Matched as whole tokens so licence ids
# that happen to contain those letters are not split.
_SPDX_EXPRESSION_JOINERS = re.compile(r"\s+(?:OR|AND|WITH)\s+", re.IGNORECASE)


def _spdx_expression_tokens(tag: str) -> list[str]:
    """Split a compound SPDX expression into licence-id tokens (GATE-10).

    Handles ``OR`` / ``AND`` / ``WITH``, strips parentheses, and drops a
    trailing ``+`` (SPDX "or later" shorthand) from each token. Does not
    attempt to evaluate the expression — callers check each token against
    the denylist fail-closed.
    """
    text = str.strip(tag).replace("(", " ").replace(")", " ")
    tokens: list[str] = []
    for part in _SPDX_EXPRESSION_JOINERS.split(text):
        tok = str.strip(part)
        if tok.endswith("+"):
            tok = tok[:-1].rstrip()
        if tok:
            tokens.append(tok)
    return tokens


def _denylist_reason_for_spdx_token(tag_cf: str) -> RejectionReason | None:
    """Return the denylist rejection reason for a casefolded SPDX token, or None."""
    if tag_cf not in DENYLISTED_SPDX_IDS_CF:
        return None
    if tag_cf in _RESEARCH_ONLY_LICENSE_CF:
        return RejectionReason.RESEARCH_ONLY_LICENSE
    return RejectionReason.DENYLISTED_LICENSE


def audit_spdx(spdx_id: str | None) -> LicenseAuditResult:
    """Audit a bare SPDX / license tag (case-insensitive).

    Non-string inputs FAIL ``invalid_row`` (BR-46). ``None`` / blank →
    ``missing_license_field``.

    Compound SPDX expressions (``OR`` / ``AND`` / ``WITH``, trailing ``+``,
    parentheses) are tokenised and each component is checked against the
    denylist **before** falling back to ``unknown_spdx`` (GATE-10). A single
    denylisted component fails the whole expression — allowlisted siblings
    cannot launder it. An all-allowlisted compound is **not** auto-passed
    (fail-closed; leave as ``unknown_spdx``).
    """
    type_err = _reject_non_string(spdx_id, field="license")
    if type_err is not None:
        return type_err
    if spdx_id is None or not str.strip(spdx_id):
        return _fail(
            RejectionReason.MISSING_LICENSE_FIELD,
            detail="license / spdx_id field is required",
        )
    # Unbound strip/casefold so str subclasses cannot launder (GATE-15).
    tag = str.strip(spdx_id)
    tag_cf = str.casefold(tag)

    denied = _denylist_reason_for_spdx_token(tag_cf)
    if denied is not None:
        return _fail(
            denied,
            detail=f"license {tag!r} is denylisted for commercial training use",
        )
    if tag_cf in ALLOWED_SPDX_IDS_CF:
        return _pass(detail=f"license {tag!r} is allowlisted")
    if tag_cf == "pending-legal-clearance":
        return _fail(
            RejectionReason.PENDING_LEGAL_CLEARANCE,
            detail="license is PENDING-LEGAL-CLEARANCE",
        )

    # GATE-10: compound / plus forms — denylist components before unknown_spdx.
    for tok in _spdx_expression_tokens(tag):
        tok_cf = str.casefold(tok)
        denied = _denylist_reason_for_spdx_token(tok_cf)
        if denied is not None:
            return _fail(
                denied,
                detail=(
                    f"license {tag!r} contains denylisted component {tok!r}; "
                    "fail-closed for commercial training use"
                ),
            )

    # operator-cleared is NOT an SPDX value and is never an unconditional pass.
    # All-allowlisted compounds also land here (not auto-passed — SECD-05).
    return _fail(
        RejectionReason.UNKNOWN_SPDX,
        detail=f"license {tag!r} is not on the allowlist",
    )


def audit_source(source: str | None) -> LicenseAuditResult:
    """Audit a training-data ``source`` field against NC models + research-only.

    NC model patterns/ids take precedence over research-only (BR-20): banned
    weights named as ``source`` fail with ``nc_model_derived`` just as they
    do in ``derived_from_model``. Does **not** inspect ``generator_lineage``.
    Non-string inputs FAIL ``invalid_row`` (BR-46). ``None`` / blank →
    ``unknown_source``.
    """
    type_err = _reject_non_string(
        source, field="source", category=PolicyCategory.TRAINING_DATA
    )
    if type_err is not None:
        return type_err
    if source is None or not str.strip(source):
        return _fail(
            RejectionReason.UNKNOWN_SOURCE,
            detail="source field is required for training-data rows",
            category=PolicyCategory.TRAINING_DATA,
        )
    text = str.strip(source)
    c = canonical(text)
    if c is None:
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
    Non-string inputs FAIL ``invalid_row`` (BR-46) — not a missing registry entry.
    """
    type_err = _reject_non_string(
        model_id, field="model_id", category=PolicyCategory.MODEL_INGEST
    )
    if type_err is not None:
        return type_err
    if model_id is None or not str.strip(model_id):
        return _fail(
            RejectionReason.MISSING_INGEST_ENTRY,
            detail="model_id is required for ingest",
            category=PolicyCategory.MODEL_INGEST,
        )
    resolved = _resolve_model_key(model_id)

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
    """Audit a TOOLING dependency (diagnostic; not training data).

    Non-string inputs FAIL ``invalid_row`` (BR-46) rather than raising.
    """
    type_err = _reject_non_string(
        package_name, field="package_name", category=PolicyCategory.TOOLING
    )
    if type_err is not None:
        return type_err
    if package_name is None or not str.strip(package_name):
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

    Required: allowlisted license, positive ``photo_clearance`` (photo-release
    axis), and a non-empty **registered** source. Unknown sources FAIL (not
    only research names). Synthetic-lineage clearance is a separate floor
    obligation on ``clearance_decision`` (BR-65); this door ADDs photo-release
    and never waives the floor.

    Unconditional NC provenance (``derived_from_model``) is applied via
    :func:`_common_provenance_checks` before category-specific gates (BR-26).
    """
    if not isinstance(asset, Mapping):
        return _fail(
            RejectionReason.INVALID_ROW,
            detail="occluder asset must be a mapping with license fields",
            category=PolicyCategory.OCCLUDER_ASSET,
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

    # BR-65: photo-release axis is independent of synthetic-lineage
    # clearance_decision. Single key ``photo_clearance`` only — no dual-shape
    # clearance / clearance_status overload (greenfield / NAME-03).
    if "photo_clearance" in asset:
        photo_raw = asset["photo_clearance"]
        if photo_raw is not None and not isinstance(photo_raw, str):
            return _fail(
                RejectionReason.INVALID_ROW,
                detail=(
                    "occluder asset photo_clearance must be a string, "
                    f"got {type(photo_raw).__name__}"
                ),
                category=cat,
            )
    else:
        photo_raw = None
    photo_token = _row_photo_clearance_token(asset)
    photo = _normalize_token(photo_token) if photo_token else ""
    if photo not in OCCLUDER_ALLOWED_CLEARANCES:
        return _fail(
            RejectionReason.UNCLEARED_OCCLUDER_ASSET,
            detail=(
                f"occluder asset source photo is uncleared "
                f"(photo_clearance={photo_raw!r}); pack-build refused"
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
    supply a matching ``row_clearance`` value drawn from the row's
    ``clearance_decision`` field (PROV-04 / BR-65) — not from photo-release
    vocabulary.

    Registry head resolution is exact against the import-time expanded
    synthetic id set (BR-36 / BR-50): ``dcface_v2``, ``dcface/v2``, and
    ``myorg/dcface`` resolve to the ``dcface`` clearance entry; ``dcface_evil``
    and ``not_dcface`` do not inherit clearance.

    Non-string inputs FAIL ``invalid_row`` (BR-46) — not a clearance outcome.
    """
    type_err = _reject_non_string(
        source_id, field="source_id", category=PolicyCategory.SYNTHETIC_SOURCE
    )
    if type_err is not None:
        return type_err
    if source_id is None or not str.strip(source_id):
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
    # PROV-04 / GATE-11: shared clearance comparison with the floor helper.
    clearance_fail = _audit_clearance_decision(
        entry,
        row_clearance=row_clearance,
        category=PolicyCategory.SYNTHETIC_SOURCE,
    )
    if clearance_fail is not None:
        return clearance_fail
    return _pass(
        detail=(
            f"synthetic source {entry.source_id!r} commercial-allowed "
            f"(clearance_decision="
            f"{entry.verification.clearance_decision or 'n/a'})"
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
        (exact expanded-id resolve — BR-36 / BR-50), including the
        no-lineage path so clearance cannot be skipped by omitting lineage.

    Unregistered ``derived_from_model`` values that are **not** synthetic-registry
    heads are NOT routed here — they use ``UNREGISTERED_DERIVED_MODEL`` (or pass
    for operator-owned sources) instead of the synthetic clearance gate (BR-33).
    """
    targets: list[str] = []
    seen: set[str] = set()

    def _add(token: str) -> None:
        t = str.strip(token)
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
    """BR-33 / BR-66 / GATE-21 / GATE-23: unregistered derived registration.

    Returns a FAIL when ``derived`` is non-empty, not NC (already checked),
    not a registered model-ingest head, not an ALLOWED synthetic-registry
    head, and not in :data:`OPERATOR_OWNED_LINEAGE`.

    Exemption is keyed off the **lineage value** (operator-controlled registry),
    never off the door-dependent ``source`` field (GATE-21 / NAME-03). The
    ``source`` parameter is retained for call-site compatibility but is not
    consulted.

    Synthetic-registry heads are re-checked for ``commercial_use`` on every
    door (GATE-23): a FORBIDDEN / non-ALLOWED entry is not exempted merely
    because ``_synthetic_audit_targets`` would handle it on TRAINING_DATA.
    Returns ``None`` when no dedicated derived gate fires.
    """
    del source  # GATE-21: provenance namespace must not exempt registration.
    if not derived:
        return None
    # Registered commercial ingest head → fine.
    if _derived_ingest_key(derived) is not None:
        return None
    # Synthetic registry head — re-check commercial_use on every door (GATE-23).
    # Previously exempted unconditionally with "handled by _synthetic_audit_targets",
    # but that helper only runs on the TRAINING_DATA path; TOOLING / MODEL_INGEST
    # would silently PASS a FORBIDDEN synthetic not mirrored into NC_MODEL_IDS.
    resolved_synth = _resolve_registry_head(derived, SYNTHETIC_SOURCE_ENTRIES)
    if resolved_synth is not None:
        entry = SYNTHETIC_SOURCE_ENTRIES.get(resolved_synth)
        if entry is not None and entry.verification.commercial_use is CommercialUse.ALLOWED:
            return None
        label = entry.source_id if entry is not None else derived
        use = (
            entry.verification.commercial_use.value
            if entry is not None
            else "unknown"
        )
        spdx = (
            entry.verification.spdx_id
            if entry is not None
            else "PENDING-LEGAL-CLEARANCE"
        )
        return _fail(
            RejectionReason.PENDING_LEGAL_CLEARANCE,
            detail=(
                f"synthetic source {label!r} is {spdx} / {use}"
            ),
            category=category,
        )
    # GATE-21: operator-owned LINEAGE registry (not source provenance namespace).
    if _is_operator_owned_lineage(derived):
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

    **Exactly one reason is reported per call** (short-circuit evaluation). A
    multi-fault row surfaces only the highest-precedence axis that fires —
    operators must not read a single reason as "the only fault" (GATE-09 /
    CLM-03). Floor precedence is documented on
    :func:`_common_provenance_checks`; door-specific gates run only after the
    floor returns ``None``.

    Checks on the training-data path, in order:
      0. structural field validation (types + required keys)
      1. shared floor via :func:`_common_provenance_checks`:
         derived type/taint → source type/taint → content-triggered
         clearance_decision (GATE-11 / BR-65) → unregistered derived
         registration (BR-66) → present licence values
      2. ``source`` against research-only / NC (NOT ``generator_lineage``)
         — redundant with floor source taint for non-empty sources; still
         enforces required-source
      3. every licence-bearing field with ``required=True`` (BR-35)
      4. fail-closed unknown source → PENDING-LEGAL-CLEARANCE (BR-22 / SECD-05)
      5. synthetic-source clearance for registry heads only (BR-33) — backstop
         for heads already covered by the floor clearance axis

    ``generator_lineage`` is informational and never causes research-source
    rejection by itself. Unregistered ``derived_from_model`` is mediated on
    the floor (BR-66), not as a training-data-only trailing gate.
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
            if isinstance(raw, str) and str.strip(raw):
                model_id = str.strip(raw)
                break
        common = _common_provenance_checks(row, category=PolicyCategory.MODEL_INGEST)
        if common is not None:
            return common
        return audit_model_ingest(model_id)

    if audit_category is PolicyCategory.SYNTHETIC_SOURCE:
        # Floor first (BR-68): non-string source/derived must fail invalid_row
        # before this door treats a non-string as a missing source.
        common = _common_provenance_checks(row, category=PolicyCategory.SYNTHETIC_SOURCE)
        if common is not None:
            return common
        source_raw = row.get("source")
        if not isinstance(source_raw, str) or not str.strip(source_raw):
            return _fail(
                RejectionReason.UNKNOWN_SOURCE,
                detail="synthetic_source category requires a non-empty source field",
                category=PolicyCategory.SYNTHETIC_SOURCE,
            )
        row_clearance = _row_clearance_decision_token(row)
        synth = audit_synthetic_source(
            str.strip(source_raw), row_clearance=row_clearance
        )
        if synth.ok:
            # The floor skipped the source taint so this door could report its
            # more specific reason. Re-apply it to any PASS so the exemption can
            # never widen a verdict, even if a future registry entry is both
            # commercially ALLOWED and NC by pattern (SECD-05 fail closed).
            backstop = _source_axis_taint(
                str.strip(source_raw), category=PolicyCategory.SYNTHETIC_SOURCE
            )
            if backstop is not None:
                return backstop
        return synth

    # ------------------------------------------------------------------
    # TRAINING_DATA path (default)
    # ------------------------------------------------------------------

    # Structural validation — require derived_from_model KEY ('' is valid opt-out).
    _derived_val, derived_err = _require_string_field(
        row, "derived_from_model", required=True, category=audit_category
    )
    if derived_err is not None:
        return derived_err

    for key in ("source", "clearance_decision", "photo_clearance", "generator_lineage"):
        _val, field_err = _require_string_field(
            row, key, required=False, category=audit_category
        )
        if field_err is not None:
            return field_err
        del _val

    # Licence keys type-checked inside _audit_row_licenses.

    # BR-26: shared unconditional NC (and type) checks. Registration and
    # content-triggered clearance live on the floor (BR-65 / BR-66).
    common = _common_provenance_checks(row, category=audit_category)
    if common is not None:
        return common

    derived = (
        str.strip(_derived_val) if _derived_val is not None else ""
    )

    source = ""
    if "source" in row and isinstance(row["source"], str):
        source = str.strip(row["source"])

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
    #
    # BR-74 / GATE-11: when the floor's content-triggered clearance axis also
    # fires (synthetic-registry source/derived without a matching
    # clearance_decision token), that reason is reported *before* this licence
    # check — the floor short-circuits. BR-25's "licence before allowlist"
    # ordering still holds among the *door-local* gates below; it does not
    # outrank the floor's clearance / registration axes.
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

    lineage_raw = row.get("generator_lineage")
    has_lineage = bool(
        str.strip(lineage_raw) if isinstance(lineage_raw, str) else False
    )
    # BR-34: only the *caller-supplied* category participates in synthetic
    # routing — never the row-declared value.
    row_clearance = _row_clearance_decision_token(row)

    for cand in _synthetic_audit_targets(
        source=source,
        derived=derived,
        category=audit_category,
        has_generator_lineage=has_lineage,
    ):
        synth_result = audit_synthetic_source(cand, row_clearance=row_clearance)
        if not synth_result.ok:
            # GATE-27 / rg-015: the synthetic backstop decides verdict/reason/
            # detail, but the returned category must remain the door the
            # *caller* asked for — never the helper's own SYNTHETIC_SOURCE stamp.
            return LicenseAuditResult(
                verdict=synth_result.verdict,
                reason=synth_result.reason,
                detail=synth_result.detail,
                category=audit_category,
            )

    # Unregistered derived is floor-mediated (BR-66); no door-local re-check.

    return _pass(
        detail="provenance row passes license policy",
        category=audit_category,
    )


def audit_tooling_row(row: Mapping[str, Any]) -> LicenseAuditResult:
    """Audit a tooling dependency row (caller-owned TOOLING category).

    Ordering (BR-24 / GATE-05 / GATE-22) — package denylist cannot be masked
    by a row-author-controlled self-declaration on any axis:

      1. Floor taint + content-triggered clearance via
         :func:`_floor_taint_and_clearance` (``derived_from_model`` NC/research
         taint, ``source`` taint, synthetic clearance). Registration and
         licence halves are deferred so neither can mask the package reason.
      2. Resolve a package identifier from ``package`` / ``package_name`` /
         ``source`` and run :func:`audit_tooling_dependency` **before**
         registration and any row-declared SPDX check so a self-declared
         licence **or** a junk ``derived_from_model`` tag cannot launder a
         denylisted package (BR-24 / GATE-22).
      3. Unregistered ``derived_from_model`` registration via
         :func:`_floor_registration` (BR-66 / GATE-21).
      4. Present row-declared licence values via :func:`_floor_licenses`
         (required=False) — still enforced, just after the package gate.

    Missing package identifier fails closed. The complete floor composition
    :func:`_common_provenance_checks` is not used here because registration
    and licence halves must interleave *after* the package gate; every half
    still runs (BR-69 / ARCH-13).
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

    # Taint + clearance only — registration and licence deferred until after
    # the package gate so denylisted_package is the authoritative reason when
    # package + registration (or package + licence) both fire (BR-24 / GATE-22).
    # BR-69: call each half explicitly; never a flag that drops an axis.
    common = _floor_taint_and_clearance(row, category=cat)
    if common is not None:
        return common

    package = ""
    for key in ("package", "package_name", "source"):
        raw = row.get(key)
        if isinstance(raw, str) and str.strip(raw):
            package = str.strip(raw)
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

    # Authoritative package gate — denylist / allowlist pin wins over both
    # registration (GATE-22) and row SPDX (GATE-05 / BR-24).
    dep_result = audit_tooling_dependency(package)
    if not dep_result.ok:
        return dep_result

    # Registration after package so a junk lineage tag cannot mask AGPL
    # (GATE-22). Same predicate as the complete floor's registration axis.
    unreg = _floor_registration(row, category=cat)
    if unreg is not None:
        return unreg

    # Row-declared licence still fails closed when present, but only after the
    # package reason has had its chance to surface (GATE-05). Same half as the
    # complete floor's licence axis (BR-69).
    license_hit = _floor_licenses(row, category=cat)
    if license_hit is not None:
        return license_hit

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
