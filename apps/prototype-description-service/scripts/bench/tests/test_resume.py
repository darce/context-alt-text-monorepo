"""Resume does not re-POST terminal-success media."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.bench.corpus import ItemOutcomeStore
from scripts.bench import driver as driver_module
from scripts.bench.driver import init_run_dir, run_leg, run_pair
from scripts.bench.preflight import pre_run_reset_evidence_sha256
from scripts.bench.stack_pair import BenchError, load_stack_pair
from scripts.eval_harness import remote_client as remote_client_module
from scripts.eval_harness.remote_client import JobPollTimeoutError, RemoteSceneClient
from scripts.bench.tests.conftest import (
    FakeClient,
    write_hashed_manifest,
    write_pair,
)


def _seed_terminal_success(items_path: Path, media_id: int, width: int = 16, height: int = 16) -> None:
    store = ItemOutcomeStore(items_path)
    store.append(
        {
            "manifest_media_id": media_id,
            "manifest_path": f"img_{media_id}.jpg",
            "content_sha256": "x",
            "stack_media_id": media_id,
            "image_width": width,
            "image_height": height,
            "phase": "ingest",
            "outcome": "ok",
            "error_code": None,
            "attempt": 1,
            "terminal_ingest_outcome": "success",
        }
    )
    store.append(
        {
            "manifest_media_id": media_id,
            "manifest_path": f"img_{media_id}.jpg",
            "content_sha256": "x",
            "stack_media_id": media_id,
            "image_width": width,
            "image_height": height,
            "phase": "analyze",
            "outcome": "ok",
            "error_code": None,
            "attempt": 1,
            "terminal_ingest_outcome": "success",
        }
    )


def _reset_evidence(pair) -> dict[str, dict[str, object]]:
    completed_at = datetime.now(UTC).isoformat()
    return {
        endpoint.stack_id: {
            "reset_attested_by": "bench test operator",
            "reset_reference": "FIR23-STACK runbook reset",
            "reset_completed_at": completed_at,
            "prior_run_identity_rows_empty": True,
        }
        for endpoint in pair.stacks
    }


def _stamp_reset_evidence(out: Path, evidence: dict[str, dict[str, object]]) -> None:
    driver_module._stamp_run_field(out, "pre_run_reset_by_stack", evidence)
    driver_module._stamp_run_field(
        out,
        "pre_run_reset_evidence_sha256",
        pre_run_reset_evidence_sha256(evidence),
    )


def test_wait_job_obeys_total_budget_separate_from_request_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    clock = [0.0]
    timeout_s = 0.02

    def pending_job(*_args: object, **_kwargs: object) -> dict[str, str]:
        nonlocal calls
        calls += 1
        clock[0] += timeout_s / 2
        return {"status": "processing"}

    monkeypatch.setattr(
        remote_client_module,
        "time",
        SimpleNamespace(monotonic=lambda: clock[0], sleep=lambda _seconds: None),
    )

    client = RemoteSceneClient(
        "https://bench.invalid",
        "key",
        timeout_s=5.0,
        job_poll_timeout_s=timeout_s,
        poll_interval=0,
        max_poll_attempts=60,
    )
    client._request_dict = pending_job  # type: ignore[method-assign]
    try:
        with pytest.raises(JobPollTimeoutError):
            client.wait_job("pending")
    finally:
        client.close()
    assert calls < 60
    assert clock[0] <= timeout_s


def test_resume_rejects_changed_manifest_before_running_legs(tmp_path: Path) -> None:
    images = tmp_path / "images"
    pinned_manifest = write_hashed_manifest(tmp_path / "manifest-a.json", images, [1])
    current_manifest = write_hashed_manifest(tmp_path / "manifest-b.json", images, [2])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    out = init_run_dir(tmp_path / "out-manifest-mismatch", pair, pinned_manifest)

    with pytest.raises(BenchError) as exc:
        run_pair(
            pair,
            manifest_path=current_manifest,
            images_dir=images,
            out_dir=out,
            skip_preflight=True,
        )

    assert exc.value.code == "resume_manifest_mismatch"
    assert hashlib.sha256(pinned_manifest.read_bytes()).hexdigest() in str(exc.value)
    assert hashlib.sha256(current_manifest.read_bytes()).hexdigest() in str(exc.value)


def test_resume_rejects_changed_stack_pair_before_running_legs(tmp_path: Path) -> None:
    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pinned_pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    current_pair = replace(pinned_pair, head_to_head_delta=pinned_pair.head_to_head_delta + 0.01)
    out = init_run_dir(tmp_path / "out-pair-mismatch", pinned_pair, manifest)

    with pytest.raises(BenchError) as exc:
        run_pair(
            current_pair,
            manifest_path=manifest,
            images_dir=images,
            out_dir=out,
            skip_preflight=True,
        )

    assert exc.value.code == "resume_stack_pair_mismatch"
    assert repr(pinned_pair.head_to_head_delta) in str(exc.value)
    assert repr(current_pair.head_to_head_delta) in str(exc.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("item_max_attempts", 3),
        ("job_poll_timeout_sec", 601),
        ("wall_clock_timeout_sec", 3601),
        ("images_dir", "other-images"),
        ("manifest_sha256", "a" * 64),
        ("media_url_map_path", "other-media-urls.json"),
    ],
)
def test_resume_rejects_changed_behavior_setting(
    tmp_path: Path, field: str, value: object
) -> None:
    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pinned_pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    current_pair = replace(pinned_pair, **{field: value})
    out = init_run_dir(tmp_path / "out", pinned_pair, manifest)

    with pytest.raises(BenchError) as exc:
        run_pair(
            current_pair,
            manifest_path=manifest,
            images_dir=images,
            out_dir=out,
            skip_preflight=True,
        )

    assert exc.value.code == "resume_stack_pair_mismatch"
    assert field in str(exc.value)
    assert repr(value) in str(exc.value)


def test_missing_run_record_refuses_existing_leg_state(tmp_path: Path) -> None:
    images = tmp_path / "images"
    manifest_a = write_hashed_manifest(tmp_path / "manifest-a.json", images, [1])
    manifest_b = tmp_path / "manifest-b.json"
    manifest_b_doc = json.loads(manifest_a.read_text(encoding="utf-8"))
    manifest_b_doc["entries"][0]["path"] = "img_1_b.jpg"
    (images / "img_1_b.jpg").write_bytes((images / "img_1.jpg").read_bytes())
    manifest_b.write_text(json.dumps(manifest_b_doc, indent=2), encoding="utf-8")
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    out = tmp_path / "out-missing-run-record"
    clients = {endpoint.stack_id: FakeClient() for endpoint in pair.stacks}
    run_pair(
        pair,
        manifest_path=manifest_a,
        images_dir=images,
        out_dir=out,
        clients=clients,
        skip_preflight=True,
        pre_run_reset_by_stack=_reset_evidence(pair),
    )

    pinned_manifest = (out / "manifest.json").read_bytes()
    manifest_pin = (out / "manifest.sha").read_bytes()
    journals = {
        endpoint.stack_id: (out / "legs" / endpoint.stack_id / "items.jsonl").read_bytes()
        for endpoint in pair.stacks
    }
    exports = {
        endpoint.stack_id: (
            out / "legs" / endpoint.stack_id / "exports" / "export_sha256.json"
        ).read_bytes()
        for endpoint in pair.stacks
    }
    (out / "run.json").unlink()

    with pytest.raises(BenchError) as exc:
        run_pair(
            pair,
            manifest_path=manifest_b,
            images_dir=images,
            out_dir=out,
            clients=clients,
            skip_preflight=True,
            pre_run_reset_by_stack=_reset_evidence(pair),
        )

    assert exc.value.code == "run_record_missing_with_leg_state"
    assert "clear the output directory" in str(exc.value)
    assert not (out / "run.json").exists()
    assert (out / "manifest.json").read_bytes() == pinned_manifest
    assert (out / "manifest.sha").read_bytes() == manifest_pin
    for endpoint in pair.stacks:
        stack_id = endpoint.stack_id
        assert (out / "legs" / stack_id / "items.jsonl").read_bytes() == journals[stack_id]
        assert (
            out / "legs" / stack_id / "exports" / "export_sha256.json"
        ).read_bytes() == exports[stack_id]


def test_resume_accepts_unchanged_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = write_hashed_manifest(tmp_path / "manifest.json", tmp_path / "images", [1])
    pair_path = write_pair(tmp_path / "pair.yaml")
    pair = load_stack_pair(pair_path)
    out = init_run_dir(tmp_path / "out", pair, manifest)
    evidence = _reset_evidence(pair)
    _stamp_reset_evidence(out, evidence)
    reached_legs: list[str] = []

    def stub_leg(endpoint, _pair, **_kwargs) -> None:
        reached_legs.append(endpoint.stack_id)

    monkeypatch.setattr(driver_module, "run_leg", stub_leg)
    monkeypatch.setattr(driver_module, "_leg_complete", lambda *_args: True)

    result = run_pair(
        load_stack_pair(pair_path),
        manifest_path=manifest,
        images_dir=tmp_path / "images",
        out_dir=out,
        skip_preflight=True,
        pre_run_reset_by_stack=evidence,
    )

    assert result == out
    assert reached_legs == [endpoint.stack_id for endpoint in pair.stacks]


def test_resume_uses_pinned_manifest_after_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    images = tmp_path / "images"
    manifest_a = write_hashed_manifest(tmp_path / "manifest-a.json", images, [1])
    manifest_b = write_hashed_manifest(tmp_path / "manifest-b.json", images, [2])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    out = init_run_dir(tmp_path / "out", pair, manifest_a)
    evidence = _reset_evidence(pair)
    _stamp_reset_evidence(out, evidence)
    validated = driver_module._validate_resume_inputs
    seen_media_ids: list[list[int]] = []

    def validate_then_replace_manifest(root, current_pair, current_manifest):
        result = validated(root, current_pair, current_manifest)
        Path(current_manifest).write_bytes(manifest_b.read_bytes())
        return result

    def capture_leg(_endpoint, _pair, *, manifest_path, preloaded_manifest=None, **_kwargs) -> None:
        manifest = preloaded_manifest
        if manifest is None:
            manifest = driver_module.load_manifest(
                str(manifest_path),
                metadata_only=True,
                skip_hash_verification=True,
                hash_skip_reason="test captures resumed manifest ids only",
            )
        seen_media_ids.append([entry.media_id for entry in manifest.entries])

    monkeypatch.setattr(driver_module, "_validate_resume_inputs", validate_then_replace_manifest)
    monkeypatch.setattr(driver_module, "run_leg", capture_leg)
    monkeypatch.setattr(driver_module, "_leg_complete", lambda *_args: True)

    run_pair(
        pair,
        manifest_path=manifest_a,
        images_dir=images,
        out_dir=out,
        skip_preflight=True,
        pre_run_reset_by_stack=evidence,
    )

    assert pair.manifest_sha256 is None
    assert seen_media_ids == [[1], [1]]


def test_resume_does_not_repost_terminal_success(tmp_path: Path) -> None:
    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1, 2])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    out = init_run_dir(tmp_path / "out", pair, manifest)
    stack_id = "acx-dev-insightface"
    items_path = out / "legs" / stack_id / "items.jsonl"
    _seed_terminal_success(items_path, 1)

    client = FakeClient()
    run_leg(
        pair.endpoint(stack_id),
        pair,
        manifest_path=manifest,
        images_dir=images,
        run_dir=out,
        client=client,
    )
    posted_ids = [img[0] for call in client.analyze_calls for img in call]
    assert 1 not in posted_ids
    assert 2 in posted_ids


def test_resume_does_not_duplicate_ok_ingest(tmp_path: Path) -> None:
    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    out = init_run_dir(tmp_path / "out-dup", pair, manifest)
    items_path = out / "legs" / "acx-dev-insightface" / "items.jsonl"
    _seed_terminal_success(items_path, 1, width=100, height=100)
    # Drop the analyze row so resume re-attempts analyze after an ok ingest.
    recs = [json.loads(line) for line in items_path.read_text().splitlines() if line.strip()]
    recs = [r for r in recs if r.get("phase") != "analyze"]
    items_path.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    run_leg(
        pair.endpoint("acx-dev-insightface"),
        pair,
        manifest_path=manifest,
        images_dir=images,
        run_dir=out,
        client=FakeClient(),
    )
    store = ItemOutcomeStore(items_path)
    ingest_rows = [r for r in store.read_all() if r.get("phase") == "ingest"]
    assert len(ingest_rows) == 1


def test_zero_dimension_ok_record_rejected(tmp_path: Path) -> None:
    from scripts.bench.stack_pair import BenchError

    path = tmp_path / "items.jsonl"
    store = ItemOutcomeStore(path)
    record = {
        "manifest_media_id": 1,
        "phase": "analyze",
        "outcome": "ok",
        "image_width": 0,
        "image_height": 16,
        "stack_media_id": 1,
    }
    with pytest.raises(BenchError) as exc:
        store.append(record)
    assert exc.value.code == "image_dimensions_missing"
    assert path.read_text(encoding="utf-8") == ""


def test_cli_and_harness_shas_are_distinct_or_explicit(tmp_path: Path) -> None:
    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    out = init_run_dir(tmp_path / "out-sha", pair, manifest)
    run_doc = json.loads((out / "run.json").read_text())
    assert run_doc["cli_sha"] != "unknown"
    assert run_doc["harness_sha"] != "unknown"
    # Distinct trees may share a commit; they must not be the same helper echo
    # of a silent unknown fallback.
    assert isinstance(run_doc["cli_sha"], str) and len(run_doc["cli_sha"]) >= 7
    assert isinstance(run_doc["harness_sha"], str) and len(run_doc["harness_sha"]) >= 7


def test_stack_media_id_prefers_job_payload(tmp_path: Path) -> None:
    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    out = init_run_dir(tmp_path / "out-sid", pair, manifest)
    client = FakeClient()
    client.wait_job = lambda job_id: {"status": "completed", "id": job_id, "media_id": 42}  # type: ignore[method-assign]
    run_leg(
        pair.endpoint("acx-dev-insightface"),
        pair,
        manifest_path=manifest,
        images_dir=images,
        run_dir=out,
        client=client,
    )
    store = ItemOutcomeStore(out / "legs" / "acx-dev-insightface" / "items.jsonl")
    analyze = [r for r in store.read_all() if r.get("phase") == "analyze" and r.get("outcome") == "ok"]
    assert analyze
    assert analyze[-1]["stack_media_id"] == 42


def test_completed_with_errors_is_not_ok(tmp_path: Path) -> None:
    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    out = init_run_dir(tmp_path / "out", pair, manifest)
    client = FakeClient()
    client.wait_job = lambda job_id: {"status": "completed_with_errors", "id": job_id}  # type: ignore[method-assign]
    run_leg(
        pair.endpoint("acx-dev-insightface"),
        pair,
        manifest_path=manifest,
        images_dir=images,
        run_dir=out,
        client=client,
    )
    store = ItemOutcomeStore(out / "legs" / "acx-dev-insightface" / "items.jsonl")
    analyze = [r for r in store.read_all() if r.get("phase") == "analyze"]
    assert analyze
    assert analyze[-1]["outcome"] == "failed"
    assert analyze[-1]["error_code"] == "analyze_completed_with_errors"
    assert "terminal_ingest_outcome" not in analyze[-1]
    assert "stack_media_id" in analyze[-1]
    assert analyze[-1]["stack_media_id"] is None
    ingest = [r for r in store.read_all() if r.get("phase") == "ingest"]
    assert ingest
    assert ingest[-1]["terminal_ingest_outcome"] == "success"
    assert "stack_media_id" in ingest[-1]
    assert ingest[-1]["stack_media_id"] is None


def test_non_analyze_ok_rows_stamp_null_stack_media_id(tmp_path: Path) -> None:
    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    out = init_run_dir(tmp_path / "out-no-sid", pair, manifest)
    client = FakeClient()
    client.wait_job = lambda job_id: {"status": "completed_with_errors", "id": job_id}  # type: ignore[method-assign]
    run_leg(
        pair.endpoint("acx-dev-insightface"),
        pair,
        manifest_path=manifest,
        images_dir=images,
        run_dir=out,
        client=client,
    )
    store = ItemOutcomeStore(out / "legs" / "acx-dev-insightface" / "items.jsonl")
    for rec in store.read_all():
        if rec.get("phase") == "analyze" and rec.get("outcome") == "ok":
            continue
        assert "stack_media_id" in rec
        assert rec["stack_media_id"] is None


def test_bencherror_append_stamps_null_stack_media_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.bench.stack_pair import BenchError

    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    out = init_run_dir(tmp_path / "out-be", pair, manifest)

    def boom(*_a, **_k):
        raise BenchError("media_unresolvable", "test seam")

    monkeypatch.setattr("scripts.bench.driver.resolve_media_bytes", boom)
    run_leg(
        pair.endpoint("acx-dev-insightface"),
        pair,
        manifest_path=manifest,
        images_dir=images,
        run_dir=out,
        client=FakeClient(),
    )
    store = ItemOutcomeStore(out / "legs" / "acx-dev-insightface" / "items.jsonl")
    failed = [r for r in store.read_all() if r.get("outcome") == "failed"]
    assert failed
    assert failed[-1]["error_code"] == "media_unresolvable"
    assert "stack_media_id" in failed[-1]
    assert failed[-1]["stack_media_id"] is None


def test_generic_exception_append_stamps_null_stack_media_id(tmp_path: Path) -> None:
    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    out = init_run_dir(tmp_path / "out-ex", pair, manifest)
    run_leg(
        pair.endpoint("acx-dev-insightface"),
        pair,
        manifest_path=manifest,
        images_dir=images,
        run_dir=out,
        client=FakeClient(analyze_ok=False),
    )
    store = ItemOutcomeStore(out / "legs" / "acx-dev-insightface" / "items.jsonl")
    analyze = [r for r in store.read_all() if r.get("phase") == "analyze"]
    assert analyze
    assert analyze[-1]["error_code"] == "analyze_failed"
    assert "stack_media_id" in analyze[-1]
    assert analyze[-1]["stack_media_id"] is None


def test_failed_item_is_reattempted(tmp_path: Path) -> None:
    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    out = init_run_dir(tmp_path / "out", pair, manifest)
    stack_id = "acx-dev-insightface"
    items_path = out / "legs" / stack_id / "items.jsonl"
    store = ItemOutcomeStore(items_path)
    store.append(
        {
            "manifest_media_id": 1,
            "manifest_path": "img_1.jpg",
            "phase": "analyze",
            "outcome": "failed",
            "error_code": "analyze_failed",
            "attempt": 1,
            "terminal_ingest_outcome": "analyze_failed",
        }
    )
    client = FakeClient()
    run_leg(
        pair.endpoint(stack_id),
        pair,
        manifest_path=manifest,
        images_dir=images,
        run_dir=out,
        client=client,
    )
    assert client.analyze_calls
    posted_ids = [img[0] for call in client.analyze_calls for img in call]
    assert 1 in posted_ids


def test_ingest_ok_does_not_burn_first_analyze_attempt(tmp_path: Path) -> None:
    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    out = init_run_dir(tmp_path / "out-attempt", pair, manifest)
    items_path = out / "legs" / "acx-dev-insightface" / "items.jsonl"
    store = ItemOutcomeStore(items_path)
    store.append(
        {
            "manifest_media_id": 1,
            "manifest_path": "img_1.jpg",
            "content_sha256": "x",
            "stack_media_id": 1,
            "image_width": 16,
            "image_height": 16,
            "phase": "ingest",
            "outcome": "ok",
            "error_code": None,
            "attempt": 1,
            "terminal_ingest_outcome": "success",
        }
    )
    client = FakeClient()
    client.wait_job = lambda job_id: {"status": "completed_with_errors", "id": job_id}  # type: ignore[method-assign]
    run_leg(
        pair.endpoint("acx-dev-insightface"),
        pair,
        manifest_path=manifest,
        images_dir=images,
        run_dir=out,
        client=client,
    )
    analyze = [r for r in ItemOutcomeStore(items_path).read_all() if r.get("phase") == "analyze"]
    assert analyze
    assert analyze[-1]["attempt"] == 1
    assert analyze[-1]["outcome"] == "failed"


def test_missing_stack_media_id_fails_closed(tmp_path: Path) -> None:
    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    out = init_run_dir(tmp_path / "out-sid-miss", pair, manifest)
    client = FakeClient()
    client.wait_job = lambda job_id: {"status": "completed", "id": job_id}  # type: ignore[method-assign]
    run_leg(
        pair.endpoint("acx-dev-insightface"),
        pair,
        manifest_path=manifest,
        images_dir=images,
        run_dir=out,
        client=client,
    )
    store = ItemOutcomeStore(out / "legs" / "acx-dev-insightface" / "items.jsonl")
    analyze = [r for r in store.read_all() if r.get("phase") == "analyze"]
    assert analyze
    assert analyze[-1]["outcome"] == "failed"
    assert analyze[-1]["error_code"] == "stack_media_id_missing"


def test_provenance_sha_failure_refuses_run_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.bench import driver as driver_mod
    from scripts.bench.stack_pair import BenchError

    def boom(*_a, **_k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(driver_mod.subprocess, "check_output", boom)
    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    with pytest.raises(BenchError) as exc:
        init_run_dir(tmp_path / "out-sha-fail", pair, manifest)
    assert exc.value.code == "provenance_sha_unavailable"
