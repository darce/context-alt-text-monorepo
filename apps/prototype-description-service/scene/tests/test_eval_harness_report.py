"""VLM-2A Slice 3: report builder + scoring pipeline — deterministic, golden-file style."""

import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from scripts.eval_harness.face_metrics import named_box_name
from scripts.eval_harness.report import (
    CORPUS_TRAP_AFFECTS_DETECTION_FN,
    DIRECTIONAL_LABEL,
    FACE_BAKEOFF_CANON_VERSION,
    GATE_PROPOSAL_RELEASE_SURFACE,
    HEADLINE_ID_RECALL_ELIGIBLE_FLOOR,
    WRONG_NAME_RATE_FLOOR,
    Audience,
    ReportError,
    ScoreVerdict,
    _build_single_subject_cohort_by_media,
    _fixture_local_detection_caveat_line,
    _latency_summary,
    _markdown_face,
    build_face_reports,
    build_real_occlusion_pairs,
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
                "identities": [
                    {
                        "name": "Alice Example",
                        "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
                        "unpositioned": False,
                    }
                ],  # wrong name: Bob labeled
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
    assert scored["counts"] == {
        "total": 3,
        "scored": 2,
        "failed": 1,
    }
    assert scored["corpus"] == {
        "manifest_entries": 3,
        "media_id_missing": 0,
        "media_id_extra": 0,
    }
    assert scored["caption"]["insertion_rate"] == pytest.approx(0.5)
    ident = scored["faces"]["identification"]
    assert ident["wrong_names"] == [["mock_images/bob-beach.jpg", "Alice Example"]]
    assert scored["failures"] == [{"path": "mock_images/glacier.jpg", "media_id": 3, "error": "timeout after 60s"}]


def test_score_run_record_emits_verdict_fail_when_wrong_names_present():
    """VLM-6 S2A: machine-readable verdict with wrong-name rate + floor (TEST-15).

    The fixture labels Bob as Alice → wrong_name_rate = 1/2 over scored images.
    Floor is zero-tolerance: any wrong human name fails the scored verdict.
    """
    scored = score_run_record(_run_record(), _manifest_entries())
    verdict = scored["verdict"]
    assert verdict["verdict"] == ScoreVerdict.FAIL.value
    assert verdict["wrong_name_rate"] == pytest.approx(0.5)
    assert verdict["wrong_name_rate_floor"] == WRONG_NAME_RATE_FLOOR
    assert WRONG_NAME_RATE_FLOOR == 0.0
    assert verdict["wrong_name_rate"] > verdict["wrong_name_rate_floor"]
    assert any("wrong_name_rate" in r for r in verdict["reasons"])
    # Non-gating metrics are reported for operators, not used as exit thresholds here.
    assert "insertion_rate" in verdict
    assert "mean_gated_score" in verdict
    assert "must_right_failed_images" in verdict


# False-polarity trap never asserted by clean fixture captions (EVAL-19 / AUDIT-07).
_MEASURABLE_TRAP_FACT = {
    "text": "purple zebra balloon",
    "kind": "object",
    "polarity": "false",
    "phrases": ["purple zebra balloon"],
}


def test_score_run_record_emits_verdict_pass_when_no_wrong_names():
    """Clean identities + measurable categories → pass with empty reasons.

    Fixture is fully gate-clean (F1d-1 / VLM6-A-05): no failed items, non-empty
    must_right and easy_wrong, fetch-time sha present, recognition_enabled, and
    face_boxes + spatial_facts + reference_facts trap so all gated categories
    have π>0 (including fabricated_fact; EVAL-19). RV1-03: n ≥ SCORE_PASS_MIN.
    """
    record, entries = _two_image_measurable_pass_pair()
    scored = score_run_record(record, entries)
    assert scored["faces"]["identification"]["wrong_names"] == []
    assert scored["counts"]["failed"] == 0
    assert scored["faces"]["identification"]["positional"]["compared_images"] >= 1
    assert scored["placement"]["claims"] >= 1
    verdict = scored["verdict"]
    assert verdict["verdict"] == ScoreVerdict.PASS.value, verdict["reasons"]
    assert verdict["wrong_name_rate"] == 0.0
    assert verdict["wrong_name_rate_floor"] == WRONG_NAME_RATE_FLOOR
    assert verdict["reasons"] == []


def test_build_reports_json_includes_verdict_block():
    json_doc, md = build_reports(_run_record(), _manifest_entries())
    parsed = json.loads(json_doc)
    assert "verdict" in parsed
    assert parsed["verdict"]["verdict"] in {
        ScoreVerdict.PASS.value,
        ScoreVerdict.FAIL.value,
        ScoreVerdict.PASS_UNGATED.value,
        ScoreVerdict.NOT_READY.value,
    }
    assert "wrong_name_rate" in parsed["verdict"]
    assert "wrong_name_rate_floor" in parsed["verdict"]
    # Markdown surfaces the verdict for operator scan.
    assert "verdict" in md.lower()


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
    """Presentation split only: ignore-list must not zero the wrong-name floor (F1-5)."""
    ignore = {"wrong_names": [["mock_images/bob-beach.jpg", "Alice Example"]]}
    json_doc, md = build_reports(_run_record(), _manifest_entries(), ignore_list=ignore)
    parsed = json.loads(json_doc)
    ident = parsed["faces"]["identification"]
    assert ident["wrong_names"] == []
    assert ident["ignored_wrong_names"] == [["mock_images/bob-beach.jpg", "Alice Example"]]
    assert "ignored (triaged): 1" in md.lower()
    # Gate rate still counts the ignored pair (1 wrong / 2 scored = 0.5).
    assert parsed["verdict"]["wrong_name_rate"] == pytest.approx(0.5)
    assert parsed["verdict"]["verdict"] == ScoreVerdict.FAIL.value
    assert ident["evaluated_images"] == 2


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
                "identities": [
                    {
                        "name": "Ryann Wiseman",
                        "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
                        "unpositioned": False,
                    }
                ],
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
    scored = score_run_record(record, entries)
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
    # must_right and easy_wrong are counted independently (F1-1); alice-pool alone
    # has must_right, bob-beach has neither (see _manifest_entries fixture).
    assert scored["caption"]["must_right_defined_images"] == 1  # only alice-pool has must_right
    assert "easy_wrong_defined_images" in scored["caption"]
    empty = [{**e, "must_right": [], "easy_wrong": []} for e in _manifest_entries()]
    scored_empty = score_run_record(_run_record(), empty)
    assert scored_empty["caption"]["must_right_defined_images"] == 0
    assert scored_empty["caption"]["easy_wrong_defined_images"] == 0


def test_rubric_defined_images_count_scored_set_not_full_manifest():  # F1-8
    """Omitted rubriced manifest entry must not keep the scored-set counter non-zero."""
    entries = _manifest_entries()
    # alice-pool has must_right; bob-beach does not. Score only bob.
    record = _run_record()
    bob = next(i for i in record["items"] if i["media_id"] == 2)
    record = {**record, "items": [bob]}
    scored = score_run_record(record, entries)
    assert scored["counts"]["scored"] == 1
    assert scored["caption"]["must_right_defined_images"] == 0
    # Full score still sees alice-pool's must_right among the scored set.
    full = score_run_record(_run_record(), entries)
    assert full["caption"]["must_right_defined_images"] == 1


def test_media_id_multiset_coverage_counts():  # VLM-6 S2A F1-2
    """Partial run-record against full manifest reports missing media_id count."""
    entries = _manifest_entries()
    record = _run_record()
    # Drop second item → one manifest media_id missing from the record multiset.
    record = {**record, "items": record["items"][:1]}
    scored = score_run_record(record, entries)
    assert scored["corpus"]["manifest_entries"] == len(entries)
    assert scored["corpus"]["media_id_missing"] == len(entries) - 1
    assert scored["corpus"]["media_id_extra"] == 0
    # Full coverage → zeros.
    full = score_run_record(_run_record(), entries)
    assert full["corpus"]["media_id_missing"] == 0
    assert full["corpus"]["media_id_extra"] == 0


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
                "identities": [
                    {
                        "name": _PUBLIC_NAME,
                        "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
                        "unpositioned": False,
                    }
                ],
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
                "identities": [
                    {
                        "name": "Wrong Celebrity",
                        "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
                        "unpositioned": False,
                    }
                ],
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
    """PUBLIC renders only publishable per_image rows; aggregates stay full-corpus.

    VLM6-R3-03: score full corpus then redact — counts.total is full, not shrunk.
    """
    record, entries = _audience_fixtures()
    json_doc, _md = build_reports(record, entries, audience=Audience.PUBLIC)
    scored = json.loads(json_doc)
    media_ids = {p["media_id"] for p in scored["per_image"]}
    assert 10 in media_ids
    assert 20 not in media_ids
    # Full-corpus score (both items) — redaction only strips rendered per_image.
    assert scored["counts"]["total"] == 2
    assert scored["counts"]["scored"] == 2


def test_public_fail_closed_missing_entry():
    """Unknown media is corpus integrity (unknown_media_items), not privacy withhold.

    VLM6-R3-05: missing manifest entry must not be folded into withheld_items.
    """
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
    assert scored["redaction"]["withheld_items"] == 1  # local-only only
    assert scored["redaction"]["unknown_media_items"] == 1  # media_id 999
    assert scored["redaction"]["total_items"] == 3
    # Unknown media stays in failures so the public artifact fails loud.
    assert any(f.get("media_id") == 999 for f in scored["failures"])
    assert scored["counts"]["failed"] >= 1


def test_public_fail_closed_missing_provenance():
    record, entries = _audience_fixtures()
    # Strip provenance from the public entry — fail-closed, not inferred publishable.
    del entries[0]["provenance"]
    json_doc, _md = build_reports(record, entries, audience=Audience.PUBLIC)
    scored = json.loads(json_doc)
    assert scored["per_image"] == []
    assert scored["redaction"]["audience"] == "public"
    assert scored["redaction"]["withheld_items"] == 2
    assert scored["redaction"]["total_items"] == 2
    assert scored["redaction"]["unknown_media_items"] == 0
    assert scored["redaction"]["withheld_manifest_entries"] == 2


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
    assert scored["redaction"]["audience"] == "public"
    assert scored["redaction"]["withheld_items"] == 1
    assert scored["redaction"]["total_items"] == 2
    assert scored["redaction"]["unknown_media_items"] == 0
    assert scored["redaction"]["withheld_manifest_entries"] == 1
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


def test_public_redacts_run_level_base_url():  # VLM6-S5-BR-01 / VLM6-R3-01
    """base_url is not on the PUBLIC provenance allow-list — must be absent.

    Fail-closed allow-list (not deny-list rewrite to 'redacted').
    """
    record, entries = _audience_fixtures()
    record["provenance"]["base_url"] = "https://acx-backend.internal.example.ts.net"
    json_doc, md = build_reports(record, entries, audience=Audience.PUBLIC)
    for blob in (json_doc, md):
        assert "acx-backend.internal.example.ts.net" not in blob
    scored = json.loads(json_doc)
    assert "base_url" not in scored["provenance"]
    # LOCAL still shows the real endpoint (operator view).
    local_json, _local_md = build_reports(record, entries, audience=Audience.LOCAL)
    assert "acx-backend.internal.example.ts.net" in local_json


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


def test_detection_from_assignment_counts_stranger_fn():  # HARM-01 / EVAL-16
    """Detection recall must include anonymous GT misses (same population as tp).

    Repro: 1 named GT detected + 1 anonymous GT missed → pre-fix published
    recall=1.0 (fn=missed_gt named-only). True detection recall is 0.5.
    Invariant (post-wG2/wH1): tp + fn + geometry_incomplete_gt reconciles to
    every GT box that entered association.
    """
    from scripts.eval_harness.face_assignment import AssignmentResult, AssociationResult
    from scripts.eval_harness.report import _detection_from_assignment

    # Named pair + unmatched stranger GT (no detections for the stranger).
    class _Pair:
        def __init__(self) -> None:
            self.det_index = 0
            self.gt_index = 0

    assoc_named = AssociationResult(
        pairs=(_Pair(),),
        unmatched_detections=(),
        unmatched_gt=(),
        ious=(),
    )
    assoc_stranger_miss = AssociationResult(
        pairs=(),
        unmatched_detections=(),
        unmatched_gt=(0,),
        ious=(),
    )
    assignment = AssignmentResult(
        matched=(),
        decisions=(),
        tau_k=(),
        tau_op=0.5,
        association_by_media={1: assoc_named, 2: assoc_stranger_miss},
        false_detections=0,
        missed_gt=0,  # named unmatched only
        missed_stranger_gt=1,  # anonymous unmatched
        geometry_incomplete_gt=0,
        association_incomplete_media=0,
    )
    det = _detection_from_assignment(assignment)
    assert det["tp"] == 1
    assert det["fp"] == 0
    assert det["fn"] == 1  # stranger miss counted
    assert det["precision"] == pytest.approx(1.0)
    assert det["recall"] == pytest.approx(0.5)
    assert det["geometry_incomplete_gt"] == 0
    assert det["association_incomplete_media"] == 0
    assert det["association_complete"] is True
    # tp + fn + geometry_incomplete_gt == all GT that entered association.
    gt_in_assoc = sum(
        len(a.pairs) + len(a.unmatched_gt) + len(a.geometry_incomplete_gt)
        for a in assignment.association_by_media.values()
    )
    assert det["tp"] + det["fn"] + det["geometry_incomplete_gt"] == gt_in_assoc == 2


def test_score_face_unknown_rejection_surfaces_missed_stranger_gt():  # HARM-09
    """slices.unknown_rejection must publish missed_stranger_gt (post wave-C)."""
    face_run, manifest = _face_fixture_corpus()
    # Drop all detections on the stranger image → missed_stranger_gt = 1.
    for item in face_run["items"]:
        if item["media_id"] == 3:
            item["faces"] = []
    scored = score_face_run_record(face_run, manifest, score_manifest_sha256="s" * 64)
    unk = scored["slices"]["unknown_rejection"]
    assert "missed_stranger_gt" in unk
    assert unk["missed_stranger_gt"] == 1
    # Detection FN includes the stranger miss (HARM-01 end-to-end).
    assert scored["detection"]["fn"] >= 1


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
    assert unk.get("missed_stranger_gt") == 0  # HARM-09 key present when matched
    # Gate proposal EXCLUDES every DIRECTIONAL slice (SC4)
    gp = scored["gate_proposal"]
    assert gp["proposed_slices"] == {} or all(
        not (scored["slices"].get(k) or {}).get("directional", True) for k in gp["proposed_slices"]
    )
    for name in ("headline_identification", "unknown_rejection", "clustering"):
        assert name in gp["excluded_directional"] or any(name in e for e in gp["excluded_directional"])
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
    manifest = {"roster": ["Alice Q", "Bob Z"], "roster_cohorts": {}, "entries": entries}
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
    bob_tau = next(d["tau_k"] for d in scored["decisions"] if d["true_name"] == "Bob Z")
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
    parent_coupling = scored["slices"]["full_corpus_identification"]["detection_recall_coupling_flag"]
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
    assert any(d["true_name"] is None and "localwp" in d["path"] for d in scored["decisions"])
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
    assert not any(tok in d["path"] for d in jane_rows for tok in ("operator", "localwp", "uploads"))
    assert "Jane Roster" in json.dumps(scored)  # present somewhere pre-redaction

    redacted = redact_face_report_for_public(scored)
    blob = json.dumps(redacted)
    # PRIMARY: the named private individual is nowhere in the public artifact.
    assert "Jane Roster" not in blob
    assert "corpus/private/jane-01.jpg" not in blob
    assert "corpus/private/jane-02.jpg" not in blob
    # Publishable celeb detail survives; every surviving row is publishable + named.
    assert redacted["decisions"]
    assert all(d.get("publishable") is True and d.get("true_name") is not None for d in redacted["decisions"])
    # Per-face clustering labels stripped (aggregate-only public artifact).
    assert redacted["slices"]["clustering"]["labels"] == []
    # Aggregate rates preserved (unknown-rejection count/rate unchanged by redaction).
    assert redacted["slices"]["unknown_rejection"]["n"] == scored["slices"]["unknown_rejection"]["n"]
    assert redacted["slices"]["unknown_rejection"]["rate"] == scored["slices"]["unknown_rejection"]["rate"]


def test_face_public_redaction_drops_operator_paths_base_url_identity_text():  # VLM6-R2-A-02
    """Face PUBLIC must use the shared provenance allow-list + path/identity scrub.

    RE-01 / RB-07: plants must exercise path redaction and identity scrub as
    *load-bearing* — secrets live inside allow-listed free text, list[str]
    leaves, demographic wrong_names, preserved denominators, and publishable
    predicted_name — not only in deny-listed provenance keys that the
    allow-list alone would drop. Whole-document absence is the contract.
    """
    private = "Jane Doe Private"
    private_slug = "JaneDoePrivate"
    face_run, manifest = _face_fixture_corpus()
    face_run["provenance"].update(
        {
            "cache_dir": f"/home/ubuntu/private/{private_slug}/cache",
            "base_url": "http://127.0.0.1:8765/v1",
            "operator_note": f"local scoring for {private}",
            "run_record_path": "/home/ubuntu/secret/face-run.json",
        }
    )
    scored = score_face_run_record(face_run, manifest, score_manifest_sha256="s" * 64)
    # Control: LOCAL/full scored report still carries the operator fields.
    pre = json.dumps(scored)
    assert f"/home/ubuntu/private/{private_slug}/cache" in pre
    assert "http://127.0.0.1:8765/v1" in pre
    assert f"local scoring for {private}" in pre
    assert "/home/ubuntu/secret/face-run.json" in pre

    # Plant leaks that only path-redaction / free-text scrub / recursive wrong_names
    # clear can catch (RE-01: delete those helpers → these plants must RED the test).
    # Score overwrites tau_fit_status/sampling_frames from protocol constants — plant
    # hostile allow-listed free text on the scored report (the PUBLIC boundary input).
    scored = json.loads(json.dumps(scored))  # deep-copy via JSON for mutation
    scored.setdefault("provenance", {})["tau_fit_status"] = (
        f"status for /var/op/{private_slug}/cache"
    )
    scored.setdefault("provenance", {})["sampling_frames"] = {
        "face_id": f"eval of {private} at /home/ubuntu/secret/notes",
    }
    scored["protocol_disclosures"] = [f"mean_prototype; exclude {private}"]
    scored.setdefault("gate_proposal", {})["scope_amendments_for_operator_ack"] = [
        f"ack {private} enrollment"
    ]
    scored.setdefault("gate_proposal", {})["error_context"] = "/home/ubuntu/secret/face-run.json"
    # RF-01: demographic wrong_names not cleared by the two-key enumeration.
    scored.setdefault("slices", {}).setdefault("demographic", {}).setdefault("by_cohort", {})[
        "adult_f"
    ] = {
        "wrong_names": [[99, 0, private, "Alice Example"]],
        "ignored_wrong_names": [],
        "precision": 0.0,
    }
    # RB-02: sampling_frame free text will be copied into preserved_* if unfixed.
    hl = scored.setdefault("slices", {}).setdefault("headline_identification", {})
    hl["sampling_frame"] = f"ops: {private} @ /home/ubuntu/secret/notes"
    hl.setdefault("precision_numerator", 0)
    hl.setdefault("precision_denominator", 1)
    # CDX-01 / RB-04: publishable decision carrying a private gallery identity.
    scored.setdefault("decisions", []).append(
        {
            "media_id": 9001,
            "publishable": True,
            "true_name": "Ada Lovelace",
            "predicted_name": private,
            "name_star": private,
            "path": "/public/ada.jpg",
            "decision": "accept",
        }
    )
    # Ensure private name is present pre-redaction (fixture live).
    assert private in json.dumps(scored)

    redacted = redact_face_report_for_public(scored)
    blob = json.dumps(redacted)
    md = __import__("scripts.eval_harness.report", fromlist=["_markdown_face"])._markdown_face(redacted)

    for surface in (blob, md):
        assert "/home/ubuntu/private" not in surface, surface[:500]
        assert private_slug not in surface
        assert private not in surface
        assert "Jane Doe" not in surface
        assert "http://127.0.0.1" not in surface
        assert "/home/ubuntu/secret" not in surface
        assert "/var/op" not in surface
        assert "face-run.json" not in surface
        assert "local scoring for" not in surface

    # Recursive whole-document contract (acceptance bar).
    assert private not in blob
    assert private_slug not in blob
    assert "/home/ubuntu" not in blob
    assert "/var/op" not in blob

    # Demographic wrong_names cleared (RF-01).
    demo = (redacted.get("slices") or {}).get("demographic") or {}
    for cohort in (demo.get("by_cohort") or {}).values():
        if isinstance(cohort, dict):
            assert cohort.get("wrong_names") in (None, [])
            assert private not in json.dumps(cohort)

    # preserved_* must not re-inject pre-scrub free text (RB-02).
    preserved = (redacted.get("redaction") or {}).get("preserved_aggregate_denominators") or {}
    assert private not in json.dumps(preserved)
    assert "/home/ubuntu" not in json.dumps(preserved)

    # Publishable row may keep true_name; private predicted/name_star must not ship (CDX-01).
    for d in redacted.get("decisions") or []:
        if d.get("true_name") == "Ada Lovelace":
            assert d.get("predicted_name") != private
            assert d.get("name_star") != private
            assert private not in json.dumps(d)

    prov = redacted["provenance"]
    for key in ("cache_dir", "base_url", "operator_note", "run_record_path"):
        assert key not in prov, f"leaked provenance key {key!r}: {prov.get(key)!r}"
    # Shared allow-list still emits safe protocol fields (no face-only fork).
    assert "head_sha" in prov
    assert "manifest_sha256" in prov
    assert "score_manifest_sha256" in prov
    assert "canon_version" in prov
    assert "zero_box_corpus" in prov


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
    summary = _latency_summary(items)
    assert summary is not None
    assert summary["images_timed"] == 4
    # nearest-rank on sorted values; p99/max surface the tail (VLM6-R4-09)
    assert summary["wall_clock_s"]["p50"] == 2.0
    assert summary["wall_clock_s"]["p95"] == 4.0
    assert summary["wall_clock_s"]["p99"] == 4.0
    assert summary["wall_clock_s"]["max"] == 4.0
    assert summary["model_calls"] == {"per_image_mean": 1.0, "total": 4}
    assert summary["cache_hits_excluded"] == 0
    assert summary["error_items_excluded"] == 0
    assert summary["timed_out_images"] == 0
    assert summary["percentile_caveat"] == "n=4_below_p95_rank_threshold"


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
    assert summary is not None
    assert summary["images_timed"] == 2
    assert summary["wall_clock_s"]["p50"] == 3.0
    assert summary["wall_clock_s"]["p95"] == 7.0
    assert summary["wall_clock_s"]["max"] == 7.0
    assert summary["model_calls"] == {"per_image_mean": 2.0, "total": 4}


def test_latency_summary_skips_error_and_untimed_items():
    items = [
        {"media_id": 1, "describe": None, "error": "timeout after 60s", "latency_s": 5.0},
        {"media_id": 2, "describe": {"alt_text_draft": "x"}, "error": None},  # no latency field at all
        {"media_id": 3, "describe": {"alt_text_draft": "x"}, "error": None, "latency_s": None},
        {"media_id": 4, "describe": {"alt_text_draft": "x"}, "error": None, "latency_s": 2.5},
    ]
    summary = _latency_summary(items)
    assert summary is not None
    assert summary["images_timed"] == 1
    assert summary["wall_clock_s"]["p50"] == 2.5
    assert summary["wall_clock_s"]["p95"] == 2.5
    assert summary["wall_clock_s"]["p99"] == 2.5
    assert summary["wall_clock_s"]["max"] == 2.5
    assert summary["error_items_excluded"] == 1
    assert summary["timed_out_images"] == 1
    assert _latency_summary(items[:3]) is None  # nothing timed at all => no section


def test_latency_section_and_markdown_line_render_when_timed():
    record, entries = _run_record(), _manifest_entries()
    record["items"][0]["latency_s"] = 3.2
    record["items"][1]["latency_s"] = 1.1
    # Both timed items must be live inference (not cache hits) so p50/p95
    # reflect open-loop timings (VLM6-R4-04). Fixture item 1 defaults cached=True.
    record["items"][0]["describe"]["cached"] = False
    record["items"][1]["describe"]["cached"] = False
    json_doc, md = build_reports(record, entries)
    scored = json.loads(json_doc)
    lat = scored["latency"]
    assert lat["images_timed"] == 2
    assert lat["wall_clock_s"]["p50"] == 1.1
    assert lat["wall_clock_s"]["p95"] == 3.2
    assert lat["wall_clock_s"]["p99"] == 3.2
    assert lat["wall_clock_s"]["max"] == 3.2
    assert lat["model_calls"] == {"per_image_mean": 1.0, "total": 2}
    assert lat["error_items_excluded"] == 1  # glacier timeout item
    assert lat["timed_out_images"] == 1
    assert "latency: per-image wall-clock p50 1.1s p95 3.2s" in md
    assert "p99" in md and "max" in md
    assert build_reports(record, entries) == build_reports(record, entries)  # determinism holds


def test_latency_excludes_cache_hits():  # VLM6-R4-04
    """Cache-hit timings must not dilute p50/p95 open-loop latency (TEST-15).

    RED without fix: both items timed → p50=0.5 (cache 0.001 + live 1.0 avg-ish
    nearest-rank) or images_timed=2. GREEN: only the live miss contributes.
    """
    items = [
        {
            "media_id": 1,
            "describe": {"alt_text_draft": "x", "cached": True},
            "error": None,
            "latency_s": 0.001,
        },
        {
            "media_id": 2,
            "describe": {"alt_text_draft": "y", "cached": False},
            "error": None,
            "latency_s": 4.0,
        },
        {
            "media_id": 3,
            "describe": {"alt_text_draft": "z", "cached": False},
            "error": None,
            "latency_s": 2.0,
        },
    ]
    summary = _latency_summary(items)
    assert summary is not None
    assert summary["images_timed"] == 2
    assert summary["wall_clock_s"]["p50"] == 2.0
    assert summary["wall_clock_s"]["p95"] == 4.0
    assert summary["wall_clock_s"]["max"] == 4.0
    assert summary["cache_hits_excluded"] == 1
    # All-cache corpus ⇒ zero live timings but cache pollution is disclosed.
    all_cache = _latency_summary(items[:1])
    assert all_cache is not None
    assert all_cache["images_timed"] == 0
    assert all_cache["cache_hits_excluded"] == 1
    assert all_cache["percentile_caveat"] == "no_live_timings"


# --- Identity shape normalizer (dict rows vs legacy name strings) ------------


def _dict_identity(name: str, *, x: float = 10.0) -> dict:
    """Positional identity row written by cli._extract_identities after A1."""
    return {
        "name": name,
        "bbox": {"x": x, "y": 40.0, "width": 50.0, "height": 60.0},
        "unpositioned": False,
    }


def _identity_scoring_pair() -> tuple[dict, list[dict]]:
    """Alice correctly named + Bob misnamed as Alice — same labels as _run_record."""
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
                "identities": [_dict_identity("Alice Example", x=10.0)],
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
                "identities": [_dict_identity("Alice Example", x=80.0)],  # wrong name: Bob labeled
                "face_count": 1,
                "error": None,
            },
        ],
    }
    entries = [
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
    ]
    return record, entries


def test_score_run_record_identity_metrics_with_dict_shape():  # TEST-15
    """New _extract_identities dict rows must score as name strings (not TypeError).

    report.py used to pass raw dicts into ImageIdentities.predicted (Sequence[str]);
    face_metrics then does set(predicted) and dies with unhashable dict.
    """
    record, entries = _identity_scoring_pair()
    scored = score_run_record(record, entries)
    ident = scored["faces"]["identification"]
    assert ident["wrong_names"] == [["mock_images/bob-beach.jpg", "Alice Example"]]
    # Alice: TP on image 1, FP on image 2 (wrong-name hit). Bob: FN (never named).
    alice = ident["per_identity"]["Alice Example"]
    assert alice["tp"] == 1 and alice["fp"] == 1 and alice["fn"] == 0
    bob = ident["per_identity"]["Bob Builder"]
    assert bob["tp"] == 0 and bob["fp"] == 0 and bob["fn"] == 1


def test_score_run_record_rejects_bare_string_identity_shape():  # A-06 / A-10
    """Greenfield: bare-string identity lists fail validation loudly (no shim)."""
    record, entries = _identity_scoring_pair()
    for item in record["items"]:
        item["identities"] = [row["name"] for row in item["identities"]]
    with pytest.raises(ReportError, match="dict identity row"):
        score_run_record(record, entries)


def test_run_record_validation_rejects_wrong_identity_element_type():  # A-10
    """List-ness alone is not enough — wrong element type must fail at validation."""
    record, entries = _identity_scoring_pair()
    record["items"][0]["identities"] = [42, True]
    with pytest.raises(ReportError, match="identities\\[0\\].*dict"):
        score_run_record(record, entries)


def test_positional_metric_discriminates_swap_from_correct_order():  # A-02 / FL30A-GATE-01
    """Set-based identification_pr is swap-blind; positional accuracy is not.

    predicted and labeled are independent sequences (not one list copied twice):
    labeled is L→R as face_boxes would yield; predicted is written separately.
    Alphabetical present_identities storage must not be used as labeled order.
    """
    from scripts.eval_harness.face_metrics import (
        ImageIdentities,
        identification_pr,
        labeled_left_to_right,
        positional_identification,
    )

    # Spatial L→R on a 3-person group: Cam, Amy, Zoe. Manifest stores alpha.
    face_boxes = [
        _gt_box(0.15, 0.4, 0.2, 0.3, "Cam Left"),
        _gt_box(0.50, 0.4, 0.2, 0.3, "Amy Mid"),
        _gt_box(0.85, 0.4, 0.2, 0.3, "Zoe Right"),
    ]
    present_alphabetical = ["Amy Mid", "Cam Left", "Zoe Right"]  # draft_labels sort
    labeled_ltr = labeled_left_to_right(face_boxes)
    assert labeled_ltr == ["Cam Left", "Amy Mid", "Zoe Right"]
    assert labeled_ltr != present_alphabetical  # the bug premise

    # Independently written predicted sequences — not list(labeled).
    predicted_correct = ["Cam Left", "Amy Mid", "Zoe Right"]
    predicted_swapped = ["Amy Mid", "Cam Left", "Zoe Right"]  # left/mid swap

    correct = ImageIdentities(
        image="group.jpg",
        predicted=predicted_correct,
        labeled=labeled_ltr,
    )
    swapped = ImageIdentities(
        image="group.jpg",
        predicted=predicted_swapped,
        labeled=labeled_ltr,
    )
    # Using alphabetical labeled (the old call-site bug) would score correct as swap.
    alpha_wrong = ImageIdentities(
        image="group.jpg",
        predicted=predicted_correct,
        labeled=present_alphabetical,
    )
    # Set-based PR is identical for correct and swapped (A-02 premise).
    pr_ok = identification_pr([correct])
    pr_sw = identification_pr([swapped])
    assert pr_ok.precision == pr_sw.precision == 1.0
    assert pr_ok.recall == pr_sw.recall == 1.0
    # Positional score diverges on genuine swap; perfect L→R is exact.
    pos_ok = positional_identification([correct])
    pos_sw = positional_identification([swapped])
    assert pos_ok.position_accuracy == 1.0
    assert pos_ok.exact_order_rate == 1.0
    assert pos_ok.swap_images == 0
    assert pos_sw.position_accuracy == pytest.approx(1 / 3)
    assert pos_sw.swap_images == 1
    assert pos_ok.position_accuracy != pos_sw.position_accuracy
    # Prove the old input shape was wrong (TEST-15 discrimination).
    pos_alpha = positional_identification([alpha_wrong])
    assert pos_alpha.position_accuracy == pytest.approx(1 / 3)
    assert pos_alpha.swap_images == 1


def test_positional_alphabetical_present_identities_scored_via_face_boxes():  # FL30A-GATE-01
    """Perfect L→R prediction must score 1.0 even when present_identities is alpha."""
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
                "media_id": 1,
                "path": "mock_images/group.jpg",
                "describe": {
                    "alt_text_draft": "Three people stand together.",
                    "visual_facts": {"caption": "group", "objects": []},
                    "adapter": "seeded",
                    "model_id": "seeded-fixtures",
                    "model_version": "1",
                    "cached": False,
                },
                # Model predicts true L→R: Cam, Amy, Zoe.
                "identities": [
                    _dict_identity("Cam Left", x=10.0),
                    _dict_identity("Amy Mid", x=100.0),
                    _dict_identity("Zoe Right", x=200.0),
                ],
                "face_count": 3,
                "error": None,
            },
        ],
    }
    entries = [
        {
            "path": "mock_images/group.jpg",
            "media_id": 1,
            "face_count": 3,
            # Alphabetical as draft_labels stores it — NOT L→R.
            "present_identities": ["Amy Mid", "Cam Left", "Zoe Right"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [
                _gt_box(0.15, 0.4, 0.2, 0.3, "Cam Left"),
                _gt_box(0.50, 0.4, 0.2, 0.3, "Amy Mid"),
                _gt_box(0.85, 0.4, 0.2, 0.3, "Zoe Right"),
            ],
        },
    ]
    scored = score_run_record(record, entries)
    pos = scored["faces"]["identification"]["positional"]
    assert pos["position_accuracy"] == 1.0
    assert pos["exact_order_rate"] == 1.0
    assert pos["swap_images"] == 0
    assert pos["compared_images"] == 1
    assert pos["excluded_images"] == []


def test_positional_genuine_swap_still_counted_with_face_boxes():  # FL30A-GATE-01
    """Adjacent transposition relative to face_boxes is still a swap (not blind)."""
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
                "media_id": 1,
                "path": "mock_images/group.jpg",
                "describe": {
                    "alt_text_draft": "Three people stand together.",
                    "visual_facts": {"caption": "group", "objects": []},
                    "adapter": "seeded",
                    "model_id": "seeded-fixtures",
                    "model_version": "1",
                    "cached": False,
                },
                # Predicted left/mid swap relative to boxes (Cam, Amy, Zoe L→R).
                "identities": [
                    _dict_identity("Amy Mid", x=10.0),
                    _dict_identity("Cam Left", x=100.0),
                    _dict_identity("Zoe Right", x=200.0),
                ],
                "face_count": 3,
                "error": None,
            },
        ],
    }
    entries = [
        {
            "path": "mock_images/group.jpg",
            "media_id": 1,
            "face_count": 3,
            "present_identities": ["Amy Mid", "Cam Left", "Zoe Right"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [
                _gt_box(0.15, 0.4, 0.2, 0.3, "Cam Left"),
                _gt_box(0.50, 0.4, 0.2, 0.3, "Amy Mid"),
                _gt_box(0.85, 0.4, 0.2, 0.3, "Zoe Right"),
            ],
        },
    ]
    scored = score_run_record(record, entries)
    pos = scored["faces"]["identification"]["positional"]
    assert pos["swap_images"] == 1
    assert pos["position_accuracy"] == pytest.approx(1 / 3)
    assert pos["exact_order_rate"] == 0.0
    assert pos["compared_images"] == 1


def test_positional_excludes_entries_without_face_boxes():  # FL30A-GATE-01
    """Legacy entries with no face_boxes are excluded, not compared alphabetically."""
    record, entries = _identity_scoring_pair()
    # Confirm fixtures have no face_boxes (legacy shape).
    assert all(not e.get("face_boxes") for e in entries)
    scored = score_run_record(record, entries)
    pos = scored["faces"]["identification"]["positional"]
    assert pos["compared_images"] == 0
    assert pos["position_total"] == 0
    assert pos["swap_images"] == 0
    assert set(pos["excluded_images"]) == {
        "mock_images/alice-pool.jpg",
        "mock_images/bob-beach.jpg",
    }


def test_labeled_left_to_right_dedupes_duplicate_names_leftmost():  # FL30A-GATE-01
    """Duplicate face_boxes names keep the leftmost occurrence only."""
    from scripts.eval_harness.face_metrics import labeled_left_to_right

    boxes = [
        _gt_box(0.7, 0.4, 0.2, 0.3, "Alice"),  # right duplicate
        _gt_box(0.2, 0.4, 0.2, 0.3, "Alice"),  # leftmost Alice
        _gt_box(0.5, 0.4, 0.2, 0.3, "Bob"),
        _gt_box(0.9, 0.4, 0.2, 0.3, None),  # anonymous stranger skipped
    ]
    assert labeled_left_to_right(boxes) == ["Alice", "Bob"]
    assert labeled_left_to_right([]) is None
    assert labeled_left_to_right(None) is None


def test_score_run_record_wires_positional_into_report():  # A-02
    """Report faces.identification.positional is populated when face_boxes exist."""
    record, entries = _identity_scoring_pair()
    # Attach face_boxes so positional scoring is enabled (not legacy-excluded).
    entries[0]["face_boxes"] = [_gt_box(0.4, 0.4, 0.3, 0.3, "Alice Example")]
    entries[1]["face_boxes"] = [_gt_box(0.4, 0.4, 0.3, 0.3, "Bob Builder")]
    scored = score_run_record(record, entries)
    pos = scored["faces"]["identification"]["positional"]
    assert pos["position_hits"] == 1  # Alice correct; Bob image is wrong name (0 hits of 1)
    assert pos["position_total"] == 2
    assert "exact_order_rate" in pos and "swap_images" in pos
    assert pos["excluded_images"] == []


def test_identity_names_preserves_left_to_right_not_alphabetical():
    """Normalizer keeps stored L→R order; three names beat reverse-alpha (A-11)."""
    from scripts.eval_harness.report import identity_names

    # Alpha: Amy Mid, Cam Left, Zoe Right. Reverse: Zoe, Cam, Amy. L→R: Cam, Amy, Zoe.
    raw = [
        _dict_identity("Cam Left", x=10.0),
        _dict_identity("Amy Mid", x=100.0),
        _dict_identity("Zoe Right", x=200.0),
    ]
    names = identity_names(raw)
    assert names == ["Cam Left", "Amy Mid", "Zoe Right"]
    assert names != sorted(names)
    assert names != sorted(names, reverse=True)  # A-11: not reverse-alphabetical either


def test_identity_names_rejects_bare_string_shape():  # A-06
    from scripts.eval_harness.report import identity_names

    with pytest.raises(TypeError, match="dict identity row"):
        identity_names(["Zoe Left", "Amy Right"])


def test_identity_names_rejects_empty_name_and_non_dict():  # A-06
    from scripts.eval_harness.report import identity_names

    with pytest.raises(ValueError, match="empty/missing"):
        identity_names([{"name": "", "bbox": None, "unpositioned": True}])
    with pytest.raises(TypeError, match="dict identity row"):
        identity_names([_dict_identity("Keep Me"), 42])


def test_identity_names_rejects_non_list_top_level():  # A-15
    """Top-level non-list identities must raise TypeError (not silently return [])."""
    from scripts.eval_harness.report import identity_names

    for bad in (None, "Zoe Alone", {"name": "dict-not-list"}):
        with pytest.raises(TypeError, match="list of dict rows"):
            identity_names(bad)


# --- VLM-6 lc1-report: placement / hallucination wiring + public redaction ---


def test_score_run_record_surfaces_placement_accuracy():  # VLM6-R4-02
    """Placement is scored and must appear on the report (not computed-and-dropped).

    RED without wiring: ``placement`` key absent or accuracy None while caption
    asserts the correct L→R claim.
    """
    record, entries = _run_record(), _manifest_entries()
    entries[0]["spatial_facts"] = [
        {
            "subject": "Alice Example",
            "relation": "left_of",
            "reference": "Bob Builder",
            "phrases": ["left of Bob Builder"],
        }
    ]
    record["items"][0]["describe"]["alt_text_draft"] = "Alice Example stands left of Bob Builder by a pool."
    # Drop the error item so aggregates are clean.
    record["items"] = [record["items"][0]]
    scored = score_run_record(record, entries)
    assert "placement" in scored
    assert scored["placement"]["accuracy"] == pytest.approx(1.0)
    assert scored["placement"]["claims"] == 1
    assert scored["placement"]["correct"] == 1
    row = scored["per_image"][0]
    assert row["placement"]["accuracy"] == pytest.approx(1.0)
    assert "Alice Example left_of Bob Builder" in row["placement"]["correct"]
    _json_doc, md = build_reports(record, entries)
    assert "placement accuracy" in md.lower()


def test_score_run_record_surfaces_placement_wrong_claim():  # VLM6-R4-02
    """Wrong placement claims must score 0.0 (not silently omit the section)."""
    record, entries = _run_record(), _manifest_entries()
    entries[0]["spatial_facts"] = [
        {
            "subject": "Alice Example",
            "relation": "left_of",
            "reference": "Bob Builder",
            "phrases": ["left of Bob Builder"],
        }
    ]
    # Inverted claim.
    record["items"][0]["describe"]["alt_text_draft"] = "Alice Example stands right of Bob Builder by a pool."
    record["items"] = [record["items"][0]]
    scored = score_run_record(record, entries)
    assert scored["placement"]["accuracy"] == pytest.approx(0.0)
    assert scored["placement"]["wrong"] == 1
    assert scored["per_image"][0]["placement"]["wrong"]


def test_score_run_record_surfaces_hallucination_fabricated_facts():  # VLM6-R2-02
    """Fabricated-fact rate must surface on the report (not computed-and-dropped).

    RED without wiring: ``hallucination`` key absent while caption trips a false-
    polarity reference fact.
    """
    record, entries = _run_record(), _manifest_entries()
    entries[0]["reference_facts"] = [
        {
            "text": "red sports car",
            "kind": "object",
            "polarity": "false",
            "phrases": ["red sports car", "sports car"],
        },
        {
            "text": "poolside",
            "kind": "scene",
            "polarity": "true",
            "phrases": ["pool"],
        },
    ]
    record["items"][0]["describe"]["alt_text_draft"] = "Alice Example relaxes by a pool next to a red sports car."
    record["items"] = [record["items"][0]]
    scored = score_run_record(record, entries)
    assert "hallucination" in scored
    assert scored["hallucination"]["fabricated_fact_rate"] == pytest.approx(1.0)
    assert scored["hallucination"]["images_caught"] == 1
    assert scored["hallucination"]["by_kind"].get("object") == 1
    row = scored["per_image"][0]
    assert row["hallucination"]["fabricated"] is True
    assert any(f["text"] == "red sports car" for f in row["hallucination"]["fabricated_facts"])
    _json_doc, md = build_reports(record, entries)
    assert "fabricated-fact rate" in md.lower()


def test_score_run_record_hallucination_clean_caption_rate_zero():  # VLM6-R2-02
    """Clean caption against a trap corpus yields fabricated_fact_rate 0.0, not None."""
    record, entries = _run_record(), _manifest_entries()
    entries[0]["reference_facts"] = [
        {
            "text": "red sports car",
            "kind": "object",
            "polarity": "false",
            "phrases": ["red sports car"],
        }
    ]
    record["items"][0]["describe"]["alt_text_draft"] = "Alice Example relaxes by a pool."
    record["items"] = [record["items"][0]]
    scored = score_run_record(record, entries)
    assert scored["hallucination"]["fabricated_fact_rate"] == pytest.approx(0.0)
    assert scored["hallucination"]["images_caught"] == 0
    assert scored["per_image"][0]["hallucination"]["fabricated"] is False


def test_public_report_redacts_api_key_and_tenant_id():  # VLM6-R3-01 / R4-07
    """Secrets on provenance must be ABSENT from the public rendered artifact.

    Fail-closed allow-list drops unknown keys entirely (not rewrite-to-redacted).
    """
    record, entries = _audience_fixtures()
    record["provenance"]["api_key"] = "sk-live-TOPSECRET-xyz"
    record["provenance"]["tenant_id"] = "tenant-private-999"
    json_doc, md = build_reports(record, entries, audience=Audience.PUBLIC)
    for blob in (json_doc, md):
        assert "sk-live-TOPSECRET-xyz" not in blob
        assert "tenant-private-999" not in blob
    scored = json.loads(json_doc)
    assert "api_key" not in scored["provenance"]
    assert "tenant_id" not in scored["provenance"]
    # LOCAL still shows the operator secrets (operator view, not hub-safe).
    local_json, _ = build_reports(record, entries, audience=Audience.LOCAL)
    assert "sk-live-TOPSECRET-xyz" in local_json
    assert "tenant-private-999" in local_json


def test_public_report_redacts_absolute_local_paths():  # VLM6-R3
    """Absolute operator filesystem paths must be ABSENT from public output.

    Publishable items may still be stored under absolute LocalWP paths; the
    render boundary collapses them to basenames. Control asserts the sensitive
    absolute prefix is missing, not merely that a redactor was invoked.
    """
    record, entries = _audience_fixtures()
    abs_path = "/Users/daniel/Development/wp-context-alt-text/app/public/wp-content/uploads/celebs01/obama-podium.jpg"
    record["items"][0]["path"] = abs_path
    entries[0]["path"] = abs_path
    json_doc, md = build_reports(record, entries, audience=Audience.PUBLIC)
    for blob in (json_doc, md):
        assert "/Users/daniel" not in blob
        assert "wp-context-alt-text" not in blob
        assert "wp-content/uploads" not in blob
    scored = json.loads(json_doc)
    # S2-04: absolute paths must not collapse to identifying basenames; free-text
    # paths emit opaque media_id tokens (S2-03).
    assert scored["per_image"][0]["path"] == "media_id:10"
    assert "obama-podium.jpg" not in json_doc
    assert "/Users/daniel" not in json_doc


def test_public_report_still_redacts_base_url():  # VLM6-R3-01 / VLM6-S5-BR-01
    record, entries = _audience_fixtures()
    record["provenance"]["base_url"] = "https://acx-backend.internal.example.ts.net"
    json_doc, md = build_reports(record, entries, audience=Audience.PUBLIC)
    for blob in (json_doc, md):
        assert "acx-backend.internal.example.ts.net" not in blob
    assert "base_url" not in json.loads(json_doc)["provenance"]


def test_gated_score_components_surfaced_on_caption_block():
    """aggregate_gated_scores components must appear (not silent N/A absorption)."""
    record, entries = _run_record(), _manifest_entries()
    # Empty-identity glacier-like image that scores: force recognition-disabled
    # empty present set so gated_score is None (not-applicable).
    entries[0]["present_identities"] = []
    entries[0]["must_right"] = []
    record["items"][0]["describe"]["alt_text_draft"] = "A quiet pool at dusk."
    record["items"][0]["identities"] = []
    record["items"][0]["face_count"] = 0
    entries[0]["face_count"] = 0
    record["items"] = [record["items"][0], record["items"][1]]  # keep bob wrong-name row
    scored = score_run_record(record, entries)
    assert "gated_score_scored" in scored["caption"]
    assert "gated_score_excluded" in scored["caption"]
    assert (
        scored["caption"]["gated_score_scored"] + scored["caption"]["gated_score_excluded"]
        == scored["counts"]["scored"]
    )
    _json_doc, md = build_reports(record, entries)
    assert "excluded=" in md


def test_quality_block_surfaces_fkre_and_tag_coverage_aggregates():
    """Per-image fkre/tag_coverage/repetition/gist must roll up (not dead-path)."""
    record, entries = _run_record(), _manifest_entries()
    scored = score_run_record(record, entries)
    quality = scored["quality"]
    assert quality.get("mean_fkre") is not None
    assert "mean_repetition_ratio" in quality
    assert "mean_tag_coverage" in quality or quality.get("mean_tag_coverage") is None
    assert "first_sentence_gist_ok_rate" in quality
    _json_doc, md = build_reports(record, entries)
    assert "mean FKRE" in md


def test_positional_unknown_order_does_not_use_alphabetical_labeled():  # VLM6-R2-04
    """Without face_boxes, positional labeled must not silently use present_identities.

    RED before: labeled fell back to alphabetical present and would score if
    labeled_order_known were ever ignored. GREEN: excluded + empty comparison.
    S2-07: exclusions surface as order_unknown_excluded, not degraded_images.
    """
    record, entries = _run_record(), _manifest_entries()
    assert all(not e.get("face_boxes") for e in entries)
    scored = score_run_record(record, entries)
    pos = scored["faces"]["identification"]["positional"]
    assert pos["compared_images"] == 0
    assert pos["position_total"] == 0
    # Excluded images listed (legacy no-box entries).
    assert len(pos["excluded_images"]) >= 1
    ordering = scored["faces"]["identity_ordering"]
    # S2-07: true DEGRADED stamps only — bare exclusions are not degraded.
    assert ordering["degraded_images"] == 0
    assert ordering["order_unknown_excluded"] >= 1


def test_public_local_roster_name_on_publishable_item_scrubbed():  # VLM6-R3-02 / R3-06
    """Private-roster prediction on a PUBLISHABLE item must not appear in PUBLIC output.

    RED without post-score scrub: wrong_names / hallucinated_names leak the private
    name even though the item itself is publishable (item-level filter cannot help).
    """
    private_name = "Aunt Mary Arce"
    record, entries = _audience_fixtures()
    # Model asserts a local-only person on the publishable celeb image.
    record["items"][0]["identities"] = [
        {
            "name": private_name,
            "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
            "unpositioned": False,
        }
    ]
    record["items"][0]["describe"]["alt_text_draft"] = f"{private_name} at a podium."
    # Full roster includes private name so caption hallucination gate can trip.
    roster = [_PUBLIC_NAME, private_name, _LOCAL_NAME]
    local_json, _ = build_reports(record, entries, audience=Audience.LOCAL, manifest_roster=roster)
    local = json.loads(local_json)
    # Control: LOCAL must see the private assertion (proves the fixture is live).
    assert private_name in local_json
    assert any(
        private_name in (row.get("hallucinated_names") or []) or private_name in (row.get("wrong_name_hits") or [])
        for row in local["per_image"]
        if row["media_id"] == 10
    ) or any(pair[1] == private_name for pair in (local["faces"]["identification"].get("wrong_names") or []))

    pub_json, pub_md = build_reports(record, entries, audience=Audience.PUBLIC, manifest_roster=roster)
    for blob in (pub_json, pub_md):
        assert private_name not in blob
        assert _LOCAL_NAME not in blob
    pub = json.loads(pub_json)
    assert pub["faces"]["identification"]["wrong_names"] == []
    assert all(
        not (row.get("hallucinated_names") or []) and not (row.get("wrong_name_hits") or []) for row in pub["per_image"]
    )
    # Aggregates preserved from full-corpus score (not zeroed by redaction).
    assert "precision" in pub["faces"]["identification"]


def test_public_aggregate_parity_with_private_manifest_entries():  # VLM6-R3-03
    """PUBLIC must not shrink closed-roster / must_right denominators.

    RED without fix: filtering manifest_entries drops private roster names so a
    publishable-item hallucination of a private name disappears and
    must_right_defined_images collapses.
    """
    private_name = "Jane Private"
    record, entries = _audience_fixtures()
    # 1 publishable item invents a private roster name in the caption.
    record["items"] = [record["items"][0]]
    record["items"][0]["describe"]["alt_text_draft"] = f"{private_name} at a podium."
    record["items"][0]["identities"] = [
        {
            "name": _PUBLIC_NAME,
            "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
            "unpositioned": False,
        }
    ]
    # 50 non-publishable manifest entries that only exist to widen the roster.
    for i in range(50):
        entries.append(
            {
                "path": f"localwp/private-{i}.jpg",
                "media_id": 1000 + i,
                "face_count": 1,
                "present_identities": [private_name] if i == 0 else [f"Local Person {i}"],
                "must_right": [private_name] if i == 0 else [f"Local Person {i}"],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "provenance": {
                    "source": "localwp",
                    "license": "consented",
                    "publishable": False,
                },
            }
        )
    local = json.loads(build_reports(record, entries, audience=Audience.LOCAL)[0])
    pub = json.loads(build_reports(record, entries, audience=Audience.PUBLIC)[0])
    # Aggregate parity: PUBLIC must not look perfect while LOCAL fails.
    assert local["caption"]["name_precision"] == pub["caption"]["name_precision"]
    assert local["caption"]["wrong_name_image_rate"] == pub["caption"]["wrong_name_image_rate"]
    assert local["caption"]["mean_gated_score"] == pub["caption"]["mean_gated_score"]
    assert local["caption"]["must_right_defined_images"] == pub["caption"]["must_right_defined_images"]
    # Hallucination of private name is detected under both audiences.
    assert local["caption"]["wrong_name_image_rate"] == pytest.approx(1.0)
    # audience fixture already has 1 local entry + 50 added private entries
    assert pub["redaction"]["withheld_manifest_entries"] == 51
    # Private name absent from PUBLIC rendered detail (R3-02) but gate still tripped.
    assert private_name not in build_reports(record, entries, audience=Audience.PUBLIC)[0]


def test_public_provenance_allow_list_drops_unknown_keys():  # VLM6-R3-01 / R4-07 / R3-06
    """Unknown provenance keys and nested path leaks must be absent from PUBLIC.

    RED without allow-list: weave_bench_source.path / images_dir / tenant_id pass through.
    """
    record, entries = _audience_fixtures()
    record["provenance"]["tenant_id"] = "tenant-secret-42"
    record["provenance"]["images_dir"] = "/Volumes/Chimay/___Books/corpus646"
    record["provenance"]["weave_bench_source"] = {
        "path": "/Users/daniel/Local Sites/wp-acx/out/bakeoff/run-secret.json",
        "sha256": "a" * 64,
    }
    record["provenance"]["totally_unknown_future_key"] = "should-never-publish"
    record["items"][0]["describe"]["model_id"] = "/Users/daniel/models/Qwen3-VL-27B-Q4_K_M.gguf"
    json_doc, md = build_reports(record, entries, audience=Audience.PUBLIC)
    scored = json.loads(json_doc)
    prov = scored["provenance"]
    for key in (
        "tenant_id",
        "images_dir",
        "weave_bench_source",
        "totally_unknown_future_key",
        "base_url",
    ):
        assert key not in prov
    for blob in (json_doc, md):
        assert "tenant-secret-42" not in blob
        assert "/Volumes/Chimay" not in blob
        assert "run-secret.json" not in blob or "Local Sites" not in blob
        assert "should-never-publish" not in blob
        assert "/Users/daniel/models" not in blob
    # Allowed keys still present.
    assert "head_sha" in prov
    assert "manifest_sha256" in prov


def test_public_validates_record_kind_before_audience_branch():  # VLM6-R3-04
    """PUBLIC must raise ReportError on wrong kind, not KeyError('items')."""
    bogus = {"schema": "acx-eval/v1", "kind": "report", "provenance": {}}
    with pytest.raises(ReportError, match="run_record"):
        build_reports(bogus, [], audience=Audience.PUBLIC)


def test_public_per_image_allow_list_strips_identity_name_fields():  # VLM6-A-01
    """PUBLIC per-image must not leak roster names via sibling identity fields.

    Deny-list redaction cleared only hallucinated_names / wrong_name_hits; the
    sibling fields inserted_identities, missing_identities, must_right_failures
    survived with private roster names verbatim (rg-015 fail-closed allow-list).
    """
    private = "Shared Private Person"
    public = "Barack Obama"
    record, entries = _audience_fixtures()
    # Publishable item: private subject is present+must_right but absent from
    # caption/ids → missing_identities + must_right_failures carry the private name.
    record["items"] = [record["items"][0]]
    record["items"][0]["describe"]["alt_text_draft"] = f"{public} at a podium."
    record["items"][0]["identities"] = [
        {
            "name": public,
            "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
            "unpositioned": False,
        }
    ]
    entries[0]["present_identities"] = [public, private]
    entries[0]["must_right"] = [private]
    roster = [public, private]

    local = json.loads(build_reports(record, entries, audience=Audience.LOCAL, manifest_roster=roster)[0])
    local_row = next(r for r in local["per_image"] if r["media_id"] == 10)
    # Control: LOCAL surface is live — private name is in the sibling fields.
    assert private in (local_row.get("missing_identities") or [])
    assert private in (local_row.get("must_right_failures") or [])

    pub = json.loads(build_reports(record, entries, audience=Audience.PUBLIC, manifest_roster=roster)[0])
    assert pub["per_image"], "publishable row must survive redaction"
    pub_row = pub["per_image"][0]
    # Finding surface: per_image sibling fields (not aggregate per_identity).
    assert private not in json.dumps(pub_row)
    # Name-bearing fields must be absent (allow-list drop), not emptied-in-place.
    for key in (
        "inserted_identities",
        "missing_identities",
        "must_right_failures",
        "hallucinated_names",
        "wrong_name_hits",
    ):
        assert key not in pub_row, f"identity field leaked into PUBLIC per_image: {key}"


def test_public_per_image_allow_list_drops_future_name_field():  # VLM6-A-01
    """A brand-new name-bearing per-image key must NOT appear in PUBLIC (rg-015).

    Deny-lists leak on schema growth; this is the assertion that the allow-list
    actually holds — a field never listed is excluded by default.
    """
    private = "Future Leak Person"
    record, entries = _audience_fixtures()
    record["items"] = [record["items"][0]]
    from scripts.eval_harness.report import _redact_caption_report_for_public

    local = score_run_record(record, entries)
    assert local["per_image"], "fixture must produce a scored row"
    local["per_image"][0]["brand_new_name_field"] = [private]
    # Also stamp the private name into a classic leak field so LOCAL control is live.
    local["per_image"][0]["inserted_identities"] = [private]
    assert private in json.dumps(local["per_image"][0])

    redacted = _redact_caption_report_for_public(local, run_record=record, manifest_entries=entries)
    assert redacted["per_image"], "publishable row must survive"
    pub_row = redacted["per_image"][0]
    assert private not in json.dumps(pub_row)
    assert "brand_new_name_field" not in pub_row
    assert "inserted_identities" not in pub_row


def test_score_run_record_positional_uses_centre_x_not_corner_x():  # VLM6-B-03
    """Production positional path must centre-order predicted names (not list/corner order).

    Wide @ corner-x=100 width=200 → centre 200; Narrow @ corner-x=150 width=50 →
    centre 175. Stored identities in corner order [Wide, Narrow] are wrong for
    L→R; centre order [Narrow, Wide] matches labeled face_boxes. Without B-03
    wiring, position_accuracy is 0.0 (swap); with it, 1.0 (TEST-15).
    """
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
                "media_id": 1,
                "path": "mock_images/pair.jpg",
                "describe": {
                    "alt_text_draft": "Narrow Left stands left of Wide Right.",
                    "visual_facts": {"objects": []},
                },
                # Corner-x order (Wide first) — centre-x order is Narrow first.
                "identities": [
                    {
                        "name": "Wide Right",
                        "bbox": {"x": 100.0, "y": 0.0, "width": 200.0, "height": 100.0},
                        "unpositioned": False,
                    },
                    {
                        "name": "Narrow Left",
                        "bbox": {"x": 150.0, "y": 0.0, "width": 50.0, "height": 100.0},
                        "unpositioned": False,
                    },
                ],
                "face_count": 2,
                "identity_ordering": "positional",
                "image_width": 400,
                "image_height": 200,
                "error": None,
            },
        ],
    }
    entries = [
        {
            "path": "mock_images/pair.jpg",
            "media_id": 1,
            "face_count": 2,
            "present_identities": ["Narrow Left", "Wide Right"],
            "must_right": ["Narrow Left"],
            "easy_wrong": ["Carol Decoy"],
            "policy": {"recognition_enabled": True},
            # Labeled L→R by centre-x (Narrow left of Wide).
            "face_boxes": [
                {"name": "Narrow Left", "x": 0.4375, "y": 0.25},
                {"name": "Wide Right", "x": 0.5, "y": 0.25},
            ],
            "spatial_facts": [
                {
                    "subject": "Narrow Left",
                    "relation": "left_of",
                    "reference": "Wide Right",
                    "phrases": ["left of Wide Right"],
                }
            ],
        },
    ]
    scored = score_run_record(record, entries)
    pos = scored["faces"]["identification"]["positional"]
    assert pos["compared_images"] == 1
    assert pos["swap_images"] == 0
    assert pos["position_accuracy"] == pytest.approx(1.0)
    assert pos["exact_order_rate"] == pytest.approx(1.0)


def test_score_run_record_positional_vacuity_signal_on_real_golden():  # VLM6-B-10
    """Real golden corpus (0/37 face_boxes) must emit positional vacuity fields.

    Frame (AUDIT-07): target=adoption readiness; sampling unit=scored image;
    observation unit=image with face_boxes L→R; π=0 on face_boxes today.
    """
    from scripts.eval_harness.cli import _manifest_sha
    from scripts.eval_harness.manifest import load_manifest
    from scripts.eval_harness.schema import SCHEMA, DocKind

    golden = Path(__file__).resolve().parent / "seed" / "golden.json"
    manifest = load_manifest(str(golden), skip_hash_verification=True)
    entries = [e.model_dump() for e in manifest.entries]
    assert len(entries) == 37
    assert all(not (e.get("face_boxes") or []) for e in entries)
    msha = _manifest_sha(manifest)
    items = []
    for entry in entries:
        names = list(entry.get("present_identities") or [])
        must = list(entry.get("must_right") or [])
        cap = " ".join(must + names + ["outdoors smiling."]) if (must or names) else "A scenic outdoor photograph."
        items.append(
            {
                "media_id": entry["media_id"],
                "path": entry["path"],
                "describe": {
                    "alt_text_draft": cap,
                    "visual_facts": {"objects": []},
                },
                "identities": [
                    {
                        "name": n,
                        "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
                        "unpositioned": False,
                    }
                    for n in names
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
    scored = score_run_record(record, entries, score_manifest_sha256=msha, manifest_roster=list(manifest.roster or []))
    pos = scored["faces"]["identification"]["positional"]
    assert pos["compared_images"] == 0
    assert pos["evaluable"] is False
    assert pos["status"] == "not_evaluable"
    assert pos["vacuity_signal"]
    assert "π=0" in pos["vacuity_signal"] or "not evaluable" in pos["vacuity_signal"].lower()
    assert pos["sampling_frame"]
    assert scored["verdict"]["verdict"] == ScoreVerdict.NOT_READY.value
    assert any("positional" in r.lower() for r in scored["verdict"]["reasons"])


def _two_image_measurable_pass_pair() -> tuple[dict, list[dict]]:
    """Measurable corpus that clears SCORE_PASS_MIN_SCORED_IMAGES (RV1-03 n=5).

    Name kept for call-site stability; body is five distinct measurable images.
    """
    from scripts.eval_harness.report import SCORE_PASS_MIN_SCORED_IMAGES

    pairs = [
        ("Alice Example", "Bob Builder", "pool"),
        ("Carol Decoy", "Dana Friend", "park"),
        ("Eve Visitor", "Frank Guest", "cafe"),
        ("Grace Host", "Hank Neighbor", "yard"),
        ("Ivy Cousin", "Jake Sibling", "beach"),
    ]
    # Pad if the floor is raised further.
    while len(pairs) < SCORE_PASS_MIN_SCORED_IMAGES:
        i = len(pairs) + 1
        pairs.append((f"Person{i}A", f"Person{i}B", f"scene{i}"))
    items: list[dict] = []
    entries: list[dict] = []
    for idx, (left, right, scene) in enumerate(pairs, start=1):
        path = f"mock_images/{left.split()[0].lower()}-{scene}.jpg"
        items.append(
            {
                "media_id": idx,
                "path": path,
                "describe": {
                    "alt_text_draft": f"{left} stands left of {right} by a {scene}.",
                    "visual_facts": {"objects": []},
                },
                "identities": [
                    {
                        "name": left,
                        "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
                        "unpositioned": False,
                    },
                    {
                        "name": right,
                        "bbox": {"x": 80.0, "y": 40.0, "width": 50.0, "height": 60.0},
                        "unpositioned": False,
                    },
                ],
                "face_count": 2,
                "identity_ordering": "positional",
                "image_width": 200,
                "image_height": 200,
                "error": None,
            }
        )
        entries.append(
            {
                "path": path,
                "media_id": idx,
                "face_count": 2,
                "present_identities": [left, right],
                "must_right": [left],
                "easy_wrong": [right],
                "policy": {"recognition_enabled": True},
                "face_boxes": [
                    {"name": left, "x": 0.2, "y": 0.4},
                    {"name": right, "x": 0.6, "y": 0.4},
                ],
                "spatial_facts": [
                    {
                        "subject": left,
                        "relation": "left_of",
                        "reference": right,
                        "phrases": [f"left of {right}"],
                    }
                ],
                "reference_facts": [dict(_MEASURABLE_TRAP_FACT)],
            }
        )
    record = {
        "schema": "acx-eval/v1",
        "kind": "run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "base_url": "https://api.example.com",
            "head_sha": "0" * 40,
            "started_at": "2026-07-06T00:00:00Z",
        },
        "items": items,
    }
    return record, entries


def test_score_run_record_positional_vacuity_absent_when_measurable():  # VLM6-B-10 control
    """When all gated categories are measurable, vacuity signal clears and pass is allowed.

    Control for B-10: face_boxes (positional) + spatial_facts (placement) +
    reference_facts trap (fabricated_fact) so every category has π>0; proves
    the gate can go green and is not a permanent brick (TEST-15).
    RV1-03: sample size must clear SCORE_PASS_MIN_SCORED_IMAGES (n=5).
    """
    from scripts.eval_harness.report import SCORE_PASS_MIN_SCORED_IMAGES

    record, entries = _two_image_measurable_pass_pair()
    scored = score_run_record(record, entries)
    pos = scored["faces"]["identification"]["positional"]
    assert pos["compared_images"] >= 1
    assert pos["evaluable"] is True
    assert pos["status"] == "scored"
    assert pos["vacuity_signal"] is None
    assert scored["hallucination"]["fabricated_fact_rate"] == pytest.approx(0.0)
    assert scored["hallucination"]["images_with_traps"] >= 1
    assert scored["counts"]["scored"] >= SCORE_PASS_MIN_SCORED_IMAGES
    assert scored["verdict"]["verdict"] == ScoreVerdict.PASS.value, scored["verdict"]["reasons"]


def _passable_scored_dict(**hall_overrides: object) -> dict:
    """Hand-built scored dict that clears every score vacuity + quality floor (S2-06)."""
    from scripts.eval_harness.report import SCORE_PASS_MIN_SCORED_IMAGES

    n = SCORE_PASS_MIN_SCORED_IMAGES
    hall = {
        "fabricated_fact_rate": 0.0,
        "fabricated_fact_rate_trapped": 0.0,
        "images_with_traps": 1,
    }
    hall.update(hall_overrides)
    return {
        "counts": {"total": n, "scored": n, "failed": 0},
        "corpus": {"media_id_missing": 0, "media_id_extra": 0},
        "provenance": {"manifest_sha256": "a" * 64},
        "caption": {
            "must_right_defined_images": 1,
            "easy_wrong_defined_images": 1,
            "must_right_failed_images": 0,
            "insertion_rate": 0.0,
            "mean_gated_score": 1.0,
        },
        "faces": {
            "detection": {"precision": 1.0, "recall": 1.0},
            "identification": {
                "evaluated_images": n,
                "wrong_names": [],
                "ignored_wrong_names": [],
                "precision": 1.0,
                "recall": 1.0,
                "positional": {
                    "compared_images": n,
                    "evaluable": True,
                    "status": "scored",
                    "excluded_images": [],
                    "position_accuracy": 1.0,
                },
            },
            "identity_ordering": {
                "degraded_images": 0,
                "positional_images": n,
                "order_unknown_excluded": 0,
            },
        },
        "placement": {"claims": n, "accuracy": 1.0, "abstained": 0, "images_scored": n},
        "hallucination": hall,
    }


def test_build_score_verdict_treats_fabricated_fact_rate_none_as_vacuous():  # VLM6-C-05 / fx4
    """None fabricated_fact_rate is not measurable — never a clean zero-hallucination pass.

    Injects None on an otherwise-passable scored dict (TEST-15). Works for both
    current 0.0 (traps present, none fired) and fx4's None (no traps).
    """
    from scripts.eval_harness.report import build_score_verdict

    scored = _passable_scored_dict(
        fabricated_fact_rate=None,
        fabricated_fact_rate_trapped=None,
        images_with_traps=0,
    )
    verdict = build_score_verdict(scored, rubric_gate="enforce")
    assert verdict["verdict"] == ScoreVerdict.NOT_READY.value
    assert any("fabricated_fact" in r for r in verdict["reasons"])
    # Control: numeric 0.0 is measurable clean (not vacuous) when traps>0.
    scored["hallucination"]["fabricated_fact_rate"] = 0.0
    scored["hallucination"]["fabricated_fact_rate_trapped"] = 0.0
    scored["hallucination"]["images_with_traps"] = 1
    verdict_ok = build_score_verdict(scored, rubric_gate="enforce")
    assert verdict_ok["verdict"] == ScoreVerdict.PASS.value
    assert not any("fabricated_fact" in r for r in verdict_ok["reasons"])


def test_score_verdict_not_ready_when_positional_and_placement_vacuous():  # VLM6-A-05
    """Clean identities on a π=0 corpus must NOT persist verdict=pass (EVAL-23).

    Shipped golden has face_boxes/spatial_facts on 0/37 — positional compared=0
    and placement claims=0. A readiness gate that reports pass here is dishonest
    about which claim units have sampling probability 0 (AUDIT-07).
    """
    # Fixture mirrors the clean-pass shape: correct names, non-empty rubrics,
    # fetch sha present — but no face_boxes / spatial_facts (vacuous categories).
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
                "media_id": 1,
                "path": "mock_images/alice-pool.jpg",
                "describe": {
                    "alt_text_draft": "Alice Example relaxes by a pool.",
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
            },
            {
                "media_id": 2,
                "path": "mock_images/bob-beach.jpg",
                "describe": {
                    "alt_text_draft": "Bob Builder on a beach.",
                    "visual_facts": {"objects": []},
                },
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
        ],
    }
    entries = [
        {
            "path": "mock_images/alice-pool.jpg",
            "media_id": 1,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "must_right": ["Alice Example"],
            "easy_wrong": ["Bob Builder"],
            "policy": {"recognition_enabled": True},
        },
        {
            "path": "mock_images/bob-beach.jpg",
            "media_id": 2,
            "face_count": 1,
            "present_identities": ["Bob Builder"],
            "must_right": ["Bob Builder"],
            "easy_wrong": ["Alice Example"],
            "policy": {"recognition_enabled": True},
        },
    ]
    scored = score_run_record(record, entries)
    assert scored["faces"]["identification"]["positional"]["compared_images"] == 0
    assert scored["placement"]["claims"] == 0
    assert scored["placement"]["accuracy"] is None
    verdict = scored["verdict"]
    # Must not be adoption-eligible pass when critical categories are unobservable.
    assert verdict["verdict"] != ScoreVerdict.PASS.value
    assert verdict["verdict"] == ScoreVerdict.NOT_READY.value
    reasons_blob = " | ".join(verdict["reasons"]).lower()
    assert "positional" in reasons_blob
    assert "placement" in reasons_blob
    assert reasons_blob  # non-empty reasons naming the vacuous categories


def test_score_verdict_pass_when_positional_and_placement_measurable():  # VLM6-A-05 control
    """Discrimination control: once every gated claim unit is measurable, verdict can pass.

    Same clean identities as the vacuity test, but face_boxes + spatial_facts +
    reference_facts trap populate positional, placement, and fabricated_fact
    denominators (π>0). Proves the gate can go green (TEST-15). S2-05 requires
    sample size ≥ SCORE_PASS_MIN_SCORED_IMAGES.
    """
    record, entries = _two_image_measurable_pass_pair()
    scored = score_run_record(record, entries)
    assert scored["faces"]["identification"]["positional"]["compared_images"] >= 1
    assert scored["placement"]["claims"] >= 1
    assert scored["placement"]["accuracy"] is not None
    assert scored["hallucination"]["fabricated_fact_rate"] == pytest.approx(0.0)
    assert scored["hallucination"]["images_with_traps"] >= 1
    from scripts.eval_harness.report import SCORE_PASS_MIN_SCORED_IMAGES

    assert scored["counts"]["scored"] >= SCORE_PASS_MIN_SCORED_IMAGES
    verdict = scored["verdict"]
    assert verdict["verdict"] == ScoreVerdict.PASS.value, verdict["reasons"]
    assert verdict["reasons"] == []


def test_score_verdict_blocks_pass_on_vacuous_placement_alone():  # VLM6-B-07
    """Placement must enter the verdict; claims=0 / accuracy=None blocks pass.

    Positional is made measurable so the only vacuity reason is placement
    (EVAL-04 slice gate; EVAL-23 weakest category).
    """
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
                "media_id": 1,
                "path": "mock_images/alice-pool.jpg",
                "describe": {
                    "alt_text_draft": "Alice Example and Bob Builder by a pool.",
                    "visual_facts": {"objects": []},
                },
                "identities": [
                    {
                        "name": "Alice Example",
                        "bbox": {"x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
                        "unpositioned": False,
                    },
                    {
                        "name": "Bob Builder",
                        "bbox": {"x": 80.0, "y": 40.0, "width": 50.0, "height": 60.0},
                        "unpositioned": False,
                    },
                ],
                "face_count": 2,
                "identity_ordering": "positional",
                "error": None,
            },
        ],
    }
    entries = [
        {
            "path": "mock_images/alice-pool.jpg",
            "media_id": 1,
            "face_count": 2,
            "present_identities": ["Alice Example", "Bob Builder"],
            "must_right": ["Alice Example"],
            "easy_wrong": ["Carol Decoy"],
            "policy": {"recognition_enabled": True},
            "face_boxes": [
                {"name": "Alice Example", "x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
                {"name": "Bob Builder", "x": 80.0, "y": 40.0, "width": 50.0, "height": 60.0},
            ],
            # No spatial_facts → placement accuracy=None, claims=0 (π=0).
        },
    ]
    scored = score_run_record(record, entries)
    assert scored["faces"]["identification"]["positional"]["compared_images"] >= 1
    assert scored["placement"]["claims"] == 0
    assert scored["placement"]["accuracy"] is None
    verdict = scored["verdict"]
    assert verdict["verdict"] != ScoreVerdict.PASS.value
    assert verdict["verdict"] == ScoreVerdict.NOT_READY.value
    assert any("placement" in r.lower() for r in verdict["reasons"])
    # Positional is measurable — must not be blamed.
    assert not any("positional" in r.lower() for r in verdict["reasons"])


def test_predicted_order_degraded_excluded_from_positional():  # VLM6-R4-06
    """identity_ordering=degraded must not contaminate position_accuracy.

    RED without fix: alphabetically-ordered predictions scored as if spatial.
    """
    record, entries = _identity_scoring_pair()
    # Two-person image with face_boxes establishing L→R labeled order.
    entries[0]["present_identities"] = ["Alice Example", "Bob Builder"]
    entries[0]["face_count"] = 2
    entries[0]["face_boxes"] = [
        {"name": "Alice Example", "x": 10.0, "y": 40.0, "width": 50.0, "height": 60.0},
        {"name": "Bob Builder", "x": 80.0, "y": 40.0, "width": 50.0, "height": 60.0},
    ]
    # Predicted order is swapped AND stamped degraded (alphabetical append path).
    record["items"] = [record["items"][0]]
    record["items"][0]["identities"] = [
        _dict_identity("Bob Builder", x=10.0),
        _dict_identity("Alice Example", x=80.0),
    ]
    record["items"][0]["face_count"] = 2
    record["items"][0]["identity_ordering"] = "degraded"
    record["items"][0]["describe"]["alt_text_draft"] = "Alice Example and Bob Builder."
    scored = score_run_record(record, entries)
    pos = scored["faces"]["identification"]["positional"]
    assert pos["compared_images"] == 0
    assert record["items"][0]["path"] in pos["excluded_images"] or any(
        "alice" in p.lower() for p in pos["excluded_images"]
    )


def test_unknown_identity_ordering_stamp_raises():  # VLM6-RH-06
    """A typo'd ordering stamp must go loud, not take neither branch.

    RED before the enum move: ``"degrade"`` matched neither raw-string arm, so
    both counters stayed 0 and the A-07 surface reported a clean run. The
    exhaustive comparison is the only thing that can fail here (sr-007).
    """
    record, entries = _identity_scoring_pair()
    record["items"][0]["identity_ordering"] = "degrade"  # one char short
    with pytest.raises(ReportError, match="unknown identity_ordering"):
        score_run_record(record, entries)


def test_absent_identity_ordering_stamp_is_legal():  # VLM6-RH-06 discrimination
    """Discrimination control: ``None`` means "fetch never stamped", not a typo.

    Without this the guard above could be satisfied by rejecting everything,
    which would break the committed anchor (37/37 unstamped).
    """
    record, entries = _identity_scoring_pair()
    record["items"][0].pop("identity_ordering", None)
    scored = score_run_record(record, entries)
    ordering = scored["faces"]["identity_ordering"]
    # Unstamped is not "positional" — it is unproven. S2-07: do not invent
    # degraded_images from exclusions; order_unknown_excluded is the vacuity surface.
    assert ordering["positional_images"] == 0
    assert ordering["degraded_images"] == 0
    assert ordering["order_unknown_excluded"] >= 1


def test_strata_by_difficulty_and_domain():  # VLM6-R4-05
    """Caption gate must emit per-difficulty / per-domain blocks with n."""
    record, entries = _run_record(), _manifest_entries()
    entries[0]["difficulty"] = "easy"
    entries[0]["domain"] = "portrait"
    entries[1]["difficulty"] = "hard"
    entries[1]["domain"] = "group"
    scored = score_run_record(record, entries)
    assert "strata" in scored
    by_diff = scored["strata"]["by_difficulty"]
    by_dom = scored["strata"]["by_domain"]
    assert "easy" in by_diff and by_diff["easy"]["n"] >= 1
    assert "hard" in by_diff and by_diff["hard"]["n"] >= 1
    assert "portrait" in by_dom and "group" in by_dom
    assert "mean_gated_score" in by_diff["easy"]
    _json_doc, md = build_reports(record, entries)
    assert "difficulty=easy" in md or "difficulty=" in md


def test_wrong_name_rate_is_per_image_not_assertion_pairs():  # VLM6-S2A-B-09
    """One image with two wrong names must contribute 1.0 rate when scored_n=1.

    RED without fix: rate = 2/1 = 2.0 (unbounded 'rate').
    """
    record, entries = _identity_scoring_pair()
    record["items"] = [record["items"][1]]  # Bob misnamed
    # Two wrong predicted names on the same image.
    record["items"][0]["identities"] = [
        _dict_identity("Alice Example", x=10.0),
        _dict_identity("Zoe Intruder", x=80.0),
    ]
    record["items"][0]["face_count"] = 2
    entries = [entries[1]]
    entries[0]["face_count"] = 1
    scored = score_run_record(record, entries)
    rate = scored["verdict"]["wrong_name_rate"]
    assert rate <= 1.0
    assert rate == pytest.approx(1.0)
    assert scored["verdict"]["wrong_name_images"] == 1
    assert scored["verdict"]["wrong_name_assertions"] >= 1


def test_identity_names_lives_on_report_module():  # VLM6-RH-07
    """report.identity_names is the scoring normalizer (no cli import cycle)."""
    from scripts.eval_harness.report import identity_names as report_identity_names

    names = report_identity_names([{"name": "Zoe Alone", "bbox": None, "unpositioned": True}])
    assert names == ["Zoe Alone"]
    with pytest.raises(TypeError, match="list of dict rows"):
        report_identity_names("not-a-list")


def test_identity_names_has_exactly_one_definition():  # VLM6-RH-07 residual
    """cli and describe_baseline must re-export report's function, not clone it.

    The first RH-07 fix removed the import cycle by copying the body into both
    modules. The contract tests above then exercised the ``cli`` clone while
    scoring ran the ``report`` one, so a regression in the copy that actually
    scores could not go red. Identity comparison is the only assertion that
    fails when someone re-clones (equal behaviour today, divergent tomorrow).
    """
    from scripts.eval_harness import cli as cli_mod
    from scripts.eval_harness import report as report_mod

    assert cli_mod.identity_names is report_mod.identity_names


# --- VLM6 gx2: honest adoption verdicts + real redaction (S2-01..07 / S4-05) ---


def test_build_score_verdict_zero_fab_rate_with_zero_traps_is_vacuous():  # VLM6-S2-01
    """Numeric fabricated_fact_rate=0.0 with images_with_traps=0 must not certify.

    Pre-fix: fab_rate=0.0, traps=0 → verdict=pass (clean-zero lie). GREEN: not_ready.
    """
    from scripts.eval_harness.report import build_score_verdict

    scored = _passable_scored_dict(
        fabricated_fact_rate=0.0,
        fabricated_fact_rate_trapped=0.0,
        images_with_traps=0,
    )
    verdict = build_score_verdict(scored, rubric_gate="enforce")
    assert verdict["verdict"] != ScoreVerdict.PASS.value
    assert verdict["verdict"] == ScoreVerdict.NOT_READY.value
    assert any("fabricated_fact" in r for r in verdict["reasons"])
    assert any("images_with_traps=0" in r for r in verdict["reasons"])


def test_build_score_verdict_quality_floors_fail_total_failure_mutations():  # VLM6-S2-02
    """Quality-floor bands fail measured-and-bad slices (RV1-04 / EVAL-04).

    Pre-fix floors were IEEE corners (0.0 / 1.0) so 0.0001 / 0.9999 passed.
    Threshold ± epsilon pins the band edges.
    """
    from scripts.eval_harness.report import (
        FABRICATED_FACT_RATE_CEILING,
        PLACEMENT_ACCURACY_FLOOR,
        POSITION_ACCURACY_FLOOR,
        build_score_verdict,
    )

    eps = 1e-6
    # At-or-below / at-or-above threshold → FAIL.
    fail_cases = [
        (
            "position_at_floor",
            lambda s: s["faces"]["identification"]["positional"].update(
                {"position_accuracy": POSITION_ACCURACY_FLOOR}
            ),
            "position_accuracy",
        ),
        (
            "position_below",
            lambda s: s["faces"]["identification"]["positional"].update(
                {"position_accuracy": POSITION_ACCURACY_FLOOR - eps}
            ),
            "position_accuracy",
        ),
        (
            "placement_at_floor",
            lambda s: s["placement"].update({"accuracy": PLACEMENT_ACCURACY_FLOOR}),
            "placement.accuracy",
        ),
        (
            "fab_at_ceiling",
            lambda s: s["hallucination"].update(
                {
                    "fabricated_fact_rate": FABRICATED_FACT_RATE_CEILING,
                    "fabricated_fact_rate_trapped": FABRICATED_FACT_RATE_CEILING,
                    "images_with_traps": 2,
                }
            ),
            "fabricated_fact_rate",
        ),
        (
            "fab_above",
            lambda s: s["hallucination"].update(
                {
                    "fabricated_fact_rate": FABRICATED_FACT_RATE_CEILING + eps,
                    "fabricated_fact_rate_trapped": FABRICATED_FACT_RATE_CEILING + eps,
                    "images_with_traps": 2,
                }
            ),
            "fabricated_fact_rate",
        ),
    ]
    for label, mut, token in fail_cases:
        scored = _passable_scored_dict()
        mut(scored)
        verdict = build_score_verdict(scored, rubric_gate="enforce")
        assert verdict["verdict"] == ScoreVerdict.FAIL.value, f"{label}: {verdict}"
        assert any("quality-floor" in r and token in r for r in verdict["reasons"]), (
            label,
            verdict["reasons"],
        )
    # Just above / below threshold → not a quality-floor fail (may still pass).
    pass_edge = _passable_scored_dict()
    pass_edge["faces"]["identification"]["positional"]["position_accuracy"] = (
        POSITION_ACCURACY_FLOOR + eps
    )
    pass_edge["placement"]["accuracy"] = PLACEMENT_ACCURACY_FLOOR + eps
    pass_edge["hallucination"]["fabricated_fact_rate"] = FABRICATED_FACT_RATE_CEILING - eps
    pass_edge["hallucination"]["fabricated_fact_rate_trapped"] = FABRICATED_FACT_RATE_CEILING - eps
    pass_edge["hallucination"]["images_with_traps"] = 2
    verdict_ok = build_score_verdict(pass_edge, rubric_gate="enforce")
    assert not any("quality-floor" in r for r in verdict_ok["reasons"]), verdict_ok["reasons"]
    assert verdict_ok["verdict"] == ScoreVerdict.PASS.value, verdict_ok


def test_quality_floor_realistic_midrange_and_chance_boundary():  # VLM6-R2-G-06
    """0.5 is binary-chance, not a 0.05 band — realistic mid-range must pass.

    Floor uses `<=` so accuracy==0.5 fails; accuracy just above passes. A
    working-model mid-range (e.g. 0.72 position / 0.65 placement) must not trip
    quality-floor. Unmeasured slices (compared=0 / claims=0) stay dormant —
    matches S2A bake-off anchors where position_accuracy is None.
    """
    from scripts.eval_harness.report import (
        PLACEMENT_ACCURACY_FLOOR,
        POSITION_ACCURACY_FLOOR,
        build_score_quality_floor_reasons,
        build_score_verdict,
    )

    assert POSITION_ACCURACY_FLOOR == 0.5
    assert PLACEMENT_ACCURACY_FLOOR == 0.5

    # Realistic mid-range (above chance) → no quality-floor reason.
    mid = _passable_scored_dict()
    mid["faces"]["identification"]["positional"]["position_accuracy"] = 0.72
    mid["faces"]["identification"]["positional"]["compared_images"] = 5
    mid["placement"]["accuracy"] = 0.65
    mid["placement"]["claims"] = 4
    mid_reasons = build_score_quality_floor_reasons(mid, scored_n=int(mid["counts"]["scored"]))
    assert mid_reasons == [], mid_reasons
    mid_verdict = build_score_verdict(mid, rubric_gate="enforce")
    assert not any("quality-floor" in r for r in mid_verdict["reasons"]), mid_verdict["reasons"]
    assert mid_verdict["verdict"] == ScoreVerdict.PASS.value, mid_verdict

    # Just above chance: comparison is `<=`, so 0.5 + epsilon must not trip.
    just_above = _passable_scored_dict()
    just_above["faces"]["identification"]["positional"]["position_accuracy"] = 0.5001
    just_above["faces"]["identification"]["positional"]["compared_images"] = 5
    just_reasons = build_score_quality_floor_reasons(
        just_above, scored_n=int(just_above["counts"]["scored"])
    )
    assert not any("position_accuracy" in r for r in just_reasons), just_reasons
    just_verdict = build_score_verdict(just_above, rubric_gate="enforce")
    assert not any(
        "quality-floor" in r and "position_accuracy" in r for r in just_verdict["reasons"]
    ), just_verdict["reasons"]

    # Exact chance boundary: `<=` means floor itself is FAIL.
    at_floor = _passable_scored_dict()
    at_floor["faces"]["identification"]["positional"]["position_accuracy"] = POSITION_ACCURACY_FLOOR
    at_floor["faces"]["identification"]["positional"]["compared_images"] = 5
    at_floor["placement"]["accuracy"] = PLACEMENT_ACCURACY_FLOOR
    at_floor["placement"]["claims"] = 4
    at_reasons = build_score_quality_floor_reasons(at_floor, scored_n=int(at_floor["counts"]["scored"]))
    assert any("position_accuracy" in r and "<=" in r for r in at_reasons), at_reasons
    assert any("placement.accuracy" in r and "<=" in r for r in at_reasons), at_reasons
    at_verdict = build_score_verdict(at_floor, rubric_gate="enforce")
    assert at_verdict["verdict"] == ScoreVerdict.FAIL.value, at_verdict

    # Unmeasured (bake-off-shaped): accuracy present but compared/claims == 0 → dormant.
    dormant = _passable_scored_dict()
    dormant["faces"]["identification"]["positional"]["position_accuracy"] = 0.0
    dormant["faces"]["identification"]["positional"]["compared_images"] = 0
    dormant["placement"]["accuracy"] = 0.0
    dormant["placement"]["claims"] = 0
    assert build_score_quality_floor_reasons(dormant, scored_n=int(dormant["counts"]["scored"])) == []


def test_public_redaction_scrubs_free_text_identity_names_everywhere():  # VLM6-S2-03 / S2-04
    """Identity names in path / short_error / failures must be absent from PUBLIC blob.

    Assert on the whole serialized document — not key-by-key — so a future free-text
    allow-list key cannot re-open the leak (TEST-15 / S2-03 shape fix).
    """
    from scripts.eval_harness.report import _redact_caption_report_for_public

    private = "Jane Doe Private"
    record, entries = _audience_fixtures()
    # Publishable row with name embedded in free-text path + short_error.
    record["items"] = [record["items"][0]]
    record["items"][0]["path"] = f"celebs01/{private}-with-obama.jpg"
    entries = [entries[0]]
    entries[0]["path"] = f"celebs01/{private}-with-obama.jpg"
    local = score_run_record(record, entries)
    assert local["per_image"], "fixture must produce a scored row"
    local["per_image"][0]["path"] = f"celebs01/{private}-with-obama.jpg"
    local["per_image"][0]["short_error"] = f"short compression failed involving {private}"
    local["failures"] = [
        {
            "path": f"/home/op/uploads/{private}.jpg",
            "media_id": 10,
            "error": f"timeout while describing {private}",
            "secret_extra": f"should drop but names {private}",
        }
    ]
    # Pre-redaction control: name is live in the local document.
    assert private in json.dumps(local)

    redacted = _redact_caption_report_for_public(local, run_record=record, manifest_entries=entries)
    blob = json.dumps(redacted)
    assert private not in blob
    assert f"/home/op/uploads/{private}.jpg" not in blob
    assert f"{private}.jpg" not in blob
    # Free-text path is opaque media_id token (S2-04: not identifying basename).
    assert redacted["per_image"][0]["path"] == "media_id:10"
    assert redacted["per_image"][0]["short_error"] in ("<redacted>", "<error>")
    assert redacted["failures"]
    fail = redacted["failures"][0]
    assert "secret_extra" not in fail
    assert private not in json.dumps(fail)
    assert fail["path"] == "media_id:10"


def test_score_and_compare_agree_on_vacuous_fabricated_fact():  # VLM6-S2-01 / S2-06
    """score verdict and compare share one vacuity predicate for fab_rate/traps."""
    from scripts.eval_harness.cli import _compare_vacuous_categories
    from scripts.eval_harness.report import (
        build_score_verdict,
        fabricated_fact_is_vacuous,
        score_vacuous_category_labels,
    )

    scored = _passable_scored_dict(
        fabricated_fact_rate=0.0,
        fabricated_fact_rate_trapped=0.0,
        images_with_traps=0,
    )
    assert fabricated_fact_is_vacuous(scored["hallucination"]) is True
    labels = score_vacuous_category_labels(scored, include_verdict_fields=False)
    assert "fabricated_fact" in labels
    verdict = build_score_verdict(scored, rubric_gate="enforce")
    assert verdict["verdict"] == ScoreVerdict.NOT_READY.value
    # Stamp verdict so compare's include_verdict_fields path is live.
    scored_with_verdict = {**scored, "verdict": verdict}
    compare_msgs = _compare_vacuous_categories(scored_with_verdict, role="candidate")
    assert any("fabricated_fact" in m for m in compare_msgs)


def test_single_image_measurable_corpus_is_not_ready():  # VLM6-S2-05
    """One-item measurable corpus must not earn adoption pass (sample-size floor)."""
    record, entries = _two_image_measurable_pass_pair()
    record["items"] = record["items"][:1]
    entries = entries[:1]
    scored = score_run_record(record, entries)
    assert scored["counts"]["scored"] == 1
    assert scored["faces"]["identification"]["positional"]["compared_images"] >= 1
    assert scored["placement"]["claims"] >= 1
    assert scored["hallucination"]["images_with_traps"] >= 1
    assert scored["verdict"]["verdict"] == ScoreVerdict.NOT_READY.value
    assert any("sample-size" in r for r in scored["verdict"]["reasons"])


def test_order_unknown_excluded_not_folded_into_degraded_images():  # VLM6-S2-07
    """Positional exclusions must not invent degraded_images contract metadata."""
    record, entries = _run_record(), _manifest_entries()
    assert all(not e.get("face_boxes") for e in entries)
    scored = score_run_record(record, entries)
    ordering = scored["faces"]["identity_ordering"]
    assert ordering["order_unknown_excluded"] >= 1
    assert ordering["degraded_images"] == 0
    assert ordering["degraded_paths"] == []


def test_markdown_renders_null_provenance_as_null_not_none():  # VLM6-S4-05
    """JSON null provenance must render as the token null, not Python None."""
    from scripts.eval_harness.report import _fmt_prov, _markdown

    assert _fmt_prov(None) == "null"
    assert _fmt_prov("abc") == "abc"
    record, entries = _two_image_measurable_pass_pair()
    scored = score_run_record(record, entries)
    scored["provenance"]["head_sha"] = None
    scored["provenance"]["started_at"] = None
    md = _markdown(scored)
    assert "started_at: null" in md
    assert "started_at: None" not in md
    assert "head_sha: `null`" in md
    assert "head_sha: `None`" not in md


def test_score_verdict_enum_includes_non_comparable():  # VLM6-S2-09
    assert ScoreVerdict.NON_COMPARABLE.value == "non_comparable"
    assert set(ScoreVerdict) >= {
        ScoreVerdict.PASS,
        ScoreVerdict.FAIL,
        ScoreVerdict.PASS_UNGATED,
        ScoreVerdict.NOT_READY,
        ScoreVerdict.NON_COMPARABLE,
    }


def test_face_markdown_renders_null_and_bool_json_tokens():  # HARM-04 / S4-05
    """Face MD must use _fmt_prov for nulls/bools and emit started_at."""
    from scripts.eval_harness.report import _fmt_prov, _markdown_face

    assert _fmt_prov(None) == "null"
    assert _fmt_prov(False) == "false"
    assert _fmt_prov(True) == "true"
    # Empty string → default remains live for non-head_sha producers (VLM6-R2-A-04).
    assert _fmt_prov("") == "unknown"
    assert _fmt_prov("", default="missing") == "missing"
    face_run, manifest = _face_fixture_corpus()
    scored = score_face_run_record(face_run, manifest, score_manifest_sha256="s" * 64)
    scored["provenance"]["head_sha"] = None
    scored["provenance"]["started_at"] = None
    scored["provenance"]["zero_box_corpus"] = False
    md = _markdown_face(scored)
    assert "started_at: null" in md
    assert "started_at: None" not in md
    assert "head_sha: `null`" in md
    assert "zero_box_corpus: false" in md
    assert "zero_box_corpus: False" not in md
    assert "directional=true" in md or "directional=false" in md
    assert "directional=True" not in md
    assert "directional=False" not in md
    # VLM6-R2-A-04: coupling_flag must not render raw Python False/True.
    assert "coupling_flag=false" in md or "coupling_flag=true" in md
    assert "coupling_flag=False" not in md
    assert "coupling_flag=True" not in md


def test_sample_size_in_shared_vacuity_predicate_blocks_compare():  # RV1-02
    """Forged verdict=pass + scored=1 must be vacuous so compare cannot adopt.

    Pre-fix: sample-size lived only in build_score_vacuity_reasons; compare
    consulted score_vacuous_category_labels and accepted the forgery.
    """
    from scripts.eval_harness.cli import _compare_vacuous_categories
    from scripts.eval_harness.report import score_vacuous_category_labels

    forged = _passable_scored_dict()
    forged["counts"] = {"total": 1, "scored": 1, "failed": 0}
    forged["verdict"] = {
        "verdict": ScoreVerdict.PASS.value,
        "reasons": [],
        "wrong_name_rate": 0.0,
    }
    labels = score_vacuous_category_labels(forged, include_verdict_fields=True)
    assert "sample_size" in labels
    msgs = _compare_vacuous_categories(forged, role="candidate")
    assert any("sample_size" in m for m in msgs), msgs


def test_undersized_but_gt1_corpus_is_not_ready():  # RV1-03
    """n=2 measurable corpus is not_ready under SCORE_PASS_MIN_SCORED_IMAGES=5."""
    from scripts.eval_harness.report import SCORE_PASS_MIN_SCORED_IMAGES

    assert SCORE_PASS_MIN_SCORED_IMAGES >= 5
    record, entries = _two_image_measurable_pass_pair()
    record["items"] = record["items"][:2]
    entries = entries[:2]
    scored = score_run_record(record, entries)
    assert scored["counts"]["scored"] == 2
    assert scored["verdict"]["verdict"] == ScoreVerdict.NOT_READY.value
    assert any("sample-size" in r for r in scored["verdict"]["reasons"])


def test_public_path_lists_opaque_no_space_identity_slug():  # RV4-01 / TEST-15
    """Nested path lists emit media_id:N; no-space identity slug must be absent."""
    private_slug = "JaneDoePrivate"
    record, entries = _audience_fixtures()
    # Publishable path with no-space identity slug (evades space-basename heuristic).
    # Name lives ONLY in the path — not as a per_identity key (that's a different surface).
    leak_path = f"celebs01/{private_slug}-with-obama.jpg"
    record["items"] = [record["items"][0]]
    record["items"][0]["path"] = leak_path
    entries = [entries[0]]
    entries[0]["path"] = leak_path
    local = score_run_record(record, entries)
    # Inject path into nested lists that PUBLIC must scrub (RV4-01 surfaces).
    local["faces"]["identification"]["excluded_images"] = [leak_path]
    local["faces"]["identification"]["positional"]["excluded_images"] = [leak_path]
    local["faces"]["identity_ordering"]["degraded_paths"] = [leak_path]
    assert private_slug in json.dumps(local)

    from scripts.eval_harness.report import _redact_caption_report_for_public

    redacted = _redact_caption_report_for_public(local, run_record=record, manifest_entries=entries)
    blob = json.dumps(redacted)
    assert private_slug not in blob, blob
    assert leak_path not in blob
    pos_excl = redacted["faces"]["identification"]["positional"]["excluded_images"]
    assert pos_excl == ["media_id:10"], pos_excl
    assert redacted["faces"]["identification"]["excluded_images"] == ["media_id:10"]
    assert redacted["faces"]["identity_ordering"]["degraded_paths"] == ["media_id:10"]
    assert redacted["per_image"][0]["path"] == "media_id:10"


def test_public_scrubs_case_and_slug_identity_variants():  # RV4-05 / TEST-15
    """Lowercased and slugified private names must be absent from PUBLIC blob."""
    private = "Jane Doe Private"
    record, entries = _audience_fixtures()
    # Keep both publishable + private rows so private is on the scrub roster but
    # not a publishable per_identity key.
    record, entries = _audience_fixtures()
    local = score_run_record(record, entries)
    # Publishable row free-text carries case/slug variants of the private name.
    pub = next(r for r in local["per_image"] if r["media_id"] == 10)
    pub["short_error"] = "timeout involving jane doe private and JaneDoePrivate and jane-doe-private"
    pub["path"] = "celebs01/jane-doe-private-with-obama.jpg"
    # Pre-control: variants live in local doc.
    blob_local = json.dumps(local)
    assert "jane doe private" in blob_local or "JaneDoePrivate" in blob_local

    from scripts.eval_harness.report import _redact_caption_report_for_public, _scrub_identity_names

    # Unit: scrub hits case/slug folds.
    scrubbed = _scrub_identity_names(
        "saw jane doe private and JaneDoePrivate and jane-doe-private",
        [private],
    )
    assert "jane doe private" not in scrubbed.casefold()
    assert "janedoeprivate" not in scrubbed.replace("[redacted]", "").casefold().replace("-", "").replace("_", "")
    assert "[redacted]" in scrubbed

    redacted = _redact_caption_report_for_public(local, run_record=record, manifest_entries=entries)
    blob = json.dumps(redacted)
    assert private not in blob
    assert "JaneDoePrivate" not in blob
    assert "jane doe private" not in blob
    assert "jane-doe-private" not in blob
    pub_out = next(r for r in redacted["per_image"] if r["media_id"] == 10)
    assert pub_out["path"] == "media_id:10"
    assert pub_out["short_error"] in ("<redacted>", "<error>")


# ---------------------------------------------------------------------------
# VLM-6 Wave D / lane wd-A — ordering disclosure + detection sampling frame
# ---------------------------------------------------------------------------


def _ordering_disclosure_pair() -> tuple[dict, list[dict]]:
    """One image with order_degraded GT + one fully-coordinated sibling.

    Image 1: cx1 G-01 mixed y (A/B real y, C missing y) → order_degraded=True.
    Image 2: both named boxes carry x+y → order_degraded=False.
    Aggregate labeled_y_missing_images must be 1, not 0/2, and must not fold
    into degraded_images (predicted stamp is positional on both).
    """
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
                "media_id": 1,
                "path": "/ops/private/lane-wda/group-y-missing.jpg",
                "describe": {
                    "alt_text_draft": "Three people stand together.",
                    "visual_facts": {"caption": "people", "objects": []},
                    "adapter": "seeded",
                    "model_id": "seeded-fixtures",
                    "model_version": "1",
                    "cached": False,
                },
                "identities": [
                    {
                        "name": "C",
                        "bbox": {"x": 10.0, "y": 10.0, "width": 20.0, "height": 20.0},
                        "unpositioned": False,
                    }
                ],
                "face_count": 3,
                "identity_ordering": "positional",
                "error": None,
            },
            {
                "media_id": 2,
                "path": "celebs01/full-coords.jpg",
                "describe": {
                    "alt_text_draft": "Two people stand together.",
                    "visual_facts": {"caption": "people", "objects": []},
                    "adapter": "seeded",
                    "model_id": "seeded-fixtures",
                    "model_version": "1",
                    "cached": False,
                },
                "identities": [
                    {
                        "name": "D",
                        "bbox": {"x": 10.0, "y": 10.0, "width": 20.0, "height": 20.0},
                        "unpositioned": False,
                    }
                ],
                "face_count": 2,
                "identity_ordering": "positional",
                "error": None,
            },
        ],
    }
    entries = [
        {
            "path": "/ops/private/lane-wda/group-y-missing.jpg",
            "media_id": 1,
            "face_count": 3,
            "present_identities": ["A", "B", "C"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [
                {"x": 0.5, "y": 0.9, "w": 0.1, "h": 0.1, "name": "A"},
                {"x": 0.5, "y": 0.1, "w": 0.1, "h": 0.1, "name": "B"},
                {"x": 0.2, "y": None, "w": 0.1, "h": 0.1, "name": "C"},
            ],
            "provenance": {"source": "operator", "license": "consented", "publishable": False},
        },
        {
            "path": "celebs01/full-coords.jpg",
            "media_id": 2,
            "face_count": 2,
            "present_identities": ["D", "E"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [
                {"x": 0.2, "y": 0.4, "w": 0.1, "h": 0.1, "name": "D"},
                {"x": 0.8, "y": 0.4, "w": 0.1, "h": 0.1, "name": "E"},
            ],
            "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
        },
    ]
    return record, entries


def test_labeled_y_missing_images_aggregates_order_degraded():  # VLM6-R2-G-01 / wd-A
    """Report must aggregate labeled_order.order_degraded into its own counter.

    TEST-15: count must be 1 for the mixed fixture (not a constant 0, not 2).
    S2-07 / rg-015: must NOT overload degraded_images (predicted stamp).
    """
    from scripts.eval_harness.face_metrics import labeled_order

    record, entries = _ordering_disclosure_pair()
    # Precondition: face_boxes really trigger order_degraded on image 1 only.
    r0 = labeled_order(entries[0]["face_boxes"])
    r1 = labeled_order(entries[1]["face_boxes"])
    assert r0.order_degraded is True and r0.names == ["C", "B", "A"]
    assert r1.order_degraded is False

    scored = score_run_record(record, entries)
    ordering = scored["faces"]["identity_ordering"]
    assert "labeled_y_missing_images" in ordering
    assert ordering["labeled_y_missing_images"] == 1
    assert ordering["labeled_y_missing_paths"] == ["/ops/private/lane-wda/group-y-missing.jpg"]
    # Predicted stamp is POSITIONAL on both — do not overload degraded_*.
    assert ordering["degraded_images"] == 0
    assert ordering["degraded_paths"] == []
    assert ordering["positional_images"] == 2


def test_labeled_y_missing_paths_public_redacted():  # VLM6-R2-A-02 / wd-A Task 3
    """labeled_y_missing_paths carries operator paths — PUBLIC must scrub them.

    Private absolute path must not survive the caption PUBLIC export (same
    contract as degraded_paths). Labeled-y-missing int counter may remain.
    """
    from scripts.eval_harness.report import _redact_caption_report_for_public

    record, entries = _ordering_disclosure_pair()
    local = score_run_record(record, entries)
    leak = "/ops/private/lane-wda/group-y-missing.jpg"
    assert leak in local["faces"]["identity_ordering"]["labeled_y_missing_paths"]
    assert leak in json.dumps(local)

    redacted = _redact_caption_report_for_public(
        local, run_record=record, manifest_entries=entries
    )
    blob = json.dumps(redacted)
    assert leak not in blob
    assert "/ops/private" not in blob
    # Private media is unpublished → path list drops (publishable-only keep),
    # or collapses to media_id:N if kept. Either way no operator path survives.
    paths = redacted["faces"]["identity_ordering"]["labeled_y_missing_paths"]
    assert all(not (isinstance(p, str) and p.startswith("/")) for p in paths)
    assert all("/ops/" not in str(p) for p in paths)
    # Int counter is not a path — must survive PUBLIC (not provenance allow-list).
    assert redacted["faces"]["identity_ordering"]["labeled_y_missing_images"] == 1


def test_face_detection_carries_sampling_frame():  # VLM6-R2-C-02 / wd-A
    """Face bakeoff detection object must publish sampling_frame (string).

    Shape matches floor-gated slices (str protocol description). Arithmetic
    (tp/fp/fn/precision/recall) must be unchanged by the disclosure field.
    TEST-15: key alone is not enough — type/non-empty + arithmetic pin.
    """
    face_run, manifest = _face_fixture_corpus()
    scored = score_face_run_record(face_run, manifest, score_manifest_sha256="s" * 64)
    det = scored["detection"]
    assert "sampling_frame" in det
    assert isinstance(det["sampling_frame"], str)
    assert det["sampling_frame"]  # non-empty
    # Same type/shape as a floor-gated slice sampling_frame.
    hl_frame = scored["slices"]["headline_identification"]["sampling_frame"]
    assert type(det["sampling_frame"]) is type(hl_frame) is str
    # Provenance sampling_frames map includes detection (same dict source).
    assert "detection" in scored["provenance"]["sampling_frames"]
    assert scored["provenance"]["sampling_frames"]["detection"] == det["sampling_frame"]
    # Arithmetic pin (fixture: 3 matched, 0 miss/fp) — disclosure is additive only.
    assert det["tp"] == 3
    assert det["fp"] == 0
    assert det["fn"] == 0
    assert det["precision"] == pytest.approx(1.0)
    assert det["recall"] == pytest.approx(1.0)
    # Population language must name the GT-box unit (operator can read the frame).
    frame = det["sampling_frame"].casefold()
    assert "gt" in frame or "box" in frame
    assert "associat" in frame or "scoreable" in frame or "media" in frame


def _face_y_missing_fixture() -> tuple[dict, dict]:
    """Face run + manifest with one order_degraded image (mixed missing y) + clean sibling."""
    dim = 8
    alice = _unit([1.0] + [0.0] * (dim - 1))
    bob = _unit([0.0, 1.0] + [0.0] * (dim - 2))
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
                "path": "/ops/private/lane-wg1/group-y-missing.jpg",
                "model_id": "ort-yunet-sface",
                "embedding_dim": dim,
                "image_size": [100, 100],
                # Zero dets: order_degraded trap must not float()-coerce null y (wF4).
                "faces": [],
            },
            {
                "media_id": 2,
                "path": "celebs01/clean-pair.jpg",
                "model_id": "ort-yunet-sface",
                "embedding_dim": dim,
                "image_size": [100, 100],
                "faces": [
                    _face_det([10.0, 20.0, 30.0, 30.0], alice),
                    _face_det([50.0, 20.0, 30.0, 30.0], bob),
                ],
            },
        ],
    }
    manifest = {
        "roster": ["Alice Example", "Bob Example"],
        "roster_cohorts": {"Alice Example": "cohort_a", "Bob Example": "cohort_b"},
        "entries": [
            {
                "path": "/ops/private/lane-wg1/group-y-missing.jpg",
                "media_id": 1,
                "face_count": 2,
                "present_identities": ["Alice Example", "Bob Example"],
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                # Mixed: Bob has y, Alice missing y, same x → order_degraded.
                "face_boxes": [
                    {"x": 0.5, "y": 0.1, "w": 0.2, "h": 0.2, "name": "Bob Example"},
                    {"x": 0.5, "w": 0.2, "h": 0.2, "name": "Alice Example"},  # no y
                ],
                "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
            },
            {
                "path": "celebs01/clean-pair.jpg",
                "media_id": 2,
                "face_count": 2,
                "present_identities": ["Alice Example", "Bob Example"],
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [
                    _gt_box(0.25, 0.35, 0.3, 0.3, "Alice Example"),
                    _gt_box(0.65, 0.35, 0.3, 0.3, "Bob Example"),
                ],
                "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
            },
        ],
    }
    return face_run, manifest


def test_face_bakeoff_publishes_labeled_y_missing_identity_ordering():  # wG1 / VLM6-R2-G-01
    """Face score_face_run_record must publish identity_ordering.labeled_y_missing_*.

    wF4 residual: counter lived only on caption score_run_record; face freeze
    could not pin it. Field names/semantics match caption faces.identity_ordering.
    Denominator = counts.scored (same scoreable set).
    """
    from scripts.eval_harness.face_metrics import labeled_order

    face_run, manifest = _face_y_missing_fixture()
    r0 = labeled_order(manifest["entries"][0]["face_boxes"])
    r1 = labeled_order(manifest["entries"][1]["face_boxes"])
    assert r0.order_degraded is True
    assert r1.order_degraded is False

    scored = score_face_run_record(face_run, manifest, score_manifest_sha256="s" * 64)
    assert "identity_ordering" in scored
    ordering = scored["identity_ordering"]
    # Same keys as caption faces.identity_ordering.
    for key in (
        "positional_images",
        "degraded_images",
        "degraded_paths",
        "order_unknown_excluded",
        "labeled_y_missing_images",
        "labeled_y_missing_paths",
    ):
        assert key in ordering, f"missing identity_ordering.{key}"
    assert ordering["labeled_y_missing_images"] == 1
    assert ordering["labeled_y_missing_paths"] == ["/ops/private/lane-wg1/group-y-missing.jpg"]
    # Predicted stamps absent on face walk items → honest 0 (not invented degraded).
    assert ordering["degraded_images"] == 0
    assert ordering["degraded_paths"] == []
    assert ordering["positional_images"] == 0
    # order_degraded image is positional-excluded (caption semantics).
    assert ordering["order_unknown_excluded"] >= 1
    # Denominator honesty: counter is out of scored images.
    assert scored["counts"]["scored"] == 2
    assert ordering["labeled_y_missing_images"] <= scored["counts"]["scored"]


def test_face_identity_ordering_matches_caption_on_same_corpus():  # wG1
    """Face identity_ordering GT counters must match caption aggregation on same boxes.

    Two names for one quantity is the divergence this wave sequence eliminates.
    Predicted stamp counters may differ when face items lack identity_ordering
    stamps (face walk never stamps them) — only GT-side fields must agree.
    """
    face_run, manifest = _face_y_missing_fixture()
    face_scored = score_face_run_record(face_run, manifest, score_manifest_sha256="s" * 64)

    entries = list(manifest["entries"])
    cap_items = [
        {
            "media_id": e["media_id"],
            "path": e["path"],
            "model_id": "x",
            "describe": {"alt_text_draft": "placeholder"},
            "identity_ordering": "positional",
            "image_width": 100,
            "image_height": 100,
        }
        for e in entries
    ]
    cap = score_run_record(
        {
            "kind": "run_record",
            "schema_version": 1,
            "items": cap_items,
            "provenance": {
                "manifest_sha256": "m" * 64,
                "model_id": "x",
                "leg": "candidate",
            },
        },
        entries,
    )
    face_io = face_scored["identity_ordering"]
    cap_io = cap["faces"]["identity_ordering"]
    assert face_io["labeled_y_missing_images"] == cap_io["labeled_y_missing_images"] == 1
    assert face_io["labeled_y_missing_paths"] == cap_io["labeled_y_missing_paths"]
    # order_unknown_excluded: caption also excludes order_degraded; face matches GT side.
    assert face_io["order_unknown_excluded"] == cap_io["order_unknown_excluded"]


def test_face_labeled_y_missing_paths_public_redacted():  # wG1 / VLM6-R2-A-02
    """Face PUBLIC export must scrub labeled_y_missing_paths (operator paths)."""
    face_run, manifest = _face_y_missing_fixture()
    local = score_face_run_record(face_run, manifest, score_manifest_sha256="s" * 64)
    leak = "/ops/private/lane-wg1/group-y-missing.jpg"
    assert leak in local["identity_ordering"]["labeled_y_missing_paths"]

    redacted = redact_face_report_for_public(local)
    blob = json.dumps(redacted)
    assert leak not in blob
    assert "/ops/private" not in blob
    paths = redacted["identity_ordering"]["labeled_y_missing_paths"]
    assert all(not (isinstance(p, str) and (p.startswith("/") or "/ops/" in p)) for p in paths)
    # Int counter survives PUBLIC.
    assert redacted["identity_ordering"]["labeled_y_missing_images"] == 1


def test_face_labeled_y_missing_constant_zero_mutation_diverges(
    monkeypatch: pytest.MonkeyPatch,
):  # wG1 TEST-15
    """Acceptance: constant-0 aggregation of order_degraded must diverge on face path.

    Same bar as wF4 caption-path control, but on score_face_run_record so the
    face freeze can pin the counter after regeneration.
    """
    from scripts.eval_harness.face_metrics import LabeledOrderResult, labeled_order
    import scripts.eval_harness.report as report_mod

    face_run, manifest = _face_y_missing_fixture()
    live = score_face_run_record(face_run, manifest, score_manifest_sha256="s" * 64)
    live_n = int(live["identity_ordering"]["labeled_y_missing_images"])
    assert live_n >= 1

    real_lo = labeled_order

    def _blind_constant_zero(face_boxes):  # type: ignore[no-untyped-def]
        result = real_lo(face_boxes)
        return LabeledOrderResult(names=result.names, y_missing_count=0, order_degraded=False)

    monkeypatch.setattr(report_mod, "labeled_order", _blind_constant_zero)
    blind = score_face_run_record(face_run, manifest, score_manifest_sha256="s" * 64)
    blind_n = int(blind["identity_ordering"]["labeled_y_missing_images"])
    assert blind_n == 0
    assert blind_n != live_n, (
        f"constant-0 mutation still matches live ({live_n}) — face freeze cannot "
        "see labeled_y_missing regressions (TEST-15 blindness not closed)"
    )


# ---------------------------------------------------------------------------
# VLM-6 Wave H / lane wH1 — publish geometry_incomplete_* on face detection
# ---------------------------------------------------------------------------


def _face_geometry_incomplete_fixture() -> tuple[dict, dict]:
    """Face run + manifest: one geometry-incomplete named GT + complete siblings.

    Media 1: Alice (null y) + Bob (complete y), zero detections — Alice is
    geometry-incomplete (not FN); Bob is complete unmatched (FN).
    Media 2: clean Alice+Bob pair with matching detections.
    """
    dim = 8
    alice = _unit([1.0] + [0.0] * (dim - 1))
    bob = _unit([0.0, 1.0] + [0.0] * (dim - 2))
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
                "path": "/ops/private/lane-wh1/group-y-missing.jpg",
                "model_id": "ort-yunet-sface",
                "embedding_dim": dim,
                "image_size": [100, 100],
                "faces": [],
            },
            {
                "media_id": 2,
                "path": "celebs01/clean-pair.jpg",
                "model_id": "ort-yunet-sface",
                "embedding_dim": dim,
                "image_size": [100, 100],
                "faces": [
                    _face_det([10.0, 20.0, 30.0, 30.0], alice),
                    _face_det([50.0, 20.0, 30.0, 30.0], bob),
                ],
            },
        ],
    }
    manifest = {
        "roster": ["Alice Example", "Bob Example"],
        "roster_cohorts": {"Alice Example": "cohort_a", "Bob Example": "cohort_b"},
        "entries": [
            {
                "path": "/ops/private/lane-wh1/group-y-missing.jpg",
                "media_id": 1,
                "face_count": 2,
                "present_identities": ["Alice Example", "Bob Example"],
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [
                    {"x": 0.5, "y": 0.1, "w": 0.2, "h": 0.2, "name": "Bob Example"},
                    {"x": 0.5, "w": 0.2, "h": 0.2, "name": "Alice Example"},  # no y
                ],
                "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
            },
            {
                "path": "celebs01/clean-pair.jpg",
                "media_id": 2,
                "face_count": 2,
                "present_identities": ["Alice Example", "Bob Example"],
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [
                    _gt_box(0.25, 0.35, 0.3, 0.3, "Alice Example"),
                    _gt_box(0.65, 0.35, 0.3, 0.3, "Bob Example"),
                ],
                "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
            },
        ],
    }
    return face_run, manifest


def test_face_detection_publishes_geometry_incomplete_stamp():  # wH1 / wG2 residual 1
    """Face detection block must publish geometry_incomplete_* / association_complete.

    Stamp exists on AssignmentResult (wG2) but was invisible on the report
    surface — freeze could not pin it (rg-015 one level up). Fields come from
    the assignment stamp, not a boundary recount.
    Denominator: geometry_incomplete_gt out of n_gt (= tp+fn+incomplete);
    association_incomplete_media out of counts.scored.
    """
    face_run, manifest = _face_geometry_incomplete_fixture()
    scored = score_face_run_record(face_run, manifest, score_manifest_sha256="s" * 64)
    det = scored["detection"]
    for key in (
        "geometry_incomplete_gt",
        "association_incomplete_media",
        "association_complete",
    ):
        assert key in det, f"missing detection.{key}"
    assert det["geometry_incomplete_gt"] == 1
    assert det["association_incomplete_media"] == 1
    assert det["association_complete"] is False
    # Arithmetic: Alice incomplete + Bob FN on media1 + 2 TP on media2.
    assert det["tp"] == 2
    assert det["fn"] == 1  # Bob complete miss only — Alice NOT re-absorbed as FN
    n_gt = det["tp"] + det["fn"] + det["geometry_incomplete_gt"]
    assert n_gt == 4
    assert det["geometry_incomplete_gt"] <= n_gt
    assert det["association_incomplete_media"] <= scored["counts"]["scored"]
    # Sampling frame discloses geometry-incomplete exclusion (EVAL-03).
    frame = det["sampling_frame"]
    assert "geometry_incomplete" in frame
    assert "tp+fn+geometry_incomplete_gt" in frame
    assert "tp+fn equals GT boxes that reached association" not in frame
    # Provenance map shares the same string.
    assert scored["provenance"]["sampling_frames"]["detection"] == frame


def test_detection_from_assignment_publishes_stamp_not_recount():  # wH1 / rg-015
    """geometry_incomplete_* must be the AssignmentResult stamp, not a recount.

    Wire assignment.geometry_incomplete_gt to a deliberate value that would
    disagree with a pairs+unmatched+incomplete recount of association_by_media
    if the report re-derived it — the published field must still equal the stamp.
    """
    from scripts.eval_harness.face_assignment import AssignmentResult, AssociationResult
    from scripts.eval_harness.report import _detection_from_assignment

    class _Pair:
        def __init__(self) -> None:
            self.det_index = 0
            self.gt_index = 0

    assoc = AssociationResult(
        pairs=(_Pair(),),
        unmatched_detections=(),
        unmatched_gt=(),
        ious=(),
        geometry_incomplete_gt=(1,),  # one incomplete on this media
    )
    # Stamp deliberately disagrees with len(assoc.geometry_incomplete_gt) sum
    # if a future caller forgot to propagate — report must still publish stamp.
    assignment = AssignmentResult(
        matched=(),
        decisions=(),
        tau_k=(),
        tau_op=0.5,
        association_by_media={1: assoc},
        false_detections=0,
        missed_gt=0,
        missed_stranger_gt=0,
        geometry_incomplete_gt=7,  # stamp value (not re-derived from assoc)
        association_incomplete_media=3,
    )
    det = _detection_from_assignment(assignment)
    assert det["geometry_incomplete_gt"] == 7
    assert det["association_incomplete_media"] == 3
    assert det["association_complete"] is False
    # Incomplete must not inflate FN (stamp path only for misses).
    assert det["fn"] == 0
    assert det["tp"] == 1


def test_detection_incomplete_not_reabsorbed_as_fn():  # wH1 Task 3
    """Report path must not re-count geometry-incomplete boxes as detection FN.

    wG2 excluded them at associate_detections; publication must preserve that
    exclusion end-to-end (sr-001: do not adjust arithmetic to make text true).
    """
    face_run, manifest = _face_geometry_incomplete_fixture()
    scored = score_face_run_record(face_run, manifest, score_manifest_sha256="s" * 64)
    det = scored["detection"]
    # 1 incomplete + 1 complete miss + 2 matched = 4 GT; fn is complete-only.
    assert det["geometry_incomplete_gt"] == 1
    assert det["fn"] == 1
    assert det["tp"] == 2
    assert det["tp"] + det["fn"] + det["geometry_incomplete_gt"] == 4
    # If incomplete were re-absorbed: fn would be 2 and incomplete 0 or ignored.
    assert det["fn"] != det["fn"] + det["geometry_incomplete_gt"]


def test_face_geometry_incomplete_constant_zero_mutation_diverges(
    monkeypatch: pytest.MonkeyPatch,
):  # wH1 TEST-15
    """Acceptance: constant-0 stamp of geometry_incomplete must diverge on face path.

    Separates pre-existing freeze staleness from counter observability: compare
    live vs mutated re-scores on detection.geometry_incomplete_gt specifically,
    not the freeze pass/fail bit.
    """
    from dataclasses import replace

    import scripts.eval_harness.report as report_mod
    from scripts.eval_harness.face_assignment import score_face_assignment

    face_run, manifest = _face_geometry_incomplete_fixture()
    live = score_face_run_record(face_run, manifest, score_manifest_sha256="s" * 64)
    live_n = int(live["detection"]["geometry_incomplete_gt"])
    assert live_n >= 1
    assert live["detection"]["association_complete"] is False

    real_sfa = score_face_assignment

    def _blind_constant_zero(run_items, gt_by_media, **kwargs):  # type: ignore[no-untyped-def]
        result = real_sfa(run_items, gt_by_media, **kwargs)
        return replace(
            result,
            geometry_incomplete_gt=0,
            association_incomplete_media=0,
        )

    monkeypatch.setattr(report_mod, "score_face_assignment", _blind_constant_zero)
    blind = score_face_run_record(face_run, manifest, score_manifest_sha256="s" * 64)
    blind_n = int(blind["detection"]["geometry_incomplete_gt"])
    assert blind_n == 0
    assert blind["detection"]["association_complete"] is True
    assert blind_n != live_n, (
        f"constant-0 mutation still matches live ({live_n}) — face freeze cannot "
        "see geometry_incomplete regressions (TEST-15 blindness not closed)"
    )
    # FN arithmetic must be unchanged by the stamp-only mutation (sr-001).
    assert blind["detection"]["fn"] == live["detection"]["fn"]
    assert blind["detection"]["tp"] == live["detection"]["tp"]


def test_face_detection_sampling_frame_discloses_geometry_incomplete():  # wH1 residual 2
    """Detection sampling_frame must state the real post-wG2 population identity.

    Pre-wH1 text claimed tp+fn equals every GT that reached association; after
    geometry-incomplete exclusion that identity is wrong (EVAL-03).
    """
    from scripts.eval_harness.report import FACE_BAKEOFF_SAMPLING_FRAMES

    frame = FACE_BAKEOFF_SAMPLING_FRAMES["detection"]
    assert "geometry_incomplete_gt" in frame
    assert "tp+fn+geometry_incomplete_gt equals" in frame
    assert "not detector FN" in frame or "not detector fn" in frame.casefold()
    # Obsolete claim must be gone.
    assert "tp+fn equals GT boxes that reached association" not in frame
    # End-to-end: published detection block carries the registry string.
    face_run, manifest = _face_geometry_incomplete_fixture()
    scored = score_face_run_record(face_run, manifest, score_manifest_sha256="s" * 64)
    assert scored["detection"]["sampling_frame"] == frame


def _scored_face_md_stub(*, traps: list[dict] | None, fn: int = 5, scored: int = 11) -> dict:
    """Minimal scored face report for MD-renderer unit tests (no live scorer)."""
    return {
        "schema": "acx-eval/v1",
        "kind": "report",
        "report_kind": "face_bakeoff",
        "provenance": {"corpus_traps": traps or [], "head_sha": None, "started_at": None},
        "detection": {
            "precision": 0.857,
            "recall": 0.545,
            "tp": 6,
            "fp": 1,
            "fn": fn,
            "sampling_frame": "all_gt_boxes_on_scoreable_media_via_association",
        },
        "counts": {"scored": scored, "total": scored, "failed": 0, "matched_faces": 0},
        "slices": {},
        "gate_proposal": {},
    }


def test_fixture_local_detection_caveat_filters_on_affects_only():  # VLM6-R2-C-02
    """Renderer unit: caveat keys on affects=detection_fn, never kind/media id.

    N is the matching trap-media count, never trap-attributed FN (rg-015).
    A trap whose kind looks like HARM-05 but has no affects (or a different
    affect) must not emit the line.
    """
    assert CORPUS_TRAP_AFFECTS_DETECTION_FN == "detection_fn"
    traps = [
        {
            "media_id": 99,
            "path": "fixture/trap-a.jpg",
            "kind": "NOT_A_HARM_TOKEN",
            "affects": [CORPUS_TRAP_AFFECTS_DETECTION_FN],
        },
        {
            "media_id": 11,
            "path": "celebs01/y-missing-mixed-order.jpg",
            "kind": "HARM-05_must_not_match_on_kind",
            "affects": ["identity_ordering"],
        },
    ]
    line = _fixture_local_detection_caveat_line(traps=traps, fn=5, scored_images=11)
    assert line is not None
    assert "fixture-local detection frame" in line
    assert "recall is NOT a population estimate" in line
    assert "fn=5 includes misses from 1 deliberate trap media" in line
    # Defect pin: N is trap MEDIA. "{n} of fn=" reads as an FN share (rg-015).
    assert "1 of fn=" not in line
    assert "the FN share attributable to them is not derivable from this table" in line
    assert "99 `fixture/trap-a.jpg`" in line
    assert "y-missing-mixed-order.jpg" not in line
    assert "synthetic determinism anchor (11 images)" in line

    md = _markdown_face(_scored_face_md_stub(traps=traps, fn=5, scored=11))
    assert line in md
    # Immediately after the detection precision line (no geometry_incomplete here).
    det_idx = md.index("precision: 0.857 recall: 0.545")
    cav_idx = md.index("fixture-local detection frame")
    assert cav_idx > det_idx

    # Kind-only / media-id-only traps must not emit a phantom caveat (rg-009).
    kind_only = [
        {
            "media_id": 9,
            "path": "localwp/uploads/stranger-fn-miss.jpg",
            "kind": "HARM-05_pure_stranger_miss",
        },
        {
            "media_id": 10,
            "path": "localwp/uploads/mixed-fn-miss.jpg",
            "kind": "HARM-05_mixed_named_anonymous_miss",
        },
    ]
    assert _fixture_local_detection_caveat_line(traps=kind_only, fn=5, scored_images=11) is None
    assert "fixture-local detection frame" not in _markdown_face(
        _scored_face_md_stub(traps=kind_only)
    )
    # Stripped affects (real corpus / can-fail control) emits nothing.
    stripped = [{k: v for k, v in t.items() if k != "affects"} for t in traps]
    assert _fixture_local_detection_caveat_line(traps=stripped, fn=5, scored_images=11) is None
    assert "fixture-local detection frame" not in _markdown_face(
        _scored_face_md_stub(traps=stripped)
    )
    assert _fixture_local_detection_caveat_line(traps=[], fn=5, scored_images=11) is None
    assert _fixture_local_detection_caveat_line(traps=None, fn=5, scored_images=11) is None


# ---------------------------------------------------------------------------
# VLM-6 Wave E / lane wE1 — face PUBLIC redaction fail-closed + order_degraded
# ---------------------------------------------------------------------------


def test_face_public_export_no_private_name_or_operator_path_anywhere():  # wE1 acceptance
    """Single acceptance bar: no private name / operator path in serialised PUBLIC.

    Plants exercise every known leak vector (RF-01/02, RB-01..06, CDX-01) and
    assert recursively over the whole document (not per known key). Must go RED
    on unfixed redactor (TEST-15 / RE-01 / RB-07).
    """
    private = "Jane Roster Private"
    private_slug = "JaneRosterPrivate"
    abs_path = f"/home/ubuntu/secret/{private_slug}/face-run.json"
    report = {
        "schema": "acx-eval/v1",
        "kind": "report",
        "report_kind": "face_bakeoff",
        "provenance": {
            "head_sha": "0" * 40,
            "manifest_sha256": "m" * 64,
            "score_manifest_sha256": "s" * 64,
            "started_at": "2026-08-12T00:00:00Z",
            "canon_version": "v1",
            "protocol_id": "face-bakeoff",
            "zero_box_corpus": False,
            "total_gt_boxes": 1,
            "k_folds": {"requested": 5, "effective": 5, "clamped": False},
            # Allow-listed free text carrying secrets (RB-06).
            "tau_fit_status": f"fitted under {abs_path}",
            "sampling_frames": {"face_id": f"eval of {private}"},
            # Deny-listed (allow-list alone drops these).
            "cache_dir": f"/home/ubuntu/private/{private_slug}/cache",
            "operator_note": f"do not ship {private}",
        },
        "protocol_disclosures": [f"mean_prototype; exclude {private}"],  # RB-01 list[str]
        "gate_proposal": {
            "role": None,
            "excluded_directional": None,
            "p95_scan_latency": None,
            "scope_amendments_for_operator_ack": [f"ack {private}"],
            "error_context": abs_path,  # RB-03 non-path free text
            "identification_detection_coupling": {
                "detection_recall_coupling_flag": False,
                "missed_gt": None,
                "unmatched_detections": None,
            },
        },
        "decisions": [
            # Misidentified non-publishable named identity → wrong_names source (RF-01).
            {
                "media_id": 1,
                "publishable": False,
                "true_name": private,
                "predicted_name": "Alice Celeb",
                "name_star": "Alice Celeb",
                "path": f"/ops/localwp/{private_slug}.jpg",
                "decision": "accept",
            },
            # Publishable image referencing private gallery identity (CDX-01 / RB-04).
            {
                "media_id": 2,
                "publishable": True,
                "true_name": "Ada Lovelace",
                "predicted_name": private,
                "name_star": private,
                "path": "/public/ada.jpg",
                "decision": "reject",
            },
        ],
        "slices": {
            "headline_identification": {
                "precision": 0.0,
                "recall": 0.0,
                "precision_numerator": 0,
                "precision_denominator": 1,
                "recall_numerator": 0,
                "recall_denominator": 1,
                "n_named_probes": 1,
                "n_recall_eligible": 1,
                "sampling_frame": f"ops: {private} @ {abs_path}",  # RB-02
                "wrong_names": [[1, 0, private, "Alice Celeb"]],
                "ignored_wrong_names": [],
            },
            "full_corpus_identification": {
                "wrong_names": [[1, 0, private, "Alice Celeb"]],
                "ignored_wrong_names": [],
            },
            # RF-01: demographic copy never cleared by two-key enumeration.
            "demographic": {
                "by_cohort": {
                    "adult_f": {
                        "wrong_names": [[1, 0, private, "Alice Celeb"]],
                        "ignored_wrong_names": [],
                        "precision": 0.0,
                    }
                }
            },
            "unknown_rejection": {
                "rate": 1.0,
                "n": 1,
                "correct_rejects": 1,
                "rate_numerator": 1,
                "rate_denominator": 1,
                "sampling_frame": "strangers",
            },
            "clustering": {"labels": [0], "purity": 1.0},
        },
        "failures": [
            {"media_id": 1, "path": abs_path, "error": f"timeout involving {private}"},
        ],
        "counts": {"total": 2, "scored": 2, "failed": 1, "matched_faces": 1},
        "detection": {"precision": 1.0, "recall": 1.0, "tp": 1, "fp": 0, "fn": 0},
    }

    # Control: private material is live in the LOCAL-shaped report.
    pre = json.dumps(report)
    assert private in pre
    assert abs_path in pre

    redacted = redact_face_report_for_public(report)
    blob = json.dumps(redacted, sort_keys=True)
    md = __import__("scripts.eval_harness.report", fromlist=["_markdown_face"])._markdown_face(
        redacted
    )

    for token in (
        private,
        private_slug,
        "Jane Roster",
        "/home/ubuntu",
        "/ops/localwp",
        "/var/op",
        "face-run.json",
        abs_path,
    ):
        assert token not in blob, f"PUBLIC JSON leaked {token!r}"
        assert token not in md, f"PUBLIC MD leaked {token!r}"

    # Structure: wrong_names cleared everywhere including demographic.
    demo_rows = (
        ((redacted.get("slices") or {}).get("demographic") or {}).get("by_cohort") or {}
    )
    for cohort in demo_rows.values():
        if isinstance(cohort, dict):
            assert list(cohort.get("wrong_names") or []) == []

    # CDX-01: publishable Ada row may survive, but not with private predicted names.
    ada = [d for d in (redacted.get("decisions") or []) if d.get("true_name") == "Ada Lovelace"]
    assert ada, "publishable named decision should be retained"
    assert all(d.get("predicted_name") != private for d in ada)
    assert all(d.get("name_star") != private for d in ada)

    # RB-05: raw Python None/True/False must not appear in face markdown.
    assert re.search(r"\bNone\b", md) is None, md
    assert re.search(r"\bTrue\b", md) is None, md
    assert re.search(r"\bFalse\b", md) is None, md


def test_scrub_face_public_free_text_scrubs_list_str_elements():  # RB-01 / RF-02
    from scripts.eval_harness.report import _scrub_face_public_free_text

    names = ["Jane Doe Private"]
    obj = {
        "protocol_disclosures": ["mean_prototype; exclude Jane Doe Private"],
        "gate_proposal": {
            "scope_amendments_for_operator_ack": ["ack Jane Doe Private"],
            "flag_dict": {"msg": "dict path Jane Doe Private"},
        },
    }
    out = _scrub_face_public_free_text(obj, names)
    blob = json.dumps(out)
    assert "Jane Doe Private" not in blob
    assert out["gate_proposal"]["flag_dict"]["msg"] == "<redacted>"
    assert out["protocol_disclosures"][0] == "<redacted>"
    assert out["gate_proposal"]["scope_amendments_for_operator_ack"][0] == "<redacted>"


def test_order_degraded_excluded_from_positional_scoring():  # RA-01
    """Degraded L→R (missing y) must not score as full spatial ground truth.

    Invented alphabetical order on identical-x / no-y boxes previously produced
    position_accuracy=1.0 when the model emitted the same alpha order. Exclude
    order_degraded images from positional scoring; disclose via labeled_y_missing_*.
    """
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
                "media_id": 1,
                "path": "celebs01/alpha-invented.jpg",
                "describe": {
                    "alt_text_draft": "Alice and Bob stand together.",
                    "visual_facts": {"caption": "people", "objects": []},
                    "adapter": "seeded",
                    "model_id": "seeded-fixtures",
                    "model_version": "1",
                    "cached": False,
                },
                "identities": [
                    {
                        "name": "Alice",
                        "bbox": {"x": 10.0, "y": 10.0, "width": 20.0, "height": 20.0},
                        "unpositioned": False,
                    },
                    {
                        "name": "Bob",
                        "bbox": {"x": 50.0, "y": 10.0, "width": 20.0, "height": 20.0},
                        "unpositioned": False,
                    },
                ],
                "face_count": 2,
                "identity_ordering": "positional",
                "error": None,
                "image_width": 100,
                "image_height": 100,
            },
            {
                "media_id": 2,
                "path": "celebs01/full-coords.jpg",
                "describe": {
                    "alt_text_draft": "Carol stands alone.",
                    "visual_facts": {"caption": "person", "objects": []},
                    "adapter": "seeded",
                    "model_id": "seeded-fixtures",
                    "model_version": "1",
                    "cached": False,
                },
                "identities": [
                    {
                        "name": "Carol",
                        "bbox": {"x": 10.0, "y": 10.0, "width": 20.0, "height": 20.0},
                        "unpositioned": False,
                    }
                ],
                "face_count": 1,
                "identity_ordering": "positional",
                "error": None,
                "image_width": 100,
                "image_height": 100,
            },
        ],
    }
    entries = [
        {
            "path": "celebs01/alpha-invented.jpg",
            "media_id": 1,
            "face_count": 2,
            "present_identities": ["Alice", "Bob"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            # identical x, no y → order_degraded + alphabetical invent
            "face_boxes": [
                {"name": "Bob", "x": 0.5},
                {"name": "Alice", "x": 0.5},
            ],
            "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
        },
        {
            "path": "celebs01/full-coords.jpg",
            "media_id": 2,
            "face_count": 1,
            "present_identities": ["Carol"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [{"name": "Carol", "x": 0.2, "y": 0.4, "w": 0.1, "h": 0.1}],
            "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
        },
    ]
    scored = score_run_record(record, entries)
    pos = scored["faces"]["identification"]["positional"]
    ordering = scored["faces"]["identity_ordering"]
    assert ordering["labeled_y_missing_images"] == 1
    # Degraded image excluded from positional — only the fully-coordinated sibling.
    assert pos["compared_images"] == 1
    assert "celebs01/alpha-invented.jpg" in (pos.get("excluded_images") or [])
    # Must NOT report perfect accuracy from invented alphabetical order.
    assert pos["position_accuracy"] == pytest.approx(1.0)  # sibling exact match only
    assert pos["exact_order_images"] == 1


def test_empty_string_y_normalized_before_labeled_order_in_report():  # RA-04 boundary
    """Empty-string y must take the missing-y branch, not crash score_run_record.

    Source fix lives in face_metrics (cross-lane); report normalizes at the boundary.
    """
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
                "media_id": 1,
                "path": "celebs01/empty-y.jpg",
                "describe": {
                    "alt_text_draft": "A person.",
                    "visual_facts": {"caption": "person", "objects": []},
                    "adapter": "seeded",
                    "model_id": "seeded-fixtures",
                    "model_version": "1",
                    "cached": False,
                },
                "identities": [
                    {
                        "name": "Ada",
                        "bbox": {"x": 10.0, "y": 10.0, "width": 20.0, "height": 20.0},
                        "unpositioned": False,
                    }
                ],
                "face_count": 1,
                "identity_ordering": "positional",
                "error": None,
            }
        ],
    }
    entries = [
        {
            "path": "celebs01/empty-y.jpg",
            "media_id": 1,
            "face_count": 1,
            "present_identities": ["Ada"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [{"name": "Ada", "x": 0.5, "y": ""}],
            "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
        }
    ]
    scored = score_run_record(record, entries)  # must not raise
    assert scored["faces"]["identity_ordering"]["labeled_y_missing_images"] == 1


def test_low_sample_warning_surfaced_in_provenance():  # RF-15
    """Operator-facing low-sample caveat when scored < SCORE_PASS_MIN_SCORED_IMAGES.

    Constants stay at 5 / 0.5 — only disclosure is added (not an sr-001 loosen).
    """
    from scripts.eval_harness.report import SCORE_PASS_MIN_SCORED_IMAGES

    assert SCORE_PASS_MIN_SCORED_IMAGES == 5
    record, entries = _two_image_measurable_pass_pair()
    record["items"] = record["items"][:2]
    entries = entries[:2]
    scored = score_run_record(record, entries)
    assert scored["counts"]["scored"] == 2
    warn = scored["provenance"].get("low_sample_warning")
    assert warn, "low_sample_warning must be present for n<min"
    assert "scored=2" in str(warn) or "2" in str(warn)
    assert str(SCORE_PASS_MIN_SCORED_IMAGES) in str(warn)
    # Rendered surfaces must also show the caveat (comment rewrites alone fail RF-15).
    md = __import__("scripts.eval_harness.report", fromlist=["_markdown"])._markdown(scored)
    assert "low_sample" in md.casefold() or "sample" in md.casefold() and "warning" in md.casefold()


def test_path_basename_stems_not_over_scrubbed():  # RF-13
    """Harvest must not add short path basenames that corrupt unrelated free text."""
    from scripts.eval_harness.report import (
        _face_private_identity_names_for_public_scrub,
        redact_face_report_for_public,
    )

    report = {
        "provenance": {
            "head_sha": "0" * 40,
            "sampling_frames": {"detection": "alignment image_count check"},
        },
        "decisions": [
            {
                "media_id": 1,
                "publishable": False,
                "true_name": None,
                "predicted_name": None,
                "name_star": None,
                "path": "/ops/al.jpg",  # stem "al" must NOT become a scrub target
            }
        ],
        "slices": {},
        "failures": [],
        "protocol_disclosures": ["alignment image_count check"],
    }
    harvested = _face_private_identity_names_for_public_scrub(report)
    assert "al" not in harvested
    assert "img" not in harvested
    red = redact_face_report_for_public(report)
    # Unrelated protocol free text must survive (not collapsed by stem over-scrub).
    assert red["protocol_disclosures"] == ["alignment image_count check"]


def test_single_subject_cohort_namedness_agrees_with_face_metrics():  # wE4 → wF1
    """Cohort builder must use named_box_name — not raw name truthiness.

    Contract (TEST-06): agreement with face_metrics.named_box_name, not a
    hardcoded expected set. Whitespace-only ``"   "`` and ZWSP-prefixed
    ``"\\u200bAlice"`` must not diverge from the shared predicate.
    TEST-15: pre-fix raw ``if name`` counts whitespace as named.
    """
    cases = [
        {"name": "   ", "x": 0.5, "y": 0.5, "w": 0.1, "h": 0.1},
        {"name": "\u200bAlice", "x": 0.5, "y": 0.5, "w": 0.1, "h": 0.1},
        {"name": "Alice", "x": 0.5, "y": 0.5, "w": 0.1, "h": 0.1},
        {"name": "\u200b", "x": 0.5, "y": 0.5, "w": 0.1, "h": 0.1},
        {"name": "", "x": 0.5, "y": 0.5, "w": 0.1, "h": 0.1},
    ]
    for i, box in enumerate(cases):
        mid = i + 1
        entries = [
            {
                "media_id": mid,
                "demographic_cohort": f"cohort-{mid}",
                "provenance": {"source": "celeb"},
                "face_boxes": [box],
                "face_count": 1,
            }
        ]
        cohort = _build_single_subject_cohort_by_media(entries)
        pred_named = named_box_name(box) is not None
        in_cohort = mid in cohort
        assert in_cohort is pred_named, (
            f"media_id={mid} name={box['name']!r}: cohort={in_cohort} "
            f"named_box_name={named_box_name(box)!r}"
        )


def test_occlusion_named_filter_agrees_with_face_metrics():  # wE4 → wF1
    """Real-occlusion named filter + true_name must share named_box_name.

    Agreement with face_metrics (TEST-06), not a hardcoded name list.
    TEST-15: pre-fix raw truthiness admits whitespace-only / format-only.
    """
    boxes = [
        {"name": "   ", "x": 0.2, "y": 0.2, "w": 0.1, "h": 0.1},
        {"name": "\u200bAlice", "x": 0.5, "y": 0.5, "w": 0.1, "h": 0.1},
        {"name": "Bob", "x": 0.8, "y": 0.5, "w": 0.1, "h": 0.1},
        {"name": "\u200b", "x": 0.1, "y": 0.1, "w": 0.05, "h": 0.05},
    ]
    expected_names = [named_box_name(b) for b in boxes if named_box_name(b) is not None]
    assert expected_names  # fixture sanity: at least one named box
    manifest = {
        "entries": [
            {
                "media_id": 1,
                "path": "celebs01/occ.jpg",
                "tags": ["masked"],
                "face_boxes": boxes,
                "face_count": len(boxes),
                "present_identities": ["Alice", "Bob"],
                "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
            }
        ]
    }
    record = {
        "items": [
            {
                "media_id": 1,
                "faces": [],
                "image_size": [100, 100],
                "error": None,
            }
        ]
    }
    pairs = build_real_occlusion_pairs(record, manifest)
    true_names = [p["true_name"] for p in pairs.get("masked", [])]
    assert true_names == expected_names, (
        f"occlusion true_names={true_names!r} vs named_box_name path={expected_names!r}"
    )
