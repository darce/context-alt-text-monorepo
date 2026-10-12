"""Loaded-runtime rung for the AuraFace acceptance gate (offline evidence only).

``validate_loaded_runtime`` decides whether the recorded loaded-runtime evidence is
complete and consistent. The AuraFace entrypoint (``scripts.validate_auraface_runtime``)
owns ordering against the shared closed v1 guard in ``scripts.validate_fir_dev_runtime``.

Return contract
---------------
``None``              Every rung in this helper is complete and consistent.
``(status, reason)``  ``status`` is ``"invalid"`` for a contradiction (a pin, a peer role,
                      or the snapshot binding) and ``"incomplete"`` for a reported
                      observation that is absent or lacks its authoritative provenance.
                      ``reason`` is a stable code. Raw snapshot or policy values are
                      never echoed.

Expected values come only from ``MODEL_MANIFEST`` and the approved acceptance policy.
Observed values come only from the snapshot and the Aura evidence sidecar. A missing
observation is never filled from an expected value. Inside this helper a proven
contradiction outranks missing evidence, so it is never reported merely as incomplete.

Rungs, in evaluation order
--------------------------
1. Acceptance policy shape. A malformed policy is invalid, not evidence.
2. Snapshot role shape: closed role names, no duplicates.
3. Sidecar: ``schema_version`` 1, closed top-level keys, ``snapshot_sha256`` binding to the
   canonical JSON SHA-256 of the snapshot, and EXACT runtime roles ``EVIDENCE_ROLES``.
4. Loaded license digests (YuNet, AuraFace) on ``EVIDENCE_ROLES`` against ``MODEL_MANIFEST``.
5. Numeric preprocessing contract on ``EVIDENCE_ROLES`` against ``MODEL_MANIFEST``, all seven
   fields.
6. Loaded weight digests on ``EVIDENCE_ROLES`` in the snapshot against ``MODEL_MANIFEST``.
7. Source git SHA on every snapshot role, and sidecar source tree on ``EVIDENCE_ROLES``,
   against the approved source policy.
8. Sidecar database identity on ``EVIDENCE_ROLES`` against the snapshot catalog identity.

Across roles, divergence is checked before the pin, so a divergent role is reported as
divergence and not as a pin mismatch.

Scope
-----
``fix-blob-ownership`` is a snapshot role. Its source git SHA is checked (rung 7), but it
never requires loaded-model, license, or preprocessing sidecar evidence and is not in
``EVIDENCE_ROLES``. The helper is offline. It has no I/O, network, DB, GPU, or model load,
and it does not prove that a model executed.

Canon: PROV-01 (every output walks back to its evidence), EMB-01 (one embedding space per
comparison), TEST-15 (the frozen tests must catch a deliberately broken rung).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from typing import Any, Final

from recognition.infrastructure.face_pipeline.provenance import MODEL_MANIFEST
from scripts.validate_fir_dev_runtime import ROLE_NAMES

__all__ = [
    "AURA_EVIDENCE_SCHEMA_VERSION",
    "EVIDENCE_ROLES",
    "LOADED_RUNTIME_INCOMPLETE_REASONS",
    "LOADED_RUNTIME_INVALID_REASONS",
    "validate_loaded_runtime",
]

AURA_EVIDENCE_SCHEMA_VERSION: Final = 1
# Exact sidecar role set. fix-blob-ownership loads no model and is never evidence-bearing here.
EVIDENCE_ROLES: Final[tuple[str, ...]] = ("api", "worker")

# Model names are the MODEL_MANIFEST keys that the AuraFace runtime loads.
_MODEL_NAMES: Final[tuple[str, ...]] = ("yunet", "auraface")
_EVIDENCE_TOP_LEVEL_KEYS: Final = frozenset({"schema_version", "snapshot_sha256", "runtime_roles"})
_EVIDENCE_ROLE_SECTIONS: Final = frozenset(
    {"loaded_license_hashes", "preprocessing_contract", "source_tree", "database_identity"}
)
_DATABASE_IDENTITY_FIELDS: Final[tuple[str, ...]] = ("database_name", "role")
_NUMERIC_REL_TOL: Final = 1e-9
_SHA256_DIGEST: Final = re.compile(r"sha256:[0-9a-f]{64}")
_GIT_OBJECT_ID: Final = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")

LOADED_RUNTIME_INVALID_REASONS: Final = frozenset(
    {
        "malformed_acceptance_policy",
        "snapshot_schema_invalid",
        "unknown_role_observation",
        "duplicate_role_observation",
        "malformed_observation_wrapper",
        "malformed_loaded_weight_hash",
        "aura_evidence_schema_invalid",
        "unsupported_aura_evidence_schema",
        "evidence_snapshot_mismatch",
        "license_hash_mismatch",
        "role_license_hash_mismatch",
        "preprocessing_contract_mismatch",
        "role_loaded_weight_hash_mismatch",
        "model_asset_hash_unexpected",
        "role_source_identity_mismatch",
        "source_identity_unapproved",
        "database_identity_divergent",
    }
)
LOADED_RUNTIME_INCOMPLETE_REASONS: Final = frozenset(
    {
        "incomplete_role_observation",
        "incomplete_loaded_weight_hashes",
        "missing_loaded_weight_hashes",
        "incomplete_source_identity",
        "incomplete_snapshot_binding",
        "incomplete_runtime_role_evidence",
        "incomplete_license_evidence",
        "incomplete_preprocessing_evidence",
        "incomplete_database_identity",
        "observation_provenance_declared",
    }
)

_INVALID: Final = "invalid"
_INCOMPLETE: Final = "incomplete"
# Sentinel for a field that is missing or not authoritative. Its value must never be used.
_ABSENT: Final = object()


class _Findings:
    """Collect every rung finding. A contradiction outranks missing evidence."""

    def __init__(self) -> None:
        self._invalid: list[str] = []
        self._incomplete: list[str] = []

    def invalid(self, reason: str) -> None:
        self._invalid.append(reason)

    def incomplete(self, reason: str) -> None:
        self._incomplete.append(reason)

    def verdict(self) -> tuple[str, str] | None:
        if self._invalid:
            return _INVALID, self._invalid[0]
        if self._incomplete:
            return _INCOMPLETE, self._incomplete[0]
        return None


def _model_pin_digest(name: str) -> str:
    return f"sha256:{MODEL_MANIFEST[name].sha256}"


def _model_license_pin(name: str) -> str:
    return f"sha256:{MODEL_MANIFEST[name].license_sha256}"


def _expected_preprocessing() -> dict[str, Any]:
    """Expected AuraFace numeric contract, read from MODEL_MANIFEST and never from evidence."""

    entry = MODEL_MANIFEST["auraface"]
    preprocessing = entry.preprocessing
    if preprocessing is None or entry.normalization is None:
        raise RuntimeError("MODEL_MANIFEST auraface preprocessing authority is not pinned")
    return {
        "input_size": list(preprocessing.input_size),
        "channel_order": preprocessing.channel_order,
        "input_mean": preprocessing.input_mean,
        "input_scale": preprocessing.input_scale,
        "alignment_template_id": preprocessing.alignment_template_id,
        "output_l2_normalized": preprocessing.output_l2_normalized,
        "pipeline_normalization": entry.normalization,
    }


def _acceptance_pins(acceptance_policy: Any) -> tuple[str, str] | None:
    if not isinstance(acceptance_policy, Mapping):
        return None
    target = acceptance_policy.get("target_label")
    git_sha = acceptance_policy.get("approved_source_git_sha")
    tree = acceptance_policy.get("approved_source_tree")
    if not isinstance(target, str) or not target.strip():
        return None
    if not isinstance(git_sha, str) or _GIT_OBJECT_ID.fullmatch(git_sha) is None:
        return None
    if not isinstance(tree, str) or _GIT_OBJECT_ID.fullmatch(tree) is None:
        return None
    return git_sha, tree


def _snapshot_digest(snapshot: Mapping[str, Any]) -> str | None:
    try:
        canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError):
        return None
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _snapshot_roles(snapshot: Any) -> dict[str, Mapping[str, Any]] | tuple[str, str]:
    """Return the snapshot records keyed by role, or the refusal for an unreadable shape."""

    if not isinstance(snapshot, Mapping):
        return _INVALID, "snapshot_schema_invalid"
    observations = snapshot.get("observations")
    if not isinstance(observations, list):
        return _INVALID, "snapshot_schema_invalid"
    by_role: dict[str, Mapping[str, Any]] = {}
    for record in observations:
        if not isinstance(record, Mapping) or not isinstance(record.get("role"), str):
            return _INVALID, "snapshot_schema_invalid"
        role = record["role"]
        if role not in ROLE_NAMES:
            return _INVALID, "unknown_role_observation"
        if role in by_role:
            return _INVALID, "duplicate_role_observation"
        by_role[role] = record
    return by_role


def _check_binding(aura_evidence: Mapping[str, Any], snapshot_digest: str, findings: _Findings) -> None:
    observed = aura_evidence.get("snapshot_sha256")
    if observed is None:
        findings.incomplete("incomplete_snapshot_binding")
    elif not isinstance(observed, str) or _SHA256_DIGEST.fullmatch(observed) is None:
        findings.invalid("aura_evidence_schema_invalid")
    elif observed != snapshot_digest:
        findings.invalid("evidence_snapshot_mismatch")


def _evidence_roles(aura_evidence: Mapping[str, Any], findings: _Findings) -> dict[str, Mapping[str, Any]]:
    """Return the well-formed evidence record for each required role, enforcing the EXACT role set."""

    runtime_roles = aura_evidence.get("runtime_roles")
    if runtime_roles is None:
        findings.incomplete("incomplete_runtime_role_evidence")
        return {}
    if not isinstance(runtime_roles, Mapping):
        findings.invalid("aura_evidence_schema_invalid")
        return {}
    if set(runtime_roles) - set(EVIDENCE_ROLES):
        findings.invalid("aura_evidence_schema_invalid")
    roles: dict[str, Mapping[str, Any]] = {}
    for role in EVIDENCE_ROLES:
        record = runtime_roles.get(role)
        if record is None:
            findings.incomplete("incomplete_runtime_role_evidence")
        elif not isinstance(record, Mapping) or set(record) - _EVIDENCE_ROLE_SECTIONS:
            findings.invalid("aura_evidence_schema_invalid")
        else:
            roles[role] = record
    return roles


def _snapshot_observation(
    record: Mapping[str, Any] | None,
    field: str,
    provenance: str,
    *,
    missing: str,
    findings: _Findings,
) -> Any:
    """Return an authoritative snapshot value, or ``_ABSENT`` after recording why it is not usable."""

    if record is None:
        findings.incomplete("incomplete_role_observation")
        return _ABSENT
    wrapper = record.get(field)
    if wrapper is None:
        findings.incomplete(missing)
        return _ABSENT
    if not isinstance(wrapper, Mapping):
        findings.invalid("malformed_observation_wrapper")
        return _ABSENT
    value = wrapper.get("value")
    if value is None:
        findings.incomplete(missing)
        return _ABSENT
    if wrapper.get("provenance") != provenance:
        findings.incomplete("observation_provenance_declared")
        return _ABSENT
    return value


def _sidecar_observation(
    role_record: Mapping[str, Any],
    section: str,
    provenance: str,
    *,
    missing: str,
    findings: _Findings,
) -> Any:
    """Return an authoritative sidecar value, or ``_ABSENT`` after recording why it is not usable."""

    wrapper = role_record.get(section)
    if wrapper is None:
        findings.incomplete(missing)
        return _ABSENT
    if not isinstance(wrapper, Mapping) or set(wrapper) - {"value", "provenance"}:
        findings.invalid("aura_evidence_schema_invalid")
        return _ABSENT
    value = wrapper.get("value")
    if value is None:
        findings.incomplete(missing)
        return _ABSENT
    if wrapper.get("provenance") != provenance:
        findings.incomplete("observation_provenance_declared")
        return _ABSENT
    return value


def _report_divergence(
    observed: Mapping[str, Mapping[str, Any]],
    names: Iterable[str],
    reason: str,
    findings: _Findings,
) -> None:
    """Flag any name whose observed value differs between complete roles."""

    for name in names:
        if len({value[name] for value in observed.values()}) > 1:
            findings.invalid(reason)


def _same_real(observed: Any, expected: float) -> bool:
    if isinstance(observed, bool) or not isinstance(observed, (int, float)):
        return False
    try:
        value = float(observed)
    except OverflowError:
        return False
    return math.isfinite(value) and math.isclose(value, expected, rel_tol=_NUMERIC_REL_TOL, abs_tol=0.0)


def _preprocessing_field_matches(observed: Any, expected: Any) -> bool:
    if isinstance(expected, bool):
        return observed is expected
    if isinstance(expected, str):
        return isinstance(observed, str) and observed == expected
    if isinstance(expected, list):
        return (
            isinstance(observed, (list, tuple))
            and len(observed) == len(expected)
            and all(
                isinstance(item, int) and not isinstance(item, bool) and item == want
                for item, want in zip(observed, expected, strict=True)
            )
        )
    return _same_real(observed, float(expected))


def _check_loaded_weights(by_role: Mapping[str, Mapping[str, Any]], findings: _Findings) -> None:
    """Weights are checked on model-loading roles only. Missing or partial sets are incomplete."""

    observed: dict[str, Mapping[str, Any]] = {}
    for role in EVIDENCE_ROLES:
        value = _snapshot_observation(
            by_role.get(role),
            "loaded_weight_hashes",
            "runtime_loaded_artifact",
            missing="incomplete_loaded_weight_hashes",
            findings=findings,
        )
        if value is _ABSENT:
            continue
        if not isinstance(value, Mapping):
            findings.incomplete("incomplete_loaded_weight_hashes")
            continue
        if not value:
            findings.incomplete("missing_loaded_weight_hashes")
            continue
        if set(value) != set(_MODEL_NAMES):
            findings.incomplete("incomplete_loaded_weight_hashes")
            continue
        if any(not isinstance(digest, str) or _SHA256_DIGEST.fullmatch(digest) is None for digest in value.values()):
            findings.invalid("malformed_loaded_weight_hash")
            continue
        observed[role] = value
    _report_divergence(observed, _MODEL_NAMES, "role_loaded_weight_hash_mismatch", findings)
    for value in observed.values():
        for name in _MODEL_NAMES:
            if value[name] != _model_pin_digest(name):
                findings.invalid("model_asset_hash_unexpected")


def _check_licenses(roles: Mapping[str, Mapping[str, Any]], findings: _Findings) -> None:
    observed: dict[str, Mapping[str, Any]] = {}
    for role in EVIDENCE_ROLES:
        if role not in roles:
            continue
        value = _sidecar_observation(
            roles[role],
            "loaded_license_hashes",
            "runtime_loaded_artifact",
            missing="incomplete_license_evidence",
            findings=findings,
        )
        if value is _ABSENT:
            continue
        if not isinstance(value, Mapping) or set(value) - set(_MODEL_NAMES):
            findings.invalid("aura_evidence_schema_invalid")
            continue
        if any(value.get(name) is None for name in _MODEL_NAMES):
            findings.incomplete("incomplete_license_evidence")
            continue
        if any(not isinstance(value[name], str) for name in _MODEL_NAMES):
            findings.invalid("aura_evidence_schema_invalid")
            continue
        observed[role] = value
    _report_divergence(observed, _MODEL_NAMES, "role_license_hash_mismatch", findings)
    for value in observed.values():
        for name in _MODEL_NAMES:
            if value[name] != _model_license_pin(name):
                findings.invalid("license_hash_mismatch")


def _check_preprocessing(roles: Mapping[str, Mapping[str, Any]], findings: _Findings) -> None:
    expected = _expected_preprocessing()
    for role in EVIDENCE_ROLES:
        if role not in roles:
            continue
        value = _sidecar_observation(
            roles[role],
            "preprocessing_contract",
            "runtime_probe",
            missing="incomplete_preprocessing_evidence",
            findings=findings,
        )
        if value is _ABSENT:
            continue
        if not isinstance(value, Mapping) or set(value) - set(expected):
            findings.invalid("aura_evidence_schema_invalid")
            continue
        if any(value.get(field) is None for field in expected):
            findings.incomplete("incomplete_preprocessing_evidence")
            continue
        for field, want in expected.items():
            if not _preprocessing_field_matches(value[field], want):
                findings.invalid("preprocessing_contract_mismatch")


def _check_identity_agreement(
    values: Iterable[str],
    approved: str,
    divergence_reason: str,
    unapproved_reason: str,
    findings: _Findings,
) -> None:
    distinct = set(values)
    if len(distinct) > 1:
        findings.invalid(divergence_reason)
    elif distinct and approved not in distinct:
        findings.invalid(unapproved_reason)


def _check_source_identity(
    by_role: Mapping[str, Mapping[str, Any]],
    approved_git_sha: str,
    findings: _Findings,
) -> None:
    """Every snapshot role, including fix-blob-ownership, must carry the approved source SHA."""

    values: list[str] = []
    for role in ROLE_NAMES:
        value = _snapshot_observation(
            by_role.get(role),
            "source_git_sha",
            "binary_identity",
            missing="incomplete_source_identity",
            findings=findings,
        )
        if value is _ABSENT:
            continue
        if not isinstance(value, str):
            findings.invalid("malformed_observation_wrapper")
        elif not value.strip():
            findings.incomplete("incomplete_source_identity")
        else:
            values.append(value)
    _check_identity_agreement(
        values,
        approved_git_sha,
        "role_source_identity_mismatch",
        "source_identity_unapproved",
        findings,
    )


def _check_sidecar_source_tree(
    roles: Mapping[str, Mapping[str, Any]],
    approved_tree: str,
    findings: _Findings,
) -> None:
    values: list[str] = []
    for role in EVIDENCE_ROLES:
        if role not in roles:
            continue
        value = _sidecar_observation(
            roles[role],
            "source_tree",
            "binary_identity",
            missing="incomplete_source_identity",
            findings=findings,
        )
        if value is _ABSENT:
            continue
        if not isinstance(value, str):
            findings.invalid("aura_evidence_schema_invalid")
        elif not value.strip():
            findings.incomplete("incomplete_source_identity")
        else:
            values.append(value)
    _check_identity_agreement(
        values,
        approved_tree,
        "role_source_identity_mismatch",
        "source_identity_unapproved",
        findings,
    )


def _snapshot_database_identity(snapshot: Mapping[str, Any], findings: _Findings) -> dict[str, str] | None:
    """Return the catalog database identity from the snapshot, or None after recording why it is absent."""

    database = snapshot.get("database")
    if database is None:
        findings.incomplete("incomplete_database_identity")
        return None
    if not isinstance(database, Mapping):
        findings.invalid("snapshot_schema_invalid")
        return None
    identity = database.get("identity")
    if identity is None:
        findings.incomplete("incomplete_database_identity")
        return None
    if not isinstance(identity, Mapping):
        findings.invalid("snapshot_schema_invalid")
        return None
    actual: dict[str, str] = {}
    for field in _DATABASE_IDENTITY_FIELDS:
        wrapper = identity.get(field)
        if wrapper is None:
            findings.incomplete("incomplete_database_identity")
            return None
        if not isinstance(wrapper, Mapping):
            findings.invalid("malformed_observation_wrapper")
            return None
        value = wrapper.get("value")
        if not isinstance(value, str) or not value.strip():
            findings.incomplete("incomplete_database_identity")
            return None
        if wrapper.get("provenance") != "database_catalog":
            findings.incomplete("observation_provenance_declared")
            return None
        actual[field] = value
    return actual


def _check_database_identity(
    snapshot: Mapping[str, Any],
    roles: Mapping[str, Mapping[str, Any]],
    findings: _Findings,
) -> None:
    actual = _snapshot_database_identity(snapshot, findings)
    if actual is None:
        return
    for role in EVIDENCE_ROLES:
        if role not in roles:
            continue
        value = _sidecar_observation(
            roles[role],
            "database_identity",
            "database_catalog",
            missing="incomplete_database_identity",
            findings=findings,
        )
        if value is _ABSENT:
            continue
        if not isinstance(value, Mapping) or set(value) - set(_DATABASE_IDENTITY_FIELDS):
            findings.invalid("aura_evidence_schema_invalid")
            continue
        if any(value.get(field) is None for field in _DATABASE_IDENTITY_FIELDS):
            findings.incomplete("incomplete_database_identity")
            continue
        if any(value[field] != actual[field] for field in _DATABASE_IDENTITY_FIELDS):
            findings.invalid("database_identity_divergent")


def validate_loaded_runtime(
    snapshot: Any,
    *,
    aura_evidence: Any,
    acceptance_policy: Any,
) -> tuple[str, str] | None:
    """Check the loaded-runtime evidence for one AuraFace acceptance candidate.

    Returns ``None`` when every rung in this helper is complete and consistent. Otherwise
    returns ``("invalid", reason)`` for a contradiction or ``("incomplete", reason)`` for a
    missing or non-authoritative observation. Pure: it does not mutate its inputs, perform
    I/O, or print the snapshot or policy.

    The three inputs are untrusted JSON-shaped values, so they are typed ``Any``. Every
    structure is checked at runtime before it is read.
    """

    pins = _acceptance_pins(acceptance_policy)
    if pins is None:
        return _INVALID, "malformed_acceptance_policy"
    by_role = _snapshot_roles(snapshot)
    if isinstance(by_role, tuple):
        return by_role
    snapshot_digest = _snapshot_digest(snapshot)
    if snapshot_digest is None:
        return _INVALID, "snapshot_schema_invalid"
    if not isinstance(aura_evidence, Mapping):
        return _INVALID, "aura_evidence_schema_invalid"
    version = aura_evidence.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        return _INVALID, "aura_evidence_schema_invalid"
    if version != AURA_EVIDENCE_SCHEMA_VERSION:
        return _INVALID, "unsupported_aura_evidence_schema"

    approved_git_sha, approved_tree = pins
    findings = _Findings()
    if set(aura_evidence) - _EVIDENCE_TOP_LEVEL_KEYS:
        findings.invalid("aura_evidence_schema_invalid")
    _check_binding(aura_evidence, snapshot_digest, findings)
    roles = _evidence_roles(aura_evidence, findings)

    _check_licenses(roles, findings)
    _check_preprocessing(roles, findings)
    _check_loaded_weights(by_role, findings)
    _check_source_identity(by_role, approved_git_sha, findings)
    _check_sidecar_source_tree(roles, approved_tree, findings)
    _check_database_identity(snapshot, roles, findings)
    return findings.verdict()
