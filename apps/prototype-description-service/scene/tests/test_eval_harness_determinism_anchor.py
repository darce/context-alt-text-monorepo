"""Committed S2A determinism anchor is regenerable and load-bearing (VLM-6 F4/F5).

The frozen triple under docs/tasks/vlm/bakeoff-results/ is the artifact the
digest gate (VLM6-S2A-B-06) compares via ``score --check-determinism
--expect-report``. These tests pin:
  - generator byte-stability against the committed files
  - computed provenance.manifest_sha256 equals current golden manifest
  - TEST-15: corrupting a tmp expect-report makes the shipped gate go red
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.eval_harness.cli import (
    _check_score_determinism_cross_process,
    _determinism_artifact_dir,
    _manifest_sha,
)
from scripts.eval_harness.generate_determinism_anchor import (
    _DEFAULT_STEM,
    write_anchor,
)
from scripts.eval_harness.manifest import load_manifest

_REPO_ROOT = Path(__file__).resolve().parents[4]  # monorepo root
_SERVICE_ROOT = Path(__file__).resolve().parents[2]  # apps/prototype-description-service
_GOLDEN = _SERVICE_ROOT / "scene" / "tests" / "seed" / "golden.json"
_ANCHOR_DIR = _REPO_ROOT / "docs" / "tasks" / "vlm" / "bakeoff-results"
_STEM = _DEFAULT_STEM
_RUN = _ANCHOR_DIR / f"{_STEM}.json"
_REPORT_JSON = _ANCHOR_DIR / f"{_STEM}-report.json"
_REPORT_MD = _ANCHOR_DIR / f"{_STEM}-report.md"

# File digests of the committed triple — update only when intentionally regenerating.
# Regenerated VLM6-lb1 after default-on hash verification unblocked the generator
# (manifest_sha256 prefix 83bfdc4e; prior freeze 859a083e was stale vs current golden/schema).
# Regenerated again after the wave-C merge: scoring gained `strata`, `placement`,
# `hallucination`, positional `compared_images`/`excluded_images`, and the
# `wrong_name_images`/`wrong_name_assertions` verdict split. Cause (2) of the
# ANCHOR_MISMATCH message — deliberate scoring change, stale freeze. The run-record
# digest is unchanged (4c80fdbf), which is the evidence that only scoring moved:
# the recorded model output is byte-identical, so this is not corruption.
# Regenerated again for VLM6-R4-03: the markdown now discloses that placement is
# vacuous (claims=0). Run-record and report JSON digests are unchanged — only the
# .md moved, which is the evidence that disclosure changed and scoring did not.
_FROZEN_DIGESTS = {
    _RUN.name: "4c80fdbf08d1599268d54e684505cdf6cfd33a91d2010151ea572f914e23573a",
    _REPORT_JSON.name: "1c627ec2dd28c843082a871c1ac75b8999f2cae25eb1e4606e1b658893168f64",
    _REPORT_MD.name: "97d6132b6842175ec624776347af0596248fc702fc05564e6bbb04a5e3856dcb",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("name,expected", list(_FROZEN_DIGESTS.items()))
def test_committed_anchor_digests_match_frozen(name: str, expected: str) -> None:
    """Pin machine-diffable digests so a silent rewrite of the freeze goes red (TEST-15 base)."""
    path = _ANCHOR_DIR / name
    assert path.is_file(), f"missing committed anchor artifact: {path}"
    assert _sha256(path) == expected


def test_generator_regenerates_byte_identical_committed_anchor(tmp_path: Path) -> None:
    """Generator is the source of truth — re-run must match the freeze byte-for-byte."""
    run_path, report_json, report_md, manifest_sha = write_anchor(
        manifest_path=_GOLDEN,
        out_dir=tmp_path,
        stem=_STEM,
        head_sha="0" * 40,
        started_at="2026-08-11T00:00:00Z",
    )
    # Metadata-only: compares generation-time sha to loader sha; never opens image bytes.
    expected_sha = _manifest_sha(load_manifest(str(_GOLDEN), skip_hash_verification=True))
    assert manifest_sha == expected_sha
    assert manifest_sha.startswith("83bfdc4e")
    assert run_path.read_bytes() == _RUN.read_bytes()
    assert report_json.read_bytes() == _REPORT_JSON.read_bytes()
    assert report_md.read_bytes() == _REPORT_MD.read_bytes()


def test_committed_run_record_identity_rows_are_dicts_and_manifest_sha_computed() -> None:
    """Greenfield shape: no bare-string identities; sha was generation-time computed."""
    record = json.loads(_RUN.read_text())
    # Metadata-only: provenance sha check against roster/entries; never opens image bytes.
    assert record["provenance"]["manifest_sha256"] == _manifest_sha(
        load_manifest(str(_GOLDEN), skip_hash_verification=True)
    )
    assert len(record["items"]) == 37
    for item in record["items"]:
        for row in item["identities"]:
            assert isinstance(row, dict)
            assert "name" in row
        assert (item.get("describe") or {}).get("adapter") == "seeded"


def test_corrupt_expect_report_makes_determinism_gate_red(tmp_path: Path) -> None:
    """TEST-15 / DBG-11: corrupted --expect-report turns the shipped gate red.

    Pre-F5 the guard compared the record to itself across seeds, so a doctored
    freeze was undetectable. This control must fail if ANCHOR_MISMATCH is
    removed or weakened (sr-001).
    """
    run_copy = tmp_path / _RUN.name
    run_copy.write_bytes(_RUN.read_bytes())
    payload = json.loads(_REPORT_JSON.read_text())
    before = (payload.get("verdict") or {}).get("verdict", "pass_ungated")
    payload.setdefault("verdict", {})["verdict"] = "CORRUPTED_FOR_TEST_15"
    corrupt_expect = tmp_path / "expect-corrupt-report.json"
    corrupt_expect.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    assert _sha256(corrupt_expect) != _FROZEN_DIGESTS[_REPORT_JSON.name]

    with pytest.raises(SystemExit) as exc:
        _check_score_determinism_cross_process(
            run_copy,
            str(_GOLDEN),
            rubric_gate="skip",
            expect_report=corrupt_expect,
        )
    msg = str(exc.value)
    assert "determinism check ANCHOR_MISMATCH" in msg
    assert "[score]" in msg
    assert "generate_determinism_anchor" in msg
    assert "do NOT regenerate" in msg
    assert "determinism check FAILED" not in msg
    assert "determinism check ERROR" not in msg
    # F7-01: diagnostic lands in out/, never beside run-record or freeze tree.
    artifact = _determinism_artifact_dir() / "determinism-anchor-mismatch-score.diff.txt"
    assert artifact.is_file()
    assert str(artifact.resolve()) in msg
    assert not list(tmp_path.glob("determinism-anchor-mismatch*.diff.txt"))
    # Committed freeze still intact (TEST-15 restore semantics).
    assert _sha256(_REPORT_JSON) == _FROZEN_DIGESTS[_REPORT_JSON.name]
    assert before != "CORRUPTED_FOR_TEST_15"


def test_expect_report_matches_committed_freeze_green(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Clean --expect-report against the committed freeze still exits green (discrimination)."""
    run_copy = tmp_path / _RUN.name
    run_copy.write_bytes(_RUN.read_bytes())
    # Copy freeze into tmp so we never risk writing beside committed artifacts.
    expect_copy = tmp_path / _REPORT_JSON.name
    expect_copy.write_bytes(_REPORT_JSON.read_bytes())

    json_doc, _md = _check_score_determinism_cross_process(
        run_copy,
        str(_GOLDEN),
        rubric_gate="skip",
        expect_report=expect_copy,
    )
    out = capsys.readouterr().out
    assert "determinism check passed [score]" in out
    assert "matches --expect-report" in out
    assert "ANCHOR_MISMATCH" not in out
    assert json_doc == _REPORT_JSON.read_text(encoding="utf-8")
    assert _sha256(_REPORT_JSON) == _FROZEN_DIGESTS[_REPORT_JSON.name]
    assert _sha256(_RUN) == _FROZEN_DIGESTS[_RUN.name]


def test_corrupt_run_record_alt_text_makes_determinism_gate_red(tmp_path: Path) -> None:
    """F5-01 carry-over / TEST-15: corrupt run-record input (not just the freeze).

    F5 landed report-side corruption. The hole the guard exists for is a
    corrupted *run-record* that parent and children re-score identically —
    seed-stability still "passes" without ``--expect-report``. Mutate
    ``items[i].describe.alt_text_draft`` (no content gate watches it alone;
    wrong-name stays clean) so ANCHOR_MISMATCH is the sole detector.
    """
    run_copy = tmp_path / _RUN.name
    payload = json.loads(_RUN.read_text())
    item = payload["items"][0]
    describe = dict(item.get("describe") or {})
    describe["alt_text_draft"] = "CORRUPTED ALT TEXT DRAFT FOR F5-01 INPUT CONTROL"
    item["describe"] = describe
    run_copy.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    expect_copy = tmp_path / _REPORT_JSON.name
    expect_copy.write_bytes(_REPORT_JSON.read_bytes())

    with pytest.raises(SystemExit) as exc:
        _check_score_determinism_cross_process(
            run_copy,
            str(_GOLDEN),
            rubric_gate="skip",
            expect_report=expect_copy,
        )
    msg = str(exc.value)
    assert "determinism check ANCHOR_MISMATCH" in msg
    assert "[score]" in msg
    assert "determinism check FAILED" not in msg
    assert "determinism check ERROR" not in msg
    assert "wrong-name" not in msg.lower()
    artifact = _determinism_artifact_dir() / "determinism-anchor-mismatch-score.diff.txt"
    assert artifact.is_file()
    assert str(artifact.resolve()) in msg
    assert not list(tmp_path.glob("determinism-anchor-mismatch*.diff.txt"))
    # Committed freeze and original run-record untouched.
    assert _sha256(_REPORT_JSON) == _FROZEN_DIGESTS[_REPORT_JSON.name]
    assert _sha256(_RUN) == _FROZEN_DIGESTS[_RUN.name]
