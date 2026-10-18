"""Synthetic regressions for serialized first imports and malformed SQLite rows.

The scheduler only pauses execution at a function boundary. All connections, writer
locks, transactions, CLI calls, and stored values use the real implementation/SQLite.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import sqlite3
import sys
import traceback

import pytest

from scripts.eval_harness import corpus_catalog as cc
from test_eval_harness_corpus_catalog_sqlite import (
    CORPUS_ID,
    MANIFEST_REL,
    PRIVATE_TOKEN,
    _base_checkout,
    _db_import_cli,
    _run_cli,
    _sha,
    private_dir,
)


def _paused_import(db, corpus_id, raw, ready, release, result):
    """Stop after file creation, before entering the real SQLite writer."""
    def schedule(frame, event, arg):
        if (event == "call" and frame.f_code is cc._evidence_write.__code__):
            ready.set()
            if not release.wait(15):
                raise RuntimeError("synthetic scheduler timed out")
        return schedule

    sys.settrace(schedule)
    try:
        status = cc.import_evidence_manifest(db, corpus_id, raw, expected_sha256=_sha(raw))
        result.put(("ok", status))
    except cc.CatalogError as exc:
        result.put(("controlled", str(exc)))
    except BaseException:
        result.put(("unexpected", traceback.format_exc()))
    finally:
        sys.settrace(None)


@pytest.mark.parametrize("fail_first", [False, True], ids=["identical-idempotent", "failed-writer-cleanup"])
def test_first_import_cannot_erase_a_concurrent_commit(tmp_path, private_dir, fail_first):
    repo = _base_checkout(tmp_path)
    raw = (repo / MANIFEST_REL).read_bytes()
    local = tmp_path / "synthetic-local.json"
    local.write_bytes(raw)
    db = private_dir / "race.sqlite3"
    ctx = mp.get_context("spawn")
    ready, release, result = ctx.Event(), ctx.Event(), ctx.Queue()
    first_id = "synthetic-failing-id" if fail_first else CORPUS_ID
    first = ctx.Process(target=_paused_import, args=(db, first_id, raw, ready, release, result))
    first.start()
    try:
        assert ready.wait(15), "first importer did not reach the scheduler"
        second = _db_import_cli(repo, db, local, tmp_path)
        assert second.returncode == 0, second.stderr
        assert json.loads(second.stdout)["status"] == "imported"
        assert cc.read_evidence_manifest(db, CORPUS_ID, expected_sha256=_sha(raw)) == raw
        if fail_first:
            # A real SQLite INSERT failure after another importer has committed.
            with sqlite3.connect(db) as conn:
                conn.execute(
                    "CREATE TRIGGER synthetic_failure BEFORE INSERT ON corpus_manifest "
                    "BEGIN SELECT RAISE(ABORT, 'synthetic-private-failure'); END"
                )
        committed_bytes = db.read_bytes()
        release.set()
        first.join(15)
        assert not first.is_alive(), "first importer did not finish"
        assert first.exitcode == 0
        outcome = result.get(timeout=2)
        # Check preservation first: the original race unlinks this committed DB.
        assert db.is_file(), "first importer deleted the second importer's committed store"
        assert db.read_bytes() == committed_bytes
        assert cc.read_evidence_manifest(db, CORPUS_ID, expected_sha256=_sha(raw)) == raw
        if fail_first:
            assert outcome == ("controlled", cc._EVIDENCE_UNREADABLE)
        else:
            assert outcome == ("ok", "already_imported")
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT count(*) FROM corpus_manifest").fetchone() == (1,)
    finally:
        release.set()
        first.join(2)
        if first.is_alive():
            first.terminate()
            first.join(5)
        result.close()
        result.join_thread()


@pytest.mark.parametrize("storage", ["text", "integer", "real", "null"])
@pytest.mark.parametrize("command", ["show", "check", "db-import"])
def test_malformed_manifest_storage_is_controlled_and_preserves_db(tmp_path, private_dir, storage, command):
    repo = _base_checkout(tmp_path)
    raw = (repo / MANIFEST_REL).read_bytes()
    local = tmp_path / "synthetic-local.json"
    local.write_bytes(raw)
    private_dir.mkdir(mode=0o700)
    db = private_dir / "malformed.sqlite3"
    values = {"text": raw.decode("utf-8"), "integer": 7, "real": 1.5, "null": None}
    with sqlite3.connect(db) as conn:
        # The version/table checks accept this damaged schema, including NULL.
        conn.execute(
            "CREATE TABLE corpus_manifest (corpus_id TEXT PRIMARY KEY, "
            "manifest_sha256 TEXT, manifest_bytes BLOB)"
        )
        conn.execute("PRAGMA user_version = 1")
        conn.execute("INSERT INTO corpus_manifest VALUES (?, ?, ?)", (CORPUS_ID, _sha(raw), values[storage]))
    before = db.read_bytes()
    if command == "db-import":
        response = _db_import_cli(repo, db, local, tmp_path)
    else:
        response = _run_cli(command, CORPUS_ID, "--repo-root", str(repo), "--evidence-db", str(db), cwd=tmp_path)
    assert db.read_bytes() == before
    assert response.returncode == 2, response.stderr
    assert response.stdout == ""
    assert response.stderr == f"error: {cc._EVIDENCE_UNREADABLE}\n"
    assert "Traceback" not in response.stderr
    assert PRIVATE_TOKEN not in response.stderr
