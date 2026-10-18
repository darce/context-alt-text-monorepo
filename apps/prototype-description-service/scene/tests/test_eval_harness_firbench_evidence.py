"""Benchmark CLI contract for the FIRBENCH-1 evidence artifact pointers (E1).

Every fixture is synthetic. The evidence DB and the artifact files live in a fresh directory under
``EVIDENCE_SCRATCH`` (/var/tmp), outside every Git-marked ancestor (``/tmp`` holds a stray ``.git``
on this host). Hashes use ``hashlib`` as the oracle. Most assertions drive the real CLI in a
subprocess. In-process tests import the modules only inside test bodies, so collection never
depends on them.

The report tests replace ``report_run`` with a wiring-only stub that returns the same shape as
``firbench_report.render_report``: an absolute ``target / "index.html"`` Path. They prove the
registration wiring and nothing about the renderer. The native end-to-end report fixture in
``test_eval_harness_firbench_cli_report_integration.py`` is not usable here, because its run step
names a decision manifest outside this checkout.
"""

from __future__ import annotations

import contextlib
import hashlib
import itertools
import json
import multiprocessing as mp
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[2]
# /tmp holds an empty stray .git directory on this host, so an evidence DB there is refused as inside a
# Git-marked ancestor. /var/tmp has no .git ancestor.
EVIDENCE_SCRATCH = Path("/var/tmp")
ARTIFACT_ID = "synthetic-report-1"
REPORT_BYTES = b'{"synthetic": true}\n'
PRIVATE_TOKEN = "private-token-b7e1"
CORPUS_ID = "synthetic-corpus"
MANIFEST_BYTES = b'{"synthetic": "manifest"}\n'
UNREADABLE = "evidence DB is missing, unreadable, or not a version-1 evidence DB"
BUSY = "evidence DB is locked by another writer; retry later"
ID_INVALID = "artifact ID must be 1-128 ASCII letters, digits, '.', '_' or '-', starting with a letter or digit"
NOT_REGISTERED = "artifact ID is not registered in the evidence DB"
CONFLICT = "artifact ID is already registered with different metadata; refusing to overwrite"
ROW_MALFORMED = "evidence DB artifact pointer row is malformed"
TABLE_SHAPE = "evidence DB artifact pointer table has an unsupported shape"
MISSING = "artifact file is missing"
CHANGED = "artifact changed since registration"
NOT_REGULAR = "artifact must be a regular file"
KIND_MISMATCH = "artifact extension does not match its kind"
BINARY = "artifact is an image or database file, not a report"
UNREADABLE_FILE = "artifact file is unreadable"
SHA_A = "a" * 64
SHA_B = "b" * 64


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


MANIFEST_ROW = (CORPUS_ID, _sha(MANIFEST_BYTES), MANIFEST_BYTES)


def _fe():
    from scripts.eval_harness import firbench_evidence

    return firbench_evidence


def _cli():
    from scripts.eval_harness import firbench_cli

    return firbench_cli


def _run_module(module: str, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in ("ACX_EVAL_BENCH", "GOLDEN_IMAGES_DIR")}
    env["PYTHONPATH"] = str(APP_DIR)
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def _run_firbench(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return _run_module("scripts.eval_harness.firbench_cli", *args, cwd=cwd)


def _evidence_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """The benchmark entry point, which is the path operators use."""
    return _run_firbench("evidence", *args, cwd=cwd)


def _command_args(command: str, db: Path, artifact: Path, artifact_id: str = ARTIFACT_ID) -> tuple[str, ...]:
    if command == "register":
        return ("register", artifact_id, "--evidence-db", str(db), "--kind", "report-json", "--path", str(artifact))
    if command == "list":
        return ("list", "--evidence-db", str(db))
    return (command, artifact_id, "--evidence-db", str(db))


def _register(
    db: Path, artifact_id: str, path: Path, *, cwd: Path, kind: str = "report-json", extra: tuple[str, ...] = ()
) -> subprocess.CompletedProcess[str]:
    return _evidence_cli(
        "register", artifact_id, "--evidence-db", str(db), "--kind", kind, "--path", str(path), *extra, cwd=cwd
    )


@pytest.fixture
def scratch():
    """Fresh 0700 directory under /var/tmp for one DB and its synthetic artifacts."""
    root = Path(tempfile.mkdtemp(prefix="fb1-e1-evidence-", dir=EVIDENCE_SCRATCH))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _make_v0_db(db: Path) -> None:
    """The corpus_catalog v0 store as it exists today: 0600, user_version 1, one pinned manifest row."""
    os.close(os.open(db, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    with contextlib.closing(sqlite3.connect(db, isolation_level=None)) as conn:
        conn.execute(
            "CREATE TABLE corpus_manifest (corpus_id TEXT PRIMARY KEY NOT NULL, "
            "manifest_sha256 TEXT NOT NULL, manifest_bytes BLOB NOT NULL)"
        )
        conn.execute("PRAGMA user_version = 1")
        conn.execute("INSERT INTO corpus_manifest VALUES (?, ?, ?)", MANIFEST_ROW)


def _v0_db(root: Path, name: str = "evidence.sqlite3") -> Path:
    db = root / name
    _make_v0_db(db)
    return db


def _artifact(root: Path, name: str, data: bytes = REPORT_BYTES) -> Path:
    directory = root / "artifacts"
    directory.mkdir(exist_ok=True)
    path = directory / name
    path.write_bytes(data)
    return path


def _readonly(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)


def _db_sha(db: Path) -> str:
    return _sha(db.read_bytes())


def _pointers(db: Path) -> list[tuple]:
    with contextlib.closing(_readonly(db)) as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'artifact_pointer_v1'").fetchone() is None:
            return []
        return conn.execute(
            "SELECT artifact_id, kind, resolved_path, file_sha256, source_sha, manifest_sha256, "
            "manifest_hash_kind, qualification FROM artifact_pointer_v1 ORDER BY artifact_id"
        ).fetchall()


def _v0_state(db: Path) -> tuple:
    with contextlib.closing(_readonly(db)) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()
        rows = conn.execute("SELECT corpus_id, manifest_sha256, manifest_bytes FROM corpus_manifest").fetchall()
    return version, rows


def _assert_no_leaks(result: subprocess.CompletedProcess[str]) -> None:
    text = result.stdout + result.stderr
    for canary in (PRIVATE_TOKEN, "SELECT", "INSERT", "sqlite_master", "artifact_pointer_v1", "Traceback"):
        assert canary not in text, f"output leaked {canary!r}"


def test_benchmark_cli_routes_evidence_register_show_and_list_to_the_pointer_module(scratch):
    db = scratch / "evidence.sqlite3"
    _make_v0_db(db)
    report = scratch / "artifacts" / "report.json"
    report.parent.mkdir()
    report.write_bytes(REPORT_BYTES)

    registered = _run_firbench(
        "evidence",
        "register",
        ARTIFACT_ID,
        "--evidence-db",
        str(db),
        "--kind",
        "report-json",
        "--path",
        str(report),
        cwd=scratch,
    )
    assert registered.returncode == 0, registered.stderr

    shown = _run_firbench("evidence", "show", ARTIFACT_ID, "--evidence-db", str(db), cwd=scratch)
    assert shown.returncode == 0, shown.stderr
    assert _sha(REPORT_BYTES) in shown.stdout
    assert str(report) not in shown.stdout

    listed = _run_firbench("evidence", "list", "--evidence-db", str(db), cwd=scratch)
    assert listed.returncode == 0, listed.stderr
    assert ARTIFACT_ID in listed.stdout

    with contextlib.closing(sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone() == (1,)
        assert conn.execute("SELECT corpus_id, manifest_sha256, manifest_bytes FROM corpus_manifest").fetchall() == [
            MANIFEST_ROW
        ]


# --- the v0 store stays the same store ---------------------------------------------------------


def test_v0_db_stays_readable_and_unchanged_after_registration(scratch):
    db = _v0_db(scratch)
    artifact = _artifact(scratch, "report.json")
    before = _v0_state(db)
    assert _register(db, ARTIFACT_ID, artifact, cwd=scratch).returncode == 0
    assert _v0_state(db) == before
    from scripts.eval_harness import corpus_catalog as cc

    # The catalog reader still accepts the DB, which now also holds the additive pointer table.
    assert cc.read_evidence_manifest(db, CORPUS_ID, expected_sha256=_sha(MANIFEST_BYTES)) == MANIFEST_BYTES
    assert [row[0] for row in _pointers(db)] == [ARTIFACT_ID]


@pytest.mark.parametrize("command", ["register", "show", "check", "resolve", "list"])
def test_missing_db_is_never_created_by_any_command(scratch, command):
    absent_dir = scratch / "absent"
    db = absent_dir / "evidence.sqlite3"
    artifact = _artifact(scratch, "report.json")
    result = _evidence_cli(*_command_args(command, db, artifact), cwd=scratch)
    assert result.returncode == 2
    assert result.stderr == f"error: {UNREADABLE}\n"
    assert not absent_dir.exists()


def test_absent_pointer_table_lists_empty_and_refuses_lookups(scratch):
    db = _v0_db(scratch)
    before = _db_sha(db)
    listed = _evidence_cli("list", "--evidence-db", str(db), cwd=scratch)
    assert listed.returncode == 0, listed.stderr
    assert json.loads(listed.stdout) == {"artifacts": []}
    for command in ("show", "check", "resolve"):
        result = _evidence_cli(command, ARTIFACT_ID, "--evidence-db", str(db), cwd=scratch)
        assert result.returncode == 2
        assert result.stderr == f"error: {NOT_REGISTERED}\n"
    assert _db_sha(db) == before


def test_read_commands_never_mutate_the_db(scratch):
    db = _v0_db(scratch)
    artifact = _artifact(scratch, "report.json")
    assert _register(db, ARTIFACT_ID, artifact, cwd=scratch).returncode == 0
    before = _db_sha(db)
    for command in ("show", "check", "resolve", "list"):
        result = _evidence_cli(*_command_args(command, db, artifact), cwd=scratch)
        assert result.returncode == 0, result.stderr
    assert _db_sha(db) == before
    assert not list(scratch.glob("*-journal"))


# --- idempotence and ID conflicts ---------------------------------------------------------------


def test_identical_reregistration_is_already_registered_and_writes_nothing(scratch):
    db = _v0_db(scratch)
    artifact = _artifact(scratch, "report.json")
    first = _register(db, ARTIFACT_ID, artifact, cwd=scratch)
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["status"] == "registered"
    before = _db_sha(db)
    again = _register(db, ARTIFACT_ID, artifact, cwd=scratch)
    assert again.returncode == 0, again.stderr
    assert json.loads(again.stdout)["status"] == "already_registered"
    assert _db_sha(db) == before


@pytest.mark.parametrize("variant", ["other-path", "source", "qualification", "manifest", "kind"])
def test_conflicting_metadata_for_the_same_id_is_refused_without_overwrite(scratch, variant):
    db = _v0_db(scratch)
    artifact = _artifact(scratch, "report.json")
    assert _register(db, ARTIFACT_ID, artifact, cwd=scratch).returncode == 0
    before_rows = _pointers(db)
    kind, path, extra = "report-json", artifact, ()
    if variant == "other-path":
        path = _artifact(scratch, "copy.json")
    elif variant == "source":
        extra = ("--source-sha", "c" * 40)
    elif variant == "qualification":
        extra = ("--qualification", "partial")
    elif variant == "manifest":
        extra = ("--manifest-sha", SHA_B, "--manifest-hash-kind", "raw-sha256")
    else:
        kind = "scores-json"
    before = _db_sha(db)
    refused = _register(db, ARTIFACT_ID, path, cwd=scratch, kind=kind, extra=extra)
    assert refused.returncode == 2
    assert refused.stderr == f"error: {CONFLICT}\n"
    assert _db_sha(db) == before
    assert _pointers(db) == before_rows


# --- changed, missing, and unreadable files -----------------------------------------------------


def test_check_reports_matched_then_changed_and_reregistration_is_refused(scratch):
    db = _v0_db(scratch)
    artifact = _artifact(scratch, "report.json")
    assert _register(db, ARTIFACT_ID, artifact, cwd=scratch).returncode == 0
    matched = _evidence_cli("check", ARTIFACT_ID, "--evidence-db", str(db), cwd=scratch)
    assert matched.returncode == 0, matched.stderr
    assert json.loads(matched.stdout)["status"] == "matched"

    artifact.write_bytes(b'{"synthetic": "changed"}\n')
    changed = _evidence_cli("check", ARTIFACT_ID, "--evidence-db", str(db), cwd=scratch)
    assert changed.returncode == 1
    payload = json.loads(changed.stdout)
    assert payload["status"] == "changed"
    assert payload["observed_sha256"] == _sha(b'{"synthetic": "changed"}\n')
    assert payload["file_sha256"] == _sha(REPORT_BYTES)

    rewrite = _register(db, ARTIFACT_ID, artifact, cwd=scratch)
    assert rewrite.returncode == 2
    assert rewrite.stderr == f"error: {CONFLICT}\n"
    fresh = _register(db, "synthetic-report-2", artifact, cwd=scratch)
    assert fresh.returncode == 0, fresh.stderr
    stale = _evidence_cli("resolve", ARTIFACT_ID, "--evidence-db", str(db), cwd=scratch)
    assert stale.returncode == 1
    assert stale.stdout == ""
    assert stale.stderr == f"error: {CHANGED}\n"


def test_missing_file_is_reported_missing_and_resolve_refuses(scratch):
    db = _v0_db(scratch)
    artifact = _artifact(scratch, "report.json")
    assert _register(db, ARTIFACT_ID, artifact, cwd=scratch).returncode == 0
    artifact.unlink()
    checked = _evidence_cli("check", ARTIFACT_ID, "--evidence-db", str(db), cwd=scratch)
    assert checked.returncode == 1
    assert json.loads(checked.stdout)["status"] == "missing"
    assert json.loads(checked.stdout)["observed_sha256"] is None
    resolved = _evidence_cli("resolve", ARTIFACT_ID, "--evidence-db", str(db), cwd=scratch)
    assert resolved.returncode == 1
    assert resolved.stdout == ""
    assert resolved.stderr == f"error: {MISSING}\n"
    gone = _register(db, "absent-report", scratch / "artifacts" / "absent.json", cwd=scratch)
    assert gone.returncode == 2
    assert gone.stderr == f"error: {MISSING}\n"


def test_unreadable_file_is_a_controlled_refusal(scratch):
    if os.geteuid() == 0:
        pytest.skip("root reads mode-000 files; the unreadable branch needs a non-root reader")
    db = _v0_db(scratch)
    artifact = _artifact(scratch, "report.json")
    assert _register(db, ARTIFACT_ID, artifact, cwd=scratch).returncode == 0
    os.chmod(artifact, 0)
    checked = _evidence_cli("check", ARTIFACT_ID, "--evidence-db", str(db), cwd=scratch)
    assert checked.returncode == 2
    assert checked.stderr == f"error: {UNREADABLE_FILE}\n"
    refused = _register(db, "unreadable-report", artifact, cwd=scratch)
    assert refused.returncode == 2
    assert refused.stderr == f"error: {UNREADABLE_FILE}\n"


REFUSED_INPUTS = {
    "html-named-for-json": ("report.html", REPORT_BYTES, "report-json", KIND_MISMATCH),
    "json-named-for-html": ("report.json", REPORT_BYTES, "report-html", KIND_MISMATCH),
    "png-named-json": ("report.json", b"\x89PNG\r\n\x1a\n" + b"synthetic", "report-json", BINARY),
    "jpeg-named-json": ("report.json", b"\xff\xd8\xff\xe0synthetic", "report-json", BINARY),
    "sqlite-named-json": ("report.json", b"SQLite format 3\x00" + bytes(84), "report-json", BINARY),
    "directory-named-json": ("dir.json", None, "report-json", NOT_REGULAR),
    "absent": ("absent.json", None, "report-json", MISSING),
}


@pytest.mark.parametrize("case", list(REFUSED_INPUTS))
def test_wrong_kind_image_database_directory_and_absent_inputs_are_refused(scratch, case):
    name, data, kind, message = REFUSED_INPUTS[case]
    db = _v0_db(scratch)
    before = _db_sha(db)
    if data is None:
        target = scratch / "artifacts" / name
        target.parent.mkdir(exist_ok=True)
        if case == "directory-named-json":
            target.mkdir()
    else:
        target = _artifact(scratch, name, data)
    result = _register(db, "refused-input", target, cwd=scratch, kind=kind)
    assert result.returncode == 2
    assert result.stderr == f"error: {message}\n"
    assert _db_sha(db) == before
    assert _pointers(db) == []


def test_fifo_is_refused_without_blocking_and_a_swapped_fifo_is_changed(scratch):
    db = _v0_db(scratch)
    artifact = _artifact(scratch, "report.json")
    assert _register(db, ARTIFACT_ID, artifact, cwd=scratch).returncode == 0
    started = time.monotonic()
    fifo = scratch / "artifacts" / "fifo.json"
    os.mkfifo(fifo)
    refused = _register(db, "fifo-report", fifo, cwd=scratch)
    assert refused.returncode == 2
    assert refused.stderr == f"error: {NOT_REGULAR}\n"
    artifact.unlink()
    os.mkfifo(artifact)
    checked = _evidence_cli("check", ARTIFACT_ID, "--evidence-db", str(db), cwd=scratch)
    assert checked.returncode == 1
    assert json.loads(checked.stdout)["status"] == "changed"
    assert time.monotonic() - started < 60


def test_symlink_is_stored_as_its_resolved_regular_file(scratch):
    db = _v0_db(scratch)
    real = _artifact(scratch, "report.json")
    link = scratch / "artifacts" / "link.json"
    link.symlink_to(real)
    assert _register(db, ARTIFACT_ID, link, cwd=scratch).returncode == 0
    resolved = _evidence_cli("resolve", ARTIFACT_ID, "--evidence-db", str(db), cwd=scratch)
    assert resolved.returncode == 0, resolved.stderr
    assert resolved.stdout == f"{real.resolve()}\n"
    same = _register(db, ARTIFACT_ID, real, cwd=scratch)
    assert same.returncode == 0
    assert json.loads(same.stdout)["status"] == "already_registered"


def test_mutation_during_hashing_is_refused_without_a_row(scratch, monkeypatch):
    fe = _fe()
    db = _v0_db(scratch)
    artifact = _artifact(scratch, "report.json")
    counter = itertools.count()
    # Wiring-only: forces the identity comparison to see a change between the two fstat calls.
    monkeypatch.setattr(fe, "_identity", lambda info: (next(counter),))
    with pytest.raises(fe.EvidenceError, match="changed while it was being hashed"):
        fe.register_artifact(db, ARTIFACT_ID, kind="report-json", path=artifact)
    assert _pointers(db) == []


def test_size_bound_is_checked_before_any_row_is_written(scratch, monkeypatch):
    fe = _fe()
    db = _v0_db(scratch)
    artifact = _artifact(scratch, "report.json")
    monkeypatch.setattr(fe, "MAX_ARTIFACT_BYTES", len(REPORT_BYTES) - 1)
    with pytest.raises(fe.EvidenceError, match="exceeds the 256 MiB size bound"):
        fe.register_artifact(db, ARTIFACT_ID, kind="report-json", path=artifact)
    assert _pointers(db) == []


# --- stored-value and shape refusal -------------------------------------------------------------

_LOOSE_DDL = (
    "CREATE TABLE artifact_pointer_v1 (artifact_id TEXT PRIMARY KEY NOT NULL, kind TEXT NOT NULL, "
    "resolved_path TEXT NOT NULL, file_sha256 TEXT NOT NULL, source_sha TEXT, manifest_sha256 TEXT, "
    "manifest_hash_kind TEXT, qualification TEXT NOT NULL)"
)
DAMAGED_ROWS = {
    "blob-sha": ("pointer", "report-json", "/abs/report.json", b"\x00" * 32, None, None, None, "unqualified"),
    "unknown-kind": ("pointer", "pdf", "/abs/report.json", SHA_A, None, None, None, "unqualified"),
    "relative-path": ("pointer", "report-json", "relative/report.json", SHA_A, None, None, None, "unqualified"),
    "suffix-mismatch": ("pointer", "report-json", "/abs/report.html", SHA_A, None, None, None, "unqualified"),
    "half-manifest": ("pointer", "report-json", "/abs/report.json", SHA_A, None, SHA_B, None, "unqualified"),
    "bad-source": ("pointer", "report-json", "/abs/report.json", SHA_A, "xyz", None, None, "unqualified"),
    "bad-qualification": ("pointer", "report-json", "/abs/report.json", SHA_A, None, None, None, "verified"),
}


@pytest.mark.parametrize("damage", list(DAMAGED_ROWS))
@pytest.mark.parametrize("command", ["show", "check", "resolve", "list", "register"])
def test_malformed_stored_row_is_refused_and_the_db_is_left_intact(scratch, damage, command):
    db = _v0_db(scratch)
    artifact = _artifact(scratch, "report.json")
    with contextlib.closing(sqlite3.connect(db, isolation_level=None)) as conn:
        conn.execute(_LOOSE_DDL)
        conn.execute("INSERT INTO artifact_pointer_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?)", DAMAGED_ROWS[damage])
    before = _db_sha(db)
    result = _evidence_cli(*_command_args(command, db, artifact, artifact_id="pointer"), cwd=scratch)
    assert result.returncode == 2
    assert result.stderr == f"error: {ROW_MALFORMED}\n"
    _assert_no_leaks(result)
    assert _db_sha(db) == before


@pytest.mark.parametrize(
    "shape",
    [
        "extra-column",
        "nullable-qualification",
    ],
)
@pytest.mark.parametrize("command", ["show", "check", "resolve", "list", "register"])
def test_unsupported_pointer_table_shape_is_refused_before_any_write(scratch, shape, command):
    db = _v0_db(scratch)
    artifact = _artifact(scratch, "report.json")
    ddl = _LOOSE_DDL
    if shape == "extra-column":
        ddl = ddl[:-1] + ", note TEXT)"
    else:
        ddl = ddl.replace("qualification TEXT NOT NULL", "qualification TEXT")
    with contextlib.closing(sqlite3.connect(db, isolation_level=None)) as conn:
        conn.execute(ddl)
    before = _db_sha(db)
    result = _evidence_cli(*_command_args(command, db, artifact), cwd=scratch)
    assert result.returncode == 2
    assert result.stderr == f"error: {TABLE_SHAPE}\n"
    assert _db_sha(db) == before


@pytest.mark.parametrize("command", ["register", "show", "check", "resolve", "list"])
def test_corrupt_db_is_refused_with_fixed_text_and_left_intact(scratch, command):
    private = scratch / PRIVATE_TOKEN
    os.mkdir(private, 0o700)
    db = private / "evidence.sqlite3"
    db.write_bytes(b"not a sqlite database\n" * 64)
    os.chmod(db, 0o600)
    before = _db_sha(db)
    artifact = _artifact(scratch, f"{PRIVATE_TOKEN}.json")
    result = _evidence_cli(*_command_args(command, db, artifact), cwd=scratch)
    assert result.returncode == 2
    assert result.stderr == f"error: {UNREADABLE}\n"
    _assert_no_leaks(result)
    assert _db_sha(db) == before


def test_failure_output_carries_no_private_canaries(scratch):
    private = scratch / PRIVATE_TOKEN
    os.mkdir(private, 0o700)
    db = _v0_db(private)
    absent = scratch / "artifacts" / f"{PRIVATE_TOKEN}.json"
    scenarios = [
        ["register", "has/slash", "--evidence-db", str(db), "--kind", "report-json", "--path", str(absent)],
        ["register", "fresh-report", "--evidence-db", str(db), "--kind", "report-json", "--path", str(absent)],
        ["show", "unknown-id", "--evidence-db", str(db)],
        ["check", "unknown-id", "--evidence-db", str(db)],
        ["resolve", "unknown-id", "--evidence-db", str(db)],
    ]
    for args in scenarios:
        result = _evidence_cli(*args, cwd=scratch)
        assert result.returncode == 2, result.stdout + result.stderr
        _assert_no_leaks(result)


def test_uri_reserved_characters_in_the_db_path_are_encoded(scratch):
    private = scratch / "fb1 evidence #?%dir"
    os.mkdir(private, 0o700)
    db = _v0_db(private)
    artifact = _artifact(scratch, "report.json")
    assert _register(db, ARTIFACT_ID, artifact, cwd=scratch).returncode == 0
    shown = _evidence_cli("show", ARTIFACT_ID, "--evidence-db", str(db), cwd=scratch)
    assert shown.returncode == 0, shown.stderr
    assert _sha(REPORT_BYTES) in shown.stdout
    assert [row[0] for row in _pointers(db)] == [ARTIFACT_ID]


@pytest.mark.parametrize("bad_id", ["", ".leading", "has/slash", "a" * 129, "spaced id", "é", "x\n"])
def test_artifact_id_bounds_are_checked_before_the_db_is_opened(scratch, bad_id):
    db = _v0_db(scratch)
    artifact = _artifact(scratch, "report.json")
    before = _db_sha(db)
    result = _register(db, bad_id, artifact, cwd=scratch)
    assert result.returncode == 2
    assert result.stderr == f"error: {ID_INVALID}\n"
    assert _db_sha(db) == before


def test_leading_dash_id_is_refused_by_the_module_rule(scratch):
    # argparse reads a leading dash as an option, so this rule is exercised in-process.
    fe = _fe()
    db = _v0_db(scratch)
    artifact = _artifact(scratch, "report.json")
    with pytest.raises(fe.EvidenceError, match="artifact ID must be 1-128"):
        fe.register_artifact(db, "-leading", kind="report-json", path=artifact)
    assert _pointers(db) == []


@pytest.mark.parametrize("good_id", ["a" * 128, "A.b_c-9"])
def test_artifact_id_accepts_the_public_alphabet_up_to_128_characters(scratch, good_id):
    db = _v0_db(scratch)
    artifact = _artifact(scratch, "report.json")
    result = _register(db, good_id, artifact, cwd=scratch)
    assert result.returncode == 0, result.stderr
    assert [row[0] for row in _pointers(db)] == [good_id]


def test_check_and_resolve_refuse_an_unknown_id_with_exit_two(scratch):
    db = _v0_db(scratch)
    for command in ("show", "check", "resolve"):
        result = _evidence_cli(command, "never-registered", "--evidence-db", str(db), cwd=scratch)
        assert result.returncode == 2
        assert result.stderr == f"error: {NOT_REGISTERED}\n"


def test_resolve_prints_only_the_verified_absolute_path(scratch):
    db = _v0_db(scratch)
    artifact = _artifact(scratch, "report.json")
    assert _register(db, ARTIFACT_ID, artifact, cwd=scratch).returncode == 0
    resolved = _evidence_cli("resolve", ARTIFACT_ID, "--evidence-db", str(db), cwd=scratch)
    assert resolved.returncode == 0, resolved.stderr
    assert resolved.stdout == f"{artifact}\n"
    assert resolved.stderr == ""


# --- list bounds --------------------------------------------------------------------------------


def test_list_defaults_to_100_rows_and_caps_at_1000(scratch):
    fe = _fe()
    db = _v0_db(scratch)
    artifact = _artifact(scratch, "report.json")
    for index in range(101):
        fe.register_artifact(db, f"item-{index:03d}", kind="report-json", path=artifact)
    assert len(fe.list_artifacts(db)["artifacts"]) == 100
    assert len(fe.list_artifacts(db, limit=1000)["artifacts"]) == 101
    assert fe.list_artifacts(db, limit=2)["artifacts"][0]["artifact_id"] == "item-000"


@pytest.mark.parametrize("limit", ["0", "1001", "many"])
def test_list_limit_outside_1_to_1000_is_refused(scratch, limit):
    db = _v0_db(scratch)
    result = _evidence_cli("list", "--evidence-db", str(db), "--limit", limit, cwd=scratch)
    assert result.returncode == 2
    assert "--limit must be between 1 and 1000" in result.stderr


# --- concurrency and lock wait ------------------------------------------------------------------


def _paused_register(db, artifact_id, path, ready, release, result):
    """Stop after fingerprinting, before the registry enters its writer section."""
    from scripts.eval_harness import firbench_evidence as fe

    def schedule(frame, event, arg):
        if event == "call" and frame.f_code is fe._write_pointer.__code__:
            ready.set()
            if not release.wait(15):
                raise RuntimeError("synthetic scheduler timed out")
        return schedule

    sys.settrace(schedule)
    try:
        status = fe.register_artifact(db, artifact_id, kind="report-json", path=path)["status"]
        result.put(("ok", status))
    except fe.EvidenceError as exc:
        result.put(("controlled", str(exc)))
    except BaseException:
        result.put(("unexpected", traceback.format_exc()))
    finally:
        sys.settrace(None)


@pytest.mark.parametrize("fail_first", [False, True], ids=["both-commit", "failed-writer-cleanup"])
def test_first_extension_registration_cannot_erase_a_concurrent_commit(scratch, fail_first):
    db = _v0_db(scratch)
    first_artifact = _artifact(scratch, "first.json", b'{"first": true}\n')
    second_artifact = _artifact(scratch, "second.json", b'{"second": true}\n')
    ctx = mp.get_context("spawn")
    ready, release, result = ctx.Event(), ctx.Event(), ctx.Queue()
    first = ctx.Process(target=_paused_register, args=(db, "first-report", first_artifact, ready, release, result))
    first.start()
    try:
        assert ready.wait(15), "first registration did not reach the writer section"
        second = _register(db, "second-report", second_artifact, cwd=scratch)
        assert second.returncode == 0, second.stderr
        assert json.loads(second.stdout)["status"] == "registered"
        if fail_first:
            # A real SQLite INSERT failure after the other registration has committed.
            with contextlib.closing(sqlite3.connect(db, isolation_level=None)) as conn:
                conn.execute(
                    "CREATE TRIGGER synthetic_failure BEFORE INSERT ON artifact_pointer_v1 "
                    "BEGIN SELECT RAISE(ABORT, 'synthetic-private-failure'); END"
                )
        release.set()
        first.join(15)
        assert not first.is_alive(), "first registration did not finish"
        assert first.exitcode == 0
        outcome = result.get(timeout=5)
        ids = [row[0] for row in _pointers(db)]
        assert "second-report" in ids
        with contextlib.closing(_readonly(db)) as conn:
            assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name = 'artifact_pointer_v1'").fetchone() == (
                1,
            )
        assert _v0_state(db)[0] == (1,)
        if fail_first:
            assert outcome == ("controlled", UNREADABLE)
            assert ids == ["second-report"]
        else:
            assert outcome == ("ok", "registered")
            assert ids == ["first-report", "second-report"]
    finally:
        release.set()
        first.join(2)
        if first.is_alive():
            first.terminate()
            first.join(5)
        result.close()
        result.join_thread()


def test_busy_writer_lock_is_a_finite_controlled_refusal(scratch):
    db = _v0_db(scratch)
    artifact = _artifact(scratch, "report.json")
    holder = sqlite3.connect(db, isolation_level=None)
    try:
        holder.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        result = _register(db, ARTIFACT_ID, artifact, cwd=scratch)
        elapsed = time.monotonic() - started
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert result.returncode == 2
    assert result.stderr == f"error: {BUSY}\n"
    assert elapsed < 60
    assert _pointers(db) == []


# --- benchmark entry and module entry agree -----------------------------------------------------


def test_benchmark_entry_and_module_entry_print_the_same_metadata(scratch):
    db = _v0_db(scratch)
    artifact = _artifact(scratch, "report.json")
    direct_register = _run_module(
        "scripts.eval_harness.firbench_evidence",
        "register",
        ARTIFACT_ID,
        "--evidence-db",
        str(db),
        "--kind",
        "report-json",
        "--path",
        str(artifact),
        cwd=scratch,
    )
    assert direct_register.returncode == 0, direct_register.stderr
    via_bench = _evidence_cli("show", ARTIFACT_ID, "--evidence-db", str(db), cwd=scratch)
    direct = _run_module(
        "scripts.eval_harness.firbench_evidence", "show", ARTIFACT_ID, "--evidence-db", str(db), cwd=scratch
    )
    assert via_bench.returncode == direct.returncode == 0
    assert via_bench.stdout == direct.stdout
    help_text = _evidence_cli("--help", cwd=scratch)
    assert help_text.returncode == 0, help_text.stderr
    assert "register" in help_text.stdout


def test_benchmark_cli_keeps_every_existing_command_and_the_new_report_flags(scratch):
    top = _run_firbench("--help", cwd=scratch)
    assert top.returncode == 0, top.stderr
    for command in ("run", "score", "report", "compare", "unseal", "evidence"):
        assert command in top.stdout
    report = _run_firbench("report", "--help", cwd=scratch)
    assert report.returncode == 0, report.stderr
    assert "--evidence-db" in report.stdout and "--artifact-id" in report.stdout


# --- report wiring (stub producer; the real renderer is not exercised) --------------------------


def _stub_producer(calls: list):
    """Wiring-only stand-in for report_run. Returns the Path shape render_report uses: target / 'index.html'."""

    def render(run_dir, *, include_crops, repo_root):
        calls.append((Path(run_dir), include_crops, Path(repo_root)))
        index = (Path(run_dir) / "report" / "index.html").absolute()
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_bytes(b"<!doctype html><p>synthetic</p>\n")
        return index

    return render


@pytest.mark.parametrize("lone_flag", ["db-only", "id-only"])
def test_report_evidence_flags_must_be_given_together(scratch, lone_flag):
    run = scratch / "run"
    db = _v0_db(scratch)
    if lone_flag == "db-only":
        lone = ["--evidence-db", str(db)]
    else:
        lone = ["--artifact-id", "report-1"]
    result = _run_firbench("report", str(run), *lone, cwd=scratch)
    assert result.returncode == 2
    assert "--evidence-db and --artifact-id must be given together" in result.stderr
    assert not run.exists()


@pytest.mark.parametrize("case", ["bad-id", "missing-db"])
def test_report_refuses_a_bad_registry_before_the_producer_writes(scratch, monkeypatch, capsys, case):
    cli = _cli()

    def producer_must_not_run(*args, **kwargs):
        pytest.fail("the producer ran before the registry was validated")

    monkeypatch.setattr(cli, "report_run", producer_must_not_run)
    run = scratch / "run"
    db = scratch / "absent" / "evidence.sqlite3" if case == "missing-db" else _v0_db(scratch)
    artifact_id = "has/slash" if case == "bad-id" else "report-1"
    code = cli.main(["report", str(run), "--evidence-db", str(db), "--artifact-id", artifact_id])
    assert code == 2
    assert capsys.readouterr().err.startswith("error: ")
    assert not run.exists()


def test_report_registers_the_returned_index_html_as_unqualified(scratch, monkeypatch, capsys):
    fe, cli = _fe(), _cli()
    db = _v0_db(scratch)
    run = scratch / "run"
    calls: list = []
    monkeypatch.setattr(cli, "report_run", _stub_producer(calls))
    assert cli.main(["report", str(run), "--evidence-db", str(db), "--artifact-id", "report-1"]) == 0
    index = run / "report" / "index.html"
    assert capsys.readouterr().out.splitlines() == [str(index), "evidence: registered"]
    assert fe.show_artifact(db, "report-1") == {
        "artifact_id": "report-1",
        "file_sha256": _sha(index.read_bytes()),
        "kind": "report-html",
        "manifest_hash_kind": None,
        "manifest_sha256": None,
        "qualification": "unqualified",
        "source_sha": None,
    }
    assert [row[2] for row in _pointers(db)] == [str(index)]
    assert calls == [(run, False, cli._repo_root())]


def test_report_without_registry_flags_is_unchanged(scratch, monkeypatch, capsys):
    cli = _cli()
    run = scratch / "run"
    calls: list = []
    monkeypatch.setattr(cli, "report_run", _stub_producer(calls))
    assert cli.main(["report", str(run)]) == 0
    assert capsys.readouterr().out == f"{run / 'report' / 'index.html'}\n"
    assert calls == [(run, False, cli._repo_root())]


def test_failed_registration_after_render_keeps_the_report_and_never_reports_success(scratch, monkeypatch, capsys):
    fe, cli = _fe(), _cli()
    db = _v0_db(scratch)
    other = _artifact(scratch, "other.json", b'{"other": true}\n')
    fe.register_artifact(db, "report-1", kind="report-json", path=other)
    run = scratch / "run"
    monkeypatch.setattr(cli, "report_run", _stub_producer([]))
    code = cli.main(["report", str(run), "--evidence-db", str(db), "--artifact-id", "report-1"])
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert captured.err == f"error: report rendered and kept, but evidence registration failed: {CONFLICT}\n"
    index = run / "report" / "index.html"
    assert index.read_bytes() == b"<!doctype html><p>synthetic</p>\n"
    assert [row[0] for row in _pointers(db)] == ["report-1"]
