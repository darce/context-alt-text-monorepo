"""Regression tests for the bounded bench review hardening slice."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.bench import corpus as corpus_mod
from scripts.bench import driver as driver_mod
from scripts.bench.corpus import ItemOutcomeStore
from scripts.bench.driver import init_run_dir, run_leg
from scripts.bench.score_report import _analyze_ok, _load_manifest_from_run, score_head_to_head
from scripts.bench.stack_pair import BenchError, _validate_attrition, load_stack_pair
from scripts.bench.tests.conftest import (
    FakeClient,
    minimal_entry,
    png_bytes,
    valid_pair_dict,
    write_hashed_manifest,
    write_manifest,
    write_pair,
)
from scripts.eval_harness.manifest import ManifestError, load_manifest


def test_score_refuses_manifest_copy_tampering_after_run_init(tmp_path: Path) -> None:
    source = write_manifest(tmp_path / "source.json", [1, 2])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    run_dir = init_run_dir(tmp_path / "run", pair, source)

    copied = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    copied["entries"][0]["path"] = "fixtures/relabelled.jpg"
    (run_dir / "manifest.json").write_text(json.dumps(copied), encoding="utf-8")

    with pytest.raises(BenchError) as exc:
        _load_manifest_from_run(run_dir)
    assert exc.value.code == "manifest_sha_mismatch"


def test_analyze_ok_requires_manifest_path_and_hash_provenance(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path / "manifest.json", [1])
    manifest = load_manifest(
        str(manifest_path),
        metadata_only=True,
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only load",
    )
    entry = manifest.entries[0]
    record = {
        "manifest_media_id": entry.media_id,
        "manifest_path": "wrong.jpg",
        "content_sha256": entry.sha256,
        "stack_media_id": 101,
        "image_width": 10,
        "image_height": 10,
        "phase": "analyze",
        "outcome": "ok",
        "terminal_ingest_outcome": "success",
    }
    assert _analyze_ok([record], entry.media_id, entry=entry) is None


def test_score_refuses_missing_or_rogue_declared_pair_leg(tmp_path: Path) -> None:
    source = write_manifest(tmp_path / "source.json", [1, 2])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml", valid_pair_dict(accepted_set_floor=0.5)))
    run_dir = init_run_dir(tmp_path / "run", pair, source)
    (run_dir / "legs" / "acx-dev-fir").rename(run_dir / "legs" / "rogue-stack")

    with pytest.raises(BenchError) as exc:
        score_head_to_head(run_dir)
    assert exc.value.code == "stack_pair_mismatch"


def test_attrition_rejects_non_finite_values() -> None:
    with pytest.raises(BenchError) as exc:
        _validate_attrition(float("nan"))
    assert exc.value.code == "max_differential_attrition_invalid"


def test_manifest_rejects_parent_paths_and_symlink_escapes(tmp_path: Path) -> None:
    traversal = write_manifest(tmp_path / "traversal.json", [1])
    raw = json.loads(traversal.read_text(encoding="utf-8"))
    raw["entries"][0]["path"] = "../outside.jpg"
    traversal.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ManifestError, match="relative"):
        load_manifest(
            str(traversal),
            metadata_only=True,
            skip_hash_verification=True,
            hash_skip_reason="test metadata-only load",
        )

    outside = tmp_path / "outside.jpg"
    payload = b"outside corpus bytes"
    outside.write_bytes(payload)
    images = tmp_path / "images"
    images.mkdir()
    (images / "escape.jpg").symlink_to(outside)
    symlink_manifest = write_manifest(tmp_path / "symlink.json", [1])
    raw = json.loads(symlink_manifest.read_text(encoding="utf-8"))
    raw["entries"][0]["path"] = "escape.jpg"
    raw["entries"][0]["sha256"] = hashlib.sha256(payload).hexdigest()
    symlink_manifest.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ManifestError, match="outside|under"):
        load_manifest(str(symlink_manifest), images_dir=str(images))


def test_run_leg_reaches_pinned_remote_fallback_when_local_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = png_bytes(10, 10)
    entry = minimal_entry(
        1,
        path="remote.jpg",
        sha256=hashlib.sha256(payload).hexdigest(),
        face_count=0,
        present_identities=[],
        face_boxes=[],
    )
    entry["provenance"]["url"] = "https://media.example/remote.jpg"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 3,
                "annotation_mode": "exhaustive",
                "roster": [],
                "entries": [entry],
            }
        ),
        encoding="utf-8",
    )
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml", valid_pair_dict(item_max_attempts=1)))
    run_dir = init_run_dir(tmp_path / "run", pair, manifest_path)
    images = tmp_path / "empty-images"
    images.mkdir()

    def resolve_with_test_transport(entry, images_dir, **kwargs):
        return corpus_mod.resolve_media_bytes(
            entry,
            images_dir,
            resolver=lambda _host: ["93.184.216.34"],
            fetcher=lambda _url, _addresses: payload,
            **kwargs,
        )

    monkeypatch.setattr(driver_mod, "resolve_media_bytes", resolve_with_test_transport)
    client = FakeClient()
    run_leg(
        pair.endpoint("acx-dev-insightface"),
        pair,
        manifest_path=manifest_path,
        images_dir=images,
        run_dir=run_dir,
        client=client,
    )
    assert [image[2] for call in client.analyze_calls for image in call] == [payload]


def test_resource_exception_is_recorded_as_ingest_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    images = tmp_path / "images"
    manifest_path = write_hashed_manifest(tmp_path / "manifest.json", images, [1])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml", valid_pair_dict(item_max_attempts=2)))
    run_dir = init_run_dir(tmp_path / "run", pair, manifest_path)

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("DNS/socket resource unavailable")

    monkeypatch.setattr(driver_mod, "resolve_media_bytes", unavailable)
    run_leg(
        pair.endpoint("acx-dev-insightface"),
        pair,
        manifest_path=manifest_path,
        images_dir=images,
        run_dir=run_dir,
        client=FakeClient(),
    )
    records = ItemOutcomeStore(run_dir / "legs" / "acx-dev-insightface" / "items.jsonl").read_all()
    failed = [record for record in records if record.get("manifest_media_id") == 1]
    assert failed
    latest = failed[-1]
    assert latest["phase"] == "ingest"
    assert latest["outcome"] == "failed"
    assert latest["terminal_ingest_outcome"] != "success"
