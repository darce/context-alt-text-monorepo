"""Shared pytest fixtures and fakes for recognition tests."""

from __future__ import annotations

import math
import os
import uuid
from collections.abc import AsyncGenerator, Iterable, Sequence
from datetime import UTC, datetime

import numpy as np
import pytest
import pytest_asyncio
from sqlalchemy import Table, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from db.base import Base
from db.models import Tenant
from recognition.application.assignment.gate import AssignmentGate
from recognition.application.discovery.centroid import CentroidDiscovery
from recognition.application.discovery.graph import GraphDiscovery
from recognition.application.discovery.representative import RepresentativeDiscovery
from recognition.application.embedding.detector import FaceDetection
from recognition.application.embedding.generator import EmbeddingResult
from recognition.application.orchestration.cluster_service import ClusterService
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.scan.service import ScanService
from recognition.application.settings import ClusteringSettings
from recognition.application.suggestions.service import SuggestionService
from recognition.infrastructure.clustering.hdbscan_adapter import HdbscanGraphAlgorithm
from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository
from recognition.infrastructure.repositories.job_repository import SqlAlchemyJobRepository
from recognition.infrastructure.repositories.member_repository import SqlAlchemyMemberRepository
from recognition.infrastructure.repositories.suggestion_repository import SqlAlchemySuggestionRepository
from recognition.tests.db_seed import ensure_media_identity as _ensure_media_identity

os.environ["RECOGNITION_AUTH_ENABLED"] = "0"
os.environ["RECOGNITION_ASYNC_ANALYZE_INLINE"] = "1"
os.environ["RECOGNITION_RUNTIME_MODE"] = "test"


def _sqlite_vector_norm(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode()
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            stripped = stripped[1:-1]
        parts = [part.strip() for part in stripped.split(",") if part.strip()]
        coordinates = [float(part) for part in parts]
        return math.sqrt(sum(component * component for component in coordinates))
    raise TypeError(f"Unsupported vector value for SQLite norm emulation: {type(value)!r}")


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an isolated in-memory SQLite session with required tables."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _register_vector_functions(dbapi_connection, _connection_record) -> None:
        dbapi_connection.create_function("vector_norm", 1, _sqlite_vector_norm)

    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        tables: list[Table] = [
            Table("identity_clusters", Base.metadata),
            Table("curation_replay_records", Base.metadata),
            Table("identity_cluster_representatives", Base.metadata),
            Table("identity_members", Base.metadata),
            Table("cluster_merge_suggestions", Base.metadata),
            Table("identity_cluster_blocks", Base.metadata),
            Table("identity_clustering_jobs", Base.metadata),
            Table("identity_scan_jobs", Base.metadata),
            Table("identity_scan_job_items", Base.metadata),
            Table("identity_suggestions", Base.metadata),
            Table("name_suggestions", Base.metadata),
            Table("recognition_runs", Base.metadata),
            Table("recognition_events", Base.metadata),
            Table("audit_events", Base.metadata),
            Table("api_keys", Base.metadata),
            Table("demo_instances", Base.metadata),
            Table("clustering_job_reports", Base.metadata),
            Table("assignment_decisions", Base.metadata),
            Table("clustering_feedback", Base.metadata),
            Table("media_identities", Base.metadata),
            Table("identity_constraints", Base.metadata),
            Table("tenants", Base.metadata),
            Table("worker_capabilities", Base.metadata),
            # FIR-9 atlas tables (purge_service delete_plan head entries)
            Table("identity_atlas_runs", Base.metadata),
            Table("identity_atlas_points", Base.metadata),
            Table("identity_atlas_queue_dispositions", Base.metadata),
        ]
        await conn.run_sync(Base.metadata.create_all, tables=tables)
        # Create mv_identity_cluster_centroids as a regular table for SQLite
        # (PostgreSQL uses a materialized view, but SQLite doesn't support those)
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS mv_identity_cluster_centroids (
                    cluster_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    identity_count INTEGER NOT NULL DEFAULT 0,
                    centroid BLOB,
                    refreshed_at TIMESTAMP
                )
                """
            )
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await session.begin_nested()

        @event.listens_for(session.sync_session, "after_transaction_end")
        def _restart_savepoint(sess, transaction):
            if transaction.nested and not transaction._parent.nested:
                sess.begin_nested()

        try:
            yield session
            await session.rollback()
        finally:
            await session.close()

    await engine.dispose()


@pytest_asyncio.fixture
async def tenant(db_session: AsyncSession) -> Tenant:
    """Insert a tenant row for multi-tenant scoped operations."""
    tenant = Tenant(site_url="http://example.test")
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


@pytest.fixture
def uuid_str() -> str:
    """Return a new UUID string."""
    return str(uuid.uuid4())


@pytest.fixture
def seed_media_identity(db_session: AsyncSession, tenant: Tenant):
    """Seed a placeholder ``MediaIdentity`` so FK-bound repo writes can be exercised (INFRA-3)."""

    async def _seed(identity_id: str | uuid.UUID, *, tenant_id: str | uuid.UUID | None = None) -> None:
        await _ensure_media_identity(db_session, tenant_id if tenant_id is not None else tenant.id, identity_id)

    return _seed


# ----------------------------------------------------------------------
# Integration Test Protocol Fakes
# ----------------------------------------------------------------------


class FakeDetector:
    """Deterministic fake detector for integration tests."""

    async def detect(self, media_ids: Iterable[str]) -> list[FaceDetection]:
        detections = []
        for mid in media_ids:
            # Deterministic detection per media ID
            detection = FaceDetection(
                media_id=mid,
                bbox=(10, 10, 100, 100),
                confidence=0.99,
                model_id="stub-detector@test",
            )
            detections.append(detection)
        return detections


class FakeEmbeddingGenerator:
    """Deterministic fake embedding generator."""

    def __init__(self, embedding_dim: int = 512) -> None:
        self.embedding_dim = embedding_dim

    async def generate(self, face_images: list[bytes]) -> list[EmbeddingResult]:
        results = []
        for idx, img_bytes in enumerate(face_images):
            # Seed based on input bytes to be deterministic
            seed = int.from_bytes(img_bytes[:4], "little") + idx
            rng = np.random.default_rng(seed)
            vector = rng.random(self.embedding_dim).astype(np.float32)
            # Normalize
            norm = np.linalg.norm(vector)
            if norm > 0:
                vector = vector / norm

            results.append(
                EmbeddingResult(
                    media_id="placeholder",
                    embedding=vector,
                    confidence=0.95,
                )
            )
        return results


# ----------------------------------------------------------------------
# Integration Test Fixtures (Real Dependencies)
# ----------------------------------------------------------------------


@pytest.fixture
def job_repository(db_session: AsyncSession) -> SqlAlchemyJobRepository:
    return SqlAlchemyJobRepository(db_session)


@pytest.fixture
def cluster_repository(db_session: AsyncSession) -> SqlAlchemyClusterRepository:
    return SqlAlchemyClusterRepository(db_session)


@pytest.fixture
def member_repository(db_session: AsyncSession, tenant: Tenant) -> SqlAlchemyMemberRepository:
    return SqlAlchemyMemberRepository(db_session, tenant_id=tenant.id)


@pytest.fixture
def suggestion_repository(db_session: AsyncSession, tenant: Tenant) -> SqlAlchemySuggestionRepository:
    return SqlAlchemySuggestionRepository(db_session)


@pytest.fixture
def scan_service(db_session: AsyncSession) -> ScanService:
    # Use deterministic fakes
    return ScanService(
        session=db_session,
        detector=FakeDetector(),
        generator=FakeEmbeddingGenerator(embedding_dim=512),
    )


@pytest.fixture
def assignment_writer(
    cluster_repository: SqlAlchemyClusterRepository, member_repository: SqlAlchemyMemberRepository
) -> AssignmentWriter:
    settings = ClusteringSettings()
    return AssignmentWriter(settings, cluster_repository, member_repository)


@pytest.fixture
def cluster_service(
    db_session: AsyncSession,
    tenant: Tenant,
    cluster_repository: SqlAlchemyClusterRepository,
    member_repository: SqlAlchemyMemberRepository,
    assignment_writer: AssignmentWriter,
    suggestion_repository: SqlAlchemySuggestionRepository,
) -> ClusterService:
    settings = ClusteringSettings()

    # Configure discovery chain
    gate = AssignmentGate(settings, cluster_repository)
    rep_discovery = RepresentativeDiscovery(settings)
    centroid_discovery = CentroidDiscovery(settings)
    graph_discovery = GraphDiscovery(settings, HdbscanGraphAlgorithm())
    suggestions = SuggestionService(
        suggestion_repository, tenant_id=str(tenant.id), cluster_repository=cluster_repository
    )

    return ClusterService(
        gate=gate,
        representative_discovery=rep_discovery,
        centroid_discovery=centroid_discovery,
        graph_discovery=graph_discovery,
        assignment_writer=assignment_writer,
        suggestion_service=suggestions,
        logger=None,  # Logging not needed for functional integration tests
        session=db_session,  # Required for DB operations in cluster_unclustered_identities
    )


# ---- E15-34 PG schema substrate -----------------------------------------
#
# Scratch databases for `-m pg` schema tests. IDENTITY_PG_TEST_URL (sync
# psycopg URL) selects host/port/user for the scratch DBs; its database name
# is used as the base name, suffixed per-fixture and per-process so parallel
# runs and concurrent worktrees cannot collide.
#
# IDENTITY_PG_ADMIN_URL must be a role able to CREATE DATABASE and install the
# vector extension (Homebrew superuser default) — admin privilege is fine.
#
# IDENTITY_PG_TEST_URL must be a non-superuser WITHOUT BYPASSRLS. That *lack*
# of privilege is what makes tenant-isolation tests mean anything: PostgreSQL
# exempts superusers and BYPASSRLS roles from RLS even when FORCE ROW LEVEL
# SECURITY is set (FORCE only removes the table-owner exemption). Connecting
# the suite as a privileged role silently vacates every isolation assertion.
# After the scratch engine connects, fixtures query pg_roles and pytest.fail
# (not skip) if the test role is privileged — a skip would leave the gate
# green while isolation is untested. [FL30B-GATE-01] [rg-008]
#
# Skips (never fails) only when Postgres is unreachable or the admin role
# lacks CREATE DATABASE / vector privileges.

IDENTITY_PG_TEST_URL = os.environ.get(
    "IDENTITY_PG_TEST_URL",
    "postgresql+psycopg://context:context@localhost:5432/acx_identity_test",
)


def rls_unenforceable_role_message(
    *,
    role: str,
    rolsuper: bool,
    rolbypassrls: bool,
) -> str | None:
    """Return a fail message when *role* is exempt from RLS; else None.

    Superusers and BYPASSRLS roles skip row-level security even under
    FORCE ROW LEVEL SECURITY. Isolation tests against such a role assert
    nothing, so the harness must refuse them loudly.
    """
    if not rolsuper and not rolbypassrls:
        return None
    flags: list[str] = []
    if rolsuper:
        flags.append("rolsuper=true")
    if rolbypassrls:
        flags.append("rolbypassrls=true")
    return (
        f"RLS assertions are unenforceable for role {role!r} ({', '.join(flags)}). "
        "PostgreSQL exempts superusers and BYPASSRLS roles from row-level security "
        "even when FORCE ROW LEVEL SECURITY is set. "
        "IDENTITY_PG_TEST_URL must point at a non-superuser without BYPASSRLS "
        "(IDENTITY_PG_ADMIN_URL may remain a superuser for CREATE DATABASE / vector)."
    )


def assert_engine_role_rls_enforceable(engine) -> None:
    """Fail hard if the engine's connected role is superuser or has BYPASSRLS.

    Fail (not skip): a silent skip is the same greenwash as running isolation
    tests under a privileged role — the gate stays green while asserting nothing.
    """
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT current_user, r.rolsuper, r.rolbypassrls "
                "FROM pg_roles r WHERE r.rolname = current_user"
            )
        ).one()
    role, rolsuper, rolbypassrls = str(row[0]), bool(row[1]), bool(row[2])
    msg = rls_unenforceable_role_message(
        role=role, rolsuper=rolsuper, rolbypassrls=rolbypassrls
    )
    if msg is not None:
        pytest.fail(msg)


def _pg_scratch_urls(suffix: str) -> tuple[str, str, str, str]:
    """(scratch_url, admin_url, db_name, owner) derived from IDENTITY_PG_TEST_URL."""
    from urllib.parse import urlsplit

    parts = urlsplit(IDENTITY_PG_TEST_URL)
    base_name = parts.path.lstrip("/") or "acx_identity_test"
    db_name = f"{base_name}{suffix}_{os.getpid()}"
    owner = parts.username or "context"
    scratch_url = IDENTITY_PG_TEST_URL.rsplit("/", 1)[0] + f"/{db_name}"
    default_admin = f"postgresql+psycopg://{parts.hostname or 'localhost'}:{parts.port or 5432}/postgres"
    admin_url = os.environ.get("IDENTITY_PG_ADMIN_URL", default_admin)
    return scratch_url, admin_url, db_name, owner


def _pg_create_scratch_db(admin_url: str, db_name: str, owner: str):
    """Create a fresh scratch DB (+vector extension); skip when PG unusable."""
    from sqlalchemy import create_engine
    from sqlalchemy.exc import ProgrammingError

    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{db_name}" OWNER "{owner}"'))
        scratch_admin_url = admin_url.rsplit("/", 1)[0] + f"/{db_name}"
        scratch_admin = create_engine(scratch_admin_url, isolation_level="AUTOCOMMIT")
        with scratch_admin.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        scratch_admin.dispose()
    except OperationalError:
        admin.dispose()
        pytest.skip(f"Postgres unreachable at {admin_url}; start it with `make postgres-start`")
    except ProgrammingError as exc:
        admin.dispose()
        pytest.skip(
            f"Postgres at {admin_url} unusable for scratch DBs ({exc.orig!r}); "
            "IDENTITY_PG_ADMIN_URL must be a superuser/CREATEDB role with the vector extension"
        )
    return admin


def _pg_drop_scratch_db(admin, db_name: str) -> None:
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(scope="session")
def pg_migrated_engine():
    """Empty scratch DB with the identity migration applied, torn down after."""
    import subprocess
    import sys
    from pathlib import Path as _Path

    from sqlalchemy import create_engine

    scratch_url, admin_url, db_name, owner = _pg_scratch_urls("")
    admin = _pg_create_scratch_db(admin_url, db_name, owner)

    # env.py derives the URL from PG*/DB_NAME env vars and full-DSN overrides
    # (POSTGRES_DSN / POSTGRES_SYNC_DSN — env or .env — beat DB_NAME), and
    # db.settings caches resolution: run the upgrade in a subprocess with BOTH
    # full DSNs pinned to the scratch database so no ambient config can point
    # the migration at a real DB. cwd is pinned to the service root so
    # `-c db/alembic.ini` resolves regardless of the pytest invocation dir.
    service_root = _Path(__file__).resolve().parents[2]
    async_scratch = scratch_url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "db/alembic.ini", "upgrade", "head"],
        env={
            **os.environ,
            "DB_NAME": db_name,
            "POSTGRES_SYNC_DSN": scratch_url,
            "POSTGRES_DSN": async_scratch,
        },
        cwd=service_root,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if upgrade.returncode != 0:
        raise RuntimeError(f"alembic upgrade failed on {db_name}:\n{upgrade.stdout}\n{upgrade.stderr}")

    engine = create_engine(scratch_url)
    try:
        assert_engine_role_rls_enforceable(engine)
        yield engine
    finally:
        engine.dispose()
        _pg_drop_scratch_db(admin, db_name)


@pytest.fixture
def pg_empty_engine():
    """Function-scoped bare scratch DB (vector extension only, no migration)."""
    from sqlalchemy import create_engine

    scratch_url, admin_url, db_name, owner = _pg_scratch_urls("_heal")
    admin = _pg_create_scratch_db(admin_url, db_name, owner)

    engine = create_engine(scratch_url)
    try:
        assert_engine_role_rls_enforceable(engine)
        yield engine
    finally:
        engine.dispose()
        _pg_drop_scratch_db(admin, db_name)
