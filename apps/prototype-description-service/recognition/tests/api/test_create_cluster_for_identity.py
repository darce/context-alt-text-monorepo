"""API contract tests for create-for-identity cluster endpoint."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

from recognition.domain.cluster import ReservedClusterLabelError
from recognition.interface_adapters.http.exception_handlers import register_exception_handlers


def test_create_cluster_for_identity(api_client, tenant_id: str) -> None:
    identity_id = str(uuid.uuid4())
    desired_cluster_id = str(uuid.uuid4())
    resp = api_client.post(
        "/recognition/clusters/create-for-identity",
        headers={"X-Tenant-ID": tenant_id},
        json={
            "tenant_id": tenant_id,
            "identity_id": identity_id,
            "label": "Muted Yarrow",
            "desired_cluster_id": desired_cluster_id,
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["identity_id"] == identity_id
    assert payload["label"] == "Muted Yarrow"
    assert payload["cluster_id"] == desired_cluster_id
    assert payload["message"]


def test_create_cluster_for_identity_rejects_reserved_label_with_400(
    api_client, tenant_id: str, fake_cluster_service
) -> None:
    """E21-17-R1-PY47-1: reserved labels must surface 400, not ValueError->404."""
    register_exception_handlers(api_client.app)
    fake_cluster_service.create_cluster_for_identity = AsyncMock(
        side_effect=ReservedClusterLabelError("cluster-x")
    )

    resp = api_client.post(
        "/recognition/clusters/create-for-identity",
        headers={"X-Tenant-ID": tenant_id},
        json={
            "tenant_id": tenant_id,
            "identity_id": str(uuid.uuid4()),
            "label": "cluster-x",
        },
    )

    assert resp.status_code == 400
    assert resp.json()["error"] == "ReservedClusterLabelError"
