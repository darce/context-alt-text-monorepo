"""CLI tests for scripts/manage_api_keys.py (Slice 3 of E15-1).

Exercises the CLI entry point via direct in-process invocation; persistence
goes through SqlAlchemyApiKeyRepository against the in-memory db_session.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import subprocess
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
        ["python", "-m", "scripts.manage_api_keys", "--help"],
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
        argv=["create", "--tenant", str(tenant_row.id), "--tier", "STANDARD"],
        session=db_session,
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    raw = captured.out.strip()
    # Exactly one non-empty line in stdout, no "key_id" prefix.
    assert raw
    assert "key_id" not in captured.out
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
        argv=["list", "--tenant", str(tenant_row.id)],
        session=db_session,
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    # Full hash must not appear in listing.
    assert raw_hash not in out
    # Last 4 chars of the hash should appear.
    assert raw_hash[-4:] in out


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
        argv=["revoke", "--key-id", str(created.id)],
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
        argv=["revoke", "--key-id", str(uuid.uuid4())],
        session=db_session,
    )
    assert exit_code == 1
