"""Regression tests for the ADVFIX schema and billing invariants."""

from __future__ import annotations

import importlib

import pytest


class _ScalarResult:
    def __init__(self, value: object | None = None) -> None:
        self._value = value

    def scalar(self) -> object | None:
        return self._value

    def all(self) -> list:
        return self._value if isinstance(self._value, list) else []


class _CaptureBind:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.index_definition: str | None = None
        self.conflicts: list = []
        self.bypass_rls = "false"

    def execute(self, statement: object, _params: object = None) -> _ScalarResult:
        self.statements.append(str(statement))
        if "current_setting(:name, true)" in str(statement):
            return _ScalarResult(self.bypass_rls)
        if "set_config(:name, :value, true)" in str(statement):
            self.bypass_rls = _params["value"]
            return _ScalarResult(self.bypass_rls)
        if "HAVING COUNT(*) > 1" in str(statement):
            assert self.bypass_rls == "true"
            return _ScalarResult(self.conflicts)
        return _ScalarResult(self.index_definition)


class _CaptureOp:
    def __init__(self) -> None:
        self.bind = _CaptureBind()
        self.dropped_indexes: list[tuple[str, str]] = []

    def get_bind(self) -> _CaptureBind:
        return self.bind

    def drop_index(self, index_name: str, *, table_name: str) -> None:
        self.dropped_indexes.append((index_name, table_name))


def test_global_usage_state_rebuild_uses_reservation_day_and_all_open_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = importlib.import_module("db.migrations.versions.001_identity_schema")
    op = _CaptureOp()
    monkeypatch.setattr(migration, "_relkind", lambda _op, _table: "r")

    migration._seed_usage_admission_global_state_locked(op)

    update_sql = op.bind.statements[-1].lower()
    daily_cost = update_sql.split("daily_cost_units = coalesce", 1)[1].split("inflight_units =", 1)[0]
    assert "r.reserved_at >= g.period_start" in daily_cost
    assert "r.reserved_at < g.period_end" in daily_cost
    assert "r.period_start" not in daily_cost

    inflight = update_sql.split("inflight_units = coalesce", 1)[1].split("queue_depth =", 1)[0]
    queue_depth = update_sql.split("queue_depth = coalesce", 1)[1].split("queue_bytes =", 1)[0]
    queue_bytes = update_sql.split("queue_bytes = coalesce", 1)[1].split("updated_at =", 1)[0]
    for counter in (inflight, queue_depth, queue_bytes):
        assert "r.status = 'reserved'" in counter
        assert "r.period_start" not in counter
        assert "r.reserved_at" not in counter


def test_checkout_active_index_heal_replaces_old_plan_scoped_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = importlib.import_module("db.migrations.versions.001_identity_schema")
    op = _CaptureOp()
    op.bind.index_definition = (
        "CREATE UNIQUE INDEX uq_billing_checkout_attempt_one_active "
        "ON billing_checkout_attempt (tenant_id, provider, environment, seller_account, plan_code) "
        "WHERE status IN ('created', 'provider_requested', 'pending', 'ambiguous')"
    )
    monkeypatch.setattr(migration, "_is_postgres_op", lambda _op: True)
    monkeypatch.setattr(
        migration,
        "_relkind",
        lambda _op, name: "r" if name == "billing_checkout_attempt" else "i",
    )

    migration._heal_checkout_attempt_active_index(op)

    assert op.dropped_indexes == [("uq_billing_checkout_attempt_one_active", "billing_checkout_attempt")]


@pytest.mark.parametrize("index_present", [True, False])
def test_checkout_active_index_heal_refuses_conflicting_namespaces_before_drop(
    monkeypatch: pytest.MonkeyPatch,
    index_present: bool,
) -> None:
    migration = importlib.import_module("db.migrations.versions.001_identity_schema")
    op = _CaptureOp()
    op.bind.index_definition = (
        "CREATE UNIQUE INDEX uq_billing_checkout_attempt_one_active "
        "ON billing_checkout_attempt (tenant_id, provider, environment, seller_account, plan_code)"
    )
    op.bind.conflicts = [("tenant-a", "polar", "sandbox", "seller-a")]
    monkeypatch.setattr(migration, "_is_postgres_op", lambda _op: True)
    monkeypatch.setattr(
        migration,
        "_relkind",
        lambda _op, name: "r" if name == "billing_checkout_attempt" else ("i" if index_present else None),
    )
    with pytest.raises(RuntimeError) as exc:
        migration._heal_checkout_attempt_active_index(op)
    message = str(exc.value)
    for value in op.bind.conflicts[0]:
        assert value in message
    assert "close the older open attempts" in message
    assert "wipe the dev database" in message
    assert not op.dropped_indexes
    assert op.bind.bypass_rls == "false"
    sql = "\n".join(op.bind.statements)
    assert "LOCK TABLE billing_checkout_attempt IN SHARE MODE" in sql
    assert "status IN ('created', 'provider_requested', 'pending', 'ambiguous')" in sql
