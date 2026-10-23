"""Postgres proof for tenant erasure of append-only face observations (CURUX-E1-RET-001).

Runs as the non-superuser, non-BYPASSRLS scratch role with FORCE RLS, so the
immutability trigger, tenant FK, and RLS policy are the real ones from the
migration. SQLite cannot see any of this.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from recognition.application.services.purge_service import TenantPurgeService
from recognition.domain.repositories import MvRefreshOutcome

pytestmark = pytest.mark.pg

_UNIT_VECTOR = "[" + ",".join(["1"] + ["0"] * 511) + "]"


def _as_tenant(conn, tenant_id) -> None:
    conn.execute(text("SELECT set_config('app.current_tenant', :t, true)"), {"t": str(tenant_id)})


def _seed_tenant(conn, *, disposed: bool = False) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Tenant with one observation and one identity pointing at it; returns (tenant, observation, identity)."""
    tenant_id, observation_id, identity_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conn.execute(
        text("INSERT INTO tenants (id, site_url) VALUES (:id, :url)"),
        {"id": tenant_id, "url": f"https://{tenant_id}.test"},
    )
    _as_tenant(conn, tenant_id)
    conn.execute(
        text(
            "INSERT INTO face_observations (id, tenant_id, identity_namespace_id, attachment_id, evidence) "
            "VALUES (:id, :tenant, :ns, 1, CAST(:evidence AS jsonb))"
        ),
        {"id": observation_id, "tenant": tenant_id, "ns": uuid.uuid4(), "evidence": json.dumps({"v": 1})},
    )
    conn.execute(
        text(
            "INSERT INTO media_identities (id, tenant_id, media_id, media_url, face_observation_id, bbox_x, bbox_y, "
            "bbox_width, bbox_height, confidence, embedding, embedding_model, disposed_at) VALUES (:id, :tenant, 1, "
            "'http://example.test/1.jpg', :obs, 0, 0, 10, 10, 0.9, CAST(:vec AS vector), 'erasure-pg', "
            "CASE WHEN :disposed THEN now() END)"
        ),
        {"id": identity_id, "tenant": tenant_id, "obs": observation_id, "vec": _UNIT_VECTOR, "disposed": disposed},
    )
    return tenant_id, observation_id, identity_id


def _observation_count(conn, tenant_id) -> int:
    _as_tenant(conn, tenant_id)
    return conn.execute(
        text("SELECT count(*) FROM face_observations WHERE tenant_id = :t"), {"t": tenant_id}
    ).scalar_one()


def _rejects(conn, sql: str, params: dict, match: str) -> None:
    savepoint = conn.begin_nested()
    with pytest.raises(DBAPIError, match=match):
        conn.execute(text(sql), params)
    savepoint.rollback()


def test_tenant_fk_cascades_and_trigger_guards_update_and_delete(pg_migrated_engine) -> None:
    with pg_migrated_engine.connect() as conn:
        fk = conn.execute(
            text(
                "SELECT confdeltype, confrelid::regclass::text FROM pg_constraint "
                "WHERE contype = 'f' AND conrelid = 'face_observations'::regclass"
            )
        ).all()
        trigger = conn.execute(
            text(
                "SELECT tgtype FROM pg_trigger WHERE tgrelid = 'face_observations'::regclass "
                "AND tgname = 'face_observations_immutable'"
            )
        ).scalar_one()
    assert fk == [("c", "tenants")]
    # ROW (1) | BEFORE (2) | DELETE (8) | UPDATE (16)
    assert trigger == 1 | 2 | 8 | 16


def test_ordinary_mutation_rejected_and_marker_limited_to_row_tenant(pg_migrated_engine) -> None:
    with pg_migrated_engine.connect() as conn:
        transaction = conn.begin()
        try:
            tenant_a, observation_a, _ = _seed_tenant(conn)
            tenant_b, observation_b, _ = _seed_tenant(conn)
            # Detach current pointers (per tenant, under RLS) so only the trigger decides.
            for tenant_id in (tenant_a, tenant_b):
                _as_tenant(conn, tenant_id)
                conn.execute(text("UPDATE media_identities SET face_observation_id = NULL"))
            _as_tenant(conn, tenant_a)

            _rejects(conn, "UPDATE face_observations SET attachment_id = 2 WHERE id = :id", {"id": observation_a}, "immutable")
            _rejects(conn, "DELETE FROM face_observations WHERE id = :id", {"id": observation_a}, "immutable")
            conn.execute(text("SELECT set_config('app.face_observation_erasure_tenant', :t, true)"), {"t": str(tenant_a)})
            _rejects(conn, "UPDATE face_observations SET attachment_id = 2 WHERE id = :id", {"id": observation_a}, "immutable")
            # RLS still bounds the erasure: an A-context session cannot reach B's row.
            assert conn.execute(text("DELETE FROM face_observations WHERE id = :id"), {"id": observation_b}).rowcount == 0
            _rejects(
                conn,
                "INSERT INTO face_observations (id, tenant_id, identity_namespace_id, attachment_id, evidence) "
                "VALUES (:id, :t, :id, 1, '{}'::jsonb)",
                {"id": uuid.uuid4(), "t": tenant_b},
                "row-level security",
            )

            # A marker naming B is not authority over A's rows.
            conn.execute(text("SELECT set_config('app.face_observation_erasure_tenant', :t, true)"), {"t": str(tenant_b)})
            _rejects(conn, "DELETE FROM face_observations WHERE id = :id", {"id": observation_a}, "immutable")

            conn.execute(text("SELECT set_config('app.face_observation_erasure_tenant', :t, true)"), {"t": str(tenant_a)})
            savepoint = conn.begin_nested()
            assert conn.execute(text("DELETE FROM face_observations WHERE id = :id"), {"id": observation_a}).rowcount == 1
            savepoint.rollback()
            assert _observation_count(conn, tenant_a) == 1, "rolled-back erasure must leave the row"
            assert _observation_count(conn, tenant_b) == 1
        finally:
            transaction.rollback()


def test_tenant_deletion_cascades_through_current_pointer_only_for_that_tenant(pg_migrated_engine) -> None:
    with pg_migrated_engine.connect() as conn:
        transaction = conn.begin()
        try:
            tenant_a, _, _ = _seed_tenant(conn)
            tenant_b, _, _ = _seed_tenant(conn)
            conn.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": tenant_a})
            assert _observation_count(conn, tenant_a) == 0
            assert _observation_count(conn, tenant_b) == 1
            _as_tenant(conn, tenant_b)
            assert conn.execute(text("SELECT count(*) FROM media_identities")).scalar_one() == 1
        finally:
            transaction.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["all", "disposed"])
async def test_purge_service_erases_observations_under_forced_rls(pg_migrated_engine, scope) -> None:
    with pg_migrated_engine.begin() as conn:
        tenant_a, observation_a, _ = _seed_tenant(conn, disposed=True)
        tenant_b, _, _ = _seed_tenant(conn, disposed=True)
        _as_tenant(conn, tenant_a)
        live_observation = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO face_observations (id, tenant_id, identity_namespace_id, attachment_id, evidence) "
                "VALUES (:id, :t, :id, 2, '{}'::jsonb)"
            ),
            {"id": live_observation, "t": tenant_a},
        )
        conn.execute(
            text(
                "INSERT INTO media_identities (id, tenant_id, media_id, media_url, face_observation_id, bbox_x, "
                "bbox_y, bbox_width, bbox_height, confidence, embedding, embedding_model) VALUES (:id, :t, 2, "
                "'http://example.test/2.jpg', :obs, 0, 0, 10, 10, 0.9, CAST(:vec AS vector), 'erasure-pg')"
            ),
            {"id": uuid.uuid4(), "t": tenant_a, "obs": live_observation, "vec": _UNIT_VECTOR},
        )

    engine = create_async_engine(pg_migrated_engine.url.render_as_string(hide_password=False))
    try:
        async with engine.connect() as aconn:
            await aconn.execute(text("SELECT set_config('app.current_tenant', :t, false)"), {"t": str(tenant_a)})
            await aconn.commit()
            session = AsyncSession(bind=aconn, expire_on_commit=False)
            service = TenantPurgeService(session)
            service._cluster_repository.refresh_centroids_view_concurrent = AsyncMock(
                return_value=MvRefreshOutcome.REFRESHED
            )
            result = await service.purge_tenant_data(str(tenant_a), "erasure-pg", scope=scope)
            await session.close()
    finally:
        await engine.dispose()

    expected = {"all": 2, "disposed": 1}[scope]
    assert result["deleted_counts"]["face_observations"] == expected
    with pg_migrated_engine.connect() as conn:
        _as_tenant(conn, tenant_a)
        remaining = set(conn.execute(text("SELECT id FROM face_observations")).scalars())
        assert remaining == ({live_observation} if scope == "disposed" else set())
        assert observation_a not in remaining
        assert _observation_count(conn, tenant_b) == 1
        _as_tenant(conn, tenant_a)
        events = conn.execute(text("SELECT event_type FROM audit_events")).scalars().all()
        assert sorted(events) == ["purge_completed", "purge_started"]


def test_downgrade_then_reupgrade_restores_fk_and_erasure_trigger(pg_isolated_migrated_engine) -> None:
    url = pg_isolated_migrated_engine.url
    sync_url = url.render_as_string(hide_password=False)
    env = {
        **os.environ,
        "DB_NAME": url.database,
        "POSTGRES_SYNC_DSN": sync_url,
        "POSTGRES_DSN": sync_url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1),
    }
    service_root = Path(__file__).resolve().parents[3]
    pg_isolated_migrated_engine.dispose()
    for step in (["downgrade", "base"], ["upgrade", "head"]):
        completed = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "db/alembic.ini", *step],
            env=env,
            cwd=service_root,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert completed.returncode == 0, f"alembic {step}: {completed.stdout}\n{completed.stderr}"
    with pg_isolated_migrated_engine.connect() as conn:
        assert conn.execute(
            text(
                "SELECT confdeltype FROM pg_constraint WHERE contype = 'f' "
                "AND conrelid = 'face_observations'::regclass AND confrelid = 'tenants'::regclass"
            )
        ).scalar_one() == "c"
        source = conn.execute(
            text("SELECT prosrc FROM pg_proc WHERE proname = 'reject_face_observation_update'")
        ).scalar_one()
        assert "app.face_observation_erasure_tenant" in source
