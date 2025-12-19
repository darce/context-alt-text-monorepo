"""
JSON serialization helpers for regression harness inputs/outputs.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from recognition.domain.locator import IdentityLocator


def load_canonical_labels(path: Path) -> dict[IdentityLocator, str]:
    """Load a canonical report and return a locator->label mapping.

    Args:
        path: Path to `canonical_report.json`.

    Returns:
        dict[IdentityLocator, str]: Locator -> canonical label.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Canonical report must be a JSON object")

    clusters = payload.get("canonical_clusters")
    if not isinstance(clusters, list):
        raise ValueError("canonical_clusters must be a list")

    labels: dict[IdentityLocator, str] = {}
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        canonical_label = cluster.get("canonical_label")
        if not isinstance(canonical_label, str) or not canonical_label.strip():
            continue

        members = cluster.get("member_identities")
        if not isinstance(members, list):
            continue
        for member in members:
            if not isinstance(member, dict):
                continue
            locator_payload = member.get("identity_locator")
            if not isinstance(locator_payload, Mapping):
                continue
            locator = IdentityLocator.from_dict(locator_payload)
            if locator in labels and labels[locator] != canonical_label:
                raise ValueError("Conflicting canonical labels for identity locator")
            labels[locator] = canonical_label

    return labels


def load_predicted_labels(path: Path) -> dict[IdentityLocator, str]:
    """Load predicted cluster assignments from a baseline report.

    Unlike load_canonical_labels (which uses curated `canonical_clusters`),
    this function extracts labels from `pre_curation_state.predicted_clusters` -
    the original algorithmic assignments before any user curation.

    Use this to measure clustering consistency/reproducibility across runs.

    Note: If the same identity appears in multiple clusters (e.g., from multiple
    runs with reassignments), the first assignment is kept.

    Args:
        path: Path to a canonical report JSON file.

    Returns:
        dict[IdentityLocator, str]: Locator -> predicted cluster ID (as label).
    """
    import logging

    logger = logging.getLogger(__name__)

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Canonical report must be a JSON object")

    pre_curation = payload.get("pre_curation_state")
    if not isinstance(pre_curation, dict):
        raise ValueError("pre_curation_state not found. Report must be generated with --run-id or --all-runs")

    predicted_clusters = pre_curation.get("predicted_clusters")
    if not isinstance(predicted_clusters, list):
        raise ValueError("pre_curation_state.predicted_clusters must be a list")

    labels: dict[IdentityLocator, str] = {}
    conflicts = 0
    for cluster in predicted_clusters:
        if not isinstance(cluster, dict):
            continue
        cluster_id = cluster.get("predicted_cluster_id")
        if not isinstance(cluster_id, str):
            continue

        members = cluster.get("member_identity_locators")
        if not isinstance(members, list):
            continue

        for locator_payload in members:
            if not isinstance(locator_payload, Mapping):
                continue
            locator = IdentityLocator.from_dict(locator_payload)
            if locator in labels:
                if labels[locator] != cluster_id:
                    conflicts += 1
                # Keep first assignment (represents initial clustering state)
                continue
            labels[locator] = cluster_id

    if conflicts > 0:
        logger.warning(
            "Found %d identities with conflicting cluster assignments (kept first). "
            "This may indicate reassignments across multiple runs.",
            conflicts,
        )

    return labels


def write_json(path: Path, payload: Any) -> None:
    """Write a JSON payload to disk.

    Args:
        path: Output path.
        payload: JSON-serializable object.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
