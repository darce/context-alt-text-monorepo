from __future__ import annotations

import pytest
from fastapi import BackgroundTasks, HTTPException, Response

from recognition.interface_adapters.http.deps.auth import AuthContext
from recognition.interface_adapters.http.routers import clusters_topology
from recognition.interface_adapters.http.schemas.requests import (
    AssignOutlierRequest,
    CreateClusterForIdentityRequest,
    MergeClusterRequest,
    ReassignIdentityRequest,
    RevertMergeClusterRequest,
    SplitClusterRequest,
    SplitTopologyCommandRequest,
)

AUTHENTICATED_TENANT_ID = "00000000-0000-0000-0000-000000000001"
REQUEST_TENANT_ID = "00000000-0000-0000-0000-000000000002"
CLUSTER_ID = "00000000-0000-0000-0000-000000000003"
IDENTITY_ID = "00000000-0000-0000-0000-000000000004"
IDEMPOTENCY_KEY = "foreign-tenant-replay"


async def _invoke_handler(handler_name: str, auth: AuthContext) -> None:
    session = object()

    if handler_name == "create_cluster_for_identity":
        await clusters_topology.create_cluster_for_identity(
            request=CreateClusterForIdentityRequest(
                tenant_id=REQUEST_TENANT_ID,
                identity_id=IDENTITY_ID,
                label="private",
                idempotency_key=IDEMPOTENCY_KEY,
            ),
            auth=auth,
            session=session,
            cluster_service_builder=None,
        )
    elif handler_name == "merge_cluster":
        await clusters_topology.merge_cluster(
            cluster_id=CLUSTER_ID,
            request=MergeClusterRequest(
                tenant_id=REQUEST_TENANT_ID,
                target_cluster_id=IDENTITY_ID,
                idempotency_key=IDEMPOTENCY_KEY,
            ),
            background_tasks=BackgroundTasks(),
            auth=auth,
            session=session,
            cluster_service_builder=None,
            job_service=None,
        )
    elif handler_name == "split_cluster":
        await clusters_topology.split_cluster(
            cluster_id=CLUSTER_ID,
            request=SplitClusterRequest(tenant_id=REQUEST_TENANT_ID, idempotency_key=IDEMPOTENCY_KEY),
            response=Response(),
            auth=auth,
            session=session,
            cluster_service_builder=None,
            suggestion_refresh_service=None,
            job_service=None,
        )
    elif handler_name == "split_topology_command":
        await clusters_topology.split_topology_command(
            request=SplitTopologyCommandRequest(
                tenant_id=REQUEST_TENANT_ID,
                cluster_id=CLUSTER_ID,
                idempotency_key=IDEMPOTENCY_KEY,
            ),
            auth=auth,
            session=session,
            cluster_service_builder=None,
            cluster_repo=None,
        )
    elif handler_name == "reassign_identity":
        await clusters_topology.reassign_identity(
            request=ReassignIdentityRequest(
                tenant_id=REQUEST_TENANT_ID,
                identity_id=IDENTITY_ID,
                idempotency_key=IDEMPOTENCY_KEY,
            ),
            auth=auth,
            session=session,
            cluster_service_builder=None,
            suggestion_service=None,
            suggestion_refresh_service=None,
            job_service=None,
        )
    elif handler_name == "revert_merge_cluster":
        await clusters_topology.revert_merge_cluster(
            request=RevertMergeClusterRequest(
                tenant_id=REQUEST_TENANT_ID,
                target_cluster_id=CLUSTER_ID,
                moved_identity_ids=[IDENTITY_ID],
                idempotency_key=IDEMPOTENCY_KEY,
            ),
            auth=auth,
            session=session,
            cluster_service_builder=None,
        )
    elif handler_name == "assign_outlier":
        await clusters_topology.assign_outlier(
            cluster_id=CLUSTER_ID,
            request=AssignOutlierRequest(
                tenant_id=REQUEST_TENANT_ID,
                identity_id=IDENTITY_ID,
                idempotency_key=IDEMPOTENCY_KEY,
            ),
            auth=auth,
            session=session,
            cluster_service_builder=None,
            suggestion_refresh_service=None,
        )
    else:
        raise AssertionError(f"Unknown topology handler: {handler_name}")


@pytest.mark.parametrize(
    "handler_name",
    [
        "create_cluster_for_identity",
        "merge_cluster",
        "split_cluster",
        "split_topology_command",
        "reassign_identity",
        "revert_merge_cluster",
        "assign_outlier",
    ],
)
@pytest.mark.asyncio
async def test_topology_handlers_reject_foreign_tenant_before_replay_lookup(monkeypatch, handler_name: str) -> None:
    replay_lookups: list[tuple[str, str | None]] = []

    async def _record_replay_lookup(_session, tenant_id: str, idempotency_key: str | None):
        replay_lookups.append((tenant_id, idempotency_key))
        return None

    monkeypatch.setattr(clusters_topology, "_load_topology_replay", _record_replay_lookup)
    auth = AuthContext(token="test-token", tenant_claim=AUTHENTICATED_TENANT_ID, enabled=True)

    with pytest.raises(HTTPException) as exc_info:
        await _invoke_handler(handler_name, auth)

    assert exc_info.value.status_code == 403
    assert replay_lookups == []
