from __future__ import annotations

import importlib
from dataclasses import dataclass, field

import pytest
from sqlalchemy import CheckConstraint

from roster.application.curation_sync_service import CurationRefreshStatus

identity_schema = importlib.import_module("db.migrations.versions.001_identity_schema")


@dataclass
class _RecordingOp:
    created_tables: list[str] = field(default_factory=list)
    created_table_args: dict[str, tuple[object, ...]] = field(default_factory=dict)
    created_indexes: list[tuple[str, str]] = field(default_factory=list)
    executed_sql: list[str] = field(default_factory=list)
    dropped_tables: list[str] = field(default_factory=list)
    dropped_indexes: list[tuple[str, str | None]] = field(default_factory=list)

    def execute(self, sql: str) -> None:
        self.executed_sql.append(sql)

    def get_bind(self):
        # The E15-34 ensure_* helpers consult the catalog before emitting DDL;
        # report "nothing exists, RLS off" so every create/alter is recorded.
        class _FakeResult:
            def __init__(self, row):
                self._row = row

            def scalar(self):
                return self._row[0] if self._row else None

            def first(self):
                return self._row

        class _FakeBind:
            def execute(self, stmt, params=None):  # noqa: ANN001
                if "relrowsecurity" in str(stmt):
                    return _FakeResult((False, False))
                return _FakeResult(None)

        return _FakeBind()

    def create_table(self, name: str, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.created_tables.append(name)
        self.created_table_args[name] = args

    def create_index(self, name: str, table_name: str, columns: list[str], *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.created_indexes.append((name, table_name))

    def drop_table(self, name: str, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.dropped_tables.append(name)

    def drop_index(self, name: str, table_name: str | None = None, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.dropped_indexes.append((name, table_name))


def test_identity_schema_upgrade_creates_api_keys_table(monkeypatch) -> None:
    recorder = _RecordingOp()
    monkeypatch.setattr(identity_schema, "op", recorder)

    identity_schema.upgrade()

    assert "api_keys" in recorder.created_tables
    assert ("idx_api_keys_tenant", "api_keys") in recorder.created_indexes
    assert ("idx_api_keys_hash", "api_keys") in recorder.created_indexes


def test_identity_schema_upgrade_creates_demo_instances_table(monkeypatch) -> None:
    recorder = _RecordingOp()
    monkeypatch.setattr(identity_schema, "op", recorder)

    identity_schema.upgrade()

    assert "demo_instances" in recorder.created_tables
    assert ("idx_demo_instances_tenant", "demo_instances") in recorder.created_indexes
    assert ("idx_demo_instances_expires", "demo_instances") in recorder.created_indexes


def test_identity_schema_declares_expected_table_set() -> None:
    assert identity_schema.EXPECTED_SCHEMA_TABLES == [
        "tenants",
        "api_keys",
        "demo_instances",
        "worker_capabilities",
        "media_identities",
        "curation_replay_records",
        "identity_clusters",
        "identity_members",
        "identity_name_suppressions",
        "identity_cluster_representatives",
        "identity_scan_jobs",
        "identity_scan_job_items",
        "identity_clustering_jobs",
        "identity_suggestions",
        "cluster_merge_suggestions",
        "name_suggestions",
        "identity_cluster_blocks",
        "identity_constraints",
        "recognition_runs",
        "recognition_events",
        "clustering_feedback",
        "audit_events",
        "export_jobs",
        "identity_cluster_refresh_queue",
        "image_descriptions",
        "image_description_runs",
        "image_description_run_items",
        "clustering_job_reports",
        "assignment_decisions",
        "identity_atlas_runs",
        "identity_atlas_points",
        "identity_atlas_queue_dispositions",
    ]


def test_identity_schema_refresh_status_constraint_matches_enum(monkeypatch) -> None:
    recorder = _RecordingOp()
    monkeypatch.setattr(identity_schema, "op", recorder)

    identity_schema.upgrade()

    table_args = recorder.created_table_args["curation_replay_records"]
    refresh_constraint = next(arg for arg in table_args if isinstance(arg, CheckConstraint))
    expected_values = ", ".join(f"'{status.value}'" for status in CurationRefreshStatus)

    assert str(refresh_constraint.sqltext) == f"refresh_status IN ({expected_values})"


def test_identity_schema_downgrade_drops_children_before_parents(monkeypatch) -> None:
    recorder = _RecordingOp()
    monkeypatch.setattr(identity_schema, "op", recorder)

    identity_schema.downgrade()

    assert ("idx_api_keys_hash", "api_keys") in recorder.dropped_indexes
    assert ("idx_api_keys_tenant", "api_keys") in recorder.dropped_indexes
    assert recorder.dropped_tables[-3:] == ["demo_instances", "api_keys", "tenants"]
    assert recorder.dropped_tables.index("identity_members") < recorder.dropped_tables.index("identity_clusters")
    assert recorder.dropped_tables.index("identity_cluster_representatives") < recorder.dropped_tables.index(
        "identity_clusters"
    )
    assert recorder.dropped_tables.index("identity_cluster_representatives") < recorder.dropped_tables.index(
        "media_identities"
    )
    assert recorder.dropped_tables.index("recognition_events") < recorder.dropped_tables.index("recognition_runs")


def test_ensure_table_fails_loudly_when_existing_table_missing_named_constraint() -> None:
    """FL30-B-01: existing tables missing table-level constraints must not silent-heal.

    Predicted RED mutation: remove the ``_ensure_table_constraints`` call from
    ``_ensure_table`` (table-exists branch) → this raises nothing and the missing
    UniqueConstraint is silently skipped while indexes alone may still land.

    Also contract-checks the catalog query shape (not mere ``conname`` substring
    matching): the statement must target ``pg_constraint``, scope to the table
    name, and bind that name as a parameter.
    """
    import sqlalchemy as sa

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def scalar(self):
            return self._rows[0][0] if self._rows else None

        def __iter__(self):
            return iter(self._rows)

    class _ExistingTableOp:
        """Catalog reports the table exists, columns present, constraints empty."""

        def __init__(self) -> None:
            self.executed: list[tuple[str, object]] = []

        def get_bind(self):
            parent = self

            class _Bind:
                def execute(self, stmt, params=None):  # noqa: ANN001
                    sql = str(stmt)
                    parent.executed.append((sql, params))
                    sql_l = sql.lower()
                    if "relkind" in sql_l:
                        return _Result([("r",)])
                    if "column_name" in sql_l:
                        return _Result([("id",), ("run_id",)])
                    if "pg_constraint" in sql_l:
                        # No constraints present — the heal gap under test.
                        return _Result([])
                    # Unrecognized catalog query: empty rows (never a fake success).
                    return _Result([])

            return _Bind()

        def create_table(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            raise AssertionError("create_table must not run when the table already exists")

        def add_column(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            raise AssertionError("no columns should be missing in this fixture")

    op = _ExistingTableOp()
    with pytest.raises(RuntimeError, match="missing table-level constraints") as exc_info:
        identity_schema._ensure_table(
            op,
            "identity_atlas_points",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("run_id", sa.Integer, nullable=False),
            sa.UniqueConstraint("id", "run_id", name="uq_identity_atlas_points_id_run"),
        )
    assert "uq_identity_atlas_points_id_run" in str(exc_info.value)
    assert "identity_atlas_points" in str(exc_info.value)

    constraint_calls = [
        (sql, params) for sql, params in op.executed if "pg_constraint" in sql.lower()
    ]
    assert constraint_calls, (
        "expected _existing_constraint_names to query pg_constraint; "
        f"executed={[sql for sql, _ in op.executed]}"
    )
    sql, params = constraint_calls[0]
    sql_l = sql.lower()
    assert "from pg_constraint" in sql_l or "from pg_constraint " in sql_l.replace("\n", " ")
    assert "conname" in sql_l
    assert "relname" in sql_l
    assert params is not None and params.get("t") == "identity_atlas_points", (
        f"table name must be bound as parameter :t, got params={params!r}"
    )


def test_existing_constraint_names_contract_on_real_postgres(pg_empty_engine) -> None:
    """B-01: ``_existing_constraint_names`` must read real ``pg_constraint`` rows.

    Present-and-absent against a live catalog, scoped per table. Skips (via
    ``pg_empty_engine``) only when Postgres is unreachable — never fakes the
    catalog query. A regression that drops the table predicate, targets the
    wrong catalog, or stops binding ``:t`` fails here.
    """
    from sqlalchemy import text

    class _AlembicOp:
        def __init__(self, connection) -> None:
            self._connection = connection

        def get_bind(self):
            return self._connection

    table_a = "b01_constraint_probe_a"
    table_b = "b01_constraint_probe_b"
    uq_a = "uq_b01_probe_a_cols"
    uq_b = "uq_b01_probe_b_cols"
    # CHECK constraints live only in pg_constraint (no pg_class index twin),
    # so a query rewritten to pg_class cannot green on these names.
    ck_a = "ck_b01_probe_a_positive"
    ck_b = "ck_b01_probe_b_positive"

    with pg_empty_engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {table_a}"))
        conn.execute(text(f"DROP TABLE IF EXISTS {table_b}"))
        conn.execute(
            text(
                f"CREATE TABLE {table_a} ("
                "id integer PRIMARY KEY, "
                "a integer NOT NULL, "
                "b integer NOT NULL, "
                f"CONSTRAINT {uq_a} UNIQUE (a, b), "
                f"CONSTRAINT {ck_a} CHECK (a > 0)"
                ")"
            )
        )
        conn.execute(
            text(
                f"CREATE TABLE {table_b} ("
                "id integer PRIMARY KEY, "
                "a integer NOT NULL, "
                "b integer NOT NULL, "
                f"CONSTRAINT {uq_b} UNIQUE (a, b), "
                f"CONSTRAINT {ck_b} CHECK (a > 0)"
                ")"
            )
        )
        op = _AlembicOp(conn)

        names_a = identity_schema._existing_constraint_names(op, table_a)
        names_b = identity_schema._existing_constraint_names(op, table_b)

        assert uq_a in names_a, f"unique on A missing; got {sorted(names_a)}"
        assert ck_a in names_a, f"check on A missing; got {sorted(names_a)}"
        assert uq_b not in names_a, (
            f"table A query must not return B's unique {uq_b!r}; got {sorted(names_a)}"
        )
        assert ck_b not in names_a, (
            f"table A query must not return B's check {ck_b!r}; got {sorted(names_a)}"
        )

        assert uq_b in names_b and ck_b in names_b, f"B missing constraints; got {sorted(names_b)}"
        assert uq_a not in names_b and ck_a not in names_b, (
            f"table B query must not return A's constraints; got {sorted(names_b)}"
        )

        conn.execute(text(f"ALTER TABLE {table_a} DROP CONSTRAINT {ck_a}"))
        after_drop = identity_schema._existing_constraint_names(op, table_a)
        assert ck_a not in after_drop, (
            f"after DROP CONSTRAINT, {ck_a!r} must not appear; got {sorted(after_drop)}"
        )
        assert uq_a in after_drop, "unrelated unique must still be visible after check drop"

        ghost = identity_schema._existing_constraint_names(op, "no_such_table_b01")
        assert uq_a not in ghost and ck_a not in ghost and uq_b not in ghost


# ---------------------------------------------------------------------------
# GUIDEDFIX-2 [S02]: a newly declared UNIQUE constraint must land on an
# already-provisioned table instead of hard-failing every subsequent migrate.
# ---------------------------------------------------------------------------


class _ProvisionedTableOp:
    """Catalog reports the table exists with every declared column present.

    ``constraints`` is the set of constraint names already on the table; the
    idempotency-key unique constraint is absent, which is exactly the state of
    any database provisioned before it was declared.
    """

    def __init__(self, *, columns: set[str], constraints: set[str], dialect: str = "postgresql") -> None:
        self.columns = columns
        self.constraints = constraints
        self.dialect = dialect
        self.executed: list[str] = []
        self.added_columns: list[str] = []

    def execute(self, sql, *args, **kwargs) -> None:  # noqa: ANN001, ANN002, ANN003
        self.executed.append(str(sql))

    def add_column(self, table_name: str, column) -> None:  # noqa: ANN001
        self.added_columns.append(column.name)
        self.columns.add(column.name)

    def create_table(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        raise AssertionError("create_table must not run against a provisioned table")

    def get_bind(self):
        parent = self

        class _Result:
            def __init__(self, rows):
                self._rows = rows

            def scalar(self):
                return self._rows[0][0] if self._rows else None

            def __iter__(self):
                return iter(self._rows)

        class _Bind:
            dialect = type("_Dialect", (), {"name": parent.dialect})()

            def execute(self, stmt, params=None):  # noqa: ANN001
                sql = str(stmt).lower()
                if "relkind" in sql:
                    return _Result([("r",)])
                if "column_name" in sql:
                    return _Result([(name,) for name in sorted(parent.columns)])
                if "pg_constraint" in sql:
                    return _Result([(name,) for name in sorted(parent.constraints)])
                return _Result([])

        return _Bind()


def _describe_run_table_declaration(monkeypatch) -> tuple[tuple, dict]:
    """The real ``image_description_runs`` args, captured from the migration itself.

    Read from the call site rather than restated here, so this test cannot drift
    from the declaration it is asserting about.
    """
    captured: dict[str, tuple[tuple, dict]] = {}

    def _capture(op_arg, table_name, *columns, **kw):  # noqa: ANN001, ANN002, ANN003
        captured[table_name] = (columns, kw)

    monkeypatch.setattr(identity_schema, "op", _RecordingOp())
    monkeypatch.setattr(identity_schema, "_ensure_table", _capture)
    identity_schema.ensure_tables(identity_schema.op)
    # Undo before returning: the caller invokes the REAL ``_ensure_table`` next,
    # and leaving the capture stub in place would silently assert nothing.
    monkeypatch.undo()
    assert identity_schema._ensure_table is not _capture
    assert "image_description_runs" in captured
    return captured["image_description_runs"]


def _split_declaration(columns):
    import sqlalchemy as sa

    declared_columns = {c.name for c in columns if isinstance(c, sa.Column)}
    declared_constraints = {
        c.name
        for c in columns
        if isinstance(c, (sa.UniqueConstraint, sa.CheckConstraint, sa.ForeignKeyConstraint)) and c.name
    }
    return declared_columns, declared_constraints


def test_migration_declares_the_idempotency_unique_constraint_as_heal_additive(monkeypatch) -> None:
    """The call site must opt the new constraint into additive healing by name."""
    _columns, kw = _describe_run_table_declaration(monkeypatch)
    assert "uq_image_description_runs_idempotency_key" in tuple(kw.get("heal_constraints", ()))


def test_new_unique_constraint_is_added_to_an_already_provisioned_table(monkeypatch) -> None:
    """[S02] RED before the fix: this raised RuntimeError on every migrate.

    The branch added ``UniqueConstraint('tenant_id', 'idempotency_key')`` to
    ``image_description_runs``. ``_ensure_table`` no-ops ``create_table`` when
    the table exists, so on every already-provisioned database the constraint
    could never land and ``_ensure_table_constraints`` refused the mismatch -
    turning a purely additive change into a hard migration failure. The fix must
    emit the ALTER instead.
    """
    columns, kw = _describe_run_table_declaration(monkeypatch)
    declared_columns, declared_constraints = _split_declaration(columns)
    target = "uq_image_description_runs_idempotency_key"
    assert target in declared_constraints

    op = _ProvisionedTableOp(
        columns=set(declared_columns),
        constraints=declared_constraints - {target},
    )
    identity_schema._ensure_table(op, "image_description_runs", *columns, **kw)

    alters = [sql for sql in op.executed if "add constraint" in sql.lower()]
    assert len(alters) == 1, f"expected exactly one ALTER ... ADD CONSTRAINT; got {op.executed}"
    sql = alters[0].lower()
    assert "image_description_runs" in sql
    assert target in sql
    assert "unique" in sql
    assert "tenant_id" in sql and "idempotency_key" in sql
    assert op.added_columns == []


def test_unlisted_missing_constraint_still_fails_loudly(monkeypatch) -> None:
    """The heal is opt-in by name: it must not become a blanket relaxation."""
    columns, kw = _describe_run_table_declaration(monkeypatch)
    declared_columns, declared_constraints = _split_declaration(columns)
    op = _ProvisionedTableOp(
        columns=set(declared_columns),
        constraints=declared_constraints - {"valid_describe_run_status"},
    )
    with pytest.raises(RuntimeError, match="missing table-level constraints"):
        identity_schema._ensure_table(op, "image_description_runs", *columns, **kw)
    assert not [sql for sql in op.executed if "add constraint" in sql.lower()]


def test_heal_constraints_naming_an_undeclared_constraint_is_rejected() -> None:
    """rg-008: a typo in the opt-in list must fail loudly, not silently no-op."""
    import sqlalchemy as sa

    op = _ProvisionedTableOp(columns={"id", "run_id"}, constraints=set())
    with pytest.raises(RuntimeError, match="heal_constraints names"):
        identity_schema._ensure_table_constraints(
            op,
            "identity_atlas_points",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.UniqueConstraint("id", "run_id", name="uq_identity_atlas_points_id_run"),
            heal_constraints=("uq_typo_that_is_not_declared",),
        )


def test_non_postgres_dialects_emit_no_alter_and_do_not_raise(monkeypatch) -> None:
    """SQLite has no ``ALTER TABLE ... ADD CONSTRAINT``; it gets the UNIQUE inline."""
    columns, kw = _describe_run_table_declaration(monkeypatch)
    declared_columns, declared_constraints = _split_declaration(columns)
    op = _ProvisionedTableOp(
        columns=set(declared_columns),
        constraints=declared_constraints - {"uq_image_description_runs_idempotency_key"},
        dialect="sqlite",
    )
    identity_schema._ensure_table(op, "image_description_runs", *columns, **kw)
    assert not [sql for sql in op.executed if "add constraint" in sql.lower()]
