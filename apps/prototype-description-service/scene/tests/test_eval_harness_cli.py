"""VLM-2A Slice 3: CLI fetch loop (per-item isolation, bounded stall rg-007) + retention."""

import json

import pytest

from scripts.eval_harness.cli import BoundedStallError, fetch_run_record, prune_out_dir
from scripts.eval_harness.manifest import GoldenEntry, GoldenManifest


def _manifest(n: int) -> GoldenManifest:
    sha = "a" * 64
    return GoldenManifest(
        manifest_version=1,
        roster=["Alice Example"],
        entries=[
            GoldenEntry(
                path=f"mock_images/img-{i}.jpg",
                sha256=sha,
                media_id=i,
                present_identities=[],
                context_pack={"title": f"t{i}"},
                must_right=[],
                easy_wrong=[],
                policy={"recognition_enabled": True},
            )
            for i in range(1, n + 1)
        ],
    )


@pytest.fixture()
def images_dir(tmp_path):
    d = tmp_path / "mock_images"
    d.mkdir()
    for i in range(1, 6):
        (d / f"img-{i}.jpg").write_bytes(b"x")
    return tmp_path


class HappyClient:
    def describe(self, **kwargs):
        return {"alt_text_draft": "A photo.", "visual_facts": {"objects": []}}

    def analyze(self, images):
        return "job-1"

    def wait_job(self, job_id):
        return {"status": "completed"}

    def media_identities(self, media_ids):
        return []


class FlakyClient(HappyClient):
    def __init__(self, fail_paths):
        self.fail_paths = fail_paths

    def describe(self, *, filename, **kwargs):
        if filename in self.fail_paths:
            raise RuntimeError(f"boom on {filename}")
        return super().describe(filename=filename, **kwargs)


def test_fetch_produces_run_record_with_provenance(images_dir):
    record = fetch_run_record(_manifest(3), str(images_dir), HappyClient(), head_sha="f" * 40)
    assert record["schema"] == "acx-eval/v1"
    assert record["provenance"]["head_sha"] == "f" * 40
    assert len(record["items"]) == 3
    assert all(item["error"] is None for item in record["items"])


def test_single_item_failure_is_isolated(images_dir):
    client = FlakyClient({"img-2.jpg"})
    record = fetch_run_record(_manifest(3), str(images_dir), client, head_sha="f" * 40)
    errors = {item["media_id"]: item["error"] for item in record["items"]}
    assert errors[1] is None and errors[3] is None
    assert "boom" in errors[2]


def test_bounded_stall_aborts_after_consecutive_failures(images_dir):
    client = FlakyClient({f"img-{i}.jpg" for i in range(1, 6)})
    with pytest.raises(BoundedStallError):
        fetch_run_record(_manifest(5), str(images_dir), client, head_sha="f" * 40, stall_limit=3)


def test_limit_caps_items(images_dir):
    record = fetch_run_record(_manifest(5), str(images_dir), HappyClient(), head_sha="f" * 40, limit=2)
    assert len(record["items"]) == 2


def test_prune_out_dir_keeps_last_n(tmp_path):
    for i in range(7):
        (tmp_path / f"run-2026070{i}-000000.json").write_text("{}")
    (tmp_path / "ignore-list.json").write_text(json.dumps({"wrong_names": []}))
    removed = prune_out_dir(str(tmp_path), keep=3, pattern="run-*.json")
    remaining = sorted(p.name for p in tmp_path.glob("run-*.json"))
    assert len(remaining) == 3
    assert remaining == [f"run-2026070{i}-000000.json" for i in (4, 5, 6)]
    assert len(removed) == 4
    assert (tmp_path / "ignore-list.json").exists()  # never pruned


def test_stall_abort_preserves_partial_record(images_dir):
    client = FlakyClient({f"img-{i}.jpg" for i in range(1, 6)})
    with pytest.raises(BoundedStallError) as excinfo:
        fetch_run_record(_manifest(5), str(images_dir), client, head_sha="f" * 40, stall_limit=3)
    partial = excinfo.value.partial_record
    assert partial["aborted"] is True
    assert len(partial["items"]) == 3
    assert all(item["error"] for item in partial["items"])
