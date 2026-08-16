"""Golden-manifest schema + fail-fast loader (rg-008).

The manifest (`scene/tests/seed/golden.json`) is the single source of truth for
the eval corpus: per-image relative path, content sha256, stable synthetic
``media_id`` (the analyze contract keys uploads as ``image_<media_id>`` parts
and identity reads group by ``media_id``), ground-truth ``face_count`` (see
contract below), present-identity labels, context-pack fixture,
Must-Right/Easy-Wrong rubric entries, policy flags, ``annotation_mode``, and
per-box ``LabelLineage``.

Image bytes are NOT vendored in git; ``images_dir`` (usually ``$GOLDEN_IMAGES_DIR``)
points at the rsync-bootstrapped local copy and is verified hash-by-hash.

Every field is strictly typed under ``extra='forbid'`` and validated at load
time: ``policy.recognition_enabled`` is required (a typo can no longer silently
enable recognition), ``annotation_mode`` is required, every box carries
``LabelLineage``, the coverage invariant compares independently recorded
``face_count`` against ``len(face_boxes)``, paths and media_ids must be unique,
the corpus may not be empty, and the manifest version must be one this loader
understands (rg-008 fail-fast).

``face_count`` contract
-----------------------
``face_count`` is the number of **human faces visible in the frame**, including
non-roster strangers, background faces, and faces too small or occluded to
identify. It is **not** "faces the detector found" and **not** "roster members
present".

The operator records ``face_count`` as a **separate count-first step before any
box is drawn**. It is **never** derived from ``len(face_boxes)`` — a derived
count makes the coverage invariant unfalsifiable (GF-11). The invariant then
compares two independently produced numbers:

- ``exhaustive``: ``len(face_boxes) == face_count``
- ``roster_only``: ``len(face_boxes) <= face_count``
- both modes: ``face_count >= len(present_identities)`` — an identity
  claim that exceeds the independently recorded face count is unbacked
  and cannot be scored as identification ground truth

Declared limitation (GF-12): equality proves internal consistency only (the
operator's count matches the operator's own boxes). Exhaustiveness *in the
world* is Slice 3's independent exhaustiveness audit [AUDIT-04], never this
invariant.

``load_manifest`` is the v3 gate loader. Frozen v2 artifacts (golden150-draft,
Slice 5 bias-audit arms, Slice 3 audit-queue draw) go through
``load_legacy_manifest`` only — never a ``cli.py`` gate command.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
import warnings
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

SUPPORTED_MANIFEST_VERSION = 3
LEGACY_MANIFEST_VERSION = 2

# Documented defaults for v2→v3 box migration (rg-015). Applied only by the
# Slice 2 retag/migration of pre-v3 boxes; the loader never invents these.
LEGACY_IMPORT_LABELER_ID = "legacy-import"
LEGACY_IMPORT_BATCH_ID = "fir-11-slice-2-v3-migration"
LEGACY_IMPORT_LABELED_AT = "1970-01-01T00:00:00Z"  # unknown; epoch sentinel
LEGACY_IMPORT_TOOL_VERSION = "legacy-import"
# Fail-closed: assume proposals were visible unless the record says otherwise.
LEGACY_IMPORT_SAW_MACHINE_PROPOSALS = True
# Unknown occasion — pre-v3 boxes have no recoverable capture session.
# This token means "there is no occasion key". It must not satisfy the
# exhaustive capture-session gate (S2R6-01); roster_only may still carry it.
LEGACY_IMPORT_CAPTURE_SESSION_ID = "legacy-import-unknown-session"

# Recorded decision (S2R4-20): persisted annotation_mode is document-level.
# S2R3-10 closed by extra=forbid + a comment left the mixed-stamp lattice
# unreachable from any on-disk file and unrecorded outside those remarks.
# The loader now refuses a per-entry stamp under this named invariant.
ANNOTATION_MODE_DOCUMENT_LEVEL_INVARIANT = "annotation_mode_is_document_level"

# Stratification / metric-backing fields inventoried for MEAS-09 / EVAL-04.
# A metric whose backing field is 0/N corpus-wide must refuse certification
# rather than return a vacuous single-bucket pass (VLM6-R2-03).
STRATIFICATION_INVENTORY_FIELDS: tuple[str, ...] = (
    "difficulty",
    "domain",
    "tags",
    "reference_facts",
    "spatial_facts",
    "face_boxes",
    "provenance",
    "must_right",
    "easy_wrong",
    "demographic_cohort",
)

# Honest coverage gaps on the shipped golden-37 corpus: fields that cannot be
# populated without viewing image bytes or operator-authored geometry. Each
# value names the owner and the concrete next action (OBS-04). Do not invent
# ground truth to silence these gaps (VLM6-R2-03).
SHIPPED_CORPUS_COVERAGE_GAPS: dict[str, str] = {
    "reference_facts": (
        "owner=VLM-6-operator; action=author polarity-tagged reference_facts per image "
        "after a visual pass — cannot be derived from filename/face_count alone"
    ),
    "spatial_facts": (
        "owner=VLM-6-operator; action=author spatial relations from curated boxes — "
        "no box geometry is vendored for the full corpus"
    ),
    "face_boxes": (
        "owner=FIR-1/VLM-6-operator; action=author FaceBox x/y/w/h per face — "
        "phrase_boxes.json has centers only for 6 scenes and is not a substitute"
    ),
    "demographic_cohort": (
        "owner=FIR-5; action=label roster_cohorts / demographic_cohort after "
        "operator cohort definitions land — no labelled source exists yet"
    ),
}


# --- Golden-100 stratification vocabulary (VLM-6 S1) -------------------------
# Centralized enums (sr-007) so difficulty/domain/fact-kind/relation are never
# scattered magic strings. All Golden-100 additions are ADDITIVE and optional —
# the legacy golden-38 entries omit them and still validate under extra='forbid'.


class Difficulty(StrEnum):
    """Coarse per-image difficulty tier used for stratified reporting."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Domain(StrEnum):
    """Stratum an image belongs to. Every stratum gets >=5 images (plan S1)."""

    PEOPLE = "people"
    FACES = "faces"
    CROWDS = "crowds"
    OCCLUSION = "occlusion"
    MIRRORS = "mirrors"
    ANIMALS = "animals"
    ART = "art"
    ABSTRACT = "abstract"
    BLACK_AND_WHITE = "black_and_white"
    DENSE_SCENE = "dense_scene"
    TEXT_IN_IMAGE = "text_in_image"
    CHARTS = "charts"
    PRODUCTS = "products"
    LOW_LIGHT = "low_light"


class FactKind(StrEnum):
    """What a reference fact asserts, so the hallucination scorer can bucket."""

    OBJECT = "object"
    ATTRIBUTE = "attribute"
    COUNT = "count"
    RELATION = "relation"
    SCENE = "scene"
    TEXT = "text"


class FactPolarity(StrEnum):
    """Whether a reference fact is TRUE of the image or a fabrication trap.

    ``true`` facts are the ground truth a faithful caption may state (coverage);
    ``false`` facts are things that are NOT true of the image — a caption that
    asserts one has fabricated (the hallucination signal). Deterministic scoring
    matches ``phrases`` with word-boundary anchoring (see caption_metrics).
    """

    TRUE = "true"
    FALSE = "false"


class SpatialRelation(StrEnum):
    """Relative placement relations derived from curated face/object boxes."""

    LEFT_OF = "left_of"
    RIGHT_OF = "right_of"
    BETWEEN = "between"
    ABOVE = "above"
    BELOW = "below"
    FOREGROUND = "foreground"
    BACKGROUND = "background"


class LicenseTag(StrEnum):
    """Provenance license classes accepted into the corpus (PII/license screen)."""

    CC0 = "cc0"
    PUBLIC_DOMAIN = "public_domain"
    MOCK_ENTITY = "mock_entity"  # consented/synthetic roster material
    CONSENTED = "consented"  # operator's own / explicitly consented
    FIXTURE = "fixture"  # pre-existing vendored fixture pool
    # Recorded on three corpus646 unlabeled slugs (no attestable subject).
    # Not a new status invented here — the value is already in the file.
    # Fail-closed for publishability (not CC0 / public_domain).
    UNASSIGNED = "unassigned"


class ProvenanceSource(StrEnum):
    """Canonical corpus-source vocabulary (sr-007). One definition shared by the
    manifest, the strata shortlister, and the identity bridge so a source label can
    never mean three different things across modules (the celeb->stranger identity
    loss that a scattered string set caused).

    CELEB/WIKIMEDIA/OPENVERSE are public-eligible; LOCALWP/OPERATOR are PRIVATE
    (real personal photos, never published — see ``Provenance.is_publishable`` and
    ``PRIVATE_SOURCES``); FIXTURE is vendored test material.
    """

    CELEB = "celeb"
    WIKIMEDIA = "wikimedia"
    OPENVERSE = "openverse"
    LOCALWP = "localwp"
    OPERATOR = "operator"
    FIXTURE = "fixture"


class SliceTag(StrEnum):
    """Image-slice strata for face bake-off rollups (FIR-5).

    Seven values only — the SC3 slice list. ``unknown`` is structural via
    face_boxes name=None; ``demographic`` is a person cohort (roster_cohorts /
    demographic_cohort), not an image tag (rg-009).
    """

    MASKED = "masked"
    SUNGLASSES = "sunglasses"
    OCCLUSION_OTHER = "occlusion_other"
    PROFILE = "profile"
    LOW_RES = "low_res"
    BLUR = "blur"
    SIMILAR_PEOPLE = "similar_people"


class AnnotationMode(StrEnum):
    """Manifest-level declaration of what the boxes cover.

    ``exhaustive``: every human face in the frame is boxed (named or null).
    ``roster_only``: only roster members are boxed. Detection scoring is
    structurally barred against ``roster_only`` — unlabeled non-roster faces
    would be scored as false positives.
    """

    EXHAUSTIVE = "exhaustive"
    ROSTER_ONLY = "roster_only"


class ScoreInvariant(StrEnum):
    """Canonical names for score-time refusals. Import this; do not re-spell."""

    DETECTION_REQUIRES_ANNOTATION_MODE = "detection_requires_annotation_mode"
    DETECTION_REFUSES_ROSTER_ONLY = "detection_refuses_roster_only"
    DETECTION_UNRECOGNISED_ANNOTATION_MODE = "detection_unrecognised_annotation_mode"
    DETECTION_REFUSES_EMPTY_ENTRIES = "detection_refuses_empty_entries"
    DETECTION_REFUSES_MIXED_ANNOTATION_MODE = "detection_refuses_mixed_annotation_mode"
    IDENTIFICATION_REFUSES_UNBOXED_IDENTITY_CLAIMS = (
        "identification_refuses_unboxed_identity_claims"
    )
    DETECTION_REFUSES_UNCOVERED_FACE_COUNT = "detection_refuses_uncovered_face_count"
    DETECTION_REFUSES_EMPTY_OBSERVATIONS = "detection_refuses_empty_observations"
    IDENTIFICATION_REFUSES_EMPTY_OBSERVATIONS = "identification_refuses_empty_observations"


# Published markdown explanation per fired invariant (S2R5-04). A refusal
# reason that names a condition that did not fire is worse than no reason.
REFUSAL_EXPLANATIONS: dict[ScoreInvariant, str] = {
    ScoreInvariant.DETECTION_REQUIRES_ANNOTATION_MODE: (
        "detection P/R is not computed without a resolved annotation_mode; "
        "omission is not exhaustive"
    ),
    ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY: (
        "detection P/R is not computed unless annotation_mode is exhaustive"
    ),
    ScoreInvariant.DETECTION_UNRECOGNISED_ANNOTATION_MODE: (
        "detection P/R is not computed from an unrecognised annotation_mode token"
    ),
    ScoreInvariant.DETECTION_REFUSES_EMPTY_ENTRIES: (
        "detection P/R is not computed from zero score entries; "
        "an empty entry list cannot witness a detection contract"
    ),
    ScoreInvariant.DETECTION_REFUSES_MIXED_ANNOTATION_MODE: (
        "detection P/R is not computed from mixed annotation_mode stamps; "
        "the scorer will not guess which detection contract applies"
    ),
    ScoreInvariant.IDENTIFICATION_REFUSES_UNBOXED_IDENTITY_CLAIMS: (
        "identification P/R is not computed from identity claims that carry no "
        "per-face box lineage"
    ),
    ScoreInvariant.DETECTION_REFUSES_UNCOVERED_FACE_COUNT: (
        "detection P/R is not computed from an exhaustive stamp whose boxes "
        "do not cover face_count"
    ),
    ScoreInvariant.DETECTION_REFUSES_EMPTY_OBSERVATIONS: (
        "detection P/R is not computed from zero scored observations"
    ),
    ScoreInvariant.IDENTIFICATION_REFUSES_EMPTY_OBSERVATIONS: (
        "identification P/R is not computed from zero scored observations"
    ),
}
if frozenset(REFUSAL_EXPLANATIONS) != frozenset(ScoreInvariant):
    raise RuntimeError(
        "REFUSAL_EXPLANATIONS keys drifted from ScoreInvariant: "
        f"table={sorted(member.value for member in REFUSAL_EXPLANATIONS)} "
        f"enum={sorted(member.value for member in ScoreInvariant)}"
    )


def refusal_explanation(invariant: object) -> str:
    """Return the published sentence for the invariant that actually fired.

    Unknown tokens raise. Never substitute a neighbouring metric's reason.
    """
    if isinstance(invariant, ScoreInvariant):
        member = invariant
    else:
        try:
            member = ScoreInvariant(invariant)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise ManifestError(
                f"no refusal explanation for invariant {invariant!r}"
            ) from None
    text = REFUSAL_EXPLANATIONS.get(member)
    if text is None:
        raise ManifestError(f"no refusal explanation for invariant {member!r}")
    return text


def parse_annotation_mode(value: object) -> AnnotationMode | None:
    """Return the enum member, or None when the value is omitted.

    Empty / whitespace-only strings are omitted. Unknown tokens (including
    wrong case) raise ManifestError with invariant
    ``detection_unrecognised_annotation_mode``. Never invents exhaustive.
    """
    if value is None:
        return None
    if isinstance(value, AnnotationMode):
        return value
    if isinstance(value, str):
        token = value.strip()
        if not token:
            return None
        try:
            return AnnotationMode(token)
        except ValueError:
            raise ManifestError(
                f"unrecognised annotation_mode {value!r}; "
                f"expected one of {[member.value for member in AnnotationMode]}",
                invariant=ScoreInvariant.DETECTION_UNRECOGNISED_ANNOTATION_MODE,
            ) from None
    raise ManifestError(
        f"unrecognised annotation_mode {value!r}; "
        f"expected one of {[member.value for member in AnnotationMode]}",
        invariant=ScoreInvariant.DETECTION_UNRECOGNISED_ANNOTATION_MODE,
    )


class LabelSource(StrEnum):
    """How the label was produced (GF-13). ``saw_machine_proposals`` is a flag,
    not a source — a blind pass and a re-pass that both saw proposals are
    still distinct sources.
    """

    OPERATOR_BLIND = "operator_blind"
    OPERATOR_REPASS = "operator_repass"
    ARBITRATION = "arbitration"
    GOLD_REFERENCE = "gold_reference"
    LEGACY_IMPORT = "legacy_import"


class LabelDecision(StrEnum):
    """What the labeler decided about the face. ``inconclusive`` is a decision,
    not a confidence — the face is present but identity cannot be determined.
    """

    NAMED = "named"
    STRANGER = "stranger"
    INCONCLUSIVE = "inconclusive"


class LabelConfidence(StrEnum):
    """Graded confidence (GF-13). Distinct from ``LabelDecision``."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Private roots are LOCAL-ONLY: a personal photo is never publishable regardless of
# license or an explicit flag (fail-closed on the "never publish uploads" invariant).
PRIVATE_SOURCES: frozenset[ProvenanceSource] = frozenset({ProvenanceSource.LOCALWP, ProvenanceSource.OPERATOR})


class ManifestError(Exception):
    """Structural, hash, or label problem in the golden manifest. Fail fast.

    Coverage / mode / lineage failures carry a named ``invariant``, the
    ``entry_index``, and the ``entry_path`` so callers get an error taxonomy
    rather than a boolean (GF-21).
    """

    def __init__(
        self,
        message: str,
        *,
        invariant: str | None = None,
        entry_index: int | None = None,
        entry_path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.invariant = invariant
        self.entry_index = entry_index
        self.entry_path = entry_path


class RubricEmptyWarning(UserWarning):
    """The corpus defines no Must-Right/Easy-Wrong rubric entries (gate vacuous)."""


@dataclass(frozen=True)
class FieldPopulation:
    """Per-field population count for a loaded corpus (VLM6-R2-03 inventory)."""

    field: str
    populated: int
    total: int

    @property
    def empty(self) -> int:
        return self.total - self.populated

    @property
    def is_vacuous(self) -> bool:
        """True when zero entries populate the field (metric would be single-bucket)."""
        return self.total > 0 and self.populated == 0


class ContextPack(BaseModel):
    """WP context echoed to the describe route (title/caption/description).

    ``extra='allow'`` — WP context is intentionally extensible — but the known
    fields are type-checked so a mistyped title/caption fails fast.
    """

    model_config = ConfigDict(extra="allow")

    title: str | None = None
    caption: str | None = None
    description: str | None = None


class EntryPolicy(BaseModel):
    """Per-image recognition policy.

    ``recognition_enabled`` is REQUIRED so a missing or mistyped key fails at
    load time instead of silently defaulting to recognition-enabled (rg-008).
    """

    model_config = ConfigDict(extra="forbid")

    recognition_enabled: bool


class ExpectedAttachment(BaseModel):
    """Ground-truth attachment altitude for a supplied ContextPack fact (E20-FUSION).

    Mirrors Stage-2 ``Attachment`` decision fields so mis-attachment scoring
    compares runner provenance against real producer shapes (not invented enums).
    """

    model_config = ConfigDict(extra="forbid")

    fact_source: str
    fact_label: str
    decision: str  # object | caption | dropped
    altitude: str  # object | caption | none
    visible: bool = False
    review_reason: str | None = None
    fact_id: str | None = None


class ReferenceFact(BaseModel):
    """A ground-truth fact about an image (VLM-6 S1).

    ``polarity=true`` facts are things a faithful caption may state; ``false``
    facts are fabrication traps (untrue of the image). ``phrases`` are the
    deterministic word-boundary match variants the hallucination scorer checks.
    ``confirmed_by`` records whether an operator or the agent draft confirmed it.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    kind: FactKind
    polarity: FactPolarity = FactPolarity.TRUE
    phrases: list[str] = Field(default_factory=list)
    confirmed_by: str | None = None  # operator | agent

    @model_validator(mode="after")
    def _has_a_matchable_phrase(self) -> ReferenceFact:
        # A fact must expose at least one non-blank match target so scoring is never
        # silently vacuous (rg-008): whitespace-only phrases do not count — match_targets
        # would filter them to [""] and match nothing.
        if not any(p.strip() for p in self.phrases) and not self.text.strip():
            raise ValueError("reference_fact needs non-empty text or at least one non-blank phrase")
        return self

    def match_targets(self) -> list[str]:
        """Non-empty phrases to match, defaulting to the fact text."""
        targets = [p for p in self.phrases if p.strip()]
        return targets or [self.text]


class Provenance(BaseModel):
    """Per-image sourcing + license record (PII/license screen, plan S1).

    ``publishable`` gates the S5 gallery split: public figures + CC0/public-domain
    are publishable to the research hub; private personal images (real contacts)
    are LOCAL-ONLY and excluded from any rd-published artifact. It defaults to a
    conservative value derived from the license so a missing flag never leaks a
    private image (see ``is_publishable``).
    """

    model_config = ConfigDict(extra="forbid")

    source: ProvenanceSource
    license: LicenseTag
    url: str | None = None
    note: str | None = None
    publishable: bool | None = None  # None => derive conservatively from license

    @property
    def is_publishable(self) -> bool:
        """Effective publishability: fail-closed on private source, then flag, then license.

        A PRIVATE-source (localwp/operator) image is NEVER publishable — not by a
        CC0/public-domain license and not by an explicit ``publishable=True`` — so a
        mis-authored license or flag can never leak a personal photo (the crown-jewel
        "never publish uploads" invariant). For public-eligible sources an explicit
        flag wins, else only CC0 / public-domain publish by default (public figures
        set the flag).
        """
        if self.source in PRIVATE_SOURCES:
            return False
        if self.publishable is not None:
            return self.publishable
        return self.license in (LicenseTag.CC0, LicenseTag.PUBLIC_DOMAIN)


class SpatialFact(BaseModel):
    """Relative-placement ground truth derived from curated boxes (plan S1).

    ``reference`` is the second subject for binary relations (left_of/right_of/
    above/below) and is null for foreground/background; ``between`` uses
    ``reference`` plus ``reference2``.
    """

    model_config = ConfigDict(extra="forbid")

    subject: str
    relation: SpatialRelation
    reference: str | None = None
    reference2: str | None = None
    phrases: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _binary_relations_need_reference(self) -> SpatialFact:
        binary = {
            SpatialRelation.LEFT_OF,
            SpatialRelation.RIGHT_OF,
            SpatialRelation.ABOVE,
            SpatialRelation.BELOW,
        }
        if self.relation in binary and not self.reference:
            raise ValueError(f"{self.relation} requires a 'reference' subject")
        if self.relation is SpatialRelation.BETWEEN and not (self.reference and self.reference2):
            raise ValueError("between requires both 'reference' and 'reference2'")
        return self

    @property
    def text(self) -> str:
        """Human-readable label for reporting, e.g. 'Alice left_of Bob'."""
        rel = self.relation.value
        if self.relation is SpatialRelation.BETWEEN:
            return f"{self.subject} between {self.reference} and {self.reference2}"
        if self.reference:
            return f"{self.subject} {rel} {self.reference}"
        return f"{self.subject} {rel}"


def legacy_import_lineage(*, name: str | None) -> dict[str, object]:
    """Documented default lineage block for a pre-v3 box (rg-015).

    Used only by the Slice 2 migration of existing boxes. The loader never
    applies these defaults — a box without lineage fails validation.
    ``decision`` is derived from the box's existing ``name`` (named vs
    stranger). ``confidence`` is ``low`` because legacy labels were ungraded.
    ``saw_machine_proposals`` is True (fail-closed). ``labeled_at`` is the
    epoch sentinel (unknown). ``capture_session_id`` is the unknown-occasion
    sentinel: it records that no session is recoverable. The exhaustive
    gate rejects this token (S2R6-01); it does not mint an occasion key.
    """
    return {
        "labeler_id": LEGACY_IMPORT_LABELER_ID,
        "batch_id": LEGACY_IMPORT_BATCH_ID,
        "capture_session_id": LEGACY_IMPORT_CAPTURE_SESSION_ID,
        "pass_index": 0,
        "labeled_at": LEGACY_IMPORT_LABELED_AT,
        "tool_version": LEGACY_IMPORT_TOOL_VERSION,
        "saw_machine_proposals": LEGACY_IMPORT_SAW_MACHINE_PROPOSALS,
        "label_source": LabelSource.LEGACY_IMPORT.value,
        "decision": (LabelDecision.NAMED if name else LabelDecision.STRANGER).value,
        "confidence": LabelConfidence.LOW.value,
        "arbitration_of": None,
    }


class LabelLineage(BaseModel):
    """Per-box labeling provenance (PROV-01). A label without lineage cannot be
    audited; lineage is required on every box of a v3 manifest, not
    optional-with-default.

    ``saw_machine_proposals`` is a FLAG, not a source. ``inconclusive`` is a
    DECISION, not a confidence. ``capture_session_id`` is the writable surface
    for the occasion key and is required on every box of an ``exhaustive``
    manifest.
    """

    model_config = ConfigDict(extra="forbid")

    labeler_id: str
    batch_id: str
    capture_session_id: str | None = None
    pass_index: int
    labeled_at: str
    tool_version: str
    saw_machine_proposals: bool
    label_source: LabelSource
    decision: LabelDecision
    confidence: LabelConfidence
    arbitration_of: list[str] | None = None


class FaceBox(BaseModel):
    """A ground-truth face region: normalized centre (x, y) + size (w, h) in 0..1, an
    optional confirmed identity name, and the region source (iptc | mwg).

    Persisted for ALL curated faces — named people AND anonymous strangers
    (``name=None``) — so a face-detection bake-off (FIR-1) has box-level ground truth,
    not just ``face_count``. Coords mirror identity_sources.FaceRegion (centre-point).

    ``y`` may be omitted/null (VLM6-R2-G-01 / wF4). L→R ordering uses a per-box
    missing-y fallback and surfaces ``order_degraded``. Detection association
    (``associate_detections``) excludes null/invalid-y boxes from IoU matching
    and stamps ``AssociationResult.geometry_incomplete_gt`` — never invents y,
    never matches on x alone, never counts incomplete boxes as detector FNs
    (wG2). A required ``y: float`` made the freeze corpus *structurally*
    incapable of a non-zero ``labeled_y_missing_images`` counter.

    ``lineage`` is required by ``load_manifest`` (v3). It is optional on the
    model so ``load_legacy_manifest`` can return v2 boxes without inventing
    lineage (rg-015). The v3 loader rejects ``None`` — it does not default it.
    """

    model_config = ConfigDict(extra="forbid")

    x: float
    y: float | None = None
    w: float
    h: float
    name: str | None = None
    source: str  # iptc | mwg
    lineage: LabelLineage | None = None


class GoldenEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # annotation_mode is intentionally absent (S2R3-10 / S2R4-20): extra=forbid,
    # no field. Persisted mode is document-level on GoldenManifest. The
    # mixed-stamp / cannot-widen lattice is score-time raw-mapping only
    # (report.py). The loader refuses an on-disk per-entry stamp by name
    # (annotation_mode_is_document_level) rather than as an extra=forbid
    # accident, so the contract is testable against real JSON.

    path: str
    sha256: str
    media_id: int = Field(ge=1)  # synthetic, 1-based; never resets to zero (analyze keys image_<media_id>)
    face_count: int = Field(ge=0)
    present_identities: list[str]
    context_pack: ContextPack = Field(default_factory=ContextPack)
    # VLMFIX-S3-03: str only (not Optional) so null fails validation; use "" when N/A.
    base_caption: str = ""
    must_right: list[str]
    easy_wrong: list[str]
    policy: EntryPolicy
    # E20-FUSION Slice 4: optional mis-attachment labels (absent on non-fusion corpora).
    expected_attachments: list[ExpectedAttachment] = Field(default_factory=list)
    # Per-entry opt-out for corpora that intentionally omit a reference caption
    # without using empty string (reserved; loader also rejects JSON null).
    base_caption_optional: bool = False
    # --- VLM-6 S1 Golden-100 additions (all additive/optional) ---------------
    difficulty: Difficulty | None = None
    domain: Domain | None = None
    reference_facts: list[ReferenceFact] = Field(default_factory=list)
    spatial_facts: list[SpatialFact] = Field(default_factory=list)
    # All curated face boxes incl. anonymous strangers (name=None) — detection ground
    # truth for the FIR-1 bake-off; additive/optional (see FIR-1 §Coordination).
    face_boxes: list[FaceBox] = Field(default_factory=list)
    # FIR-11 Slice 1: provenance is required on the v3 gate path
    # (``load_manifest`` fail-closes, naming every offending path). The model
    # field is optional so ``load_legacy_manifest`` can return frozen v2 rows
    # that omit it (golden150's six unprovenanced entries) without inventing a
    # provenance block (rg-015). A v3 box/entry still cannot load unsigned.
    provenance: Provenance | None = None
    # FIR-5 S1: bake-off image-slice tags (additive; legacy entries omit → []).
    tags: list[SliceTag] = Field(default_factory=list)
    # Optional image-level cohort fallback; single-subject celebs01 only (S3d enforces).
    demographic_cohort: str | None = None

    @field_validator("sha256")
    @classmethod
    def _sha256_is_hex(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("sha256 must be 64 lowercase hex chars")
        return value

    @field_validator("base_caption", mode="before")
    @classmethod
    def _base_caption_not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError(
                "base_caption must be a string (use empty string when not applicable; JSON null is rejected)"
            )
        return value


class GoldenManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_version: int
    annotation_mode: AnnotationMode
    roster: list[str]
    entries: list[GoldenEntry]
    # FIR-5 S1: roster-name -> demographic cohort; keys validated ⊆ roster at load.
    roster_cohorts: dict[str, str] = Field(default_factory=dict)

    @field_validator("manifest_version")
    @classmethod
    def _version_is_supported(cls, value: int, info: ValidationInfo) -> int:
        if info.context and info.context.get("legacy"):
            if value != LEGACY_MANIFEST_VERSION:
                raise ValueError(
                    f"legacy loader understands version {LEGACY_MANIFEST_VERSION} only; got {value}"
                )
            return value
        if value != SUPPORTED_MANIFEST_VERSION:
            raise ValueError(
                f"unsupported manifest_version {value}; this loader understands "
                f"version {SUPPORTED_MANIFEST_VERSION} only"
            )
        return value

    @field_validator("entries")
    @classmethod
    def _entries_not_empty(cls, value: list[GoldenEntry]) -> list[GoldenEntry]:
        if not value:
            raise ValueError("manifest has no entries; an empty corpus cannot be scored")
        return value

    def _present_identities_fit_face_count(self) -> None:
        """Reject identity claims that exceed the independently recorded face_count.

        ``present_identities`` is identification ground truth. A list longer
        than ``face_count`` is an unbacked claim in both annotation modes
        (FIR-11-S2-04 / S2R2-05).
        """
        for index, entry in enumerate(self.entries):
            n_ids = len(entry.present_identities)
            if entry.face_count < n_ids:
                raise ManifestError(
                    f"present_identities_fit_face_count: entry[{index}] "
                    f"{entry.path}: face_count={entry.face_count} < "
                    f"len(present_identities)={n_ids}",
                    invariant="present_identities_fit_face_count",
                    entry_index=index,
                    entry_path=entry.path,
                )

    def _boxes_cover_face_count(self) -> None:
        """Manifest-level coverage invariant (replaces retired entry-level check).

        ``face_count`` is an independently recorded operator count, never
        derived from ``len(face_boxes)``. Equality under ``exhaustive`` proves
        internal consistency only — not exhaustiveness in the world.
        """
        for index, entry in enumerate(self.entries):
            n_boxes = len(entry.face_boxes)
            if self.annotation_mode is AnnotationMode.EXHAUSTIVE:
                if n_boxes != entry.face_count:
                    raise ManifestError(
                        f"boxes_cover_face_count: exhaustive entry[{index}] "
                        f"{entry.path}: len(face_boxes)={n_boxes} != "
                        f"face_count={entry.face_count}",
                        invariant="boxes_cover_face_count",
                        entry_index=index,
                        entry_path=entry.path,
                    )
            elif self.annotation_mode is AnnotationMode.ROSTER_ONLY:
                if n_boxes > entry.face_count:
                    raise ManifestError(
                        f"boxes_cover_face_count: roster_only entry[{index}] "
                        f"{entry.path}: len(face_boxes)={n_boxes} > "
                        f"face_count={entry.face_count}",
                        invariant="boxes_cover_face_count",
                        entry_index=index,
                        entry_path=entry.path,
                    )

    def _lineage_required_on_boxes(self) -> None:
        """PROV-01: a label without lineage cannot be audited."""
        for index, entry in enumerate(self.entries):
            for box_index, box in enumerate(entry.face_boxes):
                if box.lineage is None:
                    raise ManifestError(
                        f"label_lineage_required: entry[{index}] {entry.path} "
                        f"box[{box_index}] has no LabelLineage",
                        invariant="label_lineage_required",
                        entry_index=index,
                        entry_path=entry.path,
                    )

    def _capture_session_required_when_exhaustive(self) -> None:
        """Occasion key must be a real session on every exhaustive box.

        ``LEGACY_IMPORT_CAPTURE_SESSION_ID`` is not a session — it is the
        documented unknown-occasion marker minted for pre-v3 boxes. A
        truthy sentinel must not clear this gate (S2R6-01 / rg-015).
        """
        if self.annotation_mode is not AnnotationMode.EXHAUSTIVE:
            return
        for index, entry in enumerate(self.entries):
            for box_index, box in enumerate(entry.face_boxes):
                session = None if box.lineage is None else box.lineage.capture_session_id
                if not session or session == LEGACY_IMPORT_CAPTURE_SESSION_ID:
                    detail = (
                        "is missing capture_session_id"
                        if not session
                        else (
                            f"carries unknown-occasion sentinel "
                            f"{LEGACY_IMPORT_CAPTURE_SESSION_ID!r}"
                        )
                    )
                    raise ManifestError(
                        f"capture_session_id_required: exhaustive entry[{index}] "
                        f"{entry.path} box[{box_index}] {detail}",
                        invariant="capture_session_id_required",
                        entry_index=index,
                        entry_path=entry.path,
                    )

    @model_validator(mode="after")
    def _enforce_v3_invariants(self, info: ValidationInfo) -> GoldenManifest:
        if info.context and info.context.get("legacy"):
            return self
        self._present_identities_fit_face_count()
        self._boxes_cover_face_count()
        self._lineage_required_on_boxes()
        self._capture_session_required_when_exhaustive()
        return self


def _reject_per_entry_annotation_mode(entries_raw: object) -> None:
    """Persisted annotation_mode is document-level (S2R3-10 / S2R4-20).

    A per-entry stamp in a JSON file is not a loadable contract. The
    mixed-stamp lattice lives on raw mappings at score time; the loader
    must not let pydantic extra=forbid be the only rejection, because
    that makes the decision look like a missing field rather than a
    named document-level rule (rg-009).
    """
    if not isinstance(entries_raw, list):
        return
    for index, raw_entry in enumerate(entries_raw):
        if not isinstance(raw_entry, dict):
            continue
        if "annotation_mode" not in raw_entry:
            continue
        path = raw_entry.get("path")
        entry_path = path if isinstance(path, str) else None
        label = entry_path if entry_path else f"entry[{index}]"
        raise ManifestError(
            f"annotation_mode is document-level; per-entry stamp is not a "
            f"persisted contract ({label})",
            invariant=ANNOTATION_MODE_DOCUMENT_LEVEL_INVARIANT,
            entry_index=index,
            entry_path=entry_path,
        )


def _entry_field_is_populated(entry: GoldenEntry, field: str) -> bool:
    """True when ``field`` carries non-empty metric-backing content on ``entry``."""
    value = getattr(entry, field, None)
    if value is None:
        return False
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, str):
        return bool(value.strip())
    return True


def inventory_corpus_fields(manifest: GoldenManifest) -> dict[str, FieldPopulation]:
    """Report per-field population counts for stratification / metric backing.

    Makes empty strata visible (MEAS-09) instead of silently collapsing every
    per-stratum gate into one bucket (VLM6-R2-03 / EVAL-04).
    """
    total = len(manifest.entries)
    out: dict[str, FieldPopulation] = {}
    for field in STRATIFICATION_INVENTORY_FIELDS:
        populated = sum(1 for entry in manifest.entries if _entry_field_is_populated(entry, field))
        out[field] = FieldPopulation(field=field, populated=populated, total=total)
    return out


def require_metric_backing(manifest: GoldenManifest, field: str) -> FieldPopulation:
    """Refuse to certify a metric whose backing field is empty corpus-wide.

    Call this before any gate that buckets or scores on ``field``. A vacuous
    0/N field must not return pass — it must name the field, the 0/N counts,
    and the remedy (populate the field or declare a coverage gap with owner).
    """
    if field not in STRATIFICATION_INVENTORY_FIELDS:
        raise ManifestError(
            f"unknown metric-backing field {field!r}; known fields are {', '.join(STRATIFICATION_INVENTORY_FIELDS)}"
        )
    pop = inventory_corpus_fields(manifest)[field]
    if pop.is_vacuous:
        gap = SHIPPED_CORPUS_COVERAGE_GAPS.get(field)
        gap_hint = (
            f" Declared coverage gap: {gap}."
            if gap
            else (
                f" Populate {field!r} on golden entries (derivable labels or operator "
                "curation) before gating on it, or add it to SHIPPED_CORPUS_COVERAGE_GAPS "
                "with owner=… and a concrete action."
            )
        )
        raise ManifestError(
            f"cannot certify metric backed by {field!r}: {pop.populated}/{pop.total} entries "
            f"populate that field (vacuous corpus-wide; per-stratum gate would collapse to "
            f"a single bucket).{gap_hint}"
        )
    return pop


# Minimum populated entries for a critical slice to count as evaluable (EVAL-04).
# Below this threshold the claim unit is disclosed as under-sampled, not certified.
METRIC_BACKING_SLICE_THRESHOLD: int = 5

# Scorer-facing consequences when a registry gap field is empty/under-sampled.
# Kept next to the registry so disclosure cannot drift from SHIPPED_CORPUS_COVERAGE_GAPS.
_GAP_SCORER_CONSEQUENCES: dict[str, str] = {
    "face_boxes": (
        "positional_identification never runs; set-based identity scoring "
        "cannot catch right-names-on-wrong-faces"
    ),
    "spatial_facts": "placement accuracy is vacuous (0 asserted claims)",
    "reference_facts": "no trap coverage for fabricated-fact scoring (rate is undefined)",
    "demographic_cohort": "demographic/cohort fairness slices have no sampling frame",
}


def compute_corpus_coverage_gaps(
    entries: list[GoldenEntry] | list[object],
    *,
    threshold: int = METRIC_BACKING_SLICE_THRESHOLD,
) -> dict[str, dict[str, object]]:
    """Sampling-frame honesty for every SHIPPED_CORPUS_COVERAGE_GAPS field (AUDIT-07).

    Always reports populated/total and a slice threshold — never a boolean that
    hides a 1/N under-sampled field (VLM6-C-01). Driven by the package gap
    registry so demographic_cohort cannot drift out of the anchor (VLM6-C-02).
    Call from offline generators *and* live score paths (VLM6-E-07).

    Returns a dict keyed by field name. Each value is a structured record::

        {
          "populated": int,
          "total": int,
          "threshold": int,
          "below_threshold": bool,
          "pi_zero": bool,
          "reason": str,   # human-readable summary
          "registry": str, # owner=… action=… from SHIPPED_CORPUS_COVERAGE_GAPS
        }
    """
    total = len(entries)
    out: dict[str, dict[str, object]] = {}
    for field, registry in SHIPPED_CORPUS_COVERAGE_GAPS.items():
        populated = 0
        for entry in entries:
            if isinstance(entry, GoldenEntry):
                if _entry_field_is_populated(entry, field):
                    populated += 1
            else:
                value = getattr(entry, field, None)
                if value is None:
                    continue
                if isinstance(value, list) and len(value) == 0:
                    continue
                if isinstance(value, str) and not value.strip():
                    continue
                if value:
                    populated += 1
        below = populated < threshold
        pi_zero = populated == 0
        consequence = _GAP_SCORER_CONSEQUENCES.get(field, "metric claim units under-sampled")
        reason = f"{populated}/{total} entries populate it (threshold={threshold}) — {consequence}"
        out[field] = {
            "populated": populated,
            "total": total,
            "threshold": threshold,
            "below_threshold": below,
            "pi_zero": pi_zero,
            "reason": reason,
            "registry": registry,
        }
    return out


def metric_backing_refusals(manifest: GoldenManifest) -> dict[str, str]:
    """Call ``require_metric_backing`` for every registry gap field; collect refusals.

    Production gates must not treat a vacuous field as pass (EVAL-23). This
    helper is the single place generators and score paths share (VLM6-C-07).
    """
    refusals: dict[str, str] = {}
    for field in SHIPPED_CORPUS_COVERAGE_GAPS:
        try:
            require_metric_backing(manifest, field)
        except ManifestError as exc:
            refusals[field] = str(exc)
    return refusals


def resolve_verified_image(entry: GoldenEntry, images_root: Path | str) -> Path:
    """Resolve ``entry.path`` under ``images_root`` and verify the sha256 pin.

    Any path that reads image bytes must go through this (or ``load_manifest``
    hash verification) so corpus drift cannot stay silent (VLM6-R2-05 / OBS-04).
    """
    root = Path(images_root)
    if not root.is_dir():
        raise ManifestError(
            f"images directory not found: {root} — set GOLDEN_IMAGES_DIR to the "
            "rsync-bootstrapped fixture copy (see scene/tests/seed/README.md) before "
            "reading image bytes"
        )
    image_path = _resolve_image(root, entry.path)
    if image_path is None:
        raise ManifestError(
            f"image file missing: {entry.path} (under {root}) — re-rsync fixtures or "
            "fix the manifest path (see scene/tests/seed/README.md)"
        )
    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
    if digest != entry.sha256:
        raise ManifestError(
            f"sha256 mismatch for {entry.path}: manifest {entry.sha256}, file {digest} — "
            "image bytes drifted from the pinned corpus; re-bootstrap GOLDEN_IMAGES_DIR "
            "or update the manifest pin after an intentional replacement"
        )
    return image_path


def load_manifest(
    path: str,
    images_dir: str | None = None,
    *,
    skip_hash_verification: bool = False,
) -> GoldenManifest:
    """Load and validate a v3 golden manifest; verify image hashes by default.

    ``face_count`` is an operator-recorded count-first figure, never derived
    from ``len(face_boxes)``. The coverage invariant compares those two
    independently produced numbers (see module docstring).

    Hash verification is the default (VLM6-R2-05 / OBS-04). Resolution order:

    1. Explicit ``images_dir`` argument — always verified.
    2. Else ``GOLDEN_IMAGES_DIR`` env — verified when set.
    3. Else, if ``skip_hash_verification=True`` — metadata-only load (explicit
       opt-out for score paths that do not read image bytes).
    4. Else refuse with an actionable error.

    Raises ManifestError on: missing/unreadable file, malformed JSON, schema
    violations, unsupported version, missing ``annotation_mode``, a
    per-entry ``annotation_mode`` stamp (document-level only), empty corpus,
    duplicate media_id/path, identities outside the roster, roster_cohorts keys
    outside the roster, any entry missing ``provenance`` (FIR-11 Slice 1 —
    required, fail-closed; every offending path is named in one error), a box
    without ``LabelLineage``, an ``exhaustive`` box missing a real
    ``capture_session_id`` (the legacy-import unknown-occasion sentinel
    is rejected, not treated as a session), a coverage mismatch under the declared
    ``annotation_mode``, missing image files or sha256 mismatches, and silent
    no-verify attempts. Emits ``RubricEmptyWarning`` if the corpus defines no
    Must-Right/Easy-Wrong entries — the caption hard gate is then vacuous but
    that is surfaced, not silent (S1-02).

    Frozen v2 artifacts are not loaded here — use ``load_legacy_manifest``.

    Later-wave ``cli.py`` call sites that currently omit ``images_dir`` must either
    pass ``images_dir=`` / rely on ``GOLDEN_IMAGES_DIR`` when they read pixels, or
    pass ``skip_hash_verification=True`` for deliberate metadata-only loads
    (see ``_cmd_score`` ~1193, determinism helpers ~1109/1137, ``_cmd_score_face``
    ~1638/1653/1693, face fetch ~1536).
    """
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise ManifestError(
            f"golden manifest not found: {manifest_path} (expected scene/tests/seed/golden.json; see seed/README.md)"
        )
    try:
        raw = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"golden manifest unreadable or malformed JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ManifestError(
            f"golden manifest must be a JSON object, got {type(raw).__name__}"
        )

    # Version and structural shape fail before field-level holes (FIR-11-SL1-R1-04):
    # unsupported version / entries-not-a-list / entry-not-an-object must not
    # surface as TypeError or as a missing-provenance report.
    version = raw.get("manifest_version")
    if version is not None and version != SUPPORTED_MANIFEST_VERSION:
        raise ManifestError(
            f"unsupported manifest_version {version}; this loader understands "
            f"version {SUPPORTED_MANIFEST_VERSION} only"
        )
    entries_raw = raw.get("entries")
    if entries_raw is not None and not isinstance(entries_raw, list):
        raise ManifestError(
            f"manifest 'entries' must be a list, got {type(entries_raw).__name__}"
        )
    if isinstance(entries_raw, list):
        for index, raw_entry in enumerate(entries_raw):
            if not isinstance(raw_entry, dict):
                raise ManifestError(
                    f"manifest entry at index {index} must be an object, "
                    f"got {type(raw_entry).__name__}"
                )

    # v2 corpus contract (S6-01 / rg-008): base_caption is a first-class field, not
    # an optional golden-only convention. Require the key on every entry so
    # consumers can index entry["base_caption"] without KeyError; use "" when the
    # corpus does not author a reference caption (e.g. bake-off subset).
    if raw.get("manifest_version") == SUPPORTED_MANIFEST_VERSION:
        for raw_entry in entries_raw or []:
            if "base_caption" not in raw_entry:
                raise ManifestError(
                    f"manifest_version {SUPPORTED_MANIFEST_VERSION} requires 'base_caption' on "
                    f"every entry (missing on media_id={raw_entry.get('media_id')!r} path="
                    f"{raw_entry.get('path')!r}); use empty string when not applicable"
                )
            if raw_entry.get("base_caption") is None and not raw_entry.get("base_caption_optional"):
                raise ManifestError(
                    f"manifest_version {SUPPORTED_MANIFEST_VERSION} rejects null base_caption "
                    f"(media_id={raw_entry.get('media_id')!r} path={raw_entry.get('path')!r}); "
                    f"use empty string when not applicable, or set base_caption_optional=true"
                )

    # FIR-11 Slice 1: provenance is required. Aggregate every missing/null
    # entry into one ManifestError naming every offending path — fail-closed
    # and not fail-first, so a junior operator sees the full hole list.
    missing_provenance: list[str] = []
    for raw_entry in entries_raw or []:
        if raw_entry.get("provenance") is None:
            entry_path = raw_entry.get("path")
            media_id = raw_entry.get("media_id")
            if isinstance(entry_path, str) and entry_path:
                label = entry_path
                if media_id is not None:
                    label = f"{entry_path} (media_id={media_id})"
            else:
                label = f"media_id={media_id!r}"
            missing_provenance.append(label)
    if missing_provenance:
        listed = ", ".join(missing_provenance)
        raise ManifestError(
            f"provenance is required (fail-closed); missing on "
            f"{len(missing_provenance)} entries: {listed}"
        )

    if raw.get("annotation_mode") is None:
        raise ManifestError(
            "annotation_mode is required (exhaustive|roster_only)",
            invariant="annotation_mode_required",
        )
    _reject_per_entry_annotation_mode(entries_raw)

    try:
        manifest = GoldenManifest.model_validate(raw)
    except ManifestError:
        raise
    except ValidationError as exc:
        raise ManifestError(f"golden manifest schema violation: {exc}") from exc

    seen_ids: set[int] = set()
    seen_paths: set[str] = set()
    for entry in manifest.entries:
        if entry.media_id in seen_ids:
            raise ManifestError(f"duplicate media_id {entry.media_id} ({entry.path})")
        seen_ids.add(entry.media_id)
        if entry.path in seen_paths:
            raise ManifestError(f"duplicate path {entry.path!r} (each image must appear once)")
        seen_paths.add(entry.path)

    roster = set(manifest.roster)
    for entry in manifest.entries:
        for name in (*entry.present_identities, *entry.must_right, *entry.easy_wrong):
            if name not in roster:
                raise ManifestError(f"identity {name!r} in {entry.path} is not in the roster")
    for cohort_key in manifest.roster_cohorts:
        if cohort_key not in roster:
            raise ManifestError(f"roster_cohorts key {cohort_key!r} is not in the roster")

    if not any(entry.must_right or entry.easy_wrong for entry in manifest.entries):
        warnings.warn(
            "golden corpus defines no Must-Right/Easy-Wrong rubric entries; the caption "
            "hard gate and Easy-Wrong rubric are vacuous across the corpus (see seed/README.md)",
            RubricEmptyWarning,
            stacklevel=2,
        )

    resolved_images = images_dir if images_dir is not None else (os.environ.get("GOLDEN_IMAGES_DIR") or None)
    if resolved_images:
        _verify_hashes(manifest, Path(resolved_images))
    elif skip_hash_verification:
        pass  # explicit metadata-only opt-out (OBS-04: caller named the skip)
    else:
        raise ManifestError(
            "image hash verification is required by default but no images_dir was given "
            "and GOLDEN_IMAGES_DIR is unset. Pass images_dir=... (or set GOLDEN_IMAGES_DIR) "
            "to verify every entry's sha256 pin before any path that may read image bytes, "
            "or pass skip_hash_verification=True only for deliberate metadata-only loads "
            "that will not open image files (VLM6-R2-05 / OBS-04)."
        )
    return manifest


def load_legacy_manifest(path: str, images_dir: str | None = None) -> GoldenManifest:
    """Read-only v2 loader for Slice 5 bias-audit arms and Slice 3 audit-queue draw.

    Not reachable from ``cli.py`` gate commands. Accepts ``manifest_version`` 2
    only. Does **not** require ``annotation_mode``, ``LabelLineage``, or
    ``provenance`` (so frozen golden150-draft, with its six unprovenanced
    rows, can load). Does **not** apply the v3 coverage invariant.

    Documented default (rg-015): a v2 document that omits ``annotation_mode``
    is recorded as ``roster_only``. v2 manifests never claimed exhaustiveness —
    that is why corpus646 was mis-scored as if every face were boxed. The
    default is written into the returned object; it is not invented at
    detection-scoring time.

    ``manifest_version`` on the returned object stays 2.
    """
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise ManifestError(
            f"legacy manifest not found: {manifest_path}"
        )
    try:
        raw = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"legacy manifest unreadable or malformed JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ManifestError(
            f"legacy manifest must be a JSON object, got {type(raw).__name__}"
        )

    version = raw.get("manifest_version")
    if version != LEGACY_MANIFEST_VERSION:
        raise ManifestError(
            f"legacy loader understands version {LEGACY_MANIFEST_VERSION} only; got {version}"
        )
    entries_raw = raw.get("entries")
    if entries_raw is not None and not isinstance(entries_raw, list):
        raise ManifestError(
            f"manifest 'entries' must be a list, got {type(entries_raw).__name__}"
        )
    if isinstance(entries_raw, list):
        for index, raw_entry in enumerate(entries_raw):
            if not isinstance(raw_entry, dict):
                raise ManifestError(
                    f"manifest entry at index {index} must be an object, "
                    f"got {type(raw_entry).__name__}"
                )

    for raw_entry in entries_raw or []:
        if "base_caption" not in raw_entry:
            raise ManifestError(
                f"manifest_version {LEGACY_MANIFEST_VERSION} requires 'base_caption' on "
                f"every entry (missing on media_id={raw_entry.get('media_id')!r} path="
                f"{raw_entry.get('path')!r}); use empty string when not applicable"
            )
        if raw_entry.get("base_caption") is None and not raw_entry.get("base_caption_optional"):
            raise ManifestError(
                f"manifest_version {LEGACY_MANIFEST_VERSION} rejects null base_caption "
                f"(media_id={raw_entry.get('media_id')!r} path={raw_entry.get('path')!r}); "
                f"use empty string when not applicable, or set base_caption_optional=true"
            )

    payload = dict(raw)
    if payload.get("annotation_mode") is None:
        # Documented default — v2 never claimed exhaustiveness (see docstring).
        payload["annotation_mode"] = AnnotationMode.ROSTER_ONLY
    _reject_per_entry_annotation_mode(entries_raw)

    try:
        manifest = GoldenManifest.model_validate(payload, context={"legacy": True})
    except ManifestError:
        raise
    except ValidationError as exc:
        raise ManifestError(f"legacy manifest schema violation: {exc}") from exc

    seen_ids: set[int] = set()
    seen_paths: set[str] = set()
    for entry in manifest.entries:
        if entry.media_id in seen_ids:
            raise ManifestError(f"duplicate media_id {entry.media_id} ({entry.path})")
        seen_ids.add(entry.media_id)
        if entry.path in seen_paths:
            raise ManifestError(f"duplicate path {entry.path!r} (each image must appear once)")
        seen_paths.add(entry.path)

    roster = set(manifest.roster)
    for entry in manifest.entries:
        for name in (*entry.present_identities, *entry.must_right, *entry.easy_wrong):
            if name not in roster:
                raise ManifestError(f"identity {name!r} in {entry.path} is not in the roster")
    for cohort_key in manifest.roster_cohorts:
        if cohort_key not in roster:
            raise ManifestError(
                f"roster_cohorts key {cohort_key!r} is not in the roster"
            )

    if images_dir is not None:
        _verify_hashes(manifest, Path(images_dir))
    return manifest


def _verify_hashes(manifest: GoldenManifest, images_root: Path) -> None:
    if not images_root.is_dir():
        raise ManifestError(
            f"images directory not found: {images_root} — set GOLDEN_IMAGES_DIR to the "
            "rsync-bootstrapped fixture copy (see scene/tests/seed/README.md)"
        )
    for entry in manifest.entries:
        resolve_verified_image(entry, images_root)


def _resolve_image(images_root: Path, rel_path: str) -> Path | None:
    """Resolve ``rel_path`` under ``images_root``, tolerating NFC/NFD drift (S1-07).

    macOS stores decomposed (NFD) filenames while Linux preserves whatever bytes
    were written; an rsync between them can flip the normalization form. Try the
    exact bytes first, then the NFC and NFD normalizations so a non-ASCII path
    resolves the same on either platform.
    """
    for candidate in dict.fromkeys(
        (rel_path, unicodedata.normalize("NFC", rel_path), unicodedata.normalize("NFD", rel_path))
    ):
        image_path = images_root / candidate
        if image_path.is_file():
            return image_path
    return None
