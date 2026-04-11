from __future__ import annotations

import importlib
from dataclasses import dataclass, field

identity_schema = importlib.import_module("db.migrations.versions.001_identity_schema")


@dataclass
class _RecordingOp:
    created_tables: list[str] = field(default_factory=list)
    created_indexes: list[tuple[str, str]] = field(default_factory=list)
    executed_sql: list[str] = field(default_factory=list)

    def execute(self, sql: str) -> None:
        self.executed_sql.append(sql)

    def create_table(self, name: str, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.created_tables.append(name)

    def create_index(self, name: str, table_name: str, columns: list[str], *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.created_indexes.append((name, table_name))


def test_identity_schema_upgrade_creates_api_keys_table(monkeypatch) -> None:
    recorder = _RecordingOp()
    monkeypatch.setattr(identity_schema, "op", recorder)

    identity_schema.upgrade()

    assert "api_keys" in recorder.created_tables
    assert ("idx_api_keys_tenant", "api_keys") in recorder.created_indexes
    assert ("idx_api_keys_hash", "api_keys") in recorder.created_indexes
