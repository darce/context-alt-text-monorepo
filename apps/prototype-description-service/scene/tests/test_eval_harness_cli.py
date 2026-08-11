"""VLM-2A Slice 3: CLI fetch loop (per-item isolation, bounded stall rg-007) + retention."""

import json
from pathlib import Path

import pytest

from scripts.eval_harness.cli import (
    BoundedStallError,
    MaxCostExceededError,
    ProviderMismatchError,
    fetch_run_record,
    main,
    prune_out_dir,
)
from scripts.eval_harness.landmark_cache import LandmarkCacheProvenance
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
    # A-08: every item stamps image dimensions (None when bytes are not a real image).
    assert all("image_width" in item and "image_height" in item for item in record["items"])
    # A-07: ordering source stamped once identities extracted.
    assert all(item.get("identity_ordering") == "positional" for item in record["items"])


def test_fetch_persists_image_dimensions_from_pixels(tmp_path):
    """A-08: absolute-pixel bboxes need image_width/height for positional scoring."""
    from io import BytesIO

    from PIL import Image

    from scripts.eval_harness.cli import fetch_run_record
    from scripts.eval_harness.manifest import GoldenEntry, GoldenManifest

    images = tmp_path / "mock_images"
    images.mkdir()
    buf = BytesIO()
    Image.new("RGB", (64, 48), color=(10, 20, 30)).save(buf, format="PNG")
    (images / "img-1.jpg").write_bytes(buf.getvalue())
    manifest = GoldenManifest(
        manifest_version=2,
        roster=["Alice Example"],
        entries=[
            GoldenEntry(
                path="mock_images/img-1.jpg",
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
    item = record["items"][0]
    assert item["image_width"] == 64
    assert item["image_height"] == 48


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
    identities, face_count, ordering = _extract_identities(payload, media_id=7)
    assert face_count == 2
    assert ordering == "positional"
    assert identities == [
        {
            "name": "Alice Example",
            "bbox": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
            "unpositioned": False,
            "identity_id": "id-1",  # A-09: wire identity_id preserved
        }
    ]


def test_extract_identities_orders_left_to_right_not_alphabetically():
    """Group-shot names bind by face-box x — order must differ from BOTH alpha sorts.

    A-11 / TEST-15: with two names, L→R that is not alphabetical is always reverse-
    alphabetical, so the fixture could not discriminate positional binding from a
    reverse-alpha sort. Three names make alpha, reverse-alpha, and L→R all distinct.
    """
    from scripts.eval_harness.cli import _extract_identities

    # Alpha: Amy, Cam, Zoe. Reverse: Zoe, Cam, Amy. L→R by x: Cam, Amy, Zoe.
    payload = [
        {
            "identity_id": "id-amy",
            "media_id": 1,
            "cluster_label": "Amy Mid",
            "is_auto_label": False,
            "bbox": {"x": 100, "y": 40, "width": 50, "height": 60},
        },
        {
            "identity_id": "id-zoe",
            "media_id": 1,
            "cluster_label": "Zoe Right",
            "is_auto_label": False,
            "bbox": {"x": 200, "y": 40, "width": 50, "height": 60},
        },
        {
            "identity_id": "id-cam",
            "media_id": 1,
            "cluster_label": "Cam Left",
            "is_auto_label": False,
            "bbox": {"x": 10, "y": 40, "width": 50, "height": 60},
        },
    ]
    identities, face_count, ordering = _extract_identities(payload, media_id=1)
    assert face_count == 3
    assert ordering == "positional"
    names = [row["name"] for row in identities]
    assert names == ["Cam Left", "Amy Mid", "Zoe Right"]
    assert names != sorted(names)  # not alphabetical
    assert names != sorted(names, reverse=True)  # not reverse-alphabetical (A-11)
    assert [row["identity_id"] for row in identities] == ["id-cam", "id-amy", "id-zoe"]
    assert all(row["unpositioned"] is False for row in identities)


def test_extract_identities_unpositioned_after_positioned_no_fabricated_bbox():
    """Missing/malformed bbox rows stay, mark unpositioned, sort after positioned (rg-015).

    A-07: ordering_source must be ``degraded`` (loud), not silent alpha fallback.
    """
    from scripts.eval_harness.cli import _extract_identities

    payload = [
        {
            "identity_id": "id-bad",
            "media_id": 1,
            "cluster_label": "Charlie Missing",
            "is_auto_label": False,
            "bbox": {"x": 5, "y": 5, "w": 10, "h": 10},  # w/h never accepted
        },
        {
            "identity_id": "id-ok",
            "media_id": 1,
            "cluster_label": "Bob Placed",
            "is_auto_label": False,
            "bbox": {"x": 80, "y": 10, "width": 40, "height": 40},
        },
        {
            "identity_id": "id-none",
            "media_id": 1,
            "cluster_label": "Alice NoBox",
            "is_auto_label": False,
            # bbox absent
        },
    ]
    identities, face_count, ordering = _extract_identities(payload, media_id=1)
    assert face_count == 3
    assert ordering == "degraded"  # A-07: loud, not silent
    assert [row["name"] for row in identities] == [
        "Bob Placed",
        "Alice NoBox",
        "Charlie Missing",
    ]
    assert identities[0]["unpositioned"] is False
    assert identities[0]["bbox"] == {"x": 80, "y": 10, "width": 40, "height": 40}
    assert identities[0]["identity_id"] == "id-ok"
    assert identities[1]["unpositioned"] is True and identities[1]["bbox"] is None
    assert identities[2]["unpositioned"] is True and identities[2]["bbox"] is None


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


_W1_LOCAL_PATH = "localwp/uploads/jane-doe-birthday.jpg"
_W1_LOCAL_NAME = "Jane Doe Private"
_W1_PUBLIC_PATH = "celebs01/obama-podium.jpg"
_W1_PUBLIC_NAME = "Barack Obama"
_W1_INTERNAL_BASE_URL = "https://acx-backend.internal.example.ts.net"


def _write_score_manifest(tmp_path, entries, roster, name="golden.json"):
    """Write a v2 golden manifest and return (path, real score-time sha256)."""
    from scripts.eval_harness.cli import _manifest_sha
    from scripts.eval_harness.manifest import load_manifest

    manifest_path = tmp_path / name
    manifest_path.write_text(
        json.dumps({"manifest_version": 2, "roster": roster, "entries": entries})
    )
    return manifest_path, _manifest_sha(load_manifest(str(manifest_path)))


def _w1_audience_manifest_and_record(tmp_path):
    """One publishable celeb (media 10) + one local-only personal photo (media 20)."""
    from scripts.eval_harness.schema import SCHEMA, DocKind

    entries = [
        {
            "path": _W1_PUBLIC_PATH,
            "sha256": "a" * 64,
            "media_id": 10,
            "face_count": 1,
            "present_identities": [_W1_PUBLIC_NAME],
            "context_pack": {},
            "base_caption": "",
            "must_right": [_W1_PUBLIC_NAME],
            # Non-empty easy_wrong so independent vacuity gates do not fire before
            # the wrong-name floor this fixture is meant to exercise (F1-1).
            "easy_wrong": [_W1_LOCAL_NAME],
            "policy": {"recognition_enabled": True},
            "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
        },
        {
            "path": _W1_LOCAL_PATH,
            "sha256": "b" * 64,
            "media_id": 20,
            "face_count": 1,
            "present_identities": [_W1_LOCAL_NAME],
            "context_pack": {},
            "base_caption": "",
            "must_right": [_W1_LOCAL_NAME],
            "easy_wrong": [_W1_PUBLIC_NAME],
            "policy": {"recognition_enabled": True},
            "provenance": {"source": "localwp", "license": "consented", "publishable": False},
        },
    ]
    manifest_path, manifest_sha = _write_score_manifest(
        tmp_path, entries, [_W1_PUBLIC_NAME, _W1_LOCAL_NAME]
    )
    record_path = tmp_path / "run-x.json"
    record_path.write_text(
        json.dumps(
            {
                "schema": SCHEMA,
                "kind": DocKind.RUN_RECORD.value,
                "provenance": {
                    "manifest_sha256": manifest_sha,
                    "base_url": _W1_INTERNAL_BASE_URL,
                    "head_sha": "f" * 40,
                    "started_at": "t",
                },
                "items": [
                    {
                        "media_id": 10,
                        "path": _W1_PUBLIC_PATH,
                        "describe": {
                            "alt_text_draft": f"{_W1_PUBLIC_NAME} at a podium.",
                            "visual_facts": {"objects": []},
                        },
                        "identities": [{"name": _W1_PUBLIC_NAME, "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0}, "unpositioned": False}],
                        "face_count": 1,
                        "error": None,
                    },
                    {
                        "media_id": 20,
                        "path": _W1_LOCAL_PATH,
                        "describe": {
                            "alt_text_draft": f"{_W1_LOCAL_NAME} at a party.",
                            "visual_facts": {"objects": []},
                        },
                        "identities": [{"name": "Wrong Celebrity", "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0}, "unpositioned": False}],
                        "face_count": 1,
                        "error": None,
                    },
                ],
            }
        )
    )
    return manifest_path, record_path


def test_cmd_score_public_audience_emits_redacted_public_artifact(tmp_path, monkeypatch):  # VLM-6 S5 W1
    """--audience public writes a distinct <run>-report.public.{json,md} with only
    publishable entries and no local path/name leak (VLM6-C-01 / VLM6-F-03).

    Fixture keeps a local wrong-name row so public redaction of wrong_names is
    exercised; VLM-6 S2A wrong-name floor therefore exits non-zero *after*
    artifacts are written — catch SystemExit and still assert the files.
    """
    manifest_path, record_path = _w1_audience_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path), "--audience", "public"])
    assert excinfo.value.code != 0
    assert "wrong-name" in str(excinfo.value).lower()

    public_json = (tmp_path / "run-x-report.public.json").read_text()
    public_md = (tmp_path / "run-x-report.public.md").read_text()
    scored = json.loads(public_json)
    assert {p["media_id"] for p in scored["per_image"]} == {10}  # only publishable scored
    assert scored["redaction"]["withheld_items"] == 1
    for blob in (public_json, public_md):
        assert _W1_LOCAL_PATH not in blob
        assert _W1_LOCAL_NAME not in blob
        assert "Wrong Celebrity" not in blob  # wrong_names pair from the local item
        assert _W1_INTERNAL_BASE_URL not in blob  # run-level endpoint redacted (VLM6-S5-BR-01)
    assert _W1_PUBLIC_NAME in public_json
    # The full LOCAL report is still written for operator triage, unredacted.
    local_json = (tmp_path / "run-x-report.json").read_text()
    assert _W1_LOCAL_PATH in local_json
    assert "redaction" not in json.loads(local_json)


def test_cmd_score_default_local_emits_no_public_artifact(tmp_path, monkeypatch):  # VLM-6 S5 W1
    """Default audience stays byte-compatible: no public artifact is produced.

    Fixture includes a wrong-name row; score exits non-zero on the S2A floor
    after writing the local report (artifacts still land).
    """
    manifest_path, record_path = _w1_audience_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)])
    assert excinfo.value.code != 0
    assert "wrong-name" in str(excinfo.value).lower()
    assert (tmp_path / "run-x-report.json").exists()
    assert not (tmp_path / "run-x-report.public.json").exists()
    assert not (tmp_path / "run-x-report.public.md").exists()


def test_cmd_score_exits_nonzero_when_items_failed(tmp_path, monkeypatch):  # S7-01
    from scripts.eval_harness.schema import SCHEMA, DocKind

    entries = [
        {
            "path": "mock_images/img-1.jpg",
            "sha256": "a" * 64,
            "media_id": 1,
            "face_count": 0,
            "present_identities": [],
            "context_pack": {},
            "base_caption": "",
            # Non-empty rubric so empty-rubric does not fire before failed-items.
            "must_right": ["Alice Example"],
            "easy_wrong": ["Bob Builder"],
            "policy": {"recognition_enabled": True},
        }
    ]
    manifest_path, manifest_sha = _write_score_manifest(
        tmp_path, entries, ["Alice Example", "Bob Builder"]
    )
    record_path = tmp_path / "run-x.json"
    record_path.write_text(
        json.dumps(
            {
                "schema": SCHEMA,
                "kind": DocKind.RUN_RECORD.value,
                "provenance": {
                    "manifest_sha256": manifest_sha,
                    "base_url": "x",
                    "head_sha": "f" * 40,
                    "started_at": "t",
                },
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
    # Gate names itself so a red run says which one fired (VLM-6 S2A).
    assert "failed-items" in str(excinfo.value).lower()


def _wrong_name_everywhere_manifest_and_record(tmp_path):
    """Every scored image asserts a wrong human name (zero failed items).

    Used to prove the wrong-name floor gate CAN go red: pre-S2A, score exited 0
    for this catastrophic case (wrong name on 100% of images).

    Captions satisfy Must-Right so only the wrong-name floor fires (not must-right
    failures or empty-rubric).
    """
    from scripts.eval_harness.schema import SCHEMA, DocKind

    entries = [
        {
            "path": "mock_images/alice.jpg",
            "sha256": "a" * 64,
            "media_id": 1,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "context_pack": {},
            "base_caption": "",
            "must_right": ["Alice Example"],
            "easy_wrong": ["Bob Builder"],
            "policy": {"recognition_enabled": True},
        },
        {
            "path": "mock_images/bob.jpg",
            "sha256": "b" * 64,
            "media_id": 2,
            "face_count": 1,
            "present_identities": ["Bob Builder"],
            "context_pack": {},
            "base_caption": "",
            "must_right": ["Bob Builder"],
            "easy_wrong": ["Alice Example"],
            "policy": {"recognition_enabled": True},
        },
    ]
    manifest_path, manifest_sha = _write_score_manifest(
        tmp_path, entries, ["Alice Example", "Bob Builder"]
    )
    record_path = tmp_path / "run-wrong.json"
    record_path.write_text(
        json.dumps(
            {
                "schema": SCHEMA,
                "kind": DocKind.RUN_RECORD.value,
                "provenance": {
                    "manifest_sha256": manifest_sha,
                    "base_url": "https://example.test",
                    "head_sha": "f" * 40,
                    "started_at": "t",
                },
                "items": [
                    {
                        "media_id": 1,
                        "path": "mock_images/alice.jpg",
                        "describe": {
                            # Caption keeps must_right; only face identities are wrong.
                            "alt_text_draft": "Alice Example outdoors.",
                            "visual_facts": {"objects": []},
                        },
                        # Wrong name on every image (Alice image labeled Bob).
                        "identities": [
                            {
                                "name": "Bob Builder",
                                "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
                                "unpositioned": False,
                            }
                        ],
                        "face_count": 1,
                        "error": None,
                    },
                    {
                        "media_id": 2,
                        "path": "mock_images/bob.jpg",
                        "describe": {
                            "alt_text_draft": "Bob Builder on a beach.",
                            "visual_facts": {"objects": []},
                        },
                        # Wrong name on every image (Bob image labeled Alice).
                        "identities": [
                            {
                                "name": "Alice Example",
                                "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
                                "unpositioned": False,
                            }
                        ],
                        "face_count": 1,
                        "error": None,
                    },
                ],
            }
        )
    )
    return manifest_path, record_path


def test_cmd_score_exits_nonzero_when_wrong_name_rate_breaches_floor(tmp_path, monkeypatch):
    """VLM-6 S2A: wrong name on 100% of images must fail score (TEST-15 red-capable).

    Pre-fix empirical false-green: this record exited 0. Gate must name itself
    distinctly from the failed-items gate and cite rate, floor, and report path.
    """
    from scripts.eval_harness.report import WRONG_NAME_RATE_FLOOR

    manifest_path, record_path = _wrong_name_everywhere_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)])
    msg = str(excinfo.value)
    assert excinfo.value.code != 0
    assert "wrong-name" in msg.lower()
    assert "floor" in msg.lower()
    assert str(WRONG_NAME_RATE_FLOOR) in msg
    assert "run-wrong-report.json" in msg
    # Distinct from the failed-items gate message.
    assert "not scored" not in msg
    report = json.loads((tmp_path / "run-wrong-report.json").read_text())
    assert report["verdict"]["verdict"] == "fail"
    assert report["verdict"]["wrong_name_rate"] > WRONG_NAME_RATE_FLOOR
    assert report["verdict"]["wrong_name_rate_floor"] == WRONG_NAME_RATE_FLOOR
    assert report["verdict"]["reasons"]


def test_cmd_score_exits_zero_when_no_wrong_names_and_no_failures(tmp_path, monkeypatch):
    """Complementary green path: clean identities + no failures → score exits 0."""
    from scripts.eval_harness.schema import SCHEMA, DocKind

    entries = [
        {
            "path": "mock_images/alice.jpg",
            "sha256": "a" * 64,
            "media_id": 1,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "context_pack": {},
            "base_caption": "",
            "must_right": ["Alice Example"],
            "easy_wrong": ["Bob Builder"],
            "policy": {"recognition_enabled": True},
        }
    ]
    manifest_path, manifest_sha = _write_score_manifest(
        tmp_path, entries, ["Alice Example", "Bob Builder"]
    )
    record_path = tmp_path / "run-clean.json"
    record_path.write_text(
        json.dumps(
            {
                "schema": SCHEMA,
                "kind": DocKind.RUN_RECORD.value,
                "provenance": {
                    "manifest_sha256": manifest_sha,
                    "base_url": "https://example.test",
                    "head_sha": "f" * 40,
                    "started_at": "t",
                },
                "items": [
                    {
                        "media_id": 1,
                        "path": "mock_images/alice.jpg",
                        "describe": {
                            "alt_text_draft": "Alice Example outdoors.",
                            "visual_facts": {"objects": []},
                        },
                        "identities": [
                            {
                                "name": "Alice Example",
                                "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
                                "unpositioned": False,
                            }
                        ],
                        "face_count": 1,
                        "error": None,
                    }
                ],
            }
        )
    )
    monkeypatch.chdir(tmp_path)
    main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)])
    report = json.loads((tmp_path / "run-clean-report.json").read_text())
    assert report["verdict"]["verdict"] == "pass"
    assert report["verdict"]["wrong_name_rate"] == 0.0
    assert report["verdict"]["reasons"] == []


def _clean_score_manifest_and_record(tmp_path):
    """Minimal clean caption run-record + manifest for score determinism tests."""
    from scripts.eval_harness.schema import SCHEMA, DocKind

    entries = [
        {
            "path": "mock_images/alice.jpg",
            "sha256": "a" * 64,
            "media_id": 1,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "context_pack": {},
            "base_caption": "",
            "must_right": ["Alice Example"],
            "easy_wrong": ["Bob Builder"],
            "policy": {"recognition_enabled": True},
        }
    ]
    manifest_path, manifest_sha = _write_score_manifest(
        tmp_path, entries, ["Alice Example", "Bob Builder"]
    )
    record_path = tmp_path / "run-det.json"
    record_path.write_text(
        json.dumps(
            {
                "schema": SCHEMA,
                "kind": DocKind.RUN_RECORD.value,
                "provenance": {
                    "manifest_sha256": manifest_sha,
                    "base_url": "https://example.test",
                    "head_sha": "f" * 40,
                    "started_at": "t",
                },
                "items": [
                    {
                        "media_id": 1,
                        "path": "mock_images/alice.jpg",
                        "describe": {
                            "alt_text_draft": "Alice Example outdoors.",
                            "visual_facts": {"objects": []},
                        },
                        "identities": [
                            {
                                "name": "Alice Example",
                                "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
                                "unpositioned": False,
                            }
                        ],
                        "face_count": 1,
                        "error": None,
                    }
                ],
            }
        )
    )
    return manifest_path, record_path


def test_cli_score_check_determinism_runs_cross_process_guard(tmp_path, monkeypatch, capsys):
    """--check-determinism on score drives the SHIPPED cross-process guard (VLM-6 S2A item 3).

    Clean case: re-score from the persisted run-record under varied PYTHONHASHSEED
    must pass. Reaching report write without SystemExit means the guard ran and
    matched — not the old same-process double build_reports call.
    """
    from scripts.eval_harness import cli as cli_mod

    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)
    main(
        [
            "score",
            "--manifest",
            str(manifest_path),
            "--run-record",
            str(record_path),
            "--check-determinism",
        ]
    )
    assert (tmp_path / "run-det-report.json").exists()
    out = capsys.readouterr().out
    assert "cross-process" in out
    assert "determinism check passed" in out

    # Flag still recognized when required args are missing (parse error, not silent ignore).
    with pytest.raises(SystemExit) as missing:
        main(["score", "--check-determinism"])
    assert missing.value.code == 2


def test_cli_score_determinism_guard_detects_mutated_persisted_anchor(tmp_path, monkeypatch):
    """Non-vacuity (TEST-15): mutating the persisted run-record between baseline and
    subprocess re-score must make the cross-process guard report FAILED.

    Pre-fix false-green: in-process double build_reports never re-reads disk, so a
    mutated anchor still "passed". Against that implementation this test must go red.
    """
    from scripts.eval_harness import cli as cli_mod

    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)

    real_run = cli_mod.subprocess.run

    def _mutate_then_run(*args, **kwargs):
        # Corrupt the persisted anchor after in-process baseline, before subprocess score.
        payload = json.loads(record_path.read_text())
        item = payload["items"][0]
        item["describe"] = {
            "alt_text_draft": "MUTATED CAPTION FOR DETERMINISM GUARD",
            "visual_facts": {"objects": ["definitely-not-in-baseline"]},
        }
        # Also flip identity so identification surfaces diverge if captions alone are ignored.
        item["identities"] = [
            {
                "name": "Bob Builder",
                "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
                "unpositioned": False,
            }
        ]
        record_path.write_text(json.dumps(payload))
        return real_run(*args, **kwargs)

    monkeypatch.setattr(cli_mod.subprocess, "run", _mutate_then_run)
    with pytest.raises(SystemExit) as exc:
        cli_mod._check_score_determinism_cross_process(record_path, str(manifest_path))
    msg = str(exc.value)
    assert "determinism check FAILED" in msg
    assert "cross-process" in msg


# --- VLM-6 S2A item 4: four corruption discrimination guards (TEST-15) ---
#
# Adversarial review r0811e7f1 ran these four mutations against
# ``score --check-determinism`` and all four exited 0. Each guard asserts both
# non-zero exit AND a message that names its corruption class so one gate firing
# cannot make the other three look green.


def _bbox():
    return {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0}


def _score_identity(name: str) -> dict:
    return {"name": name, "bbox": _bbox(), "unpositioned": False}


def _corpus_entries(n: int, *, with_rubric: bool) -> tuple[list[str], list[dict]]:
    roster: list[str] = []
    entries: list[dict] = []
    for i in range(1, n + 1):
        name = f"Person {i}"
        roster.append(name)
        entries.append(
            {
                "path": f"mock_images/p{i}.jpg",
                "sha256": f"{i:064x}",
                "media_id": i,
                "face_count": 1,
                "present_identities": [name],
                "context_pack": {},
                "base_caption": "",
                "must_right": [name] if with_rubric else [],
                "easy_wrong": [f"Person {(i % n) + 1}"] if with_rubric else [],
                "policy": {"recognition_enabled": True},
            }
        )
    return roster, entries


def _score_run_record(entries: list[dict], *, caption_fn, identity_fn, manifest_sha: str, name: str = "run.json"):
    from scripts.eval_harness.schema import SCHEMA, DocKind

    items = []
    for entry in entries:
        items.append(
            {
                "media_id": entry["media_id"],
                "path": entry["path"],
                "describe": {
                    "alt_text_draft": caption_fn(entry),
                    "visual_facts": {"objects": []},
                },
                "identities": identity_fn(entry),
                "face_count": entry["face_count"],
                "error": None,
            }
        )
    return {
        "schema": SCHEMA,
        "kind": DocKind.RUN_RECORD.value,
        "provenance": {
            "manifest_sha256": manifest_sha,
            "base_url": "https://example.test",
            "head_sha": "f" * 40,
            "started_at": "t",
        },
        "items": items,
    }


def test_score_guard_caption_corruption_fails_must_right_gate(tmp_path, monkeypatch):
    """Corruption 1: every caption collapsed → must-right failures gate (named).

    F1b-2 / F1-12: simple predicate must_right_failed_images > 0 under default
    --rubric-gate enforce. Fixture mirrors golden's 34/37 shape (not all-rubric):
    at least one entry has empty must_right + empty present_identities so plain
    garbage cannot rely on mean_gated collapsing to 0.0 (F1-11 synthetic gap).
    """
    roster, entries = _corpus_entries(6, with_rubric=True)
    # Golden-shaped mixed rubric: one no-must_right / no-present-identities entry
    # still contributes gated 1.0 for plain garbage (mean != 0.0).
    entries[-1]["must_right"] = []
    entries[-1]["present_identities"] = []
    assert entries[-1]["easy_wrong"]  # empty-rubric gate must not fire
    manifest_path, manifest_sha = _write_score_manifest(tmp_path, entries, roster)
    record = _score_run_record(
        entries,
        caption_fn=lambda _e: "xxxxx yyyyy zzzzz qqqqq",
        identity_fn=lambda e: (
            [_score_identity(e["present_identities"][0])] if e["present_identities"] else []
        ),
        manifest_sha=manifest_sha,
        name="run-caption-corrupt.json",
    )
    record_path = tmp_path / "run-caption-corrupt.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)])
    msg = str(excinfo.value)
    assert excinfo.value.code != 0
    assert "must-right failures" in msg.lower()
    assert "caption" in msg.lower()
    # Must name this class distinctly from the other three guards.
    assert "wrong-name" not in msg.lower()
    assert "manifest-mismatch" not in msg.lower()
    assert "empty-rubric" not in msg.lower()


def test_score_guard_rubric_gate_skip_bypasses_must_right_gate(tmp_path, monkeypatch):
    """F1b-2: --rubric-gate skip bypasses must-right gate only (seeded/shakedown shape).

    Un-flagged seeded shape (generic captions, mixed must_right) exits non-zero
    under default enforce. With --rubric-gate skip the same record exits 0 and
    the artifact records rubric_gate=skip. Other gates remain active.
    """
    roster, entries = _corpus_entries(6, with_rubric=True)
    # Leave one entry without must_right and without present identities so
    # generic caption scores gated 1.0 (seeded no-name shape on real golden).
    entries[-1]["must_right"] = []
    entries[-1]["present_identities"] = []
    assert entries[-1]["easy_wrong"]  # independent vacuity still non-empty
    manifest_path, manifest_sha = _write_score_manifest(tmp_path, entries, roster)
    record = _score_run_record(
        entries,
        # Avoid the token "person" — synthetic easy_wrong names are "Person N"
        # and token-level traps would fire the wrong-name floor gate.
        caption_fn=lambda _e: "A human standing outdoors near greenery.",
        identity_fn=lambda _e: [],
        manifest_sha=manifest_sha,
        name="run-seeded-shape.json",
    )
    record_path = tmp_path / "run-seeded-shape.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    # Default enforce: un-flagged seeded shape must exit non-zero (F1-12).
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)])
    assert excinfo.value.code != 0
    assert "must-right failures" in str(excinfo.value).lower()
    # Explicit skip: harness-shakedown exemption by declaration (rg-009).
    assert (
        main(
            [
                "score",
                "--manifest",
                str(manifest_path),
                "--run-record",
                str(record_path),
                "--rubric-gate",
                "skip",
            ]
        )
        is None
    )
    report = json.loads(record_path.with_name("run-seeded-shape-report.json").read_text())
    assert report["verdict"]["rubric_gate"] == "skip"
    # F1d-1: skip must not persist a bare gated pass (OBS-04 overclaim).
    assert report["verdict"]["verdict"] == "pass_ungated"
    assert report["verdict"]["must_right_failed_images"] > 0


def test_score_report_records_rubric_gate_flag(tmp_path, monkeypatch):
    """F1b-2: report + verdict stamp --rubric-gate so skip is never a silent pass."""
    roster, entries = _corpus_entries(6, with_rubric=True)
    manifest_path, manifest_sha = _write_score_manifest(tmp_path, entries, roster)
    record = _score_run_record(
        entries,
        caption_fn=lambda e: f"{e['present_identities'][0]} outdoors smiling.",
        identity_fn=lambda e: [_score_identity(e["present_identities"][0])],
        manifest_sha=manifest_sha,
        name="run-rubric-flag.json",
    )
    record_path = tmp_path / "run-rubric-flag.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    # Default enforce is recorded even when the gate does not fire.
    assert main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)]) is None
    report = json.loads(record_path.with_name("run-rubric-flag-report.json").read_text())
    assert report["verdict"]["rubric_gate"] == "enforce"
    md = record_path.with_name("run-rubric-flag-report.md").read_text()
    assert "rubric_gate" in md
    assert "enforce" in md


def test_score_guard_wrong_names_fails_wrong_name_floor_gate(tmp_path, monkeypatch):
    """Corruption 2: wrong human names on every image → wrong-name floor gate (named)."""
    manifest_path, record_path = _wrong_name_everywhere_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)])
    msg = str(excinfo.value)
    assert excinfo.value.code != 0
    assert "wrong-name" in msg.lower()
    assert "floor" in msg.lower()
    assert "must-right failures" not in msg.lower()
    assert "manifest-mismatch" not in msg.lower()
    assert "empty-rubric" not in msg.lower()


def test_score_guard_missing_fetch_sha_fails_manifest_mismatch_gate(tmp_path, monkeypatch):
    """Corruption 3: run-record lacks fetch-time manifest_sha256 provenance.

    F1-3: score-time file sha vs fetch-time sha is informational only (archived
    re-scores under evolved manifests must succeed; truncation is the media-id
    multiset gate). Self-consistency requires the record to carry its own
    fetch-time stamp so provenance is attributable.
    """
    roster, entries = _corpus_entries(6, with_rubric=True)
    manifest_path, manifest_sha = _write_score_manifest(tmp_path, entries, roster)
    assert manifest_sha
    record = _score_run_record(
        entries,
        caption_fn=lambda e: f"{e['present_identities'][0]} outdoors smiling.",
        identity_fn=lambda e: [_score_identity(e["present_identities"][0])],
        manifest_sha=manifest_sha,
    )
    # Drop the fetch-time stamp — record is not self-consistent with any corpus.
    del record["provenance"]["manifest_sha256"]
    record_path = tmp_path / "run-no-fetch-sha.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)])
    msg = str(excinfo.value)
    assert excinfo.value.code != 0
    assert "manifest-mismatch" in msg.lower()
    assert "fetch-time" in msg.lower() or "provenance" in msg.lower()
    # Must not claim corpus truncation (that is the media-id multiset gate).
    assert "truncation" not in msg.lower()
    assert "wrong-name" not in msg.lower()
    assert "must-right failures" not in msg.lower()
    assert "empty-rubric" not in msg.lower()


def test_score_allows_fetch_sha_drift_from_score_time_manifest(tmp_path, monkeypatch):
    """F1-3 green path: evolved score-time manifest sha must not block re-score.

    Full media-id coverage + good captions + non-empty fetch stamp + mismatched
    score-time sha (as when face_boxes are later populated) → exit 0.
    """
    roster, entries = _corpus_entries(6, with_rubric=True)
    manifest_path, score_sha = _write_score_manifest(tmp_path, entries, roster)
    stale_fetch_sha = "a" * 64
    assert stale_fetch_sha != score_sha
    record = _score_run_record(
        entries,
        caption_fn=lambda e: f"{e['present_identities'][0]} outdoors smiling.",
        identity_fn=lambda e: [_score_identity(e["present_identities"][0])],
        manifest_sha=stale_fetch_sha,
    )
    record_path = tmp_path / "run-sha-drift.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    # Must exit 0 (main returns None on success).
    assert main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)]) is None


def test_score_guard_empty_must_right_fails_empty_rubric_gate(tmp_path, monkeypatch):
    """Corruption 4: must_right emptied corpus-wide → empty-rubric gate (easy_wrong kept).

    Vacuity is per-rubric: emptying only must_right while easy_wrong remains must
    still fail (OR'd counters previously silenced this; r08116b50 F1-1).
    """
    roster, entries = _corpus_entries(6, with_rubric=True)
    for entry in entries:
        entry["must_right"] = []
    # Docstring contract: only must_right is emptied; easy_wrong stays non-empty.
    assert all(not e["must_right"] and e["easy_wrong"] for e in entries)
    manifest_path, manifest_sha = _write_score_manifest(tmp_path, entries, roster)
    record = _score_run_record(
        entries,
        caption_fn=lambda e: f"{e['present_identities'][0]} outdoors smiling.",
        identity_fn=lambda e: [_score_identity(e["present_identities"][0])],
        manifest_sha=manifest_sha,
        name="run-empty-rubric.json",
    )
    record_path = tmp_path / "run-empty-rubric.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    # easy_wrong remains, so RubricEmptyWarning (OR'd loader check) does not fire —
    # the named empty-rubric gate must still exit non-zero for must_right vacuity.
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)])
    msg = str(excinfo.value)
    assert excinfo.value.code != 0
    assert "empty-rubric" in msg.lower()
    assert "must_right" in msg.lower()
    assert "vacuous" in msg.lower()
    assert "wrong-name" not in msg.lower()
    assert "manifest-mismatch" not in msg.lower()
    assert "must-right failures" not in msg.lower()
    assert "truncation" not in msg.lower()


def test_score_guard_empty_easy_wrong_fails_empty_rubric_gate(tmp_path, monkeypatch):
    """Symmetric to must_right: easy_wrong emptied corpus-wide must name easy_wrong."""
    roster, entries = _corpus_entries(6, with_rubric=True)
    for entry in entries:
        entry["easy_wrong"] = []
    assert all(e["must_right"] and not e["easy_wrong"] for e in entries)
    manifest_path, manifest_sha = _write_score_manifest(tmp_path, entries, roster)
    record = _score_run_record(
        entries,
        caption_fn=lambda e: f"{e['present_identities'][0]} outdoors smiling.",
        identity_fn=lambda e: [_score_identity(e["present_identities"][0])],
        manifest_sha=manifest_sha,
        name="run-empty-easy-wrong.json",
    )
    record_path = tmp_path / "run-empty-easy-wrong.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)])
    msg = str(excinfo.value)
    assert excinfo.value.code != 0
    assert "empty-rubric" in msg.lower()
    assert "easy_wrong" in msg.lower()
    assert "vacuous" in msg.lower()
    assert "must-right failures" not in msg.lower()
    assert "truncation" not in msg.lower()


def test_score_guard_fetch_limit_truncation_fails_coverage_gate(tmp_path, monkeypatch):
    """Corruption F1-2: 5-of-37 run-record with matching full-corpus fetch sha.

    fetch --limit N produces exactly this shape: provenance.manifest_sha256 matches
    the full score-time manifest, but items cover only a subset. Media-id multiset
    asymmetry must exit non-zero (sha-match alone is not coverage).
    """
    roster, full_entries = _corpus_entries(37, with_rubric=True)
    manifest_path, full_sha = _write_score_manifest(
        tmp_path, full_entries, roster, name="golden.json"
    )
    truncated_items = full_entries[:5]
    assert len(truncated_items) == 5
    record = _score_run_record(
        truncated_items,
        caption_fn=lambda e: f"{e['present_identities'][0]} outdoors smiling.",
        identity_fn=lambda e: [_score_identity(e["present_identities"][0])],
        manifest_sha=full_sha,  # matching full-corpus sha — not the stale-sha shape
    )
    record_path = tmp_path / "run-limit5.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)])
    msg = str(excinfo.value)
    assert excinfo.value.code != 0
    assert "truncation" in msg.lower()
    assert "missing=32" in msg or "missing=32," in msg
    assert "extra=0" in msg
    assert "manifest-mismatch" not in msg.lower()
    assert "empty-rubric" not in msg.lower()
    assert "must-right failures" not in msg.lower()
    assert "wrong-name" not in msg.lower()


# --- VLM-6 S2A F1-4: hard-key three gate inputs (schema drift must not fail open) ---


_GOLDEN_SEED = Path(__file__).resolve().parent / "seed" / "golden.json"


def _real_golden_good_record() -> tuple[Path, dict]:
    """Full 37-entry run-record from scene/tests/seed/golden.json that scores clean.

    identities are dict rows (bare strings rejected by _validate_identities_element_types).
    Caption text lives in describe.alt_text_draft / named_draft / generic_draft.
    """
    from scripts.eval_harness.cli import _manifest_sha
    from scripts.eval_harness.manifest import load_manifest
    from scripts.eval_harness.schema import SCHEMA, DocKind

    manifest = load_manifest(str(_GOLDEN_SEED))
    entries = [e.model_dump() for e in manifest.entries]
    assert len(entries) == 37
    msha = _manifest_sha(manifest)
    items = []
    for entry in entries:
        names = list(entry.get("present_identities") or [])
        must = list(entry.get("must_right") or [])
        cap = (
            " ".join(must + names + ["outdoors smiling."])
            if (must or names)
            else "A scenic outdoor photograph."
        )
        idents = [
            {
                "name": n,
                "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
                "unpositioned": False,
            }
            for n in names
        ]
        items.append(
            {
                "media_id": entry["media_id"],
                "path": entry["path"],
                "describe": {
                    "alt_text_draft": cap,
                    "named_draft": cap,
                    "generic_draft": cap,
                    "visual_facts": {"objects": []},
                },
                "identities": idents,
                "face_count": entry.get("face_count") or 0,
                "error": None,
            }
        )
    record = {
        "schema": SCHEMA,
        "kind": DocKind.RUN_RECORD.value,
        "provenance": {
            "manifest_sha256": msha,
            "base_url": "https://example.test",
            "head_sha": "f" * 40,
            "started_at": "t",
        },
        "items": items,
    }
    return _GOLDEN_SEED, record


def _corrupt_score_run_record(monkeypatch, mutator):
    """Post-process score_run_record to simulate report.py schema drift (F1-4)."""
    import scripts.eval_harness.cli as cli_mod

    real = cli_mod.score_run_record

    def _wrapped(*args, **kwargs):
        scored = real(*args, **kwargs)
        return mutator(scored)

    monkeypatch.setattr(cli_mod, "score_run_record", _wrapped)


def _assert_schema_error_only(excinfo, dotted_path: str) -> None:
    msg = str(excinfo.value)
    assert excinfo.value.code != 0
    assert "score schema error" in msg.lower()
    assert dotted_path in msg
    # Class-unique token: no other gate class may claim the exit.
    assert "must-right failures" not in msg.lower()
    assert "wrong-name" not in msg.lower() or "wrong_name_rate" in dotted_path
    assert "manifest-mismatch" not in msg.lower()
    assert "empty-rubric" not in msg.lower()
    assert "truncation" not in msg.lower()
    assert "failed-items" not in msg.lower()


def test_score_schema_error_when_manifest_matches_fetch_missing(tmp_path, monkeypatch):
    """F1-4: provenance.manifest_matches_fetch missing → schema error (real golden)."""
    import copy

    golden, record = _real_golden_good_record()

    def _drop(scored):
        scored = copy.deepcopy(scored)
        scored["provenance"].pop("manifest_matches_fetch", None)
        return scored

    _corrupt_score_run_record(monkeypatch, _drop)
    record_path = tmp_path / "run-no-mmf.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(golden), "--run-record", str(record_path)])
    _assert_schema_error_only(excinfo, "provenance.manifest_matches_fetch")
    assert "bool" in str(excinfo.value).lower()


def test_score_schema_error_when_must_right_failed_images_missing(tmp_path, monkeypatch):
    """F1-4: caption.must_right_failed_images missing → schema error (real golden)."""
    import copy

    golden, record = _real_golden_good_record()

    def _drop(scored):
        scored = copy.deepcopy(scored)
        scored["caption"].pop("must_right_failed_images", None)
        return scored

    _corrupt_score_run_record(monkeypatch, _drop)
    record_path = tmp_path / "run-no-mrf.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(golden), "--run-record", str(record_path)])
    _assert_schema_error_only(excinfo, "caption.must_right_failed_images")
    assert "number" in str(excinfo.value).lower()


def test_score_schema_error_when_wrong_name_rate_missing(tmp_path, monkeypatch):
    """F1-4: verdict.wrong_name_rate missing → schema error (real golden)."""
    import copy

    golden, record = _real_golden_good_record()

    def _drop(scored):
        scored = copy.deepcopy(scored)
        scored["verdict"].pop("wrong_name_rate", None)
        return scored

    _corrupt_score_run_record(monkeypatch, _drop)
    record_path = tmp_path / "run-no-wnr.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(golden), "--run-record", str(record_path)])
    _assert_schema_error_only(excinfo, "verdict.wrong_name_rate")
    assert "number" in str(excinfo.value).lower()


# --- VLM-6 S2A F1-5: wrong-name floor defeatable + vacuous (F1c-2) ---


def _real_golden_wrong_name_record() -> tuple[Path, dict, list[list[str]]]:
    """37-entry golden run-record with a wrong identity on every image.

    Returns (manifest_path, record, ignore_pairs) where ignore_pairs covers every
    asserted wrong name so an ignore-list can silence the pre-fix floor gate.
    """
    from scripts.eval_harness.cli import _manifest_sha
    from scripts.eval_harness.manifest import load_manifest
    from scripts.eval_harness.schema import SCHEMA, DocKind

    manifest = load_manifest(str(_GOLDEN_SEED))
    entries = [e.model_dump() for e in manifest.entries]
    assert len(entries) == 37
    msha = _manifest_sha(manifest)
    roster = list(manifest.roster or [])
    items: list[dict] = []
    ignore_pairs: list[list[str]] = []
    for entry in entries:
        names = list(entry.get("present_identities") or [])
        must = list(entry.get("must_right") or [])
        cap = (
            " ".join(must + names + ["outdoors smiling."])
            if (must or names)
            else "A scenic outdoor photograph."
        )
        wrong = "Definitely Wrong Person"
        for n in roster:
            if n not in names:
                wrong = n
                break
        idents = [
            {
                "name": wrong,
                "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
                "unpositioned": False,
            }
        ]
        items.append(
            {
                "media_id": entry["media_id"],
                "path": entry["path"],
                "describe": {
                    "alt_text_draft": cap,
                    "named_draft": cap,
                    "generic_draft": cap,
                    "visual_facts": {"objects": []},
                },
                "identities": idents,
                "face_count": entry.get("face_count") or 0,
                "error": None,
            }
        )
        ignore_pairs.append([entry["path"], wrong])
    record = {
        "schema": SCHEMA,
        "kind": DocKind.RUN_RECORD.value,
        "provenance": {
            "manifest_sha256": msha,
            "base_url": "https://example.test",
            "head_sha": "f" * 40,
            "started_at": "t",
        },
        "items": items,
    }
    return _GOLDEN_SEED, record, ignore_pairs


def test_score_ignore_list_cannot_defeat_wrong_name_floor(tmp_path, monkeypatch):
    """F1-5 (a): ignore-list covering 100% wrong names must still fail floor.

    Pre-fix: ignore-list moved every pair into ignored_wrong_names → rate=0,
    verdict=pass, exit 0. Gate must count live + ignored; presentation split
    remains (ignored_wrong_names populated, live wrong_names empty).
    """
    from scripts.eval_harness.report import WRONG_NAME_RATE_FLOOR

    golden, record, ignore_pairs = _real_golden_wrong_name_record()
    assert len(ignore_pairs) == 37
    record_path = tmp_path / "run-ignore-defeat.json"
    record_path.write_text(json.dumps(record))
    (tmp_path / "ignore-list.json").write_text(json.dumps({"wrong_names": ignore_pairs}))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(golden), "--run-record", str(record_path)])
    msg = str(excinfo.value)
    assert excinfo.value.code != 0
    assert "wrong-name floor" in msg.lower()
    assert "vacuity" not in msg.lower()  # class-unique: floor breach, not vacuity
    assert "empty-rubric" not in msg.lower()
    assert "must-right failures" not in msg.lower()
    assert "manifest-mismatch" not in msg.lower()
    assert "truncation" not in msg.lower()
    assert "schema error" not in msg.lower()
    report = json.loads(record_path.with_name("run-ignore-defeat-report.json").read_text())
    ident = report["faces"]["identification"]
    assert ident["wrong_names"] == []
    assert len(ident["ignored_wrong_names"]) == 37
    assert report["verdict"]["wrong_name_rate"] > WRONG_NAME_RATE_FLOOR
    assert report["verdict"]["verdict"] == "fail"
    assert report["verdict"]["wrong_name_rate"] == pytest.approx(1.0)


def test_score_recognition_disabled_corpus_fails_wrong_name_floor_vacuity(
    tmp_path, monkeypatch
):
    """F1-5 (b): recognition_enabled=false corpus-wide → floor vacuity gate.

    Pre-fix: identification_pr excluded every image → wrong_names=[], rate=0.0,
    exit 0 no matter how wrong the identities were (EVAL-19). Class-unique token
    must not match empty-rubric.
    """
    import copy

    from scripts.eval_harness.cli import _manifest_sha
    from scripts.eval_harness.manifest import load_manifest
    from scripts.eval_harness.schema import SCHEMA, DocKind

    raw = json.loads(_GOLDEN_SEED.read_text())
    man = copy.deepcopy(raw)
    for entry in man["entries"]:
        entry["policy"] = {**entry.get("policy", {}), "recognition_enabled": False}
    man_path = tmp_path / "golden-rec-off.json"
    man_path.write_text(json.dumps(man))
    manifest = load_manifest(str(man_path))
    entries = [e.model_dump() for e in manifest.entries]
    assert len(entries) == 37
    assert all(not e["policy"]["recognition_enabled"] for e in entries)
    msha = _manifest_sha(manifest)
    roster = list(manifest.roster or [])
    items = []
    for entry in entries:
        names = list(entry.get("present_identities") or [])
        must = list(entry.get("must_right") or [])
        cap = (
            " ".join(must + names + ["outdoors smiling."])
            if (must or names)
            else "A scenic outdoor photograph."
        )
        wrong = "Definitely Wrong Person"
        for n in roster:
            if n not in names:
                wrong = n
                break
        items.append(
            {
                "media_id": entry["media_id"],
                "path": entry["path"],
                "describe": {
                    "alt_text_draft": cap,
                    "named_draft": cap,
                    "generic_draft": cap,
                    "visual_facts": {"objects": []},
                },
                "identities": [
                    {
                        "name": wrong,
                        "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
                        "unpositioned": False,
                    }
                ],
                "face_count": entry.get("face_count") or 0,
                "error": None,
            }
        )
    record = {
        "schema": SCHEMA,
        "kind": DocKind.RUN_RECORD.value,
        "provenance": {
            "manifest_sha256": msha,
            "base_url": "https://example.test",
            "head_sha": "f" * 40,
            "started_at": "t",
        },
        "items": items,
    }
    record_path = tmp_path / "run-rec-off.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(man_path), "--run-record", str(record_path)])
    msg = str(excinfo.value)
    assert excinfo.value.code != 0
    assert "wrong-name floor vacuity" in msg.lower()
    assert "evaluated_images=0" in msg
    assert "vacuous" in msg.lower()
    # Class-unique vs empty-rubric and the non-vacuous floor breach token.
    assert "empty-rubric" not in msg.lower()
    assert "must_right is vacuous" not in msg.lower()
    assert "easy_wrong is vacuous" not in msg.lower()
    assert "must-right failures" not in msg.lower()
    assert "manifest-mismatch" not in msg.lower()
    assert "truncation" not in msg.lower()
    assert "schema error" not in msg.lower()
    # Not the plain floor-breach message (rate would be 0.0 here).
    assert "exceeds floor" not in msg.lower()
    report = json.loads(record_path.with_name("run-rec-off-report.json").read_text())
    ident = report["faces"]["identification"]
    assert ident["evaluated_images"] == 0
    assert len(ident["excluded_images"]) == 37
    assert ident["wrong_names"] == []
    # F1d-1: vacuity must persist fail (pre-fix left verdict=pass while exit 1).
    assert report["verdict"]["verdict"] == "fail"
    assert any("wrong-name floor vacuity" in r for r in report["verdict"]["reasons"])


# --- VLM-6 S2A F1d-1: persisted verdict encodes every exit condition (OBS-04) ---


def _assert_on_disk_fail_reason(report: dict, *, must_contain: str, must_not: tuple[str, ...]) -> None:
    """On-disk artifact (not stdout) is the contract: fail + class-unique reason."""
    assert report["verdict"]["verdict"] == "fail"
    reasons = report["verdict"]["reasons"]
    assert reasons, "fail verdict must list reasons"
    blob = " | ".join(reasons).lower()
    assert must_contain.lower() in blob
    for other in must_not:
        assert other.lower() not in blob, f"reason class leaked: {other!r} in {reasons!r}"


def test_score_persisted_verdict_control_pass_on_real_golden(tmp_path, monkeypatch):
    """F1d-1 discrimination control: clean real golden run persists pass, exits 0."""
    golden, record = _real_golden_good_record()
    record_path = tmp_path / "run-control-pass.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    assert main(["score", "--manifest", str(golden), "--run-record", str(record_path)]) is None
    report = json.loads(record_path.with_name("run-control-pass-report.json").read_text())
    assert report["verdict"]["verdict"] == "pass"
    assert report["verdict"]["reasons"] == []
    assert report["verdict"]["rubric_gate"] == "enforce"
    assert report["counts"]["scored"] == 37


def test_score_persisted_verdict_fail_failed_items_real_golden(tmp_path, monkeypatch):
    """F1d-1: failed-items gate → on-disk verdict fail + reasons (real golden)."""
    import copy

    golden, record = _real_golden_good_record()
    record = copy.deepcopy(record)
    record["items"][0]["error"] = "FileNotFoundError: missing"
    record["items"][0]["describe"] = None
    record["items"][0]["identities"] = []
    record_path = tmp_path / "run-fail-items.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(golden), "--run-record", str(record_path)])
    assert excinfo.value.code != 0
    assert "failed-items" in str(excinfo.value).lower()
    report = json.loads(record_path.with_name("run-fail-items-report.json").read_text())
    _assert_on_disk_fail_reason(
        report,
        must_contain="failed-items",
        must_not=(
            "truncation",
            "manifest-mismatch",
            "empty-rubric",
            "must-right failures",
            "wrong-name floor vacuity",
            "schema error",
        ),
    )


def test_score_persisted_verdict_fail_truncation_real_golden(tmp_path, monkeypatch):
    """F1d-1: truncation gate → on-disk fail + truncation reason (real golden 5/37)."""
    import copy

    golden, record = _real_golden_good_record()
    record = copy.deepcopy(record)
    record["items"] = record["items"][:5]
    record_path = tmp_path / "run-trunc.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(golden), "--run-record", str(record_path)])
    assert excinfo.value.code != 0
    assert "truncation" in str(excinfo.value).lower()
    report = json.loads(record_path.with_name("run-trunc-report.json").read_text())
    _assert_on_disk_fail_reason(
        report,
        must_contain="truncation",
        must_not=(
            "failed-items",
            "manifest-mismatch",
            "empty-rubric",
            "must-right failures",
            "wrong-name floor vacuity",
            "schema error",
        ),
    )


def test_score_persisted_verdict_fail_manifest_mismatch_real_golden(tmp_path, monkeypatch):
    """F1d-1: missing fetch-time sha → on-disk fail + manifest-mismatch reason."""
    import copy

    golden, record = _real_golden_good_record()
    record = copy.deepcopy(record)
    del record["provenance"]["manifest_sha256"]
    record_path = tmp_path / "run-no-sha.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(golden), "--run-record", str(record_path)])
    assert excinfo.value.code != 0
    assert "manifest-mismatch" in str(excinfo.value).lower()
    report = json.loads(record_path.with_name("run-no-sha-report.json").read_text())
    _assert_on_disk_fail_reason(
        report,
        must_contain="manifest-mismatch",
        must_not=(
            "failed-items",
            "truncation",
            "empty-rubric",
            "must-right failures",
            "wrong-name floor vacuity",
            "schema error",
        ),
    )


def test_score_persisted_verdict_fail_empty_rubric_must_right_real_golden(tmp_path, monkeypatch):
    """F1d-1: must_right emptied corpus-wide → on-disk fail + empty-rubric reason."""
    import copy

    from scripts.eval_harness.cli import _manifest_sha
    from scripts.eval_harness.manifest import load_manifest

    raw = json.loads(_GOLDEN_SEED.read_text())
    man = copy.deepcopy(raw)
    for entry in man["entries"]:
        entry["must_right"] = []
    man_path = tmp_path / "golden-no-mr.json"
    man_path.write_text(json.dumps(man))
    manifest = load_manifest(str(man_path))
    msha = _manifest_sha(manifest)
    _, record = _real_golden_good_record()
    record = copy.deepcopy(record)
    record["provenance"]["manifest_sha256"] = msha
    # Align media_ids/paths already match golden; re-point provenance only.
    record_path = tmp_path / "run-empty-mr.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(man_path), "--run-record", str(record_path)])
    assert excinfo.value.code != 0
    assert "empty-rubric" in str(excinfo.value).lower()
    assert "must_right" in str(excinfo.value).lower()
    report = json.loads(record_path.with_name("run-empty-mr-report.json").read_text())
    _assert_on_disk_fail_reason(
        report,
        must_contain="empty-rubric",
        must_not=(
            "failed-items",
            "truncation",
            "manifest-mismatch",
            "must-right failures",
            "wrong-name floor vacuity",
            "schema error",
        ),
    )
    assert any("must_right" in r for r in report["verdict"]["reasons"])


def test_score_persisted_verdict_fail_must_right_real_golden(tmp_path, monkeypatch):
    """F1d-1: caption corruption → on-disk fail + must-right failures reason."""
    import copy

    golden, record = _real_golden_good_record()
    record = copy.deepcopy(record)
    garbage = "xxxxx yyyyy zzzzz qqqqq"
    for item in record["items"]:
        item["describe"] = {
            "alt_text_draft": garbage,
            "named_draft": garbage,
            "generic_draft": garbage,
            "visual_facts": {"objects": []},
        }
    record_path = tmp_path / "run-mr-fail.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(golden), "--run-record", str(record_path)])
    assert excinfo.value.code != 0
    assert "must-right failures" in str(excinfo.value).lower()
    report = json.loads(record_path.with_name("run-mr-fail-report.json").read_text())
    _assert_on_disk_fail_reason(
        report,
        must_contain="must-right failures",
        must_not=(
            "failed-items",
            "truncation",
            "manifest-mismatch",
            "empty-rubric",
            "wrong-name floor vacuity",
            "schema error",
        ),
    )


def test_score_persisted_verdict_fail_wrong_name_floor_real_golden(tmp_path, monkeypatch):
    """F1d-1: 100% wrong names → on-disk fail + wrong_name_rate reason."""
    golden, record, _ignore = _real_golden_wrong_name_record()
    record_path = tmp_path / "run-wn-floor.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(golden), "--run-record", str(record_path)])
    assert excinfo.value.code != 0
    assert "wrong-name floor" in str(excinfo.value).lower()
    report = json.loads(record_path.with_name("run-wn-floor-report.json").read_text())
    _assert_on_disk_fail_reason(
        report,
        must_contain="wrong_name_rate",
        must_not=(
            "failed-items",
            "truncation",
            "manifest-mismatch",
            "empty-rubric",
            "must-right failures",
            "wrong-name floor vacuity",
            "schema error",
        ),
    )


def test_score_persisted_verdict_fail_schema_error_real_golden(tmp_path, monkeypatch):
    """F1d-1: schema drift → on-disk fail + schema error reason (written before exit)."""
    import copy

    golden, record = _real_golden_good_record()

    def _drop(scored):
        scored = copy.deepcopy(scored)
        scored["caption"].pop("must_right_failed_images", None)
        return scored

    _corrupt_score_run_record(monkeypatch, _drop)
    record_path = tmp_path / "run-schema.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(golden), "--run-record", str(record_path)])
    _assert_schema_error_only(excinfo, "caption.must_right_failed_images")
    report = json.loads(record_path.with_name("run-schema-report.json").read_text())
    _assert_on_disk_fail_reason(
        report,
        must_contain="schema error",
        must_not=(
            "failed-items",
            "truncation",
            "manifest-mismatch",
            "empty-rubric",
            "must-right failures",
            "wrong-name floor vacuity",
        ),
    )
    assert any("caption.must_right_failed_images" in r for r in report["verdict"]["reasons"])


def test_score_persisted_verdict_pass_ungated_on_rubric_gate_skip(tmp_path, monkeypatch):
    """F1d-1: --rubric-gate skip persists pass_ungated (not bare pass) on real golden."""
    import copy

    golden, record = _real_golden_good_record()
    record = copy.deepcopy(record)
    # Seeded-shape captions miss must_right but skip bypasses that gate only.
    for item in record["items"]:
        item["describe"] = {
            "alt_text_draft": "A human standing outdoors near greenery.",
            "named_draft": "A human standing outdoors near greenery.",
            "generic_draft": "A human standing outdoors near greenery.",
            "visual_facts": {"objects": []},
        }
        item["identities"] = []
    record_path = tmp_path / "run-ungated.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    assert (
        main(
            [
                "score",
                "--manifest",
                str(golden),
                "--run-record",
                str(record_path),
                "--rubric-gate",
                "skip",
            ]
        )
        is None
    )
    report = json.loads(record_path.with_name("run-ungated-report.json").read_text())
    assert report["verdict"]["verdict"] == "pass_ungated"
    assert report["verdict"]["rubric_gate"] == "skip"
    assert report["verdict"]["must_right_failed_images"] > 0
    assert report["verdict"]["reasons"] == []


# --- FIR-5 S5: face-bakeoff / score-face CLI surface ---


def test_cli_face_bakeoff_and_score_face_subcommands_present():
    # Re-run main's parser construction by invoking with --help on each
    with pytest.raises(SystemExit) as exc:
        main(["face-bakeoff", "--help"])
    assert exc.value.code == 0
    with pytest.raises(SystemExit) as exc2:
        main(["score-face", "--help"])
    assert exc2.value.code == 0


def _valid_face_manifest_and_record(dim: int = 8) -> tuple[dict, dict]:
    """A load_manifest-valid manifest + matching face-run-record (FIR5-S5-BR-05/06)."""
    import numpy as np

    def _unit(v):
        a = np.asarray(v, dtype=float)
        return (a / np.linalg.norm(a)).tolist()

    def _fd(bbox, emb):
        return {"bbox_px": bbox, "embedding": emb, "det_score": 0.95, "landmarks_px": [[0.0, 0.0]] * 5}

    def _gt(name):
        return {"x": 0.4, "y": 0.4, "w": 0.4, "h": 0.4, "name": name, "source": "iptc"}

    def _ent(path, mid, name, src, pub):
        return {
            "path": path,
            "sha256": "a" * 64,
            "media_id": mid,
            "face_count": 1,
            "base_caption": "",
            "present_identities": ([name] if name else []),
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [_gt(name)],
            "provenance": {
                "source": src,
                "license": "public_domain" if pub else "consented",
                "publishable": pub,
            },
        }

    record = {
        "schema": "acx-eval/v1",
        "kind": "face_run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "head_sha": "0" * 40,
            "started_at": "2026-07-18T00:00:00Z",
            "leg": "candidate",
            "model_id": "ort-yunet-sface",
            "embedding_dim": dim,
        },
        "items": [
            {"media_id": 1, "path": "celebs01/alice-a.jpg", "model_id": "ort-yunet-sface",
             "embedding_dim": dim, "image_size": [100, 100],
             "faces": [_fd([20.0, 20.0, 40.0, 40.0], _unit([1.0] + [0.0] * (dim - 1)))]},
            {"media_id": 2, "path": "celebs01/alice-b.jpg", "model_id": "ort-yunet-sface",
             "embedding_dim": dim, "image_size": [100, 100],
             "faces": [_fd([20.0, 20.0, 40.0, 40.0], _unit([0.98, 0.1] + [0.0] * (dim - 2)))]},
            {"media_id": 3, "path": "localwp/uploads/stranger-party.jpg", "model_id": "ort-yunet-sface",
             "embedding_dim": dim, "image_size": [100, 100],
             "faces": [_fd([20.0, 20.0, 40.0, 40.0], _unit([0.0, 1.0] + [0.0] * (dim - 2)))]},
        ],
    }
    manifest = {
        "manifest_version": 2,
        "roster": ["Alice Example"],
        "roster_cohorts": {"Alice Example": "cohort_a"},
        "entries": [
            _ent("celebs01/alice-a.jpg", 1, "Alice Example", "celeb", True),
            _ent("celebs01/alice-b.jpg", 2, "Alice Example", "celeb", True),
            _ent("localwp/uploads/stranger-party.jpg", 3, None, "localwp", False),
        ],
    }
    return record, manifest


def test_cli_score_face_check_determinism_runs_shipped_guard(tmp_path):
    """--check-determinism drives the SHIPPED cross-process guard end-to-end
    (FIR5-S5-BR-05/06): score-face re-scores in fresh PYTHONHASHSEED-varied
    subprocesses via _check_face_determinism_cross_process and exits 0 iff
    bit-identical. Reaching the write (no SystemExit) means the shipped guard ran
    and passed — not an inline re-implementation.
    """
    record, manifest = _valid_face_manifest_and_record()
    rec_path = tmp_path / "face-run.json"
    rec_path.write_text(json.dumps(record))
    man_path = tmp_path / "man.json"
    man_path.write_text(json.dumps(manifest))
    main(["score-face", "--run-record", str(rec_path), "--manifest", str(man_path), "--check-determinism"])
    assert (tmp_path / "face-run-face-report.json").exists()

    # Missing --run-record is still a parse error (flag recognized, not consumed as positional).
    with pytest.raises(SystemExit) as missing:
        main(["score-face", "--check-determinism"])
    assert missing.value.code == 2


def test_cli_score_face_determinism_guard_detects_nondeterminism(tmp_path, monkeypatch):
    """Non-vacuity (TEST-15): the shipped guard's cross-process comparison CAN go
    red. A subprocess whose re-score differs from the in-process baseline makes
    _check_face_determinism_cross_process sys.exit with 'determinism check FAILED'.
    """
    from scripts.eval_harness import cli as cli_mod

    record, manifest = _valid_face_manifest_and_record()
    rec_path = tmp_path / "face-run.json"
    rec_path.write_text(json.dumps(record))
    man_path = tmp_path / "man.json"
    man_path.write_text(json.dumps(manifest))

    class _Proc:
        returncode = 0
        stdout = "DIFFERENT-JSON---MD---DIFFERENT-MD"
        stderr = ""

    monkeypatch.setattr(cli_mod.subprocess, "run", lambda *a, **k: _Proc())
    with pytest.raises(SystemExit) as exc:
        cli_mod._check_face_determinism_cross_process(rec_path, str(man_path), public=False)
    assert "determinism check FAILED" in str(exc.value)


def test_cli_score_face_parse_run_record_required(tmp_path, monkeypatch, capsys):
    # Missing --run-record → parse error
    with pytest.raises(SystemExit) as exc:
        main(["score-face", "--manifest", "scene/tests/seed/golden.json"])
    assert exc.value.code == 2


def test_face_bakeoff_wires_synthetic_occlusion_twins_end_to_end(tmp_path, monkeypatch):
    """FIR5GL-01 discriminator [TEST-15]: a manifest with twin-eligible entries
    yields occlusion n_eligible > 0 in the score-face report, end-to-end through
    the CLI (face-bakeoff twin pass → run-record → score-face pass-through).
    Goes red if the bakeoff stops emitting ``occlusion_twin_pairs_by_tag`` OR
    score-face stops passing the pairs into build_face_reports — either drop
    reverts occlusion to the pre-fix n_eligible=0 state.
    """
    import cv2
    import numpy as np

    from recognition.infrastructure.face_pipeline._common import RawDetection
    from recognition.infrastructure.face_pipeline.aligner import FivePointAligner
    from scripts.eval_harness import cli as cli_mod

    dim = 8
    rng = np.random.default_rng(7)
    images = tmp_path / "images" / "celebs01"
    images.mkdir(parents=True)
    files = [("alice-1.jpg", "Alice Q"), ("alice-2.jpg", "Alice Q"), ("bob-1.jpg", "Bob Z"), ("bob-2.jpg", "Bob Z")]
    entries = []
    for mid, (fname, name) in enumerate(files, start=1):
        img = rng.integers(0, 256, size=(100, 100, 3)).astype(np.uint8)
        assert cv2.imwrite(str(images / fname), img)
        entries.append(
            {
                "path": f"celebs01/{fname}",
                "sha256": "0" * 64,
                "media_id": mid,
                "face_count": 1,
                "base_caption": "",
                "present_identities": [name],
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [{"x": 0.4, "y": 0.4, "w": 0.4, "h": 0.4, "name": name, "source": "iptc"}],
                "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
            }
        )
    man_path = tmp_path / "man.json"
    man_path.write_text(json.dumps({"manifest_version": 2, "roster": ["Alice Q", "Bob Z"], "entries": entries}))

    class _Det:
        """Pixel-blind fake: always one detection at the GT box (IoU 1.0)."""

        # rg-015: twin-pass provenance reads this from the injected cache detector.
        landmark_cache_provenance = LandmarkCacheProvenance.pinned_yunet()

        def detect(self, imgs):
            return [
                [
                    RawDetection(
                        bbox=np.asarray([20.0, 20.0, 40.0, 40.0], dtype=np.float32),
                        landmarks=np.asarray(
                            [[30.0, 35.0], [50.0, 35.0], [40.0, 45.0], [32.0, 55.0], [48.0, 55.0]],
                            dtype=np.float32,
                        ),
                        score=0.9,
                    )
                ]
                for _ in imgs
            ]

    class _Emb:
        embedding_dim = dim

        def embed(self, crops):
            out = []
            for crop in crops:
                seed = int.from_bytes(
                    np.ascontiguousarray(crop, dtype=np.uint8).tobytes()[:8].ljust(8, b"\0"), "little"
                )
                v = np.random.default_rng(seed).normal(size=dim)
                out.append(v / np.linalg.norm(v))
            return np.stack(out, axis=0)

    monkeypatch.setattr(cli_mod, "build_candidate_leg", lambda: (_Det(), FivePointAligner(), _Emb()))
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(tmp_path / "images"))

    cli_mod.main(["face-bakeoff", "--manifest", str(man_path)])
    record_path = next(p for p in (tmp_path / "out").glob("face-run-*.json") if "aborted" not in p.name)
    record = json.loads(record_path.read_text())

    # Bakeoff emitted document-level twin pairs: 4 named cached faces × 3 kinds.
    twins = record["occlusion_twin_pairs_by_tag"]
    assert set(twins) == {"masked", "sunglasses", "occlusion_other"}
    assert all(len(twins[tag]) == 4 for tag in twins)
    assert record["provenance"]["occlusion_twin_pass"]["n_pairs"] == 12
    assert record["provenance"]["occlusion_twin_pass"]["errors"] == []
    # Headline firewall intact: twins never entered items (EVAL-16).
    assert all(
        not ({"occluded", "occlusion", "occlusion_kind", "twin", "twin_of"} & set(item))
        for item in record["items"]
    )

    cli_mod.main(["score-face", "--manifest", str(man_path), "--run-record", str(record_path)])
    report = json.loads((tmp_path / "out" / f"{record_path.stem}-face-report.json").read_text())
    for tag in ("masked", "sunglasses", "occlusion_other"):
        synth = report["slices"]["occlusion"][tag]["synthetic"]
        # Pre-fix state was n_eligible=0 (no production caller): red if wiring drops.
        assert synth["n_eligible"] == 4, tag
        assert synth["n_eligible"] == synth["rate_denominator"]


# --- FIR-1 head-to-head: face-bakeoff --leg dispatch (candidate vs buffalo) ---


def test_cli_face_bakeoff_leg_rejects_unknown_value():
    with pytest.raises(SystemExit) as exc:
        main(["face-bakeoff", "--leg", "bogus"])
    assert exc.value.code == 2  # argparse choices error


def test_cli_face_bakeoff_buffalo_requires_eval_bench(monkeypatch):
    """--leg buffalo preflights ACX_EVAL_BENCH=1 with an actionable error."""
    monkeypatch.delenv("ACX_EVAL_BENCH", raising=False)
    with pytest.raises(SystemExit) as exc:
        main(["face-bakeoff", "--leg", "buffalo"])
    msg = str(exc.value)
    assert "ACX_EVAL_BENCH" in msg
    assert "uv sync --extra bench" in msg


def test_cli_face_bakeoff_buffalo_requires_insightface(monkeypatch):
    """Env flag alone is not enough: missing insightface names the [bench] remedy."""
    import importlib.util

    if importlib.util.find_spec("insightface") is not None:
        pytest.skip("insightface installed (bench env); missing-dep preflight not reachable")
    monkeypatch.setenv("ACX_EVAL_BENCH", "1")
    with pytest.raises(SystemExit) as exc:
        main(["face-bakeoff", "--leg", "buffalo"])
    assert "uv sync --extra bench" in str(exc.value)


def _leg_dispatch_manifest(tmp_path):
    """One-entry manifest (no named face_boxes → twin pass is a no-op) + images dir."""
    import cv2
    import numpy as np

    images = tmp_path / "images" / "celebs01"
    images.mkdir(parents=True)
    img = np.random.default_rng(11).integers(0, 256, size=(64, 64, 3)).astype(np.uint8)
    assert cv2.imwrite(str(images / "a.jpg"), img)
    man_path = tmp_path / "man.json"
    man_path.write_text(
        json.dumps(
            {
                "manifest_version": 2,
                "roster": ["Alice Q"],
                "entries": [
                    {
                        "path": "celebs01/a.jpg",
                        "sha256": "a" * 64,
                        "media_id": 1,
                        "face_count": 1,
                        "base_caption": "",
                        "present_identities": ["Alice Q"],
                        "must_right": [],
                        "easy_wrong": [],
                        "policy": {"recognition_enabled": True},
                        "context_pack": {"caption": "x"},
                        "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
                    }
                ],
            }
        )
    )
    return man_path


class _FusedFakeLeg:
    """Fused-shape fake: detector+embedder in one object (buffalo dispatch test)."""

    embedding_dim = 8
    leg_mode = "fused"
    # When tests pass cache_detector=None the leg doubles as cache detector (rg-015).
    landmark_cache_provenance = LandmarkCacheProvenance.pinned_yunet()

    def detect(self, imgs):
        import numpy as np

        from recognition.infrastructure.face_pipeline._common import RawDetection

        self._n = len(imgs)
        det = RawDetection(
            bbox=np.asarray([10.0, 10.0, 30.0, 30.0], dtype=np.float32),
            landmarks=np.asarray(
                [[15.0, 18.0], [35.0, 18.0], [25.0, 26.0], [17.0, 34.0], [33.0, 34.0]],
                dtype=np.float32,
            ),
            score=0.9,
        )
        return [[det] for _ in imgs]

    def embed(self, crops, boxes=None):  # boxes: fused-leg optional reorder guard
        import numpy as np

        v = np.ones(self.embedding_dim, dtype=np.float32)
        return np.stack([v / np.linalg.norm(v) for _ in crops], axis=0)


class _NoopAligner:
    def align(self, image, landmarks):
        from types import SimpleNamespace

        import numpy as np

        return SimpleNamespace(crop=np.zeros((112, 112, 3), dtype=np.uint8))


def test_cli_face_bakeoff_dispatches_buffalo_leg(tmp_path, monkeypatch):
    """--leg buffalo routes through _build_buffalo_leg (never build_candidate_leg)
    and stamps buffalo provenance (leg/model_id/embedding_dim/leg_mode)."""
    from scripts.eval_harness import cli as cli_mod

    man_path = _leg_dispatch_manifest(tmp_path)
    leg = _FusedFakeLeg()
    bundle = cli_mod._FaceLegBundle(
        detector=leg,
        aligner=_NoopAligner(),
        embedder=leg,
        model_id="buffalo_l",
        leg_mode="fused",
        cache_detector=None,
    )
    monkeypatch.setattr(cli_mod, "_build_buffalo_leg", lambda: bundle)
    monkeypatch.setattr(
        cli_mod, "build_candidate_leg", lambda: pytest.fail("candidate leg built for --leg buffalo")
    )
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(tmp_path / "images"))

    cli_mod.main(["face-bakeoff", "--manifest", str(man_path), "--leg", "buffalo"])
    record_path = next(p for p in (tmp_path / "out").glob("face-run-*.json") if "aborted" not in p.name)
    prov = json.loads(record_path.read_text())["provenance"]
    assert prov["leg"] == "buffalo"
    assert prov["model_id"] == "buffalo_l"
    assert prov["embedding_dim"] == 8  # from the leg embedder (rg-015), not a 512 literal
    assert prov["leg_mode"] == "fused"


def test_cli_face_bakeoff_candidate_leg_never_touches_buffalo(tmp_path, monkeypatch):
    """Default/explicit candidate dispatch keeps buffalo cold and stamps candidate provenance."""
    from recognition.infrastructure.face_pipeline.aligner import FivePointAligner
    from scripts.eval_harness import cli as cli_mod

    man_path = _leg_dispatch_manifest(tmp_path)
    leg = _FusedFakeLeg()  # shape-compatible mock; leg identity comes from dispatch args
    monkeypatch.setattr(cli_mod, "build_candidate_leg", lambda: (leg, FivePointAligner(), leg))
    monkeypatch.setattr(
        cli_mod, "_build_buffalo_leg", lambda: pytest.fail("buffalo leg built for --leg candidate")
    )
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(tmp_path / "images"))

    cli_mod.main(["face-bakeoff", "--manifest", str(man_path), "--leg", "candidate"])
    record_path = next(p for p in (tmp_path / "out").glob("face-run-*.json") if "aborted" not in p.name)
    prov = json.loads(record_path.read_text())["provenance"]
    assert prov["leg"] == "candidate"
    assert prov["model_id"] == "ort-yunet-sface"
    assert "leg_mode" not in prov
