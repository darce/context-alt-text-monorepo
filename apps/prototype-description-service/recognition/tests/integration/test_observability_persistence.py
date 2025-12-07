"""Observability persistence integration tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from db.models import AssignmentDecision, ClusteringJobReport
from recognition.observability.decisions import DecisionLog, DecisionType
from recognition.observability.persistence import ObservabilityRepository
from recognition.observability.reports import BatchJobReport
from recognition.shared.ids import generate_id


@pytest.mark.asyncio
async def test_batch_job_report_is_persisted(db_session, tenant) -> None:
    repo = ObservabilityRepository(db_session)
    started_at = datetime.now(tz=UTC)
    completed_at = started_at + timedelta(seconds=2)
    report = BatchJobReport(
        job_id=str(generate_id()),
        algorithm="hdbscan",
        started_at=started_at,
        completed_at=completed_at,
        total_identities=3,
        accept_count=2,
        suggest_count=1,
        reject_count=0,
        clusters_created=1,
        avg_similarity=0.9,
    )

    await repo.save_batch_report(report, tenant_id=str(tenant.id))
    rows = (await db_session.execute(select(ClusteringJobReport))).scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.job_id == report.job_id
    assert row.tenant_id == tenant.id
    assert row.payload.get("total_identities") == report.total_identities
    assert row.duration_ms >= 0
    assert row.success_rate == report.success_rate()


@pytest.mark.asyncio
async def test_assignment_decisions_are_queryable(db_session, tenant) -> None:
    repo = ObservabilityRepository(db_session)
    now = datetime.now(tz=UTC)
    decision_recent = DecisionLog(
        identity_id="identity-1",
        cluster_id="cluster-1",
        decision=DecisionType.REJECT,
        similarity=0.4,
        reason="low_similarity",
        timestamp=now,
    )
    decision_old = DecisionLog(
        identity_id="identity-2",
        cluster_id="cluster-2",
        decision=DecisionType.ACCEPT,
        similarity=0.92,
        reason="high_similarity",
        timestamp=now - timedelta(days=2),
    )
    await repo.add_decision(decision_old, tenant_id=str(tenant.id))
    await repo.add_decision(decision_recent, tenant_id=str(tenant.id))
    await repo.add_decision(
        DecisionLog(
            identity_id="identity-3",
            cluster_id="cluster-1",
            decision=DecisionType.REJECT,
            similarity=0.1,
            reason="other_tenant",
            timestamp=now,
        ),
        tenant_id="other-tenant",
    )

    results = await repo.list_decisions(
        tenant_id=str(tenant.id),
        outcome="reject",
        cluster_id="cluster-1",
        start_at=now - timedelta(hours=1),
        limit=1,
        offset=0,
    )

    assert len(results) == 1
    assert results[0]["identity_id"] == "identity-1"
    stored_rows = (await db_session.execute(select(AssignmentDecision))).scalars().all()
    assert len(stored_rows) == 3
