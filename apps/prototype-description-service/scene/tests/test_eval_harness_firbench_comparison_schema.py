"""Synthetic S6b comparison.json wire regressions; no runs, decisions, seals or private data.

EMB-01 (One embedding space per comparison, Foundations of Vector Retrieval, ch. 1) keeps
cross-run rows to native outcome deltas keyed by leg kind. EXP-30 keeps the tau fold spread
explicitly unavailable until real predeclared per-fold estimates exist. These tests check the
wire contract only: not the unimplemented compare_runs computation and not any observation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.eval_harness import firbench_contract as fc

FIXTURE = Path(__file__).parent / "fixtures" / "firbench_interchange_v1" / "comparison-v1.json"
SCHEMA = Path(fc.__file__).resolve().parent / "firbench_schemas" / "comparison-v1.json"
EXPLORATORY_LABEL = "exploratory: multi-factor, no verdict"
CHANGED_LEG_LABEL = "leg contract changed (expected)"
POOLED_REASON = "pooled_fit_threshold_no_per_fold_estimates"
SFACE_A = "sface__native__ab12cd__cv4.10.0__ort1.18.0"
SFACE_B = "sface__native__ef34cd__cv4.10.0__ort1.18.0"
AURA_A = "auraface__native__ab12cd__cv4.10.0__ort1.18.0"
ROOT_KEYS = (
    "schema_version",
    "estimand",
    "fpir_target",
    "compatibility",
    "treatment",
    "run_a",
    "run_b",
    "comparison_state",
    "label",
    "differences",
    "delta",
    "verdicts",
    "paired_deltas",
    "history",
    "tau_spread",
    "leg_changes",
)
NEW_ROOT_KEYS = ("comparison_state", "label", "differences", "paired_deltas", "history", "tau_spread", "leg_changes")
COMPATIBILITY_KEYS = (
    "estimand",
    "fpir_target",
    "decision_sha256_without_treatment",
    "gallery_sha256",
    "enrolment_probe_allocation",
    "fold_calibration_policy",
    "arm",
    "frame_bytes_sha256",
    "annotation_bytes_sha256",
    "psu_weighting_policy",
    "scorer_sha",
    "boundary_semantics",
    "opencv_version",
    "ort_version",
)
VERDICT_STATES = ["superior", "non_inferior", "inconclusive", "guardrail_vetoed", "unratified"]
SUPPORTED_KEYWORDS = frozenset(
    {
        "type",
        "const",
        "enum",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minLength",
        "maxLength",
        "pattern",
        "$ref",
        "if",
        "then",
        "else",
    }
)
ANNOTATION_KEYWORDS = frozenset({"$schema", "$id", "$defs", "$comment", "title", "description"})
NON_FINITE = (float("nan"), float("inf"), float("-inf"))


def _payload() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _validate(payload: object) -> None:
    fc.validate_interchange("comparison-v1", payload)


def _refused(payload: object, match: str | None = None) -> None:
    with pytest.raises(fc.FrameContractError, match=match):
        _validate(payload)


def _node(payload: Any, path: tuple[Any, ...]) -> Any:
    for part in path:
        payload = payload[part]
    return payload


def _object_paths(node: object, path: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    found: list[tuple[Any, ...]] = []
    if isinstance(node, dict):
        found.append(path)
        for key, value in node.items():
            found.extend(_object_paths(value, (*path, key)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_object_paths(value, (*path, index)))
    return found


def _scored(leg_kind: str = "sface", *, key_a: str = SFACE_A, key_b: str = SFACE_A) -> dict[str, Any]:
    return {
        "leg_kind": leg_kind,
        "leg_key_a": key_a,
        "leg_key_b": key_b,
        "status": "scored",
        "reason": None,
        "n_searches": 40,
        "n_psu": 12,
        "n_eff": 9.5,
        "point": 0.02,
        "lower": -0.01,
        "upper": 0.05,
    }


def _unscored(leg_kind: str = "sface", *, key: str = SFACE_A, reason: str = "no paired cohort recorded") -> dict:
    return {
        "leg_kind": leg_kind,
        "leg_key_a": key,
        "leg_key_b": key,
        "status": "not_scored",
        "reason": reason,
        "n_searches": 0,
        "n_psu": 0,
        "n_eff": 0,
        "point": None,
        "lower": None,
        "upper": None,
    }


def _rich() -> dict[str, Any]:
    """A comparable payload that fills every array and nullable form with synthetic values."""
    payload = _payload()
    payload.update(comparison_state="comparable", label="synthetic comparable contrast", differences=[])
    payload["paired_deltas"] = [_scored("sface", key_a=SFACE_A, key_b=SFACE_B), _unscored("auraface", key=AURA_A)]
    payload["delta"] = {"point": 0.02, "lower": -0.01, "upper": 0.05}
    payload["history"] = [
        {
            "leg_kind": "sface",
            "leg_key": SFACE_A,
            "points": [
                {"run_id": "run-0001", "fnir": 0.05, "tau": 0.41, "reason": None},
                {"run_id": "run-0002", "fnir": None, "tau": None, "reason": "run point not measured"},
            ],
        }
    ]
    payload["tau_spread"] = [
        {
            "leg_kind": "sface",
            "run_id": "run-0001",
            "status": "available",
            "reason": None,
            "values": [{"fold": 0, "tau": 0.41}, {"fold": 1, "tau": 0.43}],
            "minimum": 0.41,
            "maximum": 0.43,
        }
    ]
    payload["leg_changes"] = [
        {"leg_kind": "sface", "leg_key_a": SFACE_A, "leg_key_b": SFACE_B, "label": CHANGED_LEG_LABEL}
    ]
    return payload


def _exploratory() -> dict[str, Any]:
    payload = _rich()
    payload.update(
        comparison_state="exploratory",
        label=EXPLORATORY_LABEL,
        differences=["enrolment_probe_allocation", "fold_calibration_policy"],
        delta=None,
        verdicts=None,
    )
    return payload


NESTED_KEY_CASES = [
    pytest.param(path, key, id=f"{'/'.join(map(str, path)) or 'root'}:{key}")
    for path in _object_paths(_rich())
    for key in _node(_rich(), path)
]


# --- committed fixture and honest comparable/exploratory shapes -------------------------------


def test_committed_fixture_is_valid_synthetic_and_records_no_measured_cohort() -> None:
    payload = _payload()
    _validate(payload)
    assert "synthetic" in payload["label"]
    assert payload["comparison_state"] == "comparable"
    assert payload["delta"] is None
    assert payload["verdicts"] == {"run_a": "inconclusive", "run_b": "inconclusive"}
    assert payload["paired_deltas"] and all(row["status"] == "not_scored" for row in payload["paired_deltas"])
    assert payload["leg_changes"] == []
    assert all(row["status"] == "unavailable" for row in payload["tau_spread"])


def test_rich_comparable_payload_is_valid_baseline() -> None:
    _validate(_rich())


def test_exploratory_contrast_accepts_null_delta_and_null_verdicts() -> None:
    _validate(_exploratory())


def test_single_declared_treatment_field_stays_comparable() -> None:
    payload = _rich()
    payload["treatment"] = {"name": "arm", "fields": ["arm"]}
    payload["differences"] = ["arm"]
    _validate(payload)


# --- root shape: required, types, version -----------------------------------------------------


@pytest.mark.parametrize("key", NEW_ROOT_KEYS)
def test_each_new_root_field_is_required(key: str) -> None:
    payload = _rich()
    del payload[key]
    _refused(payload, match=key)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("comparison_state", "Comparable"),
        ("comparison_state", "scored"),
        ("comparison_state", None),
        ("label", ""),
        ("label", 3),
        ("label", None),
        ("differences", "arm"),
        ("differences", [1]),
        ("differences", [""]),
        ("differences", None),
        ("paired_deltas", {}),
        ("paired_deltas", None),
        ("history", None),
        ("history", "run-0001"),
        ("tau_spread", ""),
        ("tau_spread", {}),
        ("leg_changes", {"leg_kind": "sface"}),
        ("leg_changes", None),
    ],
)
def test_new_root_fields_reject_wrong_types_and_empty_labels(key: str, value: Any) -> None:
    payload = _rich()
    payload[key] = value
    _refused(payload, match=key)


@pytest.mark.parametrize("value", [2, "1", True, 1.5])
def test_schema_version_other_than_integer_one_is_refused(value: Any) -> None:
    payload = _rich()
    payload["schema_version"] = value
    _refused(payload, match="schema_version")


@pytest.mark.parametrize(("path", "key"), NESTED_KEY_CASES)
def test_removing_any_key_from_any_nested_object_is_refused(path: tuple[Any, ...], key: str) -> None:
    payload = _rich()
    del _node(payload, path)[key]
    _refused(payload)


@pytest.mark.parametrize(
    "path",
    [
        (),
        ("compatibility",),
        ("treatment",),
        ("run_a",),
        ("run_b",),
        ("delta",),
        ("verdicts",),
        ("paired_deltas", 0),
        ("history", 0),
        ("history", 0, "points", 0),
        ("tau_spread", 0),
        ("tau_spread", 0, "values", 0),
        ("leg_changes", 0),
    ],
)
def test_unknown_field_is_refused_at_every_closed_object(path: tuple[Any, ...]) -> None:
    payload = _rich()
    _node(payload, path)["unexpected_key"] = "x"
    _refused(payload, match="unknown keys")


# --- preserved compatibility, run and treatment fields ----------------------------------------


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("estimand", ""),
        ("fpir_target", "0.01"),
        ("fpir_target", True),
        ("fpir_target", 1.0),
        ("fpir_target", 0),
        ("fpir_target", float("nan")),
        ("decision_sha256_without_treatment", "D" * 64),
        ("decision_sha256_without_treatment", "d" * 63),
        ("gallery_sha256", None),
        ("enrolment_probe_allocation", ""),
        ("fold_calibration_policy", ""),
        ("arm", "gt_crop"),
        ("arm", None),
        ("frame_bytes_sha256", "a" * 65),
        ("annotation_bytes_sha256", 7),
        ("psu_weighting_policy", ""),
        ("scorer_sha", ""),
        ("boundary_semantics", "v3"),
        ("opencv_version", ""),
        ("ort_version", None),
    ],
)
def test_original_compatibility_field_types_and_domains_are_preserved(key: str, value: Any) -> None:
    payload = _rich()
    payload["compatibility"][key] = value
    _refused(payload, match=key)


@pytest.mark.parametrize(
    ("run", "key", "value"),
    [
        ("run_a", "run_id", ""),
        ("run_a", "decision_sha256", "ABC"),
        ("run_b", "scores_sha256", None),
        ("run_b", "run_id", 5),
    ],
)
def test_run_identity_fields_keep_their_types(run: str, key: str, value: Any) -> None:
    payload = _rich()
    payload[run][key] = value
    _refused(payload, match=key)


def test_compatibility_key_set_and_enum_values_are_frozen() -> None:
    schema = _schema()
    assert sorted(schema["properties"]["compatibility"]["required"]) == sorted(COMPATIBILITY_KEYS)
    assert schema["properties"]["compatibility"]["properties"]["arm"]["enum"] == [
        "native",
        "gt_crop_redetect",
        "cached_yunet_landmark_replay",
    ]
    assert schema["properties"]["compatibility"]["properties"]["boundary_semantics"]["enum"] == ["legacy_v1", "v2"]
    assert schema["properties"]["verdicts"]["properties"]["run_a"]["enum"] == VERDICT_STATES
    assert schema["properties"]["verdicts"]["properties"]["run_b"]["enum"] == VERDICT_STATES


def test_root_key_set_is_the_frozen_v2_shape() -> None:
    schema = _schema()
    assert sorted(schema["required"]) == sorted(ROOT_KEYS)
    assert set(schema["properties"]) == set(ROOT_KEYS)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"] == {"const": 1}


# --- comparable vs exploratory: verdicts, delta, labels, differences --------------------------


def test_exploratory_label_is_exact_string() -> None:
    payload = _exploratory()
    assert payload["label"] == EXPLORATORY_LABEL
    _validate(payload)


@pytest.mark.parametrize(
    "label",
    [
        "exploratory",
        "Exploratory: multi-factor, no verdict",
        "exploratory: multi-factor, no verdict.",
        "exploratory: multi-factor, no verdict\nextra",
        "",
    ],
)
def test_exploratory_state_refuses_any_other_label(label: str) -> None:
    payload = _exploratory()
    payload["label"] = label
    _refused(payload, match="label")


def test_comparable_state_cannot_borrow_the_exploratory_label() -> None:
    payload = _rich()
    payload["label"] = EXPLORATORY_LABEL
    _refused(payload, match="label")


def test_exploratory_state_refuses_a_verdict_object() -> None:
    payload = _exploratory()
    payload["verdicts"] = {"run_a": "inconclusive", "run_b": "inconclusive"}
    _refused(payload)


def test_exploratory_state_refuses_a_nonnull_legacy_delta() -> None:
    payload = _exploratory()
    payload["delta"] = {"point": 0.02, "lower": -0.01, "upper": 0.05}
    _refused(payload)


@pytest.mark.parametrize("differences", [[], ["enrolment_probe_allocation"]])
def test_exploratory_state_needs_two_or_more_undeclared_differences(differences: list[str]) -> None:
    payload = _exploratory()
    payload["differences"] = differences
    _refused(payload, match="differences")


def test_comparable_state_refuses_a_null_verdict() -> None:
    payload = _rich()
    payload["verdicts"] = None
    _refused(payload)


@pytest.mark.parametrize(
    ("run", "value"),
    [("run_a", "winner"), ("run_a", None), ("run_b", "guardrail"), ("run_b", "Superior")],
)
def test_comparable_verdict_states_are_the_original_closed_enum(run: str, value: Any) -> None:
    payload = _rich()
    payload["verdicts"][run] = value
    _refused(payload, match=run)


@pytest.mark.parametrize("state", VERDICT_STATES)
def test_comparable_verdict_keeps_every_original_state(state: str) -> None:
    payload = _rich()
    payload["verdicts"] = {"run_a": state, "run_b": "unratified"}
    _validate(payload)


def test_comparable_state_refuses_two_differences() -> None:
    payload = _rich()
    payload["differences"] = ["fpir_target", "gallery_sha256"]
    _refused(payload, match="differences")


def test_comparable_state_refuses_two_declared_treatment_fields() -> None:
    payload = _rich()
    payload["treatment"] = {"name": "arm", "fields": ["arm", "fpir_target"]}
    _refused(payload, match="fields")


@pytest.mark.parametrize("state", ["Comparable", "scored", "superior", None])
def test_comparison_state_is_a_closed_two_value_enum(state: Any) -> None:
    payload = _rich()
    payload["comparison_state"] = state
    _refused(payload, match="comparison_state")


# --- paired_deltas: scored versus unscored, counts, finiteness --------------------------------


def test_scored_row_accepts_a_finite_cohort_with_numbers() -> None:
    payload = _rich()
    payload["paired_deltas"] = [_scored()]
    payload["delta"] = {"point": 0.02, "lower": -0.01, "upper": 0.05}
    _validate(payload)


def test_scored_row_refuses_a_reason() -> None:
    payload = _rich()
    payload["paired_deltas"] = [{**_scored(), "reason": "should be null"}]
    _refused(payload, match="reason")


@pytest.mark.parametrize("field", ["point", "lower", "upper"])
def test_scored_row_refuses_missing_interval_numbers(field: str) -> None:
    payload = _rich()
    payload["paired_deltas"] = [{**_scored(), field: None}]
    _refused(payload, match=field)


@pytest.mark.parametrize("field", ["point", "lower", "upper"])
@pytest.mark.parametrize("value", [*NON_FINITE, True])
def test_scored_row_refuses_nonfinite_and_boolean_interval_numbers(field: str, value: Any) -> None:
    payload = _rich()
    payload["paired_deltas"] = [{**_scored(), field: value}]
    _refused(payload, match=field)


@pytest.mark.parametrize(("field", "value"), [("n_searches", 0), ("n_psu", 0)])
def test_scored_row_needs_a_nonempty_actual_paired_cohort(field: str, value: int) -> None:
    payload = _rich()
    payload["paired_deltas"] = [{**_scored(), field: value}]
    _refused(payload, match=field)


@pytest.mark.parametrize("reason", [None, ""])
def test_unscored_row_needs_a_named_reason(reason: Any) -> None:
    payload = _rich()
    payload["paired_deltas"] = [_unscored(reason=reason)]
    _refused(payload, match="reason")


@pytest.mark.parametrize("field", ["point", "lower", "upper"])
def test_unscored_row_refuses_numbers(field: str) -> None:
    payload = _rich()
    payload["paired_deltas"] = [{**_unscored(), field: 0.0}]
    _refused(payload, match=field)


def test_unscored_row_accepts_null_numbers_and_zero_counts() -> None:
    payload = _rich()
    payload["paired_deltas"] = [_unscored()]
    _validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("n_searches", -1),
        ("n_psu", -1),
        ("n_psu", 2.0),
        ("n_searches", True),
        ("n_psu", False),
        ("n_eff", -0.1),
        ("n_eff", float("nan")),
        ("n_eff", True),
        ("n_eff", "9"),
    ],
)
def test_counts_are_nonnegative_integers_and_n_eff_is_finite_nonnegative(field: str, value: Any) -> None:
    payload = _rich()
    payload["paired_deltas"] = [{**_scored(), field: value}]
    _refused(payload, match=field)


@pytest.mark.parametrize("status", ["pending", "available", None])
def test_paired_status_is_scored_or_not_scored(status: Any) -> None:
    payload = _rich()
    payload["paired_deltas"] = [{**_scored(), "status": status}]
    _refused(payload, match="status")


@pytest.mark.parametrize("leg_kind", ["arcface", "SFace", "native", "", None])
@pytest.mark.parametrize("location", ["paired_deltas", "history", "tau_spread", "leg_changes"])
def test_leg_kind_outside_the_four_value_model_enum_is_refused(location: str, leg_kind: Any) -> None:
    payload = _rich()
    payload[location][0]["leg_kind"] = leg_kind
    _refused(payload, match="leg_kind")


@pytest.mark.parametrize("leg_kind", ["sface", "auraface", "insightface", "canary"])
def test_leg_kind_accepts_each_model_enum_value(leg_kind: str) -> None:
    payload = _rich()
    payload["paired_deltas"][0]["leg_kind"] = leg_kind
    payload["history"][0]["leg_kind"] = leg_kind
    payload["tau_spread"][0]["leg_kind"] = leg_kind
    payload["leg_changes"][0]["leg_kind"] = leg_kind
    _validate(payload)


# --- history: actual supplied points, finite nullable numbers ---------------------------------


@pytest.mark.parametrize("field", ["fnir", "tau"])
@pytest.mark.parametrize("value", [*NON_FINITE, True, "0.05"])
def test_history_points_refuse_nonfinite_boolean_and_string_numbers(field: str, value: Any) -> None:
    payload = _rich()
    payload["history"][0]["points"][0][field] = value
    _refused(payload, match=field)


def test_history_point_run_id_is_nonempty() -> None:
    payload = _rich()
    payload["history"][0]["points"][0]["run_id"] = ""
    _refused(payload, match="run_id")


def test_history_points_keep_null_for_unmeasured_run_points() -> None:
    payload = _rich()
    payload["history"][0]["points"] = [
        {"run_id": "run-0001", "fnir": None, "tau": None, "reason": "run point not measured"}
    ]
    _validate(payload)


@pytest.mark.parametrize("field", ["point", "lower", "upper"])
@pytest.mark.parametrize("value", [*NON_FINITE, True])
def test_legacy_delta_refuses_nonfinite_and_boolean_numbers(field: str, value: Any) -> None:
    payload = _rich()
    payload["delta"][field] = value
    _refused(payload, match=field)


# --- tau_spread: explicit unavailable pooled fit, never an invented spread --------------------


def test_pooled_primary_tau_is_explicitly_unavailable() -> None:
    payload = _rich()
    payload["tau_spread"] = [
        {
            "leg_kind": "sface",
            "run_id": "run-0001",
            "status": "unavailable",
            "reason": POOLED_REASON,
            "values": [],
            "minimum": None,
            "maximum": None,
        }
    ]
    _validate(payload)


@pytest.mark.parametrize(
    "override",
    [
        {"values": [{"fold": 0, "tau": 0.41}]},
        {"minimum": 0.41},
        {"maximum": 0.41},
    ],
)
def test_unavailable_tau_cannot_carry_values_or_extrema(override: dict[str, Any]) -> None:
    payload = _rich()
    payload["tau_spread"] = [
        {
            "leg_kind": "sface",
            "run_id": "run-0001",
            "status": "unavailable",
            "reason": POOLED_REASON,
            "values": [],
            "minimum": None,
            "maximum": None,
            **override,
        }
    ]
    _refused(payload)


def test_unavailable_tau_needs_a_named_reason() -> None:
    payload = _rich()
    payload["tau_spread"] = [
        {
            "leg_kind": "sface",
            "run_id": "run-0001",
            "status": "unavailable",
            "reason": None,
            "values": [],
            "minimum": None,
            "maximum": None,
        }
    ]
    _refused(payload, match="reason")


def test_available_tau_needs_declared_per_fold_values() -> None:
    payload = _rich()
    payload["tau_spread"][0]["values"] = []
    _refused(payload, match="values")


def test_available_tau_reason_must_be_null() -> None:
    payload = _rich()
    payload["tau_spread"][0]["reason"] = "should be null"
    _refused(payload, match="reason")


@pytest.mark.parametrize("field", ["minimum", "maximum"])
def test_available_tau_needs_numeric_extrema(field: str) -> None:
    payload = _rich()
    payload["tau_spread"][0][field] = None
    _refused(payload, match=field)


@pytest.mark.parametrize("fold", [-1, 0.0, True, "0"])
def test_tau_fold_is_a_nonnegative_integer(fold: Any) -> None:
    payload = _rich()
    payload["tau_spread"][0]["values"][0]["fold"] = fold
    _refused(payload, match="fold")


@pytest.mark.parametrize("value", [*NON_FINITE, True])
def test_tau_values_refuse_nonfinite_and_boolean_numbers(value: Any) -> None:
    payload = _rich()
    payload["tau_spread"][0]["values"][0]["tau"] = value
    _refused(payload, match="tau")


@pytest.mark.parametrize("status", ["pending", "pooled", None])
def test_tau_status_is_available_or_unavailable(status: Any) -> None:
    payload = _rich()
    payload["tau_spread"][0]["status"] = status
    _refused(payload, match="status")


# --- leg_changes: fingerprint change label only, no runtime mismatch -------------------------


def test_leg_change_label_is_exact_changed_fingerprint_label() -> None:
    payload = _rich()
    payload["leg_changes"][0]["label"] = CHANGED_LEG_LABEL
    _validate(payload)


@pytest.mark.parametrize("label", ["", "leg contract changed", "runtime mismatch", "Leg contract changed (expected)"])
def test_leg_change_refuses_any_other_label(label: str) -> None:
    payload = _rich()
    payload["leg_changes"][0]["label"] = label
    _refused(payload, match="label")


def test_leg_change_accepts_a_changed_fingerprint_between_run_a_and_run_b_keys() -> None:
    payload = _rich()
    payload["leg_changes"][0]["leg_key_b"] = SFACE_B
    _validate(payload)


# --- structural: stdlib keywords only, closed objects, typed arrays ---------------------------


def _schema_nodes(node: object, *, branches: bool = True) -> list[dict[str, Any]]:
    """Schema objects in the document: root, $defs, properties and items, plus if/then/else when branches."""
    found: list[dict[str, Any]] = []
    if not isinstance(node, dict):
        return found
    found.append(node)
    for key, value in node.items():
        if key in ("properties", "$defs") and isinstance(value, dict):
            for sub in value.values():
                found.extend(_schema_nodes(sub, branches=branches))
        elif key == "items" or (branches and key in ("if", "then", "else")):
            found.extend(_schema_nodes(value, branches=branches))
    return found


def test_schema_uses_only_keywords_the_stdlib_checker_implements() -> None:
    for node in _schema_nodes(_schema()):
        unsupported = set(node) - SUPPORTED_KEYWORDS - ANNOTATION_KEYWORDS
        assert not unsupported, unsupported


def test_every_object_is_closed_and_every_array_has_a_typed_items_schema() -> None:
    # Conditional branches only refine a closed base definition, so they are checked through it.
    for node in _schema_nodes(_schema(), branches=False):
        types = node.get("type", [])
        types = types if isinstance(types, list) else [types]
        if "object" in types:
            assert node.get("additionalProperties") is False, node
            assert isinstance(node.get("properties"), dict), node
        if "array" in types:
            assert isinstance(node.get("items"), dict), node


def test_leg_kind_definition_is_the_four_value_model_enum() -> None:
    enum = _schema()["$defs"]["leg_kind"]["enum"]
    assert len(enum) == len(set(enum)) == 4
    assert sorted(enum) == sorted(kind.value for kind in fc.LegKind)


def test_comparison_state_definition_is_exact() -> None:
    assert _schema()["properties"]["comparison_state"] == {"enum": ["comparable", "exploratory"]}
