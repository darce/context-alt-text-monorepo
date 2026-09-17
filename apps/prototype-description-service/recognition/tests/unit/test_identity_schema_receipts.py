"""GPUFLOW-2 C0: cluster merge receipts + representative quality_components schema."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Float
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from db.models.identity import (
    ClusterMergeKind,
    ClusterMergeReceipt,
    IdentityCluster,
    IdentityClusterRepresentative,
    ReceiptExpiredError,
    ReceiptNotTopError,
    ReceiptStackUnavailableError,
    require_top_unreverted_receipt,
)

identity_schema = importlib.import_module("db.migrations.versions.001_identity_schema")


@dataclass
class _RecordingOp:
    created_tables: list[str] = field(default_factory=list)
    created_table_args: dict[str, tuple[object, ...]] = field(default_factory=dict)
    created_indexes: list[tuple[str, str]] = field(default_factory=list)

    def execute(self, sql: str) -> None:
        return None

    def get_bind(self):
        class _FakeResult:
            def scalar(self):
                return None

            def first(self):
                return None

        class _FakeBind:
            def execute(self, stmt, params=None):  # noqa: ANN001
                return _FakeResult()

        return _FakeBind()

    def create_table(self, name: str, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.created_tables.append(name)
        self.created_table_args[name] = args

    def create_index(self, name: str, table_name: str, columns: list[str], *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.created_indexes.append((name, table_name))

    def add_column(self, table_name: str, column: object) -> None:
        return None


def _unwrap_type(column_type: object) -> object:
    impl = getattr(column_type, "impl", column_type)
    return getattr(impl, "impl", impl)


def _receipt(
    *,
    created_at: datetime,
    sequence_no: int = 1,
    reverted_at: datetime | None = None,
) -> ClusterMergeReceipt:
    return ClusterMergeReceipt(
        receipt_id=uuid4(),
        tenant_id=uuid4(),
        survivor_cluster_id=uuid4(),
        source_cluster_id=uuid4(),
        source_label="source",
        moved_identity_ids=[uuid4()],
        rule_version="c1-policy-v1",
        kind=ClusterMergeKind.AUTO.value,
        created_at=created_at,
        expires_at=created_at + timedelta(days=7),
        reverted_at=reverted_at,
        sequence_no=sequence_no,
    )


def test_cluster_merge_receipts_orm_declares_contract_columns() -> None:
    columns = ClusterMergeReceipt.__table__.c
    assert set(columns.keys()) >= {
        "receipt_id",
        "tenant_id",
        "survivor_cluster_id",
        "source_cluster_id",
        "source_label",
        "moved_identity_ids",
        "rule_version",
        "kind",
        "created_at",
        "expires_at",
        "reverted_at",
        "sequence_no",
    }
    assert columns["sequence_no"].nullable is False
    unique_names = {
        constraint.name
        for constraint in ClusterMergeReceipt.__table__.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert "uq_cluster_merge_receipts_survivor_seq" in unique_names
    assert columns["receipt_id"].primary_key is True
    assert isinstance(_unwrap_type(columns["receipt_id"].type), PG_UUID)
    assert columns["source_label"].nullable is True
    assert columns["reverted_at"].nullable is True
    assert columns["expires_at"].nullable is False
    assert columns["kind"].nullable is False
    moved_type = _unwrap_type(columns["moved_identity_ids"].type)
    assert isinstance(moved_type, ARRAY)
    assert isinstance(_unwrap_type(moved_type.item_type), PG_UUID)


def test_cluster_merge_kind_is_centralized_enum() -> None:
    assert {member.value for member in ClusterMergeKind} == {"auto", "operator"}
    constraint_sql = " ".join(
        str(constraint.sqltext)
        for constraint in ClusterMergeReceipt.__table__.constraints
        if isinstance(constraint, sa.CheckConstraint)
    )
    assert "auto" in constraint_sql
    assert "operator" in constraint_sql


def test_identity_cluster_merge_receipts_are_ordered_created_at_then_sequence_desc() -> None:
    relationship = sa_inspect(IdentityCluster).relationships["merge_receipts"]
    order_by = relationship.order_by
    assert order_by is not None
    clauses = order_by if isinstance(order_by, tuple) else (order_by,)
    rendered = " ".join(str(clause).lower() for clause in clauses)
    assert "created_at" in rendered
    assert "sequence_no" in rendered
    assert rendered.count("desc") >= 2


def test_identity_cluster_representative_has_exactly_one_quality_scalar() -> None:
    columns = IdentityClusterRepresentative.__table__.c
    assert "quality_score" in columns
    assert "representative_quality" not in columns
    assert "quality_components" in columns
    assert columns["quality_components"].nullable is True
    assert isinstance(_unwrap_type(columns["quality_components"].type), JSONB)
    quality_scalars = [
        column.name
        for column in IdentityClusterRepresentative.__table__.columns
        if "quality" in column.name and isinstance(column.type, Float)
    ]
    assert quality_scalars == ["quality_score"]


def test_migration_creates_receipts_table_and_quality_components(monkeypatch) -> None:
    recorder = _RecordingOp()
    monkeypatch.setattr(identity_schema, "op", recorder)

    identity_schema.ensure_tables(recorder)

    assert "cluster_merge_receipts" in recorder.created_tables
    assert "cluster_merge_receipts" in identity_schema.EXPECTED_SCHEMA_TABLES
    assert "cluster_merge_receipts" in identity_schema.TENANT_TABLES
    assert "cluster_merge_receipts" in identity_schema.DOWNGRADE_TABLE_ORDER
    assert identity_schema.DOWNGRADE_TABLE_ORDER.index(
        "cluster_merge_receipts"
    ) < identity_schema.DOWNGRADE_TABLE_ORDER.index("identity_clusters")

    receipt_args = recorder.created_table_args["cluster_merge_receipts"]
    receipt_columns = {column.name: column for column in receipt_args if isinstance(column, sa.Column)}
    assert receipt_columns["receipt_id"].primary_key is True
    assert receipt_columns["moved_identity_ids"].nullable is False
    assert receipt_columns["kind"].nullable is False
    assert receipt_columns["reverted_at"].nullable is True
    assert receipt_columns["sequence_no"].nullable is False
    unique_names = {
        arg.name for arg in receipt_args if isinstance(arg, sa.UniqueConstraint)
    }
    assert "uq_cluster_merge_receipts_survivor_seq" in unique_names
    assert ("idx_cluster_merge_receipts_survivor", "cluster_merge_receipts") in recorder.created_indexes
    assert ("idx_cluster_merge_receipts_tenant", "cluster_merge_receipts") in recorder.created_indexes

    rep_args = recorder.created_table_args["identity_cluster_representatives"]
    rep_columns = {column.name: column for column in rep_args if isinstance(column, sa.Column)}
    assert "quality_score" in rep_columns
    assert "quality_components" in rep_columns
    assert "representative_quality" not in rep_columns
    assert rep_columns["quality_components"].nullable is True


def test_require_top_unreverted_receipt_refuses_non_top() -> None:
    now = datetime(2026, 9, 17, tzinfo=UTC)
    older = _receipt(created_at=now - timedelta(hours=2), sequence_no=1)
    newer = _receipt(created_at=now - timedelta(hours=1), sequence_no=2)
    stack = [newer, older]

    with pytest.raises(ReceiptNotTopError) as exc_info:
        require_top_unreverted_receipt(stack, older.receipt_id)

    assert exc_info.value.code == "receipt_not_top"
    assert exc_info.value.receipt_id == older.receipt_id
    assert require_top_unreverted_receipt(stack, newer.receipt_id) is newer


def test_require_top_unreverted_receipt_tie_breaks_equal_created_at_on_sequence_no() -> None:
    now = datetime(2026, 9, 17, tzinfo=UTC)
    first = _receipt(created_at=now, sequence_no=1)
    second = _receipt(created_at=now, sequence_no=2)
    stack = [first, second]

    with pytest.raises(ReceiptNotTopError) as exc_info:
        require_top_unreverted_receipt(stack, first.receipt_id)

    assert exc_info.value.code == "receipt_not_top"
    assert require_top_unreverted_receipt(stack, second.receipt_id) is second
    assert ClusterMergeReceipt.next_sequence_no(stack) == 3
    assert ClusterMergeReceipt.next_sequence_no(()) == 1


def test_reverting_non_top_receipt_is_impossible_at_repository_layer() -> None:
    now = datetime(2026, 9, 17, tzinfo=UTC)
    older = _receipt(created_at=now - timedelta(hours=2), sequence_no=1)
    newer = _receipt(created_at=now - timedelta(hours=1), sequence_no=2)
    cluster = IdentityCluster()
    cluster.merge_receipts = [newer, older]
    older.survivor_cluster = cluster
    newer.survivor_cluster = cluster

    with pytest.raises(ReceiptNotTopError) as exc_info:
        older.revert(now=now)

    assert exc_info.value.code == "receipt_not_top"
    assert older.reverted_at is None
    newer.revert(now=now)
    assert newer.reverted_at == now
    with pytest.raises(ReceiptNotTopError):
        newer.revert(now=now + timedelta(seconds=1))
    older.revert(now=now + timedelta(seconds=1))
    assert older.reverted_at == now + timedelta(seconds=1)


def test_revert_refuses_expired_top_receipt() -> None:
    created = datetime(2026, 9, 1, tzinfo=UTC)
    receipt = _receipt(created_at=created, sequence_no=1)
    now = receipt.expires_at + timedelta(seconds=1)

    with pytest.raises(ReceiptExpiredError) as exc_info:
        receipt.revert(now=now, sibling_receipts=[receipt])

    assert exc_info.value.code == "receipt_expired"
    assert exc_info.value.receipt_id == receipt.receipt_id
    assert receipt.reverted_at is None
    receipt.revert(now=receipt.expires_at, sibling_receipts=[receipt])
    assert receipt.reverted_at == receipt.expires_at


def test_revert_without_loaded_stack_fails_closed() -> None:
    now = datetime(2026, 9, 17, tzinfo=UTC)
    receipt = _receipt(created_at=now - timedelta(hours=1), sequence_no=1)

    with pytest.raises(ReceiptStackUnavailableError) as exc_info:
        receipt.revert(now=now)

    assert exc_info.value.code == "receipt_stack_unavailable"
    assert exc_info.value.receipt_id == receipt.receipt_id
    assert receipt.reverted_at is None
    receipt.revert(now=now, sibling_receipts=[receipt])
    assert receipt.reverted_at == now
