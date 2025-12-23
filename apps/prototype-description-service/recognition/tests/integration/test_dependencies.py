"""Integration tests for dependency factories using the real session."""

from __future__ import annotations

import pytest

from recognition.application.assignment.checks import (
    BlockCheck,
    ConfidenceCheck,
    ConstraintCheck,
)
from recognition.application.orchestration import ClusterService
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.infrastructure.repositories import SqlAlchemyClusterRepository, SqlAlchemyMemberRepository
from recognition.interface_adapters.http import dependencies
from recognition.observability import ClusteringLogger


@pytest.mark.asyncio
async def test_build_cluster_service_wires_sqlalchemy_repositories(db_session, tenant) -> None:
    """build_cluster_service should create ClusterService with SQLAlchemy repos."""
    service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))

    assert isinstance(service, ClusterService)
    assert isinstance(service.assignment_writer, AssignmentWriter)
    assert isinstance(service.assignment_writer._clusters, SqlAlchemyClusterRepository)
    assert isinstance(service.assignment_writer._members, SqlAlchemyMemberRepository)
    assert isinstance(service.logger, ClusteringLogger)
    # Gate now uses simplified checks (MaturityCheck, CompleteLinkCheck, MemberDistributionCheck removed)
    assert {type(check) for check in service.gate.checks} == {
        BlockCheck,
        ConfidenceCheck,
        ConstraintCheck,
    }


@pytest.mark.asyncio
async def test_get_cluster_service_uses_sqlalchemy_factory(db_session, tenant) -> None:
    """Primary dependency should build a SQLAlchemy-backed ClusterService."""
    service = await dependencies.get_cluster_service(session=db_session, tenant_id=str(tenant.id))

    assert isinstance(service, ClusterService)
    assert isinstance(service.assignment_writer._clusters, SqlAlchemyClusterRepository)
    assert isinstance(service.assignment_writer._members, SqlAlchemyMemberRepository)
