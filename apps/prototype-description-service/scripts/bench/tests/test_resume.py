"""Resume does not re-POST terminal-success media."""

from __future__ import annotations

import json
from pathlib import Path

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
