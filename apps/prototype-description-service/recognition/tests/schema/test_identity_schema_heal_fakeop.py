"""Unmarked FakeOp tests for matview grant/owner replay remediation (E-07)."""

from __future__ import annotations

import importlib

import pytest
from sqlalchemy.exc import DBAPIError

MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")


class _FakeScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar(self) -> object:
        return self._value[0] if isinstance(self._value, tuple) else self._value

    def one(self):
        return self._value


def _fake_quote_ident(ident: str) -> str:
    if ident.isidentifier() and ident.lower() == ident and not ident.startswith("_"):
        return ident
    if ident.replace("_", "").isalnum() and ident == ident.lower():
        return ident
    return '"' + ident.replace('"', '""') + '"'


class _FakeOp:
    def __init__(self, current_user: str = "app_role") -> None:
        self.statements: list[str] = []
        self.current_user = current_user

    def get_bind(self):
        op = self

        class _Bind:
            def execute(self, stmt, params=None):  # noqa: ANN001
                sql = str(stmt).lower()
                if "select quote_ident(" in sql:
                    ident = (params or {}).get("ident", op.current_user)
                    return _FakeScalarResult(_fake_quote_ident(str(ident)))
                if "select current_user" in sql:
                    return _FakeScalarResult(op.current_user)
                raise AssertionError(f"unexpected bind SQL: {stmt}")

        return _Bind()

    def execute(self, sql) -> None:  # noqa: ANN001
        self.statements.append(str(sql))


def test_restore_matview_grants_raise_named_remediation_on_dbapi_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # C-02: a vanished/renamed grantee must not leak a raw DBAPIError after
    # DROP+CREATE. Observation that would refute the finding: GRANT failure
    # raises RuntimeError naming the grantee/privilege and stating the matview
    # was rebuilt.
    op = _FakeOp()
    orig_execute = op.execute

    def _execute(sql) -> None:  # noqa: ANN001
        text_sql = str(sql)
        if text_sql.lstrip().upper().startswith("GRANT"):
            raise DBAPIError(text_sql, {}, Exception('role "vanished_reader" does not exist'))
        orig_execute(sql)

    monkeypatch.setattr(op, "execute", _execute)

    with pytest.raises(RuntimeError) as exc_info:
        MIGRATION._restore_matview_owner_and_grants(
            op,
            current_role="app_role",
            owner="app_role",
            grants=(("vanished_reader", "SELECT", False),),
        )

    message = str(exc_info.value)
    assert "vanished_reader" in message
    assert "SELECT" in message
    assert "rebuilt" in message
    assert "grant could not be replayed" in message
    assert "python -m scripts.sync_identity_schema" in message
    assert isinstance(exc_info.value.__cause__, DBAPIError)


def test_restore_matview_owner_raises_named_remediation_on_dbapi_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    op = _FakeOp(current_user="app_role")
    orig_execute = op.execute

    def _execute(sql) -> None:  # noqa: ANN001
        text_sql = str(sql)
        if "ALTER MATERIALIZED VIEW" in text_sql.upper() and "OWNER TO" in text_sql.upper():
            raise DBAPIError(text_sql, {}, Exception("permission denied to reassign ownership"))
        orig_execute(sql)

    monkeypatch.setattr(op, "execute", _execute)

    with pytest.raises(RuntimeError) as exc_info:
        MIGRATION._restore_matview_owner_and_grants(
            op,
            current_role="app_role",
            owner="other_owner",
            grants=(),
        )

    message = str(exc_info.value)
    assert "ownership could not be restored to" in message
    assert "other_owner" in message
    assert "python -m scripts.sync_identity_schema" in message
    assert isinstance(exc_info.value.__cause__, DBAPIError)
