"""CLI tests for scripts/manage_api_keys.py (Slice 3 of E15-1).

Exercises the CLI entry point via direct in-process invocation; persistence
goes through SqlAlchemyApiKeyRepository against the in-memory db_session.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import subprocess
import sys
import uuid
from datetime import datetime
from types import ModuleType, SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Tenant
from recognition.infrastructure.repositories import SqlAlchemyApiKeyRepository


def _set_database_dsn(monkeypatch, dsn: str) -> None:
    from db import settings as db_settings

    monkeypatch.setattr(
        db_settings,
        "get_database_settings",
        lambda: SimpleNamespace(postgres_dsn=dsn),
    )


class _FakeSession:
    def __init__(self, records: list[SimpleNamespace]) -> None:
        self.records = records
        self.commits = 0
        self.listed_tenant_id: uuid.UUID | None = None
        self.include_revoked = False
        self.revoked_key_id: uuid.UUID | None = None

    async def commit(self) -> None:
        self.commits += 1


class _FakeApiKeyRepository:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def list_for_tenant(self, tenant_id: uuid.UUID, *, include_revoked: bool = False):
        self.session.listed_tenant_id = tenant_id
        self.session.include_revoked = include_revoked
        return [
            row
            for row in self.session.records
            if row.tenant_id == tenant_id and (include_revoked or row.revoked_at is None)
        ]

    async def revoke(self, key_id: uuid.UUID):
        record = next((row for row in self.session.records if row.id == key_id), None)
        if record is None:
            raise LookupError(f"API key {key_id} not found")
        self.session.revoked_key_id = key_id
        record.revoked_at = datetime.now().astimezone()
        return record


@pytest_asyncio.fixture
async def tenant_row(db_session: AsyncSession) -> Tenant:
    t = Tenant(site_url="http://cli.test")
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return t


def _import_cli() -> ModuleType:
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "manage_api_keys.py"
    spec = importlib.util.spec_from_file_location("manage_api_keys_cli", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_module_importable() -> None:
    cli = _import_cli()
    assert hasattr(cli, "main")


def test_cli_module_exec_help_succeeds() -> None:
    app_root = pathlib.Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, "-m", "scripts.manage_api_keys", "--help"],
        cwd=app_root,
        capture_output=True,
        text=True,
        env={**os.environ},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "usage: manage_api_keys" in result.stdout
    assert "create a new API key" in result.stdout


@pytest.mark.asyncio
async def test_create_prints_raw_key_only_to_stdout(
    db_session: AsyncSession,
    tenant_row: Tenant,
    capsys,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ACX_ENV", "local")
    cli = _import_cli()
    exit_code = await cli.run(
        argv=["--env", "local", "create", "--tenant", str(tenant_row.id), "--tier", "STANDARD"],
        session=db_session,
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    api_key_line = captured.out.strip()
    assert api_key_line.startswith("api_key=")
    raw = api_key_line.removeprefix("api_key=")
    assert "key_id=" in captured.err

    # Hash matches a stored row.
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    repo = SqlAlchemyApiKeyRepository(db_session)
    record = await repo.get_by_hash(hashed)
    assert record is not None
    assert str(record.tenant_id) == str(tenant_row.id)


@pytest.mark.asyncio
async def test_list_masks_hash(db_session: AsyncSession, tenant_row: Tenant, capsys, monkeypatch) -> None:
    monkeypatch.setenv("ACX_ENV", "local")
    cli = _import_cli()
    repo = SqlAlchemyApiKeyRepository(db_session)
    raw_hash = hashlib.sha256(b"sample").hexdigest()
    await repo.create(
        tenant_id=tenant_row.id,
        hashed_key=raw_hash,
        rate_limit_tier="STANDARD",
    )
    await db_session.commit()

    capsys.readouterr()  # clear
    exit_code = await cli.run(
        argv=["--env", "local", "list", "--tenant", str(tenant_row.id)],
        session=db_session,
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    # Full hash must not appear in listing.
    assert raw_hash not in out
    # The hash tail must be self-labeled so operators do not confuse it with
    # the raw-key tail. E15-12-BR-04: bare `dbfb`-style output mislead the
    # local-mode smoke into thinking the wrong key was pasted.
    expected_tail = raw_hash[-4:]
    assert f"hash:{expected_tail}" in out
    # The unprefixed last-4 alone must not appear as a standalone token.
    tokens = out.replace("\n", "\t").split("\t")
    assert expected_tail not in tokens, (
        f"raw last-4 hash tail '{expected_tail}' must not appear as a bare "
        f"column; expected `hash:{expected_tail}` instead. Output was: {out!r}"
    )


@pytest.mark.asyncio
async def test_revoke_sets_revoked_at(db_session: AsyncSession, tenant_row: Tenant, capsys, monkeypatch) -> None:
    monkeypatch.setenv("ACX_ENV", "local")
    cli = _import_cli()
    repo = SqlAlchemyApiKeyRepository(db_session)
    raw_hash = hashlib.sha256(b"revoke-me").hexdigest()
    created = await repo.create(
        tenant_id=tenant_row.id,
        hashed_key=raw_hash,
        rate_limit_tier="STANDARD",
    )
    await db_session.commit()

    exit_code = await cli.run(
        argv=["--env", "local", "revoke", "--key-id", str(created.id)],
        session=db_session,
    )
    assert exit_code == 0
    err = capsys.readouterr().err
    assert f"revoked key_id={created.id}" in err

    # Subsequent lookup by hash returns None (filtered).
    assert await repo.get_by_hash(raw_hash) is None


@pytest.mark.asyncio
async def test_revoke_unknown_key_exits_1(db_session: AsyncSession, capsys, monkeypatch) -> None:
    monkeypatch.setenv("ACX_ENV", "local")
    cli = _import_cli()
    exit_code = await cli.run(
        argv=["--env", "local", "revoke", "--key-id", str(uuid.uuid4())],
        session=db_session,
    )
    assert exit_code == 1


def test_cli_requires_env_flag() -> None:
    cli = _import_cli()
    import asyncio

    with pytest.raises(SystemExit):
        asyncio.run(cli.run(argv=["create", "--tenant", str(uuid.uuid4())]))


@pytest.mark.asyncio
async def test_env_prod_rejects_localhost_dsn(
    db_session: AsyncSession,
    tenant_row: Tenant,
    capsys,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ACX_ENV", "prod")
    cli = _import_cli()
    # session is supplied, so no new DSN is opened — BR-02's guard must
    # still reject the env/DSN mismatch against the configured DSN.
    exit_code = await cli.run(
        argv=["--env", "prod", "list", "--tenant", str(tenant_row.id)],
        session=db_session,
    )
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "env=prod" in err
    assert "localhost" in err or "127.0.0.1" in err or "local" in err


@pytest.mark.asyncio
async def test_env_local_rejects_remote_dsn(
    db_session: AsyncSession,
    tenant_row: Tenant,
    capsys,
    monkeypatch,
) -> None:
    cli = _import_cli()
    monkeypatch.delenv("ACX_ENV", raising=False)
    monkeypatch.setenv(
        "POSTGRES_DSN",
        "postgresql+asyncpg://u:p@db.altcontext.internal:5432/prod",
    )
    from db import settings as db_settings

    db_settings.get_database_settings.cache_clear()

    exit_code = await cli.run(
        argv=["--env", "local", "list", "--tenant", str(tenant_row.id)],
        session=db_session,
    )
    db_settings.get_database_settings.cache_clear()
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "env=local" in err


@pytest.mark.asyncio
async def test_tenant_create_bootstraps_row(db_session: AsyncSession, capsys, monkeypatch) -> None:
    monkeypatch.setenv("ACX_ENV", "local")
    cli = _import_cli()
    tenant_id = uuid.uuid4()

    exit_code = await cli.run(
        argv=[
            "--env",
            "local",
            "tenant",
            "create",
            "--tenant",
            str(tenant_id),
            "--site-url",
            "https://tenant.example.test",
        ],
        session=db_session,
    )

    assert exit_code == 0
    tenant = await db_session.get(Tenant, tenant_id)
    assert tenant is not None
    assert tenant.site_url == "https://tenant.example.test"
    assert f"tenant_id={tenant_id}" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_tenant_list_prints_bootstrapped_rows(db_session: AsyncSession, capsys, monkeypatch) -> None:
    monkeypatch.setenv("ACX_ENV", "local")
    db_session.add(Tenant(id=uuid.uuid4(), site_url="https://first.example.test"))
    db_session.add(Tenant(id=uuid.uuid4(), site_url="https://second.example.test"))
    await db_session.commit()

    cli = _import_cli()
    exit_code = await cli.run(argv=["--env", "local", "tenant", "list"], session=db_session)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "https://first.example.test" in out
    assert "https://second.example.test" in out


def test_validate_env_vs_dsn_unit() -> None:
    cli = _import_cli()
    # prod must reject local hosts
    assert cli._validate_env_vs_dsn("prod", "postgresql+asyncpg://u:p@localhost:5432/db") is not None
    assert cli._validate_env_vs_dsn("prod", "postgresql+asyncpg://u:p@127.0.0.1:5432/db") is not None
    assert cli._validate_env_vs_dsn("prod", "postgresql+asyncpg://u:p@host.local:5432/db") is not None
    # prod accepts real remote hosts
    assert cli._validate_env_vs_dsn("prod", "postgresql+asyncpg://u:p@db.altcontext.internal:5432/db") is None
    # local/dev accept loopback and *.local
    assert cli._validate_env_vs_dsn("local", "postgresql+asyncpg://u:p@localhost:5432/db") is None
    assert cli._validate_env_vs_dsn("local", "postgresql+asyncpg://u:p@127.0.0.1:5432/db") is None
    assert cli._validate_env_vs_dsn("dev", "postgresql+asyncpg://u:p@localhost:5432/db") is None
    # local/dev reject remote hosts
    assert cli._validate_env_vs_dsn("local", "postgresql+asyncpg://u:p@db.altcontext.internal:5432/db") is not None
    assert cli._validate_env_vs_dsn("dev", "postgresql+asyncpg://u:p@db.altcontext.internal:5432/db") is not None
    # Only the explicitly matched dev runtime may use Docker Compose's
    # postgres service alias. Other remote dev hosts remain refused.
    assert (
        cli._validate_env_vs_dsn(
            "dev",
            "postgresql+asyncpg://u:p@postgres:5432/db",
            configured_env="dev",
        )
        is None
    )
    assert (
        cli._validate_env_vs_dsn(
            "dev",
            "postgresql+asyncpg://u:p@db.altcontext.internal:5432/db",
            configured_env="dev",
        )
        is not None
    )
    # Configured local/prod environments retain the original safety checks.
    assert (
        cli._validate_env_vs_dsn(
            "local",
            "postgresql+asyncpg://u:p@db.altcontext.internal:5432/db",
            configured_env="local",
        )
        is not None
    )
    assert (
        cli._validate_env_vs_dsn(
            "prod",
            "postgresql+asyncpg://u:p@localhost:5432/db",
            configured_env="prod",
        )
        is not None
    )


@pytest.mark.asyncio
async def test_acx_env_dev_allows_docker_postgres_dsn_for_list(
    capsys,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ACX_ENV", "dev")
    _set_database_dsn(monkeypatch, "postgresql+asyncpg://u:p@postgres:5432/dev")
    cli = _import_cli()
    raw_hash = hashlib.sha256(b"docker-list").hexdigest()
    tenant_id = uuid.uuid4()
    session = _FakeSession(
        [
            SimpleNamespace(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                api_key_hash=raw_hash,
                created_at=None,
                last_used_at=None,
                expires_at=None,
                revoked_at=None,
            )
        ]
    )
    monkeypatch.setattr(cli, "SqlAlchemyApiKeyRepository", _FakeApiKeyRepository)

    exit_code = await cli.run(
        argv=["--env", "dev", "list", "--tenant", str(tenant_id)],
        session=session,
    )

    assert exit_code == 0
    assert f"hash:{raw_hash[-4:]}" in capsys.readouterr().out
    assert session.listed_tenant_id == tenant_id
    assert session.include_revoked is False


@pytest.mark.asyncio
async def test_acx_env_dev_allows_docker_postgres_dsn_for_revoke(
    capsys,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ACX_ENV", "dev")
    _set_database_dsn(monkeypatch, "postgresql+asyncpg://u:p@postgres:5432/dev")
    cli = _import_cli()
    raw_hash = hashlib.sha256(b"docker-revoke").hexdigest()
    created = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        api_key_hash=raw_hash,
        created_at=None,
        last_used_at=None,
        expires_at=None,
        revoked_at=None,
    )
    session = _FakeSession([created])
    monkeypatch.setattr(cli, "SqlAlchemyApiKeyRepository", _FakeApiKeyRepository)

    exit_code = await cli.run(
        argv=["--env", "dev", "revoke", "--key-id", str(created.id)],
        session=session,
    )

    assert exit_code == 0
    assert f"revoked key_id={created.id}" in capsys.readouterr().err
    assert created.revoked_at is not None
    assert session.commits == 1
    assert session.revoked_key_id == created.id


@pytest.mark.asyncio
@pytest.mark.parametrize("configured_env", ["prod", "", "staging"])
async def test_mismatched_or_invalid_acx_env_refuses_before_settings_or_session_use(
    configured_env: str,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("ACX_ENV", configured_env)
    from db import settings as db_settings

    def unexpected_settings_read():
        raise AssertionError("runtime environment must be checked before database settings")

    monkeypatch.setattr(db_settings, "get_database_settings", unexpected_settings_read)
    cli = _import_cli()
    session = object()

    async def unexpected_command(*_args, **_kwargs):
        raise AssertionError("runtime environment must be checked before CLI operations")

    monkeypatch.setattr(cli, "_cmd_list", unexpected_command)
    exit_code = await cli.run(
        argv=["--env", "dev", "list", "--tenant", str(uuid.uuid4())],
        session=session,
    )

    assert exit_code == 1
    assert "ACX_ENV" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_mismatched_acx_env_refuses_before_settings_and_session_factory(monkeypatch, capsys) -> None:
    monkeypatch.setenv("ACX_ENV", "prod")
    from db import session as db_session_module
    from db import settings as db_settings

    def unexpected_settings_read():
        raise AssertionError("ACX_ENV mismatch must be checked before database settings")

    def unexpected_session_factory():
        raise AssertionError("ACX_ENV mismatch must be checked before opening a session")

    monkeypatch.setattr(db_settings, "get_database_settings", unexpected_settings_read)
    monkeypatch.setattr(db_session_module, "async_session_factory", unexpected_session_factory)
    cli = _import_cli()
    exit_code = await cli.run(argv=["--env", "dev", "list", "--tenant", str(uuid.uuid4())])

    assert exit_code == 1
    assert "ACX_ENV" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_matching_local_acx_env_still_rejects_remote_dsn(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("ACX_ENV", "local")
    _set_database_dsn(monkeypatch, "postgresql+asyncpg://u:p@db.altcontext.internal:5432/prod")
    cli = _import_cli()

    exit_code = await cli.run(
        argv=["--env", "local", "list", "--tenant", str(uuid.uuid4())],
        session=object(),
    )

    assert exit_code == 1
    assert "env=local" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_unset_acx_env_rejects_docker_postgres_before_session_factory(monkeypatch, capsys) -> None:
    monkeypatch.delenv("ACX_ENV", raising=False)
    _set_database_dsn(monkeypatch, "postgresql+asyncpg://u:p@postgres:5432/dev")
    from db import session as db_session_module

    def unexpected_session_factory():
        raise AssertionError("DSN-only dev fallback must refuse Docker postgres before opening a session")

    monkeypatch.setattr(db_session_module, "async_session_factory", unexpected_session_factory)
    cli = _import_cli()

    exit_code = await cli.run(argv=["--env", "dev", "revoke", "--key-id", str(uuid.uuid4())])

    assert exit_code == 1
    assert "env=dev" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_dev_docker_list_and_revoke_persist_rollback(
    db_session: AsyncSession,
    tenant_row: Tenant,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("ACX_ENV", "dev")
    _set_database_dsn(monkeypatch, "postgresql+asyncpg://u:p@postgres:5432/dev")
    cli = _import_cli()
    raw_hash = hashlib.sha256(b"dev-rollback-fixture").hexdigest()
    repo = SqlAlchemyApiKeyRepository(db_session)
    created = await repo.create(tenant_id=tenant_row.id, hashed_key=raw_hash, rate_limit_tier="STANDARD")
    await db_session.commit()

    listed = await cli.run(
        argv=["--env", "dev", "list", "--tenant", str(tenant_row.id)],
        session=db_session,
    )
    assert listed == 0
    output = capsys.readouterr().out
    assert output.split("\t", 1)[0] == str(created.id)
    assert f"hash:{raw_hash[-4:]}" in output
    assert raw_hash not in output

    revoked = await cli.run(argv=["--env", "dev", "revoke", "--key-id", str(created.id)], session=db_session)
    assert revoked == 0
    assert f"revoked key_id={created.id} revoked_at=" in capsys.readouterr().err
    await db_session.refresh(created)
    assert created.revoked_at is not None
    assert await repo.get_by_hash(raw_hash) is None
