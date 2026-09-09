"""CVUP1-R3-17: post_merge_retry_matching must stay inside one embedding space."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import numpy as np
import pytest

from recognition.application.assignment import AssignmentDecision, AssignmentOutcome
from recognition.application.identity_mapping import media_identity_from_model
from recognition.application.orchestration.cluster_merge import post_merge_retry_matching
from recognition.domain.representative import ClusterRepresentative
from recognition.domain.suggestion import AssignmentSuggestion, SuggestionStatus


def _unit(vec: list[float]) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    return arr / float(np.linalg.norm(arr))


def _rep(cluster_id: str, model: str | None) -> ClusterRepresentative:
    return ClusterRepresentative(
        id=str(uuid4()),
        cluster_id=cluster_id,
        identity_id=str(uuid4()),
        embedding=_unit([1.0, 0.0]),
        created_at=datetime.now(tz=UTC),
        embedding_model=model,
    )


def _orm_identity(*, tenant_id: str, model: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        media_id="media-1",
        embedding=_unit([1.0, 0.0]),
        confidence=0.99,
        bbox_width=10,
        bbox_height=10,
        bbox_x=0,
        bbox_y=0,
        pose_pitch=None,
        pose_yaw=None,
        pose_roll=None,
        image_phash=None,
        sharpness=None,
        embedding_norm=None,
        occlusion_severity=None,
        moved_by_merge_id=None,
        embedding_model=model,
    )


def _session_with_unclustered(models: list[SimpleNamespace]) -> AsyncMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = models
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


async def _accept(candidate):  # noqa: ANN001
    return AssignmentDecision(
        outcome=AssignmentOutcome.ACCEPT,
        candidate=candidate,
        checks_passed=["confidence_check"],
        checks_failed=[],
    )


def _harness(*, reps: list[ClusterRepresentative], unclustered: list[SimpleNamespace], tenant_id: str, cluster_id: str):
    persist = AsyncMock()
    evaluate = AsyncMock(side_effect=_accept)
    assignment_writer = SimpleNamespace(
        cluster_repository=SimpleNamespace(
            get_all_representatives=AsyncMock(return_value=reps),
            get_unclustered_in_embedding_space=AsyncMock(
                return_value=[media_identity_from_model(model) for model in unclustered]
            ),
        ),
        member_repository=SimpleNamespace(get_by_identity_id=AsyncMock(return_value=[])),
        persist_assignment=persist,
    )
    gate = SimpleNamespace(
        settings=SimpleNamespace(similarity_threshold=0.5),
        evaluate=evaluate,
    )
    suggestion_service = SimpleNamespace(
        get_by_cluster=AsyncMock(return_value=[]),
        create=AsyncMock(),
        resolve_for_identity=AsyncMock(),
        update_scores=AsyncMock(),
    )
    return persist, evaluate, assignment_writer, gate, suggestion_service, _session_with_unclustered(unclustered)


@pytest.mark.asyncio
async def test_post_merge_retry_scores_same_space_unclustered() -> None:
    tenant_id = str(uuid4())
    cluster_id = str(uuid4())
    persist, evaluate, writer, gate, suggestions, session = _harness(
        reps=[_rep(cluster_id, "space-a")],
        unclustered=[_orm_identity(tenant_id=tenant_id, model="space-a")],
        tenant_id=tenant_id,
        cluster_id=cluster_id,
    )

    await post_merge_retry_matching(
        tenant_id=tenant_id,
        target_cluster_id=cluster_id,
        session=session,
        gate=gate,
        assignment_writer=writer,
        suggestion_service=suggestions,
        max_unclustered=10,
        min_similarity_for_unclustered=0.5,
    )

    evaluate.assert_awaited()
    persist.assert_awaited()


@pytest.mark.asyncio
async def test_post_merge_retry_skips_foreign_space_even_when_cosine_is_high() -> None:
    tenant_id = str(uuid4())
    cluster_id = str(uuid4())
    persist, evaluate, writer, gate, suggestions, session = _harness(
        reps=[_rep(cluster_id, "space-a")],
        unclustered=[_orm_identity(tenant_id=tenant_id, model="space-b")],
        tenant_id=tenant_id,
        cluster_id=cluster_id,
    )

    await post_merge_retry_matching(
        tenant_id=tenant_id,
        target_cluster_id=cluster_id,
        session=session,
        gate=gate,
        assignment_writer=writer,
        suggestion_service=suggestions,
        max_unclustered=10,
        min_similarity_for_unclustered=0.5,
    )

    evaluate.assert_not_awaited()
    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_post_merge_retry_rejects_pending_foreign_space_suggestion() -> None:
    tenant_id = str(uuid4())
    cluster_id = str(uuid4())
    identity_id = str(uuid4())
    suggestion = AssignmentSuggestion(
        id=str(uuid4()),
        identity_id=identity_id,
        cluster_id=cluster_id,
        representative_similarity=0.99,
        member_similarity=0.99,
        status=SuggestionStatus.PENDING,
    )
    model = _orm_identity(tenant_id=tenant_id, model="space-b")
    model.id = uuid4()
    model.id = identity_id
    persist, evaluate, writer, gate, suggestions, session = _harness(
        reps=[_rep(cluster_id, "space-a")],
        unclustered=[],
        tenant_id=tenant_id,
        cluster_id=cluster_id,
    )
    suggestions.get_by_cluster = AsyncMock(return_value=[suggestion])
    session.get = AsyncMock(return_value=model)

    await post_merge_retry_matching(
        tenant_id=tenant_id,
        target_cluster_id=cluster_id,
        session=session,
        gate=gate,
        assignment_writer=writer,
        suggestion_service=suggestions,
        max_unclustered=10,
        min_similarity_for_unclustered=0.5,
    )

    suggestions.resolve_for_identity.assert_awaited_once_with(
        identity_id,
        cluster_id,
        resolution="rejected",
    )
    evaluate.assert_not_awaited()
    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_post_merge_retry_unstamped_gallery_matches_unstamped_probe() -> None:
    tenant_id = str(uuid4())
    cluster_id = str(uuid4())
    persist, evaluate, writer, gate, suggestions, session = _harness(
        reps=[_rep(cluster_id, None)],
        unclustered=[_orm_identity(tenant_id=tenant_id, model=None)],
        tenant_id=tenant_id,
        cluster_id=cluster_id,
    )

    await post_merge_retry_matching(
        tenant_id=tenant_id,
        target_cluster_id=cluster_id,
        session=session,
        gate=gate,
        assignment_writer=writer,
        suggestion_service=suggestions,
        max_unclustered=10,
        min_similarity_for_unclustered=0.5,
    )

    evaluate.assert_awaited()
    persist.assert_awaited()


def _compiled_sql(stmt: object) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True})).lower()


@pytest.mark.asyncio
async def test_post_merge_retry_unstamped_gallery_does_not_starve_on_mixed_batch() -> None:
    tenant_id = str(uuid4())
    cluster_id = str(uuid4())
    unstamped = _orm_identity(tenant_id=tenant_id, model=None)
    persist, evaluate, writer, gate, suggestions, session = _harness(
        reps=[_rep(cluster_id, None)],
        unclustered=[],
        tenant_id=tenant_id,
        cluster_id=cluster_id,
    )
    writer.cluster_repository.get_unclustered_in_embedding_space = AsyncMock(
        return_value=[media_identity_from_model(unstamped)]
    )

    await post_merge_retry_matching(
        tenant_id=tenant_id,
        target_cluster_id=cluster_id,
        session=session,
        gate=gate,
        assignment_writer=writer,
        suggestion_service=suggestions,
        max_unclustered=2,
        min_similarity_for_unclustered=0.5,
    )

    writer.cluster_repository.get_unclustered_in_embedding_space.assert_awaited_once_with(
        tenant_id,
        None,
        limit=2,
    )
    evaluate.assert_awaited()
    persist.assert_awaited()


@pytest.mark.asyncio
async def test_get_unclustered_in_embedding_space_does_not_starve_on_mixed_sqlite_batch() -> None:
    """Runtime SQLite: filter tenant/space/membership before LIMIT 2 (DATA-13).

    Three higher-confidence foreign-space rows would fill a limit-2 batch if
    ``embedding_model IS NULL`` ran after LIMIT. Same-tenant membership and a
    foreign-tenant unstamped row are extra controls. ORM ``embedding_model``
    stays NOT NULL; SQLite DDL is relaxed on a private MetaData copy only.
    Real ``get_unclustered_in_embedding_space`` produces candidates that feed
    ``post_merge_retry_matching``; evaluate/persist see only eligible IDs.
    """
    from sqlalchemy import MetaData, event, text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from db.base import Base
    from db.models import IdentityCluster, IdentityMember, MediaIdentity, Tenant
    from db.settings import get_database_settings
    from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository
    from recognition.tests.conftest import _sqlite_vector_norm

    dim = get_database_settings().pgvector_dimension
    unit = [0.0] * dim
    unit[0] = 1.0
    tenant_a = uuid4()
    tenant_b = uuid4()
    cluster_id = uuid4()
    foreign_space_ids = [uuid4(), uuid4(), uuid4()]
    member_id = uuid4()
    foreign_tenant_id = uuid4()
    unstamped_ids = [uuid4(), uuid4()]
    eligible_ids = [str(unstamped_ids[0]), str(unstamped_ids[1])]
    forbidden_ids = {str(item) for item in foreign_space_ids} | {str(member_id), str(foreign_tenant_id)}

    assert MediaIdentity.__table__.c.embedding_model.nullable is False
    legacy_md = MetaData()
    for table_name in ("tenants", "media_identities", "identity_clusters", "identity_members"):
        Base.metadata.tables[table_name].to_metadata(legacy_md)
    legacy_md.tables["media_identities"].c.embedding_model.nullable = True
    assert MediaIdentity.__table__.c.embedding_model.nullable is False

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _register_vector_functions(dbapi_connection, _connection_record) -> None:
        dbapi_connection.create_function("vector_norm", 1, _sqlite_vector_norm)

    try:
        async with engine.begin() as conn:
            await conn.execute(text("PRAGMA foreign_keys=ON"))
            await conn.run_sync(legacy_md.create_all)
        assert MediaIdentity.__table__.c.embedding_model.nullable is False
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            session.add_all(
                [
                    Tenant(id=tenant_a, site_url="https://keep.example.test/wp"),
                    Tenant(id=tenant_b, site_url="https://foreign.example.test/wp"),
                ]
            )
            await session.flush()
            session.add(IdentityCluster(id=cluster_id, tenant_id=tenant_a, identity_count=1))
            await session.flush()

            def _identity(
                *,
                identity_id: object,
                tenant: object,
                media_id: int,
                model: str | None,
                confidence: float,
            ) -> MediaIdentity:
                return MediaIdentity(
                    id=identity_id,
                    tenant_id=tenant,
                    media_id=media_id,
                    media_url=f"http://example.test/{media_id}.jpg",
                    bbox_x=0,
                    bbox_y=0,
                    bbox_width=10,
                    bbox_height=10,
                    confidence=confidence,
                    embedding=unit,
                    embedding_model=model,
                )

            session.add_all(
                [
                    _identity(
                        identity_id=foreign_space_ids[0],
                        tenant=tenant_a,
                        media_id=1,
                        model="space-b",
                        confidence=0.99,
                    ),
                    _identity(
                        identity_id=foreign_space_ids[1],
                        tenant=tenant_a,
                        media_id=2,
                        model="space-b",
                        confidence=0.98,
                    ),
                    _identity(
                        identity_id=foreign_space_ids[2],
                        tenant=tenant_a,
                        media_id=3,
                        model="space-b",
                        confidence=0.97,
                    ),
                    _identity(
                        identity_id=member_id,
                        tenant=tenant_a,
                        media_id=4,
                        model=None,
                        confidence=0.96,
                    ),
                    _identity(
                        identity_id=foreign_tenant_id,
                        tenant=tenant_b,
                        media_id=5,
                        model=None,
                        confidence=0.95,
                    ),
                    _identity(
                        identity_id=unstamped_ids[0],
                        tenant=tenant_a,
                        media_id=6,
                        model=None,
                        confidence=0.51,
                    ),
                    _identity(
                        identity_id=unstamped_ids[1],
                        tenant=tenant_a,
                        media_id=7,
                        model=None,
                        confidence=0.50,
                    ),
                ]
            )
            await session.flush()
            session.add(
                IdentityMember(
                    tenant_id=tenant_a,
                    cluster_id=cluster_id,
                    identity_id=member_id,
                    similarity=0.9,
                )
            )
            await session.flush()

            real_repo = SqlAlchemyClusterRepository(session)
            produced: list[object] = []

            class _DelegatingClusterRepository:
                async def get_all_representatives(self, cluster_id: str) -> list[ClusterRepresentative]:
                    return [
                        ClusterRepresentative(
                            id=str(uuid4()),
                            cluster_id=cluster_id,
                            identity_id=str(uuid4()),
                            embedding=np.asarray(unit, dtype=np.float32),
                            created_at=datetime.now(tz=UTC),
                            embedding_model=None,
                        )
                    ]

                async def get_unclustered_in_embedding_space(
                    self,
                    tenant_id: str,
                    embedding_model: str | None,
                    *,
                    limit: int,
                ) -> list[object]:
                    rows = await real_repo.get_unclustered_in_embedding_space(
                        tenant_id,
                        embedding_model,
                        limit=limit,
                    )
                    produced.extend(rows)
                    return rows

            evaluated_ids: list[str] = []
            persisted_ids: list[str] = []

            async def _eval(candidate):  # noqa: ANN001
                evaluated_ids.append(str(candidate.identity.id))
                return AssignmentDecision(
                    outcome=AssignmentOutcome.ACCEPT,
                    candidate=candidate,
                    checks_passed=["confidence_check"],
                    checks_failed=[],
                )

            async def _persist(decision: AssignmentDecision) -> None:
                persisted_ids.append(str(decision.candidate.identity.id))

            writer = SimpleNamespace(
                cluster_repository=_DelegatingClusterRepository(),
                member_repository=SimpleNamespace(get_by_identity_id=AsyncMock(return_value=[])),
                persist_assignment=AsyncMock(side_effect=_persist),
            )
            gate = SimpleNamespace(
                settings=SimpleNamespace(similarity_threshold=0.5),
                evaluate=AsyncMock(side_effect=_eval),
            )
            suggestions = SimpleNamespace(
                get_by_cluster=AsyncMock(return_value=[]),
                create=AsyncMock(),
                resolve_for_identity=AsyncMock(),
                update_scores=AsyncMock(),
            )
            await post_merge_retry_matching(
                tenant_id=str(tenant_a),
                target_cluster_id=str(cluster_id),
                session=session,
                gate=gate,
                assignment_writer=writer,
                suggestion_service=suggestions,
                max_unclustered=2,
                min_similarity_for_unclustered=0.5,
            )

            found_ids = [identity.id for identity in produced]
            assert found_ids == eligible_ids
            assert len(produced) == 2
            assert all(identity.embedding_model is None for identity in produced)
            assert forbidden_ids.isdisjoint(found_ids)
            assert evaluated_ids == eligible_ids
            assert persisted_ids == eligible_ids
            assert forbidden_ids.isdisjoint(evaluated_ids)
            assert forbidden_ids.isdisjoint(persisted_ids)
            assert MediaIdentity.__table__.c.embedding_model.nullable is False
    finally:
        await engine.dispose()
        assert MediaIdentity.__table__.c.embedding_model.nullable is False


@pytest.mark.asyncio
async def test_get_unclustered_in_embedding_space_sql_is_null_for_legacy_gallery() -> None:
    from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository

    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    repo = SqlAlchemyClusterRepository(session)

    await repo.get_unclustered_in_embedding_space(str(uuid4()), None, limit=2)

    stmt = session.execute.await_args.args[0]
    sql = _compiled_sql(stmt)
    assert "embedding_model is null" in sql
    assert "identity_member" in sql


@pytest.mark.asyncio
async def test_get_unclustered_in_embedding_space_sql_equals_gallery_model() -> None:
    from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository

    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    repo = SqlAlchemyClusterRepository(session)

    await repo.get_unclustered_in_embedding_space(str(uuid4()), "space-a", limit=10)

    stmt = session.execute.await_args.args[0]
    sql = _compiled_sql(stmt)
    assert "embedding_model" in sql
    assert "is null" not in sql
    assert "space-a" in sql
