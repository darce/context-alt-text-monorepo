"""Tests for RepresentativeMatcher adapter using AssignmentGate."""

from __future__ import annotations

import numpy as np
import pytest

from recognition.application.assignment import (
    AssignmentCandidate,
    AssignmentDecision,
    AssignmentGate,
    AssignmentOutcome,
    AssignmentWriter,
)
from recognition.application.discovery.representative import RepresentativeDiscovery
from recognition.application.representatives.representative_matcher import RepresentativeMatcher
from recognition.application.settings import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.shared.ids import generate_id


def make_settings() -> ClusteringSettings:
    return ClusteringSettings(
        similarity_threshold=0.7,
        complete_link_min_floor=0.7,
        complete_link_avg_threshold=0.8,
        min_representatives_for_maturity=1,
        member_validation_min_floor=0.7,
        member_validation_avg_threshold=0.8,
        early_stage_suggestion_enabled=True,
        early_stage_high_confidence_threshold=0.9,
        adaptive_threshold_maturity_point=1,
        hdbscan_max_batch_size=None,
    )


def make_identity(vec: np.ndarray) -> MediaIdentity:
    return MediaIdentity(
        id=str(generate_id()),
        tenant_id=str(generate_id()),
        media_id=str(generate_id()),
        embedding=vec,
        confidence=0.95,
        bbox_width=100,
        bbox_height=100,
    )


def normalize(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    return vec.astype(np.float32) / norm


class GateStub(AssignmentGate):
    def __init__(self, outcomes: list[AssignmentOutcome]) -> None:
        self.outcomes = outcomes
        self.seen: list[AssignmentCandidate] = []

    async def evaluate(self, candidate: AssignmentCandidate) -> AssignmentDecision:
        self.seen.append(candidate)
        outcome = self.outcomes.pop(0)
        return AssignmentDecision(
            outcome=outcome,
            candidate=candidate,
            checks_passed=[],
            checks_failed=[],
        )


class WriterStub(AssignmentWriter):
    def __init__(self) -> None:
        self.assigned: list[AssignmentCandidate] = []

    async def assign(self, candidate: AssignmentCandidate) -> None:
        self.assigned.append(candidate)

    async def create_cluster(self, members):
        raise NotImplementedError


class SuggestionStub:
    def __init__(self) -> None:
        self.suggestions: list[tuple[AssignmentCandidate, float | None]] = []

    async def create(self, candidate: AssignmentCandidate, confidence: float | None = None) -> None:
        self.suggestions.append((candidate, confidence))


@pytest.mark.asyncio
async def test_representative_matcher_routes_through_gate() -> None:
    settings = make_settings()
    discovery = RepresentativeDiscovery(settings=settings)
    cluster_id = str(generate_id())
    identity_accept = make_identity(normalize(np.array([1.0, 0.0, 0.0])))
    identity_suggest = make_identity(normalize(np.array([0.0, 1.0, 0.0])))
    reps = {
        cluster_id: [
            normalize(np.array([1.0, 0.0, 0.0])),
            normalize(np.array([0.9, 0.1, 0.0])),
            normalize(np.array([0.0, 1.0, 0.0])),
        ],
    }

    gate = GateStub([AssignmentOutcome.ACCEPT, AssignmentOutcome.SUGGEST])
    writer = WriterStub()
    suggestions = SuggestionStub()

    async def add_rep(cluster: str, identity: MediaIdentity) -> np.ndarray | None:
        return np.array(identity.embedding, dtype=np.float32)

    matcher = RepresentativeMatcher(
        discovery=discovery,
        gate=gate,
        writer=writer,
        add_representative_embedding=add_rep,
        suggestion_service=suggestions,
        logger=None,
    )

    assigned_count, still_unclustered, updated_reps = await matcher.match(
        [identity_accept, identity_suggest],
        reps,
    )

    assert assigned_count == 1
    assert writer.assigned[0].identity.id == identity_accept.id
    assert len(suggestions.suggestions) == 1
    assert suggestions.suggestions[0][0].identity.id == identity_suggest.id
    assert still_unclustered == [identity_suggest]
    assert cluster_id in updated_reps
    assert len(updated_reps[cluster_id]) >= 2
