"""
RepresentativeMatcher adapter that routes representative matches through AssignmentGate.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass
import numpy as np

from recognition.application.assignment import AssignmentGate, AssignmentOutcome, AssignmentWriter
from recognition.application.discovery.representative import RepresentativeDiscovery
from recognition.application.orchestration.protocols import SuggestionServiceProtocol
from recognition.domain.identity import MediaIdentity
from recognition.domain.locator import IdentityLocator
from recognition.observability import ClusteringLogger, DecisionType

# Callback to persist representative embedding after assignment
AddRepresentativeFn = Callable[[str, MediaIdentity], Awaitable[np.ndarray | None]]


class RepresentativeMatcher:
    """Adapter that feeds representative matches through the unified assignment gate."""

    def __init__(
        self,
        discovery: RepresentativeDiscovery,
        gate: AssignmentGate,
        writer: AssignmentWriter,
        add_representative_embedding: AddRepresentativeFn,
        suggestion_service: SuggestionServiceProtocol | None = None,
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
        representatives_by_cluster: dict[str, list[np.ndarray]],
    ) -> tuple[int, list[MediaIdentity], dict[str, list[np.ndarray]]]:
        """Match identities against representatives using the gate."""
        assignments = 0
        still_unclustered: list[MediaIdentity] = []

        assignment_candidates = await self.discovery.discover(candidates, representatives_by_cluster)

        for assignment_candidate in assignment_candidates:
            decision = await self.gate.evaluate(assignment_candidate)
            self._log_decision(decision)

            if decision.outcome is AssignmentOutcome.ACCEPT:
                await self.writer.assign_to_existing_cluster(
                    assignment_candidate.identity,
                    assignment_candidate.cluster_id,
                    assignment_candidate.discovery_similarity,
                )
                if self.suggestion_service:
                    await self.suggestion_service.resolve_for_identity_exclusive(
                        identity_id=assignment_candidate.identity.id,
                        accepted_cluster_id=assignment_candidate.cluster_id,
                        reason="auto_assignment_matcher",
                    )
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

        locator_payload: dict[str, object] | None = None
        identity = decision.candidate.identity
        if identity.bbox_x is not None and identity.bbox_y is not None:
            try:
                locator_payload = IdentityLocator(
                    media_id=int(identity.media_id),
                    bbox_x=int(identity.bbox_x),
                    bbox_y=int(identity.bbox_y),
                    bbox_width=int(identity.bbox_width),
                    bbox_height=int(identity.bbox_height),
                    crop_hash=None,
                ).to_dict()
            except (TypeError, ValueError):
                locator_payload = None

        metadata = dict(decision.metadata or {})
        gate_settings = getattr(self.gate, "settings", None)
        threshold = getattr(gate_settings, "similarity_threshold", None) if gate_settings is not None else None
        metadata.update(
            {
                "method": decision.candidate.discovery_method.value,
                "stage": f"{decision.candidate.discovery_method.name.title()}Discovery",
                "threshold": float(threshold) if threshold is not None else None,
                "gate_checks": {"passed": decision.checks_passed, "failed": decision.checks_failed},
                "anchor_linked": bool(decision.candidate.anchor_linked),
                "confidence": float(decision.suggestion_confidence)
                if decision.suggestion_confidence is not None
                else decision.candidate.discovery_similarity,
            }
        )
        if locator_payload is not None:
            metadata["identity_locator"] = locator_payload

        self.logger.log_decision(
            identity_id=decision.candidate.identity.id,
            cluster_id=decision.candidate.cluster_id,
            decision=decision_type,
            similarity=decision.candidate.discovery_similarity,
            reason=decision.rejection_reason,
            metadata=metadata,
            algorithm=decision.candidate.discovery_method.value,
            job_id=None,
            media_id=identity.media_id,
        )
