"""Adversarial DAG-score guards (TEST-15).

These tests mutate the run evidence and declared pair after a nominally valid
run is initialized.  The score path must reject the mutation instead of
silently selecting a fallback manifest, a different leg set, or a non-finite
attrition threshold.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from scripts.bench.driver import init_run_dir
from scripts.bench.score_report import (
    AcceptedSet,
    _analyze_ok,
    _declared_stack_ids,
    _ingest_roster,
    _load_manifest_from_run,
    _load_pair,
    _terminal_ingest_ok,
    compute_accepted_set,
    score_head_to_head,
    write_attrition,
)
from scripts.bench.stack_pair import (
    BenchError,
    StackPairConfig,
    _validate_attrition,
    load_stack_pair,
)
from scripts.bench.tests.conftest import (
    FIR_STACK,
    INSIGHTFACE_STACK,
    valid_pair_dict,
    write_manifest,
    write_pair,
)

PRIMARY = "detection_recall@frame_e2e/label_map_primary"
STACK_A = "acx-dev-insightface"
STACK_B = "acx-dev-fir"


def _pinned_run(tmp_path: Path, *, media_ids: list[int] | None = None) -> Path:
    manifest = write_manifest(tmp_path / "source.json", media_ids or [1])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml", valid_pair_dict(accepted_set_floor=0.5)))
    return init_run_dir(tmp_path / "run", pair, manifest)


def _record(entry_path: str, content_sha256: str, *, phase: str) -> dict[str, object]:
    return {
        "manifest_media_id": 1,
        "manifest_path": entry_path,
        "content_sha256": content_sha256,
        "stack_media_id": 101,
        "image_width": 10,
        "image_height": 10,
        "phase": phase,
        "outcome": "ok",
        "terminal_ingest_outcome": "success",
    }


def test_pinned_metadata_only_load_does_not_require_media_bytes(tmp_path: Path) -> None:
    run_dir = _pinned_run(tmp_path, media_ids=[1, 2])

    assert not (run_dir / "fixtures" / "m1.jpg").exists()
    assert not (run_dir / "fixtures" / "m2.jpg").exists()
    manifest = _load_manifest_from_run(run_dir)

    assert [entry.media_id for entry in manifest.entries] == [1, 2]


def test_score_refuses_missing_manifest_pin(tmp_path: Path) -> None:
    run_dir = _pinned_run(tmp_path)
    (run_dir / "manifest.sha").unlink()

    with pytest.raises(BenchError) as exc:
        _load_manifest_from_run(run_dir)

    assert exc.value.code == "manifest_sha_missing"


def test_score_refuses_tampered_manifest_before_metadata_only_load(tmp_path: Path) -> None:
    run_dir = _pinned_run(tmp_path, media_ids=[1, 2])
    raw = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    raw["entries"][0]["path"] = "fixtures/relabelled.jpg"
    (run_dir / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(BenchError) as exc:
        _load_manifest_from_run(run_dir)

    assert exc.value.code == "manifest_sha_mismatch"


def test_score_refuses_manifest_path_fallback_even_when_bytes_match_pin(tmp_path: Path) -> None:
    run_dir = _pinned_run(tmp_path)
    replacement = tmp_path / "replacement.json"
    replacement.write_bytes((run_dir / "manifest.json").read_bytes())
    (run_dir / "manifest.json").unlink()
    run_doc = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    run_doc["manifest_path"] = str(replacement)
    (run_dir / "run.json").write_text(json.dumps(run_doc), encoding="utf-8")

    with pytest.raises(BenchError) as exc:
        _load_manifest_from_run(run_dir)

    assert exc.value.code == "manifest_missing"


def test_score_refuses_manifest_snapshot_symlink(tmp_path: Path) -> None:
    run_dir = _pinned_run(tmp_path)
    source = tmp_path / "outside.json"
    source.write_bytes((run_dir / "manifest.json").read_bytes())
    (run_dir / "manifest.json").unlink()
    (run_dir / "manifest.json").symlink_to(source)

    with pytest.raises(BenchError) as exc:
        _load_manifest_from_run(run_dir)

    assert exc.value.code == "manifest_missing"


def test_record_provenance_requires_latest_path_and_content_pin(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path / "manifest.json", [1])
    from scripts.bench.corpus import load_bench_manifest

    manifest = load_bench_manifest(
        manifest_path,
        None,
        metadata_only=True,
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only record provenance",
    )
    entry = manifest.entries[0]
    valid_analyze = _record(entry.path, entry.sha256, phase="analyze")
    valid_ingest = _record(entry.path, entry.sha256, phase="ingest")

    assert _analyze_ok([valid_analyze], entry.media_id, entry=entry) == valid_analyze
    assert _terminal_ingest_ok([valid_ingest], entry.media_id, entry=entry) is True

    for field, value in (("manifest_path", "fixtures/relabelled.jpg"), ("content_sha256", "f" * 64)):
        tampered_analyze = {**valid_analyze, field: value}
        tampered_ingest = {**valid_ingest, field: value}
        assert _analyze_ok([valid_analyze, tampered_analyze], entry.media_id, entry=entry) is None
        assert _terminal_ingest_ok([valid_ingest, tampered_ingest], entry.media_id, entry=entry) is False
        assert _ingest_roster([tampered_ingest], manifest) == set()


@pytest.mark.parametrize("phase", ["analyze", "ingest"])
def test_record_provenance_does_not_accept_non_string_pin_fields(tmp_path: Path, phase: str) -> None:
    manifest_path = write_manifest(tmp_path / "manifest.json", [1])
    from scripts.bench.corpus import load_bench_manifest

    manifest = load_bench_manifest(
        manifest_path,
        None,
        metadata_only=True,
        skip_hash_verification=True,
        hash_skip_reason="test metadata-only record provenance types",
    )
    entry = manifest.entries[0]
    record = _record(entry.path, entry.sha256, phase=phase)
    record["content_sha256"] = None
    if phase == "analyze":
        assert _analyze_ok([record], entry.media_id, entry=entry) is None
    else:
        assert _terminal_ingest_ok([record], entry.media_id, entry=entry) is False


@pytest.mark.parametrize("mutator", ["missing", "renamed", "extra", "rogue_file"])
@pytest.mark.parametrize("scorer", [compute_accepted_set, score_head_to_head])
def test_scoring_binds_to_exact_declared_leg_set(tmp_path: Path, mutator: str, scorer) -> None:
    run_dir = _pinned_run(tmp_path)
    legs = run_dir / "legs"
    if mutator == "missing":
        (legs / STACK_B).rmdir()
    elif mutator == "renamed":
        (legs / STACK_B).rename(legs / "renamed-stack")
    elif mutator == "extra":
        (legs / "rogue-stack").mkdir()
    else:
        (legs / "rogue-leg.json").write_text("{}", encoding="utf-8")

    with pytest.raises(BenchError) as exc:
        scorer(run_dir)

    assert exc.value.code == "stack_pair_mismatch"


def test_scoring_rejects_empty_materialized_pair_config(tmp_path: Path) -> None:
    run_dir = _pinned_run(tmp_path)
    empty = StackPairConfig(
        stacks=(),
        head_to_head_delta=0.1,
        bootstrap_seed=1,
        primary_endpoint=PRIMARY,
        secondary_endpoints=(),
    )

    with pytest.raises(BenchError) as exc:
        _declared_stack_ids(run_dir, empty)

    assert exc.value.code == "stack_pair_invalid"


def test_score_rejects_one_stack_snapshot_before_leg_collection(tmp_path: Path) -> None:
    run_dir = _pinned_run(tmp_path)
    raw = json.loads((run_dir / "stack_pair.json").read_text(encoding="utf-8"))
    raw["stacks"] = [raw["stacks"][0]]
    (run_dir / "stack_pair.json").write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(BenchError) as exc:
        _load_pair(run_dir)

    assert exc.value.code == "pair_snapshot_invalid"


def test_attrition_writer_rejects_records_outside_declared_pair(tmp_path: Path) -> None:
    run_dir = _pinned_run(tmp_path)
    manifest = _load_manifest_from_run(run_dir)
    accepted = AcceptedSet(
        manifest_media_ids=[],
        paths=[],
        content_sha256s=[],
        accepted_set_size=0,
        detection_scoring_set=[],
        detection_scoring_set_size=0,
        manifest_entry_count=len(manifest.entries),
        floor_config=0.5,
        resolved_floor_count=2,
    )

    with pytest.raises(BenchError) as exc:
        write_attrition(
            run_dir,
            accepted,
            manifest,
            {STACK_A: [], STACK_B: [], "rogue-stack": []},
        )

    assert exc.value.code == "stack_pair_mismatch"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_differential_attrition_is_rejected(tmp_path: Path, value: float) -> None:
    with pytest.raises(BenchError) as exc:
        load_stack_pair(
            write_pair(
                tmp_path / f"pair-{str(value).replace('-', 'neg').replace('.', '_')}.yaml",
                valid_pair_dict(max_differential_attrition=value),
            )
        )

    assert exc.value.code == "max_differential_attrition_invalid"
    with pytest.raises(BenchError) as direct_exc:
        _validate_attrition(value)
    assert direct_exc.value.code == "max_differential_attrition_invalid"


@pytest.mark.parametrize("value", [0.0, 1.0])
def test_finite_differential_attrition_boundaries_remain_valid(tmp_path: Path, value: float) -> None:
    pair = load_stack_pair(
        write_pair(tmp_path / f"pair-{str(value).replace('.', '_')}.yaml", valid_pair_dict(max_differential_attrition=value))
    )

    assert pair.max_differential_attrition == value


def test_non_finite_differential_attrition_in_snapshot_is_rejected(tmp_path: Path) -> None:
    run_dir = _pinned_run(tmp_path)
    raw = json.loads((run_dir / "stack_pair.json").read_text(encoding="utf-8"))
    raw["max_differential_attrition"] = math.nan
    (run_dir / "stack_pair.json").write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(BenchError) as exc:
        _load_pair(run_dir)

    assert exc.value.code == "max_differential_attrition_invalid"


def test_stack_endpoint_allowlist_is_rechecked_for_materialized_config(tmp_path: Path) -> None:
    run_dir = _pinned_run(tmp_path)
    pair = _load_pair(run_dir)
    rogue_endpoint = type(pair.stacks[0])(
        stack_id="rogue-stack",
        role=pair.stacks[0].role,
        base_url=pair.stacks[0].base_url,
        expected_profile=pair.stacks[0].expected_profile,
        expected_pgvector_dim=pair.stacks[0].expected_pgvector_dim,
        opencv_major=pair.stacks[0].opencv_major,
        api_key_env=pair.stacks[0].api_key_env,
        tenant_id_env=pair.stacks[0].tenant_id_env,
    )
    rogue_pair = StackPairConfig(
        stacks=(rogue_endpoint, pair.stacks[1]),
        head_to_head_delta=pair.head_to_head_delta,
        bootstrap_seed=pair.bootstrap_seed,
        primary_endpoint=pair.primary_endpoint,
        secondary_endpoints=pair.secondary_endpoints,
        accepted_set_floor=pair.accepted_set_floor,
        max_differential_attrition=pair.max_differential_attrition,
    )

    with pytest.raises(BenchError) as exc:
        _declared_stack_ids(run_dir, rogue_pair)

    assert exc.value.code == "unknown_stack_id"


def test_fixture_stack_constants_remain_the_declared_pair() -> None:
    assert INSIGHTFACE_STACK["stack_id"] == STACK_A
    assert FIR_STACK["stack_id"] == STACK_B
