"""Committed S2A determinism anchor is regenerable and load-bearing (VLM-6 F4).

The frozen triple under docs/tasks/vlm/bakeoff-results/ is the artifact the
future digest gate (VLM6-S2A-B-06) will compare. These tests pin:
  - generator byte-stability against the committed files
  - computed provenance.manifest_sha256 equals current golden manifest
  - TEST-15: mutating the frozen report digest is detectable
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.eval_harness.cli import _manifest_sha
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
_FROZEN_DIGESTS = {
    _RUN.name: "743d06ad9441c8dc96d6a525741b507e9f51914d26e8faafdcbdc5b0b7e38312",
    _REPORT_JSON.name: "03ad0c6c31f2f953cf7ac2523620b8382818976327d7c4a1052c4fab86a7690a",
    _REPORT_MD.name: "51224e12818bab0da3335bbe002a553aa510a0ee8fa7ab3649f2ac197210f17b",
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
    expected_sha = _manifest_sha(load_manifest(str(_GOLDEN)))
    assert manifest_sha == expected_sha
    assert manifest_sha.startswith("859a083e")
    assert run_path.read_bytes() == _RUN.read_bytes()
    assert report_json.read_bytes() == _REPORT_JSON.read_bytes()
    assert report_md.read_bytes() == _REPORT_MD.read_bytes()


def test_committed_run_record_identity_rows_are_dicts_and_manifest_sha_computed() -> None:
    """Greenfield shape: no bare-string identities; sha was generation-time computed."""
    record = json.loads(_RUN.read_text())
    assert record["provenance"]["manifest_sha256"] == _manifest_sha(load_manifest(str(_GOLDEN)))
    assert len(record["items"]) == 37
    for item in record["items"]:
        for row in item["identities"]:
            assert isinstance(row, dict)
            assert "name" in row
        assert (item.get("describe") or {}).get("adapter") == "seeded"


def test_corrupt_frozen_report_digest_diverges(tmp_path: Path) -> None:
    """TEST-15 control: mutating one field of the frozen report.json changes its digest.

    Full B-06 digest-gate comparison is not implemented yet; this proves the
    frozen artifact is load-bearing (corruption is detectable at the digest level).
    """
    original = _REPORT_JSON.read_text()
    payload = json.loads(original)
    # Flip a stable field that must exist on a scored report.
    verdict = payload.setdefault("verdict", {})
    before = verdict.get("verdict", "pass_ungated")
    verdict["verdict"] = "CORRUPTED_FOR_TEST_15"
    corrupted_path = tmp_path / _REPORT_JSON.name
    corrupted_path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    assert _sha256(corrupted_path) != _FROZEN_DIGESTS[_REPORT_JSON.name]
    # Restore semantics: re-reading the committed file still matches the freeze.
    assert _sha256(_REPORT_JSON) == _FROZEN_DIGESTS[_REPORT_JSON.name]
    assert before != "CORRUPTED_FOR_TEST_15"
