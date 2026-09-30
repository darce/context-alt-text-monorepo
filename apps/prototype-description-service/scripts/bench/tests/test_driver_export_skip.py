"""Export resume checks include the per-media results and content digests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.bench.corpus import ItemOutcomeStore
from scripts.bench.driver import _leg_complete, run_leg
from scripts.bench.stack_pair import load_stack_pair
from scripts.bench.tests.conftest import FakeClient, write_hashed_manifest, write_pair


def test_legacy_exports_are_rebuilt_with_identity_results_and_digests(tmp_path: Path) -> None:
    manifest = write_hashed_manifest(tmp_path / "manifest.json", tmp_path / "images", [1])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    endpoint = pair.stacks[0]
    run_dir = tmp_path / "run"
    leg_dir = run_dir / "legs" / endpoint.stack_id
    exports_dir = leg_dir / "exports"
    exports_dir.mkdir(parents=True)
    (leg_dir / "cluster_job.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    for name in ("media_identities.json", "clusters.json", "cluster_members.json"):
        (exports_dir / name).write_text("[]", encoding="utf-8")
    ItemOutcomeStore(leg_dir / "items.jsonl").append(
        {
            "manifest_media_id": 1,
            "stack_media_id": 1001,
            "image_width": 10,
            "image_height": 10,
            "phase": "analyze",
            "outcome": "ok",
        }
    )

    class RecordingClient(FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.identity_queries = 0

        def media_identities(self, media_ids: list[int]) -> object:
            self.identity_queries += 1
            return super().media_identities(media_ids)

    client = RecordingClient()

    assert not _leg_complete(run_dir, endpoint.stack_id)
    run_leg(
        endpoint,
        pair,
        manifest_path=manifest,
        images_dir=None,
        run_dir=run_dir,
        client=client,
    )

    assert client.identity_queries == 1
    assert (exports_dir / "media_identity_results.json").is_file()
    digest_path = exports_dir / "export_sha256.json"
    digests = json.loads(digest_path.read_text(encoding="utf-8"))
    assert set(digests) == {
        "media_identities.json",
        "media_identity_results.json",
        "clusters.json",
        "cluster_members.json",
    }
    for name, expected_digest in digests.items():
        assert hashlib.sha256((exports_dir / name).read_bytes()).hexdigest() == expected_digest
    assert _leg_complete(run_dir, endpoint.stack_id)
