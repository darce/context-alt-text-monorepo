"""corpus646 catalog: resolve a corpus ID to its ignored originals, then verify them read-only.

Stdlib only. ``benchmarks/manifests/corpus-catalog-v1.json`` pins the frozen v3r manifest by
SHA-256 and names the corpus root relative to the primary checkout, so a linked worktree reads
the primary's ignored images rather than a stray copy. Nothing here copies, downloads, decodes,
or writes image bytes, and the catalog records no availability: existence is read live.

Verification compares only the declared ``original`` hash (``sha256_source``). The manifest's
``sha256`` field is the derived space and is never a fallback.

With ``--evidence-db`` the pinned manifest bytes come from a private SQLite evidence DB instead of
the tracked file. ``db-import`` is the only command that writes or creates that DB. It stores exact
manifest bytes and their SHA-256 for one corpus ID: no image bytes, rows, or identity data.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

CATALOG_REL = "benchmarks/manifests/corpus-catalog-v1.json"
CATALOG_SCHEMA = "benchmark-corpus-catalog/v1"
COUNT_KEYS = ("entries", "present", "matched", "missing", "mismatched", "unsafe_paths")
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[4]
EVIDENCE_SCHEMA_VERSION = 1
EVIDENCE_MAX_MANIFEST_BYTES = 32 << 20
EVIDENCE_BUSY_TIMEOUT_S = 5
EVIDENCE_SOURCE = "evidence_db"
_EVIDENCE_TABLE = "corpus_manifest"
_EVIDENCE_DDL = (
    "CREATE TABLE corpus_manifest ("
    "corpus_id TEXT PRIMARY KEY NOT NULL, "
    "manifest_sha256 TEXT NOT NULL, "
    "manifest_bytes BLOB NOT NULL)"
)
_EVIDENCE_UNREADABLE = "evidence DB is missing, unreadable, or not a version-1 evidence DB"
_EVIDENCE_UNSAFE = "evidence DB must not be inside a Git checkout, worktree, or git directory"
_EVIDENCE_DIR_OPEN = "evidence DB directory must not be readable or writable by group or others"

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
    read_manifest: bool = True,
) -> CorpusLocation:
    """Resolve a corpus ID to its locations without opening any image bytes.

    The default root is the physical root of the primary checkout. An explicit ``corpus_root``
    wins and needs no git discovery. ``require_exists=False`` returns metadata even when the
    images are absent; it does not assert availability. ``read_manifest=False`` skips the tracked
    manifest file, so the caller supplies the pinned bytes from elsewhere.
    """
    repo = Path(repo_root).absolute()
    catalog, catalog_sha256 = _read_catalog(repo)
    if corpus_id not in catalog["corpora"]:
        raise CatalogError(f"unknown corpus ID {corpus_id!r}")
    entry = catalog["corpora"][corpus_id]
    manifest_path = repo / entry["manifest_path"]
    manifest_sha256 = entry["manifest_sha256"]
    if read_manifest:
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


def verify_corpus(location: CorpusLocation, *, manifest_bytes: bytes | None = None) -> dict:
    """Hash each declared original under the images root and count outcomes. Read-only.

    Every manifest entry lands in exactly one of matched, mismatched, missing, or unsafe_paths.
    ``present`` counts safe regular files that were hashed, so it equals matched + mismatched.
    ``manifest_bytes`` replaces the tracked manifest file when the caller already holds the pinned bytes.
    """
    if (location.hash_field, location.hash_space) != (_ORIGINAL_HASH_FIELD, "original"):
        raise CatalogError("verification supports only the original hash space")
    if manifest_bytes is None:
        manifest_bytes = _read_bytes(Path(location.manifest_path), "pinned manifest is missing or unreadable")
    if _sha256(manifest_bytes) != location.manifest_sha256:
        raise CatalogError("pinned manifest bytes do not match the catalog pin")
    rows = _manifest_rows(manifest_bytes)
    images_root = Path(location.images_root)
    real_root = os.path.realpath(images_root)
    counts = dict.fromkeys(COUNT_KEYS, 0)
    counts["entries"] = len(rows)
    for row in rows:
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


def _manifest_rows(manifest: bytes) -> list:
    """Entries of pinned manifest bytes. Verification and import share this shape check."""
    doc = _parse_json(manifest, "pinned manifest is not valid JSON")
    rows = doc.get("entries") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise CatalogError("pinned manifest has no entries list")
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise CatalogError("pinned manifest has a malformed entry")
    return rows


# --- private evidence DB v0: exact manifest bytes, one immutable row per corpus ID ----------------


def read_evidence_manifest(db_path: Path, corpus_id: str, *, expected_sha256: str) -> bytes:
    """Stored manifest bytes for corpus_id, checked against the catalog pin. Opens read-only; never creates."""
    path = _evidence_path(db_path)
    if not path.is_file():
        raise CatalogError(_EVIDENCE_UNREADABLE)
    conn = _evidence_connect(path, read_only=True)
    try:
        with _evidence_errors():
            _evidence_pragmas(conn)
            _evidence_check_schema(conn)
            row = conn.execute(
                "SELECT manifest_sha256, length(manifest_bytes) FROM corpus_manifest WHERE corpus_id = ?",
                (corpus_id,),
            ).fetchone()
            if row is None:
                raise CatalogError(f"evidence DB has no manifest for corpus {corpus_id!r}")
            stored_sha256, size = row
            if not isinstance(stored_sha256, str) or not isinstance(size, int) or size < 0:
                raise CatalogError(_EVIDENCE_UNREADABLE)
            if stored_sha256 != expected_sha256:
                raise CatalogError(f"evidence DB manifest for corpus {corpus_id!r} does not match the catalog pin")
            if size > EVIDENCE_MAX_MANIFEST_BYTES:
                raise CatalogError("evidence DB manifest exceeds the size bound")
            blob = conn.execute("SELECT manifest_bytes FROM corpus_manifest WHERE corpus_id = ?", (corpus_id,)).fetchone()[0]
            if not isinstance(blob, bytes):
                raise CatalogError(_EVIDENCE_UNREADABLE)
    finally:
        conn.close()
    if _sha256(blob) != stored_sha256:
        raise CatalogError(f"evidence DB manifest for corpus {corpus_id!r} is corrupt")
    return blob


def import_evidence_manifest(db_path: Path, corpus_id: str, manifest_bytes: bytes, *, expected_sha256: str) -> str:
    """Store exact manifest bytes in one transaction. Returns "imported" or "already_imported".

    The pin and size are checked before any file is touched. Changed bytes for an existing corpus
    ID are refused, never overwritten. Failed writes roll back, leaving an empty new file
    available for retry; unlinking it could delete a concurrent importer's committed store.
    """
    if len(manifest_bytes) > EVIDENCE_MAX_MANIFEST_BYTES:
        raise CatalogError("manifest exceeds the evidence DB size bound")
    if _sha256(manifest_bytes) != expected_sha256:
        raise CatalogError(f"corpus {corpus_id!r} manifest bytes do not match the catalog pin")
    path = _evidence_path(db_path)
    _evidence_private_dir(path.parent)
    _create_evidence_file(path)
    return _evidence_write(path, corpus_id, manifest_bytes, expected_sha256)


def _evidence_path(db_path: Path) -> Path:
    """Resolved DB path. Refused when the DB or any ancestor is a ``.git`` directory or holds a ``.git`` entry."""
    resolved = Path(db_path).absolute().resolve()
    for ancestor in (resolved.parent, *resolved.parent.parents):
        if ancestor.name == ".git" or os.path.lexists(ancestor / ".git"):
            raise CatalogError(_EVIDENCE_UNSAFE)
    return resolved


def _evidence_private_dir(directory: Path) -> None:
    """Create the immediate directory 0700 when missing. An existing one is refused, never chmodded, if open."""
    try:
        if directory.is_dir():
            if stat.S_IMODE(directory.stat().st_mode) & 0o077:
                raise CatalogError(_EVIDENCE_DIR_OPEN)
            return
        directory.mkdir(mode=0o700)
        os.chmod(directory, 0o700)
    except OSError:
        raise CatalogError("evidence DB directory is missing or cannot be created") from None


def _create_evidence_file(path: Path) -> bool:
    """Create a new 0600 file. Returns False when one exists already; an existing file is never truncated."""
    try:
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    except FileExistsError:
        return False
    except OSError:
        raise CatalogError(_EVIDENCE_UNREADABLE) from None
    return True


def _evidence_connect(path: Path, *, read_only: bool) -> sqlite3.Connection:
    target = f"{path.as_uri()}?mode=ro" if read_only else str(path)
    try:
        return sqlite3.connect(target, uri=read_only, timeout=EVIDENCE_BUSY_TIMEOUT_S, isolation_level=None)
    except sqlite3.Error:
        raise CatalogError(_EVIDENCE_UNREADABLE) from None


@contextlib.contextmanager
def _evidence_errors():
    """Map every sqlite3 failure to a fixed message so SQL text and stored values never reach stderr."""
    try:
        yield
    except sqlite3.Error:
        raise CatalogError(_EVIDENCE_UNREADABLE) from None


def _evidence_pragmas(conn: sqlite3.Connection) -> None:
    """Set the required pragmas, then confirm each one took effect."""
    conn.execute(f"PRAGMA busy_timeout = {EVIDENCE_BUSY_TIMEOUT_S * 1000}")
    conn.execute("PRAGMA synchronous = FULL")
    journal = conn.execute("PRAGMA journal_mode = DELETE").fetchone()[0]
    sync = conn.execute("PRAGMA synchronous").fetchone()[0]
    busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    if (journal, sync, busy) != ("delete", 2, EVIDENCE_BUSY_TIMEOUT_S * 1000):
        raise CatalogError(_EVIDENCE_UNREADABLE)


def _evidence_check_schema(conn: sqlite3.Connection) -> None:
    if conn.execute("PRAGMA user_version").fetchone()[0] != EVIDENCE_SCHEMA_VERSION:
        raise CatalogError("evidence DB schema version is not supported")
    found = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (_EVIDENCE_TABLE,)
    ).fetchone()
    if found is None:
        raise CatalogError(_EVIDENCE_UNREADABLE)


def _evidence_write(path: Path, corpus_id: str, manifest_bytes: bytes, expected_sha256: str) -> str:
    conn = _evidence_connect(path, read_only=False)
    try:
        with _evidence_errors():
            _evidence_pragmas(conn)
            conn.execute("BEGIN IMMEDIATE")
            try:
                # Decide initialization only while owning SQLite's writer lock. A
                # different importer may have committed since file creation/open.
                fresh = (
                    conn.execute("PRAGMA user_version").fetchone()[0] == 0
                    and conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone() is None
                )
                if fresh:
                    conn.execute(_EVIDENCE_DDL)
                    conn.execute(f"PRAGMA user_version = {EVIDENCE_SCHEMA_VERSION}")
                else:
                    _evidence_check_schema(conn)
                row = conn.execute(
                    "SELECT manifest_bytes FROM corpus_manifest WHERE corpus_id = ?", (corpus_id,)
                ).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO corpus_manifest (corpus_id, manifest_sha256, manifest_bytes) VALUES (?, ?, ?)",
                        (corpus_id, expected_sha256, manifest_bytes),
                    )
                    status = "imported"
                elif not isinstance(row[0], bytes):
                    raise CatalogError(_EVIDENCE_UNREADABLE)
                elif row[0] != manifest_bytes:
                    raise CatalogError(
                        f"corpus {corpus_id!r} already has a different imported manifest; refusing to overwrite"
                    )
                else:
                    status = "already_imported"
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
    finally:
        conn.close()
    return status


def _read_local_manifest(path: Path) -> bytes:
    try:
        with open(path, "rb") as handle:
            data = handle.read(EVIDENCE_MAX_MANIFEST_BYTES + 1)
    except OSError:
        raise CatalogError("local manifest is missing or unreadable") from None
    if len(data) > EVIDENCE_MAX_MANIFEST_BYTES:
        raise CatalogError("local manifest exceeds the evidence DB size bound")
    return data


def _db_import(corpus_id: str, repo_root: Path, evidence_db: Path, manifest: Path) -> dict:
    """Import a private local copy of the pinned manifest. Reads the tracked manifest file never."""
    catalog, _ = _read_catalog(Path(repo_root).absolute())
    if corpus_id not in catalog["corpora"]:
        raise CatalogError(f"unknown corpus ID {corpus_id!r}")
    pin = catalog["corpora"][corpus_id]["manifest_sha256"]
    manifest_bytes = _read_local_manifest(Path(manifest))
    entries = len(_manifest_rows(manifest_bytes))
    status = import_evidence_manifest(evidence_db, corpus_id, manifest_bytes, expected_sha256=pin)
    return {"corpus_id": corpus_id, "entries": entries, "manifest_sha256": pin, "status": status}


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
        sub.add_argument("--evidence-db", type=Path, default=None)
    importer = commands.add_parser(
        "db-import",
        help="import a private copy of the pinned manifest into the evidence DB",
        description="import a private copy of the pinned manifest into the evidence DB",
    )
    importer.add_argument("corpus_id")
    importer.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    importer.add_argument("--evidence-db", type=Path, required=True)
    importer.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    evidence = args.evidence_db
    try:
        if args.command == "db-import":
            _emit(_db_import(args.corpus_id, args.repo_root, args.evidence_db, args.manifest))
            return 0
        location = resolve_corpus(
            args.corpus_id,
            repo_root=args.repo_root,
            corpus_root=args.corpus_root,
            require_exists=args.command == "check",
            read_manifest=evidence is None,
        )
        manifest = None
        if evidence is not None:
            manifest = read_evidence_manifest(evidence, args.corpus_id, expected_sha256=location.manifest_sha256)
        if args.command == "show":
            payload = _location_payload(location)
            if evidence is not None:
                payload.update(manifest_path=None, manifest_source=EVIDENCE_SOURCE)
            _emit(payload)
            return 0
        counts = verify_corpus(location, manifest_bytes=manifest)
    except CatalogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError:
        print("error: corpus location could not be read", file=sys.stderr)
        return 2
    complete = counts["matched"] == counts["entries"]
    payload = {
        "catalog_sha256": location.catalog_sha256,
        "corpus_id": location.corpus_id,
        "counts": counts,
        "hash_field": location.hash_field,
        "hash_space": location.hash_space,
        "location_source": location.location_source,
        "manifest_sha256": location.manifest_sha256,
        "status": "complete" if complete else "incomplete",
    }
    if evidence is not None:
        payload["manifest_source"] = EVIDENCE_SOURCE
    _emit(payload)
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
