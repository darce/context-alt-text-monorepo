"""Cluster row locks must not attempt to lock the nullable centroid join."""

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from recognition.application.orchestration.cluster_merge import (
    _lock_merge_clusters,
    _lock_survivor_cluster,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("revert", [False, True])
async def test_cluster_lock_is_valid_with_optional_centroid_join(revert: bool) -> None:
    session = AsyncMock()
    tenant = UUID(int=1)
    survivor = UUID(int=2)
    if revert:
        await _lock_survivor_cluster(session, tenant_id=tenant, survivor_cluster_id=survivor)
    else:
        await _lock_merge_clusters(session, tenant_id=tenant, cluster_ids=[UUID(int=3), survivor])

    statement = session.execute.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    # The ORM eagerly joins centroid data. PostgreSQL forbids an unqualified
    # FOR UPDATE here because the centroid is the nullable side of that join.
    assert "LEFT OUTER JOIN mv_identity_cluster_centroids" in sql
    assert sql.endswith("FOR UPDATE OF identity_clusters")
    assert statement.get_execution_options()["populate_existing"] is True
