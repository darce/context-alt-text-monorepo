from __future__ import annotations

import importlib
from dataclasses import dataclass, field

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


def test_identity_schema_declares_expected_table_set() -> None:
    assert identity_schema.EXPECTED_SCHEMA_TABLES == [
        "tenants",
        "api_keys",
        "worker_capabilities",
        "media_identities",
        "curation_replay_records",
        "identity_clusters",
        "identity_members",
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
    assert recorder.dropped_tables[-2:] == ["api_keys", "tenants"]
    assert recorder.dropped_tables.index("identity_members") < recorder.dropped_tables.index("identity_clusters")
    assert recorder.dropped_tables.index("identity_cluster_representatives") < recorder.dropped_tables.index(
        "identity_clusters"
    )
    assert recorder.dropped_tables.index("identity_cluster_representatives") < recorder.dropped_tables.index(
        "media_identities"
    )
    assert recorder.dropped_tables.index("recognition_events") < recorder.dropped_tables.index("recognition_runs")
