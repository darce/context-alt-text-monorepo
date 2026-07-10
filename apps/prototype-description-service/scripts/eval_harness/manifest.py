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
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

SUPPORTED_MANIFEST_VERSION = 2


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


class GoldenEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str
    media_id: int
    face_count: int = Field(ge=0)
    present_identities: list[str]
    context_pack: ContextPack = Field(default_factory=ContextPack)
    base_caption: str | None = None
    must_right: list[str]
    easy_wrong: list[str]
    policy: EntryPolicy
    # E20-FUSION Slice 4: optional mis-attachment labels (absent on non-fusion corpora).
    expected_attachments: list[ExpectedAttachment] = Field(default_factory=list)

    @field_validator("sha256")
    @classmethod
    def _sha256_is_hex(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("sha256 must be 64 lowercase hex chars")
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
    identities outside the roster, and (when ``images_dir`` is given) missing
    image files or sha256 mismatches. Emits ``RubricEmptyWarning`` if the corpus
    defines no Must-Right/Easy-Wrong entries — the caption hard gate is then
    vacuous but that is surfaced, not silent (S1-02).
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
