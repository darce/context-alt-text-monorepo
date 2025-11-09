"""Helpers for syncing roster entries into auxiliary embedding stores."""

from __future__ import annotations

import logging
from typing import Optional

from .interfaces import EmbeddingStoragePort, RosterStoragePort


def sync_embeddings_store(
    embedding_storage: Optional[EmbeddingStoragePort],
    roster_storage: RosterStoragePort,
    model: str,
    logger: logging.Logger,
) -> None:
    """
    Persist roster entries to the external embedding store if configured.

    The sync is best-effort: failures are logged but do not raise.
    """
    if embedding_storage is None:
        return

    try:
        entries = roster_storage.load_roster_entries(model)
        embedding_storage.save_embeddings(entries, model)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to sync embeddings for model %s: %s", model, exc)
