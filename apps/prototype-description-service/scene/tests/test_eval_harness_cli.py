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
                provenance={"source": "operator", "license": "mock_entity"},
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
                provenance={"source": "operator", "license": "mock_entity"},
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
            "provenance": {"source": "operator", "license": "mock_entity"},
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
