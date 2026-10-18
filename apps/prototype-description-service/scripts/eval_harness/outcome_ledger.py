"""Promotion seam for the existing benchmark outcome ledger."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.bench.corpus import ItemOutcomeStore
from scripts.bench.score_report import AcceptedSet, compute_accepted_set


class OutcomeLedger:
    """Facade over exactly one existing ``ItemOutcomeStore`` instance."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._store = ItemOutcomeStore(self.path)

    def append(self, record: dict[str, Any]) -> None:
        """Append one record using the existing store's serialization semantics."""
        self._store.append(record)

    def read_all(self) -> list[dict[str, Any]]:
        """Return records using the existing store's validation and ordering."""
        return self._store.read_all()

    def latest(self, manifest_media_id: int, phase: str) -> dict[str, Any] | None:
        """Return the existing store's last matching record."""
        return self._store.latest(manifest_media_id, phase)


def summarize_run(run_dir: Path | str) -> dict[str, Any]:
    accepted = compute_accepted_set(run_dir)
    return {
        "manifest_entry_count": accepted.manifest_entry_count,
        "accepted_set_size": accepted.accepted_set_size,
        "resolved_floor_count": accepted.resolved_floor_count,
        "manifest_media_ids": accepted.manifest_media_ids,
        "attrition_ingest_analyze": accepted.attrition_ingest_analyze,
        "attrition_join": accepted.attrition_join,
        "zero_detection_media_count": accepted.zero_detection_media_count,
    }


def accepted_set_for_run(run_dir: Path | str) -> AcceptedSet:
    """Promoted accepted-set entry point."""

    return compute_accepted_set(run_dir)


__all__ = (
    "AcceptedSet",
    "ItemOutcomeStore",
    "OutcomeLedger",
    "accepted_set_for_run",
    "compute_accepted_set",
    "summarize_run",
)
