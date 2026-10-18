"""GTMC Aura compound-role acceptance: normative cases for the identity-only repair role.

Tests only. This is a new module; production is unchanged in this lane.

Every case reuses the frozen fixture builders in ``test_gtmr_aura_acceptance``
(``_aura_case`` and its mutators) and calls the real Aura acceptance facade through
``_future_acceptance``. Each negative changes only the named contradiction. The
evidence digest is rebound to the mutated snapshot unless the case tests digest
binding itself.

Causal RED against the committed checkout:

* a missing persisted-ids observation beside an independent worker source-tree
  contradiction must be ``invalid``; today the missing observation short-circuits to
  ``incomplete``;
* the real chown-only ``fix-blob-ownership`` producer (role, image digest, source git
  SHA, blob volume; no models, no env, no loaded artifact) must be accepted under the
  explicitly selected Aura mode; today the closed snapshot schema refuses it.
* a present wrong weight pin beside a null or partial loaded-weight value on one evidence
  role must be ``invalid``; today the shared guard reports ``incomplete`` and the facade
  masks the contradiction.

The loaded-evidence rows that strip the repair record are RED only through that
refusal. The identity-only repair wrong source and image rows name the exact comparison
reason, so the same closed-schema refusal cannot satisfy them; their full-record twins
are the green anchors. The full-record pin controls show the observed pins are really
compared.

Controls that stay green: strict role absence, duplicate and unknown-role refusal,
full-record pin refusal (including the full-record repair source and image pins),
whole-field and wrapper-value-member absence refused as structure, stale digest
binding, complete healthy evidence, and the legacy closed-v1 contract.

Offline only: no DB, network, GPU, secrets, or model load.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest

from .test_gtmr_aura_acceptance import (
    ALT_DIGEST,
    AURA_LABEL,
    SIBLING_LABEL,
    STALE_SOURCE_GIT_SHA,
    STALE_SOURCE_TREE,
    YUNET_SHA256,
    Expect,
    _aura_case,
    _baseline_snapshot,
    _del_evidence,
    _del_prov,
    _del_target_category,
    _future_acceptance,
    _incomplete,
    _invalid,
    _role,
    _set_evidence,
    _set_evidence_license,
    _set_snapshot_role_field,
    _set_storage,
    _snapshot_digest,
    _target_identities,
    _validate,
)

Mutate = Callable[[dict[str, Any]], None]
Row = tuple[str, Expect, tuple[Mutate, ...]]

REPAIR_ROLE = "fix-blob-ownership"
STORE = "enrolled"
# Observation fields this module mutates. Verified against the frozen fixture.
SCHEMA_FIELD = "schema_version"
AUTH_FIELD = "auth_enabled"
# Required target category holding the database-side network identity.
TARGET_CATEGORY = "networks"
# Observation fields the chown-only producer never emits: no model, preprocessing, env, or loaded artifact.
REPAIR_EXCLUDED_FIELDS: tuple[str, ...] = (
    "effective_profile",
    "embedding_dimension",
    "model_id",
    "preprocessing_id",
    "loaded_weight_hashes",
    AUTH_FIELD,
)
_WRONG_API_WEIGHTS = {"yunet": YUNET_SHA256, "auraface": ALT_DIGEST}
_PARTIAL_WEIGHTS = {"yunet": YUNET_SHA256}
WEIGHTS_FIELD = "loaded_weight_hashes"
# Exact reasons for the identity-only repair contradictions: divergence of the repair source from the
# evidence roles (rung 7, checked before the pin), and the shared cross-role image-digest comparison.
SOURCE_DIVERGENCE = "role_source_identity_mismatch"
IMAGE_DIVERGENCE = "role_image_digest_mismatch"
# A wrong complete weight pin on one role, with the other role partial or null, is a present contradiction.
WEIGHT_CONTRADICTION = ("model_asset_hash_unexpected", "role_loaded_weight_hash_mismatch")


def _drop_role(role: str) -> Mutate:
    def mutate(case: dict[str, Any]) -> None:
        case["snapshot"]["observations"] = [r for r in case["snapshot"]["observations"] if r["role"] != role]

    return mutate


def _append_role_copy(role: str, new_role: str) -> Mutate:
    def mutate(case: dict[str, Any]) -> None:
        record = copy.deepcopy(_role(case["snapshot"], role))
        record["role"] = new_role
        case["snapshot"]["observations"].append(record)

    return mutate


def _del_snapshot_role_field(role: str, field: str) -> Mutate:
    def mutate(case: dict[str, Any]) -> None:
        del _role(case["snapshot"], role)[field]

    return mutate


def _del_snapshot_wrapper_member(role: str, field: str, member: str) -> Mutate:
    def mutate(case: dict[str, Any]) -> None:
        del _role(case["snapshot"], role)[field][member]

    return mutate


def _set_schema(version: int) -> Mutate:
    def mutate(case: dict[str, Any]) -> None:
        case["snapshot"][SCHEMA_FIELD] = version

    return mutate


def _strip_repair_snapshot(snapshot: dict[str, Any]) -> None:
    """Keep only identity on the repair record: the real producer reports no runtime evidence."""

    record = _role(snapshot, REPAIR_ROLE)
    for field in REPAIR_EXCLUDED_FIELDS:
        record.pop(field, None)


def _strip_repair_runtime(case: dict[str, Any]) -> None:
    _strip_repair_snapshot(case["snapshot"])


def _reverse_observations(case: dict[str, Any]) -> None:
    case["snapshot"]["observations"].reverse()


def _build(store: str, mutations: tuple[Mutate, ...], *, rebind: bool = True) -> dict[str, Any]:
    case = _aura_case(AURA_LABEL, store=store)
    for mutate in mutations:
        mutate(case)
    if rebind:
        case["aura_evidence"]["snapshot_sha256"] = _snapshot_digest(case["snapshot"])
    return case


def _assert_status(result: dict[str, Any], expected: Expect, context: str) -> None:
    status, exit_code, _ = expected
    actual = (result.get("status"), result.get("exit_code"))
    assert actual == (status, exit_code), (
        f"{context}: expected status={status} exit_code={exit_code}; "
        f"actual status={result.get('status')} exit_code={result.get('exit_code')} "
        f"reason_code={result.get('reason_code')}"
    )


def _assert_expectation(result: dict[str, Any], expected: Expect, context: str) -> None:
    """Status and exit code always; the reason code too whenever the row names one."""

    _assert_status(result, expected, context)
    reasons = expected[2]
    if reasons:
        assert result.get("reason_code") in reasons, (
            f"{context}: expected reason_code in {sorted(reasons)}; actual reason_code={result.get('reason_code')!r}"
        )


def _run_row(case_id: str, expected: Expect, mutations: tuple[Mutate, ...], *, rebind: bool = True) -> None:
    case = _build(STORE, mutations, rebind=rebind)
    _assert_expectation(_future_acceptance(case_id, case, expected), expected, case_id)


def _ready() -> Expect:
    return ("ready", 0, frozenset({"ready"}))


def _ids(rows: tuple[Row, ...]) -> list[str]:
    return [row[0] for row in rows]


# Independent authoritative contradictions: invalid even when a missing observation is also present.
COMPOUND_INVALID: tuple[Row, ...] = (
    ("missing_worker_with_schema2", _invalid(), (_drop_role("worker"), _set_schema(2))),
    (
        "missing_worker_with_auth_false",
        _invalid(),
        (_drop_role("worker"), _set_snapshot_role_field("api", AUTH_FIELD, False)),
    ),
    (
        "missing_persisted_ids_with_wrong_worker_source_tree",
        _invalid(),
        (_del_prov("persisted_model_ids"), _set_evidence("worker", "source_tree", STALE_SOURCE_TREE)),
    ),
    (
        "target_missing_with_present_wrong_resource",
        _invalid(),
        (
            _del_target_category(TARGET_CATEGORY),
            _set_storage("network_ids", [_target_identities(SIBLING_LABEL)["network"]]),
        ),
    ),
)

# Missing-only observation: incomplete, never invalid.
MISSING_ONLY: tuple[Row, ...] = (("missing_persisted_ids_only", _incomplete(), (_del_prov("persisted_model_ids"),)),)

# Strict role contract (existing closed-v1 refusal, kept): an absent role is refused, not incomplete.
ROLE_ABSENT_REFUSED: tuple[Row, ...] = (
    ("missing_worker_role", _invalid(), (_drop_role("worker"),)),
    ("missing_repair_role", _invalid(), (_drop_role(REPAIR_ROLE),)),
)

# Duplicate and unknown roles beside the identity-only repair record. Legacy refusals, unchanged.
REPAIR_REFUSED: tuple[Row, ...] = (
    ("duplicate_repair_role", _invalid(), (_strip_repair_runtime, _append_role_copy(REPAIR_ROLE, REPAIR_ROLE))),
    (
        "unknown_role_beside_repair",
        _invalid(),
        (_strip_repair_runtime, _append_role_copy(REPAIR_ROLE, "fix-blob-chown")),
    ),
)

# Identity-only repair with a wrong source or image pin. Each row names the exact comparison reason: a
# closed-schema refusal of the stripped record is not that comparison and cannot satisfy the row.
# RED against unfixed V1 by design. The full-record twins in FULL_RECORD_PIN_REFUSED are the green anchors.
IDENTITY_ONLY_NAMED_REFUSAL: tuple[Row, ...] = (
    (
        "repair_source_git_sha_contradicts_approved_pin",
        _invalid(SOURCE_DIVERGENCE),
        (_strip_repair_runtime, _set_snapshot_role_field(REPAIR_ROLE, "source_git_sha", STALE_SOURCE_GIT_SHA)),
    ),
    (
        "repair_image_digest_contradicts_api",
        _invalid(IMAGE_DIVERGENCE),
        (_strip_repair_runtime, _set_snapshot_role_field(REPAIR_ROLE, "image_digest", ALT_DIGEST)),
    ),
)

# API/worker loaded evidence is not relaxed by the repair record. Missing is incomplete; wrong is invalid.
LOADED_EVIDENCE_WITH_REPAIR: tuple[Row, ...] = (
    (
        "api_missing_weight_hashes",
        _incomplete("incomplete_loaded_weight_hashes"),
        (_strip_repair_runtime, _set_snapshot_role_field("api", WEIGHTS_FIELD, None)),
    ),
    (
        "api_missing_license_hashes",
        _incomplete(),
        (_strip_repair_runtime, _del_evidence("api", "loaded_license_hashes")),
    ),
    (
        "worker_missing_preprocessing_contract",
        _incomplete(),
        (_strip_repair_runtime, _del_evidence("worker", "preprocessing_contract")),
    ),
    (
        "worker_wrong_license_pin",
        _invalid(),
        (_strip_repair_runtime, _set_evidence_license(("worker",), "auraface", ALT_DIGEST)),
    ),
    (
        "api_wrong_weight_pin",
        _invalid(),
        (_strip_repair_runtime, _set_snapshot_role_field("api", "loaded_weight_hashes", _WRONG_API_WEIGHTS)),
    ),
)

# Full-record controls (no repair strip): the same wrong pins are refused by the existing comparison.
FULL_RECORD_PIN_REFUSED: tuple[Row, ...] = (
    (
        "worker_wrong_license_pin_full_record",
        _invalid(),
        (_set_evidence_license(("worker",), "auraface", ALT_DIGEST),),
    ),
    (
        "api_wrong_weight_pin_full_record",
        _invalid(),
        (_set_snapshot_role_field("api", "loaded_weight_hashes", _WRONG_API_WEIGHTS),),
    ),
    (
        "repair_source_git_sha_full_record",
        _invalid(SOURCE_DIVERGENCE),
        (_set_snapshot_role_field(REPAIR_ROLE, "source_git_sha", STALE_SOURCE_GIT_SHA),),
    ),
    (
        "repair_image_digest_full_record",
        _invalid(IMAGE_DIVERGENCE),
        (_set_snapshot_role_field(REPAIR_ROLE, "image_digest", ALT_DIGEST),),
    ),
)


# Facade mask: one evidence role's loaded-weight value is null or partial while the peer role carries a complete
# wrong pin. The contradiction outranks the missing value, so the facade must answer invalid, not incomplete.
# The repair record stays full, so the closed schema is not the factor under test.
PARTIAL_WEIGHT_FACADE_MASK: tuple[Row, ...] = (
    (
        "api_weights_null_worker_wrong_peer",
        _invalid(*WEIGHT_CONTRADICTION),
        (
            _set_snapshot_role_field("api", WEIGHTS_FIELD, None),
            _set_snapshot_role_field("worker", WEIGHTS_FIELD, _WRONG_API_WEIGHTS),
        ),
    ),
    (
        "api_weights_partial_worker_wrong_peer",
        _invalid(*WEIGHT_CONTRADICTION),
        (
            _set_snapshot_role_field("api", WEIGHTS_FIELD, _PARTIAL_WEIGHTS),
            _set_snapshot_role_field("worker", WEIGHTS_FIELD, _WRONG_API_WEIGHTS),
        ),
    ),
    (
        "worker_weights_null_api_wrong_peer",
        _invalid(*WEIGHT_CONTRADICTION),
        (
            _set_snapshot_role_field("worker", WEIGHTS_FIELD, None),
            _set_snapshot_role_field("api", WEIGHTS_FIELD, _WRONG_API_WEIGHTS),
        ),
    ),
    (
        "worker_weights_partial_api_wrong_peer",
        _invalid(*WEIGHT_CONTRADICTION),
        (
            _set_snapshot_role_field("worker", WEIGHTS_FIELD, _PARTIAL_WEIGHTS),
            _set_snapshot_role_field("api", WEIGHTS_FIELD, _WRONG_API_WEIGHTS),
        ),
    ),
)

# Distinct structural controls: a whole observation field, or one wrapper member, absent is refused as structure
# and is never reported as incomplete evidence. Green on unchanged V1.
STRUCTURAL_ABSENCE_REFUSED: tuple[Row, ...] = (
    (
        "api_loaded_weight_hashes_field_absent",
        _invalid("snapshot_schema_invalid"),
        (_del_snapshot_role_field("api", WEIGHTS_FIELD),),
    ),
    (
        "api_loaded_weight_hashes_value_member_absent",
        _invalid("malformed_observation_wrapper"),
        (_del_snapshot_wrapper_member("api", WEIGHTS_FIELD, "value"),),
    ),
)


@pytest.mark.parametrize(("case_id", "expected", "mutations"), COMPOUND_INVALID, ids=_ids(COMPOUND_INVALID))
def test_future_compound_contradiction_is_invalid(
    case_id: str, expected: Expect, mutations: tuple[Mutate, ...]
) -> None:
    _run_row(case_id, expected, mutations)


@pytest.mark.parametrize(("case_id", "expected", "mutations"), MISSING_ONLY, ids=_ids(MISSING_ONLY))
def test_future_missing_only_is_incomplete(case_id: str, expected: Expect, mutations: tuple[Mutate, ...]) -> None:
    _run_row(case_id, expected, mutations)


@pytest.mark.parametrize(("case_id", "expected", "mutations"), ROLE_ABSENT_REFUSED, ids=_ids(ROLE_ABSENT_REFUSED))
def test_control_strict_role_absence_is_refused(case_id: str, expected: Expect, mutations: tuple[Mutate, ...]) -> None:
    _run_row(case_id, expected, mutations)


@pytest.mark.parametrize(("case_id", "expected", "mutations"), REPAIR_REFUSED, ids=_ids(REPAIR_REFUSED))
def test_control_repair_role_contract_refuses(case_id: str, expected: Expect, mutations: tuple[Mutate, ...]) -> None:
    _run_row(case_id, expected, mutations)


@pytest.mark.parametrize(
    ("case_id", "expected", "mutations"), FULL_RECORD_PIN_REFUSED, ids=_ids(FULL_RECORD_PIN_REFUSED)
)
def test_control_full_record_wrong_pin_is_refused(
    case_id: str, expected: Expect, mutations: tuple[Mutate, ...]
) -> None:
    _run_row(case_id, expected, mutations)


@pytest.mark.parametrize(
    ("case_id", "expected", "mutations"), LOADED_EVIDENCE_WITH_REPAIR, ids=_ids(LOADED_EVIDENCE_WITH_REPAIR)
)
def test_future_loaded_evidence_still_required_with_repair(
    case_id: str, expected: Expect, mutations: tuple[Mutate, ...]
) -> None:
    _run_row(case_id, expected, mutations)


@pytest.mark.parametrize(
    ("case_id", "expected", "mutations"), IDENTITY_ONLY_NAMED_REFUSAL, ids=_ids(IDENTITY_ONLY_NAMED_REFUSAL)
)
def test_future_identity_only_repair_wrong_pin_is_refused_by_name(
    case_id: str, expected: Expect, mutations: tuple[Mutate, ...]
) -> None:
    _run_row(case_id, expected, mutations)


@pytest.mark.parametrize(
    ("case_id", "expected", "mutations"), PARTIAL_WEIGHT_FACADE_MASK, ids=_ids(PARTIAL_WEIGHT_FACADE_MASK)
)
def test_future_partial_weight_contradiction_is_not_masked(
    case_id: str, expected: Expect, mutations: tuple[Mutate, ...]
) -> None:
    _run_row(case_id, expected, mutations)


@pytest.mark.parametrize(
    ("case_id", "expected", "mutations"), STRUCTURAL_ABSENCE_REFUSED, ids=_ids(STRUCTURAL_ABSENCE_REFUSED)
)
def test_control_structural_absence_is_refused_not_incomplete(
    case_id: str, expected: Expect, mutations: tuple[Mutate, ...]
) -> None:
    _run_row(case_id, expected, mutations)


def test_control_complete_enrolled_evidence_is_ready() -> None:
    _run_row("complete_enrolled_evidence", _ready(), ())


def test_future_identity_only_repair_record_is_ready() -> None:
    case = _build(STORE, (_strip_repair_runtime,))
    repair = _role(case["snapshot"], REPAIR_ROLE)
    # Precondition: the repair record carries identity only and no invented loaded fields.
    assert {"role", "image_digest", "source_git_sha"} <= set(repair), sorted(repair)
    assert not set(REPAIR_EXCLUDED_FIELDS) & set(repair), sorted(repair)
    _assert_status(_future_acceptance("identity_only_repair", case, _ready()), _ready(), "identity_only_repair")


def test_control_stale_snapshot_digest_is_refused() -> None:
    """Changing the bound snapshot without rebinding the evidence digest must refuse."""

    _run_row("stale_snapshot_digest", _invalid(), (_reverse_observations,), rebind=False)


def test_control_legacy_closed_v1_refuses_identity_only_repair_record() -> None:
    """Legacy closed-v1 contract is unchanged: a chown-only repair record never satisfies it."""

    snapshot = _baseline_snapshot()
    assert _validate(snapshot, contract="baseline128")["status"] == "ready"
    _strip_repair_snapshot(snapshot)
    result = _validate(snapshot, contract="baseline128")
    assert result["status"] != "ready", f"closed-v1 accepted identity-only repair: {result}"
