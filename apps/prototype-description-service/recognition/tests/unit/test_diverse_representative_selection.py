"""Unit tests for diversity-aware representative selection (FPS algorithm)."""

from __future__ import annotations

import uuid

import numpy as np
import pytest

from recognition.application.persistence.representative_selector import (
    _normalize_embedding,
    _select_diverse_representatives,
)
from recognition.domain.identity import MediaIdentity


def _make_identity_with_embedding(
    embedding: np.ndarray,
    confidence: float = 0.95,
) -> MediaIdentity:
    """Create a synthetic identity with a specific embedding vector."""
    return MediaIdentity(
        id=str(uuid.uuid4()),
        tenant_id=str(uuid.uuid4()),
        media_id=str(uuid.uuid4()),
        embedding=embedding.astype(np.float32),
        confidence=confidence,
        bbox_width=100,
        bbox_height=100,
    )


def _unit_vector(dimension: int, index: int, length: int = 512) -> np.ndarray:
    """Create a unit vector with 1.0 at the specified index."""
    vec = np.zeros(length, dtype=np.float32)
    vec[index] = 1.0
    return vec


class TestNormalizeEmbedding:
    """Tests for _normalize_embedding helper."""

    def test_normalizes_to_unit_length(self) -> None:
        """Normalized vector should have L2 norm of 1."""
        vec = np.array([3.0, 4.0] + [0.0] * 510, dtype=np.float32)
        result = _normalize_embedding(vec)
        norm = float(np.linalg.norm(result))
        assert norm == pytest.approx(1.0, abs=1e-6)

    def test_handles_zero_vector(self) -> None:
        """Zero vector should not cause division by zero."""
        vec = np.zeros(512, dtype=np.float32)
        result = _normalize_embedding(vec)
        assert result.shape == (512,)
        assert np.all(result == 0)


class TestSelectDiverseRepresentatives:
    """Tests for FPS diversity selection algorithm."""

    def test_empty_list_returns_empty(self) -> None:
        """Empty input should return empty output."""
        result = _select_diverse_representatives([], max_reps=5)
        assert result == []

    def test_single_identity_returns_that_identity(self) -> None:
        """Single identity should be returned regardless of max_reps."""
        identity = _make_identity_with_embedding(_unit_vector(512, 0))
        result = _select_diverse_representatives([identity], max_reps=5)
        assert len(result) == 1
        assert result[0].id == identity.id

    def test_first_selection_is_highest_confidence(self) -> None:
        """First representative should be the highest-confidence identity."""
        low_conf = _make_identity_with_embedding(_unit_vector(512, 0), confidence=0.50)
        high_conf = _make_identity_with_embedding(_unit_vector(512, 1), confidence=0.99)
        med_conf = _make_identity_with_embedding(_unit_vector(512, 2), confidence=0.75)

        result = _select_diverse_representatives([low_conf, high_conf, med_conf], max_reps=3)

        assert len(result) == 3
        # First should be highest confidence
        assert result[0].id == high_conf.id

    def test_selects_diverse_embeddings_over_similar(self) -> None:
        """FPS should select diverse embeddings, not just high-confidence ones.

        Scenario:
        - Identity A (conf=0.99): embedding at [1, 0, 0, ...]
        - Identity B (conf=0.90): embedding at [0.99, 0.1, 0, ...] (similar to A)
        - Identity C (conf=0.80): embedding at [0, 1, 0, ...] (orthogonal to A)

        With confidence-only: A, B would be chosen.
        With FPS: A, C should be chosen (C is more diverse).
        """
        # A: highest confidence, points along axis 0
        a_embedding = _unit_vector(512, 0)
        identity_a = _make_identity_with_embedding(a_embedding, confidence=0.99)

        # B: medium confidence, very similar to A (small angle)
        b_embedding = np.zeros(512, dtype=np.float32)
        b_embedding[0] = 0.99
        b_embedding[1] = 0.1
        b_embedding /= np.linalg.norm(b_embedding)
        identity_b = _make_identity_with_embedding(b_embedding, confidence=0.90)

        # C: lowest confidence, orthogonal to A (maximum diversity)
        c_embedding = _unit_vector(512, 1)
        identity_c = _make_identity_with_embedding(c_embedding, confidence=0.80)

        result = _select_diverse_representatives(
            [identity_a, identity_b, identity_c],
            max_reps=2,
        )

        assert len(result) == 2
        # First is highest confidence (A)
        assert result[0].id == identity_a.id
        # Second should be C (orthogonal) not B (similar), despite B having higher confidence
        assert result[1].id == identity_c.id

    def test_preserves_bridge_face_with_low_confidence(self) -> None:
        """FPS should preserve a 'bridge' face even if it has low confidence.

        This is the key fix for batch consistency:
        - Batch 1: Faces A, B where B bridges to future data
        - If B has low confidence, confidence-only would discard it
        - FPS should keep B if it's geometrically diverse

        Scenario simulating sub-clusters:
        - Group 1: identity_a (conf=0.99), identity_a2 (conf=0.97) - similar embeddings
        - Bridge: identity_bridge (conf=0.70) - different embedding
        - Group 2 (not in this batch): would connect to bridge

        FPS should pick identity_a (highest conf) and identity_bridge (most diverse).
        """
        # Group 1 embeddings (clustered together)
        a_embedding = np.zeros(512, dtype=np.float32)
        a_embedding[0] = 1.0
        identity_a = _make_identity_with_embedding(a_embedding, confidence=0.99)

        a2_embedding = np.zeros(512, dtype=np.float32)
        a2_embedding[0] = 0.98
        a2_embedding[1] = 0.2
        a2_embedding /= np.linalg.norm(a2_embedding)
        identity_a2 = _make_identity_with_embedding(a2_embedding, confidence=0.97)

        a3_embedding = np.zeros(512, dtype=np.float32)
        a3_embedding[0] = 0.95
        a3_embedding[1] = 0.3
        a3_embedding /= np.linalg.norm(a3_embedding)
        identity_a3 = _make_identity_with_embedding(a3_embedding, confidence=0.93)

        # Bridge face: low confidence but very different angle
        bridge_embedding = np.zeros(512, dtype=np.float32)
        bridge_embedding[2] = 1.0  # Orthogonal to group 1
        identity_bridge = _make_identity_with_embedding(bridge_embedding, confidence=0.70)

        result = _select_diverse_representatives(
            [identity_a, identity_a2, identity_a3, identity_bridge],
            max_reps=2,
        )

        assert len(result) == 2
        # First is highest confidence (identity_a)
        assert result[0].id == identity_a.id
        # Second should be bridge (most diverse), not a2 or a3 (higher confidence but similar)
        assert result[1].id == identity_bridge.id

    def test_respects_max_reps_limit(self) -> None:
        """Should not return more than max_reps identities."""
        identities = [_make_identity_with_embedding(_unit_vector(512, i), confidence=0.9 - i * 0.01) for i in range(10)]

        result = _select_diverse_representatives(identities, max_reps=3)
        assert len(result) == 3

    def test_handles_fewer_identities_than_max_reps(self) -> None:
        """Should return all identities when count < max_reps."""
        identities = [_make_identity_with_embedding(_unit_vector(512, i), confidence=0.9) for i in range(2)]

        result = _select_diverse_representatives(identities, max_reps=10)
        assert len(result) == 2
