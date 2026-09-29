"""DEFWAVE-2 cluster snapshot receipt regressions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm.attributes import set_committed_value

from db.models.identity import ClusterMergeReceipt
from db.models.identity import IdentityCluster as ClusterModel
from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository

TENANT_ID = UUID("f1a2b3c4-d5e6-47f8-9012-3456789abcde")
CLUSTER_ID = UUID("6c1a2e32-31b2-4d54-a4de-98b1a73d77a1")


class _ScalarResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarResult:
        return self

    def all(self) -> list[object]:
        return list(self._rows)


def _receipt(*, sequence_no: int, created_at: datetime, expires_at: datetime) -> ClusterMergeReceipt:
    return ClusterMergeReceipt(
        receipt_id=uuid4(),
        tenant_id=TENANT_ID,
        survivor_cluster_id=CLUSTER_ID,
        source_cluster_id=uuid4(),
        source_label="Source cluster",
        moved_identity_ids=[uuid4()],
        rule_version="test-policy-v1",
        kind="auto",
        created_at=created_at,
        expires_at=expires_at,
        reverted_at=None,
        sequence_no=sequence_no,
    )


@pytest.mark.asyncio
async def test_targeted_snapshot_omits_older_receipt_when_current_top_is_expired() -> None:
    now = datetime.now(tz=UTC)
    older = _receipt(
        sequence_no=2,
        created_at=now - timedelta(hours=2),
        expires_at=now + timedelta(hours=1),
    )
    expired_top = _receipt(
        sequence_no=1,
        created_at=now - timedelta(hours=1),
        expires_at=now - timedelta(seconds=1),
    )
    model = ClusterModel(
        id=CLUSTER_ID,
        tenant_id=TENANT_ID,
        label="Alice",
        identity_count=2,
        clustering_algorithm="graph",
        user_confirmed=True,
        created_at=now - timedelta(days=1),
        updated_at=now,
    )
    set_committed_value(model, "merge_receipts", [expired_top, older])
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[_ScalarResult([expired_top]), _ScalarResult([model])],
    )

    [cluster] = await SqlAlchemyClusterRepository(session).get_clusters_by_ids(
        str(TENANT_ID), [str(CLUSTER_ID)]
    )

    assert cluster.undoable_merge_receipt_id is None
    assert len(session.execute.await_args_list) == 2
    receipt_stmt = session.execute.await_args_list[0].args[0]
    rendered = str(receipt_stmt).lower()
    assert "row_number()" in rendered
    assert "created_at desc" in rendered
    assert "sequence_no desc" in rendered
    assert "reverted_at is null" in rendered
    assert "receipt_rank =" in rendered
    assert "expires_at <" not in rendered
