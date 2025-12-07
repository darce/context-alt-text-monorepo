"""
RepresentativeMatcher adapter that routes representative matches through AssignmentGate.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol
from uuid import UUID

import numpy as np

from recognition.application.assignment import AssignmentGate, AssignmentOutcome, AssignmentWriter
from recognition.application.assignment.candidate import AssignmentCandidate
from recognition.application.discovery.representative import RepresentativeDiscovery
from recognition.domain.identity import MediaIdentity
from recognition.observability import ClusteringLogger, DecisionType

# Callback to persist representative embedding after assignment
AddRepresentativeFn = Callable[[UUID, MediaIdentity], Awaitable[np.ndarray | None]]


class SuggestionService(Protocol):
    """Protocol for creating assignment suggestions."""

    async def create(self, candidate: AssignmentCandidate, confidence: float | None = None) -> None:
        """Create a suggestion record for later human review."""


class RepresentativeMatcher:
    """Adapter that feeds representative matches through the unified assignment gate."""

    def __init__(
        self,
        discovery: RepresentativeDiscovery,
        gate: AssignmentGate,
        writer: AssignmentWriter,
        add_representative_embedding: AddRepresentativeFn,
        suggestion_service: SuggestionService | None = None,
        logger: ClusteringLogger | None = None,
    ) -> None:
        self.discovery = discovery
        self.gate = gate
        self.writer = writer
        self.add_representative_embedding = add_representative_embedding
        self.suggestion_service = suggestion_service
        self.logger = logger

    async def match(
        self,
        candidates: Sequence[MediaIdentity],
        representatives_by_cluster: dict[UUID, list[np.ndarray]],
    ) -> tuple[int, list[MediaIdentity], dict[UUID, list[np.ndarray]]]:
        """Match identities against representatives using the gate."""
        assignments = 0
        still_unclustered: list[MediaIdentity] = []

        assignment_candidates = await self.discovery.discover(candidates, representatives_by_cluster)

        for assignment_candidate in assignment_candidates:
            decision = await self.gate.evaluate(assignment_candidate)
            self._log_decision(decision)

            if decision.outcome is AssignmentOutcome.ACCEPT:
                await self.writer.assign(assignment_candidate)
                rep = await self.add_representative_embedding(
                    assignment_candidate.cluster_id, assignment_candidate.identity
                )
                if rep is not None:
                    representatives_by_cluster.setdefault(assignment_candidate.cluster_id, []).append(rep)
                assignments += 1
            elif decision.outcome is AssignmentOutcome.SUGGEST:
                if self.suggestion_service:
                    await self.suggestion_service.create(assignment_candidate, decision.suggestion_confidence)
                still_unclustered.append(assignment_candidate.identity)
            else:
                still_unclustered.append(assignment_candidate.identity)

        return assignments, still_unclustered, representatives_by_cluster

    def _log_decision(self, decision) -> None:
        if not self.logger:
            return
        decision_type = {
            AssignmentOutcome.ACCEPT: DecisionType.ACCEPT,
            AssignmentOutcome.SUGGEST: DecisionType.SUGGEST,
            AssignmentOutcome.REJECT: DecisionType.REJECT,
        }[decision.outcome]
        self.logger.log_decision(
            identity_id=decision.candidate.identity.id,
            cluster_id=decision.candidate.cluster_id,
            decision=decision_type,
            similarity=decision.candidate.discovery_similarity,
            reason=decision.rejection_reason,
            metadata=decision.metadata,
        )
