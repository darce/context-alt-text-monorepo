"""EVAL-01 zero-rule baseline arm: context-echo captions on the L3 held-out split."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.eval_harness.manifest import load_manifest
from scripts.eval_harness.report import build_reports, compare_scored_runs, score_run_record
from scripts.eval_harness.schema import SCHEMA, DocKind
from scripts.eval_harness.zero_rule_baseline import (
    GOLDEN_MANIFEST_PATH,
    build_zero_rule_run_record,
    load_held_out_manifest,
    stamped_entries,
    zero_rule_caption,
)

_HELD_OUT_N = 20


def test_zero_rule_caption_is_context_echo_in_field_order() -> None:
    """The rule is metadata-only: title, then caption, then description. No pixels."""
    assert (
        zero_rule_caption(
            {
                "title": "Title name",
                "caption": "Caption line.",
                "description": "Longer description.",
            }
        )
        == "Title name Caption line. Longer description."
    )
    assert zero_rule_caption({}) == ""
    assert zero_rule_caption({"caption": "  only caption  "}) == "only caption"
    assert zero_rule_caption({"description": "d", "title": "t"}) == "t d"


def test_zero_rule_run_record_matches_held_out_split_shape() -> None:
    manifest = load_held_out_manifest()
    record = build_zero_rule_run_record(manifest, started_at="2026-08-22T00:00:00Z", head_sha=None)
    golden = json.loads(Path(GOLDEN_MANIFEST_PATH).read_text(encoding="utf-8"))
    golden_ids = [int(e["media_id"]) for e in golden["entries"]]
    assert len(golden_ids) == _HELD_OUT_N
    assert record["schema"] == SCHEMA
    assert record["kind"] == DocKind.RUN_RECORD.value
    assert [item["media_id"] for item in record["items"]] == golden_ids
    assert record["provenance"]["roster_epoch"] == "post-priv1"
    assert record["provenance"]["baseline_arm"] == "zero_rule_context_echo"
    for item, entry in zip(record["items"], golden["entries"], strict=True):
        expected = zero_rule_caption(entry.get("context_pack") or {})
        assert item["describe"]["alt_text_draft"] == expected
        assert item["describe"]["adapter"] == "zero_rule"
        assert item["identities"] == []
        assert item["face_count"] == 0
        assert item["error"] is None


def test_zero_rule_run_record_scores_through_unmodified_score_run_record() -> None:
    manifest = load_held_out_manifest()
    record = build_zero_rule_run_record(manifest, started_at="t", head_sha=None)
    entries = stamped_entries(manifest)
    scored = score_run_record(
        record,
        entries,
        score_manifest_sha256=record["provenance"]["manifest_sha256"],
        manifest_roster=list(manifest.roster),
    )
    assert scored["counts"]["scored"] == _HELD_OUT_N
    assert scored["counts"]["failed"] == 0
    assert "mean_gated_score" in scored["caption"]
    assert scored["provenance"]["roster_epoch"] == "post-priv1"
    assert scored["provenance"]["score_manifest_sha256"] == record["provenance"]["manifest_sha256"]


def test_zero_rule_does_not_redraw_the_held_out_split() -> None:
    """Consume L3's golden.json as-is. Re-drawing to chase a nicer Δ is MLDATA-09."""
    via_loader = load_held_out_manifest()
    via_raw = load_manifest(
        str(GOLDEN_MANIFEST_PATH),
        skip_hash_verification=True,
        hash_skip_reason="zero-rule test metadata-only",
        metadata_only=True,
    )
    assert [e.media_id for e in via_loader.entries] == [e.media_id for e in via_raw.entries]
    assert len(via_loader.entries) == _HELD_OUT_N


def test_delta_markdown_surfaces_baseline_and_delta() -> None:
    manifest = load_held_out_manifest()
    baseline = build_zero_rule_run_record(manifest, started_at="t", head_sha=None)
    candidate = json.loads(json.dumps(baseline))
    candidate["items"][0]["describe"]["alt_text_draft"] = "unrelated caption with no roster name"
    candidate["items"][0]["describe"]["adapter"] = "seeded"
    json_doc, md = build_reports(
        candidate,
        stamped_entries(manifest),
        score_manifest_sha256=baseline["provenance"]["manifest_sha256"],
        manifest_roster=list(manifest.roster),
        baseline_run_record=baseline,
    )
    scored = json.loads(json_doc)
    delta = scored["baseline_delta"]
    assert delta.get("refused") is not True
    assert "mean_gated_score" in delta["metrics"]
    row = delta["metrics"]["mean_gated_score"]
    assert "baseline" in row and "delta" in row
    assert "## Δ vs zero-rule baseline" in md
    assert "baseline=" in md
    assert "Δ=" in md
    assert "HEADLINE:" in md


def test_delta_markdown_refuses_straddle_in_place_of_the_number() -> None:
    manifest = load_held_out_manifest()
    baseline = build_zero_rule_run_record(manifest, started_at="t", head_sha=None)
    candidate = json.loads(json.dumps(baseline))
    candidate["provenance"]["roster_epoch"] = "pre-priv1"
    json_doc, md = build_reports(
        candidate,
        stamped_entries(manifest),
        score_manifest_sha256=baseline["provenance"]["manifest_sha256"],
        manifest_roster=list(manifest.roster),
        baseline_run_record=baseline,
    )
    scored = json.loads(json_doc)
    delta = scored["baseline_delta"]
    assert delta["refused"] is True
    assert "pre-priv1" in delta["reason"]
    assert "post-priv1" in delta["reason"]
    assert "REFUSED" in md
    assert delta["metrics"] is None
    # A refused comparison must not still print a numeric Δ for mean_gated_score.
    assert "mean_gated_score: candidate=" not in md


def test_identical_arms_on_n20_are_undistinguished() -> None:
    """Honest-number mandate: Δ=0 on n=20 cannot distinguish. Headline must say so."""
    manifest = load_held_out_manifest()
    baseline = build_zero_rule_run_record(manifest, started_at="t", head_sha=None)
    candidate = json.loads(json.dumps(baseline))
    scored_c = score_run_record(
        candidate,
        stamped_entries(manifest),
        score_manifest_sha256=baseline["provenance"]["manifest_sha256"],
        manifest_roster=list(manifest.roster),
    )
    scored_b = score_run_record(
        baseline,
        stamped_entries(manifest),
        score_manifest_sha256=baseline["provenance"]["manifest_sha256"],
        manifest_roster=list(manifest.roster),
    )
    delta = compare_scored_runs(scored_c, scored_b)
    assert delta.get("refused") is not True
    assert delta["metrics"]["mean_gated_score"]["delta"] == 0
    assert delta["power"]["undistinguished"] is True
    assert delta["power"]["n_paired"] == _HELD_OUT_N
    headline = delta["power"]["headline"].lower()
    assert "cannot tell" in headline
    assert "n=20" in headline or "n=20" in str(delta["power"])
