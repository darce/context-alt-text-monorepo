"""CLI tests for scripts/provision_demo.py (DS-3)."""

from __future__ import annotations

import hashlib
import os
import pathlib
import re
import subprocess
import sys
from types import ModuleType

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import DemoInstance
from recognition.application.services.demo_provisioning_service import BASE58_ALPHABET, DEFAULT_SLUG_LENGTH
from recognition.infrastructure.repositories import SqlAlchemyApiKeyRepository

_BASE58_RE = re.compile(f"^[{re.escape(BASE58_ALPHABET)}]{{{DEFAULT_SLUG_LENGTH}}}$")


def _import_cli() -> ModuleType:
    import importlib.util

    path = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "provision_demo.py"
    spec = importlib.util.spec_from_file_location("provision_demo_cli", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_module_importable() -> None:
    cli = _import_cli()
    assert hasattr(cli, "main")
    assert hasattr(cli, "run")


def test_cli_help_succeeds() -> None:
    app_root = pathlib.Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, "-m", "scripts.provision_demo", "--help"],
        cwd=app_root,
        capture_output=True,
        text=True,
        env={**os.environ},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "provision" in result.stdout
    assert "expire" in result.stdout


@pytest.mark.asyncio
async def test_cli_provision_and_expire_round_trip(db_session: AsyncSession, capsys) -> None:
    cli = _import_cli()

    exit_code = await cli.run(
        argv=["--env", "local", "provision", "--label", "Test Gallery", "--seed", "default"],
        session=db_session,
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "demo_url=https://demo.altcontext.com/x/" in captured.out
    assert "api_key=" in captured.out
    assert "wp_username=demo-" in captured.out
    assert "wp_password=" in captured.out

    url_line = next(line for line in captured.out.splitlines() if line.startswith("demo_url="))
    slug = url_line.removeprefix("demo_url=https://demo.altcontext.com/x/")
    assert _BASE58_RE.match(slug)

    raw_line = next(line for line in captured.out.splitlines() if line.startswith("api_key="))
    raw = raw_line.removeprefix("api_key=")
    assert raw
    assert raw not in captured.err  # metadata stderr must not echo raw key

    wp_password = next(line for line in captured.out.splitlines() if line.startswith("wp_password=")).removeprefix(
        "wp_password="
    )
    assert wp_password
    assert wp_password not in captured.err

    instance = await db_session.get(DemoInstance, slug)
    assert instance is not None
    assert instance.tenant_id is not None
    assert instance.recognition_quota == 200
    assert instance.revoked is False
    hashed = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert instance.api_key_ref == hashed
    assert raw not in instance.api_key_ref

    found = await SqlAlchemyApiKeyRepository(db_session).get_by_hash(hashed)
    assert found is not None

    expire_code = await cli.run(
        argv=["--env", "local", "expire", "--slug", slug],
        session=db_session,
    )
    assert expire_code == 0
    await db_session.refresh(instance)
    assert instance.revoked is True


@pytest.mark.asyncio
async def test_cli_provision_unknown_seed(db_session: AsyncSession, capsys) -> None:
    cli = _import_cli()
    exit_code = await cli.run(
        argv=["--env", "local", "provision", "--label", "X", "--seed", "nope"],
        session=db_session,
    )
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "error:" in captured.err
