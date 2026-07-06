"""Golden-manifest schema + fail-fast loader (rg-008).

The manifest (`scene/tests/seed/golden.json`) is the single source of truth for
the eval corpus: per-image relative path, content sha256, stable synthetic
``media_id`` (the analyze contract keys uploads as ``image_<media_id>`` parts
and identity reads group by ``media_id``), present-identity labels, context-pack
fixture, Must-Right/Easy-Wrong rubric entries, and policy flags.

Image bytes are NOT vendored in git; ``images_dir`` (usually ``$GOLDEN_IMAGES_DIR``)
points at the rsync-bootstrapped local copy and is verified hash-by-hash.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ManifestError(Exception):
    """Structural, hash, or label problem in the golden manifest. Fail fast."""


class GoldenEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str
    media_id: int
    present_identities: list[str]
    context_pack: dict
    must_right: list[str]
    easy_wrong: list[str]
    policy: dict

    @field_validator("sha256")
    @classmethod
    def _sha256_is_hex(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("sha256 must be 64 lowercase hex chars")
        return value


class GoldenManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_version: int
    roster: list[str]
    entries: list[GoldenEntry]


def load_manifest(path: str, images_dir: str | None = None) -> GoldenManifest:
    """Load and validate the golden manifest; optionally verify image hashes.

    Raises ManifestError on: missing/unreadable file, malformed JSON, schema
    violations, duplicate media_id, identities outside the roster, and (when
    ``images_dir`` is given) missing image files or sha256 mismatches.
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
    for entry in manifest.entries:
        if entry.media_id in seen_ids:
            raise ManifestError(f"duplicate media_id {entry.media_id} ({entry.path})")
        seen_ids.add(entry.media_id)

    roster = set(manifest.roster)
    for entry in manifest.entries:
        for name in (*entry.present_identities, *entry.must_right, *entry.easy_wrong):
            if name not in roster:
                raise ManifestError(f"identity {name!r} in {entry.path} is not in the roster")

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
        image_path = images_root / entry.path
        if not image_path.is_file():
            raise ManifestError(f"image file missing: {entry.path} (under {images_root})")
        digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
        if digest != entry.sha256:
            raise ManifestError(f"sha256 mismatch for {entry.path}: manifest {entry.sha256}, file {digest}")
