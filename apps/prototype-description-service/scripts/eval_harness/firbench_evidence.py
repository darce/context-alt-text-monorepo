"""FIRBENCH-1 artifact pointers: register, check, and resolve evidence files in the private evidence DB.

The pointer table lives in the same explicit ``--evidence-db`` file as ``corpus_catalog`` v0 and is
created only by ``register`` under ``BEGIN IMMEDIATE``. Readers open the DB ``mode=ro``; registration
opens an existing DB ``mode=rw`` and never creates one. A pointer locates a report or score file and
records its raw SHA-256. It confers no ground truth, annotation QC, capture-occasion, human
observation, or numerical acceptance. ``resolve`` prints a local absolute path for operator use only;
never copy that output into Git, MCP, or a prompt.
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
import sys
from pathlib import Path

from scripts.eval_harness import corpus_catalog as cc

ARTIFACT_TABLE = "artifact_pointer_v1"
KINDS = {"report-json": ".json", "report-html": ".html", "scores-json": ".json", "run-manifest": ".json"}
HASH_KINDS = ("raw-sha256", "legacy-model-dump-sha256")
QUALIFICATIONS = ("unqualified", "partial")
MAX_ARTIFACT_BYTES = 256 << 20
READ_CHUNK = 1 << 20
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_SHA40_RE = re.compile(r"[0-9a-f]{40}")
_SHA64_RE = re.compile(r"[0-9a-f]{64}")
# Image and SQLite headers. A report is text, so any of these means the pointer names the wrong file.
_BINARY_PREFIXES = (
    b"SQLite format 3\x00",
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
    b"BM",
    b"II*\x00",
    b"MM\x00*",
)
_POINTER_COLUMNS = (
    ("artifact_id", "TEXT", 1, 1),
    ("kind", "TEXT", 1, 0),
    ("resolved_path", "TEXT", 1, 0),
    ("file_sha256", "TEXT", 1, 0),
    ("source_sha", "TEXT", 0, 0),
    ("manifest_sha256", "TEXT", 0, 0),
    ("manifest_hash_kind", "TEXT", 0, 0),
    ("qualification", "TEXT", 1, 0),
)
_POINTER_DDL = (
    f"CREATE TABLE {ARTIFACT_TABLE} ("
    "artifact_id TEXT PRIMARY KEY NOT NULL, "
    "kind TEXT NOT NULL CHECK (kind IN ('report-json', 'report-html', 'scores-json', 'run-manifest')), "
    "resolved_path TEXT NOT NULL, "
    "file_sha256 TEXT NOT NULL, "
    "source_sha TEXT, "
    "manifest_sha256 TEXT, "
    "manifest_hash_kind TEXT CHECK (manifest_hash_kind IN ('raw-sha256', 'legacy-model-dump-sha256')), "
    "qualification TEXT NOT NULL DEFAULT 'unqualified' CHECK (qualification IN ('unqualified', 'partial')), "
    "CHECK ((manifest_sha256 IS NULL) = (manifest_hash_kind IS NULL)))"
)
_SELECT_POINTER = (
    "SELECT artifact_id, kind, resolved_path, file_sha256, source_sha, manifest_sha256, "
    f"manifest_hash_kind, qualification FROM {ARTIFACT_TABLE}"
)
_BUSY = "evidence DB is locked by another writer; retry later"
_ID_INVALID = "artifact ID must be 1-128 ASCII letters, digits, '.', '_' or '-', starting with a letter or digit"
_KIND_INVALID = "artifact kind must be report-json, report-html, scores-json, or run-manifest"
_SOURCE_INVALID = "source SHA must be 40 lowercase hex digits"
_MANIFEST_PAIR = "--manifest-sha and --manifest-hash-kind must be given together"
_MANIFEST_INVALID = "manifest SHA must be 64 lowercase hex digits"
_HASH_KIND_INVALID = "manifest hash kind must be raw-sha256 or legacy-model-dump-sha256"
_QUALIFICATION_INVALID = "qualification must be unqualified or partial"
_NOT_REGISTERED = "artifact ID is not registered in the evidence DB"
_CONFLICT = "artifact ID is already registered with different metadata; refusing to overwrite"
_TABLE_SHAPE = "evidence DB artifact pointer table has an unsupported shape"
_ROW_MALFORMED = "evidence DB artifact pointer row is malformed"
_MISSING = "artifact file is missing"
_CHANGED = "artifact changed since registration"
_NOT_REGULAR = "artifact must be a regular file"
_TOO_LARGE = "artifact exceeds the 256 MiB size bound"
_KIND_MISMATCH = "artifact extension does not match its kind"
_BINARY = "artifact is an image or database file, not a report"
_MUTATED = "artifact changed while it was being hashed"
_UNREADABLE_FILE = "artifact file is unreadable"
_PATH_INVALID = "artifact path is invalid"


class EvidenceError(ValueError):
    """Fixed-text refusal. ``state`` is ``missing`` or ``changed`` when the artifact file itself is the cause."""

    def __init__(self, message: str, *, state: str | None = None):
        super().__init__(message)
        self.state = state


@dataclasses.dataclass(frozen=True)
class _Pointer:
    artifact_id: str
    kind: str
    path: str
    file_sha256: str
    source_sha: str | None
    manifest_sha256: str | None
    manifest_hash_kind: str | None
    qualification: str

    def public(self) -> dict:
        """Safe metadata only: no stored path and no file contents."""
        return {
            "artifact_id": self.artifact_id,
            "file_sha256": self.file_sha256,
            "kind": self.kind,
            "manifest_hash_kind": self.manifest_hash_kind,
            "manifest_sha256": self.manifest_sha256,
            "qualification": self.qualification,
            "source_sha": self.source_sha,
        }


@dataclasses.dataclass(frozen=True)
class _Artifact:
    path: str
    sha256: str


# --- request validation ------------------------------------------------------------------------


def _is_sha(value: object, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _check_id(artifact_id: object) -> str:
    if not isinstance(artifact_id, str) or _ID_RE.fullmatch(artifact_id) is None:
        raise EvidenceError(_ID_INVALID)
    return artifact_id


def _check_request(
    artifact_id: str,
    kind: str,
    source_sha: str | None,
    manifest_sha256: str | None,
    manifest_hash_kind: str | None,
    qualification: str,
) -> None:
    _check_id(artifact_id)
    if kind not in KINDS:
        raise EvidenceError(_KIND_INVALID)
    if source_sha is not None and not _is_sha(source_sha, _SHA40_RE):
        raise EvidenceError(_SOURCE_INVALID)
    if (manifest_sha256 is None) != (manifest_hash_kind is None):
        raise EvidenceError(_MANIFEST_PAIR)
    if manifest_sha256 is not None and not _is_sha(manifest_sha256, _SHA64_RE):
        raise EvidenceError(_MANIFEST_INVALID)
    if manifest_hash_kind is not None and manifest_hash_kind not in HASH_KINDS:
        raise EvidenceError(_HASH_KIND_INVALID)
    if qualification not in QUALIFICATIONS:
        raise EvidenceError(_QUALIFICATION_INVALID)


# --- evidence DB access (reuses the corpus_catalog v0 helpers; never creates a DB) -------------


@contextlib.contextmanager
def _guard():
    """Map catalog and sqlite failures to fixed text, so no SQL values or private paths reach stderr."""
    try:
        yield
    except cc.CatalogError as exc:
        raise EvidenceError(str(exc)) from None
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc) or "busy" in str(exc):
            raise EvidenceError(_BUSY) from None
        raise EvidenceError(cc._EVIDENCE_UNREADABLE) from None
    except sqlite3.Error:
        raise EvidenceError(cc._EVIDENCE_UNREADABLE) from None


def _db_path(db: Path) -> Path:
    try:
        return cc._evidence_path(Path(db))
    except cc.CatalogError as exc:
        raise EvidenceError(str(exc)) from None


def _connect(path: Path, mode: str) -> sqlite3.Connection:
    """``mode`` is ``ro`` or ``rw``. Never ``rwc``: SQLite refuses an absent file instead of creating it."""
    try:
        return sqlite3.connect(
            f"{path.as_uri()}?mode={mode}", uri=True, timeout=cc.EVIDENCE_BUSY_TIMEOUT_S, isolation_level=None
        )
    except sqlite3.Error:
        raise EvidenceError(cc._EVIDENCE_UNREADABLE) from None


def _private_directory(directory: Path) -> None:
    """Refuse an open DB directory without chmodding it, as ``db-import`` does."""
    try:
        mode = stat.S_IMODE(directory.stat().st_mode)
    except OSError:
        raise EvidenceError(cc._EVIDENCE_UNREADABLE) from None
    if mode & 0o077:
        raise EvidenceError(cc._EVIDENCE_DIR_OPEN)


@contextlib.contextmanager
def _read_only(db: Path):
    path = _db_path(db)
    if not path.is_file():
        raise EvidenceError(cc._EVIDENCE_UNREADABLE)
    conn = _connect(path, "ro")
    try:
        # The guard also covers the caller's queries, so a corrupt page never escapes as a traceback.
        with _guard():
            cc._evidence_pragmas(conn)
            cc._evidence_check_schema(conn)
            _check_table_shape_if_present(conn)
            yield conn
    finally:
        conn.close()


def _table_present(conn: sqlite3.Connection) -> bool:
    found = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (ARTIFACT_TABLE,))
    return found.fetchone() is not None


def _check_table_shape_if_present(conn: sqlite3.Connection) -> None:
    if not _table_present(conn):
        return
    # Parameterized table-valued pragma: the table name is a constant, never caller input.
    columns = conn.execute(
        'SELECT name, type, "notnull", pk FROM pragma_table_info(?) ORDER BY cid', (ARTIFACT_TABLE,)
    ).fetchall()
    if [tuple(row) for row in columns] != list(_POINTER_COLUMNS):
        raise EvidenceError(_TABLE_SHAPE)


def _pointer_from_row(row: tuple) -> _Pointer:
    artifact_id, kind, path, file_sha256, source_sha, manifest_sha256, manifest_hash_kind, qualification = row
    valid = (
        isinstance(artifact_id, str)
        and _ID_RE.fullmatch(artifact_id) is not None
        and isinstance(kind, str)
        and kind in KINDS
        and isinstance(path, str)
        and "\x00" not in path
        and os.path.isabs(path)
        and Path(path).suffix == KINDS[kind]
        and _is_sha(file_sha256, _SHA64_RE)
        and (source_sha is None or _is_sha(source_sha, _SHA40_RE))
        and (manifest_sha256 is None or _is_sha(manifest_sha256, _SHA64_RE))
        and (manifest_hash_kind is None or manifest_hash_kind in HASH_KINDS)
        and (manifest_sha256 is None) == (manifest_hash_kind is None)
        and qualification in QUALIFICATIONS
    )
    if not valid:
        raise EvidenceError(_ROW_MALFORMED)
    return _Pointer(
        artifact_id, kind, path, file_sha256, source_sha, manifest_sha256, manifest_hash_kind, qualification
    )


def _lookup(conn: sqlite3.Connection, artifact_id: str) -> _Pointer | None:
    if not _table_present(conn):
        return None
    row = conn.execute(f"{_SELECT_POINTER} WHERE artifact_id = ?", (artifact_id,)).fetchone()
    return None if row is None else _pointer_from_row(row)


# --- artifact fingerprint: one bounded, identity-checked read of a regular file -------------------


def _identity(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _fingerprint(raw: Path, kind: str) -> _Artifact:
    """Stream one regular file through SHA-256. Refuses swaps, FIFOs, devices, and mutation during hashing."""
    try:
        resolved = os.path.realpath(os.path.abspath(raw))
    except ValueError:
        raise EvidenceError(_PATH_INVALID) from None
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(resolved, flags)
    except (FileNotFoundError, NotADirectoryError):
        raise EvidenceError(_MISSING, state="missing") from None
    except OSError:
        raise EvidenceError(_UNREADABLE_FILE) from None
    try:
        return _hash_open_file(fd, resolved, kind)
    finally:
        os.close(fd)


def _hash_open_file(fd: int, resolved: str, kind: str) -> _Artifact:
    # Raw fd reads only: a buffered open of a directory raises before any stat check could refuse it.
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise EvidenceError(_NOT_REGULAR, state="changed")
        linked = os.stat(resolved, follow_symlinks=False)
        if (linked.st_dev, linked.st_ino) != (before.st_dev, before.st_ino):
            raise EvidenceError(_CHANGED, state="changed")
        if before.st_size > MAX_ARTIFACT_BYTES:
            raise EvidenceError(_TOO_LARGE, state="changed")
        digest = hashlib.sha256()
        head = b""
        total = 0
        while chunk := os.read(fd, READ_CHUNK):
            if total == 0:
                head = chunk[:16]
            total += len(chunk)
            if total > MAX_ARTIFACT_BYTES:
                raise EvidenceError(_TOO_LARGE, state="changed")
            digest.update(chunk)
        after = os.fstat(fd)
    except FileNotFoundError:
        raise EvidenceError(_CHANGED, state="changed") from None
    except OSError:
        raise EvidenceError(_UNREADABLE_FILE) from None
    if _identity(after) != _identity(before) or total != before.st_size:
        raise EvidenceError(_MUTATED, state="changed")
    try:
        linked_after = os.stat(resolved, follow_symlinks=False)
    except (FileNotFoundError, NotADirectoryError):
        raise EvidenceError(_CHANGED, state="changed") from None
    except OSError:
        raise EvidenceError(_UNREADABLE_FILE) from None
    if not stat.S_ISREG(linked_after.st_mode) or _identity(linked_after) != _identity(after):
        raise EvidenceError(_CHANGED, state="changed")
    if Path(resolved).suffix != KINDS[kind]:
        raise EvidenceError(_KIND_MISMATCH, state="changed")
    if head.startswith(_BINARY_PREFIXES) or (head[:4] == b"RIFF" and head[8:12] == b"WEBP"):
        raise EvidenceError(_BINARY, state="changed")
    return _Artifact(resolved, digest.hexdigest())


def _observe(pointer: _Pointer) -> tuple[str, str | None]:
    """Return (matched|missing|changed, observed SHA-256 or None). Unreadable files stay errors."""
    try:
        artifact = _fingerprint(Path(pointer.path), pointer.kind)
    except EvidenceError as exc:
        if exc.state is None:
            raise
        return exc.state, None
    if artifact.sha256 != pointer.file_sha256:
        return "changed", artifact.sha256
    return "matched", artifact.sha256


# --- public operations ---------------------------------------------------------------------------


def register_artifact(
    db: Path,
    artifact_id: str,
    *,
    kind: str,
    path: Path,
    source_sha: str | None = None,
    manifest_sha256: str | None = None,
    manifest_hash_kind: str | None = None,
    qualification: str = "unqualified",
) -> dict:
    """Record a pointer. Returns status ``registered`` or ``already_registered``; a changed row is refused."""
    _check_request(artifact_id, kind, source_sha, manifest_sha256, manifest_hash_kind, qualification)
    db_path = _db_path(db)
    if not db_path.is_file():
        raise EvidenceError(cc._EVIDENCE_UNREADABLE)
    _private_directory(db_path.parent)
    artifact = _fingerprint(path, kind)
    wanted = _Pointer(
        artifact_id,
        kind,
        artifact.path,
        artifact.sha256,
        source_sha,
        manifest_sha256,
        manifest_hash_kind,
        qualification,
    )
    status = _write_pointer(db_path, wanted)
    return {**wanted.public(), "status": status}


def _write_pointer(db_path: Path, wanted: _Pointer) -> str:
    conn = _connect(db_path, "rw")
    try:
        with _guard():
            cc._evidence_pragmas(conn)
            # DATA-17: decide table creation and the duplicate check only while holding the writer lock.
            conn.execute("BEGIN IMMEDIATE")
            try:
                cc._evidence_check_schema(conn)
                _check_table_shape_if_present(conn)
                if not _table_present(conn):
                    conn.execute(_POINTER_DDL)
                stored = _lookup(conn, wanted.artifact_id)
                if stored is None:
                    conn.execute(
                        f"INSERT INTO {ARTIFACT_TABLE} (artifact_id, kind, resolved_path, file_sha256, source_sha, "
                        "manifest_sha256, manifest_hash_kind, qualification) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            wanted.artifact_id,
                            wanted.kind,
                            wanted.path,
                            wanted.file_sha256,
                            wanted.source_sha,
                            wanted.manifest_sha256,
                            wanted.manifest_hash_kind,
                            wanted.qualification,
                        ),
                    )
                    status = "registered"
                elif stored == wanted:
                    status = "already_registered"
                else:
                    raise EvidenceError(_CONFLICT)
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
    finally:
        conn.close()
    return status


def preflight_artifact(db: Path, artifact_id: str) -> None:
    """Check ID, DB, schema, and writability before a producer writes. Holds the writer lock only briefly."""
    _check_id(artifact_id)
    db_path = _db_path(db)
    if not db_path.is_file():
        raise EvidenceError(cc._EVIDENCE_UNREADABLE)
    _private_directory(db_path.parent)
    conn = _connect(db_path, "rw")
    try:
        with _guard():
            cc._evidence_pragmas(conn)
            conn.execute("BEGIN IMMEDIATE")
            try:
                cc._evidence_check_schema(conn)
                _check_table_shape_if_present(conn)
            finally:
                conn.execute("ROLLBACK")
    finally:
        conn.close()


def show_artifact(db: Path, artifact_id: str) -> dict:
    _check_id(artifact_id)
    with _read_only(db) as conn:
        pointer = _lookup(conn, artifact_id)
    if pointer is None:
        raise EvidenceError(_NOT_REGISTERED)
    return pointer.public()


def list_artifacts(db: Path, *, limit: int = DEFAULT_LIMIT) -> dict:
    if not 1 <= limit <= MAX_LIMIT:
        raise EvidenceError(f"list limit must be between 1 and {MAX_LIMIT}")
    with _read_only(db) as conn:
        if not _table_present(conn):
            return {"artifacts": []}
        rows = conn.execute(f"{_SELECT_POINTER} ORDER BY artifact_id LIMIT ?", (limit,)).fetchall()
        return {"artifacts": [_pointer_from_row(row).public() for row in rows]}


def check_artifact(db: Path, artifact_id: str) -> dict:
    _check_id(artifact_id)
    with _read_only(db) as conn:
        pointer = _lookup(conn, artifact_id)
    if pointer is None:
        raise EvidenceError(_NOT_REGISTERED)
    state, observed = _observe(pointer)
    return {
        "artifact_id": artifact_id,
        "file_sha256": pointer.file_sha256,
        "observed_sha256": observed,
        "status": state,
    }


def resolve_artifact(db: Path, artifact_id: str) -> str:
    """Verified local absolute path. Missing or stale artifacts refuse; a stale path is never printed."""
    _check_id(artifact_id)
    with _read_only(db) as conn:
        pointer = _lookup(conn, artifact_id)
    if pointer is None:
        raise EvidenceError(_NOT_REGISTERED)
    state, _ = _observe(pointer)
    if state == "missing":
        raise EvidenceError(_MISSING, state="missing")
    if state == "changed":
        raise EvidenceError(_CHANGED, state="changed")
    return pointer.path


# --- CLI ----------------------------------------------------------------------------------------


def _limit(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        number = 0
    if not 1 <= number <= MAX_LIMIT:
        raise argparse.ArgumentTypeError(f"--limit must be between 1 and {MAX_LIMIT}")
    return number


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.eval_harness.firbench_evidence")
    commands = parser.add_subparsers(dest="command", required=True)
    register = commands.add_parser("register", help="record a pointer to one report or score file")
    register.add_argument("artifact_id")
    register.add_argument("--evidence-db", type=Path, required=True)
    register.add_argument("--kind", required=True, choices=tuple(KINDS))
    register.add_argument("--path", type=Path, required=True)
    register.add_argument("--source-sha", default=None)
    register.add_argument("--manifest-sha", default=None)
    register.add_argument("--manifest-hash-kind", choices=HASH_KINDS, default=None)
    register.add_argument("--qualification", choices=QUALIFICATIONS, default="unqualified")
    for name, summary in (
        ("show", "print safe metadata for one pointer"),
        ("check", "rehash the pointed file and print matched, missing, or changed"),
        ("resolve", "print the verified local absolute path (operator use only)"),
    ):
        sub = commands.add_parser(name, help=summary)
        sub.add_argument("artifact_id")
        sub.add_argument("--evidence-db", type=Path, required=True)
    listing = commands.add_parser("list", help="print safe metadata for registered pointers")
    listing.add_argument("--evidence-db", type=Path, required=True)
    listing.add_argument("--limit", type=_limit, default=DEFAULT_LIMIT)
    return parser


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "register":
            _emit(
                register_artifact(
                    args.evidence_db,
                    args.artifact_id,
                    kind=args.kind,
                    path=args.path,
                    source_sha=args.source_sha,
                    manifest_sha256=args.manifest_sha,
                    manifest_hash_kind=args.manifest_hash_kind,
                    qualification=args.qualification,
                )
            )
        elif args.command == "show":
            _emit(show_artifact(args.evidence_db, args.artifact_id))
        elif args.command == "list":
            _emit(list_artifacts(args.evidence_db, limit=args.limit))
        elif args.command == "check":
            payload = check_artifact(args.evidence_db, args.artifact_id)
            _emit(payload)
            return 0 if payload["status"] == "matched" else 1
        else:
            sys.stdout.write(resolve_artifact(args.evidence_db, args.artifact_id) + "\n")
    except EvidenceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1 if args.command == "resolve" and exc.state is not None else 2
    except (OSError, sqlite3.Error):
        print("error: evidence artifact could not be read", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
