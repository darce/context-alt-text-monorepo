"""FB1-S4-02: acceptance calibration has a separate domain from production cuts.

Synthetic native records exercise the actual S3 calibrator; no threshold or
projection substitutes feed the cluster diagnostics.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace

import numpy as np
import pytest

from scripts.eval_harness import firbench_clusters as fcl
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_score as fs
from scripts.eval_harness.firbench_frames import NonMatedUnit
from scripts.eval_harness.firbench_legs import FaceSearchRecord


def _config(tau: float | None, **changes: object) -> fcl.ClusterRunConfig:
    config = fcl.ClusterRunConfig(
        similarity_threshold=0.8,
        linkage="average",
        knn_k=1,
        histogram_bins=4,
        n_orders=3,
        order_seed=7,
        projection_seed=11,
        umap_n_neighbors=2,
        umap_min_dist=0.1,
        acceptance_tau=tau,
    )
    return replace(config, **changes)


@pytest.fixture
def leg() -> fcl.LegInput:
    faces = tuple(
        fcl.LegFace(f"face-{i}", identity, fc.IdentityStatus.named, 0, f"synthetic-qc-{i}")
        for i, identity in enumerate(("id-A", "id-A", "id-B", "id-B"))
    )
    return fcl.LegInput(
        leg_key="sface__native__synthetic__cv4__ort1",
        leg_kind=fc.LegKind.sface,
        run_id="synthetic-run",
        faces=faces,
        vectors=np.array([[1.0, 0.1], [1.0, -0.1], [0.1, 1.0], [-0.1, 1.0]]),
    )


@pytest.mark.parametrize("method", ["average", "complete"])
@pytest.mark.parametrize("similarity", [None, -1.0, 0.8, 1.0])
def test_actual_v2_calibration_above_one_is_only_a_reference(
    leg: fcl.LegInput, method: str, similarity: float | None
) -> None:
    unit = NonMatedUnit(unit_id="nonmated-face", fold=1, psu_id="fit-psu", cohort=None)
    record = FaceSearchRecord(
        face_id=unit.unit_id,
        image_id="fit-image",
        psu_id=unit.psu_id,
        identity_id=None,
        identity_status=fc.IdentityStatus.unknown,
        fold=1,
        fold_role=fc.FoldRole.fit,
        cell=("unknown", "unknown"),
        unit_id=unit.unit_id,
        sampling_arm=fc.SamplingArm.challenge,
        inclusion_probability=None,
        cohort=None,
        leg_key=leg.leg_key,
        arm=fc.Arm.native,
        arm_availability=fc.ArmStatus.available,
        alignment_mode=fc.AlignmentMode.separable,
        stage_reached=fc.SearchStage.embedded,
        top_k=(("fit-enrolled", 1.0),),
        gallery_sha256="a" * 64,
        timing_receipt_ref="synthetic-receipt",
    )
    tau = fs.calibrate_tau(
        [record],
        units=[unit],
        calibration_folds=frozenset({1}),
        fpir_target=0.1,
        boundary=fc.BoundarySemantics.v2,
        identity_folds={"fit-enrolled": 1},
    )
    assert tau == math.nextafter(1.0, math.inf)
    assert fs.curve([record], units=[unit], thresholds=[tau], boundary=fc.BoundarySemantics.v2)[0].fpi == 0

    config = _config(tau, similarity_threshold=similarity, linkage=method)
    entry = fcl.build_leg_diagnostics(leg, config=config)
    assert entry["acceptance_tau_reference"] == {
        "status": "available",
        "reason": None,
        "data": {"tau": tau, "distance": 1.0 - tau, "label": "acceptance tau (not a cluster cut)"},
    }
    assert entry["acceptance_tau_reference"]["data"]["distance"] < 0.0

    # All actual clustering, partition, chaining and projection evidence stays
    # identical when acceptance calibration is absent.
    control = fcl.build_leg_diagnostics(leg, config=replace(config, acceptance_tau=None))
    assert control["acceptance_tau_reference"] == {
        "status": "unavailable",
        "reason": "no acceptance tau recorded",
        "data": None,
    }
    assert {k: v for k, v in entry.items() if k != "acceptance_tau_reference"} == {
        k: v for k, v in control.items() if k != "acceptance_tau_reference"
    }
    cut = entry["dendrogram_cut"]
    if similarity is None:
        assert cut == {"distance": None, "caption": "no production cut recorded", "labels": None}
        assert entry["labels"]["status"] == "unavailable"
    else:
        assert cut["distance"] == 1.0 - similarity
        assert 0.0 <= cut["distance"] <= 2.0
        assert cut["caption"] == "Cut at cosine distance 1 minus the production similarity threshold"
        if similarity == 0.8:
            labels = [row["label"] for row in cut["labels"]]
            assert labels[0] == labels[1] != labels[2] == labels[3]


@pytest.mark.parametrize(
    "tau",
    [-4, -1.25, -1.0, 0, 1.0, math.nextafter(1.0, math.inf), 2.5, 4, -1e308, 1e308],
)
def test_finite_reference_values_keep_exact_unclamped_distance(leg: fcl.LegInput, tau: float) -> None:
    entry = fcl.build_leg_diagnostics(leg, config=_config(tau))
    reference = entry["acceptance_tau_reference"]
    assert reference["status"] == "available"
    assert reference["data"]["tau"] == tau
    assert reference["data"]["distance"] == 1.0 - tau
    assert json.loads(json.dumps(reference, allow_nan=False)) == reference
    assert entry["dendrogram_cut"]["distance"] == 1.0 - 0.8


@pytest.mark.parametrize("tau", [math.nan, math.inf, -math.inf, True, False, "0.5", "1.1", object()])
def test_acceptance_reference_rejects_nonfinite_bool_and_nonnumeric(tau: object) -> None:
    with pytest.raises(fc.FrameContractError):
        _config(tau)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "similarity",
    [math.nextafter(-1.0, -math.inf), math.nextafter(1.0, math.inf), -4, 4, math.nan, math.inf, -math.inf, True, False],
)
def test_production_similarity_domain_is_still_restricted(leg: fcl.LegInput, similarity: float) -> None:
    with pytest.raises(fc.FrameContractError):
        _config(0.5, similarity_threshold=similarity)
    with pytest.raises(fc.FrameContractError):
        fcl.cosine_dendrogram(leg.vectors, method="average", similarity_threshold=similarity)
    with pytest.raises(fc.FrameContractError):
        fcl.reference_threshold_cluster(leg.vectors, similarity_threshold=similarity)


@pytest.mark.parametrize("method", ["ward", "centroid", "median", "single"])
def test_reference_domain_does_not_widen_allowed_linkage(leg: fcl.LegInput, method: str) -> None:
    with pytest.raises(fc.LinkageMetricError):
        _config(None, linkage=method)
    with pytest.raises(fc.LinkageMetricError):
        fcl.cosine_dendrogram(leg.vectors, method=method, similarity_threshold=0.8)
