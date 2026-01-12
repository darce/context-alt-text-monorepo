"""Adaptive threshold learning from user feedback."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.observability import ClusteringFeedback
from recognition.application.settings.experiments import ACTIVE_EXPERIMENTS, ExperimentVariant


@dataclass(frozen=True)
class AdaptiveThresholdResult:
    threshold: float
    source: str
    confidence: float
    sample_size: int


class AdaptiveThresholdService:
    """Learn optimal similarity thresholds from user feedback."""

    MINIMUM_SAMPLES = 50

    def __init__(self, session: AsyncSession, *, default_threshold: float = 0.72) -> None:
        self._session = session
        self._default = default_threshold

    async def get_threshold(self, tenant_id: str, experiment_id: str | None = None) -> AdaptiveThresholdResult:
        if experiment_id:
            variant = self._get_experiment_variant(tenant_id, experiment_id)
            if variant is not None:
                return AdaptiveThresholdResult(
                    threshold=variant.threshold,
                    source=f"experiment:{experiment_id}:{variant.name}",
                    confidence=1.0,
                    sample_size=0,
                )

        learned = await self._learn_from_feedback(tenant_id)
        if learned and learned.sample_size >= self.MINIMUM_SAMPLES:
            return learned

        return AdaptiveThresholdResult(
            threshold=self._default,
            source="default",
            confidence=0.5,
            sample_size=0,
        )

    def _get_experiment_variant(self, tenant_id: str, experiment_id: str) -> ExperimentVariant | None:
        experiment = ACTIVE_EXPERIMENTS.get(experiment_id)
        if experiment is None:
            return None

        digest = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) / 0xFFFFFFFF
        cursor = 0.0
        for variant in experiment.variants:
            cursor += variant.weight
            if bucket <= cursor:
                return variant
        return experiment.variants[-1] if experiment.variants else None

    async def _learn_from_feedback(self, tenant_id: str) -> AdaptiveThresholdResult | None:
        try:
            tenant_uuid = uuid.UUID(str(tenant_id))
        except ValueError:
            return None

        confirmed_result = await self._session.execute(
            select(ClusteringFeedback.similarity_at_decision)
            .where(ClusteringFeedback.tenant_id == tenant_uuid)
            .where(ClusteringFeedback.user_action == "confirmed")
            .where(ClusteringFeedback.decision_type == "suggest")
        )
        confirmed_sims = [row[0] for row in confirmed_result.all() if row[0] is not None]

        rejected_result = await self._session.execute(
            select(ClusteringFeedback.similarity_at_decision)
            .where(ClusteringFeedback.tenant_id == tenant_uuid)
            .where(ClusteringFeedback.user_action.in_(["rejected", "moved", "split"]))
        )
        rejected_sims = [row[0] for row in rejected_result.all() if row[0] is not None]

        if len(confirmed_sims) < 20 or len(rejected_sims) < 10:
            return None

        min_confirmed = min(confirmed_sims)
        max_rejected = max(rejected_sims)

        if min_confirmed > max_rejected:
            optimal = (min_confirmed + max_rejected) / 2
            confidence = (min_confirmed - max_rejected) / 0.3
        else:
            optimal = float(np.percentile(confirmed_sims, 10))
            confidence = 0.6

        return AdaptiveThresholdResult(
            threshold=float(np.clip(optimal, 0.60, 0.85)),
            source="tenant_learned",
            confidence=min(confidence, 1.0),
            sample_size=len(confirmed_sims) + len(rejected_sims),
        )
