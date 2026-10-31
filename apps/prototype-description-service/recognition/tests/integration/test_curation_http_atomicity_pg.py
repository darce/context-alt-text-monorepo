"""Actual /roster/curation/sync transaction composition on a lane-owned PG17 scratch DB.

The real route, session providers, job-service builder and SqlAlchemyJobRepository
run unchanged; only the providers' session factory targets the scratch NOBYPASSRLS
role. A deferred constraint trigger makes PostgreSQL itself refuse COMMIT after the
queue, effect and replay statements have all succeeded.
"""

from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models.identity import IdentityCluster
from recognition.infrastructure.repositories.job_repository import SqlAlchemyJobRepository
from recognition.interface_adapters.http.deps import session as session_deps
from recognition.tests.integration.test_curation_replay_fingerprint import context, counts, seeded
from recognition.tests.schema.test_curation_replay_fingerprint_pg import replay_pg_engine  # noqa: F401
from recognition.tests.unit.test_curation_sync_router import _FakeAdmission
from roster.interface_adapters.http import curation_router

pytestmark = [pytest.mark.asyncio, pytest.mark.pg]

_PARTICIPANTS = ("curation_replay_records", "identity_clustering_jobs")
_LATE_COMMIT_FAULT = [
    "CREATE TABLE late_commit_fault (tenant_id uuid, table_name text, PRIMARY KEY (tenant_id, table_name))",
    """
    CREATE FUNCTION late_commit_fault() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM late_commit_fault WHERE tenant_id = NEW.tenant_id AND table_name = TG_TABLE_NAME
        ) THEN
            RAISE EXCEPTION 'injected late commit failure';
        END IF;
        RETURN NULL;
    END
    $$
    """,
    *[
        f"""
        CREATE CONSTRAINT TRIGGER late_commit_fault AFTER INSERT ON {table}
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION late_commit_fault()
        """
        for table in _PARTICIPANTS
    ],
]


@pytest_asyncio.fixture
async def route(replay_pg_engine, monkeypatch):
    with replay_pg_engine.begin() as conn:
        for statement in _LATE_COMMIT_FAULT:
            conn.execute(text(statement))
    engine = create_async_engine(
        replay_pg_engine.url.set(drivername="postgresql+asyncpg"), connect_args={"timeout": 5, "command_timeout": 10}
    )
    commit_errors: list[str] = []

    def record_commit_error(ctx):
        if ctx.statement is None:  # raised by COMMIT itself, not by a statement
            commit_errors.append(str(ctx.original_exception))

    event.listen(engine.sync_engine, "handle_error", record_commit_error)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(session_deps, "async_session_factory", sessions)
    app = FastAPI()
    app.include_router(curation_router.router, prefix="/roster")
    app.state.usage_admission_service = _FakeAdmission()
    try:
        yield SimpleNamespace(app=app, sessions=sessions, commit_errors=commit_errors)
    finally:
        await engine.dispose()
        with replay_pg_engine.begin() as conn:
            for table in _PARTICIPANTS:
                conn.execute(text(f"DROP TRIGGER late_commit_fault ON {table}"))
            conn.execute(text("DROP FUNCTION late_commit_fault()"))
            conn.execute(text("DROP TABLE late_commit_fault"))


async def post(app, tenant, request) -> httpx.Response:
    async def authenticated_tenant() -> str:
        return str(tenant)

    app.dependency_overrides[curation_router.get_authenticated_tenant_id] = authenticated_tenant
    # Report what reached the wire, even when the app raises after responding.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post("/roster/curation/sync", json=request.model_dump(mode="json"))


async def persisted(route, tenant, cluster):
    async with route.sessions() as session:
        await context(session, tenant)
        model = await session.get(IdentityCluster, cluster)
        return await counts(session, tenant), model.roster_id, model.label


@pytest.mark.parametrize("failing_participant", _PARTICIPANTS)
async def test_late_commit_failure_rolls_back_queue_effect_and_replay_without_ack(
    route, replay_pg_engine, failing_participant
):
    tenant, cluster, request = await seeded(route.sessions)
    with replay_pg_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO late_commit_fault VALUES (:t, :table)"), {"t": tenant, "table": failing_participant}
        )

    response = await post(route.app, tenant, request)

    assert route.commit_errors and all("injected late commit failure" in e for e in route.commit_errors)
    # (replay records, queued follow-up jobs): nothing may survive the failed commit.
    assert await persisted(route, tenant, cluster) == ((0, 0), None, "Before")
    assert response.status_code == 500
    assert "acknowledged" not in response.text

    with replay_pg_engine.begin() as conn:
        conn.execute(text("DELETE FROM late_commit_fault WHERE tenant_id = :t"), {"t": tenant})
    retry = await post(route.app, tenant, request)
    assert (retry.status_code, retry.json()["status"]) == (200, "acknowledged")
    replay = await post(route.app, tenant, request)
    assert (replay.status_code, replay.json()) == (200, retry.json())
    bound = await persisted(route, tenant, cluster)
    assert (bound[0], str(bound[1]), bound[2]) == ((1, 1), request.payload["person_uuid"], "Ada")


async def test_route_queue_writes_through_the_handler_transaction(route, monkeypatch):
    built = []

    class RecordingService(curation_router.CurationSyncService):
        def __init__(self, session, job_service=None):
            built.append((session, job_service))
            super().__init__(session=session, job_service=job_service)

    monkeypatch.setattr(curation_router, "CurationSyncService", RecordingService)
    tenant, cluster, request = await seeded(route.sessions)

    response = await post(route.app, tenant, request)

    [(session, job_service)] = built
    assert isinstance(job_service.repository, SqlAlchemyJobRepository)
    assert job_service.repository.session is session
    assert (response.status_code, response.json()["status"]) == (200, "acknowledged")
    assert (await persisted(route, tenant, cluster))[0] == (1, 1)
    assert route.commit_errors == []
