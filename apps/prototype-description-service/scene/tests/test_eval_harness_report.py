"""VLM-2A Slice 3: report builder + scoring pipeline — deterministic, golden-file style."""

import json

import pytest

from scripts.eval_harness.report import Audience, ReportError, build_reports, score_run_record


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
