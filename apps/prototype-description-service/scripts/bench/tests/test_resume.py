"""Resume does not re-POST terminal-success media."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.bench.corpus import ItemOutcomeStore
from scripts.bench.driver import init_run_dir, run_leg
from scripts.bench.stack_pair import load_stack_pair
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
    store.append(
        {
            "manifest_media_id": 1,
            "phase": "analyze",
            "outcome": "ok",
            "image_width": 0,
            "image_height": 16,
            "stack_media_id": 1,
        }
    )
    with pytest.raises(BenchError) as exc:
        store.read_all()
    assert exc.value.code == "image_dimensions_missing"


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
    assert analyze[-1]["terminal_ingest_outcome"] == "success"
    assert "stack_media_id" in analyze[-1]
    assert analyze[-1]["stack_media_id"] is None
    ingest = [r for r in store.read_all() if r.get("phase") == "ingest"]
    assert ingest
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
