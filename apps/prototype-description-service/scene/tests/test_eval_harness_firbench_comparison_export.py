"""FIRBENCH-1 UX comparison export: owned CLI contract tests (``comparison-export``).

Every fixture is synthetic. The evidence DB and the seed report live in a fresh 0700 directory under
``/var/tmp``, because ``/tmp`` sits under a stray Git-marked ancestor and the evidence DB refuses it.
The seed report is the committed synthetic fixture ``face_bakeoff_report.v1.json``. The tests drive the
public ``firbench_cli.main`` entry point and never import the new export module at collection time.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
from pathlib import Path

import pytest

from scripts.eval_harness import firbench_cli as cli

APP_DIR = Path(__file__).resolve().parents[2]
EVIDENCE_SCRATCH = Path("/var/tmp")
SEED_REPORT = APP_DIR / "scripts/eval_harness/tests/fixtures/face_bakeoff_report.v1.json"
ARTIFACT_ID = "ux-face-bakeoff-1"
CORPUS_ID = "synthetic-corpus"
MANIFEST_BYTES = b'{"synthetic": "manifest"}\n'


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def scratch():
    """Fresh 0700 directory under /var/tmp for one DB, its synthetic report, and the export output."""
    root = Path(tempfile.mkdtemp(prefix="fb1-ux-export-", dir=EVIDENCE_SCRATCH))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _v0_db(root: Path) -> Path:
    """The corpus_catalog v0 store: 0600, user_version 1, one pinned manifest row."""
    db = root / "evidence.sqlite3"
    os.close(os.open(db, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    with contextlib.closing(sqlite3.connect(db, isolation_level=None)) as conn:
        conn.execute(
            "CREATE TABLE corpus_manifest (corpus_id TEXT PRIMARY KEY NOT NULL, "
            "manifest_sha256 TEXT NOT NULL, manifest_bytes BLOB NOT NULL)"
        )
        conn.execute("PRAGMA user_version = 1")
        conn.execute(
            "INSERT INTO corpus_manifest VALUES (?, ?, ?)", (CORPUS_ID, _sha(MANIFEST_BYTES), MANIFEST_BYTES)
        )
    return db


def _report(root: Path) -> Path:
    directory = root / "artifacts"
    directory.mkdir()
    path = directory / "face-bakeoff.json"
    path.write_bytes(SEED_REPORT.read_bytes())
    return path


def test_comparison_export_cli_writes_export_for_registered_report(scratch, capsys):
    db = _v0_db(scratch)
    report = _report(scratch)
    assert (
        cli.main(
            ["evidence", "register", ARTIFACT_ID, "--evidence-db", str(db), "--kind", "report-json", "--path", str(report)]
        )
        == 0
    )
    capsys.readouterr()
    out = scratch / "exports" / "comparison-export.json"
    out.parent.mkdir()
    db_before = _sha(db.read_bytes())

    try:
        rc = cli.main(["comparison-export", "--evidence-db", str(db), "--artifact-id", ARTIFACT_ID, "--out", str(out)])
    except SystemExit as refusal:
        rc = refusal.code
    captured = capsys.readouterr()

    assert rc == 0, captured.err
    assert captured.out.strip() == str(out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema"] == "firbench/comparison-explorer-export-v1"
    assert payload["schema_version"] == 1
    assert [row["artifact_id"] for row in payload["reports"]] == [ARTIFACT_ID]
    assert _sha(db.read_bytes()) == db_before


# --- behavior contract: projection, binding, strict input, no-clobber publication -----------------
# Added after the recorded RED. These drive the real module and real files under /var/tmp scratch.

ARTIFACT_A = "ux-alias-a"
ARTIFACT_B = "ux-alias-b"
BOUND = 16 << 20


def _fce():
    from scripts.eval_harness import firbench_comparison_export

    return firbench_comparison_export


def _fe():
    from scripts.eval_harness import firbench_evidence

    return firbench_evidence


def _legacy(**overrides) -> dict:
    """Synthetic acx-eval/v1 face_bakeoff report with the historical key shape. Names and paths are invented."""
    report = {
        "schema": "acx-eval/v1",
        "kind": "report",
        "report_kind": "face_bakeoff",
        "model": {"model_id": "ort-yunet-sface", "embedding_dim": 128, "leg": "candidate"},
        "counts": {
            "total": 150,
            "scored": 150,
            "failed": 0,
            "matched_faces": 189,
            "named_matched": 100,
            "stranger_matched": 89,
        },
        "detection": {"tp": 189, "fn": 186, "fp": 0, "precision": 1.0, "recall": 0.504},
        "slices": {
            "clustering": {
                "d_cut": 0.6,
                "n_faces": 189,
                "n_clusters": 40,
                "purity": 0.9,
                "false_merge": 0.1,
                "false_split": 0.2,
                "p_same": 10,
                "p_diff": 20,
                "m_co_clustered": 3,
                "labels": ["Alice"],
                "reasons": ["free text reason"],
                "status": "directional",
                "directional": True,
                "sampling_frame": "frame-note",
            },
            "unknown_rejection": {
                "correct_rejects": 80,
                "false_accepts": 9,
                "n": 89,
                "n_floor": 50,
                "rate": 0.9,
                "rate_numerator": 80,
                "rate_denominator": 89,
                "error_target": "target text",
                "label": "Stranger",
                "reasons": [],
            },
            "headline_identification": {
                "tp": 100,
                "fn": 5,
                "fp": 2,
                "missed_gt": 3,
                "unmatched_detections": 1,
                "n_named_probes": 100,
                "n_recall_eligible": 105,
                "n_floor": 40,
                "precision": 0.98,
                "precision_numerator": 100,
                "precision_denominator": 102,
                "recall": 0.95,
                "recall_numerator": 100,
                "recall_denominator": 105,
                "wrong_names": [["Alice", "Bob"]],
                "floor_unit": "recall_eligible_celebs01",
                "association_provenance_notes": "free text note",
            },
            "full_corpus_identification": {
                "tp": 100,
                "fn": 8,
                "fp": 2,
                "missed_gt": 3,
                "unmatched_detections": 1,
                "n_named_probes": 100,
                "n_recall_eligible": 108,
                "precision": 0.98,
                "precision_numerator": 100,
                "precision_denominator": 102,
                "recall": 0.926,
                "recall_numerator": 100,
                "recall_denominator": 108,
                "detection_recall_coupling_flag": "flag text",
                "wrong_names": [],
            },
            "occlusion": {"masked": {"n": 3}},
        },
    }
    report.update(overrides)
    return report


def _bytes(report: dict) -> bytes:
    return (json.dumps(report, sort_keys=True) + "\n").encode("utf-8")


def _with(path: tuple, value: object) -> dict:
    report = _legacy()
    node = report
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return report


def _register(db: Path, artifact_id: str, path: Path, kind: str = "report-json") -> None:
    _fe().register_artifact(db, artifact_id, kind=kind, path=path)


def _write(root: Path, name: str, data: bytes) -> Path:
    directory = root / "artifacts"
    directory.mkdir(exist_ok=True)
    path = directory / name
    path.write_bytes(data)
    return path


def _tree_state(directory: Path) -> dict:
    state = {}
    for entry in sorted(directory.iterdir()):
        info = os.lstat(entry)
        if stat.S_ISLNK(info.st_mode):
            state[entry.name] = ("link", os.readlink(entry))
        elif stat.S_ISDIR(info.st_mode):
            state[entry.name] = ("dir", None)
        else:
            state[entry.name] = ("file", entry.read_bytes())
    return state


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_keys(item) for item in value)) if value else set()
    return set()


# -- projection ---------------------------------------------------------------------------------------


def test_summary_projects_only_fixed_numeric_fields():
    summary = _fce().summarize_legacy_report(_bytes(_legacy()), artifact_id=ARTIFACT_ID)

    assert (summary["pipeline"], summary["model_id"], summary["embedding_dim"]) == ("sface", "ort-yunet-sface", 128)
    assert summary["clustering"]["algorithm"] is None
    assert summary["clustering"]["metric"] is None
    assert summary["clustering"]["parameters"] == {"d_cut": 0.6}
    assert summary["clustering"]["p_same"] == 10
    assert summary["identification"]["headline"]["precision_numerator"] == 100
    assert summary["identification"]["headline"]["n_floor"] == 40
    assert summary["identification"]["full"]["n_floor"] is None
    assert summary["slice_sections"] == [
        "clustering",
        "full_corpus_identification",
        "headline_identification",
        "unknown_rejection",
    ]
    assert (summary["compatibility"], summary["qualification"]) == ("unknown", "unqualified")
    text = json.dumps(summary)
    for leaked in ("Alice", "Bob", "free text", "frame-note", "occlusion", "directional", "wrong_names", "winner"):
        assert leaked not in text


def test_absent_and_refused_sections_are_null_never_zero():
    slices = _legacy()["slices"]
    slices["unknown_rejection"] = {"refused": True, "invariant": "EVAL-03", "correct_rejects": 0, "rate": 0.0}
    del slices["headline_identification"]

    summary = _fce().summarize_legacy_report(_bytes(_legacy(slices=slices)), artifact_id=ARTIFACT_ID)

    assert all(value is None for value in summary["unknown_rejection"].values())
    assert all(value is None for value in summary["identification"]["headline"].values())
    assert "headline_identification" not in summary["slice_sections"]


@pytest.mark.parametrize("overrides", [{"schema": "acx-eval/v2"}, {"kind": "run"}, {"report_kind": "bakeoff"}])
def test_other_schema_or_kind_is_refused(overrides):
    with pytest.raises(_fce().ComparisonExportError, match="not an acx-eval/v1 face_bakeoff report"):
        _fce().summarize_legacy_report(_bytes(_legacy(**overrides)), artifact_id=ARTIFACT_ID)


MALFORMED = [
    (("counts", "total"), "150"),
    (("counts", "failed"), True),
    (("counts", "scored"), -1),
    (("detection", "recall"), 1.5),
    (("detection", "tp"), 1.0),
    (("slices", "clustering", "d_cut"), -0.1),
    (("slices", "clustering", "purity"), float("nan")),
    (("model", "embedding_dim"), True),
    (("model", "embedding_dim"), 0),
    (("slices", "unknown_rejection"), ["not", "a", "dict"]),
]


@pytest.mark.parametrize("path,value", MALFORMED)
def test_malformed_numeric_types_are_refused(path, value):
    with pytest.raises(_fce().ComparisonExportError):
        _fce().summarize_legacy_report(_bytes(_with(path, value)), artifact_id=ARTIFACT_ID)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema": "acx-eval/v1", "schema": "acx-eval/v1", "kind": "report", "report_kind": "face_bakeoff"}',
        b'{"schema": "acx-eval/v1", "kind": "report", "report_kind": "face_bakeoff", "counts": {"total": NaN}}',
        b'{"schema": "acx-eval/v1", "kind": "report", "report_kind": "face_bakeoff", "counts": {"total": Infinity}}',
        b'{"schema": "acx-eval/v1", "kind": "report", "report_kind": "face_bakeoff", "detection": {"recall": 1e400}}',
    ],
)
def test_strict_json_refuses_duplicate_keys_and_nonfinite_numbers(raw):
    with pytest.raises(_fce().ComparisonExportError, match="not strict JSON"):
        _fce().summarize_legacy_report(raw, artifact_id=ARTIFACT_ID)


def test_unknown_model_id_is_null_and_never_copied():
    secret = "/home/operator/private-model-xyz"
    summary = _fce().summarize_legacy_report(
        _bytes(_legacy(model={"model_id": secret, "embedding_dim": 512})), artifact_id=ARTIFACT_ID
    )
    assert (summary["model_id"], summary["pipeline"], summary["embedding_dim"]) == (None, None, 512)
    assert secret not in json.dumps(summary)

    buffalo = _fce().summarize_legacy_report(
        _bytes(_legacy(model={"model_id": "buffalo_l", "embedding_dim": 512})), artifact_id=ARTIFACT_ID
    )
    assert (buffalo["model_id"], buffalo["pipeline"]) == ("buffalo_l", "insightface")


def test_current_provenance_model_lists_are_used_only_when_unambiguous():
    report = _legacy(provenance={"model": {"model_ids": ["auraface"], "embedding_dims": [512]}})
    del report["model"]
    summary = _fce().summarize_legacy_report(_bytes(report), artifact_id=ARTIFACT_ID)
    assert (summary["model_id"], summary["pipeline"], summary["embedding_dim"]) == ("auraface", "auraface", 512)

    report["provenance"]["model"]["model_ids"] = ["auraface", "ort-yunet-sface"]
    ambiguous = _fce().summarize_legacy_report(_bytes(report), artifact_id=ARTIFACT_ID)
    assert ambiguous["model_id"] is None and ambiguous["pipeline"] is None


# -- evidence binding and real filesystem ------------------------------------------------------------


def test_export_refuses_registered_non_report_pointer(scratch):
    db = _v0_db(scratch)
    _register(db, ARTIFACT_ID, _write(scratch, "scores.json", _bytes(_legacy())), kind="scores-json")
    with pytest.raises(_fce().ComparisonExportError, match="registered report-json pointer"):
        _fce().export_comparison(db, [ARTIFACT_ID])


def test_export_refuses_source_changed_since_registration(scratch):
    db = _v0_db(scratch)
    report = _write(scratch, "a.json", _bytes(_legacy()))
    _register(db, ARTIFACT_ID, report)
    report.write_bytes(b'{"changed": true}\n')
    out = scratch / "exports" / "out.json"
    out.parent.mkdir()
    with pytest.raises(_fce().ComparisonExportError, match="changed since registration"):
        _fce().write_export(_fce().export_comparison(db, [ARTIFACT_ID]), out)
    assert not out.exists()


def test_source_swapped_after_resolve_is_refused_by_bound_read(scratch, monkeypatch):
    db = _v0_db(scratch)
    report = _write(scratch, "a.json", _bytes(_legacy()))
    _register(db, ARTIFACT_ID, report)
    real_resolve = _fe().resolve_artifact

    def resolve_then_swap(evidence_db, artifact_id):
        path = real_resolve(evidence_db, artifact_id)
        replacement = Path(path).with_name("swap-replacement.tmp")
        replacement.write_bytes(_bytes(_legacy(model={"model_id": "buffalo_l", "embedding_dim": 512})))
        os.replace(replacement, path)
        return path

    monkeypatch.setattr(_fe(), "resolve_artifact", resolve_then_swap)
    out = scratch / "exports" / "out.json"
    out.parent.mkdir()
    with pytest.raises(_fce().ComparisonExportError, match="do not match the registered SHA-256"):
        _fce().write_export(_fce().export_comparison(db, [ARTIFACT_ID]), out)
    assert not out.exists()


def test_source_changed_during_read_is_refused(scratch, monkeypatch):
    db = _v0_db(scratch)
    report = _write(scratch, "a.json", _bytes(_legacy()))
    _register(db, ARTIFACT_ID, report)
    live = Path(os.path.realpath(report))
    real_chunk = _fce()._read_chunk
    appended: list[bool] = []

    def chunk_then_append_once(fd, size):
        chunk = real_chunk(fd, size)
        if chunk and not appended:
            appended.append(True)
            with open(live, "ab") as handle:
                handle.write(b" ")
        return chunk

    monkeypatch.setattr(_fce(), "_read_chunk", chunk_then_append_once)
    with pytest.raises(_fce().ComparisonExportError, match="changed while it was being read"):
        _fce().export_comparison(db, [ARTIFACT_ID])


def test_registered_source_replaced_by_symlink_is_refused(scratch):
    db = _v0_db(scratch)
    report = _write(scratch, "a.json", _bytes(_legacy()))
    _register(db, ARTIFACT_ID, report)
    decoy = _write(scratch, "decoy.json", _bytes(_legacy()))
    report.unlink()
    report.symlink_to(decoy)
    # The decoy has identical bytes, so only the non-regular check can refuse the symlink.
    with pytest.raises(_fce().ComparisonExportError):
        _fce().export_comparison(db, [ARTIFACT_ID])


def test_oversized_source_is_refused_before_parse(scratch):
    db = _v0_db(scratch)
    big = _write(scratch, "big.json", b"{" + b" " * (BOUND))
    _register(db, ARTIFACT_ID, big)
    with pytest.raises(_fce().ComparisonExportError, match="exceeds the 16 MiB bound"):
        _fce().export_comparison(db, [ARTIFACT_ID])


def test_aliases_share_one_projection_and_output_is_deterministic(scratch):
    db = _v0_db(scratch)
    data = _bytes(_legacy())
    _register(db, ARTIFACT_B, _write(scratch, "b.json", data))
    _register(db, ARTIFACT_A, _write(scratch, "a.json", data))
    before_db = _sha(db.read_bytes())

    forward = _fce().export_comparison(db, [ARTIFACT_B, ARTIFACT_A])
    reverse = _fce().export_comparison(db, [ARTIFACT_A, ARTIFACT_B])

    assert forward == reverse
    assert [report["artifact_id"] for report in forward["reports"]] == [ARTIFACT_A]
    assert forward["dedup"] == [{"file_sha256": _sha(data), "artifact_ids": [ARTIFACT_A, ARTIFACT_B]}]
    assert [source["artifact_id"] for source in forward["sources"]] == [ARTIFACT_A, ARTIFACT_B]
    assert _keys(forward) & {"winner", "delta", "acceptance", "accept", "gate"} == set()
    out_one = scratch / "exports" / "one.json"
    out_two = scratch / "exports" / "two.json"
    out_one.parent.mkdir()
    _fce().write_export(forward, out_one)
    _fce().write_export(reverse, out_two)
    assert out_one.read_bytes() == out_two.read_bytes()
    assert _sha(db.read_bytes()) == before_db


def test_export_output_carries_no_scratch_paths_or_free_text(scratch):
    db = _v0_db(scratch)
    report = _write(scratch, "a.json", _bytes(_legacy()))
    _register(db, ARTIFACT_ID, report)
    before_source = _sha(report.read_bytes())
    out = scratch / "exports" / "out.json"
    out.parent.mkdir()
    _fce().write_export(_fce().export_comparison(db, [ARTIFACT_ID]), out)
    text = out.read_text(encoding="utf-8")
    assert str(scratch) not in text and "/var/tmp" not in text
    for leaked in ("Alice", "Bob", "free text", "target text", "flag text"):
        assert leaked not in text
    assert _sha(report.read_bytes()) == before_source


def test_export_refuses_malformed_artifact_ids_and_empty_lists(scratch):
    db = _v0_db(scratch)
    with pytest.raises(_fce().ComparisonExportError, match="artifact ID must be 1-128"):
        _fce().export_comparison(db, ["../escape"])
    with pytest.raises(_fce().ComparisonExportError, match="non-empty list"):
        _fce().export_comparison(db, [])


# -- no-clobber publication ------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["file", "symlink", "directory"])
def test_existing_destination_is_preserved_byte_identical(scratch, kind):
    db = _v0_db(scratch)
    _register(db, ARTIFACT_ID, _write(scratch, "a.json", _bytes(_legacy())))
    out = scratch / "exports" / "out.json"
    out.parent.mkdir()
    keep = scratch / "keep.txt"
    keep.write_bytes(b"keep")
    if kind == "file":
        out.write_bytes(b"competing")
    elif kind == "symlink":
        out.symlink_to(keep)
    else:
        out.mkdir()
    before = _tree_state(out.parent)
    with pytest.raises(_fce().ComparisonExportError, match="already exists"):
        _fce().write_export(_fce().export_comparison(db, [ARTIFACT_ID]), out)
    assert _tree_state(out.parent) == before
    assert keep.read_bytes() == b"keep"


def test_competing_writer_between_validation_and_link_is_preserved(scratch, monkeypatch):
    db = _v0_db(scratch)
    _register(db, ARTIFACT_ID, _write(scratch, "a.json", _bytes(_legacy())))
    payload = _fce().export_comparison(db, [ARTIFACT_ID])
    out = scratch / "exports" / "out.json"
    out.parent.mkdir()
    real_link = os.link

    def competing_then_link(source, destination, *args, **kwargs):
        Path(destination).write_bytes(b"competing writer")
        return real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(_fce().os, "link", competing_then_link)
    with pytest.raises(_fce().ComparisonExportError, match="already exists"):
        _fce().write_export(payload, out)
    assert out.read_bytes() == b"competing writer"
    assert sorted(entry.name for entry in out.parent.iterdir()) == ["out.json"]


def test_invalid_payload_writes_nothing(scratch):
    db = _v0_db(scratch)
    _register(db, ARTIFACT_ID, _write(scratch, "a.json", _bytes(_legacy())))
    payload = _fce().export_comparison(db, [ARTIFACT_ID])
    payload["reports"][0]["counts"]["total"] = -1
    out = scratch / "exports" / "out.json"
    out.parent.mkdir()
    with pytest.raises(_fce().ComparisonExportError, match="failed validation"):
        _fce().write_export(payload, out)
    assert list(out.parent.iterdir()) == []


# -- CLI surface -----------------------------------------------------------------------------------------


def test_cli_refusal_prints_fixed_message_and_exits_2(scratch, capsys):
    db = _v0_db(scratch)
    out = scratch / "o.json"
    rc = cli.main(["comparison-export", "--evidence-db", str(db), "--artifact-id", "not-registered", "--out", str(out)])
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.err == "error: ComparisonExportError: artifact ID is not registered in the evidence DB\n"
    assert str(scratch) not in captured.err


def test_cli_requires_at_least_one_artifact_id(scratch):
    db = _v0_db(scratch)
    with pytest.raises(SystemExit) as refusal:
        cli.main(["comparison-export", "--evidence-db", str(db), "--out", str(scratch / "o.json")])
    assert refusal.value.code == 2
    assert not (scratch / "o.json").exists()
