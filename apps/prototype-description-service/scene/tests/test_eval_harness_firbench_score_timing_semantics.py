"""State-only timing evidence through the real persisted-run score producer."""

import dataclasses as dc
import hashlib
import json
import shutil
from pathlib import Path

from scene.tests.test_eval_harness_firbench_score_io import fake_run as fake_run
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_score_io as io


def test_public_score_keeps_timing_state_and_digest_without_numeric_ms(fake_run, tmp_path_factory):
    path, decision, manifest, frame, all_rows = fake_run
    names = fc.Guardrail(
        "names", "false_names_per_1k_mentions", "<= 2 names/1000_mentions", "all", fc.GuardrailRole.veto
    )
    decision = fc.seal(
        dc.replace(decision, guardrails=(*decision.guardrails, names), seal=None),
        sealed_at="2026-01-01T00:00:00Z",
    )
    manifest["firbench"]["decision_sha256"] = fc.manifest_sha256(decision)
    manifest["firbench"]["external_mention_denominators"] = dict.fromkeys(all_rows, 1000)
    (path / "manifest.json").write_text(json.dumps(manifest))
    original_files = {p.relative_to(path): p.read_bytes() for p in path.rglob("*") if p.is_file()}
    receipt = original_files[Path("timings.json")]

    first = io.score_run(path, decision=decision)
    # Cross the same declared budget only in an explicit verification snapshot.
    verification = tmp_path_factory.mktemp("timing-verification")
    shutil.copytree(path, verification, dirs_exist_ok=True)
    changed = json.loads(receipt)
    changed["timing_receipt_ms"] = dict.fromkeys(changed["timing_receipt_ms"], 100)
    changed_bytes = json.dumps(changed, sort_keys=True).encode()
    (verification / "timings.json").write_bytes(changed_bytes)
    last = io.score_run(verification, decision=decision)

    assert first["guardrails"][0]["state"] == "pass"
    assert last["guardrails"][0]["state"] == "fail"
    assert first["verdict"]["state"] == "inconclusive"
    assert last["verdict"]["state"] == "guardrail_vetoed"
    assert first["decision_path"] == ["eligibility:passed", "H1:not_rejected"]
    assert last["decision_path"] == ["eligibility:passed", "H1:guardrail_vetoed"]
    assert first["guardrails"][0]["timings_sha256"] == hashlib.sha256(receipt).hexdigest()
    assert last["guardrails"][0]["timings_sha256"] == hashlib.sha256(changed_bytes).hexdigest()
    assert first["guardrails"][0]["timings_sha256"] != last["guardrails"][0]["timings_sha256"]
    assert {p.relative_to(path): p.read_bytes() for p in path.rglob("*") if p.is_file()} == original_files
    assert (verification / "timings.json").read_bytes() == changed_bytes
    assert {
        p.relative_to(verification): p.read_bytes()
        for p in verification.rglob("*")
        if p.is_file() and p.name != "timings.json"
    } == {p: data for p, data in original_files.items() if p.name != "timings.json"}
    for score in (first, last):
        timing, non_timing = score["guardrails"]
        assert timing["value"] is None
        assert timing["evidence"] == {
            "leg_key": min(all_rows),
            "cohort": None,
            "n_units": frame.n_units,
            "n_psu": None,
            "n_eff": None,
            "limit": None,
            "reason": None,
        }
        assert non_timing["state"] == "pass"
        assert non_timing["value"] == 0
        assert non_timing["evidence"]["limit"] == 2
    assert first["guardrails"][1] == last["guardrails"][1]
    for field in first.keys() - {"guardrails", "verdict", "decision_path", "hypotheses"}:
        assert first[field] == last[field]
    for before, after in zip(first["hypotheses"], last["hypotheses"], strict=True):
        for field in before.keys() - {"state", "interval"}:
            assert before[field] == after[field]
