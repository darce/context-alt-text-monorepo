"""VLM-2A Slice 3: CLI fetch loop (per-item isolation, bounded stall rg-007) + retention."""

import json

import pytest

from scripts.eval_harness.cli import (
    BoundedStallError,
    MaxCostExceededError,
    ProviderMismatchError,
    fetch_run_record,
    main,
    prune_out_dir,
)
from scripts.eval_harness.manifest import GoldenEntry, GoldenManifest
from scripts.eval_harness.report import build_reports


def _manifest(n: int) -> GoldenManifest:
    sha = "a" * 64
    return GoldenManifest(
        manifest_version=2,
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

    model_id = "gpt-4o-mini"
    cached = False

    def describe(self, **kwargs):
        return {
            "alt_text_draft": "A photo.",
            "visual_facts": {"objects": []},
            "model_id": self.model_id,
            "cached": self.cached,
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


def test_cached_describes_are_not_billed(images_dir):
    # Cache-hit describes never reach the provider; est_cost must exclude them (R2A-01).
    client = HostedClient()
    client.cached = True
    record = fetch_run_record(
        _manifest(3),
        str(images_dir),
        client,
        head_sha="f" * 40,
        provider="hosted_gpt4o",
        cost_per_image_usd=1.0,
    )
    assert record["provenance"]["paid_describe_calls"] == 0
    assert record["provenance"]["est_cost_usd"] == 0.0


def test_provider_mismatch_on_wrong_hosted_model(images_dir):
    # provider_disclosure alone cannot disambiguate WHICH hosted profile; a response
    # model_id that contradicts the claimed profile must abort (R2A-03).
    client = HostedClient()
    client.model_id = "gpt-4o"  # claimed profile hosted_gpt4o expects gpt-4o-mini
    with pytest.raises(ProviderMismatchError):
        fetch_run_record(_manifest(2), str(images_dir), client, head_sha="f" * 40, provider="hosted_gpt4o")


class SlowIdentitiesClient(HostedClient):
    """Describe is instant; the recognition wait dominates the item wall time."""

    def wait_job(self, job_id):
        import time as _time

        _time.sleep(0.05)
        return {"status": "completed"}


def test_latency_times_describe_only(images_dir):
    # latency_s must not absorb analyze/wait_job/identity polling (R2A-02).
    record = fetch_run_record(
        _manifest(1), str(images_dir), SlowIdentitiesClient(), head_sha="f" * 40, provider="hosted_gpt4o"
    )
    assert record["items"][0]["latency_s"] < 0.05


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


def test_provider_mismatch_aborts_with_partial_record(images_dir):
    # HappyClient's describe has no provider_disclosure — a --provider claim the
    # service does not corroborate must abort, never stamp mislabeled evidence (rg-015).
    with pytest.raises(ProviderMismatchError) as excinfo:
        fetch_run_record(_manifest(3), str(images_dir), HappyClient(), head_sha="f" * 40, provider="hosted_gpt4o")
    partial = excinfo.value.partial_record
    assert partial["aborted"] is True
    assert len(partial["items"]) == 1  # aborted on the first uncorroborated item


def test_max_cost_counts_prior_matrix_spend(images_dir):
    # spent_usd carries earlier matrix legs: 2.0 already spent + 1.0/image with a
    # 2.5 cap means the first paid call of this leg would exceed the cap.
    with pytest.raises(MaxCostExceededError) as excinfo:
        fetch_run_record(
            _manifest(3),
            str(images_dir),
            HostedClient(),
            head_sha="f" * 40,
            provider="hosted_gpt4o",
            cost_per_image_usd=1.0,
            max_cost_usd=2.5,
            spent_usd=2.0,
        )
    assert len(excinfo.value.partial_record["items"]) == 0


def test_cli_max_cost_requires_cost_per_image():
    with pytest.raises(SystemExit) as excinfo:
        main(["fetch", "--provider", "hosted_gpt4o", "--max-cost", "1.0"])
    assert excinfo.value.code == 2  # argparse parser.error


def test_cli_provider_rejects_unknown_and_empty_values():
    for bad in ("florence_small", "not_a_profile", ""):
        with pytest.raises(SystemExit) as excinfo:
            main(["fetch", "--provider", bad])
        assert excinfo.value.code == 2  # argparse type error, before any live work


def test_cli_score_rejects_provider_flags(tmp_path):
    record = tmp_path / "run-x.json"
    record.write_text("{}")
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--run-record", str(record), "--provider", "hosted_gpt4o"])
    assert excinfo.value.code == 2  # unrecognized argument: score is pure/offline


def test_stall_abort_preserves_partial_record(images_dir):
    client = FlakyClient({f"img-{i}.jpg" for i in range(1, 6)})
    with pytest.raises(BoundedStallError) as excinfo:
        fetch_run_record(_manifest(5), str(images_dir), client, head_sha="f" * 40, stall_limit=3)
    partial = excinfo.value.partial_record
    assert partial["aborted"] is True
    assert len(partial["items"]) == 3
    assert all(item["error"] for item in partial["items"])


def test_extract_identities_rejects_non_list_payload():  # VLM-2C-R2-S5-BR-02
    import pytest

    from scripts.eval_harness.cli import _extract_identities
    from scripts.eval_harness.remote_client import RemoteClientError

    with pytest.raises(RemoteClientError, match="media_identities"):
        _extract_identities({"error": "boom"}, media_id=1)


def test_extract_identities_uses_is_auto_label_wire_shape():  # S8-01
    """Mirror MediaIdentityService.list_by_media_ids row shape (stores.py)."""
    from scripts.eval_harness.cli import _extract_identities

    payload = [
        {
            "identity_id": "id-1",
            "media_id": 7,
            "cluster_id": "c1",
            "cluster_label": "Alice Example",
            "is_auto_label": False,
            "clustering_pending": False,
            "bbox": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
            "confidence": 0.9,
            "media_url": None,
        },
        {
            "identity_id": "id-2",
            "media_id": 7,
            "cluster_id": "c2",
            "cluster_label": "Bob Auto",
            "is_auto_label": True,  # unconfirmed auto-propagated — must not count
            "clustering_pending": False,
            "bbox": {"x": 0.5, "y": 0.1, "width": 0.2, "height": 0.2},
            "confidence": 0.8,
            "media_url": None,
        },
        {
            "identity_id": "id-3",
            "media_id": 99,
            "cluster_id": "c3",
            "cluster_label": "Other Media",
            "is_auto_label": False,
            "clustering_pending": False,
            "bbox": {"x": 0.0, "y": 0.0, "width": 0.1, "height": 0.1},
            "confidence": 0.7,
            "media_url": None,
        },
    ]
    names, face_count = _extract_identities(payload, media_id=7)
    assert face_count == 2
    assert names == ["Alice Example"]


def test_fetch_resolves_nfd_image_path(tmp_path):  # S6-03 / S7-01
    """Fetch walk must use the same NFC/NFD resolve as hash verify."""
    import unicodedata

    from scripts.eval_harness.cli import fetch_run_record
    from scripts.eval_harness.manifest import GoldenEntry, GoldenManifest

    nfd_name = unicodedata.normalize("NFD", "Breiðamerkurjökull.jpg")
    nfc_name = unicodedata.normalize("NFC", "Breiðamerkurjökull.jpg")
    assert nfd_name != nfc_name  # otherwise the test is vacuous on this platform
    images = tmp_path / "mock_images"
    images.mkdir()
    # On-disk form is NFD; manifest path is NFC (the rsync flip S1-07 documents).
    (images / nfd_name).write_bytes(b"fake-bytes")
    manifest = GoldenManifest(
        manifest_version=2,
        roster=["Alice Example"],
        entries=[
            GoldenEntry(
                path=f"mock_images/{nfc_name}",
                sha256="a" * 64,
                media_id=1,
                face_count=0,
                present_identities=[],
                context_pack={"title": "t"},
                must_right=[],
                easy_wrong=[],
                policy={"recognition_enabled": True},
            )
        ],
    )
    record = fetch_run_record(manifest, str(tmp_path), HappyClient(), head_sha="f" * 40)
    assert record["items"][0]["error"] is None


def test_cli_limit_and_keep_reject_non_positive():  # S8-03 / S6-02
    for flag, bad in (("--limit", "0"), ("--limit", "-3"), ("--keep", "0"), ("--keep", "-1")):
        with pytest.raises(SystemExit) as excinfo:
            main(["fetch", flag, bad])
        assert excinfo.value.code == 2


def test_cmd_score_exits_nonzero_when_items_failed(tmp_path, monkeypatch):  # S7-01
    from scripts.eval_harness import cli as cli_mod
    from scripts.eval_harness.schema import SCHEMA, DocKind

    manifest_path = tmp_path / "golden.json"
    entries = [
        {
            "path": "mock_images/img-1.jpg",
            "sha256": "a" * 64,
            "media_id": 1,
            "face_count": 0,
            "present_identities": [],
            "context_pack": {},
            "base_caption": "",
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
        }
    ]
    manifest_path.write_text(json.dumps({"manifest_version": 2, "roster": ["Alice Example"], "entries": entries}))
    record_path = tmp_path / "run-x.json"
    record_path.write_text(
        json.dumps(
            {
                "schema": SCHEMA,
                "kind": DocKind.RUN_RECORD.value,
                "provenance": {"manifest_sha256": "0" * 64, "base_url": "x", "head_sha": "f" * 40, "started_at": "t"},
                "items": [
                    {
                        "media_id": 1,
                        "path": "mock_images/img-1.jpg",
                        "describe": None,
                        "identities": [],
                        "face_count": 0,
                        "error": "FileNotFoundError: missing",
                        "latency_s": None,
                    }
                ],
            }
        )
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)])
    assert excinfo.value.code != 0
    assert "not scored" in str(excinfo.value)
