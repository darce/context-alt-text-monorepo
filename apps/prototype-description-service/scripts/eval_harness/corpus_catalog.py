"""corpus646 catalog: resolve a corpus ID to its ignored originals, then verify them read-only.

Stdlib only. ``benchmarks/manifests/corpus-catalog-v1.json`` pins the frozen v3r manifest by
SHA-256 and names the corpus root relative to the primary checkout, so a linked worktree reads
the primary's ignored images rather than a stray copy. Nothing here copies, downloads, decodes,
or writes image bytes, and the catalog records no availability: existence is read live.

Verification compares only the declared ``original`` hash (``sha256_source``). The manifest's
``sha256`` field is the derived space and is never a fallback.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

CATALOG_REL = "benchmarks/manifests/corpus-catalog-v1.json"
CATALOG_SCHEMA = "benchmark-corpus-catalog/v1"
COUNT_KEYS = ("entries", "present", "matched", "missing", "mismatched", "unsafe_paths")
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[4]

_ENTRY_KEYS = frozenset(
    {
        "root_relative",
        "images_subdir",
        "provenance_file",
        "manifest_path",
        "manifest_sha256",
        "hash_field",
        "hash_space",
    }
)
_RELPATH_FIELDS = ("root_relative", "images_subdir", "provenance_file", "manifest_path")
_ORIGINAL_HASH_FIELD = "sha256_source"
_CORPUS_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_READ_CHUNK = 1 << 20
_REFUSE_DEFAULT_ROOT = (
    "default corpus root needs repo_root to be a normal git checkout or linked worktree; "
    "pass --corpus-root to name the corpus explicitly"
)


class CatalogError(ValueError):
    """Catalog, pin, or root failure. Messages name catalog keys and IDs, never image files."""


@dataclasses.dataclass(frozen=True)
class CorpusLocation:
    corpus_id: str
    corpus_root: Path
    images_root: Path
    provenance_path: Path
    manifest_path: Path
    manifest_sha256: str
    hash_field: str
    hash_space: str
    catalog_path: Path
    catalog_sha256: str
    location_source: str


def load_catalog(repo_root: Path) -> dict:
    """Return the validated tracked catalog. Reads only the catalog file."""
    return _read_catalog(Path(repo_root).absolute())[0]


def resolve_corpus(
    corpus_id: str,
    *,
    repo_root: Path,
    corpus_root: Path | None = None,
    require_exists: bool = True,
) -> CorpusLocation:
    """Resolve a corpus ID to its locations without opening any image bytes.

    The default root is the physical root of the primary checkout. An explicit ``corpus_root``
    wins and needs no git discovery. ``require_exists=False`` returns metadata even when the
    images are absent; it does not assert availability.
    """
    repo = Path(repo_root).absolute()
    catalog, catalog_sha256 = _read_catalog(repo)
    if corpus_id not in catalog["corpora"]:
        raise CatalogError(f"unknown corpus ID {corpus_id!r}")
    entry = catalog["corpora"][corpus_id]
    manifest_path = repo / entry["manifest_path"]
    manifest_bytes = _read_bytes(manifest_path, f"corpus {corpus_id!r} pinned manifest is missing or unreadable")
    manifest_sha256 = _sha256(manifest_bytes)
    if manifest_sha256 != entry["manifest_sha256"]:
        raise CatalogError(f"corpus {corpus_id!r} manifest bytes do not match the catalog pin")
    if corpus_root is None:
        root = _primary_physical_root(repo) / entry["root_relative"]
        source = "primary_checkout"
    else:
        root = Path(corpus_root).absolute()
        source = "explicit_override"
    images_root = root / entry["images_subdir"]
    if require_exists and not images_root.is_dir():
        raise CatalogError(
            f"corpus {corpus_id!r} image directory is absent; restore the ignored originals or pass --corpus-root"
        )
    return CorpusLocation(
        corpus_id=corpus_id,
        corpus_root=root,
        images_root=images_root,
        provenance_path=root / entry["provenance_file"],
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        hash_field=entry["hash_field"],
        hash_space=entry["hash_space"],
        catalog_path=repo / CATALOG_REL,
        catalog_sha256=catalog_sha256,
        location_source=source,
    )


def verify_corpus(location: CorpusLocation) -> dict:
    """Hash each declared original under the images root and count outcomes. Read-only.

    Every manifest entry lands in exactly one of matched, mismatched, missing, or unsafe_paths.
    ``present`` counts safe regular files that were hashed, so it equals matched + mismatched.
    """
    if (location.hash_field, location.hash_space) != (_ORIGINAL_HASH_FIELD, "original"):
        raise CatalogError("verification supports only the original hash space")
    manifest = _read_bytes(Path(location.manifest_path), "pinned manifest is missing or unreadable")
    if _sha256(manifest) != location.manifest_sha256:
        raise CatalogError("pinned manifest bytes do not match the catalog pin")
    doc = _parse_json(manifest, "pinned manifest is not valid JSON")
    rows = doc.get("entries") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise CatalogError("pinned manifest has no entries list")
    images_root = Path(location.images_root)
    real_root = os.path.realpath(images_root)
    counts = dict.fromkeys(COUNT_KEYS, 0)
    counts["entries"] = len(rows)
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise CatalogError("pinned manifest has a malformed entry")
        target = _contained_target(images_root, real_root, row["path"])
        if target is None:
            counts["unsafe_paths"] += 1
            continue
        digest = _regular_file_sha256(target)
        if digest is None:
            counts["missing"] += 1
            continue
        counts["present"] += 1
        counts["matched" if digest == row.get(location.hash_field) else "mismatched"] += 1
    return counts


def _read_catalog(repo: Path) -> tuple[dict, str]:
    raw = _read_bytes(repo / CATALOG_REL, "tracked catalog is missing or unreadable")
    doc = _parse_json(raw, "tracked catalog is not valid JSON", object_pairs_hook=_no_duplicate_keys)
    return _validate_catalog(doc), _sha256(raw)


def _validate_catalog(doc) -> dict:
    if not isinstance(doc, dict) or set(doc) != {"schema", "corpora"}:
        raise CatalogError("tracked catalog must have exactly the keys schema and corpora")
    if doc["schema"] != CATALOG_SCHEMA:
        raise CatalogError(f"tracked catalog schema must be {CATALOG_SCHEMA!r}")
    corpora = doc["corpora"]
    if not isinstance(corpora, dict) or not corpora:
        raise CatalogError("tracked catalog corpora must be a non-empty object")
    for corpus_id, entry in corpora.items():
        if not _CORPUS_ID_RE.fullmatch(corpus_id):
            raise CatalogError("tracked catalog has a corpus ID outside the safe ID alphabet")
        _validate_entry(corpus_id, entry)
    return doc


def _validate_entry(corpus_id: str, entry) -> None:
    if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS:
        raise CatalogError(f"catalog entry {corpus_id!r} must have exactly the v1 keys")
    for field in _RELPATH_FIELDS:
        if not _is_safe_relpath(entry[field]):
            raise CatalogError(f"catalog entry {corpus_id!r} field {field} must be a relative path with no '..' parts")
    digest = entry["manifest_sha256"]
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise CatalogError(f"catalog entry {corpus_id!r} manifest_sha256 must be 64 lowercase hex digits")
    if entry["hash_space"] != "original" or entry["hash_field"] != _ORIGINAL_HASH_FIELD:
        raise CatalogError(f"catalog entry {corpus_id!r} must hash the original space with {_ORIGINAL_HASH_FIELD}")


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    doc: dict = {}
    for key, value in pairs:
        if key in doc:
            raise CatalogError("tracked catalog repeats a key")
        doc[key] = value
    return doc


def _is_safe_relpath(value) -> bool:
    if not isinstance(value, str) or "\\" in value or "\x00" in value:
        return False
    return all(part not in ("", ".", "..") for part in value.split("/"))


def _contained_target(images_root: Path, real_root: str, rel: str) -> str | None:
    """Resolved path of a manifest entry, or None when it escapes the images root by name or symlink."""
    if not _is_safe_relpath(rel):
        return None
    target = os.path.realpath(images_root / rel)
    return target if os.path.commonpath([target, real_root]) == real_root else None


def _regular_file_sha256(path: str) -> str | None:
    """Digest of a regular file, or None when it is absent, not a regular file, or unreadable."""
    if not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(_READ_CHUNK), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _primary_physical_root(repo: Path) -> Path:
    """Physical root of the primary checkout that owns this worktree's git common directory.

    Only a normal ``.git`` directory qualifies. Bare repos, separate git dirs, and stray ``.git``
    directories are refused rather than guessed.
    """
    toplevel = _git(repo, "rev-parse", "--show-toplevel")
    bare = _git(repo, "rev-parse", "--is-bare-repository")
    common = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    listing = _git(repo, "worktree", "list", "--porcelain")
    if None in (toplevel, bare, common, listing):
        raise CatalogError(_REFUSE_DEFAULT_ROOT)
    common_dir = Path(common)
    main = next((line[len("worktree ") :] for line in listing.splitlines() if line.startswith("worktree ")), None)
    if (
        Path(toplevel).resolve() != repo.resolve()
        or bare != "false"
        or common_dir.name != ".git"
        or not common_dir.is_dir()
        or main is None
        or Path(main).resolve() != common_dir.parent.resolve()
    ):
        raise CatalogError(_REFUSE_DEFAULT_ROOT)
    return common_dir.parent


def _git(repo: Path, *args: str) -> str | None:
    """Stdout of a read-only git query against ``repo``, or None on any failure. GIT_* overrides are dropped."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            env=env,
            capture_output=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace").strip()


def _read_bytes(path: Path, message: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        raise CatalogError(message) from None


def _parse_json(raw: bytes, message: str, **kwargs):
    try:
        return json.loads(raw.decode("utf-8"), **kwargs)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise CatalogError(message) from None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _location_payload(location: CorpusLocation) -> dict:
    return {
        "catalog_path": str(location.catalog_path),
        "catalog_sha256": location.catalog_sha256,
        "corpus_id": location.corpus_id,
        "corpus_root": str(location.corpus_root),
        "corpus_root_exists": location.corpus_root.is_dir(),
        "hash_field": location.hash_field,
        "hash_space": location.hash_space,
        "images_root": str(location.images_root),
        "images_root_exists": location.images_root.is_dir(),
        "location_source": location.location_source,
        "manifest_path": str(location.manifest_path),
        "manifest_sha256": location.manifest_sha256,
        "provenance_path": str(location.provenance_path),
    }


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.eval_harness.corpus_catalog")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, summary in (
        ("show", "print catalog metadata and live root existence"),
        ("check", "hash declared originals read-only and print counts"),
    ):
        sub = commands.add_parser(name, help=summary, description=summary)
        sub.add_argument("corpus_id")
        sub.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
        sub.add_argument("--corpus-root", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        location = resolve_corpus(
            args.corpus_id,
            repo_root=args.repo_root,
            corpus_root=args.corpus_root,
            require_exists=args.command == "check",
        )
        if args.command == "show":
            _emit(_location_payload(location))
            return 0
        counts = verify_corpus(location)
    except CatalogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError:
        print("error: corpus location could not be read", file=sys.stderr)
        return 2
    complete = counts["matched"] == counts["entries"]
    _emit(
        {
            "catalog_sha256": location.catalog_sha256,
            "corpus_id": location.corpus_id,
            "counts": counts,
            "hash_field": location.hash_field,
            "hash_space": location.hash_space,
            "location_source": location.location_source,
            "manifest_sha256": location.manifest_sha256,
            "status": "complete" if complete else "incomplete",
        }
    )
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
