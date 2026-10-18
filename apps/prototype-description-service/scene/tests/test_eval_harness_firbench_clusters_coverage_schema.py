"""Synthetic clusters-v1 wire regressions for the optional per-leg vector_coverage block.

The block is a conditional diagnostic: it reports how many GT faces had usable embedded
vectors in the leg cache. Pure core payloads may omit it; the materializer is specified to
always write it, a producer change outside this schema lane. The stdlib schema checks only
types, the frozen label and conditional flag, and non-negative bounds. Cross-field
arithmetic (embedded + missing = Ngt, named <= Ngt) belongs to production IO and appears
here only as a test-side oracle. Fake counts and synthetic identities only; no embeddings,
tenant stores or private data.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.eval_harness import firbench_contract as fc

FIXTURES = Path(__file__).parent / "fixtures" / "firbench_interchange_v1"
COVERAGE_LABEL = "diagnostics conditional on available GT vectors"
COVERAGE_KEYS = (
    "label",
    "conditional",
    "n_gt_faces",
    "n_named_gt_faces",
    "n_embedded_gt_faces",
    "n_missing_gt_faces",
    "n_embedded_named_faces",
    "n_detector_only_rows",
)
STRICT_COUNTS = ("n_gt_faces", "n_named_gt_faces")
NULLABLE_COUNTS = ("n_embedded_gt_faces", "n_missing_gt_faces", "n_embedded_named_faces", "n_detector_only_rows")


def _coverage(**overrides: Any) -> dict[str, Any]:
    """Full synthetic coverage over the four fixture faces, all named and all embedded."""
    coverage: dict[str, Any] = {
        "label": COVERAGE_LABEL,
        "conditional": True,
        "n_gt_faces": 4,
        "n_named_gt_faces": 4,
        "n_embedded_gt_faces": 4,
        "n_missing_gt_faces": 0,
        "n_embedded_named_faces": 4,
        "n_detector_only_rows": 0,
    }
    coverage.update(overrides)
    return coverage


def _payload_without_coverage() -> dict[str, Any]:
    """Pure-core payload: the frozen fixture with the optional block removed."""
    payload = json.loads((FIXTURES / "clusters-v1.json").read_text(encoding="utf-8"))
    payload["legs"][0].pop("vector_coverage", None)
    return payload


def _payload_with_coverage(**overrides: Any) -> dict[str, Any]:
    payload = _payload_without_coverage()
    payload["legs"][0]["vector_coverage"] = _coverage(**overrides)
    return payload


def _validate(payload: dict[str, Any]) -> None:
    fc.validate_interchange("clusters-v1", payload)


def test_absent_block_is_accepted_for_pure_core_payloads() -> None:
    payload = _payload_without_coverage()
    assert "vector_coverage" not in payload["legs"][0]
    _validate(payload)


def test_complete_block_is_accepted() -> None:
    _validate(_payload_with_coverage())


def test_block_is_optional_per_leg_and_legs_may_mix() -> None:
    payload = _payload_with_coverage()
    second = copy.deepcopy(payload["legs"][0])
    second.pop("vector_coverage")
    second["leg_key"] = "auraface__native__cd34ef__cv4.10.0__ort1.18.0"
    payload["legs"].append(second)
    _validate(payload)


def test_zero_counts_are_accepted_as_explicit_zeros() -> None:
    _validate(
        _payload_with_coverage(
            n_gt_faces=0,
            n_named_gt_faces=0,
            n_embedded_gt_faces=0,
            n_missing_gt_faces=0,
            n_embedded_named_faces=0,
            n_detector_only_rows=0,
        )
    )


@pytest.mark.parametrize("field", NULLABLE_COUNTS)
def test_each_nullable_count_accepts_null(field: str) -> None:
    _validate(_payload_with_coverage(**{field: None}))


def test_absent_cache_nulls_all_four_nullable_counts() -> None:
    _validate(
        _payload_with_coverage(
            n_embedded_gt_faces=None,
            n_missing_gt_faces=None,
            n_embedded_named_faces=None,
            n_detector_only_rows=None,
        )
    )


@pytest.mark.parametrize("key", COVERAGE_KEYS)
def test_every_coverage_key_is_required(key: str) -> None:
    payload = _payload_with_coverage()
    del payload["legs"][0]["vector_coverage"][key]
    with pytest.raises(fc.FrameContractError, match=rf"vector_coverage.*missing required key '{key}'"):
        _validate(payload)


@pytest.mark.parametrize("extra", ["n_embedded_vectors", "timing_ms", "raw_names"])
def test_unknown_coverage_keys_are_refused(extra: str) -> None:
    payload = _payload_with_coverage()
    payload["legs"][0]["vector_coverage"][extra] = 1
    with pytest.raises(fc.FrameContractError, match=rf"vector_coverage.*{extra}"):
        _validate(payload)


@pytest.mark.parametrize("block", [None, [], "coverage", True])
def test_present_block_must_be_an_object(block: Any) -> None:
    payload = _payload_without_coverage()
    payload["legs"][0]["vector_coverage"] = block
    with pytest.raises(fc.FrameContractError, match=r"vector_coverage: expected object"):
        _validate(payload)


@pytest.mark.parametrize("field", STRICT_COUNTS)
@pytest.mark.parametrize(
    "value",
    ["4", 4.0, 1.5, True, False, None, [], {}, float("nan"), float("inf"), -float("inf"), -1],
)
def test_strict_counts_refuse_wrong_types_bools_nonfinite_nulls_and_negatives(field: str, value: Any) -> None:
    payload = _payload_with_coverage(**{field: value})
    with pytest.raises(fc.FrameContractError, match=rf"vector_coverage\.{field}"):
        _validate(payload)


@pytest.mark.parametrize("field", NULLABLE_COUNTS)
@pytest.mark.parametrize(
    "value",
    ["1", 1.5, 2.0, True, False, [], {}, float("nan"), float("inf"), -float("inf"), -1],
)
def test_nullable_counts_refuse_wrong_types_bools_nonfinite_and_negatives(field: str, value: Any) -> None:
    payload = _payload_with_coverage(**{field: value})
    with pytest.raises(fc.FrameContractError, match=rf"vector_coverage\.{field}"):
        _validate(payload)


@pytest.mark.parametrize("label", ["diagnostics conditional on usable GT vectors", "", "diagnostics", None])
def test_label_is_a_frozen_constant(label: Any) -> None:
    payload = _payload_with_coverage(label=label)
    with pytest.raises(fc.FrameContractError, match=r"vector_coverage\.label"):
        _validate(payload)


@pytest.mark.parametrize("value", [False, None, 1, 0, "true"])
def test_conditional_flag_must_be_boolean_true(value: Any) -> None:
    payload = _payload_with_coverage(conditional=value)
    with pytest.raises(fc.FrameContractError, match=r"vector_coverage\.conditional"):
        _validate(payload)


def test_fixture_block_is_synthetic_full_coverage_matching_partition_counts() -> None:
    payload = json.loads((FIXTURES / "clusters-v1.json").read_text(encoding="utf-8"))
    _validate(payload)
    leg = payload["legs"][0]
    partition = leg["partition_metrics"]["data"]
    coverage = leg["vector_coverage"]
    assert set(coverage) == set(COVERAGE_KEYS)
    assert coverage["label"] == COVERAGE_LABEL and coverage["conditional"] is True
    expected_gt = partition["named_faces"] + partition["unknown_faces"] + partition["unresolved_faces"]
    assert coverage["n_gt_faces"] == expected_gt == 4
    assert coverage["n_named_gt_faces"] == partition["named_faces"]
    assert coverage["n_embedded_gt_faces"] == expected_gt
    assert coverage["n_missing_gt_faces"] == 0
    assert coverage["n_embedded_named_faces"] == partition["named_faces"]
    assert coverage["n_detector_only_rows"] == 0
    assert coverage["n_embedded_gt_faces"] + coverage["n_missing_gt_faces"] == coverage["n_gt_faces"]
