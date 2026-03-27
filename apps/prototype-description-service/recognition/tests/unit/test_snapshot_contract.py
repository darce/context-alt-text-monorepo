from __future__ import annotations

import json
from pathlib import Path

from recognition.interface_adapters.http.schemas.responses import ClusterSnapshotResponse


def test_cluster_snapshot_golden_fixture_matches_backend_snapshot_contract() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[5]
        / "packages"
        / "shared-contracts"
        / "recognition"
        / "cluster-snapshot.golden.json"
    )
    payload = json.loads(fixture_path.read_text())

    snapshot = ClusterSnapshotResponse.model_validate(payload)

    assert snapshot.snapshot_version == 104
    assert len(snapshot.clusters) == 2
    assert len(snapshot.members) == 3

    first_cluster = snapshot.clusters[0]
    assert first_cluster.representative_id == "4b8f0a3e-3f1f-4f59-96f2-bfb6c8c1d3bb"
    assert first_cluster.is_pinned is True
    assert first_cluster.representative_thumb_path == ("acx://cluster/6c1a2e32-31b2-4d54-a4de-98b1a73d77a1/media/501")

    second_cluster = snapshot.clusters[1]
    assert second_cluster.label is None
    assert second_cluster.suggested_label == "Alice Example"
    assert second_cluster.suggested_target_cluster_id == "6c1a2e32-31b2-4d54-a4de-98b1a73d77a1"

    first_member = snapshot.members[0]
    assert first_member.identity_uuid == "4b8f0a3e-3f1f-4f59-96f2-bfb6c8c1d3bb"
    assert first_member.cluster_uuid == first_cluster.cluster_uuid
    assert first_member.bbox.width == 80
    assert first_member.similarity == 0.98
