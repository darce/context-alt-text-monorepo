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
from typing import Protocol

import numpy as np

from recognition.domain.cluster import IdentityCluster
from recognition.domain.representative import ClusterRepresentative

logger = logging.getLogger(__name__)


class _EmbeddingModelRow(Protocol):
    embedding_model: str | None


def representative_embedding_model(rep: ClusterRepresentative) -> str | None:
    """Return the provenance stamp carried by a domain representative."""
    try:
        model = rep.embedding_model
    except AttributeError:
        # Keep old structural test doubles fail-closed while production callers
        # use the concrete ClusterRepresentative contract above.
        return None
    return model if isinstance(model, str) and model else None


def representative_vector(rep: ClusterRepresentative) -> np.ndarray | None:
    try:
        raw = rep.embedding
    except AttributeError:
        return None
    vec = np.asarray(raw, dtype=np.float32)
    if vec.size == 0:
        return None
    return vec


def same_space_vector(rep: ClusterRepresentative, target_model: str) -> np.ndarray | None:
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


def same_space_representative_vectors(
    reps: Sequence[ClusterRepresentative],
) -> tuple[str | None, list[np.ndarray]]:
    """Return the majority-space gallery model and its raw vectors.

    Representative repositories may return a legacy all-unstamped set or a
    set containing more than one stamped space.  Keep the existing majority
    selection rule in one place so every cosine caller applies the same
    fail-closed handling before normalizing vectors.
    """
    chosen = choose_embedding_model(representative_embedding_model(rep) for rep in reps)
    vectors: list[np.ndarray] = []
    for rep in reps:
        if chosen is None:
            if representative_embedding_model(rep) is not None:
                continue
            vector = representative_vector(rep)
        else:
            vector = same_space_vector(rep, chosen)
        if vector is not None:
            vectors.append(vector)
    return chosen, vectors


def cluster_embedding_model(cluster: IdentityCluster) -> str | None:
    """Resolve a cluster's embedding space without inventing a default.

    Prefer an explicit ``embedding_model`` on the cluster, else the majority
    of loaded representatives (lex-stable tie-break). Unresolved → None.
    """
    explicit = cluster.embedding_model
    if isinstance(explicit, str) and explicit:
        return explicit
    return choose_embedding_model(representative_embedding_model(rep) for rep in cluster.representatives or [])


def filter_to_active_embedding_space[EmbeddingModelRowT: _EmbeddingModelRow](
    items: Sequence[EmbeddingModelRowT],
    *,
    log_prefix: str = "[clustering]",
) -> list[EmbeddingModelRowT]:
    """Keep one embedding space: unstamped-only is legacy no-op; stamped → active id.

    If the active runtime id cannot be resolved, fail closed (empty) and log
    WARNING. Never majority-cluster a foreign space.
    """
    if not items:
        return []
    distinct = {str(item.embedding_model) for item in items if item.embedding_model}
    if not distinct:
        # There is no provenance to compare against. Preserve the legacy
        # all-unstamped path; a stamped row in the same batch is handled below
        # and is never allowed to mix with these rows.
        return list(items)
    from recognition.application.embedding.manifest import try_active_embedding_model_id

    active = try_active_embedding_model_id()
    if not active:
        logger.warning(
            "%s stamped embedding_model present but active model unresolved; fail-closed empty batch (FIR23-01)",
            log_prefix,
        )
        return []
    matched = [item for item in items if item.embedding_model == active]
    if not matched:
        logger.warning(
            "%s embedding_model=%s none match active=%s; fail-closed empty batch",
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
