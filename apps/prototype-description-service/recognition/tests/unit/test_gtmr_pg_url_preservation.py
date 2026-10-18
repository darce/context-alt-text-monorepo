"""Offline regression for the provisioning PG helper's connection URL."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def test_provision_pg_helper_preserves_connection_fields() -> None:
    # Load only the exact helper: importing the PG test module also imports
    # application configuration. This test needs neither credentials nor a DB.
    path = Path(__file__).resolve().parents[1] / "scripts" / "test_provision_customer_pg.py"
    source = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    helper = next(
        node for node in source.body
        if isinstance(node, ast.FunctionDef) and node.name == "_async_sessionmaker"
    )
    captured = []

    def capture_engine(url):
        captured.append(url)
        return create_async_engine(url)

    namespace = {
        "create_async_engine": capture_engine,
        "async_sessionmaker": async_sessionmaker,
    }
    exec(compile(ast.Module(body=[helper], type_ignores=[]), str(path), "exec"), namespace)
    original = URL.create(
        "postgresql+psycopg",
        username="synthetic-user",
        password="synthetic:@/% password",
        host="example.invalid",
        port=54321,
        database="synthetic-db",
        query={"application_name": "offline-url-regression"},
    )
    engine, _ = namespace["_async_sessionmaker"](SimpleNamespace(url=original))
    # Engine construction and dialect argument inspection open no connection.
    _, parameters = engine.dialect.create_connect_args(engine.url)
    if parameters.get("password") != original.password:
        pytest.fail("dialect password was not preserved", pytrace=False)
    if not isinstance(captured[0], URL):
        pytest.fail("create_async_engine must receive a URL object", pytrace=False)
    for field in ("username", "password", "host", "port", "database", "query"):
        if getattr(engine.url, field) != getattr(original, field):
            pytest.fail(f"connection field was not preserved: {field}", pytrace=False)
    assert engine.url.drivername == "postgresql+asyncpg"
    assert original.drivername == "postgresql+psycopg"
