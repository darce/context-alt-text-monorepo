"""FIR-11-S2R3-12 — report-layer detection coverage with entry-level stamps.

The scene report suite's unstamped fixtures take the refusal branch, so
PUBLIC rendering / determinism / redaction of a *present* detection
block is no longer exercised at this layer. Stamps live on entries, not
on a parent document: a document-level fill will not survive the
post-E1 resolver (FIR-11-S2R3-02).
"""

from __future__ import annotations

import json

import pytest

from scripts.eval_harness.manifest import ScoreInvariant
from scripts.eval_harness.report import Audience, build_reports, score_run_record

_LINEAGE = {
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

_LOCAL_PATH = "localwp/uploads/jane-doe-birthday.jpg"
_LOCAL_NAME = "Jane Doe Private"
_PUBLIC_PATH = "celebs01/obama-podium.jpg"
_PUBLIC_NAME = "Barack Obama"

# Default 3-item fixture: two scored faces + one failed item.
_DEFAULT_TP, _DEFAULT_FP, _DEFAULT_FN = 2, 0, 0
_LOCAL_TP = 2
# build_reports scores the full corpus once, then redacts for PUBLIC
# (report.py::build_reports docstring, VLM6-R3-03) — detection is never
# re-scored on a filtered population, so PUBLIC == LOCAL here (VLM6-DELTA-11).
_PUBLIC_TP = _LOCAL_TP


def _named_box(name: str | None, *, x: float = 0.5) -> dict:
    return {
        "x": x,
        "y": 0.4,
        "w": 0.2,
        "h": 0.3,
        "name": name,
        "source": "operator",
        "lineage": _LINEAGE,
    }


def _stamp_entry(entry: dict, mode: str) -> dict:
    """Entry-level stamp only. Never writes a parent/document mode."""
    entry["annotation_mode"] = mode
    return entry


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
                "identities": [{"name": "Alice Example", "unpositioned": True}],
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
                "identities": [{"name": "Alice Example", "unpositioned": True}],
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


def _manifest_entries(*, mode: str | None = "exhaustive") -> list[dict]:
    entries = [
        {
            "path": "mock_images/alice-pool.jpg",
            "media_id": 1,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "must_right": ["Alice Example"],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [_named_box("Alice Example")],
        },
        {
            "path": "mock_images/bob-beach.jpg",
            "media_id": 2,
            "face_count": 1,
            "present_identities": ["Bob Builder"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [_named_box("Bob Builder")],
        },
        {
            "path": "mock_images/glacier.jpg",
            "media_id": 3,
            "face_count": 0,
            "present_identities": [],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [],
        },
    ]
    if mode is not None:
        for entry in entries:
            _stamp_entry(entry, mode)
    return entries


def _audience_fixtures(*, mode: str | None = "exhaustive") -> tuple[dict, list[dict]]:
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
                "identities": [{"name": _PUBLIC_NAME, "unpositioned": True}],
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
                "identities": [{"name": "Wrong Celebrity", "unpositioned": True}],
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
            "face_boxes": [_named_box(_PUBLIC_NAME)],
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
            "face_boxes": [_named_box(_LOCAL_NAME)],
            "provenance": {
                "source": "localwp",
                "license": "consented",
                "publishable": False,
            },
        },
    ]
    if mode is not None:
        for entry in entries:
            _stamp_entry(entry, mode)
    return record, entries


def _detection_section(md: str) -> str:
    return md.split("## Face detection")[1].split("## Face identification")[0]


def _assert_scored_detection(det: dict, *, tp: int, fp: int, fn: int) -> None:
    assert det.get("refused") is not True
    assert "invariant" not in det
    assert det["tp"] == tp
    assert det["fp"] == fp
    assert det["fn"] == fn
    denom_p = tp + fp
    denom_r = tp + fn
    assert det["precision"] == (pytest.approx(tp / denom_p) if denom_p else None)
    assert det["recall"] == (pytest.approx(tp / denom_r) if denom_r else None)


def _assert_scored_detection_markdown(md: str, *, tp: int, fp: int, fn: int) -> None:
    section = _detection_section(md)
    assert "REFUSED" not in section
    prec = "null" if tp + fp == 0 else f"{tp / (tp + fp):.3f}"
    rec = "null" if tp + fn == 0 else f"{tp / (tp + fn):.3f}"
    assert f"- precision: {prec} recall: {rec} (tp={tp} fp={fp} fn={fn})" in section


def test_fixtures_stamp_entries_not_parent_document() -> None:
    """S2R3-12 / S2R3-02: a parent-level fill will evaporate when E1 lands."""
    entries = _manifest_entries()
    record, audience = _audience_fixtures()
    assert "annotation_mode" not in record
    assert "annotation_mode" not in record.get("provenance", {})
    for entry in (*entries, *audience):
        assert entry["annotation_mode"] == "exhaustive"
        assert entry.get("face_boxes") is not None
        assert len(entry["face_boxes"]) == entry["face_count"]


def test_score_run_record_emits_scored_detection_arithmetic() -> None:
    scored = score_run_record(_run_record(), _manifest_entries())
    _assert_scored_detection(
        scored["faces"]["detection"], tp=_DEFAULT_TP, fp=_DEFAULT_FP, fn=_DEFAULT_FN
    )
    assert scored["counts"] == {"total": 3, "scored": 2, "failed": 1}


def test_markdown_renders_scored_detection_line() -> None:
    _json_doc, md = build_reports(_run_record(), _manifest_entries())
    _assert_scored_detection_markdown(md, tp=_DEFAULT_TP, fp=_DEFAULT_FP, fn=_DEFAULT_FN)


def test_build_reports_scored_detection_is_deterministic() -> None:
    record, entries = _run_record(), _manifest_entries()
    json_a, md_a = build_reports(record, entries)
    json_b, md_b = build_reports(record, entries)
    assert json_a == json_b
    assert md_a == md_b
    _assert_scored_detection(
        json.loads(json_a)["faces"]["detection"],
        tp=_DEFAULT_TP,
        fp=_DEFAULT_FP,
        fn=_DEFAULT_FN,
    )
    _assert_scored_detection_markdown(md_a, tp=_DEFAULT_TP, fp=_DEFAULT_FP, fn=_DEFAULT_FN)


def test_local_matches_default_audience_with_scored_detection() -> None:
    record, entries = _run_record(), _manifest_entries()
    default_json, default_md = build_reports(record, entries)
    local_json, local_md = build_reports(record, entries, audience=Audience.LOCAL)
    assert default_json == local_json
    assert default_md == local_md
    _assert_scored_detection(
        json.loads(local_json)["faces"]["detection"],
        tp=_DEFAULT_TP,
        fp=_DEFAULT_FP,
        fn=_DEFAULT_FN,
    )


def test_public_audience_renders_scored_detection() -> None:
    record, entries = _audience_fixtures()
    json_doc, md = build_reports(record, entries, audience=Audience.PUBLIC)
    scored = json.loads(json_doc)
    _assert_scored_detection(scored["faces"]["detection"], tp=_PUBLIC_TP, fp=0, fn=0)
    _assert_scored_detection_markdown(md, tp=_PUBLIC_TP, fp=0, fn=0)
    media_ids = {row["media_id"] for row in scored["per_image"]}
    assert media_ids == {10}


def test_local_audience_renders_full_scored_detection() -> None:
    record, entries = _audience_fixtures()
    json_doc, md = build_reports(record, entries, audience=Audience.LOCAL)
    scored = json.loads(json_doc)
    _assert_scored_detection(scored["faces"]["detection"], tp=_LOCAL_TP, fp=0, fn=0)
    _assert_scored_detection_markdown(md, tp=_LOCAL_TP, fp=0, fn=0)
    assert {row["media_id"] for row in scored["per_image"]} == {10, 20}


def test_public_redaction_keeps_scored_detection_and_withholds_private() -> None:
    record, entries = _audience_fixtures()
    json_doc, md = build_reports(record, entries, audience=Audience.PUBLIC)
    scored = json.loads(json_doc)
    _assert_scored_detection(scored["faces"]["detection"], tp=_PUBLIC_TP, fp=0, fn=0)
    # VLM6-DELTA-11: redaction block gained mode/unknown_media_items/
    # withheld_manifest_entries/total_manifest_entries/note fields
    # (report.py::_redact_caption_report_for_public, ~line 1026).
    assert scored["redaction"] == {
        "audience": "public",
        "mode": "post_score_redact_caption_report",
        "withheld_items": 1,
        "unknown_media_items": 0,
        "withheld_manifest_entries": 1,
        "total_items": 2,
        "total_manifest_entries": 2,
        "note": (
            "Aggregates scored on the full corpus (roster/rubric intact); "
            "identity-bearing detail lists and non-publishable per_image rows "
            "stripped. unknown_media_items are corpus-integrity failures, not privacy."
        ),
    }
    assert "withheld 1 of 2 items" in md
    for blob in (json_doc, md):
        assert _LOCAL_PATH not in blob
        assert _LOCAL_NAME not in blob
        assert "Wrong Celebrity" not in blob
    assert _PUBLIC_NAME in json_doc
    # RV4-05: PUBLIC per_image "path" is always the opaque media_id:N token —
    # never an operator basename/path, even for a publishable item
    # (_public_free_text_value, report.py ~line 792). VLM6-DELTA-11.
    assert _PUBLIC_PATH not in json_doc
    assert {row["media_id"] for row in scored["per_image"]} == {10}


def test_public_scored_detection_is_deterministic() -> None:
    record, entries = _audience_fixtures()
    a_json, a_md = build_reports(record, entries, audience=Audience.PUBLIC)
    b_json, b_md = build_reports(record, entries, audience=Audience.PUBLIC)
    assert a_json == b_json
    assert a_md == b_md
    _assert_scored_detection(json.loads(a_json)["faces"]["detection"], tp=_PUBLIC_TP, fp=0, fn=0)
    _assert_scored_detection_markdown(a_md, tp=_PUBLIC_TP, fp=0, fn=0)


def test_overshoot_markdown_names_fp() -> None:
    """pred=3 labeled=1 must surface tp=1 fp=2, not a refused block."""
    record = {
        "schema": "acx-eval/v1",
        "kind": "run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "base_url": "x",
            "head_sha": "0" * 40,
            "started_at": "t",
        },
        "items": [
            {
                "media_id": 1,
                "path": "mock_images/alice.jpg",
                "describe": {"alt_text_draft": "Alice Example.", "visual_facts": {"objects": []}},
                "identities": [{"name": "Alice Example", "unpositioned": True}],
                "face_count": 3,
                "error": None,
            }
        ],
    }
    entry = _stamp_entry(
        {
            "path": "mock_images/alice.jpg",
            "media_id": 1,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [_named_box("Alice Example")],
        },
        "exhaustive",
    )
    json_doc, md = build_reports(record, [entry])
    _assert_scored_detection(json.loads(json_doc)["faces"]["detection"], tp=1, fp=2, fn=0)
    _assert_scored_detection_markdown(md, tp=1, fp=2, fn=0)


def test_stranger_faces_are_not_detection_fps() -> None:
    record = {
        "schema": "acx-eval/v1",
        "kind": "run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "base_url": "x",
            "head_sha": "0" * 40,
            "started_at": "t",
        },
        "items": [
            {
                "media_id": 1,
                "path": "mock_images/group.jpg",
                "describe": {"alt_text_draft": "Muted and friends.", "visual_facts": {"objects": []}},
                "identities": [{"name": "Muted Yarrow", "unpositioned": True}],
                "face_count": 3,
                "error": None,
            }
        ],
    }
    entry = _stamp_entry(
        {
            "path": "mock_images/group.jpg",
            "media_id": 1,
            "face_count": 3,
            "present_identities": ["Muted Yarrow"],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [
                _named_box("Muted Yarrow"),
                _named_box(None, x=0.2),
                _named_box(None, x=0.8),
            ],
        },
        "exhaustive",
    )
    json_doc, md = build_reports(record, [entry])
    scored = json.loads(json_doc)
    _assert_scored_detection(scored["faces"]["detection"], tp=3, fp=0, fn=0)
    _assert_scored_detection_markdown(md, tp=3, fp=0, fn=0)
    assert scored["faces"]["identification"]["true_rejections"] == 1


def test_wrong_name_markdown_alongside_scored_detection() -> None:
    _json_doc, md = build_reports(_run_record(), _manifest_entries())
    _assert_scored_detection_markdown(md, tp=_DEFAULT_TP, fp=_DEFAULT_FP, fn=_DEFAULT_FN)
    assert "mock_images/bob-beach.jpg" in md
    assert "Alice Example" in md
    assert "Wrong-name" in md or "wrong-name" in md


def test_json_and_markdown_detection_agree() -> None:
    scored = score_run_record(_run_record(), _manifest_entries())
    json_doc, md = build_reports(_run_record(), _manifest_entries())
    built = json.loads(json_doc)["faces"]["detection"]
    assert built == scored["faces"]["detection"]
    _assert_scored_detection(built, tp=_DEFAULT_TP, fp=_DEFAULT_FP, fn=_DEFAULT_FN)
    _assert_scored_detection_markdown(md, tp=_DEFAULT_TP, fp=_DEFAULT_FP, fn=_DEFAULT_FN)


def test_unstamped_entries_refuse_missing_mode() -> None:
    """Subject is the missing-stamp refusal — leave unstamped on purpose."""
    json_doc, md = build_reports(_run_record(), _manifest_entries(mode=None))
    det = json.loads(json_doc)["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == ScoreInvariant.DETECTION_REQUIRES_ANNOTATION_MODE
    assert det["tp"] is None
    section = _detection_section(md)
    assert (
        "- REFUSED (detection_requires_annotation_mode): "
        "detection P/R is not computed without a resolved annotation_mode; "
        "omission is not exhaustive"
    ) in section


def test_roster_only_stamp_refuses_detection() -> None:
    """Subject is the roster_only refusal — stamp the restrictive mode."""
    json_doc, md = build_reports(_run_record(), _manifest_entries(mode="roster_only"))
    det = json.loads(json_doc)["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY
    assert det["tp"] is None
    section = _detection_section(md)
    assert (
        "- REFUSED (detection_refuses_roster_only): "
        "detection P/R is not computed unless annotation_mode is exhaustive"
    ) in section


def test_markdown_names_refused_detection_explanation_literally() -> None:
    """S2R3-11: pin the published sentence, not the production constant.

    Mutating the explanation to 'detection scored normally; refusal is
    cosmetic' must fail this pin. Importing DETECTION_REFUSED_EXPLANATION
    or REFUSAL_EXPLANATIONS would stay green.
    """
    _json_doc, md = build_reports(_run_record(), _manifest_entries(mode="roster_only"))
    section = _detection_section(md)
    assert (
        "- REFUSED (detection_refuses_roster_only): "
        "detection P/R is not computed unless annotation_mode is exhaustive"
    ) in section
    assert "detection scored normally" not in section
    assert "refusal is cosmetic" not in section
    assert "used anyway" not in section
    assert "zero scored observations" not in section
    assert "precision: null" not in section


def test_all_failed_items_refuse_empty_observations() -> None:
    """Stamped exhaustive still refuses: zero scored observations, not missing mode."""
    record = _run_record()
    for item in record["items"]:
        item["error"] = "boom"
    json_doc, md = build_reports(record, _manifest_entries())
    det = json.loads(json_doc)["faces"]["detection"]
    assert det["refused"] is True
    assert det["invariant"] == ScoreInvariant.DETECTION_REFUSES_EMPTY_OBSERVATIONS
    assert det["precision"] is None
    section = _detection_section(md)
    assert (
        "- REFUSED (detection_refuses_empty_observations): "
        "detection P/R is not computed from zero scored observations"
    ) in section
    assert json.loads(json_doc)["counts"]["scored"] == 0
