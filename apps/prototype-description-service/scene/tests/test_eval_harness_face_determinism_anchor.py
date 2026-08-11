"""Committed synthetic face determinism anchor (VLM-6 F6 / B-06).

Pins the offline face freeze under docs/tasks/vlm/bakeoff-results/ and drives
the shipped ``score-face --check-determinism --expect-report`` gate:

  - generator byte-stability against committed artifacts
  - report-side corruption → ANCHOR_MISMATCH (TEST-15)
  - run-record-side embedding corruption → ANCHOR_MISMATCH (TEST-15)
  - same run-record corruption without --expect-report → silent pass (DBG-11)
  - clean freeze → green with matches --expect-report

PROV-01: embeddings are synthetic dim=8 unit vectors; no real face data.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from scripts.eval_harness.cli import (
    _check_face_determinism_cross_process,
    _manifest_sha,
    main,
)
from scripts.eval_harness.generate_face_determinism_anchor import (
    _DEFAULT_MANIFEST_STEM,
    _DEFAULT_STEM,
    _EMBEDDING_DIM,
    write_face_anchor,
)
from scripts.eval_harness.manifest import load_manifest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_ANCHOR_DIR = _REPO_ROOT / "docs" / "tasks" / "vlm" / "bakeoff-results"
_STEM = _DEFAULT_STEM
_MANIFEST_STEM = _DEFAULT_MANIFEST_STEM
_MANIFEST = _ANCHOR_DIR / f"{_MANIFEST_STEM}.json"
_RUN = _ANCHOR_DIR / f"{_STEM}.json"
_REPORT_JSON = _ANCHOR_DIR / f"{_STEM}-face-report.json"
_REPORT_MD = _ANCHOR_DIR / f"{_STEM}-face-report.md"

# File digests of the committed face quadruple — update only when intentionally regenerating.
_FROZEN_DIGESTS = {
    _MANIFEST.name: "f41a93d771cad4cfc9baa9553c8fd42e3ea512f5baa3c3e4a3edaa699cde669f",
    _RUN.name: "3fb8628a2f6b5594e724b365684f37ff01173aac420035f3bbcfeaa037b0a751",
    _REPORT_JSON.name: "6c696a5450236fce3ed7ba66acbcc7982b3263d6ad8b7f49fa260d57bca59dca",
    _REPORT_MD.name: "6d066e5be26f1b20663fb381038affdfd883656bcf641170a6cc47849e7fb88b",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unit(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [float(v) / norm for v in values]


@pytest.mark.parametrize("name,expected", list(_FROZEN_DIGESTS.items()))
def test_committed_face_anchor_digests_match_frozen(name: str, expected: str) -> None:
    path = _ANCHOR_DIR / name
    assert path.is_file(), f"missing committed face anchor artifact: {path}"
    assert _sha256(path) == expected


def test_face_generator_regenerates_byte_identical_committed_anchor(tmp_path: Path) -> None:
    """Generator is the source of truth — re-run must match the freeze byte-for-byte."""
    man_path, run_path, report_json, report_md, manifest_sha = write_face_anchor(
        out_dir=tmp_path,
        stem=_STEM,
        manifest_stem=_MANIFEST_STEM,
        head_sha="0" * 40,
        started_at="2026-08-11T00:00:00Z",
    )
    expected_sha = _manifest_sha(load_manifest(str(_MANIFEST)))
    assert manifest_sha == expected_sha
    assert manifest_sha.startswith("e7004f3b")
    assert man_path.read_bytes() == _MANIFEST.read_bytes()
    assert run_path.read_bytes() == _RUN.read_bytes()
    assert report_json.read_bytes() == _REPORT_JSON.read_bytes()
    assert report_md.read_bytes() == _REPORT_MD.read_bytes()


def test_face_run_record_is_synthetic_dim8_no_real_embeddings() -> None:
    """PROV-01: committed face run-record holds only synthetic dim=8 vectors."""
    record = json.loads(_RUN.read_text())
    assert record["kind"] == "face_run_record"
    assert record["provenance"]["embedding_dim"] == _EMBEDDING_DIM
    assert record["provenance"]["model_id"] == "synthetic-face-anchor"
    assert record["provenance"]["manifest_sha256"] == _manifest_sha(
        load_manifest(str(_MANIFEST))
    )
    assert len(record["items"]) == 3
    for item in record["items"]:
        assert item["embedding_dim"] == _EMBEDDING_DIM
        for face in item["faces"]:
            assert len(face["embedding"]) == _EMBEDDING_DIM


def test_corrupt_face_expect_report_makes_determinism_gate_red(tmp_path: Path) -> None:
    """TEST-15 report-side: corrupted --expect-report → ANCHOR_MISMATCH [score-face]."""
    run_copy = tmp_path / _RUN.name
    run_copy.write_bytes(_RUN.read_bytes())
    payload = json.loads(_REPORT_JSON.read_text())
    payload.setdefault("counts", {})["matched_faces"] = 999
    corrupt_expect = tmp_path / "expect-corrupt-face-report.json"
    corrupt_expect.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    assert _sha256(corrupt_expect) != _FROZEN_DIGESTS[_REPORT_JSON.name]

    with pytest.raises(SystemExit) as exc:
        _check_face_determinism_cross_process(
            run_copy,
            str(_MANIFEST),
            public=False,
            expect_report=corrupt_expect,
        )
    msg = str(exc.value)
    assert "determinism check ANCHOR_MISMATCH" in msg
    assert "[score-face]" in msg
    assert "generate_face_determinism_anchor" in msg
    assert "do NOT regenerate" in msg
    assert "determinism check FAILED" not in msg
    assert "determinism check ERROR" not in msg
    assert list(tmp_path.glob("determinism-anchor-mismatch-score-face.diff.txt"))
    assert _sha256(_REPORT_JSON) == _FROZEN_DIGESTS[_REPORT_JSON.name]


def test_corrupt_face_run_record_embedding_makes_determinism_gate_red(tmp_path: Path) -> None:
    """TEST-15 input-side: corrupt embedding → ANCHOR_MISMATCH (not wrong-name).

    landmarks_px / det_score are score-invisible (changing them leaves the
    certified JSON identical). Embedding is the face-path field that changes
    the score without tripping score-face's post-determinism failed-items gate.
    """
    payload = json.loads(_RUN.read_text())
    face = payload["items"][0]["faces"][0]
    emb = list(face["embedding"])
    emb[0] = -abs(emb[0]) - 0.5
    face["embedding"] = _unit(emb)
    run_copy = tmp_path / "run-corrupt.json"
    run_copy.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    expect_copy = tmp_path / _REPORT_JSON.name
    expect_copy.write_bytes(_REPORT_JSON.read_bytes())

    with pytest.raises(SystemExit) as exc:
        _check_face_determinism_cross_process(
            run_copy,
            str(_MANIFEST),
            public=False,
            expect_report=expect_copy,
        )
    msg = str(exc.value)
    assert "determinism check ANCHOR_MISMATCH" in msg
    assert "[score-face]" in msg
    assert "determinism check FAILED" not in msg
    assert "determinism check ERROR" not in msg
    assert "score-face gate failed" not in msg
    assert list(tmp_path.glob("determinism-anchor-mismatch-score-face.diff.txt"))
    assert _sha256(_RUN) == _FROZEN_DIGESTS[_RUN.name]
    assert _sha256(_REPORT_JSON) == _FROZEN_DIGESTS[_REPORT_JSON.name]


def test_corrupt_face_run_record_without_expect_report_passes_silently(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """DBG-11: same embedding corruption without --expect-report still seed-passes.

    Parent and children re-score the same corrupted file and agree — the hole
    F6 closes. Proves the red path above is new coverage, not a rename.
    """
    payload = json.loads(_RUN.read_text())
    face = payload["items"][0]["faces"][0]
    emb = list(face["embedding"])
    emb[0] = -abs(emb[0]) - 0.5
    face["embedding"] = _unit(emb)
    run_copy = tmp_path / "run-corrupt-no-expect.json"
    run_copy.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )

    _check_face_determinism_cross_process(
        run_copy,
        str(_MANIFEST),
        public=False,
        expect_report=None,
    )
    out = capsys.readouterr().out
    assert "determinism check passed [score-face]" in out
    assert "matches --expect-report" not in out
    assert "ANCHOR_MISMATCH" not in out


def test_face_expect_report_matches_committed_freeze_green(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Clean --expect-report against the committed face freeze exits green."""
    run_copy = tmp_path / _RUN.name
    run_copy.write_bytes(_RUN.read_bytes())
    expect_copy = tmp_path / _REPORT_JSON.name
    expect_copy.write_bytes(_REPORT_JSON.read_bytes())

    json_doc, _md = _check_face_determinism_cross_process(
        run_copy,
        str(_MANIFEST),
        public=False,
        expect_report=expect_copy,
    )
    out = capsys.readouterr().out
    assert "determinism check passed [score-face]" in out
    assert "matches --expect-report" in out
    assert "ANCHOR_MISMATCH" not in out
    assert json_doc == _REPORT_JSON.read_text(encoding="utf-8")
    assert _sha256(_REPORT_JSON) == _FROZEN_DIGESTS[_REPORT_JSON.name]
    assert _sha256(_RUN) == _FROZEN_DIGESTS[_RUN.name]


def test_cli_score_face_expect_report_requires_check_determinism(tmp_path: Path) -> None:
    """OBS-04: --expect-report alone is a hard exit (no silent half-gate)."""
    run_copy = tmp_path / _RUN.name
    run_copy.write_bytes(_RUN.read_bytes())
    expect_copy = tmp_path / _REPORT_JSON.name
    expect_copy.write_bytes(_REPORT_JSON.read_bytes())
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "score-face",
                "--manifest",
                str(_MANIFEST),
                "--run-record",
                str(run_copy),
                "--expect-report",
                str(expect_copy),
            ]
        )
    assert "--expect-report requires --check-determinism" in str(exc.value)


def test_cli_score_face_expect_report_end_to_end_green(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Shipped CLI: score-face --check-determinism --expect-report against freeze."""
    run_copy = tmp_path / _RUN.name
    run_copy.write_bytes(_RUN.read_bytes())
    expect_copy = tmp_path / _REPORT_JSON.name
    expect_copy.write_bytes(_REPORT_JSON.read_bytes())
    man_copy = tmp_path / _MANIFEST.name
    man_copy.write_bytes(_MANIFEST.read_bytes())

    main(
        [
            "score-face",
            "--manifest",
            str(man_copy),
            "--run-record",
            str(run_copy),
            "--check-determinism",
            "--expect-report",
            str(expect_copy),
        ]
    )
    out = capsys.readouterr().out
    assert "determinism check passed [score-face]" in out
    assert "matches --expect-report" in out
    assert "baseline=randomized; child_seeds=0,1,42" in out
    # Committed freeze tree untouched (CLI wrote beside tmp run-record only).
    assert _sha256(_REPORT_JSON) == _FROZEN_DIGESTS[_REPORT_JSON.name]
    assert _sha256(_RUN) == _FROZEN_DIGESTS[_RUN.name]
    assert _sha256(_MANIFEST) == _FROZEN_DIGESTS[_MANIFEST.name]
