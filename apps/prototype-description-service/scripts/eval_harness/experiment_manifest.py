"""RED-only contract surface for the FIRDV-2 experiment manifest.

The implementation belongs to the follow-up GREEN slice.  This module keeps
the import surface stable so the contract tests can collect without creating a
second corpus manifest, run-record schema, SHA normalizer, or stack-pair
policy implementation.
"""

from __future__ import annotations

from typing import Any

from scripts.eval_harness.manifest import (
    _SHA256_RE,
    LEGACY_MANIFEST_VERSION,
    SUPPORTED_MANIFEST_VERSION,
)
from scripts.eval_harness.provenance_sha import normalize_head_sha


class ExperimentManifestError(ValueError):
    """The experiment manifest does not satisfy its immutable-run contract."""


def build_experiment_manifest(**_kwargs: Any) -> dict[str, Any]:
    """RED placeholder; the GREEN implementation will build a validated document."""

    return {}


def validate_experiment_manifest(document: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    """RED placeholder; the GREEN implementation will validate and normalize a document."""

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
