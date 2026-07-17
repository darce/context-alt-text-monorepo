"""Slice 1: load_confirmed_faces — read-only identity join with the five filters."""

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import Table, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from db.models.base_imports import _DB_SETTINGS, Base
from db.models.identity import IdentityCluster, IdentityMember, MediaIdentity
from db.models.tenant import Tenant
from scene.application.identity_merge import load_confirmed_faces

MEDIA_ID = 7001
IMAGE_W = 1000
IMAGE_H = 500


def _embedding() -> list[float]:
    return [1.0] + [0.0] * (_DB_SETTINGS.pgvector_dimension - 1)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                Table("tenants", Base.metadata),
                Table("media_identities", Base.metadata),
                Table("identity_clusters", Base.metadata),
                Table("identity_members", Base.metadata),
            ],
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _identity(tenant_id, *, media_id=MEDIA_ID, bbox=(100, 50, 60, 80), confidence=0.97):
    x, y, w, h = bbox
    return MediaIdentity(
        tenant_id=tenant_id,
        media_id=media_id,
        media_url=f"http://test.local/{media_id}.jpg",
        bbox_x=x,
        bbox_y=y,
        bbox_width=w,
        bbox_height=h,
        confidence=confidence,
        embedding=_embedding(),
        embedding_model="buffalo_l@insightface",
    )


def _cluster(tenant_id, *, label, user_confirmed=True, dismissed=False, roster_id=None):
    return IdentityCluster(
        tenant_id=tenant_id,
        label=label,
        user_confirmed=user_confirmed,
        roster_id=roster_id,
        dismissed_at=datetime.now(tz=UTC) if dismissed else None,
    )


async def _link(session, tenant_id, identity, cluster, *, similarity=0.9):
    session.add_all([identity, cluster])
    await session.flush()
    session.add(
        IdentityMember(
            tenant_id=tenant_id,
            cluster_id=cluster.id,
            identity_id=identity.id,
            similarity=similarity,
        )
    )


@pytest_asyncio.fixture
async def tenant(session):
    row = Tenant(id=uuid.uuid4(), site_url="http://join-test.local")
    session.add(row)
    await session.flush()
    return row


@pytest.mark.asyncio
async def test_confirmed_labeled_face_is_returned_normalized(session, tenant):
    roster = uuid.uuid4()
    identity = _identity(tenant.id, bbox=(100, 50, 60, 80))
    cluster = _cluster(tenant.id, label="Daniel", roster_id=roster)
    await _link(session, tenant.id, identity, cluster)
    await session.commit()

    faces = await load_confirmed_faces(
        session, tenant_id=tenant.id, media_id=MEDIA_ID, image_width=IMAGE_W, image_height=IMAGE_H
    )
    assert len(faces) == 1
    face = faces[0]
    assert face.label == "Daniel"
    assert face.roster_id == roster
    assert face.cluster_id == cluster.id
    assert face.box.x == pytest.approx(0.1)
    assert face.box.y == pytest.approx(0.1)
    assert face.box.width == pytest.approx(0.06)
    assert face.box.height == pytest.approx(0.16)


@pytest.mark.asyncio
async def test_filters_exclude_ineligible_rows(session, tenant):
    await _link(session, tenant.id, _identity(tenant.id), _cluster(tenant.id, label="Confirmed OK"))
    await _link(
        session,
        tenant.id,
        _identity(tenant.id, bbox=(1, 1, 10, 10)),
        _cluster(tenant.id, label="Unconfirmed", user_confirmed=False),
    )
    await _link(
        session,
        tenant.id,
        _identity(tenant.id, bbox=(2, 2, 10, 10)),
        _cluster(tenant.id, label="cluster-3"),  # placeholder label
    )
    await _link(
        session,
        tenant.id,
        _identity(tenant.id, bbox=(3, 3, 10, 10)),
        _cluster(tenant.id, label="Dismissed", dismissed=True),
    )
    await _link(
        session,
        tenant.id,
        _identity(tenant.id, bbox=(4, 4, 10, 10)),
        _cluster(tenant.id, label=None, user_confirmed=True),
    )
    await _link(
        session,
        tenant.id,
        _identity(tenant.id, media_id=MEDIA_ID + 1, bbox=(5, 5, 10, 10)),
        _cluster(tenant.id, label="Other Media"),
    )
    await session.commit()

    faces = await load_confirmed_faces(
        session, tenant_id=tenant.id, media_id=MEDIA_ID, image_width=IMAGE_W, image_height=IMAGE_H
    )
    assert [f.label for f in faces] == ["Confirmed OK"]
