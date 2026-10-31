"""Opt-in PG17 boot qualification; no models or application server are loaded.

ACX_BOOT_TEST_ADMIN_DSN must name the isolated loopback test administrator.
The historical fixture is supplied with ACX_BOOT_OLD_SCHEMA (served012 model001).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

SERVICE = Path(__file__).resolve().parents[2]
ENTRYPOINT = SERVICE / "scripts/docker-entrypoint.sh"


@pytest.fixture(scope="module")
def pg():
    raw = os.environ.get("ACX_BOOT_TEST_ADMIN_DSN")
    if not raw:
        pytest.skip("isolated PG17 bootstrap qualification is opt-in")
    url = make_url(raw)
    assert (url.drivername, url.host, url.port, url.database, url.username) == (
        "postgresql+psycopg",
        "127.0.0.1",
        15437,
        "acx_uxfir_test",
        "postgres",
    )
    prefix = "acx_boot_" + uuid4().hex[:12]
    roles = {kind: prefix + "_" + kind for kind in ("dml", "su", "bypass")}
    password = uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 5})
    databases, allocated = [], []
    engines = []
    try:
        with admin.connect() as c:
            assert c.scalar(text("SELECT current_database()")) == "acx_uxfir_test"
            assert c.scalar(text("SHOW server_version_num")) == "170011"
            assert c.scalar(text("SELECT inet_server_addr() IS NOT NULL")) is True
            for kind, role in roles.items():
                flags = (
                    "SUPERUSER"
                    if kind == "su"
                    else "NOSUPERUSER " + ("BYPASSRLS" if kind == "bypass" else "NOBYPASSRLS")
                )
                c.execute(text(f"CREATE ROLE \"{role}\" LOGIN {flags} PASSWORD '{password}'"))
                allocated.append(role)
            for kind in ("current", "old"):
                name = prefix + "_" + kind
                c.execute(text(f'CREATE DATABASE "{name}"'))
                databases.append(name)
        result = {"roles": roles, "urls": {}, "owners": {}}
        for name in databases:
            kind = name.rsplit("_", 1)[1]
            engine = create_engine(
                url.set(database=name),
                connect_args={"connect_timeout": 5, "options": "-c statement_timeout=30000 -c lock_timeout=2000"},
            )
            engines.append(engine)
            with engine.begin() as c:
                assert c.scalar(text("SELECT current_database()")) == name
                c.execute(text("CREATE EXTENSION vector"))
                c.execute(text("REVOKE CREATE ON SCHEMA public FROM PUBLIC"))
            if kind == "current":
                from scripts.sync_identity_schema import sync_schema

                sync_schema(engine)
            else:
                historical = Path(os.environ["ACX_BOOT_OLD_SCHEMA"])
                assert (
                    hashlib.sha256(historical.read_bytes()).hexdigest()
                    == "1781957e73e2646e89fb6d4cb5ecc07c013c169baa11a144d33277f7a5044092"
                )
                spec = importlib.util.spec_from_file_location("bootstrap_served012", historical)
                old = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(old)
                with engine.begin() as c, Operations.context(MigrationContext.configure(c)):
                    old.upgrade()
            with engine.begin() as c:
                c.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
                c.execute(text("INSERT INTO alembic_version VALUES ('001_identity_schema')"))
                for role in roles.values():
                    c.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
                    c.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{role}"'))
                    c.execute(text(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"'))
            result["owners"][kind] = engine
            result["urls"][kind] = {
                k: url.set(database=name, username=r, password=password).render_as_string(hide_password=False)
                for k, r in roles.items()
            }
        yield result
    finally:
        for engine in engines:
            engine.dispose()
        with admin.connect() as c:
            for name in reversed(databases):
                c.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
            for role in reversed(allocated):
                c.execute(text(f'DROP ROLE "{role}"'))
            assert not c.scalar(
                text("SELECT count(*) FROM pg_database WHERE datname = ANY(:names)"), {"names": databases}
            )
            assert not c.scalar(text("SELECT count(*) FROM pg_roles WHERE rolname = ANY(:names)"), {"names": allocated})
        admin.dispose()
        evidence = os.environ.get("ACX_BOOT_TEST_EVIDENCE")
        if evidence:
            Path(evidence).write_text(
                json.dumps({"databases": databases, "roles": allocated, "cleanup_verified": True}) + "\n"
            )


class Boot:
    def __init__(
        self,
        tmp_path,
        dsn="postgresql+psycopg://invalid:invalid@127.0.0.1:1/invalid",
        mode="verify",
        variant="recognition",
        apply=False,
    ):
        self.root = tmp_path
        self.log = tmp_path / "commands"
        self.cache = tmp_path / "cache"
        self.cache.mkdir()
        (tmp_path / ".image-variant").write_text(variant)
        (tmp_path / "blobs").mkdir()
        source = ENTRYPOINT.read_text().replace("/app", str(tmp_path)).replace("/data/cache", str(self.cache))
        self.script = tmp_path / "entrypoint.sh"
        self.script.write_text(source)
        self.env = dict(
            os.environ,
            PATH=str(tmp_path) + os.pathsep + os.environ["PATH"],
            PYTHONPATH=str(SERVICE),
            POSTGRES_SYNC_DSN=dsn,
            POSTGRES_DSN=dsn,
            RECOGNITION_BLOB_ROOT=str(tmp_path / "blobs"),
            ACX_BOOT_LOG=str(self.log),
            ACX_BOOT_PYTHON=sys.executable,
            ACX_BOOT_SERVICE=str(SERVICE),
            ACX_BOOT_APPLY="1" if apply else "0",
        )
        self.env.pop("ACX_IMAGE_VARIANT", None)
        self.env.pop("ACX_SCHEMA_BOOTSTRAP_MODE", None)
        if mode is not None:
            self.env["ACX_SCHEMA_BOOTSTRAP_MODE"] = mode
        wrapper = f"""#!{sys.executable}
import os,sys,time
from pathlib import Path
with open(os.environ["ACX_BOOT_LOG"],"a") as f:f.write(" ".join([Path(sys.argv[0]).name,*sys.argv[1:]])+"\\n")
name=Path(sys.argv[0]).name
if name=="uvicorn": raise SystemExit(0)
if os.environ.get("ACX_BOOT_BLOCK")==name:
 Path(os.environ["ACX_BOOT_LOG"]+".waiting").touch()
 time.sleep(60)
if name=="alembic":
 if os.environ["ACX_BOOT_APPLY"]!="1": raise SystemExit(91)
 os.chdir(os.environ["ACX_BOOT_SERVICE"])
 os.execv(str(Path(os.environ["ACX_BOOT_PYTHON"]).parent/"alembic"),["alembic",*sys.argv[1:]])
if sys.argv[1:3]==["-m","scripts.verify_vlm_cache"]: raise SystemExit(int(os.environ.get("ACX_BOOT_CACHE_EXIT","0")))
if sys.argv[1:3]!=["-m","scripts.verify_identity_schema"] and os.environ["ACX_BOOT_APPLY"]!="1": raise SystemExit(92)
os.execv(os.environ["ACX_BOOT_PYTHON"],[os.environ["ACX_BOOT_PYTHON"],*sys.argv[1:]])
"""
        for name in ("python", "alembic", "uvicorn"):
            path = tmp_path / name
            path.write_text(wrapper)
            path.chmod(0o755)

    def run(self):
        return subprocess.run(["sh", str(self.script)], env=self.env, capture_output=True, text=True, timeout=40)

    def commands(self):
        return self.log.read_text().splitlines() if self.log.exists() else []


def catalog(engine):
    with engine.connect() as c:
        return c.execute(
            text(
                "SELECT c.relname,a.attname,a.atttypid,a.atttypmod,a.attnotnull FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid WHERE n.nspname='public' AND a.attnum>0 AND NOT a.attisdropped ORDER BY 1,2"
            )
        ).all(), c.execute(
            text(
                "SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace='public'::regnamespace ORDER BY 1,2"
            )
        ).all()


def test_healed_dml_verify_serves_without_schema_writes(pg, tmp_path):
    before = catalog(pg["owners"]["current"])
    boot = Boot(tmp_path, pg["urls"]["current"]["dml"])
    result = boot.run()
    assert result.returncode == 0, (
        f"verify must serve without migration commands: exit={result.returncode}, commands={boot.commands()}, stderr={result.stderr}"
    )
    assert boot.commands() == [
        "python -m scripts.verify_identity_schema --runtime-role",
        "uvicorn api.main:app --host 0.0.0.0 --port 8000",
    ]
    assert catalog(pg["owners"]["current"]) == before


def test_unhealed_stamped_001_refuses_without_healing(pg, tmp_path):
    before = catalog(pg["owners"]["old"])
    boot = Boot(tmp_path, pg["urls"]["old"]["dml"])
    result = boot.run()
    assert result.returncode == 1
    assert "request_fingerprint" in result.stderr
    assert boot.commands() == ["python -m scripts.verify_identity_schema --runtime-role"]
    assert catalog(pg["owners"]["old"]) == before


@pytest.mark.parametrize("kind,flag", [("su", "SUPERUSER"), ("bypass", "BYPASSRLS")])
def test_privileged_runtime_refused_but_owner_verifier_retained(pg, tmp_path, kind, flag):
    dsn = pg["urls"]["current"][kind]
    boot = Boot(tmp_path, dsn)
    result = boot.run()
    assert result.returncode == 2
    assert flag in result.stderr
    assert not any(c.startswith("uvicorn") for c in boot.commands())
    standalone = subprocess.run(
        [sys.executable, "-m", "scripts.verify_identity_schema"],
        env=boot.env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert standalone.returncode == 0, standalone.stderr


def test_dml_role_cannot_ddl(pg):
    engine = create_engine(pg["urls"]["current"]["dml"])
    try:
        with engine.connect() as c:
            assert c.scalar(text("SELECT count(*) FROM alembic_version")) == 1
            assert c.execute(text("UPDATE alembic_version SET version_num=version_num")).rowcount == 1
            c.rollback()
            with pytest.raises(DBAPIError) as failure:
                c.execute(text("CREATE TABLE acx_boot_forbidden (id int)"))
            assert failure.value.orig.sqlstate == "42501"
        with engine.connect() as c:
            with pytest.raises(DBAPIError) as failure:
                c.execute(text("ALTER TABLE curation_replay_records ADD COLUMN acx_boot_forbidden int"))
            assert failure.value.orig.sqlstate == "42501"
    finally:
        engine.dispose()


@pytest.mark.parametrize("mode", [None, "apply"])
def test_default_apply_retains_real_chain(pg, tmp_path, mode):
    boot = Boot(tmp_path, pg["urls"]["current"]["su"], mode=mode, apply=True)
    result = boot.run()
    assert result.returncode == 0, result.stderr
    assert boot.commands() == [
        "alembic -c db/alembic.ini upgrade head",
        "python -m scripts.sync_identity_schema",
        "python -m scripts.verify_identity_schema",
        "uvicorn api.main:app --host 0.0.0.0 --port 8000",
    ]


def test_default_apply_dml_fails_at_heal(pg, tmp_path):
    boot = Boot(tmp_path, pg["urls"]["current"]["dml"], mode=None, apply=True)
    result = boot.run()
    assert result.returncode != 0
    assert "permission denied" in result.stderr or "must be owner" in result.stderr
    assert boot.commands() == ["alembic -c db/alembic.ini upgrade head", "python -m scripts.sync_identity_schema"]


@pytest.mark.parametrize("mode", ["invalid", "", "VERIFY"])
def test_invalid_mode_fails_before_any_db_command(tmp_path, mode):
    boot = Boot(tmp_path, mode=mode)
    result = boot.run()
    assert result.returncode != 0
    assert "ACX_SCHEMA_BOOTSTRAP_MODE" in result.stderr
    assert boot.commands() == []


@pytest.mark.parametrize("drift", ["type", "nullable", "missing_check", "wrong_check", "not_valid"])
def test_runtime_checks_fingerprint_contract(pg, tmp_path, drift):
    owner = pg["owners"]["current"]
    # Restore the committed isolated mutation even if the verifier/test fails.
    with owner.connect() as c:
        # DDL must be committed for the subprocess, so restore explicitly below.
        changes = {
            "type": "ALTER TABLE curation_replay_records ALTER COLUMN request_fingerprint TYPE varchar(65)",
            "nullable": "ALTER TABLE curation_replay_records ALTER COLUMN request_fingerprint SET NOT NULL",
            "missing_check": "ALTER TABLE curation_replay_records DROP CONSTRAINT ck_curation_replay_request_fingerprint",
            "wrong_check": "ALTER TABLE curation_replay_records DROP CONSTRAINT ck_curation_replay_request_fingerprint, ADD CONSTRAINT ck_curation_replay_request_fingerprint CHECK (true)",
            "not_valid": "ALTER TABLE curation_replay_records DROP CONSTRAINT ck_curation_replay_request_fingerprint, ADD CONSTRAINT ck_curation_replay_request_fingerprint CHECK (request_fingerprint IS NULL OR length(request_fingerprint)=64) NOT VALID",
        }
        try:
            c.execute(text(changes[drift]))
            c.commit()
            before = catalog(owner)
            boot = Boot(tmp_path, pg["urls"]["current"]["dml"])
            standalone = subprocess.run(
                [sys.executable, "-m", "scripts.verify_identity_schema", "--runtime-role"],
                env=boot.env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert standalone.returncode in (1, 2), "structural verifier accepted drifted request_fingerprint contract"
            result = boot.run()
            assert result.returncode in (1, 2)
            assert "request_fingerprint" in result.stderr
            assert boot.commands() == ["python -m scripts.verify_identity_schema --runtime-role"]
            assert catalog(owner) == before
        finally:
            c.rollback()
            c.execute(
                text(
                    "ALTER TABLE curation_replay_records DROP CONSTRAINT IF EXISTS ck_curation_replay_request_fingerprint"
                )
            )
            c.execute(
                text(
                    "ALTER TABLE curation_replay_records ALTER COLUMN request_fingerprint DROP NOT NULL, ALTER COLUMN request_fingerprint TYPE varchar(64)"
                )
            )
            c.execute(
                text(
                    "ALTER TABLE curation_replay_records ADD CONSTRAINT ck_curation_replay_request_fingerprint CHECK (request_fingerprint IS NULL OR length(request_fingerprint)=64)"
                )
            )
            c.commit()


@pytest.mark.parametrize("guard", ["missing_variant", "bad_variant", "mismatch", "blob"])
def test_boot_guards_run_before_db(tmp_path, guard):
    boot = Boot(tmp_path)
    if guard == "missing_variant":
        (tmp_path / ".image-variant").unlink()
    if guard == "bad_variant":
        (tmp_path / ".image-variant").write_text("unknown")
    if guard == "mismatch":
        boot.env["ACX_IMAGE_VARIANT"] = "vlm"
    if guard == "blob":
        boot.env["RECOGNITION_BLOB_ROOT"] = str(tmp_path / "absent")
    result = boot.run()
    assert result.returncode != 0
    assert "FATAL" in result.stderr
    assert boot.commands() == []


def test_vlm_cache_failure_prevents_server(pg, tmp_path):
    boot = Boot(tmp_path, pg["urls"]["current"]["dml"], variant="vlm")
    boot.env["ACX_BOOT_CACHE_EXIT"] = "17"
    result = boot.run()
    assert result.returncode == 17
    assert boot.commands() == [
        "python -m scripts.verify_identity_schema --runtime-role",
        "python -m scripts.verify_vlm_cache",
    ]


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_verify_boot_forwards_signals(pg, tmp_path, sig):
    boot = Boot(tmp_path, pg["urls"]["current"]["dml"])
    boot.env["ACX_BOOT_BLOCK"] = "python"
    process = subprocess.Popen(
        ["sh", str(boot.script)], env=boot.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        deadline = time.monotonic() + 10
        while not Path(str(boot.log) + ".waiting").exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert process.poll() is None
        process.send_signal(sig)
        _, stderr = process.communicate(timeout=10)
        assert process.returncode == 143
        assert "SIGTERM during boot chain" in stderr
        assert boot.commands() == ["python -m scripts.verify_identity_schema --runtime-role"]
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


@pytest.mark.parametrize("runtime_kind,expected", [("dml", 0), ("su", 2), ("bypass", 2)])
def test_verify_uses_request_dsn_without_owner_connection(pg, tmp_path, runtime_kind, expected):
    boot = Boot(tmp_path, pg["urls"]["current"][runtime_kind])
    boot.env["POSTGRES_SYNC_DSN"] = "postgresql+psycopg://owner:unusable@127.0.0.1:1/unusable"
    result = boot.run()
    assert result.returncode == expected, result.stderr
    assert boot.commands()[0] == "python -m scripts.verify_identity_schema --runtime-role"
    assert any(c.startswith("uvicorn") for c in boot.commands()) == (expected == 0)


def test_runtime_refuses_privileged_login_with_effective_dml_role(pg, tmp_path):
    dsn = make_url(pg["urls"]["current"]["su"]).update_query_dict({"options": "-c role=" + pg["roles"]["dml"]})
    boot = Boot(tmp_path, dsn.render_as_string(hide_password=False))
    result = boot.run()
    assert result.returncode == 2
    assert "session_user=" + pg["roles"]["su"] + " has SUPERUSER" in result.stderr
    assert not any(c.startswith("uvicorn") for c in boot.commands())


@pytest.mark.parametrize("disable_cache", ["0", "1"])
def test_verify_actual_asyncpg_request_dsn(pg, tmp_path, disable_cache):
    dsn = make_url(pg["urls"]["current"]["dml"]).set(drivername="postgresql+asyncpg")
    boot = Boot(tmp_path, dsn.render_as_string(hide_password=False))
    boot.env["DB_DISABLE_STMT_CACHE"] = disable_cache
    result = boot.run()
    assert result.returncode == 0, result.stderr
    assert boot.commands()[-1].startswith("uvicorn")


def test_verify_database_unreachable_fails_closed(tmp_path):
    boot = Boot(tmp_path)
    result = boot.run()
    assert result.returncode == 3
    assert "identity schema verification could not run" in result.stderr
    assert boot.commands() == ["python -m scripts.verify_identity_schema --runtime-role"]


def test_vlm_unreadable_cache_guard_retained(pg, tmp_path):
    boot = Boot(tmp_path, pg["urls"]["current"]["dml"], variant="vlm")
    boot.cache.chmod(0)
    try:
        assert not os.access(boot.cache, os.R_OK), "qualification must run as an unprivileged OS user"
        result = boot.run()
        assert result.returncode == 1
        assert "not readable by uid" in result.stderr
        assert boot.commands() == ["python -m scripts.verify_identity_schema --runtime-role"]
    finally:
        boot.cache.chmod(0o700)


def test_blob_unwritable_guard_retained(tmp_path):
    boot = Boot(tmp_path)
    blob = tmp_path / "blobs"
    blob.chmod(0o500)
    try:
        assert not os.access(blob, os.W_OK), "qualification must run as an unprivileged OS user"
        result = boot.run()
        assert result.returncode == 1
        assert "not writable by uid" in result.stderr
        assert boot.commands() == []
    finally:
        blob.chmod(0o700)
