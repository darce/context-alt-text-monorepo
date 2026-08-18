"""VLM-6 S1: sealed eval split (EVAL-07 / MLDATA-09 / EVAL-10)."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.eval_harness.cli import main
from scripts.eval_harness.manifest import AnnotationMode, EntryPolicy, GoldenEntry, GoldenManifest, load_manifest
from scripts.eval_harness.strata import (
    SPLIT_DISJOINTNESS_NOTE,
    SplitDisjointnessStatus,
    SplitHalf,
    assign_split,
    compute_split_seal_sha256,
    draw_eval_split,
    verify_eval_split,
)

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
        metadata_only=True,
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


def _committed_expected(**overrides):
    kwargs = {
        "source_manifest_sha256": hashlib.sha256(_SEED_MANIFEST.read_bytes()).hexdigest(),
        "expected_seed": _DRAW_SEED,
        "expected_held_out_fraction": 0.5,
        "expected_draw_timestamp": _DRAW_TIMESTAMP,
        "expected_partition_provenance": _PARTITION_PROVENANCE,
        "expected_source_manifest_path": "scene/tests/seed/golden.json",
        "expected_pre_split_exposure": list(_EXPOSURE_NOTES),
    }
    kwargs.update(overrides)
    return kwargs


def test_pin_committed_sealed_eval_split():
    artifact = json.loads(_SEALED_SPLIT.read_text())
    assert verify_eval_split(artifact, _load_golden(), **_committed_expected()) == []
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


def _check_cli_args(out: Path, **overrides) -> list[str]:
    args = {
        "manifest": str(_SEED_MANIFEST),
        "out": str(out),
        "seed": _DRAW_SEED,
        "draw_timestamp": _DRAW_TIMESTAMP,
        "partition_provenance": _PARTITION_PROVENANCE,
        "held_out_fraction": "0.5",
        "exposure_notes": list(_EXPOSURE_NOTES),
    }
    args.update(overrides)
    argv = [
        "draw-eval-split",
        "--manifest",
        args["manifest"],
        "--out",
        args["out"],
        "--check",
        "--seed",
        args["seed"],
        "--held-out-fraction",
        str(args["held_out_fraction"]),
        "--draw-timestamp",
        args["draw_timestamp"],
        "--partition-provenance",
        args["partition_provenance"],
    ]
    for note in args["exposure_notes"]:
        argv.extend(["--exposure-note", note])
    return argv


def _fixture_expected(**overrides):
    kwargs = {
        "source_manifest_sha256": "a" * 64,
        "expected_seed": _DRAW_SEED,
        "expected_held_out_fraction": 0.5,
        "expected_draw_timestamp": _DRAW_TIMESTAMP,
        "expected_partition_provenance": _PARTITION_PROVENANCE,
        "expected_source_manifest_path": "scene/tests/seed/golden.json",
        "expected_pre_split_exposure": ["fixture exposure"],
    }
    kwargs.update(overrides)
    return kwargs


def _alice_bob_manifest() -> GoldenManifest:
    """Two-entry identity-disjoint corpus (Q1-03)."""
    return GoldenManifest(
        manifest_version=3,
        annotation_mode=AnnotationMode.ROSTER_ONLY,
        roster=["Alice", "Bob"],
        entries=[
            GoldenEntry(
                path="alice.jpg",
                sha256="a" * 64,
                media_id=1,
                face_count=1,
                present_identities=["Alice"],
                must_right=["Alice"],
                easy_wrong=[],
                policy=EntryPolicy(recognition_enabled=False),
            ),
            GoldenEntry(
                path="bob.jpg",
                sha256="b" * 64,
                media_id=2,
                face_count=1,
                present_identities=["Bob"],
                must_right=["Bob"],
                easy_wrong=[],
                policy=EntryPolicy(recognition_enabled=False),
            ),
        ],
    )


def _draw_alice_bob(**overrides):
    kwargs = {
        "seed": "alice-bob-seed",
        "held_out_fraction": 0.5,
        "draw_timestamp": _DRAW_TIMESTAMP,
        "source_manifest_path": "alice-bob.json",
        "source_manifest_sha256": "c" * 64,
        "pre_split_exposure": ["fixture exposure"],
        "partition_provenance": "synthetic two-entry Alice/Bob",
    }
    kwargs.update(overrides)
    return draw_eval_split(_alice_bob_manifest(), **kwargs)


def _alice_bob_expected(**overrides):
    kwargs = {
        "source_manifest_sha256": "c" * 64,
        "expected_seed": "alice-bob-seed",
        "expected_held_out_fraction": 0.5,
        "expected_draw_timestamp": _DRAW_TIMESTAMP,
        "expected_partition_provenance": "synthetic two-entry Alice/Bob",
        "expected_source_manifest_path": "alice-bob.json",
        "expected_pre_split_exposure": ["fixture exposure"],
    }
    kwargs.update(overrides)
    return kwargs


def test_cli_check_exits_0_on_committed_artifact():
    assert main(_check_cli_args(_SEALED_SPLIT)) is None


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
                "--held-out-fraction",
                "0.5",
                "--draw-timestamp",
                _DRAW_TIMESTAMP,
                "--partition-provenance",
                _PARTITION_PROVENANCE,
                "--exposure-note",
                "fixture exposure",
            ]
        )
    assert excinfo.value.code == 3


@pytest.mark.parametrize("fraction", ["0.0", "1.0"])
def test_cli_held_out_fraction_bounds_exit_2(tmp_path, fraction, capsys):
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
                "--partition-provenance",
                _PARTITION_PROVENANCE,
                "--held-out-fraction",
                fraction,
                "--exposure-note",
                "fixture exposure",
            ]
        )
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    combined = f"{captured.err}{captured.out}"
    assert "fraction" in combined.lower() or "0 < f < 1" in combined, combined


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


def _tamper_draw_timestamp_not_iso(artifact):
    artifact["draw_timestamp"] = "not-iso-8601"


def _tamper_pre_split_exposure_empty(artifact):
    artifact["pre_split_exposure"] = []


def _tamper_source_manifest_sha(artifact):
    artifact["source_manifest"]["sha256"] = "0" * 64


def _tamper_held_out_sha(artifact):
    artifact["held_out"]["sha256"][0] = "0" * 64


@pytest.mark.parametrize(
    "mutator, needle",
    [
        (_tamper_draw_timestamp_not_iso, "draw_timestamp"),
        (_tamper_pre_split_exposure_empty, "pre_split_exposure"),
        (_tamper_source_manifest_sha, "source_manifest.sha256"),
        (_tamper_held_out_sha, "sha256"),
    ],
    ids=["draw_timestamp", "pre_split_exposure", "source_sha", "held_out_sha"],
)
def test_cli_check_tampered_fields_exit_1(tmp_path, capsys, mutator, needle):
    # W3-RV-04: one tamper per case; capture the specific violation (TEST-15).
    tampered = json.loads(_SEALED_SPLIT.read_text())
    mutator(tampered)
    out = tmp_path / "split.json"
    out.write_text(json.dumps(tampered, indent=2, sort_keys=True) + "\n")
    with pytest.raises(SystemExit) as excinfo:
        main(_check_cli_args(out))
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert needle in captured.err or needle in captured.out


def test_cli_check_wrong_partition_provenance_exits_1():
    with pytest.raises(SystemExit) as excinfo:
        main(_check_cli_args(_SEALED_SPLIT, partition_provenance="pre-audit, buffalo-derived merge-only"))
    assert excinfo.value.code == 1


def test_cli_check_wrong_exposure_note_exits_1(capsys):
    args = _check_cli_args(_SEALED_SPLIT)
    args.extend(["--exposure-note", "no prior exposure"])
    with pytest.raises(SystemExit) as excinfo:
        main(args)
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "pre_split_exposure" in captured.err


def test_cli_check_is_metadata_only_without_image_bytes(tmp_path, monkeypatch):
    empty = tmp_path / "no-bytes"
    empty.mkdir()
    monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(empty))
    assert main(_check_cli_args(_SEALED_SPLIT)) is None


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
    assert main(_check_cli_args(_SEALED_SPLIT)) is None
    redrawn = tmp_path / "split.json"
    assert main(_draw_cli_args(redrawn)) is None
    assert redrawn.read_bytes() == _SEALED_SPLIT.read_bytes()


def _mutate_draw_timestamp_future(artifact):
    artifact["draw_timestamp"] = "2099-01-01T00:00:00Z"


def _mutate_draw_timestamp_date_only(artifact):
    artifact["draw_timestamp"] = "2026-08-18"


def _mutate_exposure_rewrite(artifact):
    artifact["pre_split_exposure"] = ["no prior exposure"]


def _mutate_exposure_whitespace(artifact):
    artifact["pre_split_exposure"] = [" "]


def _mutate_partition_provenance(artifact):
    artifact["disjointness"]["partition_provenance"] = "cluster-disjoint verified"


def _mutate_source_manifest_path(artifact):
    artifact["source_manifest"]["path"] = "apps/evil/golden.json"


def _mutate_disjointness_note_deleted(artifact):
    artifact["disjointness"].pop("note", None)


def _mutate_disjointness_note_rewrite(artifact):
    artifact["disjointness"]["note"] = "safe for face-id"


def _mutate_top_level_unknown(artifact):
    artifact["operator_blessed"] = True


def _mutate_held_out_unknown(artifact):
    artifact["held_out"]["human_override"] = True


def _mutate_source_manifest_unknown(artifact):
    artifact["source_manifest"]["blessed_by"] = "operator"


def _mutate_disjointness_unknown(artifact):
    artifact["disjointness"]["auditor"] = "buffalo"


@pytest.mark.parametrize(
    "mutator, needle",
    [
        (_mutate_draw_timestamp_future, "seal digest"),
        (_mutate_draw_timestamp_date_only, "draw_timestamp"),
        (_mutate_exposure_rewrite, "seal digest"),
        (_mutate_exposure_whitespace, "pre_split_exposure"),
        (_mutate_partition_provenance, "partition_provenance"),
        (_mutate_source_manifest_path, "source_manifest.path"),
        (_mutate_disjointness_note_deleted, "disjointness.note"),
        (_mutate_disjointness_note_rewrite, "disjointness.note"),
        (_mutate_top_level_unknown, "operator_blessed"),
        (_mutate_held_out_unknown, "human_override"),
        (_mutate_source_manifest_unknown, "blessed_by"),
        (_mutate_disjointness_unknown, "auditor"),
    ],
    ids=[
        "draw_timestamp_future",
        "draw_timestamp_date_only",
        "exposure_rewrite",
        "exposure_whitespace",
        "partition_provenance",
        "source_manifest_path",
        "note_deleted",
        "note_rewrite",
        "unknown_top_level",
        "unknown_held_out",
        "unknown_source_manifest",
        "unknown_disjointness",
    ],
)
def test_verify_eval_split_field_rewrites_name_the_field(mutator, needle):
    artifact = _draw_golden()
    mutator(artifact)
    violations = verify_eval_split(
        artifact,
        _load_golden(),
        expected_draw_timestamp=_DRAW_TIMESTAMP,
        expected_partition_provenance=_PARTITION_PROVENANCE,
        expected_source_manifest_path="scene/tests/seed/golden.json",
        expected_pre_split_exposure=["fixture exposure"],
    )
    assert violations
    assert any(needle in message for message in violations), violations


def test_verify_seal_digest_mismatch():
    artifact = _draw_golden()
    artifact["draw_timestamp"] = "2099-01-01T00:00:00Z"
    violations = verify_eval_split(artifact, _load_golden())
    assert any("seal digest mismatch" in message for message in violations), violations


def test_verify_status_verified_flip_is_violation():
    artifact = _draw_golden()
    assert artifact["disjointness"]["identities_spanning_both_halves"]
    artifact["disjointness"]["status"] = SplitDisjointnessStatus.VERIFIED.value
    violations = verify_eval_split(artifact, _load_golden())
    assert any("verified" in message and "status" in message for message in violations), violations


def test_verify_unknown_top_level_key_is_violation():
    artifact = _draw_golden()
    artifact["operator_blessed"] = True
    violations = verify_eval_split(artifact, _load_golden())
    assert any("operator_blessed" in message for message in violations), violations


def test_cli_bare_check_without_required_flags_exits_2():
    with pytest.raises(SystemExit) as excinfo:
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
    assert excinfo.value.code == 2


def test_committed_artifact_verifies_clean():
    artifact = json.loads(_SEALED_SPLIT.read_text())
    assert verify_eval_split(artifact, _load_golden(), **_committed_expected()) == []
    assert artifact["disjointness"]["note"] == SPLIT_DISJOINTNESS_NOTE


def _reseal(artifact: dict) -> dict:
    """Recompute seal_sha256 so only the field check (not digest) can fail."""
    artifact["seal_sha256"] = compute_split_seal_sha256(artifact)
    return artifact


def test_verify_exposure_inventory_with_present_identities_tamper_names_field():
    # VLM6-W3-RV-05 (a): reseal so digest passes; only inventory recompute kills.
    artifact = _reseal(_draw_golden())
    artifact["exposure_inventory"]["with_present_identities"] = 0
    _reseal(artifact)
    violations = verify_eval_split(artifact, _load_golden())
    assert any("exposure_inventory" in message for message in violations), violations


def test_verify_protection_rewrite_names_field():
    # VLM6-W3-RV-05 (b): rewrite protection after reseal.
    artifact = _draw_golden()
    artifact["protection"] = "operator-blessed"
    _reseal(artifact)
    violations = verify_eval_split(artifact, _load_golden())
    assert any("protection" in message for message in violations), violations


def test_verify_protection_deleted_names_field():
    artifact = _draw_golden()
    del artifact["protection"]
    _reseal(artifact)
    violations = verify_eval_split(artifact, _load_golden())
    assert any("protection" in message for message in violations), violations


def test_verify_empty_partition_provenance_names_field():
    # VLM6-W3-RV-05 (c): empty string after reseal; do not pass expected= so
    # only the empty-string check (not mismatch) can kill.
    artifact = _draw_golden()
    artifact["disjointness"]["partition_provenance"] = ""
    _reseal(artifact)
    violations = verify_eval_split(artifact, _load_golden())
    assert any("partition_provenance" in message for message in violations), violations


def test_verify_wrong_expected_draw_timestamp_names_field():
    # VLM6-W3-RV-05 (d): artifact is sealed-clean; only expected-equality kills.
    artifact = _draw_golden()
    violations = verify_eval_split(
        artifact,
        _load_golden(),
        expected_draw_timestamp="2020-01-01T00:00:00+00:00",
    )
    assert any("draw_timestamp" in message for message in violations), violations


def test_cli_check_wrong_draw_timestamp_exits_1(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(_check_cli_args(_SEALED_SPLIT, draw_timestamp="2020-01-01T00:00:00+00:00"))
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "draw_timestamp" in captured.err or "draw_timestamp" in captured.out


def _mutate_train_unknown(artifact):
    artifact["train"]["human_override"] = True


def test_verify_resealed_unknown_train_key_names_closed_key():
    # Q1-01: reseal so only the TRAIN-half closed-key check can kill.
    artifact = _draw_golden()
    _mutate_train_unknown(artifact)
    _reseal(artifact)
    violations = verify_eval_split(artifact, _load_golden())
    assert any("unknown train key: human_override" in message for message in violations), violations


def test_verify_resealed_date_only_timestamp_is_iso_violation():
    # Q1-02: resealed date-only; expected_draw_timestamp=None so only ISO check kills.
    artifact = _draw_golden()
    artifact["draw_timestamp"] = "2026-08-18"
    _reseal(artifact)
    violations = verify_eval_split(artifact, _load_golden(), expected_draw_timestamp=None)
    assert any("ISO-8601" in message and "draw_timestamp" in message for message in violations), violations


def test_verify_resealed_naive_timestamp_is_tz_violation():
    # Q1-02: resealed naive (no tz); expected_draw_timestamp=None so only tz/ISO check kills.
    artifact = _draw_golden()
    artifact["draw_timestamp"] = "2026-08-18T12:00:00"
    _reseal(artifact)
    violations = verify_eval_split(artifact, _load_golden(), expected_draw_timestamp=None)
    assert any("ISO-8601" in message and "draw_timestamp" in message for message in violations), violations


def test_verify_resealed_whitespace_exposure_names_non_empty_strings():
    # Q1-03: reseal whitespace note; expected_pre_split_exposure=None so only strip() kills.
    artifact = _draw_golden()
    artifact["pre_split_exposure"] = [" "]
    _reseal(artifact)
    violations = verify_eval_split(artifact, _load_golden(), expected_pre_split_exposure=None)
    assert any("non-empty strings" in message for message in violations), violations


def test_verify_resealed_unknown_exposure_inventory_key_is_named():
    # Q1-04: extra inventory key + reseal; assert closed-key name, not just equality.
    artifact = _draw_golden()
    artifact["exposure_inventory"]["operator_blessed"] = True
    _reseal(artifact)
    violations = verify_eval_split(artifact, _load_golden())
    assert any("unknown exposure_inventory key" in message for message in violations), violations


def test_draw_disjoint_alice_bob_is_verified_and_round_trips():
    # VLM6-RV4-Q1-03: identity-disjoint draw must be verified, then verify returns [].
    artifact = _draw_alice_bob()
    assert artifact["disjointness"]["identities_spanning_both_halves"] == []
    assert artifact["disjointness"]["status"] == SplitDisjointnessStatus.VERIFIED.value
    assert verify_eval_split(artifact, _alice_bob_manifest(), **_alice_bob_expected()) == []


@pytest.mark.parametrize("fraction", [0.0, 1.0])
def test_draw_verify_closed_fraction_round_trip(fraction):
    # VLM6-RV4-Q1-03: 0.0/1.0 empty one half; span is empty; draw/verify are inverses.
    artifact = _draw_alice_bob(held_out_fraction=fraction)
    assert artifact["disjointness"]["identities_spanning_both_halves"] == []
    assert artifact["disjointness"]["status"] == SplitDisjointnessStatus.VERIFIED.value
    assert (
        verify_eval_split(
            artifact,
            _alice_bob_manifest(),
            **_alice_bob_expected(expected_held_out_fraction=fraction),
        )
        == []
    )


def test_verify_provisional_empty_span_is_named():
    # MUT[delete_provisional_empty_span]: disjoint draw flipped to provisional.
    artifact = _draw_alice_bob()
    artifact["disjointness"]["status"] = SplitDisjointnessStatus.PROVISIONAL.value
    _reseal(artifact)
    violations = verify_eval_split(artifact, _alice_bob_manifest(), **_alice_bob_expected())
    assert any(
        "disjointness.status provisional but identities_spanning_both_halves is empty" in message
        for message in violations
    ), violations


def test_verify_none_expected_seed_is_named_violation():
    # VLM6-W3-RV-02 / Q1-04: library must fail-closed when expected_seed is omitted.
    violations = verify_eval_split(_draw_golden(), _load_golden(), **_fixture_expected(expected_seed=None))
    assert any("expected_seed" in message for message in violations), violations


def test_verify_none_expected_fraction_is_named_violation():
    violations = verify_eval_split(_draw_golden(), _load_golden(), **_fixture_expected(expected_held_out_fraction=None))
    assert any("expected_held_out_fraction" in message for message in violations), violations


def test_verify_none_expected_draw_timestamp_is_named_violation():
    violations = verify_eval_split(_draw_golden(), _load_golden(), **_fixture_expected(expected_draw_timestamp=None))
    assert any("expected_draw_timestamp" in message for message in violations), violations


def test_verify_none_expected_partition_provenance_is_named_violation():
    violations = verify_eval_split(
        _draw_golden(), _load_golden(), **_fixture_expected(expected_partition_provenance=None)
    )
    assert any("expected_partition_provenance" in message for message in violations), violations


def test_verify_none_expected_pre_split_exposure_is_named_violation():
    violations = verify_eval_split(
        _draw_golden(), _load_golden(), **_fixture_expected(expected_pre_split_exposure=None)
    )
    assert any("expected_pre_split_exposure" in message for message in violations), violations


def test_verify_expected_seed_mismatch_names_seed():
    # MUT[delete_expected_seed]: artifact seed is honest; only expected-equality kills.
    violations = verify_eval_split(_draw_golden(), _load_golden(), **_fixture_expected(expected_seed="attacker-seed"))
    assert any("seed mismatch" in message for message in violations), violations


def test_verify_expected_fraction_mismatch_names_fraction():
    # MUT[delete_expected_fraction]: artifact fraction is honest; only expected-equality kills.
    violations = verify_eval_split(_draw_golden(), _load_golden(), **_fixture_expected(expected_held_out_fraction=0.3))
    assert any("held_out_fraction mismatch" in message for message in violations), violations


def test_verify_seedless_both_ids_names_both_halves():
    # MUT[delete_both_ids]: drop seed so membership recompute cannot mask the check.
    artifact = _draw_golden()
    del artifact["seed"]
    shared = artifact["held_out"]["media_ids"][0]
    artifact["train"]["media_ids"].append(shared)
    violations = verify_eval_split(artifact, _load_golden(), **_fixture_expected())
    assert any("media_id in both halves" in message for message in violations), violations


def test_verify_seedless_both_shas_names_both_halves():
    # MUT[delete_both_shas]
    artifact = _draw_golden()
    del artifact["seed"]
    shared = artifact["held_out"]["sha256"][0]
    artifact["train"]["sha256"].append(shared)
    violations = verify_eval_split(artifact, _load_golden(), **_fixture_expected())
    assert any("sha256 in both halves" in message for message in violations), violations


def test_verify_seedless_neither_ids_names_neither_half():
    # MUT[delete_neither_ids]
    artifact = _draw_golden()
    del artifact["seed"]
    dropped = artifact["held_out"]["media_ids"].pop(0)
    violations = verify_eval_split(artifact, _load_golden(), **_fixture_expected())
    assert any("media_id in manifest but in neither half" in message for message in violations), violations
    assert any(str(dropped) in message for message in violations), violations


def test_verify_seedless_extra_ids_names_not_in_manifest():
    # MUT[delete_extra_ids]: phantom must name 'not in manifest', not membership mismatch.
    artifact = _draw_golden()
    del artifact["seed"]
    artifact["held_out"]["media_ids"].append(99999)
    violations = verify_eval_split(artifact, _load_golden(), **_fixture_expected())
    assert any("held_out media_id not in manifest" in message for message in violations), violations
    assert not any("membership mismatch" in message for message in violations), violations


def test_verify_seedless_extra_shas_names_not_in_manifest():
    # MUT[delete_extra_shas]
    artifact = _draw_golden()
    del artifact["seed"]
    artifact["held_out"]["sha256"].append("f" * 64)
    violations = verify_eval_split(artifact, _load_golden(), **_fixture_expected())
    assert any("held_out sha256 not in manifest" in message for message in violations), violations


def test_cli_check_missing_held_out_fraction_exits_2():
    argv = [
        "draw-eval-split",
        "--manifest",
        str(_SEED_MANIFEST),
        "--out",
        str(_SEALED_SPLIT),
        "--check",
        "--seed",
        _DRAW_SEED,
        "--draw-timestamp",
        _DRAW_TIMESTAMP,
        "--partition-provenance",
        _PARTITION_PROVENANCE,
        "--exposure-note",
        _EXPOSURE_NOTES[0],
    ]
    with pytest.raises(SystemExit) as excinfo:
        main(argv)
    assert excinfo.value.code == 2


def test_cli_check_missing_exposure_notes_exits_2():
    argv = [
        "draw-eval-split",
        "--manifest",
        str(_SEED_MANIFEST),
        "--out",
        str(_SEALED_SPLIT),
        "--check",
        "--seed",
        _DRAW_SEED,
        "--held-out-fraction",
        "0.5",
        "--draw-timestamp",
        _DRAW_TIMESTAMP,
        "--partition-provenance",
        _PARTITION_PROVENANCE,
    ]
    with pytest.raises(SystemExit) as excinfo:
        main(argv)
    assert excinfo.value.code == 2


def test_cli_check_attacker_seed_reseal_exits_1(tmp_path, capsys):
    # VLM6-RV4-Q1-04: remembership under other-seed; default --seed is the committed seed.
    source_sha = hashlib.sha256(_SEED_MANIFEST.read_bytes()).hexdigest()
    artifact = _draw_golden(
        seed="other-seed",
        source_manifest_sha256=source_sha,
        pre_split_exposure=list(_EXPOSURE_NOTES),
    )
    out = tmp_path / "split.json"
    out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    with pytest.raises(SystemExit) as excinfo:
        main(_check_cli_args(out))
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "seed mismatch" in captured.err


def test_cli_check_resealed_fraction_03_exits_1(tmp_path, capsys):
    # VLM6-RV4-Q1-02: 0.3 remembership checked against required committed 0.5.
    source_sha = hashlib.sha256(_SEED_MANIFEST.read_bytes()).hexdigest()
    artifact = _draw_golden(
        held_out_fraction=0.3,
        source_manifest_sha256=source_sha,
        pre_split_exposure=list(_EXPOSURE_NOTES),
    )
    out = tmp_path / "split.json"
    out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    with pytest.raises(SystemExit) as excinfo:
        main(_check_cli_args(out))
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "held_out_fraction" in captured.err


def test_cli_check_resealed_exposure_rewrite_exits_1(tmp_path, capsys):
    # VLM6-RV4-Q1-01: resealed ["no prior exposure"] vs committed notes.
    artifact = json.loads(_SEALED_SPLIT.read_text())
    artifact["pre_split_exposure"] = ["no prior exposure"]
    _reseal(artifact)
    out = tmp_path / "split.json"
    out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    with pytest.raises(SystemExit) as excinfo:
        main(_check_cli_args(out))
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "pre_split_exposure" in captured.err
