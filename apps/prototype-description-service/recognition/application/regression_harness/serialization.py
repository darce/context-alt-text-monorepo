"""
JSON serialization helpers for regression harness inputs/outputs.
"""

from __future__ import annotations

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
    raise NotImplementedError("TODO: implement load_canonical_labels")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON payload to disk.

    Args:
        path: Output path.
        payload: JSON-serializable object.
    """
    raise NotImplementedError("TODO: implement write_json")
