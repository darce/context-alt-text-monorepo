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


def write_json(path: Path, payload: Any) -> None:
    """Write a JSON payload to disk.

    Args:
        path: Output path.
        payload: JSON-serializable object.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
