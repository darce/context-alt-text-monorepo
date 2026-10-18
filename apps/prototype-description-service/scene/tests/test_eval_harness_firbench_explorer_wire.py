"""Public synthetic producer-to-explorer wire and malformed-input regressions.

The SQLite case needs the same normal-VM /var/tmp access as the existing evidence
tests. The projection case also exercises the unchanged real producer, without
requiring registry storage. Neither case adds a duplicate top-level d_cut.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import pytest

from scripts.eval_harness import firbench_cli as cli
from scripts.eval_harness import firbench_comparison_export as producer
from scripts.eval_harness.firbench_explorer import ExplorerError, render_explorer


ARTIFACT_ID = "synthetic-wire-sface"


def _legacy_bytes() -> bytes:
    return json.dumps(
        {
            "schema": "acx-eval/v1",
            "kind": "report",
            "report_kind": "face_bakeoff",
            "model": {"model_id": "ort-yunet-sface", "embedding_dim": 128},
            "counts": {
                "total": 150, "scored": 150, "failed": 0,
                "matched_faces": 189, "named_matched": 100, "stranger_matched": 89,
            },
            "detection": {"tp": 189, "fp": 0, "fn": 186, "precision": 1.0, "recall": 0.504},
            "slices": {
                "clustering": {
                    "d_cut": 0.6, "n_faces": 189, "n_clusters": 40,
                    "m_co_clustered": 3, "p_diff": 20, "p_same": 10,
                    "false_merge": 0.1, "false_split": 0.2, "purity": 0.9,
                },
                "unknown_rejection": {
                    "correct_rejects": 80, "false_accepts": 9, "n": 89,
                    "n_floor": 50, "rate": 0.9, "rate_numerator": 80, "rate_denominator": 89,
                },
            },
        },
        sort_keys=True,
    ).encode("ascii")


def _projected_wire() -> dict:
    report = producer.summarize_legacy_report(_legacy_bytes(), artifact_id=ARTIFACT_ID)
    sha = report["file_sha256"]
    return {
        "schema": producer.SCHEMA,
        "schema_version": producer.SCHEMA_VERSION,
        "sources": [{
            "artifact_id": ARTIFACT_ID, "file_sha256": sha, "kind": "report-json",
            "qualification": "unqualified", "source_sha": None,
            "manifest_hash_kind": None, "manifest_sha256": None,
        }],
        "dedup": [{"file_sha256": sha, "artifact_ids": [ARTIFACT_ID]}],
        "reports": [report],
    }


class _TableCells(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self.row = []
        if tag in {"td", "th"}:
            self.cell = []

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self.cell is not None:
            assert self.row is not None
            self.row.append(" ".join(" ".join(self.cell).split()))
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def _assert_recorded_clustering(index: Path) -> None:
    table = _TableCells()
    table.feed(index.read_text(encoding="utf-8"))
    for label, expected in (
        ("Merge rate", 10.0), ("Split rate", 20.0), ("Cluster purity", 0.9),
        ("Grouped faces", 189), ("Clusters", 40), ("Clustering setting d_cut", 0.6),
    ):
        rows = [row for row in table.rows if row and row[0].startswith(label + " ")]
        assert len(rows) == 1, (label, rows)
        recorded = [cell for cell in rows[0][1:] if cell not in {"No result", "not recorded"}]
        assert len(recorded) == 1, (label, rows[0])
        number = re.match(r"\d+(?:\.\d+)?", recorded[0])
        assert number is not None, (label, recorded)
        assert float(number.group()) == pytest.approx(expected), (label, recorded)
        if label in {"Merge rate", "Split rate"}:
            assert number.end() < len(recorded[0]) and recorded[0][number.end()] == "%"


@pytest.fixture
def evidence_root():
    root = Path(tempfile.mkdtemp(prefix="fb1-ux-wire-", dir="/var/tmp"))
    try:
        yield root
    finally:
        shutil.rmtree(root)


def test_registered_comparison_export_renders_nonnull_clustering(evidence_root: Path, capsys) -> None:
    """Real SQLite/evidence -> actual comparison-export CLI -> actual render API."""
    db = evidence_root / "evidence.sqlite3"
    os.close(os.open(db, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    manifest = b'{"synthetic":"wire-manifest"}\n'
    with contextlib.closing(sqlite3.connect(db, isolation_level=None)) as conn:
        conn.execute(
            "CREATE TABLE corpus_manifest (corpus_id TEXT PRIMARY KEY NOT NULL, "
            "manifest_sha256 TEXT NOT NULL, manifest_bytes BLOB NOT NULL)"
        )
        conn.execute("PRAGMA user_version = 1")
        conn.execute(
            "INSERT INTO corpus_manifest VALUES (?, ?, ?)",
            ("synthetic-wire-corpus", hashlib.sha256(manifest).hexdigest(), manifest),
        )
    source = evidence_root / "synthetic-report.json"
    source.write_bytes(_legacy_bytes())
    assert cli.main([
        "evidence", "register", ARTIFACT_ID, "--evidence-db", str(db),
        "--kind", "report-json", "--path", str(source),
    ]) == 0
    capsys.readouterr()
    db_before = hashlib.sha256(db.read_bytes()).hexdigest()
    source_before = source.read_bytes()
    data = evidence_root / "comparison.json"
    assert cli.main([
        "comparison-export", "--evidence-db", str(db),
        "--artifact-id", ARTIFACT_ID, "--out", str(data),
    ]) == 0
    payload = json.loads(data.read_text(encoding="utf-8"))
    clustering = payload["reports"][0]["clustering"]
    assert clustering["parameters"] == {"d_cut": 0.6}
    assert "d_cut" not in clustering
    assert clustering["algorithm"] is None and clustering["metric"] is None
    data_before = data.read_bytes()
    try:
        index = render_explorer(data, evidence_root / "explorer")
        _assert_recorded_clustering(index)
    finally:
        assert hashlib.sha256(db.read_bytes()).hexdigest() == db_before
        assert source.read_bytes() == source_before
        assert data.read_bytes() == data_before


def test_projected_producer_wire_renders_nonnull_clustering(tmp_path: Path) -> None:
    payload = _projected_wire()
    clustering = payload["reports"][0]["clustering"]
    assert clustering["parameters"] == {"d_cut": 0.6}
    assert "d_cut" not in clustering
    assert clustering["algorithm"] is None and clustering["metric"] is None
    data = producer.write_export(payload, tmp_path / "comparison.json")
    before = data.read_bytes()
    index = render_explorer(data, tmp_path / "explorer")
    _assert_recorded_clustering(index)
    assert data.read_bytes() == before


def _isolated_input(tmp_path: Path) -> tuple[dict, Path]:
    payload = _projected_wire()
    # Schema-supported null isolates input guards from the separate clustering defect.
    payload["reports"][0]["clustering"] = None
    return payload, tmp_path / "input.json"


def test_unhashable_model_id_is_a_fixed_explorer_refusal(tmp_path: Path) -> None:
    payload, data = _isolated_input(tmp_path)
    payload["reports"][0]["model_id"] = []
    data.write_text(json.dumps(payload), encoding="utf-8")
    out = tmp_path / "explorer"
    with pytest.raises(ExplorerError) as refusal:
        render_explorer(data, out)
    assert str(refusal.value) == "invalid explorer export: unknown model at reports[0].model_id"
    assert not out.exists()


def test_oversized_integer_rate_is_a_fixed_explorer_refusal(tmp_path: Path) -> None:
    payload, data = _isolated_input(tmp_path)
    payload["reports"][0]["detection"]["recall"] = 10**400
    data.write_text(json.dumps(payload), encoding="utf-8")
    out = tmp_path / "explorer"
    with pytest.raises(ExplorerError) as refusal:
        render_explorer(data, out)
    assert str(refusal.value) == "invalid explorer export: number out of range at reports[0].detection.recall"
    assert not out.exists()
