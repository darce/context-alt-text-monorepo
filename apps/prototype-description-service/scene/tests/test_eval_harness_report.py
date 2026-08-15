"""VLM-2A Slice 3: report builder + scoring pipeline — deterministic, golden-file style."""

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from scripts.eval_harness.report import (
    DIRECTIONAL_LABEL,
    FACE_BAKEOFF_CANON_VERSION,
    GATE_PROPOSAL_RELEASE_SURFACE,
    HEADLINE_ID_RECALL_ELIGIBLE_FLOOR,
    Audience,
    ReportError,
    _latency_summary,
    build_face_reports,
    build_reports,
    redact_face_report_for_public,
    score_face_run_record,
    score_run_record,
    synthetic_real_divergence,
    wilson_half_width,
)
from scripts.eval_harness.schema import DocKind


def _run_record() -> dict:
    return {
        "schema": "acx-eval/v1",
        "kind": "run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "base_url": "https://api.example.com",
            "head_sha": "0" * 40,
            "started_at": "2026-07-06T00:00:00Z",
        },
        "items": [
            {
                "media_id": 1,
                "path": "mock_images/alice-pool.jpg",
                "describe": {
                    "alt_text_draft": "Alice Example relaxes by a pool.",
                    "visual_facts": {"caption": "a person by a pool", "objects": ["pool", "person"]},
                    "adapter": "seeded",
                    "model_id": "seeded-fixtures",
                    "model_version": "1",
                    "cached": False,
                },
                "identities": ["Alice Example"],
                "face_count": 1,
                "error": None,
            },
            {
                "media_id": 2,
                "path": "mock_images/bob-beach.jpg",
                "describe": {
                    "alt_text_draft": "A man on a beach.",
                    "visual_facts": {"caption": "a man on a beach", "objects": ["beach"]},
                    "adapter": "seeded",
                    "model_id": "seeded-fixtures",
                    "model_version": "1",
                    "cached": True,
                },
                "identities": ["Alice Example"],  # wrong name: Bob labeled
                "face_count": 1,
                "error": None,
            },
            {
                "media_id": 3,
                "path": "mock_images/glacier.jpg",
                "describe": None,
                "identities": [],
                "face_count": 0,
                "error": "timeout after 60s",
            },
        ],
    }


def _manifest_entries() -> list[dict]:
    return [
        {
            "path": "mock_images/alice-pool.jpg",
            "media_id": 1,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "must_right": ["Alice Example"],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
        },
        {
            "path": "mock_images/bob-beach.jpg",
            "media_id": 2,
            "face_count": 1,
            "present_identities": ["Bob Builder"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
        },
        {
            "path": "mock_images/glacier.jpg",
            "media_id": 3,
            "face_count": 0,
            "present_identities": [],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
        },
    ]


def test_score_run_record_shapes():
    scored = score_run_record(_run_record(), _manifest_entries())
    assert scored["counts"] == {"total": 3, "scored": 2, "failed": 1}
    assert scored["caption"]["insertion_rate"] == pytest.approx(0.5)
    ident = scored["faces"]["identification"]
    assert ident["wrong_names"] == [["mock_images/bob-beach.jpg", "Alice Example"]]
    assert scored["failures"] == [{"path": "mock_images/glacier.jpg", "media_id": 3, "error": "timeout after 60s"}]


def test_reports_deterministic_and_json_round_trips():
    record, entries = _run_record(), _manifest_entries()
    json_a, md_a = build_reports(record, entries)
    json_b, md_b = build_reports(record, entries)
    assert json_a == json_b
    assert md_a == md_b
    parsed = json.loads(json_a)
    assert parsed["schema"] == "acx-eval/v1"
    assert parsed["provenance"]["head_sha"] == "0" * 40


def test_markdown_lists_wrong_names_individually():
    _json_doc, md = build_reports(_run_record(), _manifest_entries())
    assert "mock_images/bob-beach.jpg" in md
    assert "Alice Example" in md
    assert "Wrong-name" in md or "wrong-name" in md


def test_markdown_reports_failures_and_provenance():
    _json_doc, md = build_reports(_run_record(), _manifest_entries())
    assert "timeout after 60s" in md
    assert "0" * 40 in md


def test_ignore_list_suppresses_triaged_wrong_names():
    ignore = {"wrong_names": [["mock_images/bob-beach.jpg", "Alice Example"]]}
    json_doc, md = build_reports(_run_record(), _manifest_entries(), ignore_list=ignore)
    parsed = json.loads(json_doc)
    ident = parsed["faces"]["identification"]
    assert ident["wrong_names"] == []
    assert ident["ignored_wrong_names"] == [["mock_images/bob-beach.jpg", "Alice Example"]]
    assert "ignored (triaged): 1" in md.lower()


def test_model_provenance_surfaced():  # HARM-01
    json_doc, md = build_reports(_run_record(), _manifest_entries())
    model = json.loads(json_doc)["provenance"]["model"]
    assert model["adapters"] == ["seeded"]
    assert model["model_ids"] == ["seeded-fixtures"]
    assert model["model_versions"] == ["1"]
    assert "seeded" in md and "NOT a caption-model baseline" in md


def test_cache_hit_reads_contract_cached_field():  # HARM-02
    per_image = {p["media_id"]: p for p in score_run_record(_run_record(), _manifest_entries())["per_image"]}
    assert per_image[1]["cache_hit"] is False
    assert per_image[2]["cache_hit"] is True  # describe.cached=True, previously always False


def test_score_time_manifest_sha_recorded_and_compared():  # HARM-03
    scored = score_run_record(_run_record(), _manifest_entries(), score_manifest_sha256="a" * 64)
    prov = scored["provenance"]
    assert prov["score_manifest_sha256"] == "a" * 64
    assert prov["manifest_sha256"] == "m" * 64  # fetch-time preserved
    assert prov["manifest_matches_fetch"] is False  # a != m: drift surfaced


def test_detection_uses_face_count_and_counts_stranger_true_rejection():  # S3-01 / HARM-04 / S2-05
    record = {
        "schema": "acx-eval/v1",
        "kind": "run_record",
        "provenance": {"manifest_sha256": "m" * 64, "base_url": "x", "head_sha": "0" * 40, "started_at": "t"},
        "items": [
            {  # group photo: 1 roster person correctly named + 2 strangers, no wrong name
                "media_id": 1,
                "path": "mock_images/group.jpg",
                "describe": {"alt_text_draft": "Ryann and friends.", "visual_facts": {"objects": []}},
                "identities": ["Ryann Wiseman"],
                "face_count": 3,
                "error": None,
            },
        ],
    }
    entries = [
        {
            "path": "mock_images/group.jpg",
            "media_id": 1,
            "face_count": 3,  # ground truth: 3 faces present
            "present_identities": ["Ryann Wiseman"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
        }
    ]
    entries[0]["annotation_mode"] = "exhaustive"
    scored = score_run_record(record, entries, annotation_mode="exhaustive")
    det = scored["faces"]["detection"]
    # 3 predicted vs 3 labeled -> no false positives from the 2 strangers
    assert det["tp"] == 3 and det["fp"] == 0 and det["fn"] == 0
    # strangers present + no wrong name asserted -> true rejection counted (was dead code)
    assert scored["faces"]["identification"]["true_rejections"] == 1


def test_missing_media_id_becomes_failure_not_keyerror():  # S3-04
    record = _run_record()
    record["items"][0]["media_id"] = 999  # not in manifest
    scored = score_run_record(record, _manifest_entries())
    assert any(f["media_id"] == 999 and "not in score-time manifest" in f["error"] for f in scored["failures"])


def test_report_file_passed_as_run_record_is_rejected():  # HARM-06
    report_doc = json.loads(build_reports(_run_record(), _manifest_entries())[0])
    with pytest.raises(ReportError, match="report"):
        score_run_record(report_doc, _manifest_entries())


def test_unknown_schema_rejected():  # S3-04
    record = _run_record()
    record["schema"] = "acx-eval/v99"
    with pytest.raises(ReportError, match="schema"):
        score_run_record(record, _manifest_entries())


def test_missing_provenance_rejected():  # S3-04 malformed-doc guard
    record = _run_record()
    del record["provenance"]
    with pytest.raises(ReportError, match="provenance"):
        score_run_record(record, _manifest_entries())


def test_rubric_defined_images_surfaced():  # S1-02
    scored = score_run_record(_run_record(), _manifest_entries())
    assert scored["caption"]["must_right_defined_images"] == 1  # only alice-pool has must_right
    empty = [{**e, "must_right": [], "easy_wrong": []} for e in _manifest_entries()]
    scored_empty = score_run_record(_run_record(), empty)
    assert scored_empty["caption"]["must_right_defined_images"] == 0


def test_all_items_failed_aggregate_paths():  # S3-08
    record = _run_record()
    for item in record["items"]:
        item["error"] = "boom"
    json_doc, md = build_reports(record, _manifest_entries())
    scored = json.loads(json_doc)
    assert scored["counts"]["scored"] == 0
    assert scored["caption"]["mean_gated_score"] is None
    assert scored["faces"]["detection"]["precision"] is None
    assert "null" in md  # _fmt(None) rendered


# --- ALTQ-1: quality axes, dual surface, eval modes ---


def test_per_image_carries_quality_axes_and_quality_section():
    scored = score_run_record(_run_record(), _manifest_entries())
    row = next(r for r in scored["per_image"] if r["media_id"] == 1)
    for key in (
        "wrong_name_hits",
        "hallucinated_names",
        "meta_framing_hits",
        "context_duplication_ratio",
        "sentence_count",
        "name_front_loaded",
    ):
        assert key in row
    quality = scored["quality"]
    assert quality["sentence_band"] == [1, 4]
    assert quality["meta_framing_images"] == 0
    assert scored["caption"]["name_precision"] == pytest.approx(1.0)
    assert scored["caption"]["wrong_name_images"] == 0


def test_wrong_name_from_easy_wrong_zeroes_caption_gate():
    record, entries = _run_record(), _manifest_entries()
    entries[0]["easy_wrong"] = ["Mallory Trap"]
    record["items"][0]["describe"]["alt_text_draft"] = "Alice Example and Mallory Trap relax by a pool."
    scored = score_run_record(record, entries)
    row = next(r for r in scored["per_image"] if r["media_id"] == 1)
    assert row["wrong_name_hits"] == ["Mallory Trap"]
    assert row["gated_score"] == 0.0
    assert scored["caption"]["wrong_name_images"] == 1


def test_roster_hallucination_detected_across_corpus():
    record, entries = _run_record(), _manifest_entries()
    # Bob Builder is another entry's identity — naming him on Alice's image is a
    # closed-roster hallucination.
    record["items"][0]["describe"]["alt_text_draft"] = "Alice Example and Bob Builder relax by a pool."
    scored = score_run_record(record, entries)
    row = next(r for r in scored["per_image"] if r["media_id"] == 1)
    assert row["hallucinated_names"] == ["Bob Builder"]
    assert row["gated_score"] == 0.0


def test_alt_text_long_scored_as_second_surface():
    record, entries = _run_record(), _manifest_entries()
    record["items"][0]["describe"]["alt_text_long"] = (
        "Alice Example relaxes on a lounge chair beside a turquoise pool. Palm shadows cross the "
        "deck. Her sunhat rests on the table beside a paperback."
    )
    scored = score_run_record(record, entries)
    long_c = scored["caption_long"]
    assert long_c["images_with_long"] == 1
    assert long_c["insertion_rate"] == pytest.approx(1.0)
    assert long_c["quality"]["sentence_band"] == [2, 8]
    row = next(r for r in scored["per_image"] if r["media_id"] == 1)
    assert row["long"]["sentence_count"] == 3
    assert row["long"]["gated_score"] == 1.0


def test_no_caption_long_section_without_long_surface():
    scored = score_run_record(_run_record(), _manifest_entries())
    assert "caption_long" not in scored


def test_context_distractor_mode_counts_takes_and_resistance():
    record, entries = _run_record(), _manifest_entries()
    record["provenance"]["eval_mode"] = "context_distractor"
    entries[0]["easy_wrong"] = ["Mallory Trap"]
    record["items"][0]["describe"]["injected_distractor"] = "Mallory Trap"
    record["items"][0]["describe"]["alt_text_draft"] = "Alice Example and Mallory Trap relax by a pool."
    entries[1]["easy_wrong"] = ["Ned Nemo"]
    record["items"][1]["describe"]["injected_distractor"] = "Ned Nemo"
    scored = score_run_record(record, entries)
    assert scored["eval_mode"] == "context_distractor"
    d = scored["distractor"]
    assert d["injected_images"] == 2
    assert d["taken_images"] == 1
    assert d["resistance_rate"] == pytest.approx(0.5)
    taken_row = next(r for r in scored["per_image"] if r["media_id"] == 1)
    assert taken_row["distractor_taken"] is True
    assert taken_row["gated_score"] == 0.0  # a taken distractor is a wrong name


def test_name_ablation_mode_gates_on_leaks_not_must_right():
    record, entries = _run_record(), _manifest_entries()
    record["provenance"]["eval_mode"] = "name_ablation"
    record["items"][0]["describe"]["ablated_names"] = ["Alice Example"]
    record["items"][1]["describe"]["ablated_names"] = []
    # Caption still names Alice although her name was stripped from context: leak.
    scored = score_run_record(record, entries)
    leak_row = next(r for r in scored["per_image"] if r["media_id"] == 1)
    assert leak_row["gated_score"] == 0.0
    assert leak_row["must_right_failures"] == []  # must-right suspended in ablation
    clean_row = next(r for r in scored["per_image"] if r["media_id"] == 2)
    assert clean_row["gated_score"] == 1.0  # "A man on a beach" leaks nothing
    a = scored["ablation"]
    assert a["eligible_images"] == 2
    assert a["leak_images"] == 1
    assert a["leak_free_rate"] == pytest.approx(0.5)


def test_unknown_eval_mode_rejected():
    record = _run_record()
    record["provenance"]["eval_mode"] = "bogus"
    with pytest.raises(ReportError):
        score_run_record(record, _manifest_entries())


def test_mode_banner_and_sections_rendered_in_markdown():
    record, entries = _run_record(), _manifest_entries()
    record["provenance"]["eval_mode"] = "name_ablation"
    _json_doc, md = build_reports(record, entries)
    assert "name_ablation" in md
    assert "Name-ablation leak check" in md
    assert "Quality axes" in md


def test_reports_remain_deterministic_with_new_sections():
    record, entries = _run_record(), _manifest_entries()
    record["items"][0]["describe"]["alt_text_long"] = "Alice Example by a pool. Sunlight everywhere."
    json_a, md_a = build_reports(record, entries)
    json_b, md_b = build_reports(record, entries)
    assert json_a == json_b
    assert md_a == md_b


# --- ALTQ-1 review-fix regressions (round r07140ddf) ---


def test_ablation_item_without_stamp_becomes_failure_not_leak():  # A-03/B-03
    record, entries = _run_record(), _manifest_entries()
    record["provenance"]["eval_mode"] = "name_ablation"
    record["items"][0]["describe"]["ablated_names"] = ["Alice Example"]
    # item 2 carries NO ablated_names stamp -> was never transformed at fetch
    scored = score_run_record(record, entries)
    failed = [f for f in scored["failures"] if f["media_id"] == 2]
    assert failed and "ablated_names stamp" in failed[0]["error"]
    assert scored["ablation"]["eligible_images"] == 1  # only the stamped item


def test_distractor_taken_via_stamp_survives_manifest_drift():  # A-02/B-04
    record, entries = _run_record(), _manifest_entries()
    record["provenance"]["eval_mode"] = "context_distractor"
    # Fetch-time manifest had "Mallory Trap" in easy_wrong; score-time manifest
    # drifted and no longer lists her. The stamp alone must still gate.
    entries[0]["easy_wrong"] = []
    record["items"][0]["describe"]["injected_distractor"] = "Mallory Trap"
    record["items"][0]["describe"]["alt_text_draft"] = "Alice Example and Mallory Trap relax by a pool."
    scored = score_run_record(record, entries)
    assert scored["distractor"]["taken_images"] == 1
    row = next(r for r in scored["per_image"] if r["media_id"] == 1)
    assert row["gated_score"] == 0.0


def test_distractor_taken_on_long_surface_counts():  # B-08
    record, entries = _run_record(), _manifest_entries()
    record["provenance"]["eval_mode"] = "context_distractor"
    entries[0]["easy_wrong"] = ["Mallory Trap"]
    record["items"][0]["describe"]["injected_distractor"] = "Mallory Trap"
    record["items"][0]["describe"]["alt_text_long"] = "Alice Example relaxes by a pool. Mallory Trap reads nearby."
    scored = score_run_record(record, entries)
    assert scored["distractor"]["taken_images"] == 1


def test_manifest_roster_widens_hallucination_gate():  # A-01/B-07
    record, entries = _run_record(), _manifest_entries()
    record["items"][0]["describe"]["alt_text_draft"] = "Alice Example and Zed Zenith relax by a pool."
    unwidened = score_run_record(record, entries)
    row = next(r for r in unwidened["per_image"] if r["media_id"] == 1)
    assert row["hallucinated_names"] == []  # Zed unknown to entry rubrics
    widened = score_run_record(record, entries, manifest_roster=["Zed Zenith"])
    row = next(r for r in widened["per_image"] if r["media_id"] == 1)
    assert row["hallucinated_names"] == ["Zed Zenith"]
    assert row["gated_score"] == 0.0


def test_ablation_gate_zeroes_leak_on_recognition_disabled_row():  # A-04
    record, entries = _run_record(), _manifest_entries()
    record["provenance"]["eval_mode"] = "name_ablation"
    entries[0]["policy"] = {"recognition_enabled": False}
    record["items"][0]["describe"]["ablated_names"] = ["Alice Example"]
    record["items"][1]["describe"]["ablated_names"] = []
    scored = score_run_record(record, entries)
    row = next(r for r in scored["per_image"] if r["media_id"] == 1)
    assert row["gated_score"] == 0.0  # leaked name gates even though ineligible
    assert scored["ablation"]["leak_images"] == 1


# --- VLM-6 S1: audience-aware public vs local report split --------------------

_LOCAL_PATH = "localwp/uploads/jane-doe-birthday.jpg"
_LOCAL_NAME = "Jane Doe Private"
_PUBLIC_PATH = "celebs01/obama-podium.jpg"
_PUBLIC_NAME = "Barack Obama"


def _audience_fixtures() -> tuple[dict, list[dict]]:
    """One publishable celeb + one local-only personal photo (wrong-name risk)."""
    record = {
        "schema": "acx-eval/v1",
        "kind": "run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "base_url": "https://api.example.com",
            "head_sha": "0" * 40,
            "started_at": "2026-07-06T00:00:00Z",
        },
        "items": [
            {
                "media_id": 10,
                "path": _PUBLIC_PATH,
                "describe": {
                    "alt_text_draft": f"{_PUBLIC_NAME} at a podium.",
                    "visual_facts": {"objects": ["podium"]},
                    "adapter": "seeded",
                    "model_id": "seeded-fixtures",
                    "model_version": "1",
                    "cached": False,
                },
                "identities": [_PUBLIC_NAME],
                "face_count": 1,
                "error": None,
            },
            {
                "media_id": 20,
                "path": _LOCAL_PATH,
                "describe": {
                    "alt_text_draft": f"{_LOCAL_NAME} at a party.",
                    "visual_facts": {"objects": ["cake"]},
                    "adapter": "seeded",
                    "model_id": "seeded-fixtures",
                    "model_version": "1",
                    "cached": False,
                },
                # Wrong name asserted — must never leak into a public report.
                "identities": ["Wrong Celebrity"],
                "face_count": 1,
                "error": None,
            },
        ],
    }
    entries = [
        {
            "path": _PUBLIC_PATH,
            "media_id": 10,
            "face_count": 1,
            "present_identities": [_PUBLIC_NAME],
            "must_right": [_PUBLIC_NAME],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "provenance": {
                "source": "celeb",
                "license": "public_domain",
                "publishable": True,
            },
        },
        {
            "path": _LOCAL_PATH,
            "media_id": 20,
            "face_count": 1,
            "present_identities": [_LOCAL_NAME],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "provenance": {
                "source": "localwp",
                "license": "consented",
                "publishable": False,
            },
        },
    ]
    return record, entries


def test_public_excludes_non_publishable_and_keeps_publishable():
    record, entries = _audience_fixtures()
    json_doc, _md = build_reports(record, entries, audience=Audience.PUBLIC)
    scored = json.loads(json_doc)
    media_ids = {p["media_id"] for p in scored["per_image"]}
    assert 10 in media_ids
    assert 20 not in media_ids
    assert scored["counts"]["total"] == 1  # only publishable items scored
    assert scored["counts"]["scored"] == 1


def test_public_fail_closed_missing_entry():
    record, entries = _audience_fixtures()
    record["items"].append(
        {
            "media_id": 999,
            "path": "ghost.jpg",
            "describe": {"alt_text_draft": "ghost", "visual_facts": {"objects": []}},
            "identities": [],
            "face_count": 0,
            "error": None,
        }
    )
    json_doc, _md = build_reports(record, entries, audience=Audience.PUBLIC)
    scored = json.loads(json_doc)
    assert all(p["media_id"] != 999 for p in scored["per_image"])
    assert scored["redaction"]["withheld_items"] == 2  # local + missing
    assert scored["redaction"]["total_items"] == 3


def test_public_fail_closed_missing_provenance():
    record, entries = _audience_fixtures()
    # Strip provenance from the public entry — fail-closed, not inferred publishable.
    del entries[0]["provenance"]
    json_doc, _md = build_reports(record, entries, audience=Audience.PUBLIC)
    scored = json.loads(json_doc)
    assert scored["per_image"] == []
    assert scored["redaction"] == {
        "audience": "public",
        "withheld_items": 2,
        "total_items": 2,
    }


def test_public_fail_closed_unparseable_provenance():
    record, entries = _audience_fixtures()
    entries[0]["provenance"] = {"source": "celeb"}  # missing required license
    json_doc, _md = build_reports(record, entries, audience=Audience.PUBLIC)
    scored = json.loads(json_doc)
    assert all(p["media_id"] != 10 for p in scored["per_image"])
    assert scored["redaction"]["withheld_items"] == 2


def test_public_redaction_counts():
    record, entries = _audience_fixtures()
    json_doc, md = build_reports(record, entries, audience=Audience.PUBLIC)
    scored = json.loads(json_doc)
    assert scored["redaction"] == {
        "audience": "public",
        "withheld_items": 1,
        "total_items": 2,
    }
    # Honest redaction must also surface in markdown (not silent drop).
    assert "withheld" in md.lower()
    assert "1" in md and "2" in md


def test_public_serialized_output_leaks_no_local_path_or_name():
    record, entries = _audience_fixtures()
    json_doc, md = build_reports(record, entries, audience=Audience.PUBLIC)
    for blob in (json_doc, md):
        assert _LOCAL_PATH not in blob
        assert _LOCAL_NAME not in blob
        assert "Wrong Celebrity" not in blob  # wrong_names pair from local item
    # Publishable identity still present.
    assert _PUBLIC_NAME in json_doc
    assert _PUBLIC_PATH in json_doc or "obama" in json_doc.lower()


def test_local_output_unchanged_byte_identical_to_default():
    """LOCAL is the default and must stay byte-identical to pre-audience behaviour."""
    record, entries = _run_record(), _manifest_entries()
    default_json, default_md = build_reports(record, entries)
    local_json, local_md = build_reports(record, entries, audience=Audience.LOCAL)
    assert default_json == local_json
    assert default_md == local_md
    assert "redaction" not in json.loads(local_json)


def test_local_still_includes_non_publishable():
    record, entries = _audience_fixtures()
    json_doc, md = build_reports(record, entries, audience=Audience.LOCAL)
    scored = json.loads(json_doc)
    media_ids = {p["media_id"] for p in scored["per_image"]}
    assert media_ids == {10, 20}
    assert _LOCAL_PATH in json_doc
    assert _LOCAL_PATH in md
    assert "redaction" not in scored


def test_public_reports_deterministic():
    record, entries = _audience_fixtures()
    a_json, a_md = build_reports(record, entries, audience=Audience.PUBLIC)
    b_json, b_md = build_reports(record, entries, audience=Audience.PUBLIC)
    assert a_json == b_json
    assert a_md == b_md


# --- FIR-5 S5: face score path, floors, redaction, divergence, determinism ---


def _unit(vec: list[float]) -> list[float]:
    a = np.asarray(vec, dtype=np.float64)
    n = float(np.linalg.norm(a))
    assert n > 0
    return (a / n).tolist()


def _face_det(bbox_px: list[float], emb: list[float], *, det_score: float = 0.95) -> dict:
    return {
        "bbox_px": bbox_px,
        "landmarks_px": [[0.0, 0.0]] * 5,
        "embedding": _unit(emb),
        "det_score": det_score,
    }


def _gt_box(x: float, y: float, w: float, h: float, name: str | None) -> dict:
    return {"x": x, "y": y, "w": w, "h": h, "name": name, "source": "iptc"}


def _face_fixture_corpus() -> tuple[dict, dict]:
    """Full unfiltered corpus: celebs01 Alice (2 faces) + LOCALWP stranger.

    Alice has ≥2 matched faces so she is recall-eligible; stranger is private.
    Embeddings: Alice faces near [1,0,...]; stranger near [0,1,...] so open-set
    reject is natural at typical τ.
    """
    dim = 8
    alice_a = _unit([1.0] + [0.0] * (dim - 1))
    alice_b = _unit([0.98, 0.1] + [0.0] * (dim - 2))
    stranger = _unit([0.0, 1.0] + [0.0] * (dim - 2))

    # image 100x100; GT centre boxes that match the pixel bboxes via IoU
    # det bbox_px [x,y,w,h] = [20,20,40,40] → centre (0.4, 0.4) size (0.4, 0.4) on 100x100
    face_run = {
        "schema": "acx-eval/v1",
        "kind": DocKind.FACE_RUN_RECORD.value,
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
                "faces": [_face_det([20.0, 20.0, 40.0, 40.0], alice_a)],
            },
            {
                "media_id": 2,
                "path": "celebs01/alice-b.jpg",
                "model_id": "ort-yunet-sface",
                "embedding_dim": dim,
                "image_size": [100, 100],
                "faces": [_face_det([20.0, 20.0, 40.0, 40.0], alice_b)],
            },
            {
                "media_id": 3,
                "path": "localwp/uploads/stranger-party.jpg",
                "model_id": "ort-yunet-sface",
                "embedding_dim": dim,
                "image_size": [100, 100],
                "faces": [_face_det([20.0, 20.0, 40.0, 40.0], stranger)],
            },
        ],
    }
    manifest = {
        "annotation_mode": "exhaustive",
        "roster": ["Alice Example"],
        "roster_cohorts": {"Alice Example": "cohort_a"},
        "entries": [
            {
                "path": "celebs01/alice-a.jpg",
                "media_id": 1,
                "face_count": 1,
                "present_identities": ["Alice Example"],
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [_gt_box(0.4, 0.4, 0.4, 0.4, "Alice Example")],
                "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
                "demographic_cohort": "cohort_a",
            },
            {
                "path": "celebs01/alice-b.jpg",
                "media_id": 2,
                "face_count": 1,
                "present_identities": ["Alice Example"],
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [_gt_box(0.4, 0.4, 0.4, 0.4, "Alice Example")],
                "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
                "demographic_cohort": "cohort_a",
            },
            {
                "path": "localwp/uploads/stranger-party.jpg",
                "media_id": 3,
                "face_count": 1,
                "present_identities": [],
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [_gt_box(0.4, 0.4, 0.4, 0.4, None)],  # stranger
                "provenance": {"source": "localwp", "license": "consented", "publishable": False},
            },
        ],
    }
    return face_run, manifest


def test_score_face_run_record_full_corpus_and_floor_gated_rollup():
    face_run, manifest = _face_fixture_corpus()
    scored = score_face_run_record(face_run, manifest, score_manifest_sha256="s" * 64)
    assert scored["report_kind"] == "face_bakeoff"
    # Full corpus: private stranger is scored (matched)
    assert scored["counts"]["matched_faces"] == 3
    assert scored["counts"]["stranger_matched"] == 1
    # Under-floor → DIRECTIONAL
    hl = scored["slices"]["headline_identification"]
    assert hl["directional"] is True
    assert hl["n_recall_eligible"] < HEADLINE_ID_RECALL_ELIGIBLE_FLOOR
    assert DIRECTIONAL_LABEL in hl["status"]
    unk = scored["slices"]["unknown_rejection"]
    assert unk["n"] == 1  # private stranger counted
    assert unk["directional"] is True
    # Gate proposal EXCLUDES every DIRECTIONAL slice (SC4)
    gp = scored["gate_proposal"]
    assert gp["proposed_slices"] == {} or all(
        not (scored["slices"].get(k) or {}).get("directional", True)
        for k in gp["proposed_slices"]
    )
    for name in ("headline_identification", "unknown_rejection", "clustering"):
        assert name in gp["excluded_directional"] or any(
            name in e for e in gp["excluded_directional"]
        )
    # Coupling flag + p95 deferral + scope amendments + protocol disclosures present
    assert "identification_recall" in gp["identification_detection_coupling"]
    assert "detection_recall" in gp["identification_detection_coupling"]
    assert "detection_recall_coupling_flag" in gp["identification_detection_coupling"]
    assert "FIR-6-owned" in gp["p95_scan_latency"]
    assert any("FIR-5a" in a for a in gp["scope_amendments_for_operator_ack"])
    assert any("Wilson" in a for a in gp["scope_amendments_for_operator_ack"])
    disclosures = scored.get("protocol_disclosures") or gp.get("protocol_disclosures") or []
    assert any("mean_prototype" in d for d in disclosures)
    assert any("ambiguity" in d or "margin" in d for d in disclosures)
    assert any("impostor" in d for d in disclosures)
    assert any("subject-disjoint" in d or "CAL-07" in d for d in disclosures)
    assert any("solid seeded rectangles" in d for d in disclosures)
    assert any("YuNet" in d and "landmark cache" in d for d in disclosures)
    assert any("outcome-independent" in d for d in disclosures)
    # FIR5V11-06: canon pin + release-surface label + sampling frames
    assert scored["provenance"]["canon_version"] == FACE_BAKEOFF_CANON_VERSION
    assert scored["provenance"]["protocol_id"]
    assert "headline_identification" in scored["provenance"]["sampling_frames"]
    assert gp["release_surface"] == GATE_PROPOSAL_RELEASE_SURFACE
    assert gp["canon_version"] == FACE_BAKEOFF_CANON_VERSION
    # AUDIT: every published rate carries sampling_frame + denominators
    assert hl["sampling_frame"]
    assert "precision_denominator" in hl and "recall_denominator" in hl
    assert "error_target" in hl
    assert unk["sampling_frame"] and "error_target" in unk
    assert "rate_numerator" in unk and "rate_denominator" in unk
    # Nested lists sorted (wrong_names already sorted; decisions sorted)
    decisions = scored["decisions"]
    keys = [(d["true_name"] or "\uffff", d["media_id"], d["box_index"]) for d in decisions]
    assert keys == sorted(keys)


def test_zero_box_corpus_all_directional():
    face_run = {
        "schema": "acx-eval/v1",
        "kind": DocKind.FACE_RUN_RECORD.value,
        "provenance": {"manifest_sha256": "m" * 64, "head_sha": "0" * 40, "leg": "candidate"},
        "items": [
            {
                "media_id": 1,
                "path": "x.jpg",
                "model_id": "m",
                "embedding_dim": 4,
                "image_size": [10, 10],
                "faces": [],
            }
        ],
    }
    manifest = {
        "annotation_mode": "exhaustive",
        "roster": [],
        "roster_cohorts": {},
        "entries": [
            {
                "path": "x.jpg",
                "media_id": 1,
                "face_count": 0,
                "present_identities": [],
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [],
            }
        ],
    }
    scored = score_face_run_record(face_run, manifest)
    assert scored["provenance"]["zero_box_corpus"] is True
    assert scored["slices"]["headline_identification"]["directional"] is True
    assert scored["slices"]["unknown_rejection"]["directional"] is True
    assert scored["slices"]["clustering"]["directional"] is True
    assert scored["gate_proposal"]["proposed_slices"] == {}


def test_below_floor_never_in_gate_proposal():
    face_run, manifest = _face_fixture_corpus()
    scored = score_face_run_record(face_run, manifest)
    for name, block in scored["gate_proposal"]["proposed_slices"].items():
        assert block.get("directional") is not True, name
        assert DIRECTIONAL_LABEL not in str(block.get("status", ""))


def _two_identity_split_tau_fixture() -> tuple[dict, dict, list[float]]:
    """Corpus whose per-fold τ_k provably differ from τ_op (FIR5RR-01 report frame).

    Alice: near-identical pair (axes 0/1) → her fold's fit (Bob-only) selects
    τ=0.40. Bob: spread pair with cos(b1,b2)=0.62 (axes 2/3) → his fold's fit
    (Alice-only) selects τ=0.55. τ_op = median(0.40, 0.55) = 0.475.
    Returns (face_run, manifest, bob_gallery_proto) for twin construction.
    """
    dim = 8
    s = float(np.sqrt(1.0 - 0.81))
    a1 = _unit([1.0, 0.0] + [0.0] * (dim - 2))
    a2 = _unit([0.98, 0.1] + [0.0] * (dim - 2))
    b1 = _unit([0.0, 0.0, 0.9, s] + [0.0] * (dim - 4))
    b2 = _unit([0.0, 0.0, 0.9, -s] + [0.0] * (dim - 4))
    items = []
    entries = []
    for mid, emb, name in ((1, a1, "Alice Q"), (2, a2, "Alice Q"), (3, b1, "Bob Z"), (4, b2, "Bob Z")):
        items.append(
            {
                "media_id": mid,
                "path": f"celebs01/{name.split()[0].lower()}-{mid}.jpg",
                "model_id": "ort-yunet-sface",
                "embedding_dim": dim,
                "image_size": [100, 100],
                "faces": [_face_det([20.0, 20.0, 40.0, 40.0], emb)],
            }
        )
        entries.append(
            {
                "path": f"celebs01/{name.split()[0].lower()}-{mid}.jpg",
                "media_id": mid,
                "face_count": 1,
                "present_identities": [name],
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [_gt_box(0.4, 0.4, 0.4, 0.4, name)],
                "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
            }
        )
    face_run = {
        "schema": "acx-eval/v1",
        "kind": DocKind.FACE_RUN_RECORD.value,
        "provenance": {
            "manifest_sha256": "m" * 64,
            "head_sha": "0" * 40,
            "started_at": "2026-07-18T00:00:00Z",
            "leg": "candidate",
            "model_id": "ort-yunet-sface",
            "embedding_dim": dim,
        },
        "items": items,
    }
    manifest = {
        "annotation_mode": "exhaustive",
        "roster": ["Alice Q", "Bob Z"],
        "roster_cohorts": {},
        "entries": entries,
    }
    return face_run, manifest, b2


def test_occlusion_twin_scored_at_source_identity_heldout_tau_in_report():
    """FIR5RR-01/02 report-level discriminator: a Bob twin with s_max=0.5 sits
    BELOW Bob's own held-out fold τ_k (0.55) but ABOVE τ_op (0.475) and above
    Alice's τ_k (0.40). The scored report must count it INCORRECT. Goes red if
    the scorer regresses to τ_op — or drops τ propagation entirely (closed-set
    argmax would accept it as correct)."""
    face_run, manifest, b2 = _two_identity_split_tau_fixture()
    b2u = np.asarray(b2, dtype=np.float64)
    e5 = np.zeros(len(b2))
    e5[5] = 1.0
    twin = (0.5 * b2u + float(np.sqrt(0.75)) * e5).tolist()
    scored = score_face_run_record(
        face_run,
        manifest,
        occlusion_pairs_by_tag={
            "masked": [
                {
                    "media_id": 3,
                    "box_index": 0,
                    "true_name": "Bob Z",
                    "kind": "masked",
                    "embedding": twin,
                }
            ]
        },
    )
    # Fixture preconditions: fold taus split around tau_op.
    assert sorted(scored["tau"]["tau_k"]) == pytest.approx([0.40, 0.55])
    assert scored["tau"]["tau_op"] == pytest.approx(0.475)
    bob_tau = next(
        d["tau_k"] for d in scored["decisions"] if d["true_name"] == "Bob Z"
    )
    assert bob_tau == pytest.approx(0.55)  # Bob's held-out fold τ_k ≠ τ_op
    synth = scored["slices"]["occlusion"]["masked"]["synthetic"]
    assert synth["n_eligible"] == 1
    # s_max=0.5 < Bob's own τ_k=0.55 → reject → INCORRECT. A τ_op (0.475)
    # regression — or a dropped-τ closed-set argmax — would score it correct.
    assert synth["n_correct"] == 0
    assert synth["accuracy"] == 0.0
    # FIR5RR-04: subject-count clamp disclosed (requested K=5 → effective 2).
    assert scored["tau"]["requested_k"] == 5
    assert scored["tau"]["effective_k"] == 2
    assert "clamped" in str(scored["tau"]["k_clamp_disclosure"])
    assert scored["provenance"]["k_folds"] == {
        "requested": 5,
        "effective": 2,
        "clamped": True,
    }
    # FIR5RR-07: fully fitted here.
    assert scored["tau"]["tau_fit_status"] == "fitted"
    assert scored["provenance"]["tau_fit_status"] == "fitted"


def test_headline_association_counts_scoped_and_fail_closed():
    """FIR5RR-06: headline missed_gt counts NAMED unmatched GT only; unmatched
    detections count only on probe-contributing media; celebs01 media absent
    from association contribute manifest named-face counts with a provenance
    note — never a silent continue."""
    face_run, manifest = _face_fixture_corpus()
    dim = 8
    # (a) celebs01 media 6: GT stranger box, no detection → unmatched GT with
    #     name=None must NOT count toward the NAMED headline miss frame.
    face_run["items"].append(
        {
            "media_id": 6,
            "path": "celebs01/stranger-unmatched.jpg",
            "model_id": "ort-yunet-sface",
            "embedding_dim": dim,
            "image_size": [100, 100],
            "faces": [],
        }
    )
    manifest["entries"].append(
        {
            "path": "celebs01/stranger-unmatched.jpg",
            "media_id": 6,
            "face_count": 1,
            "present_identities": [],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [_gt_box(0.4, 0.4, 0.4, 0.4, None)],
            "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
        }
    )
    # (b) celebs01 media 7: a detection with NO GT (unmatched detection) on an
    #     image contributing no headline probe → excluded from the frame count.
    face_run["items"].append(
        {
            "media_id": 7,
            "path": "celebs01/false-det.jpg",
            "model_id": "ort-yunet-sface",
            "embedding_dim": dim,
            "image_size": [100, 100],
            "faces": [_face_det([20.0, 20.0, 40.0, 40.0], _unit([0.3, 0.3, 0.9] + [0.0] * (dim - 3)))],
        }
    )
    manifest["entries"].append(
        {
            "path": "celebs01/false-det.jpg",
            "media_id": 7,
            "face_count": 0,
            "present_identities": [],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [],
            "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
        }
    )
    # (c) celebs01 media 8: TWO manifest named faces, but the run-record item
    #     ERRORED → absent from association → both named faces count as misses
    #     with an explicit provenance note.
    face_run["items"].append(
        {
            "media_id": 8,
            "path": "celebs01/errored.jpg",
            "model_id": "ort-yunet-sface",
            "embedding_dim": dim,
            "image_size": [100, 100],
            "faces": [],
            "error": "remote timeout",
        }
    )
    manifest["entries"].append(
        {
            "path": "celebs01/errored.jpg",
            "media_id": 8,
            "face_count": 2,
            "present_identities": ["Alice Example", "Cara Example"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [
                _gt_box(0.25, 0.4, 0.3, 0.3, "Alice Example"),
                _gt_box(0.7, 0.4, 0.3, 0.3, "Cara Example"),
            ],
            "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
        }
    )
    scored = score_face_run_record(face_run, manifest)
    hl = scored["slices"]["headline_identification"]
    # NAMED-miss frame: 2 from the errored media only; the stranger unmatched
    # GT (media 6) is excluded. Old behaviour: 1 (stranger) + silent skip of 8.
    assert hl["missed_gt"] == 2
    # Unmatched detection on media 7 (no headline probe there) excluded.
    assert hl["unmatched_detections"] == 0
    notes = hl["association_provenance_notes"]
    assert len(notes) == 1
    assert "media_id 8" in notes[0] and "2 manifest named face" in notes[0]
    # The error item is still a failure row (excluded-from-frame is documented
    # in the headline sampling frame string).
    assert any(f["media_id"] == 8 for f in scored["failures"])
    assert "error-item media excluded" in hl["sampling_frame"]


def test_tau_unfitted_forces_all_tau_slices_directional():
    """FIR5RR-07: single-subject corpus → mid-grid τ → every τ-dependent slice
    is DIRECTIONAL with an explicit tau_fit_status reason."""
    face_run, manifest = _face_fixture_corpus()
    # Keep only the two Alice items → single subject (no stranger).
    face_run["items"] = [i for i in face_run["items"] if i["media_id"] in (1, 2)]
    manifest["entries"] = [e for e in manifest["entries"] if e["media_id"] in (1, 2)]
    scored = score_face_run_record(face_run, manifest)
    assert scored["tau"]["tau_fit_status"] == "mid_grid_unfitted"
    assert scored["provenance"]["tau_fit_status"] == "mid_grid_unfitted"
    reason = "tau_fit_status=mid_grid_unfitted"
    for name in ("headline_identification", "unknown_rejection", "clustering"):
        block = scored["slices"][name]
        assert block["directional"] is True, name
        assert any(reason in r for r in block["reasons"]), name
    for tag, block in scored["slices"]["occlusion"].items():
        synth = block["synthetic"]
        assert synth["directional"] is True, tag
        assert any(reason in r for r in synth["reasons"]), tag
    assert scored["gate_proposal"]["proposed_slices"] == {}


def test_demographic_cohorts_inherit_coupling_and_new_disclosures_present():
    """FIR5RR-05/09/13/15: per-cohort miss fields are null (not fabricated 0),
    coupling inherited from full-corpus totals; new protocol disclosures ride
    every scored face artifact."""
    face_run, manifest = _face_fixture_corpus()
    scored = score_face_run_record(face_run, manifest)
    parent_coupling = scored["slices"]["full_corpus_identification"][
        "detection_recall_coupling_flag"
    ]
    for cohort, block in scored["slices"]["demographic"]["by_cohort"].items():
        assert block["missed_gt"] is None, cohort
        assert block["unmatched_detections"] is None, cohort
        assert block["detection_recall_coupling_flag"] == parent_coupling, cohort
        assert "not attributed per cohort" in block["sampling_frame"]
    disclosures = scored["protocol_disclosures"]
    assert any("stranger" in d and "FIR-6" in d and "unmeasured" in d for d in disclosures)  # RR-09
    assert any("not independent" in d and "unknown-rejection" in d for d in disclosures)  # RR-13
    assert any("cardinality" in d for d in disclosures)  # RR-15
    # RR-11: leg-asymmetry disclosure single-sourced from landmark_cache.
    from scripts.eval_harness.landmark_cache import (
        LANDMARK_CACHE_LEG_ASYMMETRY_DISCLOSURE,
    )
    from scripts.eval_harness.synthetic_occlusion import (
        SYNTHETIC_OCCLUSION_PROTOCOL_DISCLOSURES,
    )

    assert LANDMARK_CACHE_LEG_ASYMMETRY_DISCLOSURE in SYNTHETIC_OCCLUSION_PROTOCOL_DISCLOSURES
    assert LANDMARK_CACHE_LEG_ASYMMETRY_DISCLOSURE in disclosures
    # FIR5CR-06: fold protocol disclosure single-sourced from face_assignment.
    from scripts.eval_harness.face_assignment import (
        FOLD_MEDIA_CORESIDENCY_DISCLOSURE,
    )

    assert FOLD_MEDIA_CORESIDENCY_DISCLOSURE in disclosures
    assert any("not media-disjoint" in d for d in disclosures)
    # RR-13: unknown-rejection slice error_target carries the dependence note.
    assert "independent" in scored["slices"]["unknown_rejection"]["error_target"]


def test_tau_by_identity_disagreeing_fold_taus_raise():
    """FIR5CR-02: one identity with two different held-out tau_k values means the
    subject-disjoint fold split regressed — the map builder must raise."""
    from types import SimpleNamespace

    from scripts.eval_harness.report import _tau_by_identity_from_decisions

    good = [
        SimpleNamespace(true_name="Alice", tau_k=0.6),
        SimpleNamespace(true_name="Alice", tau_k=0.6),
        SimpleNamespace(true_name="Bob", tau_k=0.4),
        SimpleNamespace(true_name=None, tau_k=0.9),  # strangers ignored
    ]
    assert _tau_by_identity_from_decisions(good) == {"Alice": 0.6, "Bob": 0.4}
    bad = [
        SimpleNamespace(true_name="Alice", tau_k=0.6),
        SimpleNamespace(true_name="Alice", tau_k=0.7),
    ]
    with pytest.raises(ReportError, match="fold-split regression"):
        _tau_by_identity_from_decisions(bad)


def test_association_counts_out_of_range_gt_index_noted_and_counted():
    """FIR5CR-05: gi >= len(boxes) is counted conservatively as a miss with a
    provenance note — never a silent skip."""
    from types import SimpleNamespace

    from scripts.eval_harness.report import _association_counts_for_media

    assoc = SimpleNamespace(unmatched_gt=[0, 5], unmatched_detections=[])
    assignment = SimpleNamespace(association_by_media={1: assoc})
    gt_by_media = {1: [{"name": "Alice"}]}  # index 5 is out of range
    missed, unmatched, notes = _association_counts_for_media(
        assignment,
        {1},
        gt_by_media=gt_by_media,
        probe_media_ids={1},
    )
    assert missed == 2  # named box 0 + conservative out-of-range index 5
    assert unmatched == 0
    assert any("out of range" in n and "index 5" in n for n in notes)


def test_occlusion_marked_run_record_item_rejected():
    """FIR5RR-08: an occlusion-marked run-record item must fail closed."""
    face_run, manifest = _face_fixture_corpus()
    face_run["items"][0]["occluded"] = True
    with pytest.raises(ReportError, match="occlusion marker"):
        score_face_run_record(face_run, manifest)
    face_run2, manifest2 = _face_fixture_corpus()
    face_run2["items"][1]["twin_of"] = {"media_id": 9, "box_index": 0}
    with pytest.raises(ReportError, match="occlusion marker"):
        score_face_run_record(face_run2, manifest2)


def test_publishability_private_stranger_scored_then_redacted():
    """LOCALWP stranger is SCORED into unknown-rejection yet ABSENT from redacted report."""
    face_run, manifest = _face_fixture_corpus()
    scored = score_face_run_record(face_run, manifest)
    unk = scored["slices"]["unknown_rejection"]
    assert unk["n"] >= 1
    assert any(
        d["true_name"] is None and "localwp" in d["path"] for d in scored["decisions"]
    )
    redacted = redact_face_report_for_public(scored)
    # Aggregate rates preserved
    assert redacted["slices"]["unknown_rejection"]["n"] == unk["n"]
    assert redacted["slices"]["unknown_rejection"]["rate"] == unk["rate"]
    # AUDIT-09/12: denominators retained after stripping decision rows
    preserved = redacted["redaction"]["preserved_aggregate_denominators"]
    assert preserved["unknown_rejection"]["rate_denominator"] == unk["n"]
    assert preserved["headline_identification"]["recall_denominator"] is not None
    # Private detail absent
    blob = json.dumps(redacted)
    assert "localwp/uploads/stranger-party.jpg" not in blob
    assert redacted["redaction"]["mode"] == "post_score_redact_face_report_for_public"
    assert redacted["redaction"]["stripped_decision_rows"] >= 1
    # Not the pre-score Audience.PUBLIC path
    assert "pre-score" in redacted["redaction"]["note"] or "Distinct" in redacted["redaction"]["note"]


def test_publishability_named_private_source_redacted():
    """A NAMED private-source person (publishable=False) whose path lacks the
    localwp/operator/uploads tokens must be ABSENT from the redacted public
    artifact — decisions, clustering.labels, wrong_names — while aggregate rates
    are preserved. Guards the path-substring fail-open (FIR5-S5-BR-01): redaction
    must key on manifest Provenance.is_publishable, not on path spelling.
    """
    face_run, manifest = _face_fixture_corpus()
    dim = 8
    jane_a = _unit([0.0, 0.0, 1.0] + [0.0] * (dim - 3))
    jane_b = _unit([0.0, 0.05, 0.99] + [0.0] * (dim - 3))
    # Two named faces from an OPERATOR source at a path WITHOUT any private token.
    for mid, emb, path in (
        (4, jane_a, "corpus/private/jane-01.jpg"),
        (5, jane_b, "corpus/private/jane-02.jpg"),
    ):
        face_run["items"].append(
            {
                "media_id": mid,
                "path": path,
                "model_id": "ort-yunet-sface",
                "embedding_dim": dim,
                "image_size": [100, 100],
                "faces": [_face_det([20.0, 20.0, 40.0, 40.0], emb)],
            }
        )
        manifest["entries"].append(
            {
                "path": path,
                "media_id": mid,
                "face_count": 1,
                "present_identities": ["Jane Roster"],
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [_gt_box(0.4, 0.4, 0.4, 0.4, "Jane Roster")],
                "provenance": {"source": "operator", "license": "consented", "publishable": False},
            }
        )
    manifest["roster"].append("Jane Roster")

    scored = score_face_run_record(face_run, manifest)
    # Jane IS scored into the full-corpus report — her named decision rows are the
    # fail-open leak vector the path heuristic missed (name present pre-redaction).
    jane_rows = [d for d in scored["decisions"] if d.get("true_name") == "Jane Roster"]
    assert jane_rows, "named private person must be scored into the full corpus"
    assert all(d["publishable"] is False for d in jane_rows)
    # The fixture path is the fail-open vector: no substring the old heuristic keyed on.
    assert not any(
        tok in d["path"] for d in jane_rows for tok in ("operator", "localwp", "uploads")
    )
    assert "Jane Roster" in json.dumps(scored)  # present somewhere pre-redaction

    redacted = redact_face_report_for_public(scored)
    blob = json.dumps(redacted)
    # PRIMARY: the named private individual is nowhere in the public artifact.
    assert "Jane Roster" not in blob
    assert "corpus/private/jane-01.jpg" not in blob
    assert "corpus/private/jane-02.jpg" not in blob
    # Publishable celeb detail survives; every surviving row is publishable + named.
    assert redacted["decisions"]
    assert all(
        d.get("publishable") is True and d.get("true_name") is not None
        for d in redacted["decisions"]
    )
    # Per-face clustering labels stripped (aggregate-only public artifact).
    assert redacted["slices"]["clustering"]["labels"] == []
    # Aggregate rates preserved (unknown-rejection count/rate unchanged by redaction).
    assert redacted["slices"]["unknown_rejection"]["n"] == scored["slices"]["unknown_rejection"]["n"]
    assert (
        redacted["slices"]["unknown_rejection"]["rate"]
        == scored["slices"]["unknown_rejection"]["rate"]
    )


def test_sort_nested_lists_preserves_fixed_schema_row_order():
    """§G determinism (FIR5-S5-BR-02): the collection of rows is canonicalized for
    order-independence, but the positional internals of a fixed-schema row (e.g.
    a ``wrong_names`` ``[media_id, box_index, true, pred]`` tuple) must NOT be
    reordered — the confirmed corruption was element-wise sorting inside rows.
    """
    from scripts.eval_harness.report import _sort_nested_lists

    # Two fixed-schema rows whose element order is positionally meaningful and would
    # be corrupted by an element-wise sort ("Zed" would sort after 0/5/"Al").
    rows = [[5, 0, "Zed", "Al"], [2, 1, "Bo", "Cy"]]
    out = _sort_nested_lists({"wrong_names": rows})
    # Row internals preserved (NOT reordered within each row)...
    assert [5, 0, "Zed", "Al"] in out["wrong_names"]
    assert [2, 1, "Bo", "Cy"] in out["wrong_names"]
    for r in out["wrong_names"]:
        assert r in ([5, 0, "Zed", "Al"], [2, 1, "Bo", "Cy"])

    # ...while the COLLECTION of rows (dicts) is still canonicalized for determinism.
    assert _sort_nested_lists([{"m": 2}, {"m": 1}]) == [{"m": 1}, {"m": 2}]


def test_synthetic_real_divergence_demotion_and_qualitative():
    # d > threshold → auto_demote
    # a_r=0.5, n=100 → wilson half-width small; d=0.5 > max(wilson, 0.20)
    d1 = synthetic_real_divergence(0.0, 0.5, n_real=100, real_floor=90)
    assert d1["d"] == pytest.approx(0.5)
    assert d1["threshold"] is not None and d1["threshold"] >= 0.20
    assert d1["auto_demote"] is True
    # real n < floor → no auto-demote (qualitative only)
    d2 = synthetic_real_divergence(0.0, 0.5, n_real=10, real_floor=90)
    assert d2["auto_demote"] is False
    assert d2["reason"] == "real_n_below_floor_qualitative_only"
    assert d2["threshold"] is None
    # within threshold → no demote
    d3 = synthetic_real_divergence(0.55, 0.50, n_real=200, real_floor=90)
    assert d3["auto_demote"] is False
    assert wilson_half_width(0.5, 100) > 0


def test_face_score_check_determinism_cross_process(tmp_path):
    face_run, manifest = _face_fixture_corpus()
    # Write record + a minimal loadable manifest JSON for subprocess path via pure score
    a = score_face_run_record(face_run, manifest, score_manifest_sha256="s" * 64)
    b = score_face_run_record(face_run, manifest, score_manifest_sha256="s" * 64)
    assert a == b
    ja, ma = build_face_reports(face_run, manifest, score_manifest_sha256="s" * 64)
    jb, mb = build_face_reports(face_run, manifest, score_manifest_sha256="s" * 64)
    assert ja == jb and ma == mb

    # Cross-process with varied PYTHONHASHSEED
    rec_path = tmp_path / "face-run.json"
    rec_path.write_text(json.dumps(face_run))
    # Use in-process score as baseline; subprocess imports score_face_run_record with same dicts
    script = (
        "import json,sys; "
        "from scripts.eval_harness.report import score_face_run_record; "
        "rec=json.loads(open(sys.argv[1]).read()); "
        "man=json.loads(open(sys.argv[2]).read()); "
        "print(json.dumps(score_face_run_record(rec,man,score_manifest_sha256='s'*64),sort_keys=True))"
    )
    man_path = tmp_path / "man.json"
    man_path.write_text(json.dumps(manifest))
    baseline = json.dumps(a, sort_keys=True)
    service_root = Path(__file__).resolve().parents[2]  # apps/prototype-description-service
    for seed in ("0", "1", "42"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = str(service_root) + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run(
            [sys.executable, "-c", script, str(rec_path), str(man_path)],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(service_root),
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == baseline


def test_buffalo_non_promotion_no_512d_under_docs_tasks():
    """PROV-01: no *.json under docs/tasks/** has a 512D embedding array."""
    repo_root = Path(__file__).resolve().parents[4]
    docs_tasks = repo_root / "docs" / "tasks"
    if not docs_tasks.is_dir():
        pytest.skip("docs/tasks not present in this checkout")
    offenders = []
    for path in docs_tasks.rglob("*.json"):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue

        def _walk(obj, trail="", path=path):
            if isinstance(obj, dict):
                emb = obj.get("embedding")
                if isinstance(emb, list) and len(emb) == 512 and emb and isinstance(emb[0], (int, float)):
                    offenders.append(f"{path}:{trail}.embedding len=512")
                for k, v in obj.items():
                    _walk(v, f"{trail}.{k}")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    _walk(v, f"{trail}[{i}]")

        _walk(data)
    assert offenders == [], f"buffalo 512D embeddings promoted: {offenders[:5]}"


def test_score_face_rejects_caption_run_record():
    with pytest.raises(ReportError, match="face_run_record"):
        score_face_run_record(_run_record(), _manifest_entries())


# --- ALTQ-1 Slice 3: latency summary (additive) --------------------------------


def test_latency_summary_absent_without_timing_data_keeps_report_shape():
    """ADDITIVE ONLY: a record with no timing data produces no latency section
    (and hence a byte-identical report to the pre-latency scorer)."""
    record, entries = _run_record(), _manifest_entries()
    scored = score_run_record(record, entries)
    assert "latency" not in scored
    json_doc, md = build_reports(record, entries)
    assert "latency" not in json.loads(json_doc)
    assert "latency" not in md


def test_latency_summary_single_call_items_percentiles():
    items = [
        {"media_id": i, "describe": {"alt_text_draft": "x"}, "error": None, "latency_s": lat}
        for i, lat in enumerate([4.0, 1.0, 3.0, 2.0])
    ]
    assert _latency_summary(items) == {
        "images_timed": 4,
        "wall_clock_s": {"p50": 2.0, "p95": 4.0},  # nearest-rank on sorted values
        "model_calls": {"per_image_mean": 1.0, "total": 4},
    }


def test_latency_summary_sums_passes_and_counts_model_calls():
    def _two_pass_item(media_id: int, l1: float, l2: float) -> dict:
        return {
            "media_id": media_id,
            "describe": {
                "alt_text_draft": "x",
                "passes": [
                    {"pass": "describe_facts", "raw": "{}", "latency_s": l1},
                    {"pass": "ground_weave", "raw": "x", "latency_s": l2},
                ],
            },
            "error": None,
            "latency_s": l1 + l2 + 99.0,  # per-pass timing must win over the item field when present
        }

    summary = _latency_summary([_two_pass_item(1, 1.0, 2.0), _two_pass_item(2, 3.0, 4.0)])
    assert summary == {
        "images_timed": 2,
        "wall_clock_s": {"p50": 3.0, "p95": 7.0},
        "model_calls": {"per_image_mean": 2.0, "total": 4},
    }


def test_latency_summary_skips_error_and_untimed_items():
    items = [
        {"media_id": 1, "describe": None, "error": "boom", "latency_s": 5.0},
        {"media_id": 2, "describe": {"alt_text_draft": "x"}, "error": None},  # no latency field at all
        {"media_id": 3, "describe": {"alt_text_draft": "x"}, "error": None, "latency_s": None},
        {"media_id": 4, "describe": {"alt_text_draft": "x"}, "error": None, "latency_s": 2.5},
    ]
    summary = _latency_summary(items)
    assert summary["images_timed"] == 1
    assert summary["wall_clock_s"] == {"p50": 2.5, "p95": 2.5}
    assert _latency_summary(items[:3]) is None  # nothing timed at all => no section


def test_latency_section_and_markdown_line_render_when_timed():
    record, entries = _run_record(), _manifest_entries()
    record["items"][0]["latency_s"] = 3.2
    record["items"][1]["latency_s"] = 1.1
    json_doc, md = build_reports(record, entries)
    scored = json.loads(json_doc)
    assert scored["latency"] == {
        "images_timed": 2,
        "wall_clock_s": {"p50": 1.1, "p95": 3.2},
        "model_calls": {"per_image_mean": 1.0, "total": 2},
    }
    assert "- latency: per-image wall-clock p50 1.1s p95 3.2s (2 timed)" in md
    assert build_reports(record, entries) == build_reports(record, entries)  # determinism holds
