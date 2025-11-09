"""Simple roster cache utilities."""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from .entities import RosterEntry


class RosterCache:
    """In-memory cache keyed by model name."""

    def __init__(self) -> None:
        self._store: Dict[str, List[RosterEntry]] = {}

    def get_or_load(self, model: str, loader: Callable[[], List[RosterEntry]]) -> List[RosterEntry]:
        """Return cached entries for model, using loader callback when missing."""
        if model in self._store:
            return self._store[model]

        entries = loader()
        self._store[model] = entries
        return entries

    def set(self, model: str, entries: List[RosterEntry]) -> None:
        """Explicitly assign cached entries for a model."""
        self._store[model] = entries

    def invalidate(self, model: str) -> None:
        """Remove cached entries for the given model."""
        self._store.pop(model, None)

    def clear(self) -> None:
        """Evict all cached entries."""
        self._store.clear()

    def peek(self, model: str) -> Optional[List[RosterEntry]]:
        """Return cached entries if present without triggering load."""
        return self._store.get(model)
