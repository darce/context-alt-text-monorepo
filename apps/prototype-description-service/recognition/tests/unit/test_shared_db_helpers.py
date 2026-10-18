import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy import column
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from recognition.shared.db.dialect import is_postgres, is_sqlite, timestamp_as_epoch
from recognition.shared.db.helpers import get_rowcount
from recognition.shared.tenant import coerce_tenant_uuid


def _make_session(dialect_name: str | None) -> AsyncSession:
    if dialect_name is None:
        session = SimpleNamespace(bind=None)
    else:
        session = SimpleNamespace(bind=SimpleNamespace(dialect=SimpleNamespace(name=dialect_name)))
    return cast(AsyncSession, session)


def test_get_rowcount_handles_missing_value() -> None:
    assert get_rowcount(cast(CursorResult[Any], SimpleNamespace())) == 0
    assert get_rowcount(cast(CursorResult[Any], SimpleNamespace(rowcount=None))) == 0
    assert get_rowcount(cast(CursorResult[Any], SimpleNamespace(rowcount=3))) == 3


def test_is_sqlite_and_is_postgres() -> None:
    sqlite_session = _make_session("sqlite")
    postgres_session = _make_session("postgresql")
    no_bind_session = _make_session(None)

    assert is_sqlite(sqlite_session) is True
    assert is_postgres(sqlite_session) is False
    assert is_postgres(postgres_session) is True
    assert is_sqlite(postgres_session) is False
    assert is_sqlite(no_bind_session) is False
    assert is_postgres(no_bind_session) is False


def test_timestamp_as_epoch_uses_dialect_specific_sql() -> None:
    col: ColumnElement[Any] = column("started_at")

    sqlite_expr = timestamp_as_epoch(col, _make_session("sqlite"))
    sqlite_sql = str(sqlite_expr.compile(dialect=sqlite.dialect())).lower()
    assert "strftime" in sqlite_sql

    postgres_expr = timestamp_as_epoch(col, _make_session("postgresql"))
    postgres_sql = str(postgres_expr.compile(dialect=postgresql.dialect())).lower()
    assert "extract" in postgres_sql


def test_coerce_tenant_uuid_accepts_str_and_uuid() -> None:
    tenant_uuid = uuid.uuid4()
    assert coerce_tenant_uuid(tenant_uuid) == tenant_uuid
    assert coerce_tenant_uuid(str(tenant_uuid)) == tenant_uuid


def test_coerce_tenant_uuid_handles_md5_format() -> None:
    md5_hex = "a" * 32
    expected = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    assert coerce_tenant_uuid(md5_hex) == expected


def test_coerce_tenant_uuid_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        coerce_tenant_uuid("not-a-uuid")
