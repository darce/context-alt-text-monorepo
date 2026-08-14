"""Cluster gate: every analyze terminal (success or exhausted failure) AND ≥1 success."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.bench.driver import evaluate_cluster_gate, run_cluster_phase, run_pair
from scripts.bench.export_map import export_leg, require_cluster_success
from scripts.bench.stack_pair import BenchError
from scripts.bench.stack_pair import BenchError, load_stack_pair
from scripts.bench.tests.conftest import FakeClient, write_hashed_manifest, write_pair


def _rec(media_id: int, *, outcome: str, attempt: int) -> dict:
    rec = {
        "manifest_media_id": media_id,
        "phase": "analyze",
        "outcome": outcome,
        "attempt": attempt,
        "stack_media_id": media_id if outcome == "ok" else None,
        "terminal_ingest_outcome": "success" if outcome == "ok" else "analyze_failed",
    }
    if outcome == "ok":
        rec["image_width"] = 16
        rec["image_height"] = 16
    return rec


def test_all_terminal_with_one_success_admits() -> None:
    records = [_rec(1, outcome="ok", attempt=1), _rec(2, outcome="failed", attempt=2)]
    decision = evaluate_cluster_gate(records, item_max_attempts=2)
    assert decision.admits is True


def test_all_terminal_zero_success_refuses() -> None:
    records = [_rec(1, outcome="failed", attempt=2), _rec(2, outcome="failed", attempt=2)]
    decision = evaluate_cluster_gate(records, item_max_attempts=2)
    assert decision.admits is False
    assert decision.reason == "cluster_gate_refused"


def test_non_terminal_in_flight_refuses() -> None:
    records = [_rec(1, outcome="ok", attempt=1), _rec(2, outcome="failed", attempt=1)]
    decision = evaluate_cluster_gate(records, item_max_attempts=2)
    assert decision.admits is False
    assert decision.reason is None


def test_zero_success_writes_leg_outcome_and_skips_cluster(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    stack_id = "acx-dev-insightface"
    items = run_dir / "legs" / stack_id / "items.jsonl"
    items.parent.mkdir(parents=True)
    items.write_text(
        json.dumps(_rec(1, outcome="failed", attempt=2)) + "\n",
        encoding="utf-8",
    )
    client = FakeClient()
    decision = run_cluster_phase(run_dir, stack_id, client, tenant_id="t", item_max_attempts=2)
    assert decision.admits is False
    assert client.cluster_calls == 0
    outcome = json.loads((run_dir / "legs" / stack_id / "leg_outcome.json").read_text())
    assert outcome["error_code"] == "cluster_gate_refused"
    assert not (run_dir / "legs" / stack_id / "cluster_job.json").exists()


def test_in_flight_refusal_does_not_write_terminal_outcome(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    stack_id = "acx-dev-insightface"
    items = run_dir / "legs" / stack_id / "items.jsonl"
    items.parent.mkdir(parents=True)
    items.write_text(
        json.dumps(_rec(1, outcome="ok", attempt=1))
        + "\n"
        + json.dumps(_rec(2, outcome="failed", attempt=1))
        + "\n",
        encoding="utf-8",
    )
    client = FakeClient()
    decision = run_cluster_phase(run_dir, stack_id, client, tenant_id="t", item_max_attempts=2)
    assert decision.admits is False
    assert decision.reason is None
    assert client.cluster_calls == 0
    assert not (run_dir / "legs" / stack_id / "leg_outcome.json").exists()


def test_export_aborts_when_cluster_job_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    stack_id = "acx-dev-insightface"
    (run_dir / "legs" / stack_id).mkdir(parents=True)
    with pytest.raises(BenchError):
        require_cluster_success(run_dir, stack_id)


def test_refused_leg_does_not_mark_run_done(tmp_path: Path) -> None:
    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    out = tmp_path / "out"
    with pytest.raises(BenchError) as exc:
        run_pair(
            pair,
            manifest_path=manifest,
            images_dir=images,
            out_dir=out,
            clients={
                "acx-dev-insightface": FakeClient(analyze_ok=False),
                "acx-dev-fir": FakeClient(analyze_ok=False),
            },
            skip_preflight=True,
        )
    assert exc.value.code == "run_incomplete"
    run_doc = json.loads((out / "run.json").read_text())
    assert run_doc["phase"] != "done"


def test_export_aborts_when_cluster_job_non_success(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    stack_id = "acx-dev-insightface"
    dest = run_dir / "legs" / stack_id
    dest.mkdir(parents=True)
    (dest / "cluster_job.json").write_text(json.dumps({"status": "failed"}), encoding="utf-8")
    with pytest.raises(BenchError):
        require_cluster_success(run_dir, stack_id)
    with pytest.raises(BenchError):
        export_leg(FakeClient(), run_dir, stack_id)
