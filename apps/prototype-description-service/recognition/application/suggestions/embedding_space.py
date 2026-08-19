"""Shared FIR23-01 same-space helpers for labelled-cluster ranking.

Roster-candidates uses the in-process embedding_model stamped on eager-loaded
representatives (``get_labeled_with_representatives`` selectinloads identity).
Reps with no resolvable model are skipped fail-closed. Label inference additionally
issues a MediaIdentity SQL fallback for unresolved identity_ids; that SQL path
stays in ``label_inference.py`` and is the deliberate extra width of that caller.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def representative_embedding_model(rep: Any) -> str | None:
    """Resolve embedding_model from the rep, then a loaded identity. Never invent."""
    model = getattr(rep, "embedding_model", None)
    if model is None:
        identity = getattr(rep, "identity", None)
        if identity is not None:
            model = getattr(identity, "embedding_model", None)
    if model is None:
        return None
    return str(model)


def representative_vector(rep: Any) -> np.ndarray | None:
    raw = getattr(rep, "embedding", None)
    if raw is None:
        return None
    vec = np.asarray(raw, dtype=np.float32)
    if vec.size == 0:
        return None
    return vec


def same_space_vector(rep: Any, target_model: str) -> np.ndarray | None:
    """Return the embedding when the rep is in ``target_model`` space, else None.

    Narrower than label_inference FIR23-01: no SQL MediaIdentity fallback.
    Unresolved models are excluded (fail-closed).
    """
    model = representative_embedding_model(rep)
    if model is None or model != str(target_model):
        return None
    return representative_vector(rep)
