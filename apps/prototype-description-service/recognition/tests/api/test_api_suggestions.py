"""API contract tests for suggestion endpoints."""

from __future__ import annotations

import uuid

import pytest


def test_list_suggestions_empty_by_default(api_client, tenant_id) -> None:
    resp = api_client.get(
        f"/recognition/identities/{uuid.uuid4()}/suggestions",
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_accept_and_reject_suggestion(api_client, tenant_id, fake_suggestion_service) -> None:
    identity_id = str(uuid.uuid4())
    suggestion = await fake_suggestion_service.create(identity_id=identity_id, cluster_id=str(uuid.uuid4()))

    accept_resp = api_client.post(
        f"/recognition/suggestions/{suggestion.id}/accept",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id},
    )
    assert accept_resp.status_code == 200
    assert accept_resp.json()["status"] == "accepted"

    second = await fake_suggestion_service.create(
        identity_id=str(uuid.uuid4()),
        cluster_id=str(uuid.uuid4()),
    )
    reject_resp = api_client.post(
        f"/recognition/suggestions/{second.id}/reject",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id},
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == "rejected"


def test_accept_missing_suggestion_returns_404(api_client, tenant_id) -> None:
    resp = api_client.post(
        "/recognition/suggestions/missing-id/accept",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id},
    )

    assert resp.status_code == 404
