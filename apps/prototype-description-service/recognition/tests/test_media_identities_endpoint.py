"""Integration tests for GET /recognition/media/identities."""

from __future__ import annotations

from uuid import uuid4

import pytest

from db.models import IdentityCluster, IdentityMember, Tenant
from db.session import async_session_factory
from db.tenant_context import clear_tenant_context, set_tenant_context
from recognition.tests.fakes import make_media_identity

pytestmark = pytest.mark.usefixtures("require_database")


async def _ensure_tenant(tenant_id):
    async with async_session_factory() as session:
        session.add(Tenant(id=tenant_id, site_url=f"https://{tenant_id}.example.com"))
        await session.commit()


@pytest.mark.asyncio
async def test_media_identities_groups_by_media_and_marks_auto_labels(async_client):
    tenant_id = uuid4()
    media_id = 101
    other_media_id = 999

    await _ensure_tenant(tenant_id)

    async with async_session_factory() as session:
        await set_tenant_context(session, tenant_id)

        auto_cluster = IdentityCluster(tenant_id=tenant_id, label="cluster-5ab123", identity_count=1)
        named_cluster = IdentityCluster(tenant_id=tenant_id, label="Riley Chen", identity_count=1)
        session.add_all([auto_cluster, named_cluster])
        await session.flush()

        auto_identity = make_media_identity(tenant_id, media_id=media_id)
        named_identity = make_media_identity(tenant_id, media_id=media_id)
        # Ensure unique bounding boxes to satisfy unique_media_identity constraint
        named_identity.bbox_x = 20
        named_identity.bbox_y = 20
        session.add_all([auto_identity, named_identity])
        await session.flush()

        session.add_all(
            [
                IdentityMember(
                    tenant_id=tenant_id,
                    cluster_id=auto_cluster.id,
                    identity_id=auto_identity.id,
                    similarity=0.91,
                ),
                IdentityMember(
                    tenant_id=tenant_id,
                    cluster_id=named_cluster.id,
                    identity_id=named_identity.id,
                    similarity=0.83,
                ),
            ]
        )
        await session.commit()
        await clear_tenant_context(session)

    response = await async_client.get(
        "/recognition/media/identities",
        params=[("tenant_id", str(tenant_id)), ("media_ids", str(media_id)), ("media_ids", str(other_media_id))],
    )
    assert response.status_code == 200
    payload = response.json()

    assert str(media_id) in payload["identities_by_media"]
    media_entries = payload["identities_by_media"][str(media_id)]
    assert len(media_entries) == 2

    auto_entry = next(entry for entry in media_entries if entry["cluster_label"] == "cluster-5ab123")
    assert auto_entry["is_auto_label"] is True
    assert auto_entry["media_id"] == media_id
    assert auto_entry["similarity"] == pytest.approx(0.91, rel=1e-3)

    named_entry = next(entry for entry in media_entries if entry["cluster_label"] == "Riley Chen")
    assert named_entry["is_auto_label"] is False
    assert named_entry["cluster_id"] is not None

    assert payload["identities_by_media"][str(other_media_id)] == []


@pytest.mark.asyncio
async def test_media_identities_returns_unclustered_identities(async_client):
    tenant_id = uuid4()
    media_id = 321

    await _ensure_tenant(tenant_id)

    async with async_session_factory() as session:
        await set_tenant_context(session, tenant_id)
        identity = make_media_identity(tenant_id, media_id=media_id)
        session.add(identity)
        await session.commit()
        await clear_tenant_context(session)

    response = await async_client.get(
        "/recognition/media/identities",
        params=[("tenant_id", str(tenant_id)), ("media_ids", str(media_id))],
    )
    assert response.status_code == 200
    payload = response.json()

    entries = payload["identities_by_media"][str(media_id)]
    assert len(entries) == 1
    assert entries[0]["cluster_id"] is None
    assert entries[0]["cluster_label"] is None
    assert entries[0]["similarity"] is None


@pytest.mark.asyncio
async def test_media_identities_supports_bracket_query(async_client):
    tenant_id = uuid4()
    media_id = 555

    await _ensure_tenant(tenant_id)

    async with async_session_factory() as session:
        await set_tenant_context(session, tenant_id)
        identity = make_media_identity(tenant_id, media_id=media_id)
        session.add(identity)
        await session.commit()
        await clear_tenant_context(session)

    response = await async_client.get(
        "/recognition/media/identities",
        params=[("tenant_id", str(tenant_id)), ("media_ids[]", str(media_id))],
    )
    assert response.status_code == 200
    payload = response.json()
    assert str(media_id) in payload["identities_by_media"]
