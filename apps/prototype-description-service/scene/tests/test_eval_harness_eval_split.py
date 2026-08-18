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
_PARTITION_PROVENANCE = (
    "per-image roster labels on the VLM-2A fixture corpus (golden.json v3); "
    "no cluster partition, disjointness computed on present_identities only"
)
_EXPOSURE_NOTES = [
    (
        "golden.json v3 (37 entries) curated pre-split: present_identities "
        "non-empty on 34/37 (empty: media_id 27,34,35), face_boxes=0/37, "
        "must_right=34/37, annotation_mode=roster_only; held_out half is "
        "model-held-out but NOT selection-held-out"
    ),
    "curation tenant 4ddf8f36 (LocalWP :10018) live with clustered uploads pre-draw",
    "determinism-anchor runs S0/S2A (bakeoff-results/) scored the 37 pre-split",
]
_HASH_SKIP_REASON = "split seal pins sha256 metadata; image bytes never opened"
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
    return load_manifest(
        str(_SEED_MANIFEST),
        images_dir="",
        skip_hash_verification=True,
        hash_skip_reason=_HASH_SKIP_REASON,
    )


def _draw_golden(**overrides):
    kwargs = {
        "seed": _DRAW_SEED,
        "held_out_fraction": 0.5,
        "draw_timestamp": _DRAW_TIMESTAMP,
        "source_manifest_path": "scene/tests/seed/golden.json",
        "source_manifest_sha256": "a" * 64,
        "pre_split_exposure": ["fixture exposure"],
        "partition_provenance": _PARTITION_PROVENANCE,
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
    assert artifact["disjointness"]["partition_provenance"] == _PARTITION_PROVENANCE
    assert artifact["exposure_inventory"] == {
        "annotation_mode": "roster_only",
        "empty_identity_media_ids": [27, 34, 35],
        "entries": 37,
        "with_face_boxes": 0,
        "with_must_right": 34,
        "with_present_identities": 34,
    }


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
                "--partition-provenance",
                _PARTITION_PROVENANCE,
            ]
        )
    assert excinfo.value.code == 3


@pytest.mark.parametrize("fraction", ["0.0", "1.0"])
def test_cli_held_out_fraction_bounds_exit_2(tmp_path, fraction):
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
                fraction,
            ]
        )
    assert excinfo.value.code == 2


def test_verify_seedless_swapped_is_violation():
    # RV-02: missing seed + every held_out id moved to train must not verify [].
    tampered = copy.deepcopy(_draw_golden())
    del tampered["seed"]
    held_ids = list(tampered["held_out"]["media_ids"])
    tampered["train"]["media_ids"].extend(held_ids)
    tampered["held_out"]["media_ids"] = []
    violations = verify_eval_split(tampered, _load_golden())
    assert violations
    assert any("seed" in message for message in violations)


def test_verify_string_fraction_is_violation():
    tampered = copy.deepcopy(_draw_golden())
    tampered["held_out_fraction"] = "0.5"
    violations = verify_eval_split(tampered, _load_golden())
    assert violations
    assert any("held_out_fraction" in message for message in violations)


def test_verify_poisoned_held_out_sha_is_violation():
    # RV-03: sha-poison must fail closed (TEST-15).
    tampered = copy.deepcopy(_draw_golden())
    assert tampered["held_out"]["sha256"]
    tampered["held_out"]["sha256"][0] = "0" * 64
    violations = verify_eval_split(tampered, _load_golden())
    assert violations
    assert any("sha256" in message for message in violations)


def test_verify_emptied_sha_and_identities_are_violations():
    emptied_sha = copy.deepcopy(_draw_golden())
    emptied_sha["held_out"]["sha256"] = []
    emptied_sha["train"]["sha256"] = []
    sha_violations = verify_eval_split(emptied_sha, _load_golden())
    assert any("sha256" in message for message in sha_violations)

    emptied_ids = copy.deepcopy(_draw_golden())
    emptied_ids["held_out"]["identities"] = []
    emptied_ids["train"]["identities"] = []
    ident_violations = verify_eval_split(emptied_ids, _load_golden())
    assert any("identities" in message for message in ident_violations)


def test_verify_phantom_media_id_is_violation():
    tampered = copy.deepcopy(_draw_golden())
    tampered["held_out"]["media_ids"].append(99999)
    violations = verify_eval_split(tampered, _load_golden())
    assert any("99999" in message for message in violations)


def test_verify_schema_version_99_is_violation():
    tampered = copy.deepcopy(_draw_golden())
    tampered["schema_version"] = 99
    violations = verify_eval_split(tampered, _load_golden())
    assert any("schema_version" in message for message in violations)


def test_verify_invalid_disjointness_status_is_violation():
    tampered = copy.deepcopy(_draw_golden())
    tampered["disjointness"]["status"] = "buffalo-blessed"
    violations = verify_eval_split(tampered, _load_golden())
    assert any("status" in message for message in violations)


def test_cli_check_tampered_fields_exit_1(tmp_path):
    # RV-03 / RV-08: edited draw_timestamp / pre_split_exposure / source sha.
    tampered = json.loads(_SEALED_SPLIT.read_text())
    tampered["draw_timestamp"] = "not-iso-8601"
    tampered["pre_split_exposure"] = []
    tampered["source_manifest"]["sha256"] = "0" * 64
    out = tmp_path / "split.json"
    out.write_text(json.dumps(tampered, indent=2, sort_keys=True) + "\n")
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "draw-eval-split",
                "--manifest",
                str(_SEED_MANIFEST),
                "--out",
                str(out),
                "--check",
            ]
        )
    assert excinfo.value.code == 1


def test_cli_check_tampered_sha_exits_1(tmp_path):
    # RV-08: --check of a sha-poisoned artifact must be SystemExit 1, not None.
    tampered = json.loads(_SEALED_SPLIT.read_text())
    tampered["held_out"]["sha256"][0] = "0" * 64
    out = tmp_path / "split.json"
    out.write_text(json.dumps(tampered, indent=2, sort_keys=True) + "\n")
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "draw-eval-split",
                "--manifest",
                str(_SEED_MANIFEST),
                "--out",
                str(out),
                "--check",
            ]
        )
    assert excinfo.value.code == 1


def test_cli_check_wrong_partition_provenance_exits_1():
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "draw-eval-split",
                "--manifest",
                str(_SEED_MANIFEST),
                "--out",
                str(_SEALED_SPLIT),
                "--check",
                "--partition-provenance",
                "pre-audit, buffalo-derived merge-only",
            ]
        )
    assert excinfo.value.code == 1


def test_cli_check_is_metadata_only_without_image_bytes(tmp_path, monkeypatch):
    empty = tmp_path / "no-bytes"
    empty.mkdir()
    monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(empty))
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


def _draw_cli_args(out: Path) -> list[str]:
    args = [
        "draw-eval-split",
        "--manifest",
        str(_SEED_MANIFEST),
        "--out",
        str(out),
        "--seed",
        _DRAW_SEED,
        "--held-out-fraction",
        "0.5",
        "--draw-timestamp",
        _DRAW_TIMESTAMP,
        "--partition-provenance",
        _PARTITION_PROVENANCE,
        "--force",
    ]
    for note in _EXPOSURE_NOTES:
        args.extend(["--exposure-note", note])
    return args


def test_cli_check_committed_and_redraw_is_byte_identical(tmp_path):
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
    redrawn = tmp_path / "split.json"
    assert main(_draw_cli_args(redrawn)) is None
    assert redrawn.read_bytes() == _SEALED_SPLIT.read_bytes()
