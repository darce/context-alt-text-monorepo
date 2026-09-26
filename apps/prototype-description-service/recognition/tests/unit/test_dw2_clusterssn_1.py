from datetime import UTC, datetime

import numpy as np

from recognition.domain.representative import ClusterRepresentative
from recognition.interface_adapters.http.routers.clusters_snapshot import _export_representative_quality


def test_export_preserves_quality_score_and_explicit_null_component() -> None:
    representative = ClusterRepresentative(
        id="representative",
        cluster_id="cluster",
        identity_id="identity",
        embedding=np.array([]),
        created_at=datetime.now(UTC),
        quality_score=0.82,
        quality_components={
            "confidence": 0.94,
            "bbox_area": 7680,
            "sharpness": None,
            "occlusion_severity": 0.12,
        },
    )

    score, components = _export_representative_quality(representative)

    assert score == 0.82
    assert components is not None
    assert components.model_dump(mode="json") == {
        "confidence": 0.94,
        "bbox_area": 7680.0,
        "sharpness": None,
        "occlusion_severity": 0.12,
    }
