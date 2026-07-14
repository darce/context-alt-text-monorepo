"""AP-7: provision_customer CLI + service tests.

Covers: create path, plan/label persistence, idempotency on email, raw key once,
auth hash acceptance, no plaintext key in audit payload.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import pathlib
import subprocess
import sys
import uuid
from types import ModuleType

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ApiKey, AuditEvent, Tenant
from recognition.application.services.customer_provision_service import (
    customer_site_url,
    normalize_email,
    plan_to_tier,
    provision_customer,
)
from recognition.config.security import RateLimitTier
from recognition.infrastructure.repositories import SqlAlchemyApiKeyRepository


def _import_cli() -> ModuleType:
    path = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "provision_customer.py"
    spec = importlib.util.spec_from_file_location("provision_customer_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_module_help_succeeds() -> None:
    app_root = pathlib.Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, "-m", "scripts.provision_customer", "--help"],
        cwd=app_root,
        capture_output=True,
        text=True,
        env={**os.environ},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "provision_customer" in result.stdout
    assert "--email" in result.stdout


def test_normalize_email_and_plan_helpers() -> None:
    assert normalize_email("  Alice@Example.COM ") == "alice@example.com"
    with pytest.raises(ValueError):
        normalize_email("not-an-email")
    assert plan_to_tier("pro") is RateLimitTier.PRO
    assert plan_to_tier("FREE") is RateLimitTier.STANDARD
    assert customer_site_url("bob@example.com") == "mailto:bob@example.com"


@pytest.mark.asyncio
async def test_provision_creates_tenant_key_and_prints_once(db_session: AsyncSession, capsys) -> None:
    cli = _import_cli()
    email = "concierge-test@example.com"

    exit_code = await cli.run(
        argv=[
            "--env",
            "local",
            "--email",
            email,
            "--plan",
            "pro",
            "--label",
            "Test Co",
        ],
        session=db_session,
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "status=created" in out
    assert "api_key=" in out
    assert "tenant_id=" in out
    assert "ACX_RECOGNITION_URL" in out
    assert "ACX_RECOGNITION_API_KEY" in out
    assert "ACX_RECOGNITION_TENANT_ID" in out

    raw = next(line for line in out.splitlines() if line.startswith("api_key=")).removeprefix("api_key=")
    assert raw
    # Exactly one api_key= line.
    assert sum(1 for line in out.splitlines() if line.startswith("api_key=")) == 1

    tenant = (await db_session.execute(select(Tenant).where(Tenant.primary_contact_email == email))).scalar_one()
    assert tenant.plan == "pro"
    assert tenant.display_name == "Test Co"
    assert tenant.site_url == "mailto:concierge-test@example.com"

    hashed = hashlib.sha256(raw.encode()).hexdigest()
    repo = SqlAlchemyApiKeyRepository(db_session)
    record = await repo.get_by_hash(hashed)
    assert record is not None
    assert str(record.tenant_id) == str(tenant.id)
    assert record.rate_limit_tier == RateLimitTier.PRO.value
    assert record.expires_at is None

    # Audit must not retain the raw key.
    events = (await db_session.execute(select(AuditEvent).where(AuditEvent.tenant_id == tenant.id))).scalars().all()
    assert events
    for event in events:
        payload = event.payload or {}
        assert raw not in str(payload)
        assert "api_key" not in payload


@pytest.mark.asyncio
async def test_provision_idempotent_on_email_no_second_key(db_session: AsyncSession, capsys) -> None:
    email = f"idem-{uuid.uuid4().hex[:8]}@example.com"
    first = await provision_customer(db_session, email=email, plan="pro", label="First Co")
    assert first.status == "created"
    assert first.raw_key is not None

    second = await provision_customer(db_session, email=email, plan="pro", label="First Co")
    assert second.status == "existing"
    assert second.tenant_id == first.tenant_id
    assert second.raw_key is None

    keys = (await db_session.execute(select(ApiKey).where(ApiKey.tenant_id == first.tenant_id))).scalars().all()
    assert len(keys) == 1

    # CLI re-run path.
    cli = _import_cli()
    capsys.readouterr()
    exit_code = await cli.run(
        argv=["--env", "local", "--email", email, "--plan", "pro"],
        session=db_session,
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "status=existing" in out
    assert "api_key=" not in out
    assert str(first.tenant_id) in out


@pytest.mark.asyncio
async def test_provision_rejects_invalid_email(db_session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="invalid email"):
        await provision_customer(db_session, email="nope", plan="pro")


@pytest.mark.asyncio
async def test_env_local_rejects_remote_dsn(db_session: AsyncSession, capsys, monkeypatch) -> None:
    cli = _import_cli()
    monkeypatch.setenv(
        "POSTGRES_DSN",
        "postgresql+asyncpg://u:p@db.altcontext.internal:5432/prod",
    )
    from db import settings as db_settings

    db_settings.get_database_settings.cache_clear()
    exit_code = await cli.run(
        argv=["--env", "local", "--email", "x@example.com"],
        session=db_session,
    )
    db_settings.get_database_settings.cache_clear()
    assert exit_code == 1
    assert "env=local" in capsys.readouterr().err
