"""Synthetic real-SQLite and filesystem regressions for the E1 path boundaries."""

from __future__ import annotations

import contextlib
import hashlib
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def registered():
    # Runtime imports keep source import failures separate from collection.
    import test_eval_harness_firbench_evidence as base

    from scripts.eval_harness import corpus_catalog as cc

    root = Path(tempfile.mkdtemp(prefix="fb1-e1-paths-", dir="/var/tmp"))
    try:
        db = root / "evidence.sqlite3"
        assert (
            cc.import_evidence_manifest(
                db, base.CORPUS_ID, base.MANIFEST_BYTES, expected_sha256=base._sha(base.MANIFEST_BYTES)
            )
            == "imported"
        )
        artifact = base._artifact(root, "report.json")
        assert (
            base._fe().register_artifact(db, base.ARTIFACT_ID, kind="report-json", path=artifact)["status"]
            == "registered"
        )
        yield base, root, db, artifact
    finally:
        shutil.rmtree(root)


@pytest.mark.parametrize("command", ["show", "list", "check", "resolve"])
@pytest.mark.parametrize(
    "stored_path",
    [
        "/synthetic\x00.json",
        "/private-token-b7e1/SELECT payload\x00.json",
        "relative/report.json",
        "/synthetic/report.html",
        sqlite3.Binary(b"/synthetic/report.json"),
    ],
    ids=["nul", "nul-canary", "relative", "wrong-suffix", "blob"],
)
def test_malformed_sql_path_is_refused_before_any_reader_exposes_it(registered, command, stored_path):
    base, root, db, artifact = registered
    manifest_before = base._v0_state(db)
    with contextlib.closing(sqlite3.connect(db)) as conn:
        conn.execute("UPDATE artifact_pointer_v1 SET resolved_path=?", (stored_path,))
        conn.commit()
    before = db.read_bytes()

    result = base._evidence_cli(*base._command_args(command, db, artifact), cwd=root)

    assert db.read_bytes() == before
    assert base._v0_state(db) == manifest_before
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == f"error: {base.ROW_MALFORMED}\n"
    base._assert_no_leaks(result)
    for payload in (str(root), "/synthetic", "payload", "embedded null", "ValueError"):
        assert payload not in result.stdout + result.stderr


@pytest.mark.parametrize("absolute", [False, True], ids=["relative", "absolute"])
def test_api_registration_nul_path_is_a_fixed_error_without_db_writes(registered, absolute):
    base, root, db, _ = registered
    fe = base._fe()
    raw = Path("private-token-b7e1-SELECT\x00.json")
    if absolute:
        raw = root / raw
    before = db.read_bytes()

    with pytest.raises(fe.EvidenceError) as caught:
        fe.register_artifact(db, "refused-path", kind="report-json", path=raw)

    assert str(caught.value) == "artifact path is invalid"
    assert caught.value.state is None
    assert caught.value.__suppress_context__
    assert db.read_bytes() == before
    assert len(base._pointers(db)) == 1


@pytest.mark.parametrize("case", ["not-directory", "component-too-long"])
def test_real_filesystem_path_errors_keep_their_existing_classification(registered, case):
    base, root, db, artifact = registered
    fe = base._fe()
    raw = artifact / "child.json" if case == "not-directory" else root / ("x" * 256 + ".json")
    before = hashlib.sha256(db.read_bytes()).hexdigest()

    with pytest.raises(fe.EvidenceError) as caught:
        fe.register_artifact(db, "refused-path", kind="report-json", path=raw)

    expected = (base.MISSING, "missing") if case == "not-directory" else (base.UNREADABLE_FILE, None)
    assert (str(caught.value), caught.value.state) == expected
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert len(base._pointers(db)) == 1
