"""Tests for load-time required-secret validation (rg-008)."""

from __future__ import annotations

import pytest

from db.settings import DEFAULT_PGPASSWORD
from recognition.config.security import (
    InsecureProductionConfigError,
    validate_required_secrets,
)


def test_validate_required_secrets_rejects_unset_pgpassword_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    monkeypatch.delenv("PGPASSWORD", raising=False)
    with pytest.raises(InsecureProductionConfigError, match="PGPASSWORD") as exc_info:
        validate_required_secrets(runtime_mode="production")
    assert "PGPASSWORD" in str(exc_info.value)


def test_validate_required_secrets_rejects_dev_default_pgpassword_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    monkeypatch.setenv("PGPASSWORD", DEFAULT_PGPASSWORD)
    with pytest.raises(InsecureProductionConfigError, match="PGPASSWORD"):
        validate_required_secrets(runtime_mode="production")


def test_validate_required_secrets_rejects_empty_pgpassword_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    monkeypatch.setenv("PGPASSWORD", "")
    with pytest.raises(InsecureProductionConfigError, match="PGPASSWORD"):
        validate_required_secrets(runtime_mode="production")


def test_validate_required_secrets_accepts_non_default_pgpassword_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    monkeypatch.setenv("PGPASSWORD", "prod-secret-not-context")
    validate_required_secrets(runtime_mode="production")


def test_validate_required_secrets_accepts_postgres_dsn_with_non_default_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production path uses POSTGRES_DSN (see .env.prod.example); PGPASSWORD may be unset."""
    monkeypatch.delenv("PGPASSWORD", raising=False)
    monkeypatch.setenv(
        "POSTGRES_DSN",
        "postgresql+asyncpg://acx_app:prod-secret-not-context@postgres:5432/alt_context_service",
    )
    validate_required_secrets(runtime_mode="production")


def test_validate_required_secrets_rejects_postgres_dsn_with_dev_default_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "POSTGRES_DSN",
        f"postgresql+asyncpg://context:{DEFAULT_PGPASSWORD}@localhost:5432/alt_context_service",
    )
    with pytest.raises(InsecureProductionConfigError, match="POSTGRES_DSN"):
        validate_required_secrets(runtime_mode="production")


def test_validate_required_secrets_rejects_postgres_dsn_with_empty_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "POSTGRES_DSN",
        "postgresql+asyncpg://acx_app:@postgres:5432/alt_context_service",
    )
    with pytest.raises(InsecureProductionConfigError, match="POSTGRES_DSN"):
        validate_required_secrets(runtime_mode="production")


def test_validate_required_secrets_noop_outside_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    monkeypatch.delenv("PGPASSWORD", raising=False)
    validate_required_secrets(runtime_mode="local")
    validate_required_secrets(runtime_mode="development")


def test_validate_required_secrets_reads_runtime_mode_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "production")
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    monkeypatch.delenv("PGPASSWORD", raising=False)
    with pytest.raises(InsecureProductionConfigError, match="PGPASSWORD"):
        validate_required_secrets()
