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

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Tenant
from recognition.infrastructure.repositories import SqlAlchemyApiKeyRepository


@pytest_asyncio.fixture
async def tenant_row(db_session: AsyncSession) -> Tenant:
    t = Tenant(site_url="http://cli.test")
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return t


def _import_cli():
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "manage_api_keys.py"
    spec = importlib.util.spec_from_file_location("manage_api_keys_cli", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
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
        env={**os.environ, "PYENV_VERSION": os.environ.get("PYENV_VERSION", "description-service")},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "usage: manage_api_keys" in result.stdout
    assert "create a new API key" in result.stdout


@pytest.mark.asyncio
async def test_create_prints_raw_key_only_to_stdout(db_session: AsyncSession, tenant_row: Tenant, capsys) -> None:
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
async def test_list_masks_hash(db_session: AsyncSession, tenant_row: Tenant, capsys) -> None:
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
async def test_revoke_sets_revoked_at(db_session: AsyncSession, tenant_row: Tenant, capsys) -> None:
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
async def test_revoke_unknown_key_exits_1(db_session: AsyncSession, capsys) -> None:
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
async def test_env_prod_rejects_localhost_dsn(db_session: AsyncSession, tenant_row: Tenant, capsys) -> None:
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
async def test_env_local_rejects_remote_dsn(db_session: AsyncSession, tenant_row: Tenant, capsys, monkeypatch) -> None:
    cli = _import_cli()
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
async def test_tenant_create_bootstraps_row(db_session: AsyncSession, capsys) -> None:
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
async def test_tenant_list_prints_bootstrapped_rows(db_session: AsyncSession, capsys) -> None:
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
