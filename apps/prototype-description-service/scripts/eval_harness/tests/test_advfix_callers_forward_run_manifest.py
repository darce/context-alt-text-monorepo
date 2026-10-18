"""ADVFIX-1 callers must preserve run-manifest admission at report time."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.eval_harness import fusion_runner, zero_rule_baseline
from scripts.eval_harness.manifest import load_manifest

FUSION_MANIFEST = Path(__file__).parents[3] / "scene" / "tests" / "seed" / "fusion_regression.json"


def _manifest_dump(manifest):
    return manifest.model_dump()


def test_fusion_runner_forwards_manifest_to_all_report_builds(tmp_path, monkeypatch) -> None:
    manifest = load_manifest(
        str(FUSION_MANIFEST),
        skip_hash_verification=True,
        hash_skip_reason="fusion caller test uses manifest metadata only",
        metadata_only=True,
    )
    monkeypatch.setattr(fusion_runner, "load_manifest", lambda *args, **kwargs: manifest)
    monkeypatch.setattr(fusion_runner, "run_fusion_eval", lambda *args, **kwargs: {"items": []})
    monkeypatch.setattr(
        fusion_runner,
        "score_misattachments",
        lambda *args, **kwargs: {"labeled_facts": 0, "misattachments": 0, "hits": []},
    )
    calls = []

    def capture_build_reports(*args, **kwargs):
        calls.append(kwargs)
        return json.dumps({"verdict": {"reasons": []}}), "fusion report\n"

    monkeypatch.setattr(fusion_runner, "build_reports", capture_build_reports)

    result = fusion_runner.main(
        [
            "--manifest",
            str(FUSION_MANIFEST),
            "--out-dir",
            str(tmp_path),
            "--mode",
            "staged",
            "--audience",
            "public",
        ]
    )

    assert result == 0
    assert len(calls) == 2
    assert all(call.get("run_manifest") == _manifest_dump(manifest) for call in calls)


def test_zero_rule_baseline_forwards_manifest_to_report_build(tmp_path, monkeypatch) -> None:
    manifest = zero_rule_baseline.load_held_out_manifest()
    monkeypatch.setattr(zero_rule_baseline, "load_held_out_manifest", lambda path=None: manifest)
    monkeypatch.setattr(
        zero_rule_baseline,
        "build_zero_rule_run_record",
        lambda *args, **kwargs: {"provenance": {"manifest_sha256": "a" * 64}},
    )
    monkeypatch.setattr(zero_rule_baseline, "stamped_entries", lambda _manifest: [])
    calls = []

    def capture_build_reports(*args, **kwargs):
        calls.append(kwargs)
        return "{}", "zero-rule report\n"

    monkeypatch.setattr(zero_rule_baseline, "build_reports", capture_build_reports)

    result = zero_rule_baseline.main(
        [
            "--manifest",
            "unused.json",
            "--out-record",
            str(tmp_path / "record.json"),
            "--out-json",
            str(tmp_path / "report.json"),
            "--out-md",
            str(tmp_path / "report.md"),
        ]
    )

    assert result == 0
    assert len(calls) == 1
    assert calls[0].get("run_manifest") == _manifest_dump(manifest)
