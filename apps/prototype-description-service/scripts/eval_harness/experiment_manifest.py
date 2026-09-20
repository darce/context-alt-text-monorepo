"""Immutable provenance document for one face-evaluation experiment run.

"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from scripts.bench.stack_pair import validate_stack_pair_config
from scripts.eval_harness.face_run_record import validate_face_run_record
from scripts.eval_harness.manifest import (
    _SHA256_RE,
    LEGACY_MANIFEST_VERSION,
    SUPPORTED_MANIFEST_VERSION,
    AnnotationMode,
    GoldenManifest,
)
from scripts.eval_harness.provenance_sha import _HEX40, normalize_head_sha


class ExperimentManifestError(ValueError):
    """The experiment manifest does not satisfy its immutable-run contract."""


def _validate_corpus_manifest(corpus_manifest: dict[str, Any]) -> GoldenManifest:
    """Validate a parsed corpus through the shared v3/legacy manifest model."""
    if not isinstance(corpus_manifest, dict):
        raise ExperimentManifestError("corpus_manifest must be a parsed mapping")

    try:
        return GoldenManifest.model_validate(corpus_manifest)
    except ValidationError as exc:
        if corpus_manifest.get("manifest_version") != LEGACY_MANIFEST_VERSION:
            raise ExperimentManifestError(str(exc)) from exc

        legacy_payload = dict(corpus_manifest)
        if legacy_payload.get("annotation_mode") is None:
            legacy_payload["annotation_mode"] = AnnotationMode.ROSTER_ONLY
        try:
            return GoldenManifest.model_validate(legacy_payload, context={"legacy": True})
        except ValidationError as legacy_exc:
            raise ExperimentManifestError(str(legacy_exc)) from legacy_exc


def _normalize_head_sha(head_sha: str | None) -> str:
    """Apply the shared normalizer once, then enforce its returned shape."""
    normalized = normalize_head_sha(head_sha)
    if normalized is None or not isinstance(normalized, str) or _HEX40.fullmatch(normalized) is None:
        raise ExperimentManifestError("head_sha must be a normalized 40-character hexadecimal SHA")
    return normalized


def _stack_pair_policy(stack_pair: Any) -> dict[str, Any]:
    """Validate and project only the immutable policy fields into provenance."""
    try:
        pair = validate_stack_pair_config(stack_pair)
    except Exception as exc:
        raise ExperimentManifestError(f"invalid stack pair configuration: {exc}") from exc
    return {
        "primary_endpoint": pair.primary_endpoint,
        "secondary_endpoints": list(pair.secondary_endpoints),
        "head_to_head_delta": pair.head_to_head_delta,
        "accepted_set_floor": pair.accepted_set_floor,
        "max_differential_attrition": pair.max_differential_attrition,
        "bootstrap_seed": pair.bootstrap_seed,
        "item_max_attempts": pair.item_max_attempts,
        "manifest_sha256": pair.manifest_sha256,
    }


def build_experiment_manifest(
    *,
    run_id: Any,
    created_at: Any,
    head_sha: str | None,
    corpus_manifest: dict[str, Any],
    corpus_manifest_sha256: str,
    stack_pair: Any,
    face_run_record: dict[str, Any],
    aborted: bool,
) -> dict[str, Any]:
    """Build an immutable run-provenance document from existing validated seams."""
    try:
        corpus_hash_matches = _SHA256_RE.fullmatch(corpus_manifest_sha256)
    except TypeError:
        corpus_hash_matches = None
    if corpus_hash_matches is None:
        raise ExperimentManifestError(
            "corpus_manifest_sha256 has invalid shape; expected 64 lowercase hexadecimal characters"
        )
    if run_id is None:
        raise ExperimentManifestError("run_id is required and must remain stable")
    if created_at is None:
        raise ExperimentManifestError("created_at is required and must remain stable")

    normalized_head_sha = _normalize_head_sha(head_sha)
    corpus = _validate_corpus_manifest(corpus_manifest)
    policy = _stack_pair_policy(stack_pair)
    pinned_sha = policy["manifest_sha256"]
    if pinned_sha is None:
        raise ExperimentManifestError(
            "stack pair is unpinned: manifest_sha256 must pin the corpus manifest"
        )
    if pinned_sha != corpus_manifest_sha256:
        raise ExperimentManifestError(
            "corpus manifest sha256 pin mismatch with the stack pair manifest_sha256 pin"
        )

    validated_face_run_record = validate_face_run_record(face_run_record)
    document = {
        "identity": {
            "run_id": run_id,
            "created_at": created_at,
            "head_sha": normalized_head_sha,
        },
        "inputs": {
            "corpus_manifest_sha256": corpus_manifest_sha256,
            "corpus_manifest_version": corpus.manifest_version,
        },
        "policy": {"stack_pair": policy},
        "execution": {"status": "aborted" if aborted else "completed"},
        "output": {"face_run_record": validated_face_run_record},
    }
    return validate_experiment_manifest(document)


def validate_experiment_manifest(document: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    """Re-check the persisted run-provenance contract without rebuilding it."""
    if not isinstance(document, dict):
        raise ExperimentManifestError("experiment manifest must be a mapping")

    identity = document.get("identity")
    if not isinstance(identity, dict):
        raise ExperimentManifestError("experiment manifest identity is required")
    if not identity.get("run_id"):
        raise ExperimentManifestError("experiment manifest identity.run_id is required")
    if not identity.get("created_at"):
        raise ExperimentManifestError("experiment manifest identity.created_at is required")
    persisted_head_sha = identity.get("head_sha")
    if not isinstance(persisted_head_sha, str) or _HEX40.fullmatch(persisted_head_sha) is None:
        raise ExperimentManifestError(
            "experiment manifest identity.head_sha must be a 40-character hexadecimal SHA"
        )

    inputs = document.get("inputs")
    if not isinstance(inputs, dict):
        raise ExperimentManifestError("experiment manifest inputs are required")
    persisted_corpus_sha = inputs.get("corpus_manifest_sha256")
    if not isinstance(persisted_corpus_sha, str) or _SHA256_RE.fullmatch(persisted_corpus_sha) is None:
        raise ExperimentManifestError(
            "experiment manifest inputs.corpus_manifest_sha256 has invalid shape; expected 64 lowercase hexadecimal characters"
        )

    policy_root = document.get("policy")
    stack_policy = policy_root.get("stack_pair") if isinstance(policy_root, dict) else None
    expected_policy_keys = {
        "primary_endpoint",
        "secondary_endpoints",
        "head_to_head_delta",
        "accepted_set_floor",
        "max_differential_attrition",
        "bootstrap_seed",
        "item_max_attempts",
        "manifest_sha256",
    }
    if not isinstance(stack_policy, dict) or set(stack_policy) != expected_policy_keys:
        raise ExperimentManifestError(
            "experiment manifest policy.stack_pair must contain exactly the eight stack-pair provenance fields"
        )

    execution = document.get("execution")
    if not isinstance(execution, dict) or execution.get("status") not in {"completed", "aborted"}:
        raise ExperimentManifestError(
            "experiment manifest execution.status must be 'completed' or 'aborted'"
        )

    output = document.get("output")
    if not isinstance(output, dict) or "face_run_record" not in output:
        raise ExperimentManifestError("experiment manifest output.face_run_record is required")
    embedded_record = output["face_run_record"]
    try:
        validated_record = validate_face_run_record(embedded_record)
    except Exception as exc:
        raise ExperimentManifestError(f"invalid output.face_run_record: {exc}") from exc
    if validated_record != embedded_record:
        raise ExperimentManifestError("output.face_run_record is not in canonical validated form")
    return document


__all__ = [
    "ExperimentManifestError",
    "LEGACY_MANIFEST_VERSION",
    "SUPPORTED_MANIFEST_VERSION",
    "_SHA256_RE",
    "build_experiment_manifest",
    "normalize_head_sha",
    "validate_experiment_manifest",
]
