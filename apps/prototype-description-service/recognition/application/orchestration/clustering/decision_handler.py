"""Decision handling for incremental clustering."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import numpy as np

from recognition.application.assignment import (
    AssignmentCandidate,
    AssignmentDecision,
    AssignmentGate,
    AssignmentOutcome,
)
from recognition.application.orchestration.protocols import SuggestionServiceProtocol
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.domain.locator import IdentityLocator
from recognition.observability import ClusteringLogger, DecisionType
from recognition.shared.similarity import extract_face_embedding

logger = logging.getLogger(__name__)


def log_and_report_decision(
    *,
    logger_instance: logging.Logger,
    clustering_logger: ClusteringLogger | None,
    gate: AssignmentGate,
    candidate: AssignmentCandidate,
    decision: AssignmentDecision,
    job_label: str,
) -> None:
    """Log decision to standard logs and observability backend."""
    logger_instance.info(
        "[clustering] Gate decision for identity %s -> cluster %s: %s (checks passed: %s, failed: %s)",
        candidate.identity.id,
        candidate.cluster_id,
        decision.outcome.value,
        decision.checks_passed,
        decision.checks_failed,
    )

    if not clustering_logger:
        return

    locator_payload: dict[str, object] | None = None
    if candidate.identity.bbox_x is not None and candidate.identity.bbox_y is not None:
        try:
            locator_payload = IdentityLocator(
                media_id=int(candidate.identity.media_id),
                bbox_x=int(candidate.identity.bbox_x),
                bbox_y=int(candidate.identity.bbox_y),
                bbox_width=int(candidate.identity.bbox_width),
                bbox_height=int(candidate.identity.bbox_height),
                crop_hash=None,
            ).to_dict()
        except (TypeError, ValueError):
            locator_payload = None

    decision_metadata: dict[str, Any] = dict(decision.metadata or {})
    fingerprint = None
    if candidate.identity.embedding is not None:
        face_vec = extract_face_embedding(np.asarray(candidate.identity.embedding, dtype=np.float32))
        fingerprint = hashlib.sha256(face_vec.tobytes()).hexdigest()[:8]

    decision_metadata.update(
        {
            "identity_id": candidate.identity.id,
            "embedding_fingerprint": fingerprint,
            "image_phash": candidate.identity.image_phash,
            "method": candidate.discovery_method.value,
            "stage": f"{candidate.discovery_method.name.title()}Discovery",
            "threshold": gate.settings.similarity_threshold,
            "gate_checks": {"passed": decision.checks_passed, "failed": decision.checks_failed},
            "anchor_linked": bool(candidate.anchor_linked),
            "confidence": float(decision.suggestion_confidence)
            if decision.suggestion_confidence is not None
            else candidate.discovery_similarity,
        }
    )
    if locator_payload is not None:
        decision_metadata["identity_locator"] = locator_payload

    decision_type = {
        AssignmentOutcome.ACCEPT: DecisionType.ACCEPT,
        AssignmentOutcome.SUGGEST: DecisionType.SUGGEST,
        AssignmentOutcome.REJECT: DecisionType.REJECT,
    }[decision.outcome]

    clustering_logger.log_decision(
        identity_id=candidate.identity.id,
        cluster_id=candidate.cluster_id,
        decision=decision_type,
        similarity=candidate.discovery_similarity,
        reason=decision.rejection_reason,
        metadata=decision_metadata,
        algorithm=candidate.discovery_method.value,
        job_id=job_label,
        media_id=candidate.identity.media_id,
    )


class DecisionHandler:
    """Apply assignment decisions and persist their effects."""

    def __init__(
        self,
        *,
        gate: AssignmentGate,
        assignment_writer: AssignmentWriter,
        suggestion_service: SuggestionServiceProtocol,
        clustering_logger: ClusteringLogger | None = None,
        logger_instance: logging.Logger | None = None,
    ) -> None:
        self._gate = gate
        self._writer = assignment_writer
        self._suggestions = suggestion_service
        self._clustering_logger = clustering_logger
        self._logger = logger_instance or logger

    async def evaluate_and_handle(
        self,
        candidate: AssignmentCandidate,
        *,
        job_id: str,
        job_label: str,
    ) -> AssignmentDecision:
        """Evaluate a candidate and apply the resulting decision."""
        decision = await self._gate.evaluate(candidate)
        log_and_report_decision(
            logger_instance=self._logger,
            clustering_logger=self._clustering_logger,
            gate=self._gate,
            candidate=candidate,
            decision=decision,
            job_label=job_label,
        )

        if decision.outcome == AssignmentOutcome.ACCEPT:
            await self._writer.persist_assignment(decision, batch_mode=True)
            await self._suggestions.resolve_for_identity_exclusive(
                identity_id=candidate.identity.id,
                accepted_cluster_id=candidate.cluster_id,
                reason="auto_assignment",
            )
            self._logger.info(
                "[clustering] ACCEPTED job_id=%s identity=%s media_id=%s cluster=%s",
                job_id,
                candidate.identity.id,
                candidate.identity.media_id,
                candidate.cluster_id,
            )
        elif decision.outcome == AssignmentOutcome.SUGGEST:
            await self._suggestions.create(candidate, decision.suggestion_confidence)
            self._logger.info(
                "[clustering] SUGGESTED job_id=%s identity=%s media_id=%s cluster=%s confidence=%.2f reason=%s",
                job_id,
                candidate.identity.id,
                candidate.identity.media_id,
                candidate.cluster_id,
                decision.suggestion_confidence or 0.0,
                decision.rejection_reason,
            )
        else:
            self._logger.info(
                "[clustering] REJECTED job_id=%s identity=%s media_id=%s cluster=%s reason=%s",
                job_id,
                candidate.identity.id,
                candidate.identity.media_id,
                candidate.cluster_id,
                decision.rejection_reason,
            )

        return decision

    async def evaluate_only(
        self,
        candidate: AssignmentCandidate,
        *,
        job_id: str,
        job_label: str,
        verbose: bool = True,
    ) -> AssignmentDecision:
        """Evaluate a candidate and handle SUGGEST/REJECT, but defer ACCEPT persistence.

        For ACCEPT decisions the caller is responsible for bulk-persisting membership
        and resolving suggestions (see ``AssignmentWriter.persist_assignments_chunk``).
        This allows the orchestrator to batch all ACCEPT decisions for a chunk into
        a single bulk INSERT per cluster instead of N per-identity round-trips.
        """
        decision = await self._gate.evaluate(candidate)
        if verbose:
            log_and_report_decision(
                logger_instance=self._logger,
                clustering_logger=self._clustering_logger,
                gate=self._gate,
                candidate=candidate,
                decision=decision,
                job_label=job_label,
            )

        if decision.outcome == AssignmentOutcome.SUGGEST:
            await self._suggestions.create(candidate, decision.suggestion_confidence)
            if verbose:
                self._logger.info(
                    "[clustering] SUGGESTED job_id=%s identity=%s media_id=%s cluster=%s confidence=%.2f reason=%s",
                    job_id,
                    candidate.identity.id,
                    candidate.identity.media_id,
                    candidate.cluster_id,
                    decision.suggestion_confidence or 0.0,
                    decision.rejection_reason,
                )
        elif decision.outcome == AssignmentOutcome.REJECT:
            if verbose:
                self._logger.info(
                    "[clustering] REJECTED job_id=%s identity=%s media_id=%s cluster=%s reason=%s",
                    job_id,
                    candidate.identity.id,
                    candidate.identity.media_id,
                    candidate.cluster_id,
                    decision.rejection_reason,
                )

        return decision
