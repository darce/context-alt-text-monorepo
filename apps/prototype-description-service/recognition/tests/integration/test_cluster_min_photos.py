"""FG6 listing behavior through the actual SQL repository, without inference."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event

from db.models import IdentityCluster, IdentityMember, MediaIdentity, Tenant
from db.settings import get_database_settings
from recognition.application.orchestration.curation.cluster_queries import list_clusters
from recognition.infrastructure.repositories import SqlAlchemyClusterRepository


async def seed_cluster(session, tenant_id, photos=(), *, number=None, label=None, confirmed=False, algorithm="graph"):
    cluster = IdentityCluster(
        id=uuid.UUID(int=number) if number is not None else uuid.uuid4(),
        tenant_id=tenant_id,
        label=label,
        user_confirmed=confirmed,
        # Deliberately unrelated to the actual photo population.
        identity_count=91,
        clustering_algorithm=algorithm,
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    session.add(cluster)
    await session.flush()
    for index, photo in enumerate(photos):
        identity = await seed_identity(session, tenant_id, photo, index)
        session.add(IdentityMember(tenant_id=tenant_id, cluster_id=cluster.id, identity_id=identity.id, similarity=0.9))
    await session.flush()
    return cluster


async def seed_identity(session, tenant_id, photo, position=0):
    dimension = get_database_settings().pgvector_dimension
    identity = MediaIdentity(
        tenant_id=tenant_id,
        media_id=photo,
        media_url=f"https://example.test/{photo}.jpg",
        bbox_x=position,
        bbox_y=0,
        bbox_width=10,
        bbox_height=10,
        confidence=0.9,
        embedding=[1.0] + [0.0] * (dimension - 1),
        embedding_model="fg6-fixture",
    )
    session.add(identity)
    await session.flush()
    return identity


@pytest.mark.asyncio
async def test_distinct_photos_boundary_and_unfiltered_zero_member(db_session, tenant):
    duplicate = await seed_cluster(db_session, tenant.id, [10, 10, 20])
    singleton = await seed_cluster(db_session, tenant.id, [30])
    empty = await seed_cluster(db_session, tenant.id)
    repo = SqlAlchemyClusterRepository(db_session)

    rows = await repo.get_by_tenant(str(tenant.id))
    assert {row.id: row.photo_count for row in rows} == {
        str(duplicate.id): 2,
        str(singleton.id): 1,
        str(empty.id): 0,
    }
    rows = await repo.get_by_tenant(str(tenant.id), min_photos=2)
    assert [(row.id, row.photo_count) for row in rows] == [(str(duplicate.id), 2)]
    assert await repo.get_by_tenant(str(tenant.id), min_photos=3) == []
    assert len(await repo.get_by_tenant(str(tenant.id), min_photos=1)) == 2


@pytest.mark.asyncio
async def test_count_rejects_both_cross_tenant_member_join_directions(db_session, tenant):
    other = Tenant(site_url="https://other.test")
    db_session.add(other)
    await db_session.flush()
    own = await seed_cluster(db_session, tenant.id, [10])
    foreign = await seed_cluster(db_session, other.id, [10, 20, 30])
    # Both corrupt joins satisfy ordinary single-column FKs. Neither may count.
    foreign_identity = await seed_identity(db_session, other.id, 40)
    own_identity = await seed_identity(db_session, tenant.id, 50)
    db_session.add_all(
        [
            IdentityMember(tenant_id=tenant.id, cluster_id=own.id, identity_id=foreign_identity.id, similarity=0.8),
            IdentityMember(tenant_id=other.id, cluster_id=own.id, identity_id=own_identity.id, similarity=0.8),
        ]
    )
    await db_session.flush()
    repo = SqlAlchemyClusterRepository(db_session)
    rows = await repo.get_by_tenant(str(tenant.id))
    assert [(row.id, row.photo_count) for row in rows] == [(str(own.id), 1)]
    assert await repo.get_by_tenant(str(tenant.id), min_photos=2) == []
    rows = await repo.get_by_tenant(str(other.id), min_photos=3)
    assert [(row.id, row.photo_count) for row in rows] == [(str(foreign.id), 3)]


@pytest.mark.asyncio
async def test_filter_before_offset_and_deterministic_created_at_ties(db_session, tenant):
    # Insertion order differs from the declared tie order. Small rows separate matches.
    for number, photos in [(4, [40, 41, 42]), (3, [30]), (2, [20, 21]), (1, [10])]:
        await seed_cluster(db_session, tenant.id, photos, number=number)
    repo = SqlAlchemyClusterRepository(db_session)
    first = await repo.get_by_tenant(str(tenant.id), min_photos=2, limit=1)
    second = await repo.get_by_tenant(str(tenant.id), min_photos=2, limit=1, offset=1)
    assert [row.id for row in first + second] == [str(uuid.UUID(int=2)), str(uuid.UUID(int=4))]
    assert await repo.get_by_tenant(str(tenant.id), min_photos=2, limit=1, offset=2) == []
    assert [row.id for row in await repo.get_by_tenant(str(tenant.id), min_photos=2)] == [
        row.id for row in first + second
    ]


@pytest.mark.asyncio
async def test_search_labeled_and_minimum_intersect(db_session, tenant):
    selected = await seed_cluster(db_session, tenant.id, [10, 11], label="Alice_%", confirmed=True)
    await seed_cluster(db_session, tenant.id, [20], label="Alice_% one-photo", confirmed=True)
    await seed_cluster(db_session, tenant.id, [30, 31], label="Alice_% unconfirmed", confirmed=False)
    await seed_cluster(db_session, tenant.id, [40, 41], label="AliceXX", confirmed=True)
    repo = SqlAlchemyClusterRepository(db_session)
    rows = await repo.get_by_tenant(str(tenant.id), min_photos=2, labeled_only=True, search="alice_%")
    assert [row.id for row in rows] == [str(selected.id)]
    assert len(await repo.get_by_tenant(str(tenant.id), labeled_only=True, search="alice_%")) == 2
    assert len(await repo.get_by_tenant(str(tenant.id), min_photos=2, search="alice_%")) == 2


@pytest.mark.asyncio
async def test_minimum_requires_complete_photo_ids_before_paging(db_session, tenant):
    other = Tenant(site_url="https://other.test")
    db_session.add(other)
    await db_session.flush()
    # media_id 0 is accepted input and has no positive CHECK; it is not a known photo.
    incomplete = await seed_cluster(db_session, tenant.id, [0, 55], number=1, label="Alice zero", confirmed=True)
    complete = await seed_cluster(db_session, tenant.id, [55, 56], number=2, label="Alice", confirmed=True)
    repeated = await seed_cluster(db_session, tenant.id, [57, 57], number=3)
    foreign = await seed_cluster(db_session, tenant.id, [58], number=4)
    foreign_identity = await seed_identity(db_session, other.id, 59)
    db_session.add(
        IdentityMember(tenant_id=tenant.id, cluster_id=foreign.id, identity_id=foreign_identity.id, similarity=0.8)
    )
    await db_session.flush()
    repo = SqlAlchemyClusterRepository(db_session)

    async def listed(**kwargs):
        return [(row.id, row.photo_count) for row in await repo.get_by_tenant(str(tenant.id), **kwargs)]

    assert await listed(min_photos=2) == [(str(complete.id), 2)]
    # Unknown counts cannot match, so no page publishes them as known photos.
    assert await listed(min_photos=1) == [(str(complete.id), 2), (str(repeated.id), 1)]
    assert await listed(min_photos=1, limit=1, offset=1) == [(str(repeated.id), 1)]
    assert await listed(min_photos=1, labeled_only=True, search="alice") == [(str(complete.id), 2)]
    assert {row_id for row_id, _ in await listed()} == {str(c.id) for c in (incomplete, complete, repeated, foreign)}


@pytest.mark.asyncio
async def test_synthetic_outlier_omitted_only_when_minimum_requested(db_session, tenant):
    real = await seed_cluster(db_session, tenant.id, [10, 11])
    stored_noise = await seed_cluster(db_session, tenant.id, [20], label="noise", algorithm="outlier")
    await seed_identity(db_session, tenant.id, 99)
    repo = SqlAlchemyClusterRepository(db_session)
    kwargs = {"cluster_repo": repo, "session": db_session, "tenant_id": str(tenant.id)}
    default = await list_clusters(**kwargs)
    assert [row.id for row in default] == [str(real.id)]
    unfiltered = await list_clusters(**kwargs, include_outliers=True)
    assert {row.id for row in unfiltered} == {str(real.id), str(stored_noise.id), f"outliers-{tenant.id}"}
    filtered = await list_clusters(**kwargs, include_outliers=True, min_photos=1)
    assert {row.id for row in filtered} == {str(real.id), str(stored_noise.id)}
    assert [row.id for row in await list_clusters(**kwargs, min_photos=1)] == [str(real.id)]


@pytest.mark.asyncio
async def test_listing_query_budget_does_not_grow_per_cluster(db_session, tenant):
    repo = SqlAlchemyClusterRepository(db_session)
    await seed_cluster(db_session, tenant.id, [10])
    statements = []

    def record(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(db_session.bind.sync_engine, "before_cursor_execute", record)
    try:
        one = await repo.get_by_tenant(str(tenant.id), min_photos=1)
        small_budget = len(statements)
        for photo in range(20, 25):
            await seed_cluster(db_session, tenant.id, [photo])
        statements.clear()
        many = await repo.get_by_tenant(str(tenant.id), min_photos=1)
        assert len(many) == 6 and one[0].photo_count == 1
        assert len(statements) == small_budget
        assert len(statements) <= 4  # Listing plus bounded eager relation loads, never per-row counts.
    finally:
        event.remove(db_session.bind.sync_engine, "before_cursor_execute", record)


@pytest.mark.asyncio
async def test_authenticated_api_serializes_actual_sql_count(db_session, tenant, cluster_service):
    import httpx
    from fastapi import FastAPI

    from recognition.interface_adapters.http.deps import get_cluster_service_builder, require_auth
    from recognition.interface_adapters.http.deps.auth import AuthContext
    from recognition.interface_adapters.http.routers.clusters_snapshot import router

    selected = await seed_cluster(db_session, tenant.id, [10, 10, 20], label="Alice", confirmed=True)
    await seed_cluster(db_session, tenant.id, [30], label="Alice single-photo", confirmed=True)
    app = FastAPI()
    app.include_router(router, prefix="/recognition")

    async def authenticated():
        return AuthContext(token=None, tenant_claim=str(tenant.id), enabled=True, is_admin=True)

    app.dependency_overrides[require_auth] = authenticated

    async def build(tenant_id):
        assert tenant_id == str(tenant.id)
        return cluster_service

    async def builder():
        return build

    app.dependency_overrides[get_cluster_service_builder] = builder
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fg6.test") as client:
        response = await client.get("/recognition/clusters", params={"min_photos": 2, "labeled_only": True})
    assert response.status_code == 200
    assert [(row["id"], row["photo_count"]) for row in response.json()] == [(str(selected.id), 2)]


@pytest.fixture
def fg6_postgres_engine(request):
    """Opt-in only: reuse the existing migrated scratch DB and role checks."""
    import os
    from urllib.parse import urlsplit

    if os.environ.get("FG6_POSTGRES_CHECK") != "1":
        pytest.skip("Set FG6_POSTGRES_CHECK=1 for the disposable local Postgres check")
    for variable in ("IDENTITY_PG_TEST_URL", "IDENTITY_PG_ADMIN_URL"):
        url = os.environ.get(variable, "")
        assert urlsplit(url).hostname in {"localhost", "127.0.0.1", "::1"}, f"{variable} must be explicit loopback"
    assert "fg6_scratch" in urlsplit(os.environ["IDENTITY_PG_TEST_URL"]).path
    return request.getfixturevalue("pg_isolated_migrated_engine")


@pytest.mark.pg
@pytest.mark.asyncio
async def test_min_photos_on_ephemeral_postgres(fg6_postgres_engine):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(fg6_postgres_engine.url.set(drivername="postgresql+asyncpg"))
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            tenant = Tenant(site_url="https://fg6-pg.test")
            session.add(tenant)
            await session.flush()
            await session.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"), {"tenant": str(tenant.id)}
            )
            for number, photos in [(4, [40, 41]), (3, [30]), (2, [20, 20, 21]), (1, [])]:
                await seed_cluster(session, tenant.id, photos, number=number)
            repo = SqlAlchemyClusterRepository(session)
            rows = await repo.get_by_tenant(str(tenant.id), min_photos=2, limit=1, offset=1)
            assert [(row.id, row.photo_count) for row in rows] == [(str(uuid.UUID(int=4)), 2)]
            assert {row.photo_count for row in await repo.get_by_tenant(str(tenant.id))} == {0, 1, 2}
            await session.rollback()
    finally:
        await engine.dispose()
