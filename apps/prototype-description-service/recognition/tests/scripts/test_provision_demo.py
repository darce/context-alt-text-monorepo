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

    url_line = next(line for line in captured.out.splitlines() if line.startswith("demo_url="))
    slug = url_line.removeprefix("demo_url=https://demo.altcontext.com/x/")
    assert _BASE58_RE.match(slug)

    raw_line = next(line for line in captured.out.splitlines() if line.startswith("api_key="))
    raw = raw_line.removeprefix("api_key=")
    assert raw
    assert raw not in captured.err  # metadata stderr must not echo raw key

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


def test_cli_help_documents_account_kinds() -> None:
    app_root = pathlib.Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, "-m", "scripts.provision_demo", "provision", "--help"],
        cwd=app_root,
        capture_output=True,
        text=True,
        env={**os.environ},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--account" in result.stdout
    assert "ci" in result.stdout
    assert "--admin-user" in result.stdout


@pytest.mark.asyncio
async def test_cli_provision_ci_requires_admin_user(db_session: AsyncSession, capsys) -> None:
    cli = _import_cli()
    exit_code = await cli.run(
        argv=["--env", "local", "provision", "--label", "ACX CI", "--account", "ci"],
        session=db_session,
    )
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "error:" in captured.err
    assert "admin-user" in captured.err


@pytest.mark.asyncio
async def test_cli_provision_ci_rejects_admin_collision(db_session: AsyncSession, capsys) -> None:
    cli = _import_cli()
    exit_code = await cli.run(
        argv=[
            "--env",
            "local",
            "provision",
            "--label",
            "acx-demo-admin",
            "--account",
            "ci",
            "--admin-user",
            "acx-demo-admin",
        ],
        session=db_session,
    )
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "error:" in captured.err
    assert "differ" in captured.err


@pytest.mark.asyncio
async def test_cli_provision_ci_uses_reduced_quota(db_session: AsyncSession, capsys) -> None:
    cli = _import_cli()
    exit_code = await cli.run(
        argv=[
            "--env",
            "local",
            "provision",
            "--label",
            "ACX CI",
            "--seed",
            "default",
            "--account",
            "ci",
            "--admin-user",
            "acx-demo-admin",
        ],
        session=db_session,
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "account=ci" in captured.err
    assert "api_key=" in captured.out
    url_line = next(line for line in captured.out.splitlines() if line.startswith("demo_url="))
    slug = url_line.removeprefix("demo_url=https://demo.altcontext.com/x/")
    instance = await db_session.get(DemoInstance, slug)
    assert instance is not None
    assert instance.recognition_quota == cli.CI_RECOGNITION_QUOTA
    assert instance.recognition_quota < 200
    assert "acx-demo-admin" not in captured.out


def test_makefile_d_issue_demo_ci_account_wraps_cli() -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[5]
    mk = repo_root / "Makefile.d" / "demo-auth.mk"
    text = mk.read_text(encoding="utf-8")
    assert "issue-demo-ci-account:" in text
    assert "python -m scripts.provision_demo" in text
    assert "--account ci" in text
    assert "--admin-user" in text
    assert "Co-Authored-By" not in text
