"""UX-DATA-01: synthetic numeric overflow at the public report and CLI boundaries."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

from scripts.eval_harness import firbench_cli as cli
from scripts.eval_harness import firbench_comparison_export as export


def _report(field: str, value: object) -> bytes:
    report = {"schema": "acx-eval/v1", "kind": "report", "report_kind": "face_bakeoff"}
    if field == "d_cut":
        report["slices"] = {"clustering": {"d_cut": value}}
    else:
        report["detection"] = {"recall": value}
    return json.dumps(report).encode()


@pytest.mark.parametrize("field", ["d_cut", "recall"])
@pytest.mark.parametrize("value", [10**400, -(10**400)], ids=["positive", "negative"])
def test_public_summary_refuses_integer_float_overflow(field, value):
    # Predicted RED: math.isfinite leaks OverflowError instead of this fixed refusal.
    with pytest.raises(export.ComparisonExportError, match="^artifact report has a malformed field$"):
        export.summarize_legacy_report(_report(field, value), artifact_id="synthetic-review")


@pytest.fixture
def synthetic_store():
    # Match the existing export suite: evidence storage must be outside Git ancestors.
    root = Path(tempfile.mkdtemp(prefix="fb1-ux-export-numeric-", dir="/var/tmp"))
    try:
        db = root / "evidence.sqlite3"
        os.close(os.open(db, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        manifest = b'{"synthetic":"numeric-overflow"}\n'
        with contextlib.closing(sqlite3.connect(db, isolation_level=None)) as conn:
            conn.execute(
                "CREATE TABLE corpus_manifest (corpus_id TEXT PRIMARY KEY NOT NULL, "
                "manifest_sha256 TEXT NOT NULL, manifest_bytes BLOB NOT NULL)"
            )
            conn.execute("PRAGMA user_version = 1")
            conn.execute(
                "INSERT INTO corpus_manifest VALUES (?, ?, ?)",
                ("synthetic-numeric", hashlib.sha256(manifest).hexdigest(), manifest),
            )
        yield root, db
    finally:
        shutil.rmtree(root)


@pytest.mark.parametrize("field", ["d_cut", "recall"])
def test_registered_public_cli_refuses_overflow_without_publication(synthetic_store, capsys, field):
    root, db = synthetic_store
    source = root / "synthetic-report.json"
    source.write_bytes(_report(field, 10**400))
    assert cli.main([
        "evidence", "register", "synthetic-review", "--evidence-db", str(db),
        "--kind", "report-json", "--path", str(source),
    ]) == 0
    capsys.readouterr()
    source_before = source.read_bytes()
    db_before = db.read_bytes()
    destination = root / "exports"
    destination.mkdir()
    out = destination / "comparison.json"

    result = cli.main([
        "comparison-export", "--evidence-db", str(db), "--artifact-id", "synthetic-review",
        "--out", str(out),
    ])

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert captured.err == "error: ComparisonExportError: artifact report has a malformed field\n"
    assert str(root) not in captured.err
    assert str(10**400) not in captured.err
    assert "Traceback" not in captured.err
    assert list(destination.iterdir()) == []
    assert source.read_bytes() == source_before
    assert db.read_bytes() == db_before
