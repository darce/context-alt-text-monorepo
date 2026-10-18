"""
Persistence helpers for observability artifacts (decisions and batch reports).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AssignmentDecision, ClusteringJobReport
from recognition.observability.decisions import DecisionLog
from recognition.observability.reports import BatchJobReport
from recognition.shared.ids import parse_optional_uuid


class ObservabilityRepository:
    """Data access layer for observability outputs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_batch_report(self, report: BatchJobReport, tenant_id: str) -> ClusteringJobReport:
        """Persist a clustering batch report (tenant required: FORCE-RLS table)."""
        payload = json.loads(report.to_json())
        row = ClusteringJobReport(
            tenant_id=parse_optional_uuid(tenant_id),
            job_id=str(report.job_id),
            algorithm=report.algorithm,
            started_at=report.started_at,
            completed_at=report.completed_at,
            total_identities=report.total_identities,
            accept_count=report.accept_count,
            suggest_count=report.suggest_count,
            reject_count=report.reject_count,
            clusters_created=report.clusters_created,
            avg_similarity=report.avg_similarity,
            success_rate=report.success_rate(),
            duration_ms=report.duration_ms(),
            payload=payload,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def add_decision(
        self,
        decision: DecisionLog,
        *,
        tenant_id: str,
        algorithm: str | None = None,
        job_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AssignmentDecision:
        """Persist a single decision log (tenant required: FORCE-RLS table)."""
        row = AssignmentDecision(
            tenant_id=parse_optional_uuid(tenant_id),
            identity_id=str(decision.identity_id),
            cluster_id=str(decision.cluster_id) if decision.cluster_id else None,
            decision=decision.decision.value,
            similarity=decision.similarity,
            reason=decision.reason,
            algorithm=algorithm,
            job_id=job_id,
            metadata_json=metadata,
            timestamp=decision.timestamp,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_decisions(
        self,
        *,
        tenant_id: str | None = None,
        outcome: str | None = None,
        cluster_id: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query persisted decision logs with filters."""
        parsed_tenant = parse_optional_uuid(tenant_id)
        stmt = select(AssignmentDecision)
        if parsed_tenant:
            stmt = stmt.where(AssignmentDecision.tenant_id == parsed_tenant)
        if outcome:
            stmt = stmt.where(AssignmentDecision.decision == outcome)
        if cluster_id:
            stmt = stmt.where(AssignmentDecision.cluster_id == cluster_id)
        if start_at:
            stmt = stmt.where(AssignmentDecision.timestamp >= start_at)
        if end_at:
            stmt = stmt.where(AssignmentDecision.timestamp <= end_at)
        stmt = stmt.order_by(AssignmentDecision.timestamp.desc()).offset(offset).limit(limit)

        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._row_to_dict(row) for row in rows]

    @staticmethod
    def _row_to_dict(row: AssignmentDecision) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id) if row.tenant_id else None,
            "identity_id": row.identity_id,
            "cluster_id": row.cluster_id,
            "decision": row.decision,
            "similarity": row.similarity,
            "reason": row.reason,
            "algorithm": row.algorithm,
            "job_id": row.job_id,
            "metadata": row.metadata_json or {},
            "timestamp": row.timestamp.isoformat(),
        }


__all__ = ["ObservabilityRepository"]
