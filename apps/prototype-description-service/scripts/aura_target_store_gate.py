"""Target and store gate for the offline AuraFace acceptance contract.

``validate_target_store`` checks the rungs the Aura target owns: the operator-selected label, the six
required isolation categories, the observed target identities, the persisted-model census, the vector
column census, and the representative norm. It is stdlib-only and offline. It never collects evidence,
opens a connection, or prints the raw policy or snapshot.

Return contract
---------------
``None`` means every rung owned by this helper is complete and consistent. Otherwise the helper returns
``(status, reason_code)`` where ``status`` is ``"incomplete"`` (a reported observation is missing or
unreadable) or ``"invalid"`` (a contradiction or a malformed policy). A missing observation is never
filled with an expected value.

Reuse
-----
The vector-inventory rule, the store-state rule, and the incomplete-reason classification come from
``scripts.validate_fir_dev_runtime`` rather than being copied. The facade runs the shared closed v1
guard before this helper, so schema and freshness rules are not repeated here.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from scripts.validate_fir_dev_runtime import (
    _INCOMPLETE_REASON_CODES,
    _UNRESOLVED_MODEL_MARKERS,
    EXPECTED_CONTRACTS,
    EXPECTED_VECTOR_COLUMNS,
    _is_finite_vector,
    _parse_model_id,
    _validate_store_state,
    _vector_inventory_is_incomplete,
)

AURA_LABELS: tuple[str, ...] = ("dev-auraface", "staging-auraface", "prod-auraface")
TARGET_CATEGORIES: tuple[str, ...] = (
    "volumes",
    "networks",
    "compose_projects",
    "database_names",
    "database_roles",
    "blob_namespaces",
)
# WHY: the candidate512 contract is the single source of the Aura model-space pin.
_AURA_CONTRACT: Mapping[str, Any] = EXPECTED_CONTRACTS["candidate512"]
AURA_EMBEDDING_DIMENSION: int = _AURA_CONTRACT["embedding_dimension"]
AURA_MODEL_PREFIX: str = _AURA_CONTRACT["model_name_prefix"]
AURA_MODEL_SUFFIX: tuple[str, ...] = tuple(_AURA_CONTRACT["model_suffix"])
# Production CHECK rule: db/models/identity.py abs(vector_norm(embedding) - 1.0) < 0.01.
NORM_TOLERANCE: float = 0.01

_TARGET_INCOMPLETE_REASONS = frozenset(
    {"target_identity_unobserved", "target_observation_unreadable", "active_stamp_unobserved"}
)
# Category -> observed path. Every target-bound observation must be reported before it is compared.
_IDENTITY_PATHS: dict[str, tuple[str, ...]] = {
    "volumes": ("storage", "volume_ids"),
    "networks": ("storage", "network_ids"),
    "compose_projects": ("storage", "compose_project"),
    "database_names": ("database", "identity", "database_name"),
    "database_roles": ("database", "identity", "role"),
    "blob_namespaces": ("storage", "blob_namespace"),
}
_STORE_EVIDENCE_PATHS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("database", "store_state"), "fir_store_state_unobserved"),
    (("database", "embedding_provenance"), "embedding_provenance_unobserved"),
    (("database", "vector_column_inventory"), "vector_inventory_incomplete"),
)
_MISSING: Any = object()


def target_identities(label: str) -> dict[str, str]:
    """Proposed identities for ``acx-<label>`` under the Aura naming rules. Label must be an Aura label."""

    underscored = label.replace("-", "_")
    return {
        "compose_project": f"acx-{label}",
        "network": f"acx-{label}-net",
        "database_name": f"alt_context_{underscored}",
        "role": f"acx_{underscored}",
        "pgdata": f"/opt/acx-backend/data/{label}-pgdata",
        "blob_volume": f"acx-{label}_acx_blobs",
        "blob_namespace": f"acx-{label}",
    }


def required_target_identities(label: str) -> dict[str, frozenset[str]]:
    """The known resource contract for one label, keyed by the six isolation categories."""

    identity = target_identities(label)
    return {
        "volumes": frozenset({identity["pgdata"], identity["blob_volume"]}),
        "networks": frozenset({identity["network"]}),
        "compose_projects": frozenset({identity["compose_project"]}),
        "database_names": frozenset({identity["database_name"]}),
        "database_roles": frozenset({identity["role"]}),
        "blob_namespaces": frozenset({identity["blob_namespace"]}),
    }


def _at(value: Any, *keys: str) -> Any:
    """Read a key path, returning ``_MISSING`` for any absent key or non-mapping step."""

    current = value
    for key in keys:
        if not isinstance(current, Mapping) or key not in current:
            return _MISSING
        current = current[key]
    return current


def _has_wrapper(snapshot: Mapping[str, Any], path: tuple[str, ...]) -> bool:
    wrapper = _at(snapshot, *path)
    return isinstance(wrapper, Mapping) and "value" in wrapper and "provenance" in wrapper


def missing_evidence_reason(snapshot: Any) -> str | None:
    """Return an incomplete reason when a target or store observation is absent, else ``None``.

    A wrapper missing ``value`` or ``provenance`` is missing reported evidence. The facade calls this
    before the shared closed guard, so the specific incomplete code wins over the shared
    ``malformed_observation_wrapper`` invalid status.
    """

    if not isinstance(snapshot, Mapping):
        return None
    for path in _IDENTITY_PATHS.values():
        if not _has_wrapper(snapshot, path):
            return "target_identity_unobserved"
    for path, reason in _STORE_EVIDENCE_PATHS:
        if not _has_wrapper(snapshot, path):
            return reason
    return None


def _status_for(reason: str) -> str:
    if reason in _INCOMPLETE_REASON_CODES or reason in _TARGET_INCOMPLETE_REASONS:
        return "incomplete"
    return "invalid"


def _is_distinct_name_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item.strip() for item in value)
        and len(set(value)) == len(value)
    )


def _target_label(acceptance_policy: Any) -> str | tuple[str, str]:
    if not isinstance(acceptance_policy, Mapping):
        return ("invalid", "malformed_acceptance_policy")
    label = acceptance_policy.get("target_label")
    if not isinstance(label, str):
        return ("invalid", "malformed_acceptance_policy")
    if label not in AURA_LABELS:
        return ("invalid", "unknown_target_label")
    return label


def _target_policy_outcome(isolation_policy: Any, label: str) -> tuple[str, str] | None:
    if not isinstance(isolation_policy, Mapping):
        return ("invalid", "malformed_isolation_policy")
    policy = isolation_policy.get("required_target_resource_ids")
    if not isinstance(policy, Mapping) or set(policy) != set(TARGET_CATEGORIES):
        return ("invalid", "malformed_target_policy")
    if any(not _is_distinct_name_list(policy[category]) for category in TARGET_CATEGORIES):
        return ("invalid", "malformed_target_policy")
    for category, required in required_target_identities(label).items():
        if frozenset(policy[category]) != required:
            return ("invalid", "target_identity_mismatch")
    return None


def _observed_names(value: Any) -> frozenset[str] | None:
    if isinstance(value, str):
        return frozenset({value}) if value.strip() else None
    if isinstance(value, list) and value and all(isinstance(item, str) and item.strip() for item in value):
        return frozenset(value)
    return None


def _identity_outcome(snapshot: Mapping[str, Any], label: str) -> tuple[str, str] | None:
    observed: dict[str, frozenset[str]] = {}
    missing = False
    for category, path in _IDENTITY_PATHS.items():
        names = _observed_names(_at(snapshot, *path, "value"))
        if names is None:
            missing = True
            continue
        observed[category] = names
    for category, required in required_target_identities(label).items():
        if category in observed and observed[category] != required:
            return ("invalid", "target_identity_mismatch")
    return ("incomplete", "target_identity_unobserved") if missing else None


def _persisted_model_ids(summary: Mapping[str, Any]) -> list[str] | None:
    ids = summary.get("persisted_model_ids")
    if not isinstance(ids, list) or not all(isinstance(item, str) and item.strip() for item in ids):
        return None
    if summary.get("persisted_model_ids_complete") is not True:
        return None
    return ids


def _is_aura_stamp(model_id: str) -> bool:
    if any(marker in model_id for marker in _UNRESOLVED_MODEL_MARKERS):
        return False
    parsed = _parse_model_id(model_id)
    if parsed is None:
        return False
    name, suffix = parsed
    return name.startswith(AURA_MODEL_PREFIX) and suffix == AURA_MODEL_SUFFIX


def _active_stamp(snapshot: Mapping[str, Any]) -> str | tuple[str, str]:
    """Derive the active stamp from the API and worker model-loading roles."""

    observations = _at(snapshot, "observations")
    if not isinstance(observations, list) or not observations:
        return ("incomplete", "active_stamp_unobserved")
    stamps: list[str] = []
    missing = False
    for record in observations:
        if isinstance(record, Mapping) and record.get("role") == "fix-blob-ownership":
            continue
        model_id = _at(record, "model_id", "value")
        if not isinstance(model_id, str) or not model_id.strip():
            missing = True
            continue
        stamps.append(model_id)
    if any(stamp != stamps[0] for stamp in stamps[1:]):
        return ("invalid", "model_contract_mismatch")
    if any(not _is_aura_stamp(stamp) for stamp in stamps):
        return ("invalid", "model_space_contract_mismatch")
    if missing or not stamps:
        return ("incomplete", "active_stamp_unobserved")
    return stamps[0]


def _representative_is_unit(vector: Any) -> bool:
    """Production identity rule: the persisted representative must be unit length within tolerance."""

    total = math.fsum(float(component) * float(component) for component in vector)
    return abs(math.sqrt(total) - 1.0) < NORM_TOLERANCE


def _store_outcome(snapshot: Mapping[str, Any], stamp: str) -> tuple[str, str] | None:
    """Inventory, width, and store-state rungs reused from the FIR guard, then the Aura census."""

    findings: list[tuple[str, str]] = []
    inventory_reason = _vector_inventory_is_incomplete(snapshot)
    if inventory_reason is not None:
        findings.append((_status_for(inventory_reason), inventory_reason))
    inventory = _at(snapshot, "database", "vector_column_inventory", "value")
    if isinstance(inventory, (list, tuple)):
        for item in inventory:
            if isinstance(item, Mapping) and item.get("dimension") is not None:
                if item["dimension"] != AURA_EMBEDDING_DIMENSION:
                    findings.append(("invalid", "database_dimension_mismatch"))
    store_reason = _validate_store_state(snapshot, "candidate512")
    if store_reason is not None:
        findings.append((_status_for(store_reason), store_reason))

    summary = _at(snapshot, "database", "embedding_provenance", "value")
    if isinstance(summary, Mapping):
        counts = summary.get("row_counts")
        if isinstance(counts, Mapping) and any(
            identity not in EXPECTED_VECTOR_COLUMNS and count != 0 for identity, count in counts.items()
        ):
            findings.append(("incomplete", "fir_store_state_unobserved"))
        state = _at(snapshot, "database", "store_state", "value")
        persisted = summary.get("persisted_model_ids")
        if _persisted_model_ids(summary) is None:
            findings.append(("incomplete", "embedding_provenance_unobserved"))
        # Even an unfinished census can contradict the active stamp with a present ID.
        if isinstance(persisted, list) and all(isinstance(item, str) and item.strip() for item in persisted):
            if len(set(persisted)) != len(persisted):
                findings.append(("invalid", "persisted_model_ids_not_distinct"))
            elif state == "empty" and persisted:
                findings.append(("invalid", "persisted_model_stamp_mismatch"))
            elif state == "enrolled":
                if len(persisted) > 1:
                    findings.append(("invalid", "mixed_persisted_models"))
                elif any(model_id != stamp for model_id in persisted) or (
                    _persisted_model_ids(summary) is not None and not persisted
                ):
                    findings.append(("invalid", "persisted_model_stamp_mismatch"))
        vector = summary.get("representative_vector")
        if state == "enrolled" and _is_finite_vector(vector, AURA_EMBEDDING_DIMENSION):
            if not _representative_is_unit(vector):
                findings.append(("invalid", "non_normalized_persisted_vector"))
    for status in ("invalid", "incomplete"):
        for finding in findings:
            if finding[0] == status:
                return finding
    return None


def validate_target_store(
    snapshot: Mapping[str, Any],
    *,
    isolation_policy: Mapping[str, Any],
    acceptance_policy: Mapping[str, Any],
) -> tuple[str, str] | None:
    """Check the target and store rungs owned by one Aura label; ``None`` means they are complete and consistent."""

    label = _target_label(acceptance_policy)
    if not isinstance(label, str):
        return label
    policy_outcome = _target_policy_outcome(isolation_policy, label)
    if policy_outcome is not None:
        return policy_outcome
    findings: list[tuple[str, str]] = []
    missing = missing_evidence_reason(snapshot)
    if missing is not None:
        findings.append(("incomplete", missing))
    summary = _at(snapshot, "database", "embedding_provenance", "value")
    if not isinstance(summary, Mapping) or _persisted_model_ids(summary) is None:
        findings.append(("incomplete", "embedding_provenance_unobserved"))
    identity_outcome = _identity_outcome(snapshot, label)
    if identity_outcome is not None:
        findings.append(identity_outcome)
    stamp = _active_stamp(snapshot)
    if isinstance(stamp, tuple):
        findings.append(stamp)
    elif missing is None:
        store_outcome = _store_outcome(snapshot, stamp)
        if store_outcome is not None:
            findings.append(store_outcome)
    for status in ("invalid", "incomplete"):
        for finding in findings:
            if finding[0] == status:
                return finding
    return None
