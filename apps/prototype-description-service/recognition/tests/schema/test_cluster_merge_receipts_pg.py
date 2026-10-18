from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from db.models.identity import ClusterMergeReceipt, IdentityCluster
from db.models.tenant import Tenant

pytestmark = pytest.mark.pg


def test_pg_cluster_merge_receipt_round_trip_preserves_uuid_ids_and_uuid_array_type(pg_migrated_engine) -> None:
    tenant_id = uuid4()
    survivor_cluster_id = uuid4()
    moved_identity_ids = [uuid4(), uuid4()]
    now = datetime.now(UTC)

    with pg_migrated_engine.connect() as conn:
        transaction = conn.begin()
        try:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
                {"tenant_id": str(tenant_id)},
            )
            with Session(bind=conn, join_transaction_mode="create_savepoint") as session:
                session.add(Tenant(id=tenant_id, site_url=f"https://{tenant_id}.example.test"))
                session.add(IdentityCluster(id=survivor_cluster_id, tenant_id=tenant_id))
                receipt = ClusterMergeReceipt(
                    receipt_id=uuid4(),
                    tenant_id=tenant_id,
                    survivor_cluster_id=survivor_cluster_id,
                    source_cluster_id=uuid4(),
                    source_label="source",
                    moved_identity_ids=moved_identity_ids,
                    rule_version="pg-round-trip-v1",
                    kind="auto",
                    expires_at=now + timedelta(days=7),
                    sequence_no=1,
                )
                session.add(receipt)
                session.flush()
                receipt_id = receipt.receipt_id
                session.expunge(receipt)

                loaded = session.get(ClusterMergeReceipt, receipt_id)

            assert loaded is not None
            assert loaded.moved_identity_ids == moved_identity_ids
            assert all(isinstance(identity_id, UUID) for identity_id in loaded.moved_identity_ids)

            server_type = conn.execute(
                text(
                    "SELECT format_type(a.atttypid, a.atttypmod) "
                    "FROM pg_attribute a "
                    "JOIN pg_class c ON c.oid = a.attrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relname = 'cluster_merge_receipts' "
                    "AND a.attname = 'moved_identity_ids' AND NOT a.attisdropped"
                )
            ).scalar_one()
            assert server_type == "uuid[]", f"moved_identity_ids server type={server_type!r}, expected 'uuid[]'"
        finally:
            transaction.rollback()
