"""Regression coverage for local database env configuration."""

from __future__ import annotations

from pathlib import Path

import db.settings as settings_module


def test_database_settings_expand_env_file_references(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                "PGUSER=context",
                "PGPASSWORD=context",
                "PGHOST=localhost",
                "PGPORT=5432",
                "DB_NAME=alt_context_service",
                "POSTGRES_DSN=postgresql+asyncpg://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/${DB_NAME}",
            )
        )
        + "\n"
    )

    for key in ("PGUSER", "PGPASSWORD", "PGHOST", "PGPORT", "DB_NAME", "POSTGRES_DSN", "POSTGRES_SYNC_DSN"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(settings_module, "ENV_FILE", env_file)

    settings_module.get_database_settings.cache_clear()
    try:
        settings = settings_module.get_database_settings()
    finally:
        settings_module.get_database_settings.cache_clear()

    assert settings.postgres_dsn == "postgresql+asyncpg://context:context@localhost:5432/alt_context_service"
    assert settings.postgres_sync_dsn == "postgresql+psycopg://context:context@localhost:5432/alt_context_service"


def test_database_settings_canonicalize_legacy_db_name_from_env_file(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                "PGUSER=context",
                "PGPASSWORD=context",
                "PGHOST=localhost",
                "PGPORT=5432",
                "DB_NAME=context_alt_text_service",
                "POSTGRES_DSN=postgresql+asyncpg://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/${DB_NAME}",
            )
        )
        + "\n"
    )

    for key in ("PGUSER", "PGPASSWORD", "PGHOST", "PGPORT", "DB_NAME", "POSTGRES_DSN", "POSTGRES_SYNC_DSN", "ENV_MODE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(settings_module, "ENV_FILE", env_file)

    settings_module.get_database_settings.cache_clear()
    try:
        settings = settings_module.get_database_settings()
    finally:
        settings_module.get_database_settings.cache_clear()

    assert settings.postgres_dsn == "postgresql+asyncpg://context:context@localhost:5432/alt_context_service"
    assert settings.postgres_sync_dsn == "postgresql+psycopg://context:context@localhost:5432/alt_context_service"


def test_database_settings_canonicalize_explicit_legacy_dsn_env_vars(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"

    for key in ("PGUSER", "PGPASSWORD", "PGHOST", "PGPORT", "DB_NAME", "POSTGRES_DSN", "POSTGRES_SYNC_DSN", "ENV_MODE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ENV_MODE", "local")
    monkeypatch.setenv("POSTGRES_DSN", "postgresql+asyncpg://context:context@localhost:5432/context_alt_text_service")
    monkeypatch.setenv(
        "POSTGRES_SYNC_DSN", "postgresql+psycopg://context:context@localhost:5432/context_alt_text_service"
    )
    monkeypatch.setattr(settings_module, "ENV_FILE", env_file)

    settings_module.get_database_settings.cache_clear()
    try:
        settings = settings_module.get_database_settings()
    finally:
        settings_module.get_database_settings.cache_clear()
        monkeypatch.delenv("ENV_MODE", raising=False)
        monkeypatch.delenv("POSTGRES_DSN", raising=False)
        monkeypatch.delenv("POSTGRES_SYNC_DSN", raising=False)

    assert settings.postgres_dsn == "postgresql+asyncpg://context:context@localhost:5432/alt_context_service"
    assert settings.postgres_sync_dsn == "postgresql+psycopg://context:context@localhost:5432/alt_context_service"


def test_env_example_defines_reset_prerequisites() -> None:
    env_example = Path(__file__).resolve().parents[3] / ".env.example"
    content = env_example.read_text()

    assert "PGUSER=" in content
    assert "PGPASSWORD=" in content
    assert "DB_NAME=" in content
    assert "APP_PGUSER=${PGUSER}" in content
    assert "APP_PGPASSWORD=${PGPASSWORD}" in content


def test_database_settings_default_to_canonical_local_database_name(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"

    for key in ("PGUSER", "PGPASSWORD", "PGHOST", "PGPORT", "DB_NAME", "POSTGRES_DSN", "POSTGRES_SYNC_DSN"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(settings_module, "ENV_FILE", env_file)

    settings_module.get_database_settings.cache_clear()
    try:
        settings = settings_module.get_database_settings()
    finally:
        settings_module.get_database_settings.cache_clear()

    assert settings.postgres_dsn == "postgresql+asyncpg://context:context@localhost:5432/alt_context_service"
    assert settings.postgres_sync_dsn == "postgresql+psycopg://context:context@localhost:5432/alt_context_service"


def test_database_settings_expose_timeout_defaults(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"

    for key in (
        "PGUSER",
        "PGPASSWORD",
        "PGHOST",
        "PGPORT",
        "DB_NAME",
        "POSTGRES_DSN",
        "POSTGRES_SYNC_DSN",
        "DB_STATEMENT_TIMEOUT",
        "DB_IDLE_IN_TXN_TIMEOUT",
        "DB_DISABLE_STMT_CACHE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(settings_module, "ENV_FILE", env_file)

    settings_module.get_database_settings.cache_clear()
    try:
        settings = settings_module.get_database_settings()
    finally:
        settings_module.get_database_settings.cache_clear()

    assert settings.statement_timeout == "10s"
    assert settings.idle_in_txn_timeout == "30s"
    assert settings.embedding_timeout_s == 30
    assert settings.observability_pool_size == 2
    assert settings.observability_max_overflow == 0
    assert settings.observability_pool_timeout == 5
    assert settings.breaker_failure_threshold == 3
    assert settings.breaker_window_seconds == 30
    assert settings.breaker_half_open_after_seconds == 10
    assert settings.disable_stmt_cache is False


def test_database_settings_can_disable_asyncpg_statement_cache(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"

    for key in ("PGUSER", "PGPASSWORD", "PGHOST", "PGPORT", "DB_NAME", "POSTGRES_SYNC_DSN"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("POSTGRES_DSN", "postgresql+asyncpg://context:context@localhost:5432/alt_context_service")
    monkeypatch.setenv("DB_DISABLE_STMT_CACHE", "1")
    monkeypatch.setenv("DB_STATEMENT_TIMEOUT", "11s")
    monkeypatch.setenv("DB_IDLE_IN_TXN_TIMEOUT", "31s")
    monkeypatch.setattr(settings_module, "ENV_FILE", env_file)

    settings_module.get_database_settings.cache_clear()
    try:
        settings = settings_module.get_database_settings()
    finally:
        settings_module.get_database_settings.cache_clear()
        monkeypatch.delenv("POSTGRES_DSN", raising=False)
        monkeypatch.delenv("DB_DISABLE_STMT_CACHE", raising=False)
        monkeypatch.delenv("DB_STATEMENT_TIMEOUT", raising=False)
        monkeypatch.delenv("DB_IDLE_IN_TXN_TIMEOUT", raising=False)

    assert "prepared_statement_cache_size=0" in settings.postgres_dsn
    assert settings.disable_stmt_cache is True
    assert settings.statement_timeout == "11s"
    assert settings.idle_in_txn_timeout == "31s"


def test_database_settings_can_override_breaker_values(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"

    for key in (
        "PGUSER",
        "PGPASSWORD",
        "PGHOST",
        "PGPORT",
        "DB_NAME",
        "POSTGRES_DSN",
        "POSTGRES_SYNC_DSN",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DB_BREAKER_FAILURE_THRESHOLD", "5")
    monkeypatch.setenv("DB_BREAKER_WINDOW_SECONDS", "45")
    monkeypatch.setenv("DB_BREAKER_HALF_OPEN_AFTER_SECONDS", "12")
    monkeypatch.setattr(settings_module, "ENV_FILE", env_file)

    settings_module.get_database_settings.cache_clear()
    try:
        settings = settings_module.get_database_settings()
    finally:
        settings_module.get_database_settings.cache_clear()
        monkeypatch.delenv("DB_BREAKER_FAILURE_THRESHOLD", raising=False)
        monkeypatch.delenv("DB_BREAKER_WINDOW_SECONDS", raising=False)
        monkeypatch.delenv("DB_BREAKER_HALF_OPEN_AFTER_SECONDS", raising=False)

    assert settings.breaker_failure_threshold == 5
    assert settings.breaker_window_seconds == 45
    assert settings.breaker_half_open_after_seconds == 12


def test_database_settings_can_override_embedding_timeout(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"

    for key in (
        "PGUSER",
        "PGPASSWORD",
        "PGHOST",
        "PGPORT",
        "DB_NAME",
        "POSTGRES_DSN",
        "POSTGRES_SYNC_DSN",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DB_EMBEDDING_TIMEOUT_SECONDS", "7.5")
    monkeypatch.setattr(settings_module, "ENV_FILE", env_file)

    settings_module.get_database_settings.cache_clear()
    try:
        settings = settings_module.get_database_settings()
    finally:
        settings_module.get_database_settings.cache_clear()
        monkeypatch.delenv("DB_EMBEDDING_TIMEOUT_SECONDS", raising=False)

    assert settings.embedding_timeout_s == 7.5


def test_database_settings_can_override_observability_pool_values(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"

    for key in (
        "PGUSER",
        "PGPASSWORD",
        "PGHOST",
        "PGPORT",
        "DB_NAME",
        "POSTGRES_DSN",
        "POSTGRES_SYNC_DSN",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DB_OBSERVABILITY_POOL_SIZE", "4")
    monkeypatch.setenv("DB_OBSERVABILITY_MAX_OVERFLOW", "1")
    monkeypatch.setenv("DB_OBSERVABILITY_POOL_TIMEOUT", "7")
    monkeypatch.setattr(settings_module, "ENV_FILE", env_file)

    settings_module.get_database_settings.cache_clear()
    try:
        settings = settings_module.get_database_settings()
    finally:
        settings_module.get_database_settings.cache_clear()
        monkeypatch.delenv("DB_OBSERVABILITY_POOL_SIZE", raising=False)
        monkeypatch.delenv("DB_OBSERVABILITY_MAX_OVERFLOW", raising=False)
        monkeypatch.delenv("DB_OBSERVABILITY_POOL_TIMEOUT", raising=False)

    assert settings.observability_pool_size == 4
    assert settings.observability_max_overflow == 1
    assert settings.observability_pool_timeout == 7


def test_canonicalize_local_db_name_rewrites_legacy_name() -> None:
    db_name, warning = settings_module.canonicalize_local_db_name(
        "context_alt_text_service",
        env_mode="local",
    )

    assert db_name == "alt_context_service"
    assert warning is not None
    assert "context_alt_text_service" in warning
    assert "alt_context_service" in warning


def test_canonicalize_local_db_name_preserves_non_local_values() -> None:
    db_name, warning = settings_module.canonicalize_local_db_name(
        "context_alt_text_service",
        env_mode="production",
    )

    assert db_name == "context_alt_text_service"
    assert warning is None


def test_database_settings_canonicalize_legacy_db_name_from_environment(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"

    for key in ("PGUSER", "PGPASSWORD", "PGHOST", "PGPORT", "POSTGRES_DSN", "POSTGRES_SYNC_DSN"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ENV_MODE", "local")
    monkeypatch.setenv("DB_NAME", "context_alt_text_service")
    monkeypatch.setattr(settings_module, "ENV_FILE", env_file)

    settings_module.get_database_settings.cache_clear()
    try:
        settings = settings_module.get_database_settings()
    finally:
        settings_module.get_database_settings.cache_clear()
        monkeypatch.delenv("ENV_MODE", raising=False)
        monkeypatch.delenv("DB_NAME", raising=False)

    assert settings.postgres_dsn == "postgresql+asyncpg://context:context@localhost:5432/alt_context_service"
    assert settings.postgres_sync_dsn == "postgresql+psycopg://context:context@localhost:5432/alt_context_service"
