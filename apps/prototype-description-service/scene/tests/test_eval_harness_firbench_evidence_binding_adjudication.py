"""E1-GATE-01: real descriptor reads must stay bound to the returned pathname.

Only os.read is wrapped to schedule real filesystem changes after its first read.
The descriptor, stat results, SQLite store, bytes, and hash oracle are real.
Source and existing fixture helpers are imported at runtime, after collection.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest


@pytest.fixture
def registered():
    import test_eval_harness_firbench_evidence as base

    from scripts.eval_harness import corpus_catalog as cc
    from scripts.eval_harness import firbench_evidence as fe

    expected_source = Path(__file__).resolve().parents[2] / "scripts/eval_harness/firbench_evidence.py"
    assert Path(fe.__file__).resolve() == expected_source
    assert Path(fe._hash_open_file.__code__.co_filename).resolve() == expected_source
    scratch = base.scratch.__wrapped__()
    root = next(scratch)
    try:
        db = root / "evidence #?.sqlite3"
        raw = b'{"synthetic":"manifest"}\n'
        assert (
            cc.import_evidence_manifest(db, "synthetic", raw, expected_sha256=hashlib.sha256(raw).hexdigest())
            == "imported"
        )
        active = root / "active"
        active.mkdir()
        report = active / "report.json"
        report.write_bytes(b'{"synthetic":"old"}\n')
        pointer = fe.register_artifact(db, "synthetic", kind="report-json", path=report)
        assert pointer["status"] == "registered"
        assert pointer["file_sha256"] == hashlib.sha256(report.read_bytes()).hexdigest()
        yield fe, root, db, report, pointer, hashlib.sha256(db.read_bytes()).hexdigest()
    finally:
        scratch.close()


@pytest.mark.parametrize("operation", ["resolve", "check"])
@pytest.mark.parametrize("replacement_kind", ["file", "missing", "symlink", "directory", "fifo", "parent-file"])
def test_directory_swap_during_first_read_refuses_binding(registered, monkeypatch, operation, replacement_kind):
    fe, root, db, report, pointer, db_sha = registered
    active = report.parent
    retained = root / "retained-old"
    replacement = root / "replacement"
    replacement.mkdir()
    target = replacement / report.name
    if replacement_kind == "file":
        target.write_bytes(b'{"synthetic":"new"}\n')
        assert hashlib.sha256(target.read_bytes()).hexdigest() != pointer["file_sha256"]
    elif replacement_kind == "symlink":
        # Even a final symlink back to the original inode is no longer a regular binding.
        target.symlink_to(retained / report.name)
    elif replacement_kind == "directory":
        target.mkdir()
    elif replacement_kind == "fifo":
        os.mkfifo(target)
    elif replacement_kind == "parent-file":
        replacement.rmdir()
        replacement.write_bytes(b"synthetic non-directory parent")

    real_read = os.read
    fired = False

    def swap_after_first_read(fd, count):
        nonlocal fired
        chunk = real_read(fd, count)
        if chunk and not fired:
            fired = True
            active.rename(retained)
            replacement.rename(active)
        return chunk

    with monkeypatch.context() as patch:
        patch.setattr(fe.os, "read", swap_after_first_read)
        if operation == "resolve":
            with pytest.raises(fe.EvidenceError, match="^artifact changed since registration$") as refused:
                fe.resolve_artifact(db, "synthetic")
            assert refused.value.state == "changed"
        else:
            checked = fe.check_artifact(db, "synthetic")
            assert checked["status"] == "changed", "swapped pathname was incorrectly matched"
            assert checked["observed_sha256"] is None
    assert fired, "real first-read directory swap did not execute"
    assert hashlib.sha256((retained / report.name).read_bytes()).hexdigest() == pointer["file_sha256"]
    assert hashlib.sha256(db.read_bytes()).hexdigest() == db_sha


def test_stable_file_still_matches_and_resolves(registered):
    fe, _, db, report, pointer, db_sha = registered
    assert fe.resolve_artifact(db, "synthetic") == str(report)
    checked = fe.check_artifact(db, "synthetic")
    assert checked["status"] == "matched"
    assert checked["observed_sha256"] == pointer["file_sha256"]
    assert hashlib.sha256(db.read_bytes()).hexdigest() == db_sha


def test_descriptor_mutation_keeps_priority_over_missing_pathname(registered, monkeypatch):
    fe, root, db, report, _, db_sha = registered
    retained = root / "retained-old"
    real_read = os.read
    fired = False

    def mutate_after_first_read(fd, count):
        nonlocal fired
        chunk = real_read(fd, count)
        if chunk and not fired:
            fired = True
            report.parent.rename(retained)
            (retained / report.name).write_bytes(b'{"synthetic":"mutated while reading"}\n')
        return chunk

    with monkeypatch.context() as patch:
        patch.setattr(fe.os, "read", mutate_after_first_read)
        with pytest.raises(fe.EvidenceError, match="^artifact changed while it was being hashed$") as refused:
            fe._fingerprint(report, "report-json")
        assert refused.value.state == "changed"
    assert fired
    assert hashlib.sha256(db.read_bytes()).hexdigest() == db_sha
