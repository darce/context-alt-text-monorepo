"""Tests for deterministic Chinese Whispers clustering."""

from __future__ import annotations

import numpy as np

from recognition.domain.identity import MediaIdentity
from recognition.infrastructure.clustering.chinese_whispers import DeterministicChineseWhispers
from recognition.shared.ids import generate_id


def normalize(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    return vec.astype(np.float32) / norm


def make_identity(vec: np.ndarray, *, id_value: str | None = None, confidence: float = 0.95) -> MediaIdentity:
    """Create a MediaIdentity for clustering tests."""
    return MediaIdentity(
        id=id_value or str(generate_id()),
        tenant_id="tenant",
        media_id="media",
        embedding=vec,
        confidence=confidence,
        bbox_width=100,
        bbox_height=100,
    )


def test_chinese_whispers_same_input_same_output() -> None:
    """Clustering should be deterministic for the same input."""
    embeddings = [
        normalize(np.array([1.0, 0.0, 0.0])),
        normalize(np.array([0.9, 0.1, 0.0])),
        normalize(np.array([0.0, 1.0, 0.0])),
        normalize(np.array([0.0, 0.9, 0.1])),
    ]
    identities = [make_identity(vec, id_value=f"id-{i}") for i, vec in enumerate(embeddings)]

    cw = DeterministicChineseWhispers(threshold=0.7, max_iterations=10)
    labels1 = cw.cluster(embeddings, identities)
    labels2 = cw.cluster(embeddings, identities)

    assert labels1 == labels2


def test_chinese_whispers_uuid_tiebreaking() -> None:
    """UUID ordering keeps results stable even when input order changes."""
    embeddings = [
        normalize(np.array([1.0, 0.0])),
        normalize(np.array([1.0, 0.0])),
        normalize(np.array([1.0, 0.0])),
    ]

    identities = [
        make_identity(embeddings[0], id_value="id-b"),
        make_identity(embeddings[1], id_value="id-c"),
        make_identity(embeddings[2], id_value="id-a"),  # Smallest UUID should dominate ties
    ]

    cw = DeterministicChineseWhispers(threshold=0.0, max_iterations=5)
    labels_first = cw.cluster(embeddings, identities)

    # Reorder embeddings/identities to prove UUID ordering controls determinism
    reordered_embeddings = [embeddings[2], embeddings[0], embeddings[1]]
    reordered_identities = [identities[2], identities[0], identities[1]]
    labels_second = cw.cluster(reordered_embeddings, reordered_identities)

    mapping_first = {identities[i].id: labels_first[i] for i in range(len(identities))}
    mapping_second = {reordered_identities[i].id: labels_second[i] for i in range(len(reordered_identities))}

    assert mapping_first == mapping_second


def test_chinese_whispers_quality_weighting() -> None:
    """Higher-quality neighbors should win ties when similarities are equal."""
    embeddings = [
        normalize(np.array([1.0, 0.0])),
        normalize(np.array([1.0, 0.0])),
        normalize(np.array([1.0, 0.0])),
    ]

    # Neighbor with smaller UUID but lower quality vs larger UUID with higher quality
    low_quality = make_identity(embeddings[1], id_value="id-a", confidence=0.1)
    high_quality = make_identity(embeddings[2], id_value="id-z", confidence=0.95)
    bridge = make_identity(embeddings[0], id_value="id-m", confidence=0.9)

    cw = DeterministicChineseWhispers(threshold=0.0, max_iterations=5)
    labels = cw.cluster(embeddings, [bridge, low_quality, high_quality])

    mapping = {identity.id: labels[i] for i, identity in enumerate([bridge, low_quality, high_quality])}

    assert mapping[bridge.id] == mapping[high_quality.id]
