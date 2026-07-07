"""VLM-2A Slice 3: CLI fetch loop (per-item isolation, bounded stall rg-007) + retention."""

import json

import pytest

from scripts.eval_harness.cli import (
    BoundedStallError,
    MaxCostExceededError,
    fetch_run_record,
    main,
    prune_out_dir,
)
from scripts.eval_harness.manifest import GoldenEntry, GoldenManifest
from scripts.eval_harness.report import build_reports


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
                face_count=0,
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
    removed = prune_out_dir(str(tmp_path), keep=3)
    remaining = sorted(p.name for p in tmp_path.glob("run-*.json"))
    assert len(remaining) == 3
    assert remaining == [f"run-2026070{i}-000000.json" for i in (4, 5, 6)]
    assert len(removed) == 4
    assert (tmp_path / "ignore-list.json").exists()  # never pruned


def test_prune_out_dir_removes_reports_with_their_run(tmp_path):  # S3-02
    # Each run = record + report.json + report.md; stale runs drop as a unit and
    # markdown reports never accumulate unbounded.
    for i in range(4):
        stamp = f"2026070{i}-000000"
        (tmp_path / f"run-{stamp}.json").write_text("{}")
        (tmp_path / f"run-{stamp}-report.json").write_text("{}")
        (tmp_path / f"run-{stamp}-report.md").write_text("#")
    prune_out_dir(str(tmp_path), keep=2)
    remaining = sorted(p.name for p in tmp_path.glob("run-*"))
    # only the 2 newest stamps survive, each with all three files ('-' sorts before '.')
    assert remaining == [
        f"run-2026070{i}-000000{suffix}" for i in (2, 3) for suffix in ("-report.json", "-report.md", ".json")
    ]


def test_prune_out_dir_rejects_keep_below_one(tmp_path):  # S3-07
    (tmp_path / "run-20260701-000000.json").write_text("{}")
    for bad in (0, -1):
        with pytest.raises(ValueError, match="keep must be >= 1"):
            prune_out_dir(str(tmp_path), keep=bad)
    assert (tmp_path / "run-20260701-000000.json").exists()  # nothing deleted


# --------------------------------------------------- provider matrix (E20-11)


class HostedClient(HappyClient):
    """Hosted-style fake: describe response discloses the boundary crossing."""

    def describe(self, **kwargs):
        return {
            "alt_text_draft": "A photo.",
            "visual_facts": {"objects": []},
            "provider_disclosure": {"provider": "hosted", "left_service_boundary": True},
        }


def test_fetch_stamps_provider_and_cost_into_provenance(images_dir):
    record = fetch_run_record(
        _manifest(2),
        str(images_dir),
        HostedClient(),
        head_sha="f" * 40,
        provider="hosted_gpt4o",
        cost_per_image_usd=0.01,
    )
    prov = record["provenance"]
    assert prov["provider"] == "hosted_gpt4o"
    assert prov["cost_per_image_usd"] == 0.01
    assert prov["est_cost_usd"] == pytest.approx(0.02)


def test_hosted_items_carry_boundary_disclosure_and_latency(images_dir):
    record = fetch_run_record(_manifest(2), str(images_dir), HostedClient(), head_sha="f" * 40, provider="hosted_gpt4o")
    for item in record["items"]:
        assert item["describe"]["provider_disclosure"]["left_service_boundary"] is True
        assert item["latency_s"] >= 0


def test_max_cost_aborts_before_further_paid_calls(images_dir):
    with pytest.raises(MaxCostExceededError) as excinfo:
        fetch_run_record(
            _manifest(5),
            str(images_dir),
            HostedClient(),
            head_sha="f" * 40,
            provider="hosted_gpt4o",
            cost_per_image_usd=1.0,
            max_cost_usd=2.5,
        )
    partial = excinfo.value.partial_record
    assert partial["aborted"] is True
    assert len(partial["items"]) == 2  # third paid call would exceed the cap; never made


def test_provider_run_record_scores_with_existing_reports(images_dir):
    manifest = _manifest(2)
    record = fetch_run_record(manifest, str(images_dir), HostedClient(), head_sha="f" * 40, provider="hosted_gpt4o")
    entries = [e.model_dump() for e in manifest.entries]
    json_doc, md_doc = build_reports(record, entries)
    assert json_doc and md_doc


def test_cli_provider_flag_is_accepted_and_live_gated(monkeypatch):
    monkeypatch.delenv("ACX_EVAL_LIVE", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        main(["fetch", "--provider", "hosted_gpt4o", "--cost-per-image", "0.01", "--max-cost", "1.0"])
    assert "ACX_EVAL_LIVE" in str(excinfo.value)


def test_stall_abort_preserves_partial_record(images_dir):
    client = FlakyClient({f"img-{i}.jpg" for i in range(1, 6)})
    with pytest.raises(BoundedStallError) as excinfo:
        fetch_run_record(_manifest(5), str(images_dir), client, head_sha="f" * 40, stall_limit=3)
    partial = excinfo.value.partial_record
    assert partial["aborted"] is True
    assert len(partial["items"]) == 3
    assert all(item["error"] for item in partial["items"])
