"""Unmarked FakeOp tests for matview grant/owner replay remediation.

These tests do not need Postgres. Keep pytest.mark.pg off this module so
``make test -m 'not pg'`` still exercises the heal-own unit contract.
"""

from __future__ import annotations

import importlib
import inspect

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError

MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")


class _FakeScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar(self) -> object:
        return self._value[0] if isinstance(self._value, tuple) else self._value

    def one(self):
        return self._value

    def one_or_none(self):
        return self._value

    def all(self):
        if self._value is None:
            return []
        if isinstance(self._value, list):
            return self._value
        return [self._value]


def _fake_quote_ident(ident: str) -> str:
    if ident.isidentifier() and ident.lower() == ident and not ident.startswith("_"):
        # Postgres quote_ident leaves [a-z_][a-z0-9_]* unquoted; leading
        # underscore is still unquoted. Hyphens/mixed case need quotes.
        return ident
    if ident.replace("_", "").isalnum() and ident == ident.lower():
        return ident
    return '"' + ident.replace('"', '""') + '"'


class _FakeOp:
    """Minimal alembic Operations stand-in for owner-safe ensure_matview branches."""

    def __init__(self, current_user: str = "app_role", missing_roles: set[str] | None = None) -> None:
        self.statements: list[str] = []
        self.current_user = current_user
        self.missing_roles = set(missing_roles or ())

    def get_bind(self):
        op = self

        class _Bind:
            dialect = type("D", (), {"name": "postgresql"})()

            def execute(self, stmt, params=None):  # noqa: ANN001
                sql = str(stmt).lower()
                if "quote_ident(current_user)" in sql:
                    return _FakeScalarResult((op.current_user, _fake_quote_ident(op.current_user)))
                if "select quote_ident(" in sql:
                    ident = (params or {}).get("ident", op.current_user)
                    return _FakeScalarResult(_fake_quote_ident(str(ident)))
                if "select current_user" in sql:
                    return _FakeScalarResult(op.current_user)
                if "from pg_roles" in sql:
                    name = (params or {}).get("name", "")
                    if name in op.missing_roles:
                        return _FakeScalarResult(None)
                    return _FakeScalarResult(1)
                if "aclexplode" in sql:
                    return _FakeScalarResult([])
                raise AssertionError(f"unexpected bind SQL: {stmt}")

        return _Bind()

    def execute(self, sql) -> None:  # noqa: ANN001
        self.statements.append(str(sql))


def _issued_drop(op: _FakeOp) -> bool:
    needle = "DROP MATERIALIZED VIEW mv_identity_cluster_centroids"
    return any(needle in sql.replace("\n", " ") for sql in op.statements)


def test_restore_matview_grants_raise_named_remediation_on_dbapi_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A vanished/renamed grantee must not leak a raw DBAPIError. The DROP+CREATE
    # lives in the same transaction, so the message must not claim the view was
    # rebuilt or that re-running sync will converge.
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
    assert "grant could not be replayed" in message
    assert "rebuilt" not in message.lower()
    assert "python -m scripts.sync_identity_schema" not in message
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


def test_ensure_matview_refuses_rebuild_when_grant_grantee_vanished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    op = _FakeOp(missing_roles={"vanished_reader"})
    monkeypatch.setattr(MIGRATION, "_relkind", lambda _op, _name: "m")
    monkeypatch.setattr(MIGRATION, "_matview_centroid_typmod", lambda _op: -1)
    monkeypatch.setattr(MIGRATION, "_matview_owner_and_can_drop", lambda _op: ("app_role", True))
    monkeypatch.setattr(MIGRATION, "_matview_create_privilege_gaps", lambda _op: [])
    monkeypatch.setattr(
        MIGRATION,
        "_matview_nonowner_grants",
        lambda _op: (("vanished_reader", "SELECT", False),),
    )

    with pytest.raises(RuntimeError) as exc_info:
        MIGRATION.ensure_matview(op)

    message = str(exc_info.value)
    assert "vanished_reader" in message
    assert "cannot receive GRANT" in message
    assert "rebuilt" not in message.lower()
    assert "python -m scripts.sync_identity_schema" not in message
    assert not _issued_drop(op)
    assert not any("CREATE MATERIALIZED VIEW" in sql for sql in op.statements)


def test_ensure_matview_preflights_grant_roles_before_drop() -> None:
    src = inspect.getsource(MIGRATION.ensure_matview)
    assert src.index("_missing_matview_grant_roles") < src.index("DROP MATERIALIZED VIEW")


def test_matview_nonowner_grants_does_not_explode_null_relacl() -> None:
    src = inspect.getsource(MIGRATION._matview_nonowner_grants)
    sql = src[src.index("SELECT") :]
    assert "LEFT JOIN LATERAL aclexplode" in sql
    assert "c.relacl IS NOT NULL" in sql
    assert "COALESCE" not in sql
    assert "'{}'" not in sql


def test_ensure_unique_constraint_raises_named_action_on_unique_violation() -> None:
    class _OrigError(Exception):
        sqlstate = "23505"

    class _Op(_FakeOp):
        def execute(self, sql) -> None:  # noqa: ANN001
            raise IntegrityError(str(sql), {}, _OrigError())

    constraint = sa.UniqueConstraint(
        "tenant_id",
        "idempotency_key",
        name="uq_image_description_runs_idempotency_key",
    )
    with pytest.raises(RuntimeError) as exc_info:
        MIGRATION._ensure_unique_constraint(_Op(), "image_description_runs", constraint)

    message = str(exc_info.value)
    assert "uq_image_description_runs_idempotency_key" in message
    assert "23505" in message
    assert "image_description_runs" in message
    assert "operator" in message.lower()
    assert isinstance(exc_info.value.__cause__, IntegrityError)


def test_ensure_unique_constraint_raises_named_action_on_dbapi_pgcode_23505() -> None:
    class _OrigError(Exception):
        pgcode = "23505"

    class _Op(_FakeOp):
        def execute(self, sql) -> None:  # noqa: ANN001
            raise DBAPIError(str(sql), {}, _OrigError())

    constraint = sa.UniqueConstraint(
        "tenant_id",
        "idempotency_key",
        name="uq_image_description_runs_idempotency_key",
    )
    with pytest.raises(RuntimeError) as exc_info:
        MIGRATION._ensure_unique_constraint(_Op(), "image_description_runs", constraint)

    message = str(exc_info.value)
    assert "uq_image_description_runs_idempotency_key" in message
    assert "23505" in message
    assert "image_description_runs" in message
    assert "duplicate" in message.lower()
    assert isinstance(exc_info.value.__cause__, DBAPIError)
