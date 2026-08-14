"""Golden-manifest schema + fail-fast loader (rg-008).

The manifest (`scene/tests/seed/golden.json`) is the single source of truth for
the eval corpus: per-image relative path, content sha256, stable synthetic
``media_id`` (the analyze contract keys uploads as ``image_<media_id>`` parts
and identity reads group by ``media_id``), ground-truth ``face_count`` (total
human faces present, including non-roster strangers), present-identity labels,
context-pack fixture, Must-Right/Easy-Wrong rubric entries, and policy flags.

Image bytes are NOT vendored in git; ``images_dir`` (usually ``$GOLDEN_IMAGES_DIR``)
points at the rsync-bootstrapped local copy and is verified hash-by-hash.

Every field is strictly typed under ``extra='forbid'`` and validated at load
time: ``policy.recognition_enabled`` is required (a typo can no longer silently
enable recognition), ``face_count`` must cover the labeled identities, paths and
media_ids must be unique, the corpus may not be empty, and the manifest version
must be one this loader understands (rg-008 fail-fast).
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import warnings
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

SUPPORTED_MANIFEST_VERSION = 2


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


# Private roots are LOCAL-ONLY: a personal photo is never publishable regardless of
# license or an explicit flag (fail-closed on the "never publish uploads" invariant).
PRIVATE_SOURCES: frozenset[ProvenanceSource] = frozenset({ProvenanceSource.LOCALWP, ProvenanceSource.OPERATOR})


class ManifestError(Exception):
    """Structural, hash, or label problem in the golden manifest. Fail fast."""


class RubricEmptyWarning(UserWarning):
    """The corpus defines no Must-Right/Easy-Wrong rubric entries (gate vacuous)."""


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


class FaceBox(BaseModel):
    """A ground-truth face region: normalized centre (x, y) + size (w, h) in 0..1, an
    optional confirmed identity name, and the region source (iptc | mwg).

    Persisted for ALL curated faces — named people AND anonymous strangers
    (``name=None``) — so a face-detection bake-off (FIR-1) has box-level ground truth,
    not just ``face_count``. Coords mirror identity_sources.FaceRegion (centre-point).
    """

    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    w: float
    h: float
    name: str | None = None
    source: str  # iptc | mwg


class GoldenEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    # FIR-11 Slice 1: provenance is required and fail-closed. A missing key is
    # rejected by load_manifest with every offending path named (aggregate, not
    # fail-first). Mis-attestation is worse than absence (PROV-01); this field
    # being optional is what let 6 golden150 entries load unsigned.
    provenance: Provenance
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

    @model_validator(mode="after")
    def _face_count_covers_labeled(self) -> GoldenEntry:
        if self.face_count < len(self.present_identities):
            raise ValueError(
                f"face_count {self.face_count} in {self.path} is below the "
                f"{len(self.present_identities)} labeled present_identities"
            )
        return self


class GoldenManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_version: int
    roster: list[str]
    entries: list[GoldenEntry]
    # FIR-5 S1: roster-name -> demographic cohort; keys validated ⊆ roster at load.
    roster_cohorts: dict[str, str] = Field(default_factory=dict)

    @field_validator("manifest_version")
    @classmethod
    def _version_is_supported(cls, value: int) -> int:
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


def load_manifest(path: str, images_dir: str | None = None) -> GoldenManifest:
    """Load and validate the golden manifest; optionally verify image hashes.

    Raises ManifestError on: missing/unreadable file, malformed JSON, schema
    violations, unsupported version, empty corpus, duplicate media_id/path,
    identities outside the roster, roster_cohorts keys outside the roster,
    any entry missing ``provenance`` (FIR-11 Slice 1 — required, fail-closed;
    every offending path is named in one error), and (when ``images_dir`` is
    given) missing image files or sha256 mismatches. Emits ``RubricEmptyWarning``
    if the corpus defines no Must-Right/Easy-Wrong entries — the caption hard
    gate is then vacuous but that is surfaced, not silent (S1-02).
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

    # v2 corpus contract (S6-01 / rg-008): base_caption is a first-class field, not
    # an optional golden-only convention. Require the key on every entry so
    # consumers can index entry["base_caption"] without KeyError; use "" when the
    # corpus does not author a reference caption (e.g. bake-off subset).
    if isinstance(raw, dict) and raw.get("manifest_version") == SUPPORTED_MANIFEST_VERSION:
        for raw_entry in raw.get("entries") or []:
            if not isinstance(raw_entry, dict):
                continue
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
    if isinstance(raw, dict):
        missing_provenance: list[str] = []
        for raw_entry in raw.get("entries") or []:
            if not isinstance(raw_entry, dict):
                continue
            if raw_entry.get("provenance") is None:
                path = raw_entry.get("path")
                media_id = raw_entry.get("media_id")
                if isinstance(path, str) and path:
                    label = path
                    if media_id is not None:
                        label = f"{path} (media_id={media_id})"
                else:
                    label = f"media_id={media_id!r}"
                missing_provenance.append(label)
        if missing_provenance:
            listed = ", ".join(missing_provenance)
            raise ManifestError(
                f"provenance is required (fail-closed); missing on "
                f"{len(missing_provenance)} entries: {listed}"
            )

    try:
        manifest = GoldenManifest.model_validate(raw)
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
            raise ManifestError(
                f"roster_cohorts key {cohort_key!r} is not in the roster"
            )

    if not any(entry.must_right or entry.easy_wrong for entry in manifest.entries):
        warnings.warn(
            "golden corpus defines no Must-Right/Easy-Wrong rubric entries; the caption "
            "hard gate and Easy-Wrong rubric are vacuous across the corpus (see seed/README.md)",
            RubricEmptyWarning,
            stacklevel=2,
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
        image_path = _resolve_image(images_root, entry.path)
        if image_path is None:
            raise ManifestError(f"image file missing: {entry.path} (under {images_root})")
        digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
        if digest != entry.sha256:
            raise ManifestError(f"sha256 mismatch for {entry.path}: manifest {entry.sha256}, file {digest}")


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
