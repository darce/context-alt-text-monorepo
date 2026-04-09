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
                "DB_NAME=context_alt_text_service",
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

    assert settings.postgres_dsn == "postgresql+asyncpg://context:context@localhost:5432/context_alt_text_service"
    assert settings.postgres_sync_dsn == "postgresql+psycopg://context:context@localhost:5432/context_alt_text_service"


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

    assert settings.postgres_dsn == "postgresql+asyncpg://context:context@localhost:5432/context_alt_text_service"
    assert settings.postgres_sync_dsn == "postgresql+psycopg://context:context@localhost:5432/context_alt_text_service"


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
    assert settings.disable_stmt_cache is False


def test_database_settings_can_disable_asyncpg_statement_cache(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"

    for key in ("PGUSER", "PGPASSWORD", "PGHOST", "PGPORT", "DB_NAME", "POSTGRES_SYNC_DSN"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("POSTGRES_DSN", "postgresql+asyncpg://context:context@localhost:5432/context_alt_text_service")
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
