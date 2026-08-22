"""VLM-2A Slice 3: CLI fetch loop (per-item isolation, bounded stall rg-007) + retention."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.eval_harness.report import ScoreVerdict

from scripts.eval_harness.cli import (
    BoundedStallError,
    MaxCostExceededError,
    ProviderMismatchError,
    _stdio_encoding_guard,
    fetch_run_record,
    main,
    prune_out_dir,
)
from scripts.eval_harness.landmark_cache import LandmarkCacheProvenance
from scripts.eval_harness.manifest import AnnotationMode, GoldenEntry, GoldenManifest
from scripts.eval_harness.report import build_reports


@pytest.fixture(autouse=True)
def _adopt_stdio_encoding_guard(monkeypatch):
    """VLM6-RV15-L-03: adopt `_stdio_encoding_guard` at in-process `main()` sites.

    Wraps each test (leak to the next case) and each `main([...])` call (so
    this module's 76 in-process sites restore before the test continues).
    """
    real_main = main

    def _guarded_main(argv=None):
        with _stdio_encoding_guard():
            return real_main(argv)

    monkeypatch.setattr(sys.modules[__name__], "main", _guarded_main)
    with _stdio_encoding_guard():
        yield


_TEST_LINEAGE_NAMED = {
    "labeler_id": "test-labeler",
    "batch_id": "test-batch",
    "capture_session_id": "test-session",
    "pass_index": 0,
    "labeled_at": "2026-08-14T00:00:00Z",
    "tool_version": "test",
    "saw_machine_proposals": False,
    "label_source": "operator_blind",
    "decision": "named",
    "confidence": "high",
    "arbitration_of": None,
}


def _manifest(n: int) -> GoldenManifest:
    sha = "a" * 64
    return GoldenManifest(
        manifest_version=3,
        annotation_mode="roster_only",
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
                provenance={"source": "fixture", "license": "fixture"},
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
    from scripts.eval_harness.cli import IdentityOrdering

    # A-08: every item stamps image dimensions (None when bytes are not a real image).
    assert all("image_width" in item and "image_height" in item for item in record["items"])
    # A-07 / RH-06: ordering source stamped once identities extracted.
    assert all(item.get("identity_ordering") == IdentityOrdering.POSITIONAL.value for item in record["items"])


def test_fetch_persists_image_dimensions_from_pixels(tmp_path):
    """A-08: absolute-pixel bboxes need image_width/height for positional scoring."""
    from io import BytesIO

    from PIL import Image

    from scripts.eval_harness.cli import fetch_run_record

    images = tmp_path / "mock_images"
    images.mkdir()
    buf = BytesIO()
    Image.new("RGB", (64, 48), color=(10, 20, 30)).save(buf, format="PNG")
    (images / "img-1.jpg").write_bytes(buf.getvalue())
    manifest = GoldenManifest(
        manifest_version=3,
        annotation_mode=AnnotationMode.ROSTER_ONLY,
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


def test_cli_fetch_rejects_check_determinism(capsys):
    """F2f / C-06 / OBS-04: fetch must not silently accept --check-determinism.

    Pre-fix: flag lived on _common(), so ``fetch --check-determinism`` parsed
    cleanly, hit the live-env gate (or paid remote work), and exited without
    certifying anything — a green that meant the opposite of what the operator
    asked for. Post-fix: argparse free-rejects the unknown argument before any
    paid call (TEST-15 discrimination: score/score-face still accept the flag).
    """
    with pytest.raises(SystemExit) as excinfo:
        main(["fetch", "--check-determinism"])
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "unrecognized arguments" in err
    assert "--check-determinism" in err
    # Must not reach live work (pre-fix path exited with the live-env string).
    assert "ACX_EVAL_LIVE" not in err
    assert "ACX_EVAL_LIVE" not in str(excinfo.value)


def test_cli_run_check_determinism_announces_multiplier(monkeypatch, capsys):
    """F2f / C-06: run keeps --check-determinism but announces legs×seeds first.

    Decision: per-leg certification (not single check). Each provider matrix
    record is an independent scored artifact; a once-only check would leave
    other legs uncertified under a flag that claims certification. Cost must
    be visible before paid fetch / first child spawn (OBS-04).
    """
    from argparse import Namespace

    from scripts.eval_harness import cli as cli_mod

    announce_before_fetch: list[str] = []
    score_records: list[str] = []

    def fake_fetch(args):
        # Capture stdout *at fetch entry* — announcement must already be there.
        announce_before_fetch.append(capsys.readouterr().out)
        return ["r0.json", "r1.json", "r2.json"]

    def fake_score(args):
        score_records.append(args.run_record)

    monkeypatch.setattr(cli_mod, "_cmd_fetch", fake_fetch)
    monkeypatch.setattr(cli_mod, "_cmd_score", fake_score)

    args = Namespace(
        check_determinism=True,
        provider=["leg-a", "leg-b", "leg-c"],
        audience="local",
    )
    cli_mod._cmd_run(args)
    assert len(announce_before_fetch) == 1
    pre = announce_before_fetch[0]
    assert "run --check-determinism" in pre
    assert "per-leg certification" in pre
    assert "3 legs × 3 seeds" in pre
    assert "9 fresh interpreter(s)" in pre
    assert score_records == ["r0.json", "r1.json", "r2.json"]


def test_cli_run_accepts_check_determinism_at_parse(monkeypatch):
    """Discrimination control (TEST-15): run still declares --check-determinism.

    Parse must succeed and dispatch to _cmd_run; we short-circuit before live
    work so this is a free wiring check (not a paid matrix run).
    """
    from scripts.eval_harness import cli as cli_mod

    seen: list[bool] = []

    def fake_run(args):
        seen.append(bool(args.check_determinism))

    monkeypatch.setattr(cli_mod, "_cmd_run", fake_run)
    main(["run", "--check-determinism", "--provider", "hosted_gpt4o"])
    assert seen == [True]


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
    from scripts.eval_harness.cli import IdentityOrdering

    identities, face_count, ordering = _extract_identities(payload, media_id=7)
    assert face_count == 2
    assert ordering == IdentityOrdering.POSITIONAL.value
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
    identities, face_count, ordering = _extract_identities(payload, media_id=1, image_width=400, image_height=200)
    assert face_count == 3
    from scripts.eval_harness.cli import IdentityOrdering

    assert ordering == IdentityOrdering.POSITIONAL.value
    names = [row["name"] for row in identities]
    assert names == ["Cam Left", "Amy Mid", "Zoe Right"]
    assert names != sorted(names)  # not alphabetical
    assert names != sorted(names, reverse=True)  # not reverse-alphabetical (A-11)
    assert [row["identity_id"] for row in identities] == ["id-cam", "id-amy", "id-zoe"]
    assert all(row["unpositioned"] is False for row in identities)


def test_extract_identities_orders_by_centre_x_not_corner_x():  # VLM6-B-03
    """Corner-x and centre-x disagree when face widths differ — extract must use centre.

    Wide @ corner-x=100 width=200 → centre 200; Narrow @ corner-x=150 width=50 →
    centre 175. Corner order is [Wide, Narrow]; centre order is [Narrow, Wide].
    """
    from scripts.eval_harness.cli import IdentityOrdering, _extract_identities

    payload = [
        {
            "identity_id": "id-wide",
            "media_id": 1,
            "cluster_label": "Wide Right",
            "is_auto_label": False,
            "bbox": {"x": 100, "y": 0, "width": 200, "height": 100},
        },
        {
            "identity_id": "id-narrow",
            "media_id": 1,
            "cluster_label": "Narrow Left",
            "is_auto_label": False,
            "bbox": {"x": 150, "y": 0, "width": 50, "height": 100},
        },
    ]
    identities, face_count, ordering = _extract_identities(payload, media_id=1, image_width=400, image_height=200)
    assert face_count == 2
    assert ordering == IdentityOrdering.POSITIONAL.value
    names = [row["name"] for row in identities]
    assert names == ["Narrow Left", "Wide Right"]
    # Explicit discrimination: corner-x order must NOT be what we return.
    corner_order = sorted(payload, key=lambda r: r["bbox"]["x"])
    assert [r["cluster_label"] for r in corner_order] == ["Wide Right", "Narrow Left"]
    assert names != [r["cluster_label"] for r in corner_order]


def test_extract_identities_unpositioned_after_positioned_no_fabricated_bbox():
    """Missing/malformed bbox rows stay, mark unpositioned, sort after positioned (rg-015).

    A-07: ordering_source must be ``IdentityOrdering.DEGRADED`` (loud), not silent alpha fallback.
    """
    from scripts.eval_harness.cli import IdentityOrdering, _extract_identities

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
    assert ordering == IdentityOrdering.DEGRADED.value  # A-07 / RH-06: loud, not silent
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
        manifest_version=3,
        annotation_mode="roster_only",
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
                provenance={"source": "fixture", "license": "fixture"},
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


def _write_score_manifest(tmp_path, entries, roster, name="golden.json", *, annotation_mode="roster_only"):
    """Write a v3 golden manifest and return (path, real score-time sha256).

    Fills the v3-only requirements (``annotation_mode``, per-entry
    ``base_caption``/``provenance``, per-box ``lineage``) with neutral
    defaults when a caller's fixture omits them, so existing call sites do
    not each have to be hand-migrated (VLM6-PANEL6L-rvM-01: ``load_manifest``
    is v3-only, ``manifest_version`` 2 is no longer accepted here).

    ``annotation_mode="exhaustive"`` (VLM6-DELTA-05) is required for a caller
    that wants face_detection.precision/recall to be measurable: roster_only
    structurally refuses detection (report.py), which score_vacuous_category_
    labels correctly still counts as a non-observed category — a "clean pass"
    fixture must therefore declare exhaustive coverage (box count ==
    face_count per entry) rather than relying on the roster_only default.
    ``_TEST_LINEAGE_NAMED``'s capture_session_id already satisfies the
    exhaustive-only capture-session invariant.
    """
    from scripts.eval_harness.cli import _manifest_sha
    from scripts.eval_harness.manifest import load_manifest

    manifest_path = tmp_path / name

    def _normalize_box(box: dict) -> dict:
        if "lineage" in box:
            return box
        lineage = dict(_TEST_LINEAGE_NAMED)
        lineage["decision"] = "named" if box.get("name") else "stranger"
        return {**box, "lineage": lineage}

    normalized_entries = [
        {
            "base_caption": "",
            "provenance": {"source": "fixture", "license": "fixture"},
            **entry,
            "face_boxes": [_normalize_box(box) for box in entry.get("face_boxes", [])],
        }
        for entry in entries
    ]
    payload: dict = {
        "manifest_version": 3,
        "annotation_mode": annotation_mode,
        "roster": roster,
        "entries": normalized_entries,
    }
    manifest_path.write_text(json.dumps(payload))
    # Metadata-only: computes score-time sha from roster/entries; never opens image bytes.
    return manifest_path, _manifest_sha(
        load_manifest(
            str(manifest_path),
            skip_hash_verification=True,
            hash_skip_reason="test helper computes score-time sha; image bytes never opened",
            metadata_only=True,
        )
    )


# False-polarity trap phrases that clean fixture captions never assert.
# Unique object tokens so placement/name captions stay fabrication-clean (TEST-15).
_MEASURABLE_TRAP_PHRASE = "purple zebra balloon"
_MEASURABLE_TRAP_FACT = {
    "text": _MEASURABLE_TRAP_PHRASE,
    "kind": "object",
    "polarity": "false",
    "phrases": [_MEASURABLE_TRAP_PHRASE],
}


def _single_name_measurable_fields(name: str, *, x: float = 0.4) -> dict:
    """face_boxes + spatial_facts + reference_facts trap so all gated categories have π>0.

    Caption must assert the foreground phrase for placement claims to fire.
    Trap phrases must not appear in clean captions (rate → 0.0, not None; EVAL-19).
    FaceBox schema is centre-point {x,y,w,h,name,source} (rg-005).
    """
    return {
        "face_boxes": [{"name": name, "x": x, "y": 0.4, "w": 0.2, "h": 0.3, "source": "iptc"}],
        "spatial_facts": [
            {
                "subject": name,
                "relation": "foreground",
                "phrases": ["in the foreground"],
            }
        ],
        # At least one false-polarity trap so fabricated_fact_rate is measurable
        # (None when traps=0 is category-vacuity → not_ready; AUDIT-07).
        "reference_facts": [dict(_MEASURABLE_TRAP_FACT)],
    }


# Publishable padding for the W1 audience fixture. One public + one private is
# enough for redaction semantics; RV1-03 raises the adoption sample-size floor to
# SCORE_PASS_MIN_SCORED_IMAGES=5, so three extra publishable rows clear the floor
# without changing withheld_items=1 (the single local-only photo).
_W1_PUBLIC_PAD = (
    (11, "celebs01/biden-flags.jpg", "Joe Biden"),
    (12, "celebs01/harris-stage.jpg", "Kamala Harris"),
    (13, "celebs01/clinton-desk.jpg", "Hillary Clinton"),
)


def _w1_audience_manifest_and_record(tmp_path, *, inject_wrong_name: bool = False):
    """Four publishable celebs + one local-only personal photo (media 20).

    Default is a clean successful score (correct local identity) with measurable
    positional + placement + fabricated-fact categories (π>0) so verdict can
    honestly be pass. Pass ``inject_wrong_name=True`` when the case needs a
    wrong-name floor breach (public redaction, wrong-name failure path).

    Five scored images clear SCORE_PASS_MIN_SCORED_IMAGES (RV1-03); the single
    non-publishable row keeps public redaction assertions (withheld_items=1).
    """
    from scripts.eval_harness.report import SCORE_PASS_MIN_SCORED_IMAGES
    from scripts.eval_harness.schema import SCHEMA, DocKind

    local_identity = "Wrong Celebrity" if inject_wrong_name else _W1_LOCAL_NAME
    public_rows = [
        (_W1_PUBLIC_PATH, "a" * 64, 10, _W1_PUBLIC_NAME, 0.3, "at a podium"),
        *[
            (path, f"{media_id:064x}", media_id, name, 0.3 + 0.05 * (i + 1), "outdoors")
            for i, (media_id, path, name) in enumerate(_W1_PUBLIC_PAD)
        ],
    ]
    entries: list[dict] = []
    items: list[dict] = []
    roster = [_W1_PUBLIC_NAME, _W1_LOCAL_NAME]
    for path, sha, media_id, name, x, scene in public_rows:
        if name not in roster:
            roster.append(name)
        entries.append(
            {
                "path": path,
                "sha256": sha,
                "media_id": media_id,
                "face_count": 1,
                "present_identities": [name],
                "context_pack": {},
                "base_caption": "",
                "must_right": [name],
                # Non-empty easy_wrong so independent vacuity gates do not fire before
                # the wrong-name floor this fixture can exercise (F1-1).
                "easy_wrong": [_W1_LOCAL_NAME],
                "policy": {"recognition_enabled": True},
                "provenance": {
                    "source": "celeb",
                    "license": "public_domain",
                    "publishable": True,
                },
                **_single_name_measurable_fields(name, x=x),
            }
        )
        items.append(
            {
                "media_id": media_id,
                "path": path,
                "describe": {
                    "alt_text_draft": f"{name} in the foreground {scene}.",
                    "visual_facts": {"objects": []},
                },
                "identities": [
                    {
                        "name": name,
                        "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
                        "unpositioned": False,
                    }
                ],
                "face_count": 1,
                "identity_ordering": "positional",
                "image_width": 200,
                "image_height": 200,
                "error": None,
            }
        )
    entries.append(
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
            "provenance": {
                "source": "localwp",
                "license": "consented",
                "publishable": False,
            },
            **_single_name_measurable_fields(_W1_LOCAL_NAME, x=0.5),
        }
    )
    items.append(
        {
            "media_id": 20,
            "path": _W1_LOCAL_PATH,
            "describe": {
                "alt_text_draft": f"{_W1_LOCAL_NAME} in the foreground at a party.",
                "visual_facts": {"objects": []},
            },
            "identities": [
                {
                    "name": local_identity,
                    "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
                    "unpositioned": False,
                }
            ],
            "face_count": 1,
            "identity_ordering": "positional",
            "image_width": 200,
            "image_height": 200,
            "error": None,
        }
    )
    assert len(entries) >= SCORE_PASS_MIN_SCORED_IMAGES
    # VLM6-DELTA-05: every entry here is face_count=1 with exactly one named
    # face_box (_single_name_measurable_fields), so exhaustive coverage holds.
    # roster_only would structurally refuse detection and leave
    # face_detection.precision/recall permanently None -> category-vacuity
    # (not_ready), contradicting the "clean successful score" contract above.
    manifest_path, manifest_sha = _write_score_manifest(tmp_path, entries, roster, annotation_mode="exhaustive")
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
                "items": items,
            }
        )
    )
    return manifest_path, record_path


def test_cmd_score_public_audience_emits_redacted_public_artifact(tmp_path, monkeypatch):  # VLM-6 S5 W1
    """--audience public happy path (VLM6-S2A-A-06): exit 0 + redacted public artifact.

    Clean fixture (correct local identity). Wrong-name redaction lives in a
    separate test so this guard is not coupled to the S2A floor gate (sr-001).
    """
    manifest_path, record_path = _w1_audience_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert (
        main(
            [
                "score",
                "--manifest",
                str(manifest_path),
                "--run-record",
                str(record_path),
                "--audience",
                "public",
            ]
        )
        is None
    )

    public_json = (tmp_path / "run-x-report.public.json").read_text()
    public_md = (tmp_path / "run-x-report.public.md").read_text()
    scored = json.loads(public_json)
    # Only publishable media_ids on the public surface; pad rows + Obama, never media 20.
    public_ids = {10} | {mid for mid, _path, _name in _W1_PUBLIC_PAD}
    assert {p["media_id"] for p in scored["per_image"]} == public_ids
    assert 20 not in {p["media_id"] for p in scored["per_image"]}
    assert scored["redaction"]["withheld_items"] == 1  # single local-only row
    for blob in (public_json, public_md):
        assert _W1_LOCAL_PATH not in blob
        assert _W1_LOCAL_NAME not in blob
        assert _W1_INTERNAL_BASE_URL not in blob  # run-level endpoint redacted (VLM6-S5-BR-01)
    assert _W1_PUBLIC_NAME in public_json
    # The full LOCAL report is still written for operator triage, unredacted.
    local_json = (tmp_path / "run-x-report.json").read_text()
    assert _W1_LOCAL_PATH in local_json
    assert "redaction" not in json.loads(local_json)
    assert json.loads(local_json)["verdict"]["verdict"] == ScoreVerdict.PASS.value


def test_cmd_score_public_audience_redacts_wrong_names(tmp_path, monkeypatch):  # VLM6-S2A-A-06
    """Public artifact withholds wrong_names pairs even when floor exits non-zero."""
    manifest_path, record_path = _w1_audience_manifest_and_record(tmp_path, inject_wrong_name=True)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "score",
                "--manifest",
                str(manifest_path),
                "--run-record",
                str(record_path),
                "--audience",
                "public",
            ]
        )
    assert excinfo.value.code != 0
    assert "wrong-name" in str(excinfo.value).lower()
    public_json = (tmp_path / "run-x-report.public.json").read_text()
    assert "Wrong Celebrity" not in public_json
    assert _W1_LOCAL_PATH not in public_json
    assert _W1_PUBLIC_NAME in public_json


def test_cmd_score_default_local_emits_no_public_artifact(tmp_path, monkeypatch):  # VLM-6 S5 W1
    """Default audience stays byte-compatible: successful score emits no public artifact.

    Restored clean success path (F1-9 / TEST-15): a regression that writes
    public artifacts only on a *successful* default score is caught here.
    Wrong-name failure coverage lives in a separate test (net count up).
    """
    manifest_path, record_path = _w1_audience_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)
    main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)])
    assert (tmp_path / "run-x-report.json").exists()
    assert not (tmp_path / "run-x-report.public.json").exists()
    assert not (tmp_path / "run-x-report.public.md").exists()
    report = json.loads((tmp_path / "run-x-report.json").read_text())
    assert report["verdict"]["verdict"] == ScoreVerdict.PASS.value
    assert "redaction" not in report


def test_cmd_score_default_local_wrong_name_exits_nonzero(tmp_path, monkeypatch):  # VLM-6 S5 W1 / F1-9
    """Default audience with a wrong-name row exits non-zero on the S2A floor.

    Split from the green-path public-artifact guard so both paths stay watched
    (sr-001: do not convert a success test into a failure test).
    """
    manifest_path, record_path = _w1_audience_manifest_and_record(tmp_path, inject_wrong_name=True)
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
            "provenance": {"source": "fixture", "license": "fixture"},
        }
    ]
    manifest_path, manifest_sha = _write_score_manifest(tmp_path, entries, ["Alice Example", "Bob Builder"])
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
            # Boxed GT for the claimed identity (FIR-11: identification scoring
            # refuses unboxed present_identities — require_boxed_identification_gt).
            "face_boxes": [{"name": "Alice Example", "x": 0.4, "y": 0.4, "w": 0.2, "h": 0.3, "source": "iptc"}],
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
            "face_boxes": [{"name": "Bob Builder", "x": 0.4, "y": 0.4, "w": 0.2, "h": 0.3, "source": "iptc"}],
        },
    ]
    manifest_path, manifest_sha = _write_score_manifest(tmp_path, entries, ["Alice Example", "Bob Builder"])
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
    assert report["verdict"]["verdict"] == ScoreVerdict.FAIL.value
    assert report["verdict"]["wrong_name_rate"] > WRONG_NAME_RATE_FLOOR
    assert report["verdict"]["wrong_name_rate_floor"] == WRONG_NAME_RATE_FLOOR
    assert report["verdict"]["reasons"]


# Clean green-path person pairs. Length must clear SCORE_PASS_MIN_SCORED_IMAGES
# (RV1-03 n=5); each row is independently measurable so sample-size is not the
# only reason a clean score can pass.
_CLEAN_SCORE_PERSONS = (
    ("Alice Example", "Bob Builder", "alice", "outdoors"),
    ("Bob Builder", "Alice Example", "bob", "outdoors"),
    ("Carol Decoy", "Dana Friend", "carol", "park"),
    ("Dana Friend", "Carol Decoy", "dana", "cafe"),
    ("Eve Visitor", "Frank Guest", "eve", "beach"),
)


def _clean_score_manifest_and_record(tmp_path, *, stem: str = "run-det"):
    """Minimal clean caption run-record + manifest for score green-path tests.

    Includes face_boxes + spatial_facts + reference_facts trap + asserted
    placement so score exits 0 with verdict=pass (OBS-04 / VLM6-A-05 —
    vacuous fixtures are not_ready). Five scored images clear the RV1-03
    sample-size floor (SCORE_PASS_MIN_SCORED_IMAGES=5).
    """
    from scripts.eval_harness.report import SCORE_PASS_MIN_SCORED_IMAGES
    from scripts.eval_harness.schema import SCHEMA, DocKind

    persons = list(_CLEAN_SCORE_PERSONS)
    while len(persons) < SCORE_PASS_MIN_SCORED_IMAGES:
        i = len(persons) + 1
        persons.append((f"Person{i}A", f"Person{i}B", f"p{i}", f"scene{i}"))

    entries: list[dict] = []
    items: list[dict] = []
    roster: list[str] = []
    for idx, (name, decoy, slug, scene) in enumerate(persons, start=1):
        path = f"mock_images/{slug}.jpg"
        if name not in roster:
            roster.append(name)
        if decoy not in roster:
            roster.append(decoy)
        entries.append(
            {
                "path": path,
                "sha256": f"{idx:064x}",
                "media_id": idx,
                "face_count": 1,
                "present_identities": [name],
                "context_pack": {},
                "base_caption": "",
                "must_right": [name],
                "easy_wrong": [decoy],
                "policy": {"recognition_enabled": True},
                **_single_name_measurable_fields(name, x=0.3 + 0.05 * ((idx - 1) % 5)),
            }
        )
        items.append(
            {
                "media_id": idx,
                "path": path,
                "describe": {
                    "alt_text_draft": f"{name} in the foreground {scene}.",
                    "visual_facts": {"objects": []},
                },
                "identities": [
                    {
                        "name": name,
                        "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
                        "unpositioned": False,
                    }
                ],
                "face_count": 1,
                "identity_ordering": "positional",
                "image_width": 200,
                "image_height": 200,
                "error": None,
            }
        )
    assert len(entries) >= SCORE_PASS_MIN_SCORED_IMAGES
    # VLM6-DELTA-05: every entry here is face_count=1 with exactly one named
    # face_box (_single_name_measurable_fields), so exhaustive coverage holds.
    # roster_only would structurally refuse detection and leave
    # face_detection.precision/recall permanently None -> category-vacuity
    # (not_ready), contradicting this helper's "clean pass" contract.
    manifest_path, manifest_sha = _write_score_manifest(tmp_path, entries, roster, annotation_mode="exhaustive")
    record_path = tmp_path / f"{stem}.json"
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
                "items": items,
            }
        )
    )
    return manifest_path, record_path


def test_cmd_score_exits_zero_when_no_wrong_names_and_no_failures(tmp_path, monkeypatch):
    """Complementary green path: clean identities + measurable categories → exit 0 / pass.

    Fixture supplies face_boxes + spatial_facts + reference_facts trap (π>0)
    so the honest verdict is pass, not not_ready (VLM6-A-05 / OBS-04). RV1-03:
    five scored images clear the sample-size floor.
    """
    from scripts.eval_harness.report import SCORE_PASS_MIN_SCORED_IMAGES

    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path, stem="run-clean")
    monkeypatch.chdir(tmp_path)
    main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)])
    report = json.loads((tmp_path / "run-clean-report.json").read_text())
    assert report["verdict"]["verdict"] == ScoreVerdict.PASS.value
    assert report["verdict"]["wrong_name_rate"] == 0.0
    assert report["verdict"]["reasons"] == []
    assert report["faces"]["identification"]["positional"]["compared_images"] >= 1
    assert report["placement"]["claims"] >= 1
    assert report["counts"]["scored"] >= SCORE_PASS_MIN_SCORED_IMAGES


def test_cmd_score_quality_floor_breach_exits_nonzero(tmp_path, monkeypatch):
    """RV1-01 / TEST-15: quality-floor breach must exit != 0 (not green-exit over fail).

    Pre-fix: report.py stamped quality-floor reasons into verdict=fail, but
    cli.py never wired them into ``_score_gate_fail`` — process exit stayed 0.
    Assert on SystemExit code, not a log line (TEST-15 / EVAL-23 / OBS-04).
    """
    import copy

    import scripts.eval_harness.cli as cli_mod
    from scripts.eval_harness.report import build_score_verdict

    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path, stem="run-qf")
    real = cli_mod.score_run_record

    def _force_position_floor(*args, **kwargs):
        scored = real(*args, **kwargs)
        scored = copy.deepcopy(scored)
        pos = scored["faces"]["identification"]["positional"]
        # Keep compared_images > 0 so the floor is measured-and-bad, not vacuous.
        assert int(pos.get("compared_images") or 0) > 0
        pos["position_accuracy"] = 0.0
        scored["verdict"] = build_score_verdict(scored, rubric_gate=kwargs.get("rubric_gate", "enforce"))
        return scored

    monkeypatch.setattr(cli_mod, "score_run_record", _force_position_floor)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)])
    # Exit status is the contract — not a printed warning.
    assert excinfo.value.code != 0, f"expected non-zero exit, got {excinfo.value.code!r}"
    msg = str(excinfo.value).lower()
    assert "quality-floor" in msg
    assert "score quality-floor gate" in msg
    report = json.loads((tmp_path / "run-qf-report.json").read_text())
    assert report["verdict"]["verdict"] == ScoreVerdict.FAIL.value
    assert any("quality-floor" in r for r in report["verdict"]["reasons"])


def test_cli_score_check_determinism_runs_cross_process_guard(tmp_path, monkeypatch, capsys):
    """--check-determinism on score drives the SHIPPED cross-process guard (VLM-6 S2A item 3).

    Clean case: re-score from the persisted run-record under varied PYTHONHASHSEED
    must pass. Reaching report write without SystemExit means the guard ran and
    matched — not the old same-process double build_reports call.
    """
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
    # C-08 / C-03: gate identity + document named; ERROR class must not fire.
    assert "[score]" in msg
    assert "document=" in msg
    assert "determinism check ERROR" not in msg
    # F7-01: mismatch diagnostic lands in out/, not beside the run-record.
    # F8: address by exact seed filename (randomized baseline → first child seed 0),
    # never glob-index over the shared out/ directory.
    assert "artifact=" in msg
    from scripts.eval_harness.cli import _determinism_artifact_dir

    artifact = _determinism_artifact_dir() / "determinism-mismatch-score-seed0.diff.txt"
    assert artifact.is_file(), "expected mismatch artifact under scripts/eval_harness/out/"
    assert not list(tmp_path.glob("determinism-mismatch-score-seed*.diff.txt"))


def test_cli_score_expect_report_requires_check_determinism(tmp_path, monkeypatch, capsys):
    """F5 / OBS-04: --expect-report alone is rejected (no silent half-gate)."""
    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path)
    expect = tmp_path / "expect.json"
    expect.write_text("{}\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "score",
                "--manifest",
                str(manifest_path),
                "--run-record",
                str(record_path),
                "--expect-report",
                str(expect),
            ]
        )
    msg = str(exc.value)
    assert "--expect-report requires --check-determinism" in msg


def test_cli_score_determinism_seed_failed_not_anchor_mismatch(tmp_path, monkeypatch):
    """Discrimination (OBS-04 / TEST-15): genuine seed diverge stays FAILED.

    Even when --expect-report is set, a cross-process byte mismatch must not be
    re-labeled ANCHOR_MISMATCH — three outcomes, three distinct messages.
    """
    from scripts.eval_harness import cli as cli_mod

    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path)
    # Expect file is whatever the clean score would produce after a successful
    # certify; seed mutation still fires first inside _run_determinism_children.
    from scripts.eval_harness.manifest import load_manifest
    from scripts.eval_harness.report import Audience, build_reports

    record = json.loads(record_path.read_text())
    # Metadata-only: build_reports baseline for expect-report; never opens image bytes.
    man = load_manifest(
        str(manifest_path),
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only; image bytes never opened",
        metadata_only=True,
    )
    entries = [e.model_dump() for e in man.entries]
    base_json, _ = build_reports(
        record,
        entries,
        score_manifest_sha256=cli_mod._manifest_sha(man),
        manifest_roster=sorted(set(getattr(man, "roster", []) or [])),
        audience=Audience.LOCAL,
        rubric_gate="enforce",
    )
    expect = tmp_path / "expect-ok.json"
    expect.write_text(base_json)
    monkeypatch.chdir(tmp_path)

    real_run = cli_mod.subprocess.run

    def _mutate_then_run(*args, **kwargs):
        payload = json.loads(record_path.read_text())
        item = payload["items"][0]
        item["describe"] = {
            "alt_text_draft": "MUTATED CAPTION FOR DETERMINISM GUARD",
            "visual_facts": {"objects": ["definitely-not-in-baseline"]},
        }
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
        cli_mod._check_score_determinism_cross_process(
            record_path,
            str(manifest_path),
            expect_report=expect,
        )
    msg = str(exc.value)
    assert "determinism check FAILED" in msg
    assert "determinism check ANCHOR_MISMATCH" not in msg
    assert "determinism check ERROR" not in msg


def test_cli_score_determinism_guard_errors_on_child_nonzero_rc(tmp_path, monkeypatch):
    """C-03 / OBS-04: child rc != 0 is ERROR (infra), not FAILED (regression).

    A broken environment (e.g. ModuleNotFoundError for scripts.eval_harness)
    must not be reported as a determinism regression — the remedy is operator
    action on the runtime, not a build rollback.
    """
    from scripts.eval_harness import cli as cli_mod

    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)

    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "ModuleNotFoundError: No module named 'scripts.eval_harness'"

    monkeypatch.setattr(cli_mod.subprocess, "run", lambda *a, **k: _Proc())
    with pytest.raises(SystemExit) as exc:
        cli_mod._check_score_determinism_cross_process(record_path, str(manifest_path))
    msg = str(exc.value)
    assert "determinism check ERROR [score]" in msg
    assert "rc=1" in msg
    assert "ModuleNotFoundError" in msg
    assert "determinism check FAILED" not in msg


def _det_payload_path_from_run_args(args, kwargs):
    """Extract the parent-allocated payload path from a subprocess.run call.

    Parent appends the path as the final argv entry of
    ``[exe, "-c", script, *child_argv, payload_path]``.
    """
    cmd = args[0] if args else kwargs.get("args")
    return Path(cmd[-1])


def _det_ok_proc():
    class _Proc:
        returncode = 0
        stdout = "banner-ok-to-ignore\n"
        stderr = ""

    return _Proc()


def test_cli_score_determinism_guard_errors_on_malformed_output(tmp_path, monkeypatch):
    """C-03 / F2b / OBS-04: missing payload file is ERROR, not FAILED.

    Pre-F2b this was "stdout without ---MD--- framing". Transport changed; the
    assertion intent (malformed child output → ERROR class) is preserved.
    """
    from scripts.eval_harness import cli as cli_mod

    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)

    # Child exits 0 but never writes the payload path → missing-file ERROR.
    monkeypatch.setattr(cli_mod.subprocess, "run", lambda *a, **k: _det_ok_proc())
    with pytest.raises(SystemExit) as exc:
        cli_mod._check_score_determinism_cross_process(record_path, str(manifest_path))
    msg = str(exc.value)
    assert "determinism check ERROR [score]" in msg
    assert "payload file missing" in msg
    assert "determinism check FAILED" not in msg


def test_cli_score_determinism_guard_errors_on_unparseable_payload(tmp_path, monkeypatch):
    """F2b / OBS-04: payload present but not valid JSON → ERROR unparseable."""
    from scripts.eval_harness import cli as cli_mod

    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)

    def _write_junk(*args, **kwargs):
        path = _det_payload_path_from_run_args(args, kwargs)
        path.write_text("this-is-not-json{{{")
        return _det_ok_proc()

    monkeypatch.setattr(cli_mod.subprocess, "run", _write_junk)
    with pytest.raises(SystemExit) as exc:
        cli_mod._check_score_determinism_cross_process(record_path, str(manifest_path))
    msg = str(exc.value)
    assert "determinism check ERROR [score]" in msg
    assert "payload file unparseable" in msg
    assert "determinism check FAILED" not in msg


def test_cli_score_determinism_guard_errors_on_unreadable_payload(tmp_path, monkeypatch):
    """F2b / OBS-04: payload path exists but cannot be read → ERROR unreadable.

    Inject OSError on Path.read_text for the payload only — more reliable than
    chmod 0o000 (root / some sandboxes still read mode-0 files).
    """
    from scripts.eval_harness import cli as cli_mod

    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)

    payload_holder: dict[str, Path] = {}

    def _write_payload(*args, **kwargs):
        path = _det_payload_path_from_run_args(args, kwargs)
        path.write_text(json.dumps({"json": "{}", "md": ""}))
        payload_holder["path"] = path
        return _det_ok_proc()

    real_read_text = Path.read_text

    def _read_text(self, *args, **kwargs):
        target = payload_holder.get("path")
        if target is not None and self == target:
            raise OSError(13, "Permission denied", str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(cli_mod.subprocess, "run", _write_payload)
    monkeypatch.setattr(Path, "read_text", _read_text)
    with pytest.raises(SystemExit) as exc:
        cli_mod._check_score_determinism_cross_process(record_path, str(manifest_path))
    msg = str(exc.value)
    assert "determinism check ERROR [score]" in msg
    assert "payload file unreadable" in msg
    assert "determinism check FAILED" not in msg


def test_cli_score_determinism_guard_survives_sentinel_in_freeform_text(tmp_path, monkeypatch, capsys):
    """F2b / C-04 collision: free-form text that lands in the scored report docs
    and contains the old ``---MD---`` sentinel must NOT false-RED the gate.

    Report JSON/MD re-emit identity names (not raw caption drafts). Under the
    old in-band stdout framing, a name containing ``---MD---`` splits at the
    wrong offset so ``sub_json != base_json`` for content-identical docs — a
    false FAILED. Out-of-band payload transport is content-safe.
    """
    from scripts.eval_harness import cli as cli_mod
    from scripts.eval_harness.schema import SCHEMA, DocKind

    # Name embeds the old framing sentinel — re-emitted into report JSON + MD.
    name = "Alice ---MD--- Example"
    entries = [
        {
            "path": "mock_images/alice.jpg",
            "sha256": "a" * 64,
            "media_id": 1,
            "face_count": 1,
            "present_identities": [name],
            "context_pack": {},
            "base_caption": "",
            "must_right": [name],
            "easy_wrong": ["Bob Builder"],
            "policy": {"recognition_enabled": True},
        }
    ]
    manifest_path, manifest_sha = _write_score_manifest(tmp_path, entries, [name, "Bob Builder"])
    caption = f"{name} outdoors."
    record_path = tmp_path / "run-sentinel.json"
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
                            "alt_text_draft": caption,
                            "named_draft": caption,
                            "generic_draft": caption,
                            "visual_facts": {"objects": []},
                        },
                        "identities": [
                            {
                                "name": name,
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
    # Must not SystemExit — genuine match under content-safe transport.
    cli_mod._check_score_determinism_cross_process(record_path, str(manifest_path))
    out = capsys.readouterr().out
    assert "determinism check passed [score]" in out


def test_cli_score_determinism_guard_ignores_stdout_prefix_banner(tmp_path, monkeypatch, capsys):
    """F2b / C-04 prefix contamination: banners on child stdout must not poison
    the comparison. Parent reads the payload file, not stdout.
    """
    from scripts.eval_harness import cli as cli_mod
    from scripts.eval_harness.manifest import load_manifest
    from scripts.eval_harness.report import build_reports

    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)

    record = json.loads(record_path.read_text())
    # Metadata-only: build_reports for determinism baseline; never opens image bytes.
    manifest = load_manifest(
        str(manifest_path),
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only; image bytes never opened",
        metadata_only=True,
    )
    # VLM6-DELTA-06: mirror _check_score_determinism_cross_process's stamp-fill
    # (S2R6E-04) so this locally-built base_json matches what the real parent
    # baseline now produces — otherwise a missing per-entry annotation_mode
    # stamp here would desync from the fixture's stamped exhaustive mode and
    # falsely fail this banner-contamination guard for an unrelated reason.
    entries = []
    for e in manifest.entries:
        row = e.model_dump()
        if row.get("annotation_mode") is None:
            row["annotation_mode"] = manifest.annotation_mode
        entries.append(row)
    ignore_list = cli_mod._load_ignore_list(record_path.parent)
    base_json, base_md = build_reports(
        record,
        entries,
        ignore_list=ignore_list,
        score_manifest_sha256=cli_mod._manifest_sha(manifest),
        manifest_roster=sorted(set(getattr(manifest, "roster", []) or [])),
    )
    reports_file = build_reports.__code__.co_filename

    def _banner_then_payload(*args, **kwargs):
        path = _det_payload_path_from_run_args(args, kwargs)
        path.write_text(
            json.dumps(
                {
                    "json": base_json,
                    "md": base_md,
                    "build_reports_file": reports_file,
                }
            )
        )

        class _Proc:
            returncode = 0
            # Import-time / transitive banner that would prepend to sub_json under
            # the old split("---MD---", 1) transport and false-RED every run.
            stdout = "WARNING: onnxruntime CUDA EP unavailable\n"
            stderr = ""

        return _Proc()

    monkeypatch.setattr(cli_mod.subprocess, "run", _banner_then_payload)
    cli_mod._check_score_determinism_cross_process(record_path, str(manifest_path))
    out = capsys.readouterr().out
    assert "determinism check passed [score]" in out


def test_cli_determinism_guard_labels_distinguish_score_and_face(tmp_path, monkeypatch):
    """C-08 gate-identity: same failure class on both gates must differ by label.

    Caption and face guards share ``_run_determinism_children``; the only
    disambiguator in CI is the interpolated label.
    """
    from scripts.eval_harness import cli as cli_mod
    from scripts.eval_harness.report import build_reports

    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)

    class _Proc:
        returncode = 2
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(cli_mod.subprocess, "run", lambda *a, **k: _Proc())

    with pytest.raises(SystemExit) as score_exc:
        cli_mod._check_score_determinism_cross_process(record_path, str(manifest_path))
    score_msg = str(score_exc.value)
    assert "determinism check ERROR [score]" in score_msg
    assert "[score-face]" not in score_msg

    # Face path needs a face-shaped fixture; re-use the shared substrate directly
    # with the face label so the identity claim does not depend on face score setup.
    with pytest.raises(SystemExit) as face_exc:
        cli_mod._run_determinism_children(
            "import sys; sys.exit(2)",
            [],
            label="score-face",
            base_json="{}",
            base_md="",
            artifact_dir=tmp_path,
            expected_build_reports_file=build_reports.__code__.co_filename,
        )
    face_msg = str(face_exc.value)
    assert "determinism check ERROR [score-face]" in face_msg
    assert face_msg != score_msg
    # Bare [score] label must not appear on the face message (substring of
    # [score-face] is fine only if the full token is [score-face]).
    assert "[score]" not in face_msg.replace("[score-face]", "")
    assert "[score-face]" not in score_msg


def test_cli_score_determinism_guard_pins_import_root_against_cwd_decoy(tmp_path, monkeypatch, capsys):
    """F2c / C-01: child must bind the parent's build_reports, not a cwd decoy.

    Empirically (pre-pin): ``python -c`` puts cwd at sys.path[0], so a decoy
    ``scripts/eval_harness/report.py`` under chdir shadows both an editable
    install and a PYTHONPATH entry. Package is NOT only site-packages-resolved
    here — cwd shadowing is the real hazard. After the pin (cwd=import_root +
    PYTHONPATH prepend + provenance), chdir to a decoy tree must still pass.
    """
    from scripts.eval_harness import cli as cli_mod
    from scripts.eval_harness.report import build_reports

    # Fixture lives under tmp_path/fixture so decoy root can own scripts/.
    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    manifest_path, record_path = _clean_score_manifest_and_record(fixture_dir)

    # Decoy package root: full eval_harness tree via symlinks, only report.py swapped.
    decoy_root = tmp_path / "decoy_root"
    real_eh = Path(cli_mod.__file__).resolve().parent
    decoy_scripts = decoy_root / "scripts"
    decoy_eh = decoy_scripts / "eval_harness"
    decoy_eh.mkdir(parents=True)
    (decoy_scripts / "__init__.py").write_text("")
    for item in real_eh.iterdir():
        if item.name == "report.py":
            continue
        target = decoy_eh / item.name
        if not target.exists():
            target.symlink_to(item)
    # Divergent build_reports — load real report symbols so transitive imports
    # (cli → report constants) succeed, then override build_reports. Pre-pin
    # this forces FAILED; post-pin the decoy is unused.
    real_report = real_eh / "report.py"
    (decoy_eh / "report.py").write_text(
        "from pathlib import Path as _P\n"
        f"_real = _P({str(real_report)!r})\n"
        "exec(compile(_real.read_text(), str(_real), 'exec'), globals())\n"
        "def build_reports(*a, **k):\n"
        "    return ('DECOY_JSON_BYTES', 'DECOY_MD_BYTES')\n"
        "def build_face_reports(*a, **k):\n"
        "    return ('DECOY_JSON_BYTES', 'DECOY_MD_BYTES')\n"
    )
    # Prove decoy shadows under unpinned python -c (documentation of hazard).
    probe = (
        "from scripts.eval_harness.report import build_reports; "
        "print(build_reports.__code__.co_filename); "
        "print(build_reports())"
    )
    probe_proc = cli_mod.subprocess.run(
        [cli_mod.sys.executable, "-c", probe],
        cwd=str(decoy_root),
        capture_output=True,
        text=True,
        env=dict(cli_mod.os.environ),
    )
    assert probe_proc.returncode == 0, probe_proc.stderr
    assert "decoy_root" in probe_proc.stdout
    assert "DECOY_JSON_BYTES" in probe_proc.stdout

    monkeypatch.chdir(decoy_root)
    # Pin must make the guard ignore the decoy and match the parent's module.
    cli_mod._check_score_determinism_cross_process(record_path, str(manifest_path))
    out = capsys.readouterr().out
    assert "determinism check passed [score]" in out
    # Parent module path still the real checkout (not the decoy).
    assert "decoy_root" not in Path(build_reports.__code__.co_filename).resolve().as_posix()


def test_cli_score_determinism_guard_errors_on_build_reports_provenance_mismatch(tmp_path, monkeypatch):
    """F2c / OBS-04: child provenance ≠ parent is ERROR (env drift), not FAILED.

    Names both resolved paths and carries [score]. Operator remedy is fix the
    environment / import root, not hunt a build regression.
    """
    from scripts.eval_harness import cli as cli_mod
    from scripts.eval_harness.manifest import load_manifest
    from scripts.eval_harness.report import build_reports

    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)

    record = json.loads(record_path.read_text())
    # Metadata-only: build_reports for determinism baseline; never opens image bytes.
    manifest = load_manifest(
        str(manifest_path),
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only; image bytes never opened",
        metadata_only=True,
    )
    entries = [e.model_dump() for e in manifest.entries]
    ignore_list = cli_mod._load_ignore_list(record_path.parent)
    base_json, base_md = build_reports(
        record,
        entries,
        ignore_list=ignore_list,
        score_manifest_sha256=cli_mod._manifest_sha(manifest),
        manifest_roster=sorted(set(getattr(manifest, "roster", []) or [])),
    )
    decoy_path = str((tmp_path / "decoy" / "scripts" / "eval_harness" / "report.py").resolve())

    def _wrong_provenance(*args, **kwargs):
        path = _det_payload_path_from_run_args(args, kwargs)
        path.write_text(
            json.dumps(
                {
                    "json": base_json,
                    "md": base_md,
                    "build_reports_file": decoy_path,
                }
            )
        )
        return _det_ok_proc()

    monkeypatch.setattr(cli_mod.subprocess, "run", _wrong_provenance)
    with pytest.raises(SystemExit) as exc:
        cli_mod._check_score_determinism_cross_process(record_path, str(manifest_path))
    msg = str(exc.value)
    assert "determinism check ERROR [score]" in msg
    assert "build_reports module differs" in msg or "import-root drift" in msg
    parent_resolved = str(Path(build_reports.__code__.co_filename).resolve())
    assert parent_resolved in msg
    assert decoy_path in msg
    assert "determinism check FAILED" not in msg


# --- VLM-6 S2A F2d: certify the artifact actually written (GATE-05 / F2C-01) ---


def test_cli_score_determinism_certifies_written_rubric_gate(tmp_path, monkeypatch, capsys):
    """F2d / GATE-05: --rubric-gate skip is certified AND written, not enforce.

    Pre-fix the guard always called build_reports without rubric_gate, so it
    certified verdict.rubric_gate=enforce while _cmd_score wrote skip. After
    fix the on-disk artifact and the certified baseline share skip.
    """
    from scripts.eval_harness import cli as cli_mod
    from scripts.eval_harness.manifest import load_manifest
    from scripts.eval_harness.report import Audience, build_reports

    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)

    # Pre-fix shape: default build_reports stamps enforce even when the
    # operator will write skip — the GATE-05 divergence in one comparison.
    record = json.loads(record_path.read_text())
    # Metadata-only: build_reports for GATE-05 divergence baseline; never opens image bytes.
    manifest = load_manifest(
        str(manifest_path),
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only; image bytes never opened",
        metadata_only=True,
    )
    entries = [e.model_dump() for e in manifest.entries]
    ignore = cli_mod._load_ignore_list(record_path.parent)
    sha = cli_mod._manifest_sha(manifest)
    roster = sorted(set(getattr(manifest, "roster", []) or []))
    default_json, _ = build_reports(
        record, entries, ignore_list=ignore, score_manifest_sha256=sha, manifest_roster=roster
    )
    skip_json, _ = build_reports(
        record,
        entries,
        ignore_list=ignore,
        score_manifest_sha256=sha,
        manifest_roster=roster,
        audience=Audience.LOCAL,
        rubric_gate="skip",
    )
    assert json.loads(default_json)["verdict"]["rubric_gate"] == "enforce"
    assert json.loads(skip_json)["verdict"]["rubric_gate"] == "skip"
    assert default_json != skip_json  # the certified-vs-written gap at base

    main(
        [
            "score",
            "--manifest",
            str(manifest_path),
            "--run-record",
            str(record_path),
            "--rubric-gate",
            "skip",
            "--check-determinism",
        ]
    )
    out = capsys.readouterr().out
    assert "determinism check passed [score]" in out
    written = json.loads((tmp_path / "run-det-report.json").read_text())
    assert written["verdict"]["rubric_gate"] == "skip"
    # Certified baseline returned by the guard must equal the written bytes.
    certified_json, _ = cli_mod._check_score_determinism_cross_process(
        record_path,
        str(manifest_path),
        rubric_gate="skip",
        audience=Audience.LOCAL,
        label="score",
    )
    assert json.loads(certified_json)["verdict"]["rubric_gate"] == "skip"
    assert certified_json == (tmp_path / "run-det-report.json").read_text()


def test_cli_score_audience_public_check_determinism_covers_both_labels(tmp_path, monkeypatch, capsys):
    """F2d / TEST-15: --audience public --check-determinism certifies LOCAL + PUBLIC.

    Structural coverage proof: both labels print a passed line. Clean control
    still exits 0 (discrimination control — a battery of only reds proves nothing).
    """
    manifest_path, record_path = _w1_audience_manifest_and_record(tmp_path, inject_wrong_name=False)
    monkeypatch.chdir(tmp_path)
    main(
        [
            "score",
            "--manifest",
            str(manifest_path),
            "--run-record",
            str(record_path),
            "--audience",
            "public",
            "--check-determinism",
        ]
    )
    out = capsys.readouterr().out
    assert "determinism check passed [score]" in out
    assert "determinism check passed [score-public]" in out
    assert (tmp_path / "run-x-report.json").exists()
    assert (tmp_path / "run-x-report.public.json").exists()
    local = json.loads((tmp_path / "run-x-report.json").read_text())
    public = json.loads((tmp_path / "run-x-report.public.json").read_text())
    assert "redaction" not in local
    assert public["redaction"]["audience"] == "public"
    assert public["redaction"]["withheld_items"] == 1


def test_cli_score_determinism_public_label_fails_on_mismatch(tmp_path, monkeypatch):
    """F2d / TEST-15: genuine public-artifact mismatch exits FAILED [score-public]."""
    from scripts.eval_harness import cli as cli_mod
    from scripts.eval_harness.report import Audience

    manifest_path, record_path = _w1_audience_manifest_and_record(tmp_path, inject_wrong_name=False)
    monkeypatch.chdir(tmp_path)

    real_run = cli_mod.subprocess.run

    def _mutate_then_run(*args, **kwargs):
        payload = json.loads(record_path.read_text())
        # Mutate only the local-only item's caption: LOCAL report changes, and
        # PUBLIC withholds that item — but flipping the public item forces a
        # public-pair divergence the score-public label must name.
        for item in payload["items"]:
            if item["media_id"] == 10:
                item["describe"] = {
                    "alt_text_draft": "PUBLIC-ONLY MUTATION FOR DETERMINISM",
                    "visual_facts": {"objects": ["public-divergence"]},
                }
        record_path.write_text(json.dumps(payload))
        return real_run(*args, **kwargs)

    monkeypatch.setattr(cli_mod.subprocess, "run", _mutate_then_run)
    with pytest.raises(SystemExit) as exc:
        cli_mod._check_score_determinism_cross_process(
            record_path,
            str(manifest_path),
            rubric_gate="enforce",
            audience=Audience.PUBLIC,
            label="score-public",
        )
    msg = str(exc.value)
    assert "determinism check FAILED [score-public]" in msg
    assert "determinism check ERROR" not in msg


def test_cli_score_determinism_resolves_relative_paths_from_foreign_cwd(tmp_path, monkeypatch, capsys):
    """F2C-01: relative record/manifest paths survive package-root cwd pin.

    Parent may be invoked from a fixture directory with relative paths; the
    child runs with cwd=package root. Unresolved argv → FileNotFoundError ERROR.
    """
    from scripts.eval_harness import cli as cli_mod

    work = tmp_path / "fixture_dir"
    work.mkdir()
    manifest_path, record_path = _clean_score_manifest_and_record(work)
    # chdir to fixture dir; pass relative basenames only.
    monkeypatch.chdir(work)
    rel_record = Path(record_path.name)
    rel_manifest = Path(manifest_path.name)
    assert not rel_record.is_absolute()
    assert not rel_manifest.is_absolute()
    # Guard must resolve against the caller's view, not the pin.
    cli_mod._check_score_determinism_cross_process(rel_record, str(rel_manifest))
    out = capsys.readouterr().out
    assert "determinism check passed [score]" in out


# --- VLM-6 S2A F2e: C-05 seed regime naming + D-05 seed-dimension proof ---


def test_parent_hash_seed_regime_names_fixed_and_randomized(monkeypatch):
    """C-05: parent regime distinguishes fixed:<n> from randomized (OBS-04)."""
    from scripts.eval_harness import cli as cli_mod

    monkeypatch.setenv("PYTHONHASHSEED", "0")
    label, fixed = cli_mod._parent_hash_seed_regime()
    assert label == "fixed:0"
    assert fixed == "0"

    monkeypatch.setenv("PYTHONHASHSEED", "42")
    label, fixed = cli_mod._parent_hash_seed_regime()
    assert label == "fixed:42"
    assert fixed == "42"

    monkeypatch.delenv("PYTHONHASHSEED", raising=False)
    # Ambient pytest process typically has hash_randomization on; if not, the
    # helper still returns a named fixed:0 rather than an empty claim.
    label, fixed = cli_mod._parent_hash_seed_regime()
    assert label in ("randomized", "fixed:0")
    if label == "randomized":
        assert fixed is None
    else:
        assert fixed == "0"


def test_resolve_determinism_child_seeds_substitutes_parent_collision():
    """C-05: PYTHONHASHSEED=0 must not silently drop a child configuration.

    Pre-fix: child set (0,1,42) + parent fixed:0 → four configs collapse to
    three (seed-0 child duplicates baseline). Post-fix: substitute so children
    remain three distinct seeds, none equal to the parent.
    """
    from scripts.eval_harness import cli as cli_mod

    # No parent fixed → default set unchanged.
    assert cli_mod._resolve_determinism_child_seeds(None) == ("0", "1", "42")

    # Parent fixed at 0 collides with first child → substitute lowest free int.
    resolved = cli_mod._resolve_determinism_child_seeds("0")
    assert resolved == ("2", "1", "42")
    assert "0" not in resolved
    assert len(set(resolved)) == 3

    # Parent fixed at 1 collides mid-set.
    resolved = cli_mod._resolve_determinism_child_seeds("1")
    assert resolved == ("0", "2", "42")
    assert "1" not in resolved
    assert len(set(resolved)) == 3


def test_cli_score_determinism_pass_names_baseline_and_child_seeds(tmp_path, monkeypatch, capsys):
    """C-05 / OBS-04: pass line names parent regime and exact child seed set."""
    from scripts.eval_harness import cli as cli_mod

    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)
    # Force a fixed parent seed so the claim is deterministic in CI.
    monkeypatch.setenv("PYTHONHASHSEED", "7")
    cli_mod._check_score_determinism_cross_process(record_path, str(manifest_path))
    out = capsys.readouterr().out
    assert "determinism check passed [score]" in out
    assert "baseline=fixed:7" in out
    assert "child_seeds=0,1,42" in out


def test_cli_score_determinism_collision_substitutes_seed_zero(tmp_path, monkeypatch, capsys):
    """C-05 collision: parent PYTHONHASHSEED=0 → child set substitutes 0→2.

    Pre-change behaviour: child seeds (0,1,42) with parent fixed:0 silently
    tested only three distinct configs (seed-0 child == baseline). Post-change
    pass line must claim child_seeds=2,1,42 (or equivalent without 0).
    """
    from scripts.eval_harness import cli as cli_mod

    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    cli_mod._check_score_determinism_cross_process(record_path, str(manifest_path))
    out = capsys.readouterr().out
    assert "determinism check passed [score]" in out
    assert "baseline=fixed:0" in out
    assert "child_seeds=2,1,42" in out
    # Must not claim the colliding seed as a distinct child configuration.
    assert "child_seeds=0,1,42" not in out


def test_cli_score_determinism_fail_artifact_carries_baseline_regime(tmp_path, monkeypatch):
    """C-05: FAILED message + mismatch artifact name baseline + child seeds.

    F8: isolate diagnostics to this test's tmp_path and read the exact seed
    filename (parent fixed:0 → first child seed is 2). Glob-index over the
    shared out/ directory is platform-order-dependent (VLM6-S2A-F7-02).
    """
    from scripts.eval_harness import cli as cli_mod

    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    # Content assertions must not see sibling tests' files in shared out/.
    monkeypatch.setattr(cli_mod, "_determinism_artifact_dir", lambda: tmp_path)

    real_run = cli_mod.subprocess.run

    def _mutate_then_run(*args, **kwargs):
        payload = json.loads(record_path.read_text())
        item = payload["items"][0]
        item["describe"] = {
            "alt_text_draft": "MUTATED CAPTION FOR REGIME ARTIFACT",
            "visual_facts": {"objects": ["regime-probe"]},
        }
        record_path.write_text(json.dumps(payload))
        return real_run(*args, **kwargs)

    monkeypatch.setattr(cli_mod.subprocess, "run", _mutate_then_run)
    with pytest.raises(SystemExit) as exc:
        cli_mod._check_score_determinism_cross_process(record_path, str(manifest_path))
    msg = str(exc.value)
    assert "determinism check FAILED [score]" in msg
    assert "baseline=fixed:0" in msg
    assert "child_seeds=2,1,42" in msg
    assert "determinism check ERROR" not in msg

    # Exact name: parent PYTHONHASHSEED=0 → child seeds (2,1,42); first fail is seed 2.
    artifact = tmp_path / "determinism-mismatch-score-seed2.diff.txt"
    assert artifact.is_file(), f"expected exact artifact path {artifact}"
    body = artifact.read_text()
    assert "baseline_regime=fixed:0" in body
    assert "child_seeds=2,1,42" in body
    # Child seed that fired is recorded and is not the colliding parent seed.
    assert "PYTHONHASHSEED=" in body
    assert "PYTHONHASHSEED=0\n" not in body


def test_f8_determinism_artifact_content_ignores_shared_out_decoy(tmp_path, monkeypatch):
    """F8 / TEST-15 / DBG-11: shared out/ decoy must not set suite colour.

    Pre-F8 the regime test selected ``artifacts[0]`` after a glob of shared
    ``scripts/eval_harness/out/``. A sibling test's seed0 file
    (``baseline_regime=randomized``) made the suite green or red depending on
    readdir order. This control plants that decoy (and a poisoned seed2) in
    the real out/ dir, isolates diagnostics to ``tmp_path``, and reads the
    exact seed2 filename — the green is independent of shared-directory state.
    """
    from scripts.eval_harness import cli as cli_mod
    from scripts.eval_harness.cli import _determinism_artifact_dir

    shared = _determinism_artifact_dir()
    decoy = shared / "determinism-mismatch-score-seed0.diff.txt"
    poison = shared / "determinism-mismatch-score-seed2.diff.txt"
    try:
        decoy.write_text("gate=score\nbaseline_regime=randomized\nchild_seeds=0,1,42\nPYTHONHASHSEED=0\n")
        poison.write_text("gate=score\nbaseline_regime=randomized\nchild_seeds=0,1,42\nPOISONED_SHARED_OUT\n")
        # Prove the old selection form would be order-dependent against these files.
        globbed = list(shared.glob("determinism-mismatch-score-seed*.diff.txt"))
        assert decoy in globbed and poison in globbed
        seed0_first = sorted(globbed, key=lambda p: p.name)
        assert "baseline_regime=fixed:0" not in seed0_first[0].read_text()

        manifest_path, record_path = _clean_score_manifest_and_record(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PYTHONHASHSEED", "0")
        monkeypatch.setattr(cli_mod, "_determinism_artifact_dir", lambda: tmp_path)

        real_run = cli_mod.subprocess.run

        def _mutate_then_run(*args, **kwargs):
            payload = json.loads(record_path.read_text())
            item = payload["items"][0]
            item["describe"] = {
                "alt_text_draft": "MUTATED CAPTION FOR F8 DECOY CONTROL",
                "visual_facts": {"objects": ["f8-decoy-probe"]},
            }
            record_path.write_text(json.dumps(payload))
            return real_run(*args, **kwargs)

        monkeypatch.setattr(cli_mod.subprocess, "run", _mutate_then_run)
        with pytest.raises(SystemExit) as exc:
            cli_mod._check_score_determinism_cross_process(record_path, str(manifest_path))
        msg = str(exc.value)
        assert "determinism check FAILED [score]" in msg
        assert "baseline=fixed:0" in msg

        # Exact path under isolated dir — never glob-index, never shared out/.
        artifact = tmp_path / "determinism-mismatch-score-seed2.diff.txt"
        assert artifact.is_file()
        body = artifact.read_text()
        assert "baseline_regime=fixed:0" in body
        assert "child_seeds=2,1,42" in body
        assert "POISONED_SHARED_OUT" not in body
        assert "baseline_regime=randomized" not in body
        # Shared decoy/poison still present and still wrong during isolation check.
        assert "baseline_regime=randomized" in decoy.read_text()
        assert "POISONED_SHARED_OUT" in poison.read_text()
    finally:
        # VLM6-S2A-F8-01: never leave decoys in the real shared out/ after the test.
        decoy.unlink(missing_ok=True)
        poison.unlink(missing_ok=True)


def test_determinism_gate_detects_hash_order_dependence(tmp_path):
    """D-05 / TEST-15: gate goes red because of PYTHONHASHSEED, not anchor mutation.

    Injects a set-repr into the compared documents. Set iteration order varies
    with PYTHONHASHSEED, so parent baseline and seed-varied children diverge
    without mutating any run-record on disk. Proves the seed dimension is
    load-bearing for the gate substrate.
    """
    from scripts.eval_harness import cli as cli_mod
    from scripts.eval_harness.report import build_reports

    # Large set → hash-order divergence across seeds is effectively certain.
    probe_src = "seed-probe-" + "".join(chr(c) for c in range(ord("a"), ord("z") + 1))
    probe = set(probe_src)
    base = "SEED_PROBE:" + repr(probe)
    reports_file = build_reports.__code__.co_filename
    # Child rebuilds the same set under its pinned PYTHONHASHSEED; repr order
    # differs from the parent process unless seeds coincide (C-05 substitution
    # keeps children distinct from a fixed parent; randomized parent still
    # diverges from fixed child seeds with overwhelming probability).
    script = (
        "import json,sys; "
        "from pathlib import Path; "
        "from scripts.eval_harness.report import build_reports; "
        f"probe=set({probe_src!r}); "
        "doc='SEED_PROBE:'+repr(probe); "
        "Path(sys.argv[1]).write_text(json.dumps({"
        "'json':doc,'md':doc,"
        "'build_reports_file':build_reports.__code__.co_filename}))"
    )
    with pytest.raises(SystemExit) as exc:
        cli_mod._run_determinism_children(
            script,
            [],
            label="score",
            base_json=base,
            base_md=base,
            artifact_dir=tmp_path,
            expected_build_reports_file=reports_file,
        )
    msg = str(exc.value)
    assert "determinism check FAILED [score]" in msg
    assert "baseline=" in msg
    assert "child_seeds=" in msg
    assert "determinism check ERROR" not in msg
    # F8: exact filename from the FAILED message path (not glob-index).
    # Randomized parent → first child seed is 0; artifact_dir is this test's tmp_path.
    artifact = tmp_path / "determinism-mismatch-score-seed0.diff.txt"
    assert artifact.is_file(), f"expected seed-order mismatch artifact at {artifact}"
    body = artifact.read_text()
    assert "SEED_PROBE:" in body
    assert "baseline_regime=" in body


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
        entry = {
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
            # Measurable categories so clean runs can honestly pass (VLM6-A-05).
            **_single_name_measurable_fields(name, x=0.3 + 0.05 * (i % 5)),
        }
        entries.append(entry)
    return roster, entries


def _score_run_record(
    entries: list[dict],
    *,
    caption_fn,
    identity_fn,
    manifest_sha: str,
    aborted: bool = False,
):
    """Build an in-memory run-record dict for score guards (VLM6-S2A-A-08).

    Filename is not part of the record body — callers write to their own
    ``record_path`` under ``tmp_path``. ``aborted`` stamps the partial-run flag.
    Items stamp identity_ordering + image dims so centre-based positional can run.
    """
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
                "identity_ordering": "positional",
                "image_width": 200,
                "image_height": 200,
                "error": None,
            }
        )
    record = {
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
    if aborted:
        record["aborted"] = True
    return record


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
        identity_fn=lambda e: [_score_identity(e["present_identities"][0])] if e["present_identities"] else [],
        manifest_sha=manifest_sha,
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
    under default enforce. With --rubric-gate skip on a corpus with measurable
    positional/placement (π>0), the same record exits 0 as pass_ungated.
    Vacuous real-golden skip is a separate test (not_ready, not pass_ungated).
    """
    roster, entries = _corpus_entries(6, with_rubric=True)
    # Leave one entry without must_right and without present identities so
    # generic caption scores gated 1.0 (seeded no-name shape on real golden).
    entries[-1]["must_right"] = []
    entries[-1]["present_identities"] = []
    entries[-1]["face_boxes"] = []  # no named GT on the empty entry
    # VLM6-DELTA-05: exhaustive coverage requires n_boxes == face_count per
    # entry; the empty entry has no named GT, so it must also declare zero
    # faces present (not the corpus default of 1) to stay a valid exhaustive
    # manifest rather than an under-boxed one.
    entries[-1]["face_count"] = 0
    entries[-1]["spatial_facts"] = [
        {
            "subject": "a human",
            "relation": "foreground",
            "phrases": ["in the foreground"],
        }
    ]
    assert entries[-1]["easy_wrong"]  # independent vacuity still non-empty
    # VLM6-DELTA-05: face_detection.precision/recall must be measurable for an
    # honest pass_ungated verdict (roster_only structurally refuses detection).
    manifest_path, manifest_sha = _write_score_manifest(tmp_path, entries, roster, annotation_mode="exhaustive")
    record = _score_run_record(
        entries,
        # Avoid the token "person" — synthetic easy_wrong names are "Person N"
        # and token-level traps would fire the wrong-name floor gate.
        # Assert placement so placement claims > 0 (not vacuous).
        caption_fn=lambda _e: "A human standing in the foreground outdoors near greenery.",
        # Correct centre-ordered identity rows so positional is evaluable (not π=0).
        identity_fn=lambda e: [_score_identity(e["present_identities"][0])] if e.get("present_identities") else [],
        manifest_sha=manifest_sha,
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
    assert report["verdict"]["verdict"] == ScoreVerdict.PASS_UNGATED.value
    assert report["verdict"]["must_right_failed_images"] > 0
    assert report["faces"]["identification"]["positional"]["compared_images"] >= 1
    assert report["placement"]["claims"] >= 1


def test_score_report_records_rubric_gate_flag(tmp_path, monkeypatch):
    """F1b-2: report + verdict stamp --rubric-gate so skip is never a silent pass."""
    roster, entries = _corpus_entries(6, with_rubric=True)
    # VLM6-DELTA-05: exhaustive so face_detection.precision/recall are
    # measurable (honest PASS, not category-vacuity not_ready).
    manifest_path, manifest_sha = _write_score_manifest(tmp_path, entries, roster, annotation_mode="exhaustive")
    record = _score_run_record(
        entries,
        # Assert placement phrase so placement is measurable (honest pass).
        caption_fn=lambda e: f"{e['present_identities'][0]} in the foreground outdoors smiling.",
        identity_fn=lambda e: [_score_identity(e["present_identities"][0])],
        manifest_sha=manifest_sha,
    )
    record_path = tmp_path / "run-rubric-flag.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    # Default enforce is recorded even when the gate does not fire.
    assert main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)]) is None
    report = json.loads(record_path.with_name("run-rubric-flag-report.json").read_text(encoding="utf-8"))
    assert report["verdict"]["rubric_gate"] == "enforce"
    assert report["verdict"]["verdict"] == ScoreVerdict.PASS.value
    md = record_path.with_name("run-rubric-flag-report.md").read_text(encoding="utf-8")
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


def test_score_fetch_sha_drift_fails_closed_without_relabel_flag(tmp_path, monkeypatch):
    """VLM6-F-03 / EVAL-13: score-time vs fetch-time manifest drift hard-fails.

    Pre-fix (F1-3) allowed drift with a warning so archival re-scores under
    evolved labels stayed green — that also certified incomparable numbers.
    After fix: exit non-zero unless ``--allow-manifest-relabel`` (non_comparable).
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
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)])
    assert excinfo.value.code != 0
    msg = str(excinfo.value).lower()
    assert "manifest-drift" in msg or "manifest_matches_fetch" in msg
    assert "allow-manifest-relabel" in msg


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
    manifest_path, full_sha = _write_score_manifest(tmp_path, full_entries, roster, name="golden.json")
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
    """Full seed-golden run-record from scene/tests/seed/golden.json that scores clean.

    identities are dict rows (bare strings rejected by _validate_identities_element_types).
    Caption text lives in describe.alt_text_draft / named_draft / generic_draft.
    """
    from scripts.eval_harness.cli import _manifest_sha
    from scripts.eval_harness.manifest import load_manifest
    from scripts.eval_harness.schema import SCHEMA, DocKind

    # Metadata-only: builds synthetic run-record from roster/must_right; never opens image bytes.
    manifest = load_manifest(
        str(_GOLDEN_SEED),
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only; image bytes never opened",
        metadata_only=True,
    )
    entries = [e.model_dump() for e in manifest.entries]
    assert entries, "golden corpus loaded empty"
    msha = _manifest_sha(manifest)
    items = []
    for entry in entries:
        names = list(entry.get("present_identities") or [])
        must = list(entry.get("must_right") or [])
        cap = " ".join(must + names + ["outdoors smiling."]) if (must or names) else "A scenic outdoor photograph."
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
    """Seed-golden run-record with a wrong identity on every image.

    Returns (manifest_path, record, ignore_pairs) where ignore_pairs covers every
    asserted wrong name so an ignore-list can silence the pre-fix floor gate.
    """
    from scripts.eval_harness.cli import _manifest_sha
    from scripts.eval_harness.manifest import load_manifest
    from scripts.eval_harness.schema import SCHEMA, DocKind

    # Metadata-only: builds synthetic wrong-name record from roster; never opens image bytes.
    manifest = load_manifest(
        str(_GOLDEN_SEED),
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only; image bytes never opened",
        metadata_only=True,
    )
    entries = [e.model_dump() for e in manifest.entries]
    assert entries, "golden corpus loaded empty"
    msha = _manifest_sha(manifest)
    roster = list(manifest.roster or [])
    items: list[dict] = []
    ignore_pairs: list[list[str]] = []
    for entry in entries:
        names = list(entry.get("present_identities") or [])
        must = list(entry.get("must_right") or [])
        cap = " ".join(must + names + ["outdoors smiling."]) if (must or names) else "A scenic outdoor photograph."
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


def _boxed_golden_manifest(tmp_path, *, name: str = "golden-boxed.json") -> tuple[Path, str]:
    """Boxed roster_only variant of _GOLDEN_SEED (VLM6-DELTA-07).

    The checked-in golden.json is intentionally unboxed (0/N face_boxes,
    README-documented) so identification is structurally refused
    (identification_refuses_unboxed_identity_claims) — under FIR-11 a refused
    identification block always stamps wrong_names=None, which makes
    face_wrong_name_rate() read 0.0 regardless of what the run-record claims,
    so the wrong-name floor gate can never fire against the real unboxed
    fixture. Tests that need the floor gate itself to be measurable require a
    manifest with a named face_box per present_identities entry so
    require_boxed_identification_gt() is satisfied. This helper builds that
    variant into tmp_path without touching the checked-in seed file or the
    shared _real_golden_good_record/_real_golden_wrong_name_record helpers
    (used unboxed by 15+ other, unrelated passing tests). roster_only is kept
    (not exhaustive) — these tests exit at the wrong-name-floor gate, which
    fires before category-vacuity/detection-refusal is ever consulted, so
    detection staying refused under roster_only is immaterial here.
    """
    import copy

    from scripts.eval_harness.cli import _manifest_sha
    from scripts.eval_harness.manifest import load_manifest

    raw = json.loads(_GOLDEN_SEED.read_text())
    boxed = copy.deepcopy(raw)
    for entry in boxed["entries"]:
        names = list(entry.get("present_identities") or [])
        lineage = dict(_TEST_LINEAGE_NAMED)
        lineage["decision"] = "named"
        entry["face_boxes"] = [
            {"x": 10.0, "y": 40.0, "w": 50.0, "h": 60.0, "name": n, "source": "iptc", "lineage": lineage} for n in names
        ]
    manifest_path = tmp_path / name
    manifest_path.write_text(json.dumps(boxed))
    return manifest_path, _manifest_sha(
        load_manifest(
            str(manifest_path),
            skip_hash_verification=True,
            hash_skip_reason="test metadata-only; image bytes never opened",
            metadata_only=True,
        )
    )


def test_score_ignore_list_cannot_defeat_wrong_name_floor(tmp_path, monkeypatch):
    """F1-5 (a): ignore-list covering 100% wrong names must still fail floor.

    Pre-fix: ignore-list moved every pair into ignored_wrong_names → rate=0,
    verdict=pass, exit 0. Gate must count live + ignored; presentation split
    remains (ignored_wrong_names populated, live wrong_names empty).

    VLM6-DELTA-07: the real golden.json is unboxed, so identification is
    structurally refused there and wrong_names is stamped None (never
    measurable) — a boxed manifest variant is required to make this floor
    gate itself reachable; see _boxed_golden_manifest.
    """
    from scripts.eval_harness.report import WRONG_NAME_RATE_FLOOR

    _golden, record, ignore_pairs = _real_golden_wrong_name_record()
    assert len(ignore_pairs) == len(record["items"])
    boxed_manifest, boxed_sha = _boxed_golden_manifest(tmp_path)
    record = {**record, "provenance": {**record["provenance"], "manifest_sha256": boxed_sha}}
    record_path = tmp_path / "run-ignore-defeat.json"
    record_path.write_text(json.dumps(record))
    (tmp_path / "ignore-list.json").write_text(json.dumps({"wrong_names": ignore_pairs}))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(boxed_manifest), "--run-record", str(record_path)])
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
    assert len(ident["ignored_wrong_names"]) == len(record["items"])
    assert report["verdict"]["wrong_name_rate"] > WRONG_NAME_RATE_FLOOR
    assert report["verdict"]["verdict"] == ScoreVerdict.FAIL.value
    assert report["verdict"]["wrong_name_rate"] == pytest.approx(1.0)


def test_score_recognition_disabled_corpus_fails_wrong_name_floor_vacuity(tmp_path, monkeypatch):
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
    # Metadata-only: score path uses policy/must_right only; never opens image bytes.
    manifest = load_manifest(
        str(man_path),
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only; image bytes never opened",
        metadata_only=True,
    )
    entries = [e.model_dump() for e in manifest.entries]
    assert entries, "golden corpus loaded empty"
    assert all(not e["policy"]["recognition_enabled"] for e in entries)
    msha = _manifest_sha(manifest)
    roster = list(manifest.roster or [])
    items = []
    for entry in entries:
        names = list(entry.get("present_identities") or [])
        must = list(entry.get("must_right") or [])
        cap = " ".join(must + names + ["outdoors smiling."]) if (must or names) else "A scenic outdoor photograph."
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
    assert len(ident["excluded_images"]) == len(entries)
    assert ident["wrong_names"] == []
    # F1d-1: vacuity must persist fail (pre-fix left verdict=pass while exit 1).
    assert report["verdict"]["verdict"] == ScoreVerdict.FAIL.value
    assert any("wrong-name floor vacuity" in r for r in report["verdict"]["reasons"])


# --- VLM-6 S2A F1d-1: persisted verdict encodes every exit condition (OBS-04) ---


def _assert_on_disk_fail_reason(report: dict, *, must_contain: str, must_not: tuple[str, ...]) -> None:
    """On-disk artifact (not stdout) is the contract: fail + class-unique reason."""
    assert report["verdict"]["verdict"] == ScoreVerdict.FAIL.value
    reasons = report["verdict"]["reasons"]
    assert reasons, "fail verdict must list reasons"
    blob = " | ".join(reasons).lower()
    assert must_contain.lower() in blob
    for other in must_not:
        assert other.lower() not in blob, f"reason class leaked: {other!r} in {reasons!r}"


def test_score_persisted_verdict_not_ready_on_real_golden(tmp_path, monkeypatch):
    """F1d-1 / VLM6-A-05: clean real golden (π=0 face_boxes/spatial_facts) → not_ready.

    Renamed from control_pass: the 37-item harness has face_boxes/spatial_facts
    on 0/37, so the honest artifact is not_ready (not pass). OBS-04: process
    exit is non-zero to match the artifact. A genuine pass control lives on
    measurable synthetic fixtures (e.g. test_cmd_score_exits_zero_...).

    VLM6-GATE-INT-01 (supersedes VLM6-DELTA-06's gate-ordering claim on this
    test): the real golden fixture is roster_only + 0/37 boxed, so BOTH
    detection and identification are structurally refused — but the real
    golden corpus also has 0/37 spatial_facts, making ``placement``
    genuinely vacuous independent of that refusal. The category-vacuity
    gate now suppresses only the reasons that are pure restatements of a
    refused identification/detection (``positional``, ``identity_ordering``,
    ``face_identification.*``, and — since detection also refuses here —
    ``face_detection.*``); ``placement`` is not identification-derived, so
    it survives and the category-vacuity gate fires ahead of
    ``raise_if_unconsented_refusals`` (a category-vacuity exit string, not
    ``REFUSED_METRIC_EXIT_CODE``). VLM6-DELTA-06's "unconsented refusal
    always wins the race" premise only held under the pre-fix, over-broad
    gate that skipped category-vacuity entirely whenever identification
    refused — the same bug VLM6-GATE-INT-01 fixes. The persisted artifact is
    unaffected (report.py writes the scored document before any exit gate
    runs), so the verdict/positional-vacuity assertions below still hold
    against the same on-disk not_ready report.
    """
    from scripts.eval_harness.cli import SCORE_GATE_PREFIX_CATEGORY_VACUITY

    golden, record = _real_golden_good_record()
    record_path = tmp_path / "run-control-not-ready.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(golden), "--run-record", str(record_path)])
    assert isinstance(excinfo.value.code, str)
    assert excinfo.value.code.startswith(SCORE_GATE_PREFIX_CATEGORY_VACUITY)
    assert "placement" in excinfo.value.code
    report = json.loads(record_path.with_name("run-control-not-ready-report.json").read_text())
    assert report["verdict"]["verdict"] == ScoreVerdict.NOT_READY.value
    reasons_blob = " | ".join(report["verdict"]["reasons"]).lower()
    assert "positional" in reasons_blob
    assert "placement" in reasons_blob
    assert report["verdict"]["rubric_gate"] == "enforce"
    assert report["counts"]["scored"] == len(record["items"])
    # B-10: machine-readable positional vacuity on the real corpus.
    pos = report["faces"]["identification"]["positional"]
    assert pos["compared_images"] == 0
    assert pos["evaluable"] is False
    assert pos["status"] == "not_evaluable"
    assert pos["vacuity_signal"]


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
    # Metadata-only: empty must_right scoring fixture; never opens image bytes.
    manifest = load_manifest(
        str(man_path),
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only; image bytes never opened",
        metadata_only=True,
    )
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
    """F1d-1: 100% wrong names → on-disk fail + wrong_name_rate reason.

    VLM6-DELTA-07: boxed manifest variant — see _boxed_golden_manifest;
    the unboxed real golden refuses identification, which would leave
    wrong_name_rate stamped 0.0 and never reach this gate.
    """
    _golden, record, _ignore = _real_golden_wrong_name_record()
    boxed_manifest, boxed_sha = _boxed_golden_manifest(tmp_path)
    record = {**record, "provenance": {**record["provenance"], "manifest_sha256": boxed_sha}}
    record_path = tmp_path / "run-wn-floor.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(boxed_manifest), "--run-record", str(record_path)])
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


def test_score_persisted_verdict_skip_still_not_ready_on_real_golden(tmp_path, monkeypatch):
    """F1d-1 / OBS-04: --rubric-gate skip does not clear category vacuity on real golden.

    Skip only exempts must-right failures. Real golden still has π=0 positional
    and placement, so the honest verdict is not_ready (never pass_ungated over
    an unmeasurable corpus). pass_ungated is covered by the measurable skip
    fixture in test_score_guard_rubric_gate_skip_bypasses_must_right_gate.
    """
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
    with pytest.raises(SystemExit) as excinfo:
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
    assert excinfo.value.code != 0
    report = json.loads(record_path.with_name("run-ungated-report.json").read_text())
    assert report["verdict"]["verdict"] == ScoreVerdict.NOT_READY.value
    assert report["verdict"]["rubric_gate"] == "skip"
    assert report["verdict"]["must_right_failed_images"] > 0
    reasons_blob = " | ".join(report["verdict"]["reasons"]).lower()
    assert "positional" in reasons_blob or "placement" in reasons_blob


# --- VLM-6 S2A F1d-2: rounding floor (F1-7) + scored-set rubric denominator (F1-8) ---


def test_score_one_wrong_name_real_golden_exits_nonzero(tmp_path, monkeypatch):
    """F1-7 real-corpus: exactly 1 wrong name among 37 must exit non-zero (floor=0).

    1/37 ≈ 0.0270 does not round to 0.0 — this is the non-scaled real-corpus case
    that must still fail. Discrimination control remains the clean 37-item pass.

    VLM6-DELTA-07: boxed manifest variant — see _boxed_golden_manifest; the
    unboxed real golden refuses identification, which would leave
    wrong_name_rate stamped 0.0 and never reach this gate.
    """
    import copy

    from scripts.eval_harness.report import WRONG_NAME_RATE_FLOOR

    _golden, record = _real_golden_good_record()
    boxed_manifest, boxed_sha = _boxed_golden_manifest(tmp_path)
    record = copy.deepcopy(record)
    # Corrupt one identity only; captions stay Must-Right-clean.
    target = record["items"][0]
    names_on_item = [i["name"] for i in (target.get("identities") or [])]
    wrong = "Definitely Wrong Person"
    for n in json.loads(_GOLDEN_SEED.read_text()).get("roster") or []:
        if n not in names_on_item:
            wrong = n
            break
    if target.get("identities"):
        target["identities"][0] = {
            "name": wrong,
            "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
            "unpositioned": False,
        }
    else:
        target["identities"] = [
            {
                "name": wrong,
                "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
                "unpositioned": False,
            }
        ]
    record["provenance"] = {**record["provenance"], "manifest_sha256": boxed_sha}
    record_path = tmp_path / "run-one-wrong.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(boxed_manifest), "--run-record", str(record_path)])
    msg = str(excinfo.value)
    assert excinfo.value.code != 0
    assert "wrong-name floor" in msg.lower()
    assert "vacuity" not in msg.lower()
    assert "empty-rubric" not in msg.lower()
    assert "must-right failures" not in msg.lower()
    assert "truncation" not in msg.lower()
    report = json.loads(record_path.with_name("run-one-wrong-report.json").read_text())
    assert report["verdict"]["verdict"] == ScoreVerdict.FAIL.value
    assert report["verdict"]["wrong_name_rate_floor"] == WRONG_NAME_RATE_FLOOR
    live = report["faces"]["identification"]["wrong_names"]
    ignored = report["faces"]["identification"]["ignored_wrong_names"]
    assert len(live) + len(ignored) == 1
    assert any("wrong_name_rate" in r for r in report["verdict"]["reasons"])


def test_score_rounding_cannot_hide_one_wrong_name_scaled(tmp_path, monkeypatch):
    """F1-7 scaled fixture (explicit): 1 wrong / 20001 images rounds rate to 0.0.

    SYNTHETIC SCALED FIXTURE — 20001 real images do not exist in golden.json.
    Pre-fix gated on round(rate, 4) so 1/20001 → 0.0 and 0.0 > 0.0 was false
    (exit 0). Post-fix gates on wrong-name count when floor is 0.0 (TEST-15).

    VLM6-DELTA-07: each entry needs a named face_box for its present_identities
    name or identification is structurally refused (unboxed identity claims),
    which stamps wrong_names=None and never reaches this gate.
    """
    from scripts.eval_harness.report import WRONG_NAME_RATE_FLOOR
    from scripts.eval_harness.schema import SCHEMA, DocKind

    n = 20001
    roster = ["Alice Example", "Bob Builder"]
    entries = []
    items = []
    for i in range(n):
        name = roster[i % 2]
        other = roster[(i + 1) % 2]
        path = f"mock_images/scaled-{i:05d}.jpg"
        entries.append(
            {
                "path": path,
                "sha256": f"{i:064x}"[:64],
                "media_id": i + 1,
                "face_count": 1,
                "present_identities": [name],
                "context_pack": {},
                "base_caption": "",
                "must_right": [name],
                "easy_wrong": [other],
                "policy": {"recognition_enabled": True},
                "face_boxes": [{"x": 10.0, "y": 40.0, "w": 50.0, "h": 60.0, "name": name, "source": "iptc"}],
            }
        )
        # Exactly one wrong name on image 0; the rest are correct.
        pred = other if i == 0 else name
        items.append(
            {
                "media_id": i + 1,
                "path": path,
                "describe": {
                    "alt_text_draft": f"{name} outdoors smiling.",
                    "named_draft": f"{name} outdoors smiling.",
                    "generic_draft": f"{name} outdoors smiling.",
                    "visual_facts": {"objects": []},
                },
                "identities": [
                    {
                        "name": pred,
                        "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
                        "unpositioned": False,
                    }
                ],
                "face_count": 1,
                "error": None,
            }
        )
    manifest_path, manifest_sha = _write_score_manifest(tmp_path, entries, roster, name="scaled-20001.json")
    record = {
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
    record_path = tmp_path / "run-scaled-round.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)])
    msg = str(excinfo.value)
    assert excinfo.value.code != 0
    assert "wrong-name floor" in msg.lower()
    assert "vacuity" not in msg.lower()
    assert "empty-rubric" not in msg.lower()
    assert "truncation" not in msg.lower()
    report = json.loads(record_path.with_name("run-scaled-round-report.json").read_text())
    # Display rate rounds to 0.0 — that must NOT silence the gate (F1-7).
    assert report["verdict"]["wrong_name_rate"] == 0.0
    assert report["verdict"]["wrong_name_rate_floor"] == WRONG_NAME_RATE_FLOOR
    assert report["verdict"]["verdict"] == ScoreVerdict.FAIL.value
    live = report["faces"]["identification"]["wrong_names"]
    ignored = report["faces"]["identification"]["ignored_wrong_names"]
    assert len(live) + len(ignored) == 1
    assert any("wrong_names=1" in r for r in report["verdict"]["reasons"])


@pytest.mark.xfail(
    strict=True,
    reason=(
        "FIR-ORCH-BR-23: live reported golden has 0 empty-must_right images "
        "(the 3 carriers were media 27, 34, 35 on the 37-entry corpus and landed "
        "in train). Do not re-pin 3→0; F1-8 is proved on a scratch copy below."
    ),
)
def test_score_empty_rubric_keys_on_scored_set_not_manifest(tmp_path, monkeypatch):
    """F1-8: rubric defined count is over scored items, not the full manifest.

    Real golden has 34 must_right entries; scoring only the 3 non-must_right
    media_ids leaves the measured set vacuous. Pre-fix counted the manifest
    (defined=34) so empty-rubric stayed silent. Post-fix defined=0 and the
    empty-rubric class token appears in on-disk reasons (EVAL-19).

    Truncation also fires (media-id multiset incomplete vs full golden) — that
    is expected; F1-8 is proved by must_right_defined_images==0 + empty-rubric
    reason, not by exit-token order alone.
    """
    import copy

    golden, full_record = _real_golden_good_record()
    raw = json.loads(_GOLDEN_SEED.read_text())
    no_mr_ids = {e["media_id"] for e in raw["entries"] if not e.get("must_right")}
    assert len(no_mr_ids) == 3
    record = copy.deepcopy(full_record)
    record["items"] = [it for it in record["items"] if it["media_id"] in no_mr_ids]
    assert len(record["items"]) == 3
    record_path = tmp_path / "run-scored-no-mr.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(golden), "--run-record", str(record_path)])
    assert excinfo.value.code != 0
    report = json.loads(record_path.with_name("run-scored-no-mr-report.json").read_text())
    # Measured set has zero must_right (F1-8); easy_wrong still defined on the 3.
    assert report["caption"]["must_right_defined_images"] == 0
    assert report["caption"]["easy_wrong_defined_images"] == 3
    assert report["counts"]["scored"] == 3
    assert report["verdict"]["verdict"] == ScoreVerdict.FAIL.value
    reasons_blob = " | ".join(report["verdict"]["reasons"]).lower()
    assert "empty-rubric" in reasons_blob
    assert "must_right" in reasons_blob
    # Class token present; other non-applicable classes stay out of empty-rubric reason.
    empty_reasons = [r for r in report["verdict"]["reasons"] if "empty-rubric" in r.lower()]
    assert empty_reasons
    assert all("wrong-name floor vacuity" not in r for r in empty_reasons)
    assert all("schema error" not in r for r in empty_reasons)


def test_score_empty_rubric_keys_on_scored_set_scratch_manifest(tmp_path, monkeypatch):
    """F1-8 / TEST-15: scored-set vacuity on a scratch copy that still has must_right on unscored rows."""
    import copy

    from scripts.eval_harness.cli import _manifest_sha
    from scripts.eval_harness.manifest import load_manifest

    golden, full_record = _real_golden_good_record()
    raw = json.loads(Path(golden).read_text())
    assert len(raw["entries"]) >= 5
    scratch = copy.deepcopy(raw)
    scored_ids = []
    for entry in scratch["entries"][:3]:
        entry["must_right"] = []
        scored_ids.append(entry["media_id"])
    assert any(e.get("must_right") for e in scratch["entries"][3:]), (
        "scratch fixture must keep must_right on unscored rows so F1-8 is not tautological"
    )
    man_path = tmp_path / "golden-f18.json"
    man_path.write_text(json.dumps(scratch))
    manifest = load_manifest(
        str(man_path),
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only; image bytes never opened",
        metadata_only=True,
    )
    record = copy.deepcopy(full_record)
    record["provenance"] = {**record["provenance"], "manifest_sha256": _manifest_sha(manifest)}
    record["items"] = [it for it in record["items"] if it["media_id"] in set(scored_ids)]
    assert len(record["items"]) == 3
    record_path = tmp_path / "run-scored-no-mr.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(man_path), "--run-record", str(record_path)])
    assert excinfo.value.code != 0
    report = json.loads(record_path.with_name("run-scored-no-mr-report.json").read_text())
    assert report["caption"]["must_right_defined_images"] == 0
    assert report["counts"]["scored"] == 3
    assert report["verdict"]["verdict"] == ScoreVerdict.FAIL.value
    reasons_blob = " | ".join(report["verdict"]["reasons"]).lower()
    assert "empty-rubric" in reasons_blob
    assert "must_right" in reasons_blob


def test_score_f1d2_control_clean_real_golden_not_ready(tmp_path, monkeypatch):
    """F1d-2: clean real golden scores fully but is not_ready (π=0 categories).

    Controls that must_right denominators and scored count stay honest while
    the readiness verdict correctly refuses pass (VLM6-A-05 / OBS-04).
    """
    golden, record = _real_golden_good_record()
    record_path = tmp_path / "run-f1d2-control.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(golden), "--run-record", str(record_path)])
    assert excinfo.value.code != 0
    report = json.loads(record_path.with_name("run-f1d2-control-report.json").read_text())
    assert report["verdict"]["verdict"] == ScoreVerdict.NOT_READY.value
    assert report["verdict"]["reasons"]  # non-empty vacuity reasons
    expected_must_right = sum(1 for e in json.loads(Path(golden).read_text())["entries"] if e.get("must_right"))
    assert report["caption"]["must_right_defined_images"] == expected_must_right
    assert report["counts"]["scored"] == len(record["items"])


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

    def _lineage(name):
        return {
            "labeler_id": "test-labeler",
            "batch_id": "test-batch",
            "capture_session_id": "test-session",
            "pass_index": 0,
            "labeled_at": "2026-08-14T00:00:00Z",
            "tool_version": "test",
            "saw_machine_proposals": False,
            "label_source": "operator_blind",
            "decision": "named" if name else "stranger",
            "confidence": "high",
            "arbitration_of": None,
        }

    def _gt(name):
        return {
            "x": 0.4,
            "y": 0.4,
            "w": 0.4,
            "h": 0.4,
            "name": name,
            "source": "iptc",
            "lineage": _lineage(name),
        }

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
            {
                "media_id": 1,
                "path": "celebs01/alice-a.jpg",
                "model_id": "ort-yunet-sface",
                "embedding_dim": dim,
                "image_size": [100, 100],
                "faces": [_fd([20.0, 20.0, 40.0, 40.0], _unit([1.0] + [0.0] * (dim - 1)))],
            },
            {
                "media_id": 2,
                "path": "celebs01/alice-b.jpg",
                "model_id": "ort-yunet-sface",
                "embedding_dim": dim,
                "image_size": [100, 100],
                "faces": [_fd([20.0, 20.0, 40.0, 40.0], _unit([0.98, 0.1] + [0.0] * (dim - 2)))],
            },
            {
                "media_id": 3,
                "path": "localwp/uploads/stranger-party.jpg",
                "model_id": "ort-yunet-sface",
                "embedding_dim": dim,
                "image_size": [100, 100],
                "faces": [_fd([20.0, 20.0, 40.0, 40.0], _unit([0.0, 1.0] + [0.0] * (dim - 2)))],
            },
        ],
    }
    manifest = {
        "manifest_version": 3,
        "annotation_mode": "exhaustive",
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

    Transport (F2b): child writes an out-of-band payload dict, not stdout framing.
    """
    from scripts.eval_harness import cli as cli_mod

    record, manifest = _valid_face_manifest_and_record()
    rec_path = tmp_path / "face-run.json"
    rec_path.write_text(json.dumps(record))
    man_path = tmp_path / "man.json"
    man_path.write_text(json.dumps(manifest))

    from scripts.eval_harness.report import build_face_reports

    def _divergent_payload(*args, **kwargs):
        path = _det_payload_path_from_run_args(args, kwargs)
        # Matching provenance so we reach FAILED (byte mismatch), not ERROR.
        path.write_text(
            json.dumps(
                {
                    "json": "DIFFERENT-JSON",
                    "md": "DIFFERENT-MD",
                    "build_reports_file": build_face_reports.__code__.co_filename,
                }
            )
        )
        return _det_ok_proc()

    monkeypatch.setattr(cli_mod.subprocess, "run", _divergent_payload)
    with pytest.raises(SystemExit) as exc:
        cli_mod._check_face_determinism_cross_process(rec_path, str(man_path), public=False)
    msg = str(exc.value)
    assert "determinism check FAILED" in msg
    assert "[score-face]" in msg
    assert "document=" in msg


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
    import hashlib

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
        img_path = images / fname
        assert cv2.imwrite(str(img_path), img)
        # Real pin: face-bakeoff verifies hashes before reading pixels (VLM6-R2-05).
        digest = hashlib.sha256(img_path.read_bytes()).hexdigest()
        entries.append(
            {
                "path": f"celebs01/{fname}",
                "sha256": digest,
                "media_id": mid,
                "face_count": 1,
                "base_caption": "",
                "present_identities": [name],
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [
                    {
                        "x": 0.4,
                        "y": 0.4,
                        "w": 0.4,
                        "h": 0.4,
                        "name": name,
                        "source": "iptc",
                        "lineage": dict(_TEST_LINEAGE_NAMED),
                    }
                ],
                "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
            }
        )
    man_path = tmp_path / "man.json"
    man_path.write_text(
        json.dumps(
            {
                "manifest_version": 3,
                "annotation_mode": "exhaustive",
                "roster": ["Alice Q", "Bob Z"],
                "entries": entries,
            }
        )
    )

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
        not ({"occluded", "occlusion", "occlusion_kind", "twin", "twin_of"} & set(item)) for item in record["items"]
    )

    cli_mod.main(["score-face", "--manifest", str(man_path), "--run-record", str(record_path)])
    report = json.loads((tmp_path / "out" / f"{record_path.stem}-face-report.json").read_text())
    for tag in ("masked", "sunglasses", "occlusion_other"):
        synth = report["slices"]["occlusion"][tag]["synthetic"]
        # Pre-fix state was n_eligible=0 (no production caller): red if wiring drops.
        assert synth["n_eligible"] == 4, tag
        assert synth["n_eligible"] == synth["rate_denominator"]


# --- FIR-1 head-to-head: face-bakeoff --leg dispatch (candidate vs buffalo) ---


def test_face_bakeoff_passes_images_dir_not_skip(tmp_path, monkeypatch):
    """TEST-15 / VLM6-R2-05 discriminator: pixel path must pass images_dir=.

    face-bakeoff opens image bytes (walk_face_run_record / twin pass). If a
    future change blanket-applies skip_hash_verification=True here, this test
    goes red even when GOLDEN_IMAGES_DIR is set (env auto-verify would otherwise
    mask the skip). Captures kwargs at the load_manifest call site.
    """
    from scripts.eval_harness import cli as cli_mod
    from scripts.eval_harness.manifest import ManifestError

    man_path = tmp_path / "man.json"
    man_path.write_text(
        json.dumps(
            {
                "manifest_version": 3,
                "annotation_mode": "roster_only",
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
                        "provenance": {
                            "source": "celeb",
                            "license": "public_domain",
                            "publishable": True,
                        },
                    }
                ],
            }
        )
    )
    images = tmp_path / "images"
    images.mkdir()
    leg = _FusedFakeLeg()
    monkeypatch.setattr(cli_mod, "build_candidate_leg", lambda: (leg, _NoopAligner(), leg))
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(images))

    captured: list[dict] = []

    def _spy(path, images_dir=None, *, skip_hash_verification=False):
        captured.append(
            {
                "path": path,
                "images_dir": images_dir,
                "skip_hash_verification": skip_hash_verification,
            }
        )
        raise ManifestError("spy-stop: kwargs captured")

    monkeypatch.setattr(cli_mod, "load_manifest", _spy)

    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["face-bakeoff", "--manifest", str(man_path)])
    assert "spy-stop" in str(exc.value)
    assert captured, "load_manifest was never called"
    call = captured[0]
    assert call["images_dir"] == str(images), (
        f"pixel path must pass images_dir= (got {call!r}); skip_hash_verification alone re-opens VLM6-R2-05"
    )
    assert call["skip_hash_verification"] is False


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
    import hashlib

    import cv2
    import numpy as np

    images = tmp_path / "images" / "celebs01"
    images.mkdir(parents=True)
    img = np.random.default_rng(11).integers(0, 256, size=(64, 64, 3)).astype(np.uint8)
    img_path = images / "a.jpg"
    assert cv2.imwrite(str(img_path), img)
    # Real pin: face-bakeoff verifies hashes before reading pixels (VLM6-R2-05).
    digest = hashlib.sha256(img_path.read_bytes()).hexdigest()
    man_path = tmp_path / "man.json"
    man_path.write_text(
        json.dumps(
            {
                "manifest_version": 3,
                "annotation_mode": "roster_only",
                "roster": ["Alice Q"],
                "entries": [
                    {
                        "path": "celebs01/a.jpg",
                        "sha256": digest,
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
    monkeypatch.setattr(cli_mod, "build_candidate_leg", lambda: pytest.fail("candidate leg built for --leg buffalo"))
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
    monkeypatch.setattr(cli_mod, "_build_buffalo_leg", lambda: pytest.fail("buffalo leg built for --leg candidate"))
    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(tmp_path / "images"))

    cli_mod.main(["face-bakeoff", "--manifest", str(man_path), "--leg", "candidate"])
    record_path = next(p for p in (tmp_path / "out").glob("face-run-*.json") if "aborted" not in p.name)
    prov = json.loads(record_path.read_text())["provenance"]
    assert prov["leg"] == "candidate"
    assert prov["model_id"] == "ort-yunet-sface"
    assert "leg_mode" not in prov


# --- VLM6-lc2 residual gates (A-02, F2A-01, R2-08, B-10) ---


def test_score_aborted_record_exits_nonzero(tmp_path, monkeypatch):
    """VLM6-S2A-A-02: aborted partial record must not certify as pass."""
    roster, entries = _corpus_entries(2, with_rubric=True)
    manifest_path, manifest_sha = _write_score_manifest(tmp_path, entries, roster)
    record = _score_run_record(
        entries,
        caption_fn=lambda e: f"{e['present_identities'][0]} outdoors smiling.",
        identity_fn=lambda e: [_score_identity(e["present_identities"][0])],
        manifest_sha=manifest_sha,
        aborted=True,
    )
    record_path = tmp_path / "run-aborted.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)])
    assert excinfo.value.code != 0
    msg = str(excinfo.value).lower()
    assert "aborted-record" in msg
    report = json.loads(record_path.with_name("run-aborted-report.json").read_text(encoding="utf-8"))
    assert report["verdict"]["verdict"] == ScoreVerdict.FAIL.value
    assert any("aborted" in r.lower() for r in report["verdict"]["reasons"])


def test_score_zero_scored_exits_nonzero(tmp_path, monkeypatch):
    """VLM6-S2A-A-02: empty items (scored=0, failed=0) must not green-exit."""
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
            "must_right": ["Alice Example"],
            "easy_wrong": ["Bob Builder"],
            "policy": {"recognition_enabled": True},
        }
    ]
    manifest_path, manifest_sha = _write_score_manifest(tmp_path, entries, ["Alice Example", "Bob Builder"])
    # Empty items → scored=0, failed=0 (distinct from all-error failed-items).
    record = {
        "schema": SCHEMA,
        "kind": DocKind.RUN_RECORD.value,
        "provenance": {
            "manifest_sha256": manifest_sha,
            "base_url": "https://example.test",
            "head_sha": "f" * 40,
            "started_at": "t",
        },
        "items": [],
    }
    record_path = tmp_path / "run-empty.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)])
    assert excinfo.value.code != 0
    msg = str(excinfo.value).lower()
    assert "zero-scored" in msg
    assert "failed-items" not in msg
    report = json.loads(record_path.with_name("run-empty-report.json").read_text())
    assert report["counts"]["scored"] == 0
    assert report["verdict"]["verdict"] == ScoreVerdict.FAIL.value


def test_cli_determinism_guard_errors_on_child_timeout(tmp_path, monkeypatch):
    """VLM6-S2A-F2A-01: TimeoutExpired maps to ERROR class, not FAILED.

    Covers stderr-present and stderr-None shapes; asserts timeout= is passed.
    """
    from scripts.eval_harness import cli as cli_mod

    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)
    seen_timeouts: list[object] = []

    def _raise_timeout_with_stderr(*args, **kwargs):
        seen_timeouts.append(kwargs.get("timeout"))
        raise cli_mod.subprocess.TimeoutExpired(
            cmd=args[0] if args else kwargs.get("args"),
            timeout=kwargs.get("timeout") or 120,
            output=None,
            stderr="hung on cv2 import",
        )

    monkeypatch.setattr(cli_mod.subprocess, "run", _raise_timeout_with_stderr)
    with pytest.raises(SystemExit) as exc:
        cli_mod._check_score_determinism_cross_process(record_path, str(manifest_path))
    msg = str(exc.value)
    assert "determinism check ERROR [score]" in msg
    assert "timed out" in msg
    assert "determinism check FAILED" not in msg
    assert seen_timeouts
    assert all(t == cli_mod._DETERMINISM_CHILD_TIMEOUT_S for t in seen_timeouts)

    # stderr=None must not crash (TimeoutExpired.stderr can be None).
    def _raise_timeout_no_stderr(*args, **kwargs):
        raise cli_mod.subprocess.TimeoutExpired(
            cmd=args[0] if args else kwargs.get("args"),
            timeout=kwargs.get("timeout") or 120,
            output=None,
            stderr=None,
        )

    monkeypatch.setattr(cli_mod.subprocess, "run", _raise_timeout_no_stderr)
    with pytest.raises(SystemExit) as exc2:
        cli_mod._check_score_determinism_cross_process(record_path, str(manifest_path))
    msg2 = str(exc2.value)
    assert "determinism check ERROR [score]" in msg2
    assert "timed out" in msg2


def _adoption_compare_report(**overrides):
    """Full-fidelity caption score report fixture for adoption-gate compare tests.

    Non-vacuous on every adoption category; counts.scored != 37 so harness-anchor
    non-adoption does not fire. Callers override individual fields for polarity /
    vacuity / protocol mismatch cases (VLM6-E-01 / A-02 / A-03).
    """
    import copy

    base = {
        "schema": "acx-eval/v1",
        "kind": "report",
        "eval_mode": "standard",
        "provenance": {
            "score_manifest_sha256": "aa" * 32,
            "manifest_sha256": "aa" * 32,
            "manifest_matches_fetch": True,
            "prompt_variant": "v3_weave",
            "two_pass": True,
            "dual_length": False,
            "face_gate": True,
            "head_sha": "0" * 40,
        },
        "counts": {"total": 100, "scored": 100, "failed": 0},
        "corpus": {"manifest_entries": 100, "media_id_missing": 0, "media_id_extra": 0},
        "caption": {
            "insertion_rate": 0.10,
            "mean_gated_score": 0.50,
            "must_right_failed_images": 0,
            "must_right_defined_images": 90,
            "easy_wrong_defined_images": 80,
        },
        "hallucination": {
            "fabricated_fact_rate": 0.05,
            "fabricated_fact_rate_trapped": 0.10,
            "images_with_traps": 20,
            "trap_instances": 20,
            "fabricated_instances": 1,
        },
        "placement": {
            "accuracy": 0.85,
            "claims": 40,
            "correct": 34,
            "wrong": 6,
            "abstained": 0,
            "images_scored": 100,
        },
        "faces": {
            "detection": {"precision": 0.90, "recall": 0.88, "tp": 80, "fp": 9, "fn": 11},
            "identification": {
                "precision": 0.92,
                "recall": 0.91,
                "evaluated_images": 90,
                "wrong_names": [],
                "ignored_wrong_names": [],
                "positional": {
                    "position_accuracy": 0.80,
                    "exact_order_rate": 0.70,
                    "compared_images": 50,
                    "position_total": 100,
                    "position_hits": 80,
                    "excluded_images": [],
                },
            },
            "identity_ordering": {
                "positional_images": 50,
                "degraded_images": 0,
                "degraded_paths": [],
            },
        },
        "verdict": {
            # RV1-05 / sr-007: fixture verdicts from the enum — never raw literals
            # that can forge a status the enum would reject.
            "verdict": ScoreVerdict.PASS.value,
            "wrong_name_rate": 0.0,
            "rubric_gate": "enforce",
            "reasons": [],
        },
    }

    def _merge(dst, src):
        for key, value in src.items():
            if isinstance(value, dict) and isinstance(dst.get(key), dict):
                _merge(dst[key], value)
            else:
                dst[key] = value

    out = copy.deepcopy(base)
    _merge(out, overrides)
    return out


def test_cli_compare_insertion_rate_lower_is_better(tmp_path, capsys):
    """VLM6-E-01 / TEST-15: insertion_rate polarity is lower-is-better.

    inserted / (inserted + missing) measures hallucinated identities; a candidate
    that inserts *more* wrong names must FAIL meet-or-beat (not PASS).
    """
    baseline = _adoption_compare_report(caption={"insertion_rate": 0.10})
    # Higher insertion_rate = more hallucinations = regression (must go red).
    worse = _adoption_compare_report(caption={"insertion_rate": 0.50})
    # Lower insertion_rate = fewer hallucinations = meet-or-beat.
    better = _adoption_compare_report(caption={"insertion_rate": 0.05})
    base_path = tmp_path / "baseline.json"
    worse_path = tmp_path / "worse.json"
    better_path = tmp_path / "better.json"
    base_path.write_text(json.dumps(baseline))
    worse_path.write_text(json.dumps(worse))
    better_path.write_text(json.dumps(better))

    with pytest.raises(SystemExit) as exc:
        main(["compare", "--baseline", str(base_path), "--candidate", str(worse_path)])
    assert exc.value.code != 0
    assert "insertion_rate" in str(exc.value)
    assert "compare regression gate" in str(exc.value) or "compare" in str(exc.value).lower()

    assert main(["compare", "--baseline", str(base_path), "--candidate", str(better_path)]) is None
    out = capsys.readouterr().out
    assert "insertion_rate" in out
    assert "lower-better" in out


def test_cli_compare_rejects_handwritten_four_field_json(tmp_path):
    """VLM6-A-02 / F-02: bare four-metric JSON is not a same-corpus score report."""
    bare = {
        "caption": {
            "insertion_rate": 0.0,
            "mean_gated_score": 1.0,
            "must_right_failed_images": 0,
        },
        "verdict": {"wrong_name_rate": 0.0},
    }
    full = _adoption_compare_report()
    bare_path = tmp_path / "bare.json"
    full_path = tmp_path / "full.json"
    bare_path.write_text(json.dumps(bare))
    full_path.write_text(json.dumps(full))

    with pytest.raises(SystemExit) as exc:
        main(["compare", "--baseline", str(bare_path), "--candidate", str(full_path)])
    assert exc.value.code != 0
    msg = str(exc.value).lower()
    assert "compare" in msg
    assert any(tok in msg for tok in ("schema", "kind", "same-corpus", "not a caption", "protocol"))


def test_cli_compare_rejects_pass_ungated_baseline(tmp_path):
    """VLM6-A-02: baseline whose own verdict is not adoption-eligible pass is refused."""
    # Match protocol (rubric_gate) so the adoption-eligible verdict check is reached.
    baseline = _adoption_compare_report(verdict={"verdict": ScoreVerdict.PASS_UNGATED.value, "rubric_gate": "enforce"})
    candidate = _adoption_compare_report(verdict={"verdict": ScoreVerdict.PASS.value, "rubric_gate": "enforce"})
    base_path = tmp_path / "baseline.json"
    cand_path = tmp_path / "candidate.json"
    base_path.write_text(json.dumps(baseline))
    cand_path.write_text(json.dumps(candidate))

    with pytest.raises(SystemExit) as exc:
        main(["compare", "--baseline", str(base_path), "--candidate", str(cand_path)])
    assert exc.value.code != 0
    assert "pass_ungated" in str(exc.value) or "adoption" in str(exc.value).lower()


def test_cli_compare_rejects_manifest_digest_mismatch(tmp_path):
    """VLM6-A-02 / EVAL-13: different score_manifest_sha256 is not same-corpus."""
    baseline = _adoption_compare_report()
    candidate = _adoption_compare_report(provenance={"score_manifest_sha256": "bb" * 32})
    base_path = tmp_path / "baseline.json"
    cand_path = tmp_path / "candidate.json"
    base_path.write_text(json.dumps(baseline))
    cand_path.write_text(json.dumps(candidate))

    with pytest.raises(SystemExit) as exc:
        main(["compare", "--baseline", str(base_path), "--candidate", str(cand_path)])
    assert exc.value.code != 0
    assert "score_manifest_sha256" in str(exc.value) or "manifest" in str(exc.value).lower()


def test_cli_compare_vacuous_category_blocks_adoption(tmp_path):
    """VLM6-A-03 / EVAL-23: None/vacuous adoption categories block PASS (fail closed)."""
    baseline = _adoption_compare_report()
    # Placement accuracy None with claims=0 is the 37-item harness shape.
    candidate = _adoption_compare_report(
        placement={"accuracy": None, "claims": 0, "correct": 0, "wrong": 0, "abstained": 0, "images_scored": 100}
    )
    base_path = tmp_path / "baseline.json"
    cand_path = tmp_path / "candidate.json"
    base_path.write_text(json.dumps(baseline))
    cand_path.write_text(json.dumps(candidate))

    with pytest.raises(SystemExit) as exc:
        main(["compare", "--baseline", str(base_path), "--candidate", str(cand_path)])
    assert exc.value.code != 0
    msg = str(exc.value).lower()
    assert "placement" in msg or "vacuous" in msg or "non_observable" in msg or "not_adoption" in msg


def test_cli_compare_harness_37_refuses_adoption_pass(tmp_path):
    """VLM6-A-03 / EVAL-04: 37-item harness corpus cannot emit adoption PASS."""
    # Even with non-None numbers, n=37 is the golden.json harness anchor — not Golden-100.
    baseline = _adoption_compare_report(
        counts={"total": 37, "scored": 37, "failed": 0},
        corpus={"manifest_entries": 37, "media_id_missing": 0, "media_id_extra": 0},
    )
    candidate = _adoption_compare_report(
        counts={"total": 37, "scored": 37, "failed": 0},
        corpus={"manifest_entries": 37, "media_id_missing": 0, "media_id_extra": 0},
        caption={"insertion_rate": 0.05, "mean_gated_score": 0.6, "must_right_failed_images": 0},
    )
    base_path = tmp_path / "baseline.json"
    cand_path = tmp_path / "candidate.json"
    base_path.write_text(json.dumps(baseline))
    cand_path.write_text(json.dumps(candidate))

    with pytest.raises(SystemExit) as exc:
        main(["compare", "--baseline", str(base_path), "--candidate", str(cand_path)])
    assert exc.value.code != 0
    msg = str(exc.value).lower()
    assert "37" in msg or "harness" in msg or "golden-100" in msg or "not_adoption" in msg or "adoption" in msg


def test_cli_compare_meet_or_beat_all_categories_pass(tmp_path, capsys):
    """VLM6-A-03: meet-or-beat across the full adoption metric set exits 0."""
    baseline = _adoption_compare_report()
    candidate = _adoption_compare_report(
        caption={"insertion_rate": 0.05, "mean_gated_score": 0.60, "must_right_failed_images": 0},
        faces={
            "detection": {"precision": 0.95, "recall": 0.90},
            "identification": {
                "precision": 0.95,
                "recall": 0.93,
                "positional": {"position_accuracy": 0.85, "exact_order_rate": 0.75},
            },
        },
        placement={"accuracy": 0.90},
        hallucination={"fabricated_fact_rate": 0.02, "fabricated_fact_rate_trapped": 0.05},
    )
    base_path = tmp_path / "baseline.json"
    cand_path = tmp_path / "candidate.json"
    base_path.write_text(json.dumps(baseline))
    cand_path.write_text(json.dumps(candidate))

    assert main(["compare", "--baseline", str(base_path), "--candidate", str(cand_path)]) is None
    out = capsys.readouterr().out
    assert "compare meet-or-beat: PASS" in out or "PASS" in out
    # Adoption categories must appear in the comparison surface.
    for token in (
        "insertion_rate",
        "mean_gated_score",
        "detection.precision",
        "identification.precision",
        "position_accuracy",
        "placement.accuracy",
        "fabricated_fact_rate",
    ):
        assert token in out, f"missing adoption metric surface: {token}"


def test_cmd_run_scores_all_records_despite_gate_failure(tmp_path, monkeypatch, capsys):
    """VLM6-S2A-B-10: run scores every record; exits once with per-record summary.

    RF-05 / rg-006: per-record stderr and final SystemExit must use registered
    fixed prefixes (path after the colon) so log scrapers can match without
    knowing the record path.
    """
    from argparse import Namespace

    from scripts.eval_harness import cli as cli_mod
    from scripts.eval_harness.cli import (
        SCORE_GATE_PREFIX_RUN_RECORD,
        SCORE_GATE_PREFIX_RUN_SUMMARY,
    )

    scored: list[str] = []

    def fake_fetch(args):
        return ["r0.json", "r1.json", "r2.json"]

    def fake_score(args):
        scored.append(args.run_record)
        if args.run_record == "r1.json":
            raise cli_mod.ScoreGateError("score must-right failures gate: synthetic")

    monkeypatch.setattr(cli_mod, "_cmd_fetch", fake_fetch)
    monkeypatch.setattr(cli_mod, "_cmd_score", fake_score)
    args = Namespace(check_determinism=False, provider=None, audience="local")
    with pytest.raises(SystemExit) as exc:
        cli_mod._cmd_run(args)
    assert scored == ["r0.json", "r1.json", "r2.json"]
    msg = str(exc.value)
    assert msg.startswith(SCORE_GATE_PREFIX_RUN_SUMMARY), (
        f"run multi-record exit must start with {SCORE_GATE_PREFIX_RUN_SUMMARY!r}; got {msg!r}"
    )
    assert "r1.json" in msg
    assert "must-right" in msg
    err = capsys.readouterr().err
    assert SCORE_GATE_PREFIX_RUN_RECORD in err, (
        f"run per-record stderr must carry {SCORE_GATE_PREFIX_RUN_RECORD!r}; got {err!r}"
    )
    # Path is after the fixed prefix (not interpolated into it).
    assert f"{SCORE_GATE_PREFIX_RUN_RECORD} r1.json:" in err
    assert "score gate failed for " not in err


# ---------------------------------------------------------------------------
# VLM-6 fx1 lane: score write-path + score-face + serialize (VLM6-F-03..A-08)
# ---------------------------------------------------------------------------


def test_cmd_score_manifest_drift_fails_closed(tmp_path, monkeypatch):
    """VLM6-F-03 / EVAL-13 / TEST-15: manifest_matches_fetch=False fails the score gate.

    Pre-fix only printed a WARNING and could exit 0 with verdict=pass; drifted
    numbers then fed compare. After fix: SystemExit with a class-unique token.
    """
    from scripts.eval_harness import cli as cli_mod
    from scripts.eval_harness.report import ScoreVerdict

    manifest_path, record_path = _w1_audience_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)

    real_score = cli_mod.score_run_record

    def _drifted(*args, **kwargs):
        scored = real_score(*args, **kwargs)
        prov = dict(scored.get("provenance") or {})
        prov["manifest_matches_fetch"] = False
        prov["score_manifest_sha256"] = "dd" * 32
        scored["provenance"] = prov
        return scored

    monkeypatch.setattr(cli_mod, "score_run_record", _drifted)

    with pytest.raises(SystemExit) as exc:
        main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)])
    assert exc.value.code != 0
    msg = str(exc.value).lower()
    assert "manifest" in msg
    assert "drift" in msg or "mismatch" in msg or "matches_fetch" in msg
    report = json.loads((tmp_path / "run-x-report.json").read_text())
    # On the hard-fail path the written verdict must not remain a certifiable pass.
    assert report["verdict"]["verdict"] != ScoreVerdict.PASS.value or "manifest" in str(exc.value).lower()


def test_cmd_score_allow_manifest_relabel_marks_non_comparable(tmp_path, monkeypatch):
    """VLM6-F-03: archival relabel opt-in persists non_comparable; compare rejects it."""
    from scripts.eval_harness import cli as cli_mod

    manifest_path, record_path = _w1_audience_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)

    real_score = cli_mod.score_run_record

    def _drifted(*args, **kwargs):
        scored = real_score(*args, **kwargs)
        prov = dict(scored.get("provenance") or {})
        prov["manifest_matches_fetch"] = False
        prov["score_manifest_sha256"] = "ee" * 32
        scored["provenance"] = prov
        return scored

    monkeypatch.setattr(cli_mod, "score_run_record", _drifted)

    # Opt-in archival path skips the hard drift gate, writes non_comparable, then
    # still exits non-zero so operators cannot mistake it for adoption-ready output.
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "score",
                "--manifest",
                str(manifest_path),
                "--run-record",
                str(record_path),
                "--allow-manifest-relabel",
            ]
        )
    assert exc.value.code != 0
    assert "non_comparable" in str(exc.value) or "manifest-relabel" in str(exc.value)
    report = json.loads((tmp_path / "run-x-report.json").read_text())
    assert report["verdict"]["verdict"] == ScoreVerdict.NON_COMPARABLE.value
    assert report["provenance"].get("manifest_matches_fetch") is False


def test_cmd_score_does_not_clobber_committed_freeze_reports(tmp_path, monkeypatch):
    """VLM6-E-05 / rg-002 / TEST-15: committed freeze reports are not clobbered.

    Pre-fix: score always wrote ``{run-record-stem}-report.json`` beside the
    record, so scoring the freeze run-record rewrote the committed report.
    After fix: run-records under ``docs/tasks/vlm/bakeoff-results`` write reports
    to OUT_DIR (or refuse overwrite), leaving the freeze sentinel intact.
    """
    from scripts.eval_harness import cli as cli_mod

    freeze_dir = tmp_path / "docs" / "tasks" / "vlm" / "bakeoff-results"
    freeze_dir.mkdir(parents=True)
    manifest_path, record_path = _w1_audience_manifest_and_record(freeze_dir)
    # Rename to freeze-shaped stem so sibling freeze reports match the layout.
    freeze_record = freeze_dir / "S2A-determinism-anchor-run-20260811.json"
    freeze_record.write_text(record_path.read_text())
    record_path.unlink()
    freeze_json = freeze_dir / "S2A-determinism-anchor-run-20260811-report.json"
    freeze_md = freeze_dir / "S2A-determinism-anchor-run-20260811-report.md"
    sentinel = '{"schema":"acx-eval/v1","kind":"report","freeze":"DO_NOT_CLOBBER"}\n'
    freeze_json.write_text(sentinel)
    freeze_md.write_text("# freeze sentinel\n")

    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    monkeypatch.chdir(tmp_path)
    # May exit non-zero on quality gates; freeze must still be untouched.
    try:
        main(["score", "--manifest", str(manifest_path), "--run-record", str(freeze_record)])
    except SystemExit:
        pass
    assert freeze_json.read_text() == sentinel, "committed freeze report must not be clobbered"
    assert freeze_md.read_text() == "# freeze sentinel\n"
    # Primary write target is OUT_DIR, not the freeze tree.
    out_report = tmp_path / "out" / "S2A-determinism-anchor-run-20260811-report.json"
    assert out_report.exists(), "score must redirect freeze-tree writes to OUT_DIR"


def test_cmd_score_public_carries_local_folded_verdict(tmp_path, monkeypatch):
    """VLM6-A-04 / TEST-15: PUBLIC artifact cannot say pass when LOCAL says fail.

    Schema/evidence folds used to apply only to LOCAL; PUBLIC was re-built without
    the fold and could disagree. After fix both audiences share the folded verdict.
    """
    from scripts.eval_harness import cli as cli_mod
    from scripts.eval_harness.report import ScoreVerdict

    manifest_path, record_path = _w1_audience_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)

    real_score = cli_mod.score_run_record

    def _zero_scored(*args, **kwargs):
        scored = real_score(*args, **kwargs)
        # Force the evidence fold path: scored=0 triggers fail verdict on LOCAL.
        scored["counts"] = {
            "total": int(scored["counts"]["total"]),
            "scored": 0,
            "failed": int(scored["counts"]["total"]),
        }
        return scored

    monkeypatch.setattr(cli_mod, "score_run_record", _zero_scored)

    with pytest.raises(SystemExit) as exc:
        main(
            [
                "score",
                "--manifest",
                str(manifest_path),
                "--run-record",
                str(record_path),
                "--audience",
                "public",
            ]
        )
    assert exc.value.code != 0
    local = json.loads((tmp_path / "run-x-report.json").read_text())
    public = json.loads((tmp_path / "run-x-report.public.json").read_text())
    assert local["verdict"]["verdict"] == ScoreVerdict.FAIL.value
    assert public["verdict"]["verdict"] == local["verdict"]["verdict"]
    assert public["verdict"]["verdict"] != ScoreVerdict.PASS.value


def test_cmd_score_face_public_uses_audience_suffix(tmp_path):
    """VLM6-A-06 / TEST-15: --public must not clobber the unsuffixed LOCAL face report."""
    record, manifest = _valid_face_manifest_and_record()
    rec_path = tmp_path / "face-run.json"
    rec_path.write_text(json.dumps(record))
    man_path = tmp_path / "man.json"
    man_path.write_text(json.dumps(manifest))

    # LOCAL write first.
    main(["score-face", "--run-record", str(rec_path), "--manifest", str(man_path)])
    local_path = tmp_path / "face-run-face-report.json"
    assert local_path.exists()
    local_bytes = local_path.read_text()
    local_bytes_before = local_bytes

    # PUBLIC must land on a distinct suffix path.
    main(["score-face", "--run-record", str(rec_path), "--manifest", str(man_path), "--public"])
    public_path = tmp_path / "face-run-face-report.public.json"
    assert public_path.exists(), "public face report must use .public suffix"
    assert local_path.read_text() == local_bytes_before, "LOCAL face report must not be clobbered by --public"


def test_cmd_score_face_gates_on_written_document(tmp_path, monkeypatch):
    """VLM6-A-07 / TEST-15: face gate must read back the written artifact.

    Pre-fix re-derived via score_face_run_record after write, so a serialisation
    bug in the written document could not go red. After fix: gate uses read-back.
    """
    from scripts.eval_harness import cli as cli_mod

    record, manifest = _valid_face_manifest_and_record()
    rec_path = tmp_path / "face-run.json"
    rec_path.write_text(json.dumps(record))
    man_path = tmp_path / "man.json"
    man_path.write_text(json.dumps(manifest))

    real_face_once = cli_mod._face_score_once

    def _corrupt_write(record_arg, manifest_arg, **kwargs):
        json_doc, md_doc = real_face_once(record_arg, manifest_arg, **kwargs)
        # Corrupt the serialised counts so a gate that re-derives from the record
        # would still see scored>0, but a gate that reads the written doc goes red.
        corrupted = json.loads(json_doc)
        corrupted["counts"] = {"scored": 0, "total": corrupted.get("counts", {}).get("total", 0), "failed": 0}
        return json.dumps(corrupted, indent=2, sort_keys=True) + "\n", md_doc

    monkeypatch.setattr(cli_mod, "_face_score_once", _corrupt_write)

    with pytest.raises(SystemExit) as exc:
        main(["score-face", "--run-record", str(rec_path), "--manifest", str(man_path)])
    assert exc.value.code != 0
    assert "zero-scored" in str(exc.value) or "scored=0" in str(exc.value)


def test_serialize_score_docs_propagates_renderer_errors(monkeypatch):
    """VLM6-A-08 / sr-006 / TEST-15: renderer KeyError must not become a green stub."""
    from scripts.eval_harness import cli as cli_mod

    def _boom(_scored):
        raise KeyError("verdict")

    monkeypatch.setattr(cli_mod, "_score_report_markdown", _boom)
    with pytest.raises(KeyError, match="verdict"):
        cli_mod._serialize_score_docs(
            {
                "schema": "acx-eval/v1",
                "kind": "report",
                "caption": {"insertion_rate": 0.0},
                "counts": {"scored": 1, "total": 1, "failed": 0},
                "faces": {"identification": {"wrong_names": []}},
                "verdict": {"verdict": ScoreVerdict.PASS.value},
            }
        )


# --- fx8: freeze-certification separates byte-stability from adoption exit ---
#
# make eval-anchor-check must exit 0 when freezes match byte-for-byte, even when
# the freeze is a deliberately imperfect non-evidential fixture (wrong names +
# vacuous categories). Adoption gates stay hard for live score runs (sr-001).


def test_score_freeze_certification_requires_expect_report(tmp_path, monkeypatch):
    """TEST-15 / EVAL-13: --freeze-certification cannot skip gating alone."""
    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "score",
                "--manifest",
                str(manifest_path),
                "--run-record",
                str(record_path),
                "--check-determinism",
                "--freeze-certification",
            ]
        )
    msg = str(exc.value)
    assert "--freeze-certification requires --expect-report" in msg
    # Flag alone (no --check-determinism either) is still rejected the same way.
    with pytest.raises(SystemExit) as exc2:
        main(
            [
                "score",
                "--manifest",
                str(manifest_path),
                "--run-record",
                str(record_path),
                "--freeze-certification",
            ]
        )
    assert "--freeze-certification requires --expect-report" in str(exc2.value)


def test_score_freeze_certification_exits_zero_when_bytes_match_despite_wrong_names(tmp_path, monkeypatch, capsys):
    """TEST-15: freeze-certification exit = byte-stability only (adoption visible).

    Fixture has a wrong-name floor breach so live score exits non-zero. After a
    freeze is captured, --freeze-certification must exit 0 while still printing
    the adoption verdict so operators cannot misread it as model certification.
    """
    manifest_path, record_path = _w1_audience_manifest_and_record(tmp_path, inject_wrong_name=True)
    monkeypatch.chdir(tmp_path)

    # Capture a freeze of the imperfect fixture (adoption gates fire).
    with pytest.raises(SystemExit) as live:
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
    assert live.value.code != 0
    assert "wrong-name" in str(live.value).lower()
    written = tmp_path / "run-x-report.json"
    assert written.is_file()
    expect = tmp_path / "freeze-expect.json"
    expect.write_text(written.read_text(encoding="utf-8"), encoding="utf-8")
    capsys.readouterr()  # clear capture buffer

    # Byte-stable re-score of the same imperfect freeze must exit 0.
    rc = main(
        [
            "score",
            "--manifest",
            str(manifest_path),
            "--run-record",
            str(record_path),
            "--check-determinism",
            "--expect-report",
            str(expect),
            "--freeze-certification",
        ]
    )
    assert rc is None  # main returns None on success (no SystemExit)
    out = capsys.readouterr().out
    assert "determinism check passed" in out
    assert "matches --expect-report" in out
    # Adoption outcomes remain visible (not hidden).
    assert "verdict=fail" in out
    assert "wrong_name_rate=" in out
    # Explicit non-adoption certification language (VLM6-E-08).
    assert "freeze-certification" in out.lower()
    assert "byte-stable" in out.lower() or "bit-identical" in out.lower()
    assert "not" in out.lower() and ("adoption" in out.lower() or "model quality" in out.lower())


def test_score_freeze_certification_exits_nonzero_on_anchor_mismatch(tmp_path, monkeypatch):
    """TEST-15: freeze-certification still goes red on byte mismatch."""
    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)

    # Produce a correct freeze first.
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
    written = tmp_path / "run-det-report.json"
    expect = tmp_path / "freeze-expect-bad.json"
    # Perturb one byte of the committed-shape freeze (tmp copy only).
    body = written.read_text(encoding="utf-8")
    # Flip a stable numeric field that cannot accidentally re-match.
    if '"insertion_rate": 0.0' in body:
        tampered = body.replace('"insertion_rate": 0.0', '"insertion_rate": 0.1', 1)
    else:
        tampered = body[:-2] + "X\n"  # last-resort single-byte corruption
    assert tampered != body
    expect.write_text(tampered, encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main(
            [
                "score",
                "--manifest",
                str(manifest_path),
                "--run-record",
                str(record_path),
                "--check-determinism",
                "--expect-report",
                str(expect),
                "--freeze-certification",
            ]
        )
    msg = str(exc.value)
    assert "determinism check ANCHOR_MISMATCH" in msg
    assert "matches --expect-report" not in msg or "does not match" in msg


def test_score_live_wrong_name_still_exits_nonzero_without_freeze_certification(tmp_path, monkeypatch):
    """TEST-15 / sr-001: live score (no freeze-cert) keeps adoption gates hard.

    Regression guard: freeze-certification must not soft-open the wrong-name floor
    for ordinary score runs.
    """
    manifest_path, record_path = _w1_audience_manifest_and_record(tmp_path, inject_wrong_name=True)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "score",
                "--manifest",
                str(manifest_path),
                "--run-record",
                str(record_path),
            ]
        )
    assert exc.value.code != 0
    assert "wrong-name" in str(exc.value).lower()


def test_score_face_freeze_certification_requires_expect_report(tmp_path):
    """score-face: --freeze-certification without --expect-report is rejected."""
    record, manifest = _valid_face_manifest_and_record()
    rec_path = tmp_path / "face-run.json"
    rec_path.write_text(json.dumps(record))
    man_path = tmp_path / "man.json"
    man_path.write_text(json.dumps(manifest))
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "score-face",
                "--run-record",
                str(rec_path),
                "--manifest",
                str(man_path),
                "--check-determinism",
                "--freeze-certification",
            ]
        )
    assert "--freeze-certification requires --expect-report" in str(exc.value)


# --- gx1: freeze-certification must NOT skip measurement-integrity gates ---
#
# fx8 placed the freeze-cert return above integrity gates. A corrupt record's
# expect-file can self-match (anchor generators capture certified build_reports
# bytes with no post-hoc fold), so integrity failures greened under the flag.
# Integrity still exit-determining; only adoption quality is soft (TEST-15).


def _certified_caption_expect(manifest_path, record_path, expect_path, *, rubric_gate="enforce"):
    """Write certified build_reports JSON as --expect-report (anchor-generator shape).

    Mirrors generate_determinism_anchor: capture pre-fold certified bytes so a
    corrupt record can self-match the expect path. Integrity gates must still
    fire under --freeze-certification when those bytes are byte-stable.
    """
    from scripts.eval_harness.cli import _load_ignore_list, _manifest_sha
    from scripts.eval_harness.manifest import load_manifest
    from scripts.eval_harness.report import Audience, build_reports

    record = json.loads(Path(record_path).read_text(encoding="utf-8"))
    manifest = load_manifest(
        str(manifest_path),
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only; image bytes never opened",
        metadata_only=True,
    )
    # VLM6-DELTA-06: mirror _cmd_score's stamp-fill (S2R6E-04) so this
    # "certified expect" is built from the same entries the cross-process
    # determinism guard now produces (cli.py _cmd_score /
    # _check_score_determinism_cross_process) — otherwise a missing
    # per-entry annotation_mode stamp here vs. a filled one there is a
    # spurious ANCHOR_MISMATCH that masks the actual integrity gate under
    # test (aborted-record / zero-scored / truncation / manifest-mismatch).
    entries = []
    for e in manifest.entries:
        row = e.model_dump()
        if row.get("annotation_mode") is None:
            row["annotation_mode"] = manifest.annotation_mode
        entries.append(row)
    json_doc, _md = build_reports(
        record,
        entries,
        ignore_list=_load_ignore_list(Path(record_path).parent),
        score_manifest_sha256=_manifest_sha(manifest),
        manifest_roster=sorted(set(getattr(manifest, "roster", []) or [])),
        audience=Audience.LOCAL,
        rubric_gate=rubric_gate,
    )
    Path(expect_path).write_text(json_doc, encoding="utf-8")
    return json_doc


def _freeze_cert_score_argv(manifest_path, record_path, expect_path, *extra):
    return [
        "score",
        "--manifest",
        str(manifest_path),
        "--run-record",
        str(record_path),
        "--check-determinism",
        "--expect-report",
        str(expect_path),
        "--freeze-certification",
        *extra,
    ]


def test_score_freeze_certification_aborted_exits_nonzero(tmp_path, monkeypatch):
    """TEST-15 / S1-01: aborted-record integrity still fires under freeze-cert."""
    roster, entries = _corpus_entries(2, with_rubric=True)
    manifest_path, manifest_sha = _write_score_manifest(tmp_path, entries, roster)
    record = _score_run_record(
        entries,
        caption_fn=lambda e: f"{e['present_identities'][0]} in the foreground outdoors.",
        identity_fn=lambda e: [_score_identity(e["present_identities"][0])],
        manifest_sha=manifest_sha,
        aborted=True,
    )
    record_path = tmp_path / "run-abort-fc.json"
    record_path.write_text(json.dumps(record))
    expect = tmp_path / "abort-expect.json"
    _certified_caption_expect(manifest_path, record_path, expect)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc:
        main(_freeze_cert_score_argv(manifest_path, record_path, expect))
    assert exc.value.code != 0
    assert "aborted-record" in str(exc.value).lower()
    # Not a soft byte-stability green-exit.
    assert "freeze-certification passed" not in str(exc.value).lower()


def test_score_freeze_certification_zero_scored_exits_nonzero(tmp_path, monkeypatch):
    """TEST-15 / S1-01: zero-scored integrity still fires under freeze-cert."""
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
            "must_right": ["Alice Example"],
            "easy_wrong": ["Bob Builder"],
            "policy": {"recognition_enabled": True},
        }
    ]
    manifest_path, manifest_sha = _write_score_manifest(tmp_path, entries, ["Alice Example", "Bob Builder"])
    record = {
        "schema": SCHEMA,
        "kind": DocKind.RUN_RECORD.value,
        "provenance": {
            "manifest_sha256": manifest_sha,
            "base_url": "https://example.test",
            "head_sha": "f" * 40,
            "started_at": "t",
        },
        "items": [],
    }
    record_path = tmp_path / "run-zero-fc.json"
    record_path.write_text(json.dumps(record))
    expect = tmp_path / "zero-expect.json"
    _certified_caption_expect(manifest_path, record_path, expect)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc:
        main(_freeze_cert_score_argv(manifest_path, record_path, expect))
    assert exc.value.code != 0
    assert "zero-scored" in str(exc.value).lower()


def test_score_freeze_certification_truncated_exits_nonzero(tmp_path, monkeypatch):
    """TEST-15 / S1-01: truncation integrity still fires under freeze-cert."""
    roster, entries = _corpus_entries(2, with_rubric=True)
    manifest_path, manifest_sha = _write_score_manifest(tmp_path, entries, roster)
    # Only first of two media-ids present → truncation gate.
    record = _score_run_record(
        entries[:1],
        caption_fn=lambda e: f"{e['present_identities'][0]} in the foreground outdoors.",
        identity_fn=lambda e: [_score_identity(e["present_identities"][0])],
        manifest_sha=manifest_sha,
    )
    record_path = tmp_path / "run-trunc-fc.json"
    record_path.write_text(json.dumps(record))
    expect = tmp_path / "trunc-expect.json"
    _certified_caption_expect(manifest_path, record_path, expect)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc:
        main(_freeze_cert_score_argv(manifest_path, record_path, expect))
    assert exc.value.code != 0
    assert "truncation" in str(exc.value).lower()


def test_score_freeze_certification_manifest_mismatch_exits_nonzero(tmp_path, monkeypatch):
    """TEST-15 / S1-01: missing fetch-time sha integrity still fires under freeze-cert."""
    roster, entries = _corpus_entries(1, with_rubric=True)
    manifest_path, _manifest_sha = _write_score_manifest(tmp_path, entries, roster)
    record = _score_run_record(
        entries,
        caption_fn=lambda e: f"{e['present_identities'][0]} in the foreground outdoors.",
        identity_fn=lambda e: [_score_identity(e["present_identities"][0])],
        manifest_sha="f" * 64,  # any non-empty; then drop the key
    )
    del record["provenance"]["manifest_sha256"]
    record_path = tmp_path / "run-nosha-fc.json"
    record_path.write_text(json.dumps(record))
    expect = tmp_path / "nosha-expect.json"
    _certified_caption_expect(manifest_path, record_path, expect)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc:
        main(_freeze_cert_score_argv(manifest_path, record_path, expect))
    assert exc.value.code != 0
    assert "manifest-mismatch" in str(exc.value).lower()


def test_score_freeze_certification_schema_invalid_exits_nonzero(tmp_path, monkeypatch):
    """TEST-15 / S1-02: schema_exit must not be discarded under freeze-cert (rg-005).

    Determinism children re-import report.py, so we cannot monkeypatch
    build_reports without tripping environment-drift. Instead drop a hard key
    in the post-cert fold path (same surface schema_exit is produced on) so the
    certified expect still byte-matches while schema_exit is non-None.
    """
    from scripts.eval_harness import cli as cli_mod

    real_fold = cli_mod._fold_schema_errors_into_verdict

    def _drop_then_fold(scored):
        caption = scored.get("caption")
        if isinstance(caption, dict):
            caption.pop("must_right_failed_images", None)
        return real_fold(scored)

    monkeypatch.setattr(cli_mod, "_fold_schema_errors_into_verdict", _drop_then_fold)

    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path)
    expect = tmp_path / "schema-expect.json"
    _certified_caption_expect(manifest_path, record_path, expect)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc:
        main(_freeze_cert_score_argv(manifest_path, record_path, expect))
    assert exc.value.code != 0
    msg = str(exc.value).lower()
    assert "schema error" in msg
    assert "must_right_failed_images" in msg


def test_score_face_freeze_certification_exits_zero_when_bytes_match(tmp_path, monkeypatch, capsys):
    """TEST-15: score-face freeze-cert green path (byte-stable + integrity clean)."""
    from scripts.eval_harness.cli import _manifest_sha
    from scripts.eval_harness.manifest import load_manifest
    from scripts.eval_harness.report import build_face_reports

    record, manifest = _valid_face_manifest_and_record()
    rec_path = tmp_path / "face-run-fc.json"
    rec_path.write_text(json.dumps(record))
    man_path = tmp_path / "face-man-fc.json"
    man_path.write_text(json.dumps(manifest))
    # Certified face expect (anchor-generator shape).
    man = load_manifest(
        str(man_path),
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only; image bytes never opened",
        metadata_only=True,
    )
    j, _m = build_face_reports(record, man, score_manifest_sha256=_manifest_sha(man), public=False)
    expect = tmp_path / "face-expect.json"
    expect.write_text(j, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    rc = main(
        [
            "score-face",
            "--run-record",
            str(rec_path),
            "--manifest",
            str(man_path),
            "--check-determinism",
            "--expect-report",
            str(expect),
            "--freeze-certification",
        ]
    )
    assert rc is None
    out = capsys.readouterr().out
    assert "determinism check passed" in out
    assert "matches --expect-report" in out
    assert "freeze-certification" in out.lower()
    assert "byte-stable" in out.lower() or "bit-identical" in out.lower()


def _empty_golden_dir(tmp_path, monkeypatch) -> Path:
    """Existing-but-empty GOLDEN_IMAGES_DIR — fresh eval box shape (VLM6-RV3-Q4-01)."""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(empty))
    return empty


def test_cli_score_ignores_empty_golden_images_dir(tmp_path, monkeypatch):
    """VLM6-RV3-Q4-01 / OBS-04: score is metadata-only; empty env dir must not fail.

    Mutation: removing metadata_only=True from _cmd_score.load_manifest fails
    with ManifestError: image file missing.
    """
    _empty_golden_dir(tmp_path, monkeypatch)
    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path)
    monkeypatch.chdir(tmp_path)
    main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)])
    assert list(tmp_path.glob("*-report.json")), "score must write a report without image bytes"


def test_cli_score_face_ignores_empty_golden_images_dir(tmp_path, monkeypatch):
    """VLM6-RV3-Q4-01 / OBS-04: score-face is metadata-only; empty env dir must not fail.

    Mutation: removing metadata_only=True from _cmd_score_face.load_manifest
    fails with ManifestError: image file missing.
    """
    _empty_golden_dir(tmp_path, monkeypatch)
    record, manifest = _valid_face_manifest_and_record()
    rec_path = tmp_path / "face-run.json"
    rec_path.write_text(json.dumps(record))
    man_path = tmp_path / "man.json"
    man_path.write_text(json.dumps(manifest))
    main(["score-face", "--run-record", str(rec_path), "--manifest", str(man_path)])
    assert (tmp_path / "face-run-face-report.json").exists()


# ---------------------------------------------------------------------------
# VLM-6 Wave C · lane cx6 — gate-prefix contract (VLM6-R2-F-01 / F-03)
# ---------------------------------------------------------------------------


def test_score_face_failed_items_shares_caption_gate_prefix(tmp_path, monkeypatch):
    """VLM6-R2-F-03 / rg-015 / TEST-15: face failed-items uses shared prefix.

    Pre-fix face emitted ``score-face gate failed:`` so
    ``grep "failed-items gate"`` missed face entirely. Shared constant
    ``SCORE_GATE_PREFIX_FAILED_ITEMS`` must appear on both paths; face-specific
    tokens live in the suffix only.
    """
    from scripts.eval_harness import cli as cli_mod
    from scripts.eval_harness.cli import SCORE_GATE_PREFIX_FAILED_ITEMS

    record, manifest = _valid_face_manifest_and_record()
    rec_path = tmp_path / "face-run-fi.json"
    rec_path.write_text(json.dumps(record))
    man_path = tmp_path / "face-man-fi.json"
    man_path.write_text(json.dumps(manifest))

    real_face_once = cli_mod._face_score_once

    def _inject_failed(record_arg, manifest_arg, **kwargs):
        json_doc, md_doc = real_face_once(record_arg, manifest_arg, **kwargs)
        corrupted = json.loads(json_doc)
        counts = dict(corrupted.get("counts") or {})
        # Keep scored > 0 so zero-scored does not fire first; failed > 0 trips
        # the failed-items class (same order as caption score).
        scored_n = int(counts.get("scored") or 0)
        counts["failed"] = 1
        if scored_n <= 0:
            counts["scored"] = 1
            counts["total"] = max(int(counts.get("total") or 0), 1)
        corrupted["counts"] = counts
        return json.dumps(corrupted, indent=2, sort_keys=True) + "\n", md_doc

    monkeypatch.setattr(cli_mod, "_face_score_once", _inject_failed)

    with pytest.raises(SystemExit) as exc:
        main(["score-face", "--run-record", str(rec_path), "--manifest", str(man_path)])
    assert exc.value.code != 0
    msg = str(exc.value)
    assert SCORE_GATE_PREFIX_FAILED_ITEMS in msg, (
        f"face failed-items must share caption prefix {SCORE_GATE_PREFIX_FAILED_ITEMS!r}; got: {msg!r}"
    )
    assert "failed-items gate" in msg
    # Divergent historical prefix must not return (grep contract).
    assert not msg.startswith("score-face gate failed:")
    assert "score-face" in msg  # distinguishing suffix still present


def _parse_readme_score_gate_prefix_table(readme: str) -> set[str]:
    """Extract the Exit-message-prefix column from the operator gate table.

    Bounded to the 'Score non-zero exit prefixes' section so the pre-gate
    hard-failure table cannot silently satisfy (or pollute) set equality.
    """
    import re

    start = readme.find("### Score non-zero exit prefixes")
    assert start >= 0, "README missing § 'Score non-zero exit prefixes'"
    rest = readme[start:]
    end_m = re.search(r"\n(?:Integrity gates|Pre-gate hard failures)", rest)
    section = rest[: end_m.start()] if end_m else rest
    # Column 2 of each data row: | class | `prefix` | when | action |
    return set(re.findall(r"^\| [^|\n]+ \| `([^`]+)` \|", section, re.MULTILINE))


def test_score_gate_prefixes_documented_in_readme():
    """VLM6-R2-F-01 / RF-06 / rg-006: README table ≡ SCORE_GATE_PREFIXES.

    Bidirectional set equality (no ``>= N`` floor):
    - undocumented constant → red (frozenset − table)
    - stale README row → red (table − frozenset)
    - deleted constant absorbed by a loose floor → red (floor-free)
    Parses the operator-facing table only (not prose/code-comment substring).
    """
    from scripts.eval_harness.cli import SCORE_GATE_PREFIXES

    readme_path = Path(__file__).resolve().parents[2] / "scripts" / "eval_harness" / "README.md"
    assert readme_path.is_file(), f"missing eval-harness README at {readme_path}"
    readme = readme_path.read_text(encoding="utf-8")
    table = _parse_readme_score_gate_prefix_table(readme)
    missing_from_readme = sorted(SCORE_GATE_PREFIXES - table)
    stale_in_readme = sorted(table - SCORE_GATE_PREFIXES)
    assert not missing_from_readme and not stale_in_readme, (
        "SCORE_GATE_PREFIXES ↔ README table drift (rg-006 / RF-06):\n"
        f"  missing from README table: {missing_from_readme}\n"
        f"  stale in README table: {stale_in_readme}\n"
        f"  frozenset={sorted(SCORE_GATE_PREFIXES)}\n"
        f"  table={sorted(table)}"
    )
    # Count is derived from the frozenset (no hardcoded floor that tolerates
    # deleting a documented prefix — RF-06).
    assert len(table) == len(SCORE_GATE_PREFIXES)
    assert len(SCORE_GATE_PREFIXES) >= 1


def test_score_gate_fail_call_sites_use_prefix_constants():
    """RE-04 / TEST-15: gate messages must be built from SCORE_GATE_PREFIX_*.

    The README drift test alone stays green when a call site hardcodes a
    divergent literal while the frozenset stays fully documented. This AST
    scan locks call sites: ``_score_gate_fail`` / run-wrapper print+exit must
    reference a ``SCORE_GATE_PREFIX_*`` name (or a known prebuilt ``*_exit`` /
    ``msg`` variable that itself is built from those constants).
    """
    import ast
    import re

    from scripts.eval_harness.cli import SCORE_GATE_PREFIXES

    cli_path = Path(__file__).resolve().parents[2] / "scripts" / "eval_harness" / "cli.py"
    src = cli_path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    # Every SCORE_GATE_PREFIX_* assignment value must be in the frozenset, and
    # every frozenset member must have a matching assignment (single source).
    assigned: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id.startswith("SCORE_GATE_PREFIX_"):
            continue
        if target.id == "SCORE_GATE_PREFIXES":
            continue
        assert isinstance(node.value, ast.Constant) and isinstance(node.value.value, str), (
            f"{target.id} must be a string constant"
        )
        assigned[target.id] = node.value.value
    assert set(assigned.values()) == set(SCORE_GATE_PREFIXES), (
        "SCORE_GATE_PREFIX_* assignments ≠ SCORE_GATE_PREFIXES frozenset:\n"
        f"  only in assignments: {sorted(set(assigned.values()) - set(SCORE_GATE_PREFIXES))}\n"
        f"  only in frozenset: {sorted(set(SCORE_GATE_PREFIXES) - set(assigned.values()))}"
    )

    allowed_indirect = frozenset(
        {
            "schema_exit",
            "relabel_exit",
            "evidence_exit",
            "first_msg",
            "msg",
            "err",
        }
    )
    offenders: list[str] = []

    def _names_in(expr: ast.AST) -> set[str]:
        return {n.id for n in ast.walk(expr) if isinstance(n, ast.Name)}

    def _arg_ok(arg: ast.AST) -> bool:
        if isinstance(arg, ast.Name):
            # Bare name: prebuilt message (schema_exit / relabel_exit / …).
            return True
        # _score_schema_error_message(...) is itself built from SCORE_GATE_PREFIX_SCHEMA_ERROR.
        if isinstance(arg, ast.Call):
            f = arg.func
            if isinstance(f, ast.Name) and f.id == "_score_schema_error_message":
                return True
            if isinstance(f, ast.Attribute) and f.attr == "_score_schema_error_message":
                return True
        names = _names_in(arg)
        if any(n.startswith("SCORE_GATE_PREFIX_") for n in names):
            return True
        if names & allowed_indirect:
            return True
        return False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        func_name = None
        if isinstance(func, ast.Name):
            func_name = func.id
        elif isinstance(func, ast.Attribute):
            func_name = func.attr
        if func_name == "_score_gate_fail":
            if not node.args:
                offenders.append(f"L{node.lineno}: _score_gate_fail() with no args")
                continue
            if not _arg_ok(node.args[0]):
                offenders.append(
                    f"L{node.lineno}: _score_gate_fail arg does not reference "
                    f"SCORE_GATE_PREFIX_* (or allowed indirect); names="
                    f"{sorted(_names_in(node.args[0]))}"
                )
        elif func_name == "print" and node.args:
            # RF-05: run per-record stderr wrapper.
            arg0 = node.args[0]
            if isinstance(arg0, (ast.JoinedStr, ast.Constant)):
                # Reconstruct static text for a cheap filter.
                static = ""
                if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                    static = arg0.value
                elif isinstance(arg0, ast.JoinedStr):
                    static = "".join(
                        v.value for v in arg0.values if isinstance(v, ast.Constant) and isinstance(v.value, str)
                    )
                if re.search(r"score gate failed|run score gate", static):
                    if not _arg_ok(arg0):
                        offenders.append(
                            f"L{node.lineno}: print gate wrapper missing SCORE_GATE_PREFIX_*; static={static!r}"
                        )
        elif func_name == "exit" and node.args:
            # sys.exit(...) — run multi-record summary.
            arg0 = node.args[0]
            static = ""
            if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                static = arg0.value
            elif isinstance(arg0, ast.JoinedStr):
                static = "".join(
                    v.value for v in arg0.values if isinstance(v, ast.Constant) and isinstance(v.value, str)
                )
            if re.search(r"run score gates failed|score gate failed", static):
                if not _arg_ok(arg0):
                    offenders.append(
                        f"L{node.lineno}: sys.exit gate summary missing SCORE_GATE_PREFIX_*; static={static!r}"
                    )

    assert not offenders, (
        "Gate call sites must build messages from SCORE_GATE_PREFIX_* constants "
        "(RE-04 / RF-04 / RF-05):\n  - " + "\n  - ".join(offenders)
    )


def test_refuse_overwrite_uses_stable_shared_prefix(tmp_path, monkeypatch):
    """RF-04 / rg-015 / TEST-15: refuse-overwrite is label-independent.

    Pre-fix emitted ``f"{label} refuse-overwrite: …"`` so caption vs face
    diverged (``score refuse-overwrite:`` vs ``score-face refuse-overwrite:``)
    and neither was in SCORE_GATE_PREFIXES. Shared constant lives in the
    prefix; label is a suffix token.
    """
    from scripts.eval_harness import cli as cli_mod
    from scripts.eval_harness.cli import (
        SCORE_GATE_PREFIX_REFUSE_OVERWRITE,
        SCORE_GATE_PREFIXES,
        ScoreGateError,
        _refuse_report_overwrite,
    )

    assert SCORE_GATE_PREFIX_REFUSE_OVERWRITE in SCORE_GATE_PREFIXES
    target = tmp_path / "docs" / "tasks" / "vlm" / "bakeoff-results" / "x-report.json"
    target.parent.mkdir(parents=True)
    target.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        cli_mod,
        "_is_committed_report_tree",
        lambda p: "bakeoff-results" in str(p),
    )

    with pytest.raises(ScoreGateError) as cap_score:
        _refuse_report_overwrite([target], allow=False, label="score")
    msg_score = str(cap_score.value)
    assert msg_score.startswith(SCORE_GATE_PREFIX_REFUSE_OVERWRITE), (
        f"caption refuse-overwrite must start with {SCORE_GATE_PREFIX_REFUSE_OVERWRITE!r}; got {msg_score!r}"
    )
    assert "score:" in msg_score  # label as suffix

    with pytest.raises(ScoreGateError) as cap_face:
        _refuse_report_overwrite([target], allow=False, label="score-face")
    msg_face = str(cap_face.value)
    assert msg_face.startswith(SCORE_GATE_PREFIX_REFUSE_OVERWRITE), (
        f"face refuse-overwrite must start with {SCORE_GATE_PREFIX_REFUSE_OVERWRITE!r}; got {msg_face!r}"
    )
    assert "score-face" in msg_face
    # Historical label-varying prefixes must not return as the class token.
    assert not msg_face.startswith("score-face refuse-overwrite:")
    assert not msg_score.startswith("score refuse-overwrite:")
    # Allow-path is silent.
    _refuse_report_overwrite([target], allow=True, label="score")


# ---------------------------------------------------------------------------
# VLM6-RV11-L-01 / L-02 — C-locale score I/O (EVAL-10)
# ---------------------------------------------------------------------------

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_ASCII_LOCALE_ENV = {
    "LC_ALL": "C",
    "LANG": "C",
    "PYTHONUTF8": "0",
    "PYTHONCOERCECLOCALE": "0",
}

# Drop parent locale/utf8 so `_ASCII_LOCALE_ENV` is the child's sole source
# (MUT s is otherwise masked when the parent is already C).
_ASCII_LOCALE_PARENT_KEYS = (
    "LC_ALL",
    "LANG",
    "LC_CTYPE",
    "LC_MESSAGES",
    "LANGUAGE",
    "PYTHONUTF8",
    "PYTHONCOERCECLOCALE",
)
_ASCII_FS_ENCODINGS = frozenset({"ascii", "ansi-x3.4-1968", "us-ascii"})
_ASCII_LOCALE_PROBE_CACHE: tuple[str, str, int] | None = None
_ASCII_LOCALE_PROBE_CACHE_KEY: tuple[tuple[tuple[str, str], ...], tuple[str, ...]] | None = None


def _c_locale_child_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in _ASCII_LOCALE_PARENT_KEYS:
        env.pop(key, None)
    env.update(_ASCII_LOCALE_ENV)
    extra = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(_SERVICE_ROOT) + (os.pathsep + extra if extra else "")
    return env


def _ascii_locale_probe_key() -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    """Hashable snapshot of the env the child will actually see (TEST-15)."""
    return (tuple(sorted(_ASCII_LOCALE_ENV.items())), tuple(_ASCII_LOCALE_PARENT_KEYS))


def _ascii_locale_probe() -> tuple[str, str, int]:
    """One child process per distinct env: observe encodings (TEST-15).

    functools.lru_cache cannot be imported here (E402 / ownership is this region
    only). A one-slot cache keyed on `_ASCII_LOCALE_ENV` + stripped-key set is
    the same session cost as before, but MUT u can no longer pin a stale triple.
    """
    global _ASCII_LOCALE_PROBE_CACHE, _ASCII_LOCALE_PROBE_CACHE_KEY
    key = _ascii_locale_probe_key()
    if _ASCII_LOCALE_PROBE_CACHE is not None and key == _ASCII_LOCALE_PROBE_CACHE_KEY:
        return _ASCII_LOCALE_PROBE_CACHE
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import locale,sys;"
                "print(sys.getfilesystemencoding());"
                "print(locale.getpreferredencoding(False));"
                "print(int(bool(sys.flags.utf8_mode)))"
            ),
        ],
        env=_c_locale_child_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"C-locale encoding probe exited {proc.returncode}: {proc.stderr}")
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    if len(lines) < 3:
        raise AssertionError(f"C-locale encoding probe returned {lines!r} stderr={proc.stderr!r}")
    _ASCII_LOCALE_PROBE_CACHE = (lines[0], lines[1], int(lines[2]))
    _ASCII_LOCALE_PROBE_CACHE_KEY = key
    return _ASCII_LOCALE_PROBE_CACHE


def _assert_child_ascii_locale() -> None:
    fsenc, pref, utf8_mode = _ascii_locale_probe()
    # getfilesystemencoding() is a platform property (always utf-8 on Darwin).
    # Product I/O pins need preferred/stdio ASCII + utf8_mode==0 (TEST-15).
    pref_ok = pref.lower().replace("_", "-") in _ASCII_FS_ENCODINGS
    if not (pref_ok and utf8_mode == 0):
        raise AssertionError(
            "C-locale child probe is not ASCII / utf8_mode=0: "
            f"getfilesystemencoding={fsenc!r} getpreferredencoding={pref!r} "
            f"utf8_mode={utf8_mode} (dict keys={sorted(_ASCII_LOCALE_ENV)!r})"
        )


def test_assert_child_ascii_locale_accepts_utf8_filesystem_encoding(monkeypatch):
    """VLM6-RV14-L-01 / TEST-15: fs encoding is a platform property.

    Darwin hard-wires getfilesystemencoding() to utf-8. The guard must still
    accept a child whose preferred encoding is ASCII and utf8_mode==0.
    """
    monkeypatch.setattr(
        sys.modules[__name__],
        "_ascii_locale_probe",
        lambda: ("utf-8", "ANSI_X3.4-1968", 0),
    )
    _assert_child_ascii_locale()


def test_assert_child_ascii_locale_rejects_non_ascii_preferred_or_utf8_mode(monkeypatch):
    """VLM6-RV14-L-01 / TEST-15: preferred encoding + utf8_mode stay hard."""
    monkeypatch.setattr(
        sys.modules[__name__],
        "_ascii_locale_probe",
        lambda: ("utf-8", "utf-8", 0),
    )
    with pytest.raises(AssertionError, match="getpreferredencoding"):
        _assert_child_ascii_locale()

    monkeypatch.setattr(
        sys.modules[__name__],
        "_ascii_locale_probe",
        lambda: ("utf-8", "ascii", 1),
    )
    with pytest.raises(AssertionError, match="utf8_mode"):
        _assert_child_ascii_locale()


def test_ascii_locale_probe_cache_is_keyed_on_env():
    """VLM6-RV15-Q2-02 / VLM6-RV14-Q2-01 / TEST-15: key includes _ASCII_LOCALE_ENV.

    Seed cache AND key through `_ascii_locale_probe_key()` (never CACHE_KEY=None),
    then mutate PYTHONUTF8. Parent-key-only or constant keying returns the
    stale triple; the live key must re-probe (utf8_mode==1).
    """
    global _ASCII_LOCALE_PROBE_CACHE, _ASCII_LOCALE_PROBE_CACHE_KEY
    saved_cache = _ASCII_LOCALE_PROBE_CACHE
    saved_key = _ASCII_LOCALE_PROBE_CACHE_KEY
    saved_env = dict(_ASCII_LOCALE_ENV)
    try:
        _ASCII_LOCALE_PROBE_CACHE = ("ascii", "ascii", 0)
        _ASCII_LOCALE_PROBE_CACHE_KEY = _ascii_locale_probe_key()
        _ASCII_LOCALE_ENV["PYTHONUTF8"] = "1"
        fsenc, pref, utf8_mode = _ascii_locale_probe()
        assert utf8_mode == 1, (
            f"probe cache is not keyed on env: PYTHONUTF8=1 still returned stale {(fsenc, pref, utf8_mode)!r} (MUT u)"
        )
    finally:
        _ASCII_LOCALE_ENV.clear()
        _ASCII_LOCALE_ENV.update(saved_env)
        _ASCII_LOCALE_PROBE_CACHE = saved_cache
        _ASCII_LOCALE_PROBE_CACHE_KEY = saved_key


def _run_score_c_locale(
    manifest_path: Path, record_path: Path, extra_argv: list[str] | None = None
) -> subprocess.CompletedProcess:
    _assert_child_ascii_locale()
    env = _c_locale_child_env()
    argv = [
        sys.executable,
        "-c",
        "import sys; from scripts.eval_harness.cli import main; main(sys.argv[1:])",
        "score",
        "--manifest",
        str(manifest_path),
        "--run-record",
        str(record_path),
    ]
    if extra_argv:
        argv.extend(extra_argv)
    return subprocess.run(
        argv,
        cwd=str(_SERVICE_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_cmd_score_check_determinism_raw_utf8_run_record_under_c_locale(tmp_path):
    """VLM6-RV12-Q1-02 / L-02 / EVAL-10: --check-determinism child must pin utf-8.

    Parent read is already pinned; the child snippet rec_path.read_text() is not.
    Under C locale a café run record makes the child UnicodeDecodeError (rc=1)
    while plain score exits 0. MUT[drop_child_read_pin]: drop encoding= on the
    child read → this test fails.
    """
    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path, stem="run-det-cafe")
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    payload["items"][0]["describe"]["alt_text_draft"] = "café " + payload["items"][0]["describe"]["alt_text_draft"]
    record_path.write_bytes((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
    proc = _run_score_c_locale(manifest_path, record_path, extra_argv=["--check-determinism"])
    assert proc.returncode == 0, proc.stderr
    assert "determinism check passed" in proc.stdout


def test_load_ignore_list_accepts_utf8_bom(tmp_path):
    """VLM6-RV12-Q1-03 / EVAL-10: BOM-prefixed ignore-list must load.

    MUT[utf8_sig_to_utf8]: encoding='utf-8' → ManifestError Unexpected UTF-8 BOM.
    """
    from scripts.eval_harness.cli import _load_ignore_list

    body = json.dumps({"wrong_names": []})
    (tmp_path / "ignore-list.json").write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    payload = _load_ignore_list(tmp_path)
    assert payload == {"wrong_names": []}


def test_load_ignore_list_invalid_bytes_raises_manifest_error_naming_path(tmp_path):
    """VLM6-RV12-Q1-03 / EVAL-10: \\xff\\xfe ignore-list → ManifestError naming path.

    MUT[narrow_ignore_guard]: except JSONDecodeError only → UnicodeDecodeError escapes.
    """
    from scripts.eval_harness.cli import _load_ignore_list
    from scripts.eval_harness.manifest import ManifestError

    path = tmp_path / "ignore-list.json"
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(ManifestError) as excinfo:
        _load_ignore_list(tmp_path)
    msg = str(excinfo.value)
    assert str(path) in msg
    assert "Traceback" not in msg


def test_cmd_score_ignore_list_jose_under_c_locale(tmp_path):
    """VLM6-RV12-Q1-03 / EVAL-10: C-locale score with José in ignore-list.

    MUT[drop_ignore_read_pin]: bare read_text() → UnicodeDecodeError (MUT p).
    """
    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path, stem="run-jose-ignore")
    ignore = {"wrong_names": [["mock_images/alice.jpg", "José"]]}
    (tmp_path / "ignore-list.json").write_bytes((json.dumps(ignore, ensure_ascii=False) + "\n").encode("utf-8"))
    proc = _run_score_c_locale(manifest_path, record_path)
    assert proc.returncode == 0, proc.stderr


def test_cmd_score_audience_public_writes_pi_under_c_locale(tmp_path):
    """VLM6-RV12-Q2-01 / TEST-15: C-locale --audience public pins public writes.

    MUT[drop_public_write_pin]: drop encoding= on public json/md → UnicodeEncodeError π.
    """
    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path, stem="run-public-c")
    proc = _run_score_c_locale(manifest_path, record_path, extra_argv=["--audience", "public"])
    assert proc.returncode == 0, proc.stderr
    public_json = tmp_path / "run-public-c-report.public.json"
    raw = public_json.read_bytes()
    assert b"\xcf\x80" in raw
    assert "π" in public_json.read_text(encoding="utf-8")


def test_cmd_score_writes_utf8_report_under_c_locale(tmp_path):
    """VLM6-RV11-L-01 / EVAL-10: score report writes must pin utf-8.

    report.py serialises ensure_ascii=False and always emits 'π'. Unpinned
    write_text under PYTHONUTF8=0 LC_ALL=C LANG=C dies with UnicodeEncodeError.
    MUT[drop_score_write_pin]: revert the json_path write pin → this test fails.
    """
    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path, stem="run-c-locale")
    proc = _run_score_c_locale(manifest_path, record_path)
    assert proc.returncode == 0, proc.stderr
    report_path = tmp_path / "run-c-locale-report.json"
    scored = json.loads(report_path.read_text(encoding="utf-8"))
    assert isinstance(scored, dict)
    assert "π" in report_path.read_text(encoding="utf-8")


def test_cmd_score_raw_utf8_run_record_under_c_locale(tmp_path):
    """VLM6-RV11-L-02 / EVAL-10: raw-UTF-8 run record must decode under C locale.

    MUT[drop_record_read_pin]: bare read_text() → UnicodeDecodeError.
    """
    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path, stem="run-raw-utf8")
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    payload["items"][0]["describe"]["alt_text_draft"] = "café " + payload["items"][0]["describe"]["alt_text_draft"]
    record_path.write_bytes((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
    proc = _run_score_c_locale(manifest_path, record_path)
    assert proc.returncode == 0, proc.stderr


def test_cmd_score_invalid_utf8_run_record_named_exit(tmp_path, capsys):
    """VLM6-RV11-L-02: \\xff\\xfe record → named exit 2, no report written.

    MUT[narrow_record_guard]: except OSError only → UnicodeDecodeError escapes.
    """
    record = tmp_path / "run-bad.json"
    record.write_bytes(b"\xff\xfe")
    man = tmp_path / "man.json"
    man.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(man), "--run-record", str(record)])
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "score: run record not found/unreadable:" in captured.err
    assert str(record) in captured.err
    assert not (tmp_path / "run-bad-report.json").exists()


def test_cmd_score_missing_run_record_named_exit(tmp_path, capsys):
    """VLM6-RV11-L-02: missing run record → named exit 2."""
    missing = tmp_path / "no-such-run.json"
    man = tmp_path / "man.json"
    man.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        main(["score", "--manifest", str(man), "--run-record", str(missing)])
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "score: run record not found/unreadable:" in captured.err
    assert str(missing) in captured.err


# ---------------------------------------------------------------------------
# VLM-6 fix wave 12 / Lane IA — score-face fail-closed + C-locale I/O
# ---------------------------------------------------------------------------


def _run_score_face_c_locale(
    manifest_path: Path, record_path: Path, extra_argv: list[str] | None = None
) -> subprocess.CompletedProcess:
    _assert_child_ascii_locale()
    env = _c_locale_child_env()
    argv = [
        sys.executable,
        "-c",
        "import sys; from scripts.eval_harness.cli import main; main(sys.argv[1:])",
        "score-face",
        "--manifest",
        str(manifest_path),
        "--run-record",
        str(record_path),
    ]
    if extra_argv:
        argv.extend(extra_argv)
    return subprocess.run(
        argv,
        cwd=str(_SERVICE_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _assert_no_score_reports(tmp_path: Path) -> None:
    leftover = [p.name for p in tmp_path.glob("*report*")]
    assert leftover == []


def test_cmd_score_face_invalid_utf8_run_record_named_exit(tmp_path, capsys):
    """VLM6-RV12-Q1-01 / L-01: \\xff\\xfe record → named exit 2, no report written.

    MUT[narrow_face_record_guard]: except OSError only → UnicodeDecodeError escapes.
    """
    record = tmp_path / "run-bad.json"
    record.write_bytes(b"\xff\xfe")
    man = tmp_path / "man.json"
    man.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        main(["score-face", "--manifest", str(man), "--run-record", str(record)])
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "score-face: run record not found/unreadable:" in captured.err
    assert str(record) in captured.err
    _assert_no_score_reports(tmp_path)


def test_cmd_score_face_missing_run_record_named_exit(tmp_path, capsys):
    """VLM6-RV12-Q1-01 / L-01: missing run record → named exit 2."""
    missing = tmp_path / "no-such-face-run.json"
    man = tmp_path / "man.json"
    man.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        main(["score-face", "--manifest", str(man), "--run-record", str(missing)])
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "score-face: run record not found/unreadable:" in captured.err
    assert str(missing) in captured.err
    _assert_no_score_reports(tmp_path)


def test_cmd_score_face_directory_run_record_named_exit(tmp_path, capsys):
    """VLM6-RV12-Q1-01 / L-01: directory as record → named exit 2."""
    record_dir = tmp_path / "run-dir"
    record_dir.mkdir()
    man = tmp_path / "man.json"
    man.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        main(["score-face", "--manifest", str(man), "--run-record", str(record_dir)])
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "score-face: run record not found/unreadable:" in captured.err
    assert str(record_dir) in captured.err
    _assert_no_score_reports(tmp_path)


def test_cmd_score_face_raw_utf8_run_record_under_c_locale(tmp_path):
    """VLM6-RV12-Q2-05 / TEST-15: encoding=utf-8 pin on score-face record read.

    Raw-UTF-8 face run-record (image path celebs01/café-a.jpg, bytes c3 a9)
    must decode under PYTHONUTF8=0 LC_ALL=C LANG=C. MUT n [drop_face_record_read_pin]:
    bare read_text() → UnicodeDecodeError.
    """
    record, manifest = _valid_face_manifest_and_record()
    record["items"][0]["path"] = "celebs01/café-a.jpg"
    manifest["entries"][0]["path"] = "celebs01/café-a.jpg"
    rec_path = tmp_path / "face-run.json"
    rec_path.write_bytes((json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
    man_path = tmp_path / "man.json"
    man_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert b"\xc3\xa9" in rec_path.read_bytes()
    proc = _run_score_face_c_locale(man_path, rec_path)
    assert proc.returncode == 0, proc.stderr


def test_cmd_score_face_check_determinism_raw_utf8_run_record_under_c_locale(tmp_path):
    """VLM6-RV13-Q2-01 / TEST-15: score-face --check-determinism child must pin utf-8.

    Parent read is already pinned; the child snippet Path(sys.argv[1]).read_text()
    is not unless encoding='utf-8'. Under C locale a café face run-record makes
    the child UnicodeDecodeError (rc!=0) while plain score-face exits 0.
    MUT p: revert cli.py child read to open(sys.argv[1]).read() → this test fails.
    """
    record, manifest = _valid_face_manifest_and_record()
    record["items"][0]["path"] = "celebs01/café-a.jpg"
    manifest["entries"][0]["path"] = "celebs01/café-a.jpg"
    rec_path = tmp_path / "face-run-det.json"
    rec_path.write_bytes((json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
    man_path = tmp_path / "man.json"
    man_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert b"\xc3\xa9" in rec_path.read_bytes()
    proc = _run_score_face_c_locale(man_path, rec_path, extra_argv=["--check-determinism"])
    assert proc.returncode == 0, proc.stderr
    assert "determinism check passed" in proc.stdout


def test_cmd_score_face_writes_utf8_report_under_c_locale(tmp_path):
    """VLM6-RV12-Q2-02 / TEST-15: score-face report writes must pin utf-8.

    Valid fixture emits § (and ± τ – — → ↔ ∧ ≈ ≥). Unpinned write_text under
    C locale dies with UnicodeEncodeError '\\xa7'. MUT m [drop_face_write_pin]:
    bare json_doc/md_doc write_text → this test fails.
    """
    record, manifest = _valid_face_manifest_and_record()
    rec_path = tmp_path / "face-run.json"
    rec_path.write_text(json.dumps(record), encoding="utf-8")
    man_path = tmp_path / "man.json"
    man_path.write_text(json.dumps(manifest), encoding="utf-8")
    proc = _run_score_face_c_locale(man_path, rec_path)
    assert proc.returncode == 0, proc.stderr
    report_path = tmp_path / "face-run-face-report.json"
    body = report_path.read_text(encoding="utf-8")
    assert "§" in body


def test_cmd_score_non_ascii_run_record_path_under_c_locale(tmp_path):
    """VLM6-RV13-L-01 / L-02 / Q1-02: print(md_path) emits real UTF-8 path bytes.

    Fixture path is bytes so parent pytest under LC_ALL=C can still create it
    (AGT-06: no skip). Child is captured in binary so the assertion cannot be
    fooled by the parent's decoder. Printed path must be the real UTF-8
    basename (OBS-08), not the backslashreplace lie.
    """
    manifest_path, record_path = _clean_score_manifest_and_record(tmp_path, stem="run-clean")
    dir_b = os.fsencode(tmp_path)
    cafe_record_b = dir_b + b"/" + b"run-caf\xc3\xa9.json"
    with open(cafe_record_b, "wb") as fh:
        fh.write(record_path.read_bytes())
    # PYTHONIOENCODING=ascii forces errors=strict BEFORE `_reconfigure_stdio`.
    # C-locale pipes default to surrogateescape. The child prints
    # sys.stdout.errors first so this env var is load-bearing (TEST-15).
    _assert_child_ascii_locale()
    env = _c_locale_child_env()
    env["PYTHONIOENCODING"] = "ascii"
    proc = subprocess.run(
        [
            os.fsencode(sys.executable),
            b"-c",
            (
                b"import sys; print(sys.stdout.errors, flush=True); "
                b"from scripts.eval_harness.cli import main; main(sys.argv[1:])"
            ),
            b"score",
            b"--manifest",
            os.fsencode(manifest_path),
            b"--run-record",
            cafe_record_b,
        ],
        cwd=os.fsencode(_SERVICE_ROOT),
        env=env,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
    md_path_basename = b"run-caf\xc3\xa9-report.md"
    json_path_basename = b"run-caf\xc3\xa9-report.json"
    assert os.path.exists(dir_b + b"/" + json_path_basename)
    assert os.path.exists(dir_b + b"/" + md_path_basename)
    lines = proc.stdout.splitlines()
    assert lines[0] == b"strict", (
        f"PYTHONIOENCODING=ascii must pin stdout.errors=strict before reconfigure; got {lines[0]!r}"
    )
    # Path is the next line; a stats line follows, so strip() does not end
    # with the basename. Pin the machine-consumable line (OBS-08 / L-02).
    assert lines[1].endswith(os.fsencode(md_path_basename))
    assert b"run-caf\\xe9-report.md" not in proc.stdout


def test_reconfigure_stdio_utf8_stdout_and_stderr(monkeypatch):
    """VLM6-RV13-Q2-04 / TEST-15: both halves of the reconfigure loop are pinned.

    In-process: ascii/strict TextIOWrappers, then _reconfigure_stdio(), then a
    true Unicode write (not via argv). Underlying buffers must hold UTF-8
    bytes, not the backslashreplace escape. MUT c (stdout-only loop) fails
    the stderr half; MUT L-01 (drop encoding=utf-8) fails both; MUT b
    (errors=strict) fails the errors pin.
    """
    import io

    from scripts.eval_harness.cli import _reconfigure_stdio

    stdout_buf = io.BytesIO()
    stderr_buf = io.BytesIO()
    fake_stdout = io.TextIOWrapper(stdout_buf, encoding="ascii", errors="strict", newline="")
    fake_stderr = io.TextIOWrapper(stderr_buf, encoding="ascii", errors="strict", newline="")
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    monkeypatch.setattr(sys, "stderr", fake_stderr)

    _reconfigure_stdio()

    assert fake_stdout.encoding.lower() in {"utf-8", "utf8"}
    assert fake_stderr.encoding.lower() in {"utf-8", "utf8"}
    assert fake_stdout.errors == "backslashreplace"
    assert fake_stderr.errors == "backslashreplace"

    payload = "run-café-report.md"
    fake_stdout.write(payload)
    fake_stdout.flush()
    fake_stderr.write(payload)
    fake_stderr.flush()

    utf8_payload = b"run-caf\xc3\xa9-report.md"
    escaped_payload = b"run-caf\\xe9-report.md"
    assert utf8_payload in stdout_buf.getvalue()
    assert escaped_payload not in stdout_buf.getvalue()
    assert utf8_payload in stderr_buf.getvalue()
    assert escaped_payload not in stderr_buf.getvalue()


def test_in_process_main_does_not_leak_stdio_encoding():
    """VLM6-RV15-L-03 / TEST-15: in-process main() must not leak stdio codecs.

    `_reconfigure_stdio` sets utf-8/backslashreplace on process-global streams.
    The autouse `_stdio_encoding_guard` fixture must restore (encoding, errors)
    before this assertion sees them.
    """
    before = (sys.stdout.encoding, sys.stdout.errors)
    with pytest.raises(SystemExit):
        main([])
    after = (sys.stdout.encoding, sys.stdout.errors)
    assert after == before, f"stdio leaked across in-process main(): {before!r} -> {after!r}"
