"""Integration tests for tenant scoping using the real database session."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from db.models import IdentityCluster, Tenant
from recognition.domain.cluster import IdentityCluster as DomainCluster
from recognition.domain.repositories import SuggestionCreateData
from recognition.infrastructure.repositories import SqlAlchemyClusterRepository, SqlAlchemySuggestionRepository
from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http import router as recognition_router


def _make_client(session_override=None) -> TestClient:
    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    if session_override is not None:

        async def _session_dep():
            session_obj = session_override() if callable(session_override) else session_override
            if hasattr(session_obj, "__aiter__"):
                async for item in session_obj:
                    yield item
                return
            yield session_obj

        app.dependency_overrides[dependencies.get_session] = _session_dep
        app.dependency_overrides[dependencies.get_optional_session] = _session_dep
    return TestClient(app)


@pytest.mark.asyncio
async def test_tenant_cannot_query_other_clusters(db_session, tenant) -> None:
    """Tenant-scoped queries should not return clusters for other tenants."""
    other_tenant = Tenant(site_url="http://other.test")
    db_session.add(other_tenant)
    await db_session.commit()
    await db_session.refresh(other_tenant)

    db_session.add(
        IdentityCluster(
            id=uuid.uuid4(),
            tenant_id=other_tenant.id,
            label="other",
            identity_count=0,
        )
    )
    await db_session.commit()

    client = _make_client(session_override=lambda: db_session)
    resp = client.get(
        "/recognition/clusters", headers={"X-Tenant-ID": str(tenant.id)}, params={"tenant_id": str(tenant.id)}
    )

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_suggestions_are_tenant_scoped(db_session, tenant) -> None:
    """Suggestions for tenant A should not be visible or mutable by tenant B."""
    tenant_a = str(tenant.id)
    tenant_b = str(uuid.uuid4())

    cluster_repo = SqlAlchemyClusterRepository(db_session)
    cluster = await cluster_repo.save(
        DomainCluster(
            id=None,
            tenant_id=tenant_a,
            label="tenant-a-cluster",
            is_labeled=False,
            member_count=0,
            created_at=None,
        )
    )

    sugg_repo_a = SqlAlchemySuggestionRepository(db_session, tenant_id=tenant_a)
    suggestion = await sugg_repo_a.create(
        tenant_a,
        SuggestionCreateData(
            identity_id=str(uuid.uuid4()),
            cluster_id=cluster.id,
            representative_similarity=0.9,
            member_similarity=0.8,
            confidence_score=0.9,
        ),
    )

    client = _make_client(session_override=lambda: db_session)

    resp_list = client.get(
        f"/recognition/identities/{uuid.uuid4()}/suggestions",
        headers={"X-Tenant-ID": tenant_b},
    )
    assert resp_list.status_code == 200
    assert resp_list.json() == []

    resp_accept = client.post(
        f"/recognition/suggestions/{suggestion.id}/accept",
        headers={"X-Tenant-ID": tenant_b},
        json={"tenant_id": tenant_b},
    )
    assert resp_accept.status_code == 404
