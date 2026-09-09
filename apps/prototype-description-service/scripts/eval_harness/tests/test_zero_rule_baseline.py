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
    # Hand-derived from golden.json context_pack title+caption+description.
    # Do not call zero_rule_caption() here — that tautology stays green if the
    # echo rule is inverted (TEST-15).
    expected_captions = {
        1: (
            "Slate Willow inside the Breiðamerkurjökull ice cave "
            "Slate Willow crouching beneath blue glacial ice in Iceland. "
            "Slate Willow, in a white climbing helmet with a headlamp and a "
            "fur-hooded black parka, crouches on wet rocks inside the blue ice "
            "cave at Breiðamerkurjökull with a camera at her side."
        ),
        2: (
            "Hollow Pennant's birthday mirror selfie "
            "Hollow Pennant in a Happy Birthday tiara sticking her tongue out. "
            "Hollow Pennant takes a hotel-bathroom mirror selfie in a rhinestone "
            "Happy Birthday tiara and teal crop top, sticking her tongue out."
        ),
        4: (
            "Russet Fathom at the bar "
            "Russet Fathom leaning on a wooden bar counter. "
            "Russet Fathom rests her arms on a worn wooden bar counter in a cream "
            "graphic tee, bottles and taps lining the back bar behind her."
        ),
        5: (
            "Russet Fathom and Muted Current on a night out "
            "Russet Fathom and Muted Current at a warmly lit bar. "
            "Russet Fathom and Muted Current share a night out at a warmly lit bar, "
            "with other patrons reflected in the mirror behind them."
        ),
        11: (
            "Russet Fathom crosses the finish line "
            "Russet Fathom mid-stride at a winter road race. "
            "Russet Fathom, in a teal beanie, sunglasses, black neck gaiter, and "
            "green running kit with a race bib and a magenta layer tied at her waist, "
            "leaps mid-stride past spectators lining the barricades."
        ),
        13: (
            "Russet Fathom under the magnolias "
            "Russet Fathom smiling beneath pink magnolia blossoms. "
            "Russet Fathom, in a grey cap and rose-tinted sunglasses with low "
            "pigtails, smiles under a canopy of pink magnolia blossoms against a "
            "blue sky."
        ),
        14: (
            "Russet Fathom on the rooftop "
            "Russet Fathom in sunglasses under a clear blue sky. "
            "Russet Fathom smiles in dark sunglasses and a cream hoodie on a rooftop "
            "terrace, windblown hair catching the sun, city towers on the horizon."
        ),
        15: (
            "Russet Fathom on the street "
            "Russet Fathom in a grainy black-and-white street shot. "
            "Russet Fathom pauses mid-stride on a city sidewalk with a shoulder bag, "
            "in a grainy, underexposed black-and-white frame beside a beverage truck."
        ),
        16: (
            "Russet Fathom at the show "
            "Russet Fathom blurred in pink stage light. "
            "Russet Fathom's face glows out of focus behind netting and bokeh lights, "
            "washed in pink concert lighting."
        ),
        18: (
            "Gilded Cypress in gold leaf "
            "Gilded Cypress wearing gold leaf makeup and red lipstick. "
            "Gilded Cypress, hair pinned up, wears flakes of gold leaf across her "
            "face, shoulders, and chest with bold red lipstick and gold drop "
            "earrings, standing in a kitchen."
        ),
        19: (
            "Auburn Current's birthday princess moment "
            "Auburn Current celebrating under the balloon arch. "
            "Auburn Current celebrates at a birthday party beneath a purple, green, "
            "and gold balloon arch, with a Birthday Princess sash and tiara in the mix."
        ),
        20: (
            "Auburn Current and her Aussie "
            "Auburn Current hugging an Australian Shepherd by the fireplace. "
            "Auburn Current, in a cream sweater, kneels on a wood floor hugging a "
            "blue merle Australian Shepherd in front of a marble fireplace."
        ),
        21: (
            "Auburn Current out on the water "
            "Auburn Current in her pink bucket hat on the bow. "
            "Auburn Current, in a pink bucket hat and striped top, lounges on the "
            "bow of a motorboat with a friend on a hazy summer day."
        ),
        24: (
            "Auburn Current in the pool "
            "Auburn Current floating in a tiled indoor pool. "
            "Auburn Current floats on her back in a black swimsuit in the pale green "
            "water of a tiled indoor pool, near the Shallow Water lettering at the "
            "pool edge."
        ),
        25: (
            "Linen Kestrel in black and white "
            "Linen Kestrel looking up in round glasses. "
            "Linen Kestrel, bald with round black-rimmed glasses, lies back against "
            "a patterned pillow in a high-contrast black-and-white overhead portrait."
        ),
        28: (
            "Slate Willow at the gala dinner "
            "Slate Willow and friends dressed up at a formal dinner. "
            "Slate Willow, in a white slip dress and red lipstick, takes a selfie "
            "with three friends in evening dresses at a set table in an ornate "
            "gilded dining room."
        ),
        29: (
            "Slate Willow and the cake "
            "Slate Willow biting into a slice of cake. "
            "Slate Willow, in a sparkly top, bites a striped slice of cake while a "
            "phone on a selfie stick films her, a couple embracing in the background "
            "of the party room."
        ),
        33: (
            "Slate Willow at the plane wreck "
            "Slate Willow climbing into the wrecked fuselage. "
            "Slate Willow, in a fur-hooded parka, steps up into the torn aluminum "
            "fuselage of the abandoned DC-3 wreck on a grey black-sand plain."
        ),
        36: (
            "Muted Yarrow at the pink bar "
            "Muted Yarrow with a margarita under pink neon. "
            "Muted Yarrow, in a black backless top and sheer patterned skirt, holds "
            "a salt-rimmed margarita at a pink-lit bar beneath a Pink Panther poster "
            "and an antique mirror."
        ),
        37: (
            "Muted Yarrow's pajama party "
            "Muted Yarrow dancing with friends in matching pink satin. "
            "Muted Yarrow raises a drink among five friends in matching pink satin "
            "pajamas, dancing by an iridescent foil curtain and a silver number balloon."
        ),
    }
    assert set(expected_captions) == set(golden_ids)
    for item, entry in zip(record["items"], golden["entries"], strict=True):
        media_id = int(item["media_id"])
        assert item["describe"]["alt_text_draft"] == expected_captions[media_id]
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
    assert "- REFUSED (delta_refuses_straddled_stamps):" in md
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
