"""VLM-6 S1: sealed eval split (EVAL-07 / MLDATA-09 / EVAL-10)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.eval_harness.cli import main
from scripts.eval_harness.manifest import load_manifest
from scripts.eval_harness.strata import SplitHalf, assign_split, draw_eval_split, verify_eval_split

_SEED_MANIFEST = Path(__file__).resolve().parent / "seed" / "golden.json"
_SEALED_SPLIT = (
    Path(__file__).resolve().parents[4] / "docs/tasks/vlm/bakeoff-results/S1-sealed-eval-split-20260818.json"
)
_DRAW_SEED = "vlm6-s1-sealed-eval-split-20260818"
_DRAW_TIMESTAMP = "2026-08-18T00:00:00Z"
# Seal: hard-coded held_out.media_ids from the committed draw.
_SEALED_HELD_OUT_MEDIA_IDS: list[int] = [
    1,
    2,
    4,
    5,
    11,
    13,
    14,
    15,
    16,
    18,
    19,
    20,
    21,
    24,
    25,
    28,
    29,
    33,
    36,
    37,
]

_SYNTHETIC_SHAS = [f"{index:064x}" for index in range(64)]


def _load_golden():
    return load_manifest(str(_SEED_MANIFEST), skip_hash_verification=True)


def _draw_golden(**overrides):
    kwargs = {
        "seed": _DRAW_SEED,
        "held_out_fraction": 0.5,
        "draw_timestamp": _DRAW_TIMESTAMP,
        "source_manifest_path": "scene/tests/seed/golden.json",
        "source_manifest_sha256": "a" * 64,
        "pre_split_exposure": ["fixture exposure"],
    }
    kwargs.update(overrides)
    return draw_eval_split(_load_golden(), **kwargs)


def test_assign_split_is_deterministic_seed_sensitive_and_respects_closed_fraction():
    sha = _SYNTHETIC_SHAS[0]
    assert assign_split(sha, seed="alpha", held_out_fraction=0.5) == assign_split(
        sha, seed="alpha", held_out_fraction=0.5
    )
    halves_a = [assign_split(s, seed="seed-a", held_out_fraction=0.5) for s in _SYNTHETIC_SHAS]
    halves_b = [assign_split(s, seed="seed-b", held_out_fraction=0.5) for s in _SYNTHETIC_SHAS]
    assert halves_a != halves_b
    assert all(assign_split(s, seed="alpha", held_out_fraction=0.0) is SplitHalf.TRAIN for s in _SYNTHETIC_SHAS)
    assert all(assign_split(s, seed="alpha", held_out_fraction=1.0) is SplitHalf.HELD_OUT for s in _SYNTHETIC_SHAS)


def test_draw_eval_split_partitions_golden_without_overlap():
    manifest = _load_golden()
    artifact = _draw_golden()
    held = artifact["held_out"]["media_ids"]
    train = artifact["train"]["media_ids"]
    manifest_ids = sorted(entry.media_id for entry in manifest.entries)
    assert sorted(held + train) == manifest_ids
    assert set(held).isdisjoint(train)
    held_identities = {
        ident for entry in manifest.entries if entry.media_id in set(held) for ident in entry.present_identities
    }
    train_identities = {
        ident for entry in manifest.entries if entry.media_id in set(train) for ident in entry.present_identities
    }
    assert artifact["disjointness"]["identities_spanning_both_halves"] == sorted(held_identities & train_identities)


def test_pin_committed_sealed_eval_split():
    artifact = json.loads(_SEALED_SPLIT.read_text())
    assert verify_eval_split(artifact, _load_golden()) == []
    assert artifact["held_out"]["media_ids"] == _SEALED_HELD_OUT_MEDIA_IDS
    assert artifact["seed"] == _DRAW_SEED
    assert artifact["draw_timestamp"] == _DRAW_TIMESTAMP


def test_verify_eval_split_catches_moved_id_bad_rule_and_stale_span():
    artifact = _draw_golden()
    moved = copy.deepcopy(artifact)
    donor = moved["held_out"]["media_ids"]
    assert donor, "draw produced an empty held_out half"
    mid = donor.pop(0)
    moved["train"]["media_ids"].append(mid)
    moved_violations = verify_eval_split(moved, _load_golden())
    assert any("membership" in message for message in moved_violations)

    bad_rule = copy.deepcopy(artifact)
    bad_rule["assignment_rule"] = "not-the-supported-hmac-rule"
    rule_violations = verify_eval_split(bad_rule, _load_golden())
    assert any("assignment_rule" in message for message in rule_violations)

    stale = copy.deepcopy(artifact)
    stale["disjointness"]["identities_spanning_both_halves"] = ["Nobody"]
    stale_violations = verify_eval_split(stale, _load_golden())
    assert any("identities_spanning_both_halves" in message for message in stale_violations)


def test_cli_check_exits_0_on_committed_artifact():
    assert (
        main(
            [
                "draw-eval-split",
                "--manifest",
                str(_SEED_MANIFEST),
                "--out",
                str(_SEALED_SPLIT),
                "--check",
            ]
        )
        is None
    )


def test_cli_draw_without_force_exits_3_on_existing_out(tmp_path):
    out = tmp_path / "split.json"
    out.write_text("{}\n")
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "draw-eval-split",
                "--manifest",
                str(_SEED_MANIFEST),
                "--out",
                str(out),
                "--seed",
                _DRAW_SEED,
                "--draw-timestamp",
                _DRAW_TIMESTAMP,
            ]
        )
    assert excinfo.value.code == 3


def test_cli_held_out_fraction_1_exits_2(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "draw-eval-split",
                "--manifest",
                str(_SEED_MANIFEST),
                "--out",
                str(tmp_path / "split.json"),
                "--seed",
                _DRAW_SEED,
                "--draw-timestamp",
                _DRAW_TIMESTAMP,
                "--held-out-fraction",
                "1.0",
            ]
        )
    assert excinfo.value.code == 2
