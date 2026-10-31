"""Behavioral qualification in randomized task-owned PG17 databases only.

Run with the repository's existing venv through common/run_check.py. No models.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps/prototype-description-service"
TOOL = APP / "scripts/provision_fir_runtime_roles.py"
ADMIN = "postgresql+psycopg://postgres:uxfir-ephemeral-test-only@127.0.0.1:15437/acx_uxfir_test"
sys.path.insert(0, str(APP))


@pytest.fixture
def sandbox(tmp_path):
    url = make_url(ADMIN)
    assert (url.username, url.host, url.port, url.database) == ("postgres", "127.0.0.1", 15437, "acx_uxfir_test")
    name = "acx_role_" + uuid4().hex[:12]
    api, worker = name + "_api", name + "_worker"
    admin = create_engine(url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 5})
    owner = None
    allocated = False
    try:
        with admin.connect() as c:
            assert c.scalar(text("SELECT current_database()")) == "acx_uxfir_test"
            assert str(c.scalar(text("SHOW server_version"))).startswith("17.11 ")
            # Client endpoint is pinned above; PG is reached through Docker's loopback mapping.
            assert c.scalar(text("SELECT inet_server_port()")) == 5432
            assert c.scalar(text("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")) is True
            c.execute(text(f'CREATE DATABASE "{name}"'))
            allocated = True
        target = url.set(database=name)
        owner = create_engine(target, connect_args={"connect_timeout": 5})
        # Current schema authority, not a handcrafted fixture policy or migration.
        with owner.begin() as c:
            c.execute(text("CREATE EXTENSION vector"))
            c.execute(text(f'REVOKE TEMPORARY ON DATABASE "{name}" FROM PUBLIC'))
        from scripts.sync_identity_schema import sync_schema

        sync_schema(owner)
        # Heal does not stamp alembic; reproduce the existing schema's stamp.
        with owner.begin() as c:
            c.execute(text("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)"))
            c.execute(text("INSERT INTO alembic_version VALUES ('001_identity_schema')"))
        owner_file = tmp_path / "owner.dsn"
        owner_file.write_text(target.render_as_string(hide_password=False))
        owner_file.chmod(0o600)
        env_file = tmp_path / "existing-environment.json"
        env_file.write_text(
            json.dumps(
                {
                    "POSTGRES_DSN": target.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False),
                    "POSTGRES_SYNC_DSN": target.render_as_string(hide_password=False),
                    "PGUSER": "postgres",
                    "PGPASSWORD": url.password,
                    "APP_PGUSER": "postgres",
                    "APP_PGPASSWORD": url.password,
                    "POSTGRES_USER": "postgres",
                    "POSTGRES_PASSWORD": url.password,
                    "PGHOST": url.host,
                    "PGPORT": str(url.port),
                    "DB_NAME": name,
                    "POSTGRES_DB": name,
                    "ACX_NETWORK_NAME": "acx-dev-fir-net",
                    "RECOGNITION_AUTH_ENABLED": "1",
                    "RECOGNITION_API_KEY_HEADER": "X-API-Key",
                    "RECOGNITION_SECRET_BACKEND": "env",
                    "PGVECTOR_DIM": "512",
                }
            )
        )
        env_file.chmod(0o600)
        yield {
            "name": name,
            "api": api,
            "worker": worker,
            "owner": owner,
            "owner_file": owner_file,
            "env_file": env_file,
            "output": tmp_path / "private-profile",
            "url": target,
        }
    finally:
        if owner is not None:
            owner.dispose()
        if allocated:
            with admin.connect() as c:
                c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
                # Only the exact two randomized role names allocated by this test.
                for role in (api, worker):
                    c.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
                assert c.scalar(text("SELECT count(*) FROM pg_database WHERE datname=:n"), {"n": name}) == 0
                assert (
                    c.scalar(text("SELECT count(*) FROM pg_roles WHERE rolname IN (:a,:w)"), {"a": api, "w": worker})
                    == 0
                )
                print("cleanup verified:", name, api, worker)
        admin.dispose()


def invoke(sandbox, *extra):
    s = sandbox
    return subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--owner-dsn-file",
            str(s["owner_file"]),
            "--expected-database",
            s["name"],
            "--expected-host",
            "127.0.0.1",
            "--expected-port",
            "15437",
            "--api-role",
            s["api"],
            "--worker-role",
            s["worker"],
            "--runtime-environment-file",
            str(s["env_file"]),
            "--profile-dir",
            str(s["output"]),
            *extra,
        ],
        cwd=APP,
        env={**os.environ, "PYTHONPATH": str(APP)},
        capture_output=True,
        text=True,
        timeout=60,
    )


def roles(s):
    with s["owner"].connect() as c:
        return (
            c.execute(
                text("SELECT rolname FROM pg_roles WHERE rolname IN (:a,:w) ORDER BY rolname"),
                {"a": s["api"], "w": s["worker"]},
            )
            .scalars()
            .all()
        )


def test_dryrun_validates_existing_schema_without_mutating_roles_or_files(sandbox):
    before = roles(sandbox)
    result = invoke(sandbox)
    assert result.returncode == 0, "dry-run must validate the isolated existing target successfully: " + result.stderr
    assert json.loads(result.stdout)["mode"] == "dry-run"
    assert roles(sandbox) == before == []
    assert not sandbox["output"].exists()
    assert sandbox["url"].password not in result.stdout + result.stderr


def profile(s):
    return json.loads((s["output"] / "runtime.compose.json").read_text())


def test_apply_private_profiles_custody_and_real_request_rls(sandbox):
    s = sandbox
    # Existing DB-only API-key identity must survive role provisioning exactly.
    key_tenant, key_id = uuid4(), uuid4()
    with s["owner"].begin() as c:
        c.execute(
            text("INSERT INTO tenants(id,site_url) VALUES (:t,'https://retained-key.invalid')"), {"t": key_tenant}
        )
        c.execute(
            text("INSERT INTO api_keys(id,tenant_id,api_key_hash) VALUES (:i,:t,:h)"),
            {"i": key_id, "t": key_tenant, "h": secrets.token_hex(64)},
        )
        retained = c.execute(
            text("SELECT row_to_json(k)::text FROM api_keys k WHERE id=:i"), {"i": key_id}
        ).scalar_one()
    result = invoke(s, "--apply")
    assert result.returncode == 0, "apply must provision dedicated roles: " + result.stderr
    assert json.loads(result.stdout)["mode"] == "applied"
    with s["owner"].connect() as c:
        assert (
            c.execute(text("SELECT row_to_json(k)::text FROM api_keys k WHERE id=:i"), {"i": key_id}).scalar_one()
            == retained
        )
        assert c.scalar(text("SELECT count(*) FROM tenants WHERE id=:t"), {"t": key_tenant}) == 1
    data = profile(s)
    original = json.loads(s["env_file"].read_text())
    assert set(data["services"]) == {"api", "worker"}
    assert s["output"].stat().st_mode & 0o777 == 0o700
    for p in s["output"].iterdir():
        assert p.stat().st_mode & 0o777 == 0o600
    assert original["PGPASSWORD"] not in (s["output"] / "runtime.compose.json").read_text()
    assert original["PGPASSWORD"] not in result.stdout + result.stderr
    for service, role in [("api", s["api"]), ("worker", s["worker"])]:
        env = data["services"][service]["environment"]
        assert env["POSTGRES_USER"] == env["PGUSER"] == env["APP_PGUSER"] == role
        assert env["PGPASSWORD"] == env["POSTGRES_PASSWORD"] == env["APP_PGPASSWORD"]
        assert env["ACX_SCHEMA_BOOTSTRAP_MODE"] == "verify"
        assert env["ALLOW_RLS_BYPASS_FOR_TESTS"] == "0"
        for key in ("RECOGNITION_AUTH_ENABLED", "RECOGNITION_API_KEY_HEADER", "ACX_NETWORK_NAME", "PGVECTOR_DIM"):
            assert env[key] == original[key]
        for key in ("POSTGRES_DSN", "POSTGRES_SYNC_DSN"):
            url = make_url(env[key])
            assert (url.host, url.port, url.database, url.username) == ("127.0.0.1", 15437, s["name"], role)
            assert not url.query
    assert (
        data["services"]["api"]["environment"]["PGPASSWORD"] != data["services"]["worker"]["environment"]["PGPASSWORD"]
    )
    before = {p.name: p.read_bytes() for p in s["output"].iterdir()}
    second = invoke(s, "--apply")
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["mode"] == "unchanged"
    assert before == {p.name: p.read_bytes() for p in s["output"].iterdir()}
    tenant, foreign = uuid4(), uuid4()
    with s["owner"].begin() as c:
        c.execute(
            text("INSERT INTO tenants(id,site_url) VALUES (:a,'https://own.invalid'),(:b,'https://foreign.invalid')"),
            {"a": tenant, "b": foreign},
        )
        for t in (tenant, foreign):
            c.execute(
                text(
                    "INSERT INTO curation_replay_records(id,tenant_id,idempotency_key,result_status) VALUES (:id,:t,'retained','acknowledged')"
                ),
                {"id": uuid4(), "t": t},
            )
    env = data["services"]["api"]["environment"]
    probe = subprocess.run(
        [sys.executable, "-c", API_PROBE, str(tenant), str(foreign), s["api"]],
        env={**os.environ, **env, "PYTHONPATH": str(APP)},
        cwd=APP,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert probe.returncode == 0, probe.stdout + probe.stderr
    assert json.loads(probe.stdout)["foreign_rows"] == 0
    print("request qualification:", probe.stdout.strip())


API_PROBE = r"""
import asyncio,json,sys
from fastapi import FastAPI
from starlette.requests import Request
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from db import session as db_session
from recognition.interface_adapters.http.deps.session import get_session
async def run():
    request=Request({'type':'http','app':FastAPI()})
    dep=get_session(request,tenant_id=sys.argv[1]); s=await anext(dep)
    try:
        assert (await s.execute(text('SELECT current_user'))).scalar_one()==sys.argv[3]
        assert (await s.execute(text("SELECT current_setting('statement_timeout')"))).scalar_one()=='10s'
        flags=(await s.execute(text('SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication FROM pg_roles WHERE rolname=current_user'))).one()
        assert flags==(False,False,False,False,False)
        own=(await s.execute(text('SELECT count(*) FROM curation_replay_records WHERE tenant_id=:t'),{'t':sys.argv[1]})).scalar_one()
        foreign=(await s.execute(text('SELECT count(*) FROM curation_replay_records WHERE tenant_id=:t'),{'t':sys.argv[2]})).scalar_one()
        assert own==1 and foreign==0, (own,foreign)
        assert (await s.execute(text('SELECT count(*) FROM pg_class WHERE relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)'))).scalar_one()==0
        assert (await s.execute(text('SELECT count(*) FROM pg_namespace WHERE nspowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)'))).scalar_one()==0
        for ddl in ['CREATE TABLE public.forbidden_runtime_ddl(id int)','CREATE SCHEMA forbidden_runtime_schema','CREATE TEMP TABLE forbidden_runtime_temp(id int)', 'ALTER TABLE curation_replay_records ADD COLUMN forbidden int']:
            try:
                async with s.begin_nested(): await s.execute(text(ddl))
            except DBAPIError as e: assert e.orig.sqlstate=='42501', e.orig.sqlstate
            else: raise AssertionError('runtime DDL unexpectedly allowed')
        try:
            async with s.begin_nested():
                await s.execute(text("INSERT INTO curation_replay_records(id,tenant_id,idempotency_key,result_status) VALUES (gen_random_uuid(),:t,'foreign-write','acknowledged')"),{'t':sys.argv[2]})
        except DBAPIError as e: assert e.orig.sqlstate=='42501'
        else: raise AssertionError('foreign write unexpectedly allowed')
        # Actual current named constraint; this is not a fixture-side check.
        try:
            async with s.begin_nested():
                await s.execute(text("INSERT INTO curation_replay_records(id,tenant_id,idempotency_key,result_status,request_fingerprint) VALUES (gen_random_uuid(),:t,'short','acknowledged','bad')"),{'t':sys.argv[1]})
        except DBAPIError as e:
            assert e.orig.sqlstate=='23514'
            assert e.orig.__cause__.constraint_name=='ck_curation_replay_request_fingerprint'
        else: raise AssertionError('invalid receipt unexpectedly allowed')
        await anext(dep,None)
        dep=get_session(request,tenant_id=None); s=await anext(dep)
        assert (await s.execute(text('SELECT count(*) FROM curation_replay_records'))).scalar_one()==0
        await anext(dep,None)
        print(json.dumps({'own_rows':own,'foreign_rows':foreign,'tenantless_rows':0,'ddl_refusals':4,'role':sys.argv[3]}))
    finally:
        await dep.aclose()
        for e in (db_session.engine,db_session.observability_engine,db_session.clustering_engine):await e.dispose()
asyncio.run(run())
"""


@pytest.mark.parametrize(
    "vector",
    [
        "wrong-target",
        "nested-dsn",
        "role-override",
        "query-password",
        "public-temp",
        "unowned-role",
        "unsafe-file",
        "vault-provider",
    ],
)
def test_refuses_unsafe_target_credentials_or_unowned_role(sandbox, vector):
    s = sandbox
    args = []
    if vector == "wrong-target":
        args = ["--expected-database", "alt_context_service"]
    elif vector in ("nested-dsn", "role-override", "query-password"):
        query = {
            "nested-dsn": {"dsn": "postgresql://owner:secret@localhost/other"},
            "role-override": {"options": "-c role=postgres"},
            "query-password": {"password": "unsafe-query-password"},
        }[vector]
        s["owner_file"].write_text(s["url"].set(query=query).render_as_string(hide_password=False))
    elif vector == "public-temp":
        with s["owner"].begin() as c:
            c.execute(text(f'GRANT TEMPORARY ON DATABASE "{s["name"]}" TO PUBLIC'))
    elif vector == "unowned-role":
        with s["owner"].begin() as c:
            c.execute(text(f'CREATE ROLE "{s["api"]}" LOGIN NOSUPERUSER NOBYPASSRLS'))
    elif vector == "unsafe-file":
        s["owner_file"].chmod(0o644)
    elif vector == "vault-provider":
        env = json.loads(s["env_file"].read_text())
        env["RECOGNITION_SECRET_BACKEND"] = "oci_vault"
        s["env_file"].write_text(json.dumps(env))
    before = roles(s)
    result = invoke(s, "--apply", *args)
    assert result.returncode != 0, "unsafe input must refuse before DDL"
    assert "refused" in result.stderr.lower(), result.stderr
    assert roles(s) == before
    assert not s["output"].exists()
    assert s["url"].password not in result.stdout + result.stderr
    assert "unsafe-query-password" not in result.stdout + result.stderr


def test_custody_loss_and_role_privilege_drift_never_adopt_or_rotate(sandbox):
    s = sandbox
    r = invoke(s, "--apply")
    assert r.returncode == 0, r.stderr
    before = {p.name: p.read_bytes() for p in s["output"].iterdir()}
    with s["owner"].begin() as c:
        c.execute(text(f'ALTER ROLE "{s["api"]}" BYPASSRLS'))
    r = invoke(s, "--apply")
    assert r.returncode != 0
    assert before == {p.name: p.read_bytes() for p in s["output"].iterdir()}
    with s["owner"].begin() as c:
        c.execute(text(f'ALTER ROLE "{s["api"]}" NOBYPASSRLS'))
    (s["output"] / "custody.json").unlink()
    r = invoke(s, "--apply")
    assert r.returncode != 0
    assert (s["output"] / "runtime.compose.json").read_bytes() == before["runtime.compose.json"]


def test_actual_worker_global_claim_retry_and_rollback_without_inference(sandbox):
    s = sandbox
    r = invoke(s, "--apply")
    assert r.returncode == 0, r.stderr
    tenants = [uuid4(), uuid4()]
    scans = [uuid4(), uuid4()]
    items = [uuid4(), uuid4()]
    clustering = [uuid4(), uuid4()]
    with s["owner"].begin() as c:
        for t, j, i, k in zip(tenants, scans, items, clustering, strict=True):
            c.execute(
                text("INSERT INTO tenants(id,site_url) VALUES (:t,:site)"),
                {"t": t, "site": "https://worker-" + t.hex + ".invalid"},
            )
            c.execute(
                text("INSERT INTO identity_scan_jobs(id,tenant_id,media_ids,total_media) VALUES (:j,:t,ARRAY[1],1)"),
                {"j": j, "t": t},
            )
            c.execute(
                text(
                    "INSERT INTO identity_scan_job_items(id,job_id,tenant_id,media_id,media_url) VALUES (:i,:j,:t,1,'https://worker.invalid/never-fetched.jpg')"
                ),
                {"i": i, "j": j, "t": t},
            )
            c.execute(
                text(
                    "INSERT INTO identity_clustering_jobs(id,tenant_id,job_type,payload) VALUES (:k,:t,'curation','{}')"
                ),
                {"k": k, "t": t},
            )
        assert (
            c.scalar(
                text(
                    "SELECT count(*) FROM pg_constraint WHERE conrelid='identity_clustering_jobs'::regclass AND conname IN ('valid_status','valid_job_type')"
                )
            )
            == 2
        )
    env = profile(s)["services"]["worker"]["environment"]
    r = subprocess.run(
        [sys.executable, "-c", WORKER_PROBE, *map(str, items), s["worker"]],
        env={**os.environ, **env, "PYTHONPATH": str(APP), "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
        cwd=APP,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads(r.stdout)
    assert report["claimed_tenants"] == 2 and report["retry_count"] == 1
    assert report["centroid_refresh_sqlstate"] == "42501"
    print("worker bounded qualification:", r.stdout.strip())


WORKER_PROBE = r"""
import asyncio,json,sys
from datetime import UTC,datetime,timedelta
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from db.settings import get_database_settings
from db.tenant_context import enable_rls_bypass
from recognition.worker.scan_worker import ScanWorker,ScanWorkerConfig
from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository
from recognition.infrastructure.repositories.cluster_repository import _refresh_mv_concurrent_with_bypass
async def run():
    # Constructor only. Never __aenter__, run_forever, handlers, model factory,
    # HTTP fetching, embedding, or fake inference. Real engine and methods below.
    w=ScanWorker(ScanWorkerConfig(postgres_dsn=get_database_settings().postgres_dsn,metrics_export_enabled=False))
    now=datetime.now(tz=UTC)
    try:
        async with w._session_factory() as s:
            assert (await s.execute(text('SELECT current_user'))).scalar_one()==sys.argv[3]
            assert (await s.execute(text('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user'))).one()==(False,False)
            repo=SqlAlchemyScanQueueRepository(s)
            assert await repo.claim_pending_items_any(limit=2,now=now)==[], 'tenantless/no-GUC negative control must close'
            await s.rollback()
            await enable_rls_bypass(s)
            claimed=await repo.claim_pending_items_any(limit=2,now=now)
            assert len(claimed)==2 and len({i.tenant_id for i in claimed})==2
            assert all(i.attempts==1 for i in claimed)
            await s.rollback()
            await enable_rls_bypass(s)
            assert (await s.execute(text("SELECT count(*) FROM identity_scan_job_items WHERE status='pending' AND attempts=0"))).scalar_one()==2
            claimed=await repo.claim_pending_items_any(limit=2,now=now)
            await s.commit()
            assert (await s.execute(text("SELECT coalesce(current_setting('app.bypass_rls',true),'')"))).scalar_one() in ('','false')
            await enable_rls_bypass(s)
            for i in claimed:assert await repo.release_item_for_retry(item_id=i.id,error_message='synthetic transport failure',attempts=i.attempts,now=now)
            await s.rollback()
            await enable_rls_bypass(s)
            assert (await s.execute(text("SELECT count(*) FROM identity_scan_job_items WHERE status='processing' AND attempts=1"))).scalar_one()==2
            for i in claimed:assert await repo.release_item_for_retry(item_id=i.id,error_message='synthetic transport failure',attempts=i.attempts,now=now)
            await s.commit()
            await enable_rls_bypass(s)
            assert await repo.claim_pending_items_any(limit=2,now=now)==[]
            retried=await repo.claim_pending_items_any(limit=2,now=now+timedelta(hours=1))
            assert len(retried)==2 and all(i.attempts==2 for i in retried)
            await s.rollback()
            # Exact worker source's curation claim and failure-persistence path.
            await enable_rls_bypass(s)
            job=await w._claim_next_clustering_job(session=s,now=now)
            assert job is not None and job.status=='running'
            job_id,tenant_id=job.id,job.tenant_id
            await enable_rls_bypass(s)
            await s.execute(text('UPDATE identity_clustering_jobs SET progress=0.75 WHERE id=:id'),{'id':job_id})
            await w._record_clustering_job_failure(exc=OSError('synthetic transport failure'),session=s,job_id=job_id,tenant_id=tenant_id)
            await enable_rls_bypass(s)
            row=(await s.execute(text('SELECT status,progress,payload FROM identity_clustering_jobs WHERE id=:id'),{'id':job_id})).one()
            assert row.status=='pending' and row.progress==0 and row.payload['retry_count']==1
            await s.rollback()
        # Required distinction: claims work; full worker MV maintenance is NOT
        # certified by an empty queue. No ownership or broad privilege granted.
        async with w._engine.connect() as c:
            c=await c.execution_options(isolation_level='AUTOCOMMIT')
            try:await _refresh_mv_concurrent_with_bypass(c)
            except DBAPIError as e:
                assert e.orig.sqlstate=='42501',e.orig.sqlstate
                refresh_state=e.orig.sqlstate
            else:raise AssertionError('ungranted centroid maintenance unexpectedly succeeded')
            assert (await c.execute(text("SELECT coalesce(current_setting('app.bypass_rls',true),'')"))).scalar_one() in ('','false')
        print(json.dumps({'claimed_tenants':2,'claim_rollback_pending':2,'retry_rollback_processing':2,'retry_count':1,'centroid_refresh_sqlstate':refresh_state,'models_executed':0}))
    finally:await w._engine.dispose()
asyncio.run(run())
"""


def test_idempotence_refuses_extra_runtime_privileges(sandbox):
    s = sandbox
    r = invoke(s, "--apply")
    assert r.returncode == 0, r.stderr
    before = {p.name: p.read_bytes() for p in s["output"].iterdir()}
    with s["owner"].begin() as c:
        c.execute(text(f'GRANT TRUNCATE ON TABLE curation_replay_records TO "{s["api"]}"'))
    r = invoke(s, "--apply")
    assert r.returncode != 0, "custody must not certify an extra TRUNCATE grant that bypasses RLS"
    assert before == {p.name: p.read_bytes() for p in s["output"].iterdir()}


def test_explicit_worker_maintenance_is_purpose_scoped(sandbox):
    s = sandbox
    r = invoke(s, "--apply", "--worker-centroid-maintain")
    assert r.returncode == 0, "explicit purpose-scoped centroid maintenance must provision: " + r.stderr
    with s["owner"].connect() as c:
        assert c.scalar(
            text("SELECT has_table_privilege(:r,'mv_identity_cluster_centroids','MAINTAIN')"), {"r": s["worker"]}
        )
        assert not c.scalar(
            text("SELECT has_table_privilege(:r,'mv_identity_cluster_centroids','MAINTAIN')"), {"r": s["api"]}
        )
        assert not c.scalar(
            text("SELECT has_table_privilege(:r,'curation_replay_records','MAINTAIN')"), {"r": s["worker"]}
        )
    env = profile(s)["services"]["worker"]["environment"]
    probe = r"""
import asyncio,json
from sqlalchemy import text
from db.session import engine
from recognition.infrastructure.repositories.cluster_repository import _refresh_mv_concurrent_with_bypass
from recognition.domain.repositories import MvRefreshOutcome
async def run():
    try:
        async with engine.connect() as c:
            c=await c.execution_options(isolation_level='AUTOCOMMIT')
            assert await _refresh_mv_concurrent_with_bypass(c)==MvRefreshOutcome.REFRESHED
            assert (await c.execute(text("SELECT coalesce(current_setting('app.bypass_rls',true),'')"))).scalar_one() in ('','false')
            assert (await c.execute(text('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user'))).one()==(False,False)
            assert (await c.execute(text("SELECT relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user) FROM pg_class WHERE oid='mv_identity_cluster_centroids'::regclass"))).scalar_one() is False
            print(json.dumps({'centroid_maintenance':'purpose-grant-qualified','owner':False,'role_bypassrls':False}))
    finally:await engine.dispose()
asyncio.run(run())
"""
    r = subprocess.run(
        [sys.executable, "-c", probe],
        env={**os.environ, **env, "PYTHONPATH": str(APP)},
        cwd=APP,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    print("optional maintenance qualification:", r.stdout.strip())
    r = invoke(s, "--apply", "--worker-centroid-maintain")
    assert r.returncode == 0, r.stderr
    r = invoke(s, "--apply")
    assert r.returncode != 0, "scope changes require separate custody, never silent grants/revocation"


def test_resolved_compose_preserves_per_service_configuration(sandbox):
    s = sandbox
    common = json.loads(s["env_file"].read_text())
    api = {**common, "HOST": "0.0.0.0", "ACX_GPU_STATE_PATH": "/run/acx/gpu-state.json"}
    worker = {**common, "RECOGNITION_SCAN_WORKER_METRICS_ADDR": "127.0.0.1"}
    s["env_file"].write_text(
        json.dumps(
            {
                "services": {
                    "api": {"environment": api},
                    "worker": {"environment": worker},
                    "postgres": {"environment": {"POSTGRES_PASSWORD": s["url"].password}},
                },
                "networks": {"backend": {"name": "acx-dev-fir-net"}},
            }
        )
    )
    r = invoke(s, "--apply")
    assert r.returncode == 0, "resolved per-service Compose environment must be preserved: " + r.stderr
    p = profile(s)
    assert p["networks"]["backend"]["name"] == "acx-dev-fir-net"
    assert p["services"]["api"]["environment"]["ACX_GPU_STATE_PATH"] == "/run/acx/gpu-state.json"
    assert "ACX_GPU_STATE_PATH" not in p["services"]["worker"]["environment"]
    assert p["services"]["worker"]["environment"]["RECOGNITION_SCAN_WORKER_METRICS_ADDR"] == "127.0.0.1"


def test_profile_publication_failure_rolls_back_new_roles(sandbox):
    sandbox["output"] = sandbox["output"].parent / "missing-parent" / "private-profile"
    result = invoke(sandbox, "--apply")
    assert result.returncode != 0
    assert roles(sandbox) == [], "filesystem failure after transactional grants must roll back both new roles"
    assert not sandbox["output"].exists()
