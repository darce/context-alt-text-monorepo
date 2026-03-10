"""API contract tests for create-for-identity cluster endpoint."""

from __future__ import annotations

import uuid


def test_create_cluster_for_identity(api_client, tenant_id: str) -> None:
    identity_id = str(uuid.uuid4())
    desired_cluster_id = str(uuid.uuid4())
    resp = api_client.post(
        "/recognition/clusters/create-for-identity",
        headers={"X-Tenant-ID": tenant_id},
        json={
            "tenant_id": tenant_id,
            "identity_id": identity_id,
            "label": "Ryann Wiseman",
            "desired_cluster_id": desired_cluster_id,
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["identity_id"] == identity_id
    assert payload["label"] == "Ryann Wiseman"
    assert payload["cluster_id"] == desired_cluster_id
    assert payload["message"]
