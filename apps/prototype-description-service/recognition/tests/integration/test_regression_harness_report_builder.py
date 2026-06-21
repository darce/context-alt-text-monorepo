from __future__ import annotations

import pytest

from db.models import IdentityCluster, IdentityClusterRepresentative, IdentityMember, MediaIdentity
from recognition.application.regression_harness.report_builder import generate_canonical_report
from recognition.application.regression_harness.serialization import load_canonical_labels, write_json
from recognition.domain.locator import IdentityLocator


@pytest.mark.asyncio
async def test_generate_canonical_report_includes_labeled_clusters(db_session, tenant, tmp_path) -> None:
    identity_1 = MediaIdentity(
        tenant_id=tenant.id,
        media_id=101,
        media_url="http://example.test/101.jpg",
        bbox_x=10,
        bbox_y=20,
        bbox_width=30,
        bbox_height=40,
        confidence=0.99,
        embedding=[0.0] * 512,
    )
    identity_2 = MediaIdentity(
        tenant_id=tenant.id,
        media_id=102,
        media_url="http://example.test/102.jpg",
        bbox_x=11,
        bbox_y=21,
        bbox_width=31,
        bbox_height=41,
        confidence=0.98,
        embedding=[0.1] * 512,
    )
    db_session.add_all([identity_1, identity_2])
    await db_session.commit()

    cluster = IdentityCluster(
        tenant_id=tenant.id,
        label="Alice",
        user_confirmed=True,
        identity_count=2,
    )
    db_session.add(cluster)
    await db_session.commit()
    await db_session.refresh(cluster)

    db_session.add_all(
        [
            IdentityMember(tenant_id=tenant.id, cluster_id=cluster.id, identity_id=identity_1.id, similarity=1.0),
            IdentityMember(tenant_id=tenant.id, cluster_id=cluster.id, identity_id=identity_2.id, similarity=0.9),
        ]
    )
    db_session.add(
        IdentityClusterRepresentative(
            tenant_id=tenant.id,
            cluster_id=cluster.id,
            identity_id=identity_1.id,
            embedding=[0.0] * 512,
            quality_score=0.9,
            diversity_score=0.1,
        )
    )
    await db_session.commit()

    report = await generate_canonical_report(db_session, tenant_id=str(tenant.id))
    assert report["tenant_id"] == str(tenant.id)
    assert report["schema_version"] == 1

    canonical_clusters = report["canonical_clusters"]
    assert isinstance(canonical_clusters, list)
    assert len(canonical_clusters) == 1
    cluster_payload = canonical_clusters[0]
    assert cluster_payload["canonical_label"] == "Alice"
    assert cluster_payload["final_cluster_id"] == str(cluster.id)
    assert len(cluster_payload["member_identities"]) == 2
    assert len(cluster_payload["final_representatives"]) == 1

    output_path = tmp_path / "canonical_report.json"
    write_json(output_path, report)
    labels = load_canonical_labels(output_path)
    assert (
        labels[IdentityLocator(media_id=101, bbox_x=10, bbox_y=20, bbox_width=30, bbox_height=40, crop_hash=None)]
        == "Alice"
    )
