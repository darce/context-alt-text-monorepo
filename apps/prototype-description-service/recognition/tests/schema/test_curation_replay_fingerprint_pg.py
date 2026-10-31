"""Real model001 qualification, exclusively in a lane-owned PG17 scratch DB."""

import importlib
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.pg
MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")


@pytest.fixture(scope="session")
def replay_pg_engine():
    raw_url = os.environ.get("CURATION_REPLAY_PG_ADMIN_URL")
    if not raw_url:
        pytest.skip("set CURATION_REPLAY_PG_ADMIN_URL to the isolated test Postgres")
    url = make_url(raw_url)
    assert (url.host, url.port, url.database) == ("127.0.0.1", 15437, "acx_uxfir_test")
    name = "acx_replay_fp_" + uuid4().hex[:12]
    admin = create_engine(url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 5})
    password = "uxfir-ephemeral-test-only"
    test_url = url.set(username=name, password=password, database=name)
    engine = None
    try:
        with admin.connect() as conn:
            assert 170000 <= int(conn.scalar(text("SHOW server_version_num"))) < 180000
            conn.execute(text(f"CREATE ROLE \"{name}\" LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '{password}'"))
            conn.execute(text(f'CREATE DATABASE "{name}" OWNER "{name}"'))
        scratch_admin = create_engine(url.set(database=name), isolation_level="AUTOCOMMIT")
        try:
            with scratch_admin.connect() as conn:
                conn.execute(text("CREATE EXTENSION vector"))
        finally:
            scratch_admin.dispose()
        sync_dsn = test_url.render_as_string(hide_password=False)
        async_dsn = test_url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)
        upgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "db/alembic.ini", "upgrade", "head"],
            cwd=Path(__file__).resolve().parents[3],
            env={**os.environ, "POSTGRES_SYNC_DSN": sync_dsn, "POSTGRES_DSN": async_dsn, "DB_NAME": name},
            text=True,
            capture_output=True,
            timeout=180,
        )
        assert upgrade.returncode == 0, upgrade.stdout + upgrade.stderr
        engine = create_engine(
            test_url, connect_args={"connect_timeout": 5, "options": "-c statement_timeout=10000 -c lock_timeout=2000"}
        )
        with engine.connect() as conn:
            role = conn.execute(
                text("SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")
            ).one()
            assert not role.rolsuper and not role.rolbypassrls
            print(
                "replay PG qualification:",
                conn.scalar(text("SHOW server_version")),
                role,
                "isolation:",
                conn.scalar(text("SHOW transaction_isolation")),
                "database:",
                name,
            )
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            conn.execute(text(f'DROP ROLE IF EXISTS "{name}"'))
        admin.dispose()


def test_model001_replay_column_constraints_rls_and_legacy(replay_pg_engine):
    engine = replay_pg_engine
    columns = {c["name"]: c for c in inspect(engine).get_columns("curation_replay_records")}
    assert str(columns["request_fingerprint"]["type"]) == "VARCHAR(64)"
    assert columns["request_fingerprint"]["nullable"]
    tenant, foreign = uuid4(), uuid4()
    with engine.begin() as conn:
        flags = conn.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid='curation_replay_records'::regclass"
            )
        ).one()
        assert flags == (True, True)
        conn.execute(
            text("INSERT INTO tenants(id,site_url) VALUES (:a,'https://a.test'),(:b,'https://b.test')"),
            {"a": tenant, "b": foreign},
        )
        conn.execute(text("SELECT set_config('app.current_tenant',:t,true)"), {"t": str(tenant)})
        params = {"id": uuid4(), "t": tenant, "f": "a" * 64, "key": "key"}
        insert = text(
            "INSERT INTO curation_replay_records(id,tenant_id,idempotency_key,result_status,request_fingerprint) VALUES (:id,:t,:key,'acknowledged',:f)"
        )
        conn.execute(insert, params)
        for overrides, sqlstate in [
            ({"id": uuid4()}, "23505"),
            ({"id": uuid4(), "t": foreign, "key": "foreign-write"}, "42501"),
            ({"id": uuid4(), "f": "short", "key": "invalid-fingerprint"}, "23514"),
        ]:
            with pytest.raises(DBAPIError) as failure, conn.begin_nested():
                conn.execute(insert, {**params, **overrides})
            assert failure.value.orig.sqlstate == sqlstate
        # Old rows remain representable, but the service must refuse their replay.
        conn.execute(
            text(
                "INSERT INTO curation_replay_records(id,tenant_id,idempotency_key,result_status) VALUES (:id,:t,'legacy','acknowledged')"
            ),
            {"id": uuid4(), "t": tenant},
        )
        conn.execute(text("SELECT set_config('app.current_tenant',:t,true)"), {"t": str(foreign)})
        assert conn.scalar(text("SELECT count(*) FROM curation_replay_records")) == 0
        # The same key is valid under another tenant.
        conn.execute(insert, {**params, "id": uuid4(), "t": foreign})
        assert conn.scalar(text("SELECT count(*) FROM curation_replay_records")) == 1
        conn.execute(text("SELECT set_config('app.current_tenant','',true)"))
        assert conn.scalar(text("SELECT count(*) FROM curation_replay_records")) == 0


def test_model001_transactional_downgrade_and_rollback(replay_pg_engine):
    with replay_pg_engine.connect() as conn:
        tx = conn.begin()
        try:
            with Operations.context(MigrationContext.configure(conn)):
                MIGRATION.downgrade()
            assert conn.scalar(text("SELECT to_regclass('curation_replay_records')")) is None
        finally:
            tx.rollback()
        assert "request_fingerprint" in {c["name"] for c in inspect(conn).get_columns("curation_replay_records")}
