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
    with pytest.raises(BenchError) as exc:
        require_cluster_success(run_dir, stack_id)
    assert exc.value.code == "cluster_gate_refused"


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


def test_invented_cluster_status_ok_is_refused(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    stack_id = "acx-dev-insightface"
    dest = run_dir / "legs" / stack_id
    dest.mkdir(parents=True)
    (dest / "cluster_job.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")
    with pytest.raises(BenchError) as exc:
        require_cluster_success(run_dir, stack_id)
    assert exc.value.code == "cluster_gate_refused"


def test_export_aborts_when_cluster_job_non_success(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    stack_id = "acx-dev-insightface"
    dest = run_dir / "legs" / stack_id
    dest.mkdir(parents=True)
    (dest / "cluster_job.json").write_text(json.dumps({"status": "failed"}), encoding="utf-8")
    with pytest.raises(BenchError) as exc:
        require_cluster_success(run_dir, stack_id)
    assert exc.value.code == "cluster_gate_refused"
    with pytest.raises(BenchError) as exc:
        export_leg(FakeClient(), run_dir, stack_id)
    assert exc.value.code == "cluster_gate_refused"


def test_admit_clears_stale_refusal_latch(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    stack_id = "acx-dev-insightface"
    items = run_dir / "legs" / stack_id / "items.jsonl"
    items.parent.mkdir(parents=True)
    items.write_text(json.dumps(_rec(1, outcome="ok", attempt=1)) + "\n", encoding="utf-8")
    latch = run_dir / "legs" / stack_id / "leg_outcome.json"
    latch.write_text(json.dumps({"error_code": "cluster_gate_refused"}), encoding="utf-8")
    client = FakeClient()
    decision = run_cluster_phase(run_dir, stack_id, client, tenant_id="t", item_max_attempts=2)
    assert decision.admits is True
    assert not latch.exists()
    assert (run_dir / "legs" / stack_id / "cluster_job.json").is_file()


def test_read_status_reports_failed_until_latch_cleared(tmp_path: Path) -> None:
    from scripts.bench.driver import init_run_dir, read_status
    from scripts.bench.stack_pair import load_stack_pair
    from scripts.bench.tests.conftest import write_hashed_manifest, write_pair

    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    out = init_run_dir(tmp_path / "status-run", pair, manifest)
    stack_id = "acx-dev-insightface"
    leg = out / "legs" / stack_id
    (leg / "leg_outcome.json").write_text(
        json.dumps({"error_code": "cluster_gate_refused"}), encoding="utf-8"
    )
    status = read_status(out)
    assert status["legs"][stack_id]["phase"] == "failed"
    (leg / "leg_outcome.json").unlink()
    (leg / "cluster_job.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    exports = leg / "exports"
    exports.mkdir()
    for name in ("media_identities.json", "clusters.json", "cluster_members.json"):
        (exports / name).write_text("[]", encoding="utf-8")
    status2 = read_status(out)
    assert status2["legs"][stack_id]["phase"] == "done"


def test_retryable_clears_stale_refusal_latch(tmp_path: Path) -> None:
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
    latch = run_dir / "legs" / stack_id / "leg_outcome.json"
    latch.write_text(json.dumps({"error_code": "cluster_gate_refused"}), encoding="utf-8")
    client = FakeClient()
    decision = run_cluster_phase(run_dir, stack_id, client, tenant_id="t", item_max_attempts=2)
    assert decision.admits is False
    assert decision.reason is None
    assert not latch.exists()
    assert client.cluster_calls == 0


def test_read_status_latch_precedes_exports(tmp_path: Path) -> None:
    from scripts.bench.driver import init_run_dir, read_status
    from scripts.bench.stack_pair import load_stack_pair
    from scripts.bench.tests.conftest import write_hashed_manifest, write_pair

    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    out = init_run_dir(tmp_path / "status-latch-export", pair, manifest)
    stack_id = "acx-dev-insightface"
    leg = out / "legs" / stack_id
    (leg / "leg_outcome.json").write_text(
        json.dumps({"error_code": "cluster_gate_refused"}), encoding="utf-8"
    )
    (leg / "cluster_job.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    exports = leg / "exports"
    exports.mkdir()
    for name in ("media_identities.json", "clusters.json", "cluster_members.json"):
        (exports / name).write_text("[]", encoding="utf-8")
    status = read_status(out)
    assert status["legs"][stack_id]["phase"] == "failed"
    assert status["legs"][stack_id]["exports"] is True


def test_unreadable_latch_is_fail_closed(tmp_path: Path) -> None:
    from scripts.bench.driver import _leg_complete, init_run_dir, read_status
    from scripts.bench.stack_pair import BenchError, load_stack_pair
    from scripts.bench.tests.conftest import write_hashed_manifest, write_pair

    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    out = init_run_dir(tmp_path / "status-corrupt", pair, manifest)
    stack_id = "acx-dev-insightface"
    leg = out / "legs" / stack_id
    (leg / "leg_outcome.json").write_text("{not-json", encoding="utf-8")
    (leg / "cluster_job.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    exports = leg / "exports"
    exports.mkdir()
    for name in ("media_identities.json", "clusters.json", "cluster_members.json"):
        (exports / name).write_text("[]", encoding="utf-8")
    with pytest.raises(BenchError) as exc:
        read_status(out)
    assert exc.value.code == "leg_outcome_unreadable"
    with pytest.raises(BenchError) as exc:
        _leg_complete(out, stack_id)
    assert exc.value.code == "leg_outcome_unreadable"
