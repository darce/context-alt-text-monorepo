from __future__ import annotations

import asyncio
import importlib
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy.sql.dml import Delete
from sqlalchemy.sql.selectable import Select

from scene.application.describe_operation_repository import DescribeOperationRepository


class _Result:
    def __init__(self, rows=(), *, rowcount: int = 0):
        self._rows = rows
        self.rowcount = rowcount

    def all(self):
        return self._rows


class _Session:
    def __init__(self, *, identities=(), scalar_results=None, active_leases=()):
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
        self.remaining = list(identities)
        self.pending = []
        self.scalar_results = None if scalar_results is None else iter(scalar_results)
        self.active_leases = set(active_leases)
        self.count_queries = []
        self.select_limits = []
        self.delete_parameter_counts = []

    async def execute(self, statement, *_args, **_kwargs):
        if isinstance(statement, Select):
            limit = statement._limit_clause.value if statement._limit_clause is not None else None
            self.select_limits.append(limit)
            self.pending = self.remaining[:limit] if limit is not None else list(self.remaining)
            return _Result([SimpleNamespace(tenant_id=tenant, operation_id=operation) for tenant, operation in self.pending])
        if isinstance(statement, Delete):
            table = statement.table.name
            if table in {"describe_demand_leases", "describe_operations"}:
                self.delete_parameter_counts.append((table, len(self.pending) * 2))
            rowcount = len(self.pending) if table == "describe_operations" else 0
            if table == "describe_operations":
                del self.remaining[: len(self.pending)]
            return _Result(rowcount=rowcount)
        return _Result()

    async def scalar(self, statement):
        self.count_queries.append(statement)
        if self.scalar_results is not None:
            return next(self.scalar_results)
        if self.active_leases:
            values = set(statement.compile(compile_kwargs={"render_postcompile": True}).params.values())
            excluded = sum(tenant in values and operation in values for tenant, operation in self.active_leases)
            return len(self.active_leases) - excluded
        sql = str(statement).lower()
        if "join describe_operations" in sql and "describe_operations.retain_until" in sql:
            return 0
        return 1

    async def flush(self):
        return None


def test_demand_lease_count_is_bounded_by_parent_operation_retention():
    async def body():
        session = _Session()
        count = await DescribeOperationRepository(session, lease_seconds=180).active_demand_count(
            now=datetime(2026, 1, 1, tzinfo=UTC)
        )
        assert count == 0
        sql = str(session.count_queries[0]).lower()
        assert "join describe_operations" in sql
        assert "describe_operations.retain_until" in sql

    asyncio.run(body())


def test_identity_migration_binds_lease_retention_to_parent():
    migration = importlib.import_module("db.migrations.versions.001_identity_schema")
    fk = migration._describe_demand_lease_parent_retention_fk()
    assert tuple(fk.column_keys) == ("tenant_id", "operation_id", "retain_until")
    assert tuple(element.target_fullname for element in fk.elements) == (
        "describe_operations.tenant_id",
        "describe_operations.operation_id",
        "describe_operations.retain_until",
    )
    assert (
        "describe_operations",
        "uq_describe_operations_retention_target",
        ("tenant_id", "operation_id", "retain_until"),
    ) in migration.HEAL_UNIQUE_CONSTRAINTS
    assert (
        "describe_demand_leases",
        "fk_describe_demand_leases_operation_retention",
        ("tenant_id", "operation_id", "retain_until"),
        "describe_operations",
        ("tenant_id", "operation_id", "retain_until"),
        "CASCADE",
    ) in migration.HEAL_FOREIGN_KEY_CONSTRAINTS


def test_purge_expired_deletes_operations_in_bounded_batches():
    async def body():
        identities = [(uuid.uuid4(), f"expired-{index}") for index in range(805)]
        session = _Session(identities=identities)
        purged = await DescribeOperationRepository(session, lease_seconds=60).purge_expired(
            now=datetime(2026, 1, 1, tzinfo=UTC)
        )
        assert purged == len(identities)
        assert session.remaining == []
        assert session.select_limits == [400, 400, 400, 400]
        assert [n for table, n in session.delete_parameter_counts if table == "describe_operations"] == [800, 800, 10]
        assert [n for table, n in session.delete_parameter_counts if table == "describe_demand_leases"] == [800, 800, 10]

    asyncio.run(body())


def test_stop_holds_exclude_only_the_named_leases_without_deleting_them():
    async def body():
        tenants = (uuid.uuid4(), uuid.uuid4())
        operation_ids = ("held-first", "held-second")
        active_leases = set(zip(tenants, operation_ids, strict=True))
        session = _Session(active_leases=active_leases)
        repo = DescribeOperationRepository(session, lease_seconds=180)
        one_held = await repo.active_demand_count(
            now=datetime(2026, 1, 1, tzinfo=UTC),
            stop_requested=True,
            stop_held_leases={(tenants[0], operation_ids[0])},
        )
        one_held_in_flight = one_held
        assert one_held == one_held_in_flight == 1
        one_held_compiled = session.count_queries[0].compile(compile_kwargs={"render_postcompile": True})
        assert "NOT IN" in str(one_held_compiled).upper()
        assert operation_ids[0] in one_held_compiled.params.values()

        both_held = await repo.active_demand_count(
            now=datetime(2026, 1, 1, tzinfo=UTC),
            stop_requested=True,
            stop_held_leases=set(zip(tenants, operation_ids, strict=True)),
        )
        both_held_in_flight = both_held
        assert both_held == both_held_in_flight == 0
        both_held_compiled = session.count_queries[1].compile(compile_kwargs={"render_postcompile": True})
        assert all(operation_id in both_held_compiled.params.values() for operation_id in operation_ids)
        assert session.active_leases == active_leases

    asyncio.run(body())
