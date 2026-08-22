"""EVAL-01 / P1-5(a): Δ across runs must refuse a straddled corpus or roster epoch.

Characterization: score_run_record already records score_manifest_sha256 and
sets manifest_matches_fetch, and mixed annotation_mode stamps fail loud.
Comparison across two scored runs did not refuse a corpus/epoch mismatch —
that is the defect these tests lock.
"""

from __future__ import annotations

import pytest

from scripts.eval_harness.manifest import ScoreInvariant
from scripts.eval_harness.report import (
    ReportError,
    build_reports,
    compare_scored_runs,
    score_run_record,
)


def _named_box(name: str | None, *, x: float = 0.5) -> dict:
    return {
        "x": x,
        "y": 0.4,
        "w": 0.2,
        "h": 0.3,
        "name": name,
        "source": "operator",
        "lineage": {
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
        },
    }


def _entry(*, mode: str = "exhaustive") -> dict:
    return {
        "path": "mock_images/alice-pool.jpg",
        "media_id": 1,
        "face_count": 1,
        "present_identities": ["Alice Example"],
        "must_right": ["Alice Example"],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "face_boxes": [_named_box("Alice Example")],
        "annotation_mode": mode,
        "difficulty": "easy",
        "domain": "faces",
    }


def _run_record(
    *,
    fetch_sha: str = "f" * 64,
    roster_epoch: str | None = "post-priv1",
    caption: str = "Alice Example by a pool.",
) -> dict:
    provenance: dict = {
        "manifest_sha256": fetch_sha,
        "base_url": "https://api.example.com",
        "head_sha": "0" * 40,
        "started_at": "2026-07-06T00:00:00Z",
    }
    if roster_epoch is not None:
        provenance["roster_epoch"] = roster_epoch
    return {
        "schema": "acx-eval/v1",
        "kind": "run_record",
        "provenance": provenance,
        "items": [
            {
                "media_id": 1,
                "path": "mock_images/alice-pool.jpg",
                "describe": {
                    "alt_text_draft": caption,
                    "visual_facts": {"caption": "a person by a pool", "objects": ["pool"]},
                    "adapter": "seeded",
                    "model_id": "seeded-fixtures",
                    "model_version": "1",
                    "cached": False,
                },
                "identities": [{"name": "Alice Example", "unpositioned": True}],
                "face_count": 1,
                "error": None,
            }
        ],
    }


def _score(
    *,
    fetch_sha: str = "f" * 64,
    score_sha: str = "s" * 64,
    roster_epoch: str | None = "post-priv1",
    caption: str = "Alice Example by a pool.",
) -> dict:
    return score_run_record(
        _run_record(fetch_sha=fetch_sha, roster_epoch=roster_epoch, caption=caption),
        [_entry()],
        score_manifest_sha256=score_sha,
    )


# --- characterization of today's score_run_record (not the Δ guard) ----------


def test_score_run_record_mismatch_sha_still_emits_caption_metrics() -> None:
    """Today: mixed fetch/score SHAs are flagged, not refused. Caption numbers still land."""
    scored = _score(fetch_sha="a" * 64, score_sha="b" * 64)
    prov = scored["provenance"]
    assert prov["score_manifest_sha256"] == "b" * 64
    assert prov["manifest_sha256"] == "a" * 64
    assert prov["manifest_matches_fetch"] is False
    assert scored["caption"]["mean_gated_score"] is not None
    assert scored["caption"].get("refused") is not True


def test_mixed_annotation_mode_raises_naming_both_stamps() -> None:
    """Today: mixed annotation_mode stamps already fail loud and name both values."""
    entries = [
        _entry(mode="exhaustive"),
        {**_entry(mode="roster_only"), "media_id": 2, "path": "mock_images/other.jpg"},
    ]
    record = _run_record()
    record["items"].append(
        {
            "media_id": 2,
            "path": "mock_images/other.jpg",
            "describe": {
                "alt_text_draft": "someone else.",
                "visual_facts": {"objects": []},
                "adapter": "seeded",
                "model_id": "seeded-fixtures",
                "model_version": "1",
                "cached": False,
            },
            "identities": [],
            "face_count": 0,
            "error": None,
        }
    )
    with pytest.raises(ReportError, match="mixed annotation_mode") as exc_info:
        score_run_record(record, entries)
    message = str(exc_info.value)
    assert "exhaustive" in message
    assert "roster_only" in message
    assert exc_info.value.invariant == ScoreInvariant.DETECTION_REFUSES_MIXED_ANNOTATION_MODE


# --- Δ guard: refuse straddled corpus / roster-epoch stamps ------------------


def test_compare_refuses_mismatched_score_manifest_sha_naming_both() -> None:
    candidate = _score(score_sha="c" * 64)
    baseline = _score(score_sha="b" * 64)
    delta = compare_scored_runs(candidate, baseline)
    assert delta["refused"] is True
    assert delta.get("metrics") is None
    reason = delta["reason"]
    assert "c" * 64 in reason
    assert "b" * 64 in reason
    assert "score_manifest_sha256" in reason


def test_compare_refuses_mismatched_roster_epoch_naming_both() -> None:
    candidate = _score(roster_epoch="post-priv1")
    baseline = _score(roster_epoch="pre-priv1")
    delta = compare_scored_runs(candidate, baseline)
    assert delta["refused"] is True
    assert delta.get("metrics") is None
    reason = delta["reason"]
    assert "post-priv1" in reason
    assert "pre-priv1" in reason
    assert "roster_epoch" in reason


def test_compare_refuses_missing_roster_epoch_as_a_named_stamp() -> None:
    candidate = _score(roster_epoch="post-priv1")
    baseline = _score(roster_epoch=None)
    delta = compare_scored_runs(candidate, baseline)
    assert delta["refused"] is True
    reason = delta["reason"]
    assert "roster_epoch" in reason
    assert "post-priv1" in reason
    assert "None" in reason or "missing" in reason


def test_compare_emits_baseline_and_delta_when_stamps_agree() -> None:
    candidate = _score(caption="Alice Example by a pool.")
    baseline = _score(caption="a pool.")
    delta = compare_scored_runs(candidate, baseline)
    assert delta.get("refused") is not True
    metrics = delta["metrics"]
    assert "mean_gated_score" in metrics
    row = metrics["mean_gated_score"]
    assert "baseline" in row
    assert "candidate" in row
    assert "delta" in row
    assert row["delta"] == pytest.approx(row["candidate"] - row["baseline"])
    assert "insertion_rate" in metrics

def test_delta_markdown_refuse_banner_names_straddle_invariant() -> None:
    """Markdown refuse must name the Δ invariant; a bare REFUSED is not unique."""
    candidate = _run_record(roster_epoch="pre-priv1")
    baseline = _run_record(roster_epoch="post-priv1")
    _json_doc, md = build_reports(
        candidate,
        [_entry()],
        score_manifest_sha256="s" * 64,
        baseline_run_record=baseline,
    )
    assert "## Δ vs zero-rule baseline" in md
    assert "- REFUSED (delta_refuses_straddled_stamps):" in md
    assert "mean_gated_score: candidate=" not in md
