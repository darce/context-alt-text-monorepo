"""Shared FIR23-01 same-space helpers for labelled-cluster ranking.

Roster-candidates uses the in-process embedding_model stamped on eager-loaded
representatives (``get_labeled_with_representatives`` selectinloads identity).
Reps with no resolvable model are skipped fail-closed. Label inference additionally
issues a MediaIdentity SQL fallback for unresolved identity_ids; that SQL path
stays in ``label_inference.py`` and is the deliberate extra width of that caller.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


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


def models_are_same_space(left: str | None, right: str | None) -> bool:
    """True when both ids match, including the legacy both-unstamped case.

    Mixed stamped/unstamped or two different stamps are cross-space and must
    not be cosined (FIR23-01). Two Nones stay comparable so single-model
    tenants that never stamped provenance keep working.
    """
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    return str(left) == str(right)


def choose_embedding_model(models: Iterable[str | None]) -> str | None:
    """Majority embedding_model with lex-stable tie-break (FIR23-01)."""
    counts: dict[str, int] = {}
    for model in models:
        if not model:
            continue
        key = str(model)
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def cluster_embedding_model(cluster: Any) -> str | None:
    """Resolve a cluster's embedding space without inventing a default.

    Prefer an explicit ``embedding_model`` on the cluster, else the majority
    of loaded representatives (lex-stable tie-break). Unresolved → None.
    """
    explicit = getattr(cluster, "embedding_model", None)
    if explicit:
        return str(explicit)
    return choose_embedding_model(
        representative_embedding_model(rep) for rep in getattr(cluster, "representatives", None) or []
    )


def filter_to_active_embedding_space(
    items: Sequence[Any],
    *,
    log_prefix: str = "[clustering]",
) -> list[Any]:
    """Keep one embedding space: single-model no-op; mixed → active id only.

    If the active runtime id cannot be resolved, fail closed (empty) and log
    WARNING. Never majority-cluster a foreign space.
    """
    if not items:
        return []
    distinct = {str(getattr(item, "embedding_model", None)) for item in items if getattr(item, "embedding_model", None)}
    if len(distinct) <= 1:
        return list(items)
    from recognition.application.embedding.manifest import try_active_embedding_model_id

    active = try_active_embedding_model_id()
    if not active:
        logger.warning(
            "%s mixed embedding_model present but active model unresolved; fail-closed empty batch (FIR23-01)",
            log_prefix,
        )
        return []
    matched = [item for item in items if getattr(item, "embedding_model", None) == active]
    if not matched:
        logger.warning(
            "%s mixed embedding_model=%s none match active=%s; fail-closed empty batch",
            log_prefix,
            sorted(distinct),
            active,
        )
    elif len(matched) < len(items):
        logger.info(
            "%s embedding_model filter active=%s kept=%d skipped=%d",
            log_prefix,
            active,
            len(matched),
            len(items) - len(matched),
        )
    return matched
