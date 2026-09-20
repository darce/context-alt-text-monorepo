"""RED-only promotion seam for the existing benchmark outcome ledger.

The GREEN implementation must delegate persistence to
``scripts.bench.corpus.ItemOutcomeStore`` and denominator/attrition arithmetic
to ``scripts.bench.score_report.compute_accepted_set``.  It must not introduce
another ``items.jsonl`` store or reimplement accepted-set arithmetic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.bench.corpus import ItemOutcomeStore
from scripts.bench.score_report import AcceptedSet, compute_accepted_set


class OutcomeLedger:
    """RED placeholder for a facade that delegates to ``ItemOutcomeStore``."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def append(self, _record: dict[str, Any]) -> None:
        """RED placeholder; append must delegate to the existing store."""

    def read_all(self) -> list[dict[str, Any]]:
        """RED placeholder; read must return the existing JSONL records verbatim."""

        return []

    def latest(self, _manifest_media_id: int, _phase: str) -> dict[str, Any] | None:
        """RED placeholder for the existing last-record semantics."""

        return None


def summarize_run(_run_dir: Path | str) -> dict[str, Any]:
    """RED placeholder for accepted-set and attrition fields from the existing scorer."""

    return {}


def accepted_set_for_run(run_dir: Path | str) -> AcceptedSet:
    """Promoted accepted-set entry point reserved for the GREEN implementation."""

    return compute_accepted_set(run_dir)


__all__ = [
    "AcceptedSet",
    "ItemOutcomeStore",
    "OutcomeLedger",
    "accepted_set_for_run",
    "compute_accepted_set",
    "summarize_run",
]
