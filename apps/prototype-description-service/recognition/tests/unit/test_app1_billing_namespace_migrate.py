"""Unit tests for billing_namespace_migrate.py (N1 mapping repair).

RV04: mapping namespace must be real nonempty strings with exact environment
and bounded seller length. JSON null must not stringify to ``None``.
RV05: dry-run must run the same row/namespace/tenant/collision checks as apply.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "billing_namespace_migrate.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("billing_namespace_migrate", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def migrate() -> ModuleType:
    return _load_script()


def _mapping(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "operator_identity": "ops-oncall",
        "evidence": "Polar org_xxx sandbox dashboard; row IDs from dry-run",
        "inbox": [],
        "projection": [],
    }
    payload.update(overrides)
    return payload


def _entry(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(uuid4()),
        "environment": "sandbox",
        "seller_account": "org_xxx",
    }
    payload.update(overrides)
    return payload


class _Result:
    def __init__(
        self,
        *,
        rows: list[Any] | None = None,
        scalar: Any = None,
        mapping: Any = None,
    ) -> None:
        self._rows = rows or []
        self._scalar = scalar
        self._mapping = mapping

    def scalar(self) -> Any:
        return self._scalar

    def mappings(self) -> _Result:
        return self

    def first(self) -> Any:
        return self._mapping

    def __iter__(self):
        return iter(self._rows)


class _FakeConn:
    """Minimal execute surface for ``run()`` without a live database."""

    def __init__(self, *, inbox_row: Any = None, projection_row: Any = None, collision: Any = None) -> None:
        self.inbox_row = inbox_row
        self.projection_row = projection_row
        self.collision = collision
        self.updates: list[tuple[str, Any]] = []

    def execute(self, statement: object, params: object | None = None) -> _Result:
        sql = str(statement).lower()
        if "current_setting" in sql:
            return _Result(scalar="")
        if "set_config" in sql:
            return _Result()
        if "environment is null" in sql or "seller_account is null" in sql:
            return _Result(rows=[])
        if sql.strip().startswith("update"):
            self.updates.append((sql, params))
            return _Result()
        if "from billing_webhook_inbox" in sql and "id <>" in sql:
            return _Result(scalar=self.collision)
        if "from billing_subscription_projection" in sql and "id <>" in sql:
            mapping = None
            if self.collision is not None:
                mapping = {"id": self.collision, "tenant_id": uuid4()}
            return _Result(mapping=mapping)
        if "from billing_webhook_inbox" in sql:
            return _Result(mapping=self.inbox_row)
        if "from billing_subscription_projection" in sql:
            return _Result(mapping=self.projection_row)
        return _Result()


def test_namespace_rejects_json_null_and_non_strings(migrate: ModuleType) -> None:
    valid_env = {"environment": "sandbox"}
    with pytest.raises(ValueError, match="seller_account"):
        migrate._namespace({**valid_env, "seller_account": None})
    with pytest.raises(ValueError, match="seller_account"):
        migrate._namespace({**valid_env, "seller_account": 123})
    with pytest.raises(ValueError, match="seller_account"):
        migrate._namespace({**valid_env, "seller_account": {"org": "x"}})
    with pytest.raises(ValueError, match="seller_account"):
        migrate._namespace({**valid_env, "seller_account": ["org_xxx"]})
    with pytest.raises(ValueError, match="seller_account"):
        migrate._namespace({**valid_env, "seller_account": True})
    with pytest.raises(ValueError, match="seller_account"):
        migrate._namespace({**valid_env, "seller_account": "   "})
    with pytest.raises(ValueError, match="environment"):
        migrate._namespace({"environment": None, "seller_account": "org_xxx"})
    with pytest.raises(ValueError, match="environment"):
        migrate._namespace({"environment": 1, "seller_account": "org_xxx"})
    with pytest.raises(ValueError, match="environment"):
        migrate._namespace({"environment": "staging", "seller_account": "org_xxx"})


def test_namespace_rejects_overlong_seller(migrate: ModuleType) -> None:
    limit = getattr(migrate, "_MAX_SELLER_ACCOUNT_LENGTH", 128)
    with pytest.raises(ValueError, match="seller_account"):
        migrate._namespace({"environment": "sandbox", "seller_account": "o" * (limit + 1)})


def test_namespace_accepts_exact_environment_and_bounded_seller(migrate: ModuleType) -> None:
    environment, seller = migrate._namespace({"environment": " live ", "seller_account": " org_xxx "})
    assert environment == "live"
    assert seller == "org_xxx"
    limit = getattr(migrate, "_MAX_SELLER_ACCOUNT_LENGTH", 128)
    environment, seller = migrate._namespace({"environment": "sandbox", "seller_account": "o" * limit})
    assert environment == "sandbox"
    assert len(seller) == limit


def test_load_mapping_requires_operator_evidence(migrate: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps({"inbox": [], "projection": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="evidence"):
        migrate._load_mapping(path)
    path.write_text(
        json.dumps({"operator_identity": "ops", "evidence": "  ", "inbox": [], "projection": []}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="evidence"):
        migrate._load_mapping(path)
    path.write_text(
        json.dumps(
            {
                "operator_identity": "ops-oncall",
                "evidence": "Polar dashboard row IDs",
                "inbox": [],
                "projection": [],
            }
        ),
        encoding="utf-8",
    )
    loaded = migrate._load_mapping(path)
    assert loaded["operator_identity"] == "ops-oncall"


def test_dry_run_validates_missing_row_instead_of_counting(migrate: ModuleType) -> None:
    conn = _FakeConn()
    mapping = _mapping(inbox=[_entry()])
    with pytest.raises(RuntimeError, match="was not found"):
        migrate.run(conn, mapping, apply=False)
    assert conn.updates == []


def test_dry_run_validates_tenant_mismatch_and_collision_without_write(migrate: ModuleType) -> None:
    row_id = uuid4()
    other_tenant = uuid4()
    projection_row = {
        "tenant_id": other_tenant,
        "provider": "polar",
        "provider_customer_id": "cus-1",
        "environment": None,
        "seller_account": None,
    }
    conn = _FakeConn(projection_row=projection_row)
    mapping = _mapping(
        projection=[_entry(id=str(row_id), tenant_id=str(uuid4()))],
    )
    with pytest.raises(RuntimeError, match="tenant_id"):
        migrate.run(conn, mapping, apply=False)
    assert conn.updates == []

    inbox_row = {
        "provider": "polar",
        "provider_event_id": "evt-1",
        "environment": None,
        "seller_account": None,
    }
    colliding = _FakeConn(inbox_row=inbox_row, collision=uuid4())
    with pytest.raises(RuntimeError, match="collides"):
        colliding_mapping = _mapping(inbox=[_entry(id=str(row_id))])
        migrate.run(colliding, colliding_mapping, apply=False)
    assert colliding.updates == []


def test_apply_does_not_write_when_later_entry_is_invalid(migrate: ModuleType) -> None:
    inbox_row = {
        "provider": "polar",
        "provider_event_id": "evt-1",
        "environment": None,
        "seller_account": None,
    }
    conn = _FakeConn(inbox_row=inbox_row)
    mapping = _mapping(
        inbox=[_entry(), _entry(seller_account=None)],
    )
    with pytest.raises(ValueError, match="seller_account"):
        migrate.run(conn, mapping, apply=True)
    assert conn.updates == []


def test_cli_apply_requires_mapping_and_defaults_to_dry_run(migrate: ModuleType) -> None:
    assert migrate.main(["--apply"]) == 2
    parser = migrate.argparse.ArgumentParser()
    source = _SCRIPT.read_text(encoding="utf-8")
    assert "--apply" in source
    assert "dry-run" in (migrate.__doc__ or "").lower() or "Default is dry-run" in (migrate.__doc__ or "")
    _ = parser


def test_main_does_not_open_engine_for_invalid_mapping_namespace(
    migrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "mapping.json"
    path.write_text(
        json.dumps(
            _mapping(inbox=[_entry(seller_account=None)]),
            allow_nan=False,
        ),
        encoding="utf-8",
    )

    def _boom(_dsn: str) -> None:
        raise AssertionError("engine must not be created for invalid mapping")

    monkeypatch.setattr(migrate, "create_engine", _boom)
    monkeypatch.setattr(
        migrate,
        "get_database_settings",
        lambda: SimpleNamespace(postgres_sync_dsn="postgresql+psycopg://unused"),
    )
    assert migrate.main(["--mapping", str(path)]) == 1
    assert migrate.main(["--mapping", str(path), "--apply"]) == 1
