"""Synthetic S4 -> S5 wire regressions; no embeddings, tenant stores or private data.

Canon v0.26.2: GRPH-18 (Never trust the transitive closure of a raw similarity
threshold, Introduction to Information Retrieval, § 17.2) motivates independent
pair/path evidence; EMB-01 (One embedding space per comparison, Foundations of
Vector Retrieval, ch. 1) motivates the per-leg envelope. These tests check the
wire contract, not the still-unimplemented S4 computations or real observations.
"""

from __future__ import annotations

import copy
import json
import math
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from scripts.eval_harness import firbench_contract as fc

FIXTURES = Path(__file__).parent / "fixtures" / "firbench_interchange_v1"
LEG_KEY = "sface__native__ab12cd__cv4.10.0__ort1.18.0"


def _available(data: Any) -> dict[str, Any]:
    return {"status": "available", "reason": None, "data": data}


def _absent(status: str = "not_evaluated", reason: str = "no comparison run recorded") -> dict[str, Any]:
    return {"status": status, "reason": reason, "data": None}


def _node(number: int) -> dict[str, str]:
    return {"face_id": f"face-{number:04}", "identity_id": f"id-{number:04}", "verification_ref": f"qc-{number:04}"}


def _edge(left: int, right: int) -> dict[str, Any]:
    return {"source_face_id": f"face-{left:04}", "target_face_id": f"face-{right:04}", "cosine_similarity": 0.85}


def _payload() -> dict[str, Any]:
    """A fake producer with one bridged different-identity pair and one unlinked pair."""
    rates = {
        name: _available(0.0)
        for name in ("pairwise_precision", "pairwise_recall", "bcubed_precision", "bcubed_recall", "noise_fraction")
    }
    rates.update(
        bcubed_precision=_available(0.5),
        bcubed_recall=_available(1.0),
        noise_fraction=_available(0.25),
        pairwise_recall=_absent("unavailable", "no true named pairs"),
    )
    leg = {
        "leg_key": LEG_KEY,
        "config": {
            "similarity_threshold": 0.8,
            "metric": "cosine",
            "linkage": "average",
            "production_algorithm": "hdbscan",
            "cluster_selection_epsilon": 0.6324555320336759,
            "production_parameters": [{"name": "min_cluster_size", "value": 2}],
        },
        "dendrogram_cut": {
            "distance": 0.2,
            "caption": "Cut at cosine distance 1 minus the production similarity threshold",
            "labels": [{"face_id": f"face-{n:04}", "label": 0 if n < 4 else -1} for n in range(1, 5)],
        },
        "acceptance_tau_reference": _available(
            {"tau": 0.41, "distance": 0.59, "label": "acceptance tau (not a cluster cut)"}
        ),
        "labels": _available([{"face_id": f"face-{n:04}", "label": 0 if n < 4 else -1} for n in range(1, 5)]),
        "partition_metrics": _available(
            {
                "unit": "gt_face",
                "scored_identity_status": "named",
                "excluded_identity_statuses": ["unknown", "unresolved"],
                "noise_policy": "minus_one_is_unpaired_and_bcubed_singleton",
                "named_faces": 4,
                "unknown_faces": 0,
                "unresolved_faces": 0,
                "coassigned_true_pairs": 0,
                "coassigned_predicted_pairs": 3,
                "true_pairs": 0,
                "merges": 1,
                "fragmentation": 0,
                "unknown_absorbed": 0,
                "noise_faces": 1,
                **rates,
            }
        ),
        "order_stability": _available(
            {"n_orders": 3, "seed": 7, "stable_pairs": 3, "compared_pairs": 3, "fraction": _available(1.0)}
        ),
        "chaining": _available(
            {
                "scope": {
                    "frame_id": "frame-0001",
                    "fold": 0,
                    "fold_role": "test",
                    "pair_selection_rule": "synthetic held-out verified-different pairs",
                },
                "input_pairs": 3,
                "eligible_pairs": 2,
                "path_linked_pairs": 1,
                "third_identity_linked_pairs": 1,
                "D": _available(0.5),
                "C": _available(0.5),
                "exclusions": [{"reason": "unverified_endpoint", "count": 1}],
                "pairs": [
                    {
                        "pair_id": "pair-0001",
                        "left": _node(1),
                        "right": _node(3),
                        "path_linked": True,
                        "through_third_identity": True,
                        "third_identity_id": "id-0002",
                        "path": [dict(_node(n), identity_status="named") for n in (1, 2, 3)],
                        "edges": [_edge(1, 2), _edge(2, 3)],
                    },
                    {
                        "pair_id": "pair-0002",
                        "left": _node(1),
                        "right": _node(4),
                        "path_linked": False,
                        "through_third_identity": False,
                        "third_identity_id": None,
                        "path": None,
                        "edges": [],
                    },
                ],
            }
        ),
        "mutual_knn": _available(
            {"k": 2, "face_ids": [f"face-{n:04}" for n in range(1, 5)], "edges": [_edge(1, 2), _edge(2, 3)]}
        ),
        "neighbours": _available({"k": 2, "metric": "cosine", "edges": [_edge(1, 2), _edge(1, 3)]}),
        "dendrogram": _available(
            {
                "leaf_face_ids": [f"face-{n:04}" for n in range(1, 5)],
                "linkage": [[0, 1, 0.1, 2], [2, 4, 0.15, 3], [3, 5, 0.9, 4]],
                "cophenetic_correlation": _available(0.9),
            }
        ),
        "pca_spectrum": _available(
            {"explained_variance_ratio": [0.75, 0.25], "effective_dimension": 1.6, "retained_components": 2}
        ),
        "histograms": [
            {"kind": "intra_identity_cosine", "result": _absent("unavailable", "no true named pairs")},
            {"kind": "inter_identity_cosine", "result": _available({"bins": [{"lower": -1, "upper": 1, "count": 6}]})},
            {"kind": "vector_norm", "result": _available({"bins": [{"lower": 0, "upper": 2, "count": 4}]})},
        ],
        "companions": {"knn_jaccard": _absent(), "linear_cka": _absent()},
        "projections": [
            {
                "name": "projection-0001",
                "method": "umap",
                "n_components": 2,
                "seed": 7,
                "diagnostic_only": True,
                "caption": "diagnostic projection · distances not meaningful",
                "parameters": {"n_neighbors": 15, "min_dist": 0.05},
                "versions": [{"package": "umap-learn", "version": "synthetic-1"}],
                "result": _available(
                    [{"face_id": f"face-{n:04}", "coordinates": [n * 0.1, n * 0.2]} for n in range(1, 5)]
                ),
            }
        ],
    }
    return {"schema_version": 1, "legs": [leg]}


def _validate(payload: dict[str, Any]) -> None:
    fc.validate_interchange("clusters-v1", payload)


def test_accepts_all_required_s4_evidence_and_multiple_separate_legs() -> None:
    payload = _payload()
    second = copy.deepcopy(payload["legs"][0])
    second["leg_key"] = "auraface__native__cd34ef__cv4.10.0__ort1.18.0"
    second["config"]["linkage"] = "complete"
    payload["legs"].append(second)
    _validate(payload)


def test_single_linkage_is_refused_in_frozen_fixture() -> None:
    payload = json.loads((FIXTURES / "clusters-v1.json").read_text())
    leg = payload["legs"][0] if "legs" in payload else payload
    leg["config"]["linkage"] = "single"
    with pytest.raises(fc.FrameContractError, match="linkage"):
        _validate(payload)


def test_missing_production_threshold_has_uncut_labels_and_separate_tau() -> None:
    payload = _payload()
    leg = payload["legs"][0]
    leg["config"].update(similarity_threshold=None, cluster_selection_epsilon=None)
    leg["dendrogram_cut"] = {"distance": None, "caption": "no production cut recorded", "labels": None}
    _validate(payload)
    assert leg["acceptance_tau_reference"]["data"]["distance"] == 0.59


def test_synthetic_nextafter_tau_reference_roundtrips_without_changing_production_cut(tmp_path: Path) -> None:
    payload = _payload()
    leg = payload["legs"][0]
    production_config = copy.deepcopy(leg["config"])
    production_cut = copy.deepcopy(leg["dendrogram_cut"])
    tau = math.nextafter(1.0, math.inf)
    distance = 1.0 - tau
    assert tau > 1.0 and distance < 0.0
    leg["acceptance_tau_reference"]["data"].update(tau=tau, distance=distance)
    _validate(payload)
    output = tmp_path / "synthetic-nextafter-clusters.json"
    output.write_text(json.dumps(payload, allow_nan=False), encoding="utf-8")
    restored = json.loads(output.read_text(encoding="utf-8"))
    _validate(restored)
    reference = restored["legs"][0]["acceptance_tau_reference"]["data"]
    assert reference == {"tau": tau, "distance": distance, "label": "acceptance tau (not a cluster cut)"}
    assert restored["legs"][0]["config"] == production_config
    assert restored["legs"][0]["dendrogram_cut"] == production_cut


@pytest.mark.parametrize("field", ["tau", "distance"])
@pytest.mark.parametrize("value", [-sys.float_info.max, -2, 0, 3, sys.float_info.max])
def test_acceptance_reference_fields_accept_finite_json_numbers_without_cut_bounds(field: str, value: float) -> None:
    payload = _payload()
    payload["legs"][0]["acceptance_tau_reference"]["data"][field] = value
    _validate(payload)


@pytest.mark.parametrize("field", ["tau", "distance"])
@pytest.mark.parametrize("value", [True, False, float("nan"), float("inf"), -float("inf"), "0.5", None, []])
def test_acceptance_reference_fields_reject_booleans_nonfinite_and_nonnumbers(field: str, value: Any) -> None:
    payload = _payload()
    payload["legs"][0]["acceptance_tau_reference"]["data"][field] = value
    with pytest.raises(fc.FrameContractError, match=field):
        _validate(payload)


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("config", "similarity_threshold", -math.nextafter(1.0, math.inf)),
        ("config", "similarity_threshold", math.nextafter(1.0, math.inf)),
        ("dendrogram_cut", "distance", math.nextafter(0.0, -math.inf)),
        ("dendrogram_cut", "distance", math.nextafter(2.0, math.inf)),
        *[
            (section, field, value)
            for section, field in [("config", "similarity_threshold"), ("dendrogram_cut", "distance")]
            for value in [True, False, float("nan"), float("inf"), -float("inf")]
        ],
    ],
)
def test_production_threshold_and_cut_keep_their_numeric_domains(section: str, field: str, value: Any) -> None:
    payload = _payload()
    payload["legs"][0][section][field] = value
    with pytest.raises(fc.FrameContractError, match=field):
        _validate(payload)


@pytest.mark.parametrize(
    "section",
    [
        "partition_metrics",
        "order_stability",
        "chaining",
        "mutual_knn",
        "neighbours",
        "dendrogram",
        "pca_spectrum",
        "acceptance_tau_reference",
        "labels",
    ],
)
@pytest.mark.parametrize("status", ["unavailable", "not_evaluated"])
def test_explicit_absent_diagnostics(section: str, status: str) -> None:
    payload = _payload()
    payload["legs"][0][section] = _absent(status, "synthetic missing evidence")
    _validate(payload)


def test_projection_unavailable_preserves_pca_table_and_metric_evidence() -> None:
    payload = _payload()
    leg = payload["legs"][0]
    projection = leg["projections"][0]
    pca = copy.deepcopy(projection)
    pca.update(
        name="projection-0002",
        method="pca",
        parameters={"n_neighbors": None, "min_dist": None},
        versions=[{"package": "numpy", "version": "synthetic-1"}],
    )
    projection.update(versions=[], result=_absent("unavailable", "umap-learn is not installed"))
    leg["projections"].append(pca)
    _validate(payload)
    assert leg["partition_metrics"]["status"] == leg["neighbours"]["status"] == "available"


def test_companion_evidence_between_runs_of_same_leg() -> None:
    payload = _payload()
    payload["legs"][0]["companions"] = {
        "knn_jaccard": _available(
            {"reference_run_id": "run-0001", "comparison_run_id": "run-0002", "k": 2, "value": 0.75}
        ),
        "linear_cka": _available(
            {"reference_run_id": "run-0001", "comparison_run_id": "run-0002", "dimension": 128, "value": 1.0}
        ),
    }
    _validate(payload)


def test_no_eligible_pairs_reports_undefined_rates_without_zero_claim() -> None:
    payload = _payload()
    data = payload["legs"][0]["chaining"]["data"]
    data.update(
        input_pairs=1,
        eligible_pairs=0,
        path_linked_pairs=0,
        third_identity_linked_pairs=0,
        D=_absent("unavailable", "no eligible pairs"),
        C=_absent("unavailable", "no eligible pairs"),
        pairs=[],
    )
    _validate(payload)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("config", "linkage"), "ward"),
        (("config", "linkage"), "median"),
        (("config", "linkage"), "centroid"),
        (("config", "metric"), "euclidean"),
        (("config", "similarity_threshold"), 1.1),
        (("partition_metrics", "data", "merges"), -1),
        (("partition_metrics", "data", "pairwise_precision", "data"), 1.1),
        (("partition_metrics", "data", "scored_identity_status"), "unknown"),
        (("chaining", "data", "eligible_pairs"), True),
        (("chaining", "data", "D", "data"), -0.1),
        (("chaining", "data", "scope", "fold_role"), "fit"),
        (("chaining", "data", "pairs", 0, "left", "verification_ref"), ""),
        (("chaining", "data", "pairs", 0, "path"), [_node(1)]),
        (("chaining", "data", "pairs", 0, "edges", 0, "cosine_similarity"), 1.1),
        (("dendrogram", "data", "linkage", 0), [0, 1, 0.2]),
        (("dendrogram", "data", "linkage", 0), [0, 1, 0.2, 2, 99]),
        (("dendrogram", "data", "linkage", 0, 3), 2.5),
        (("pca_spectrum", "data", "explained_variance_ratio", 0), -0.1),
        (("pca_spectrum", "data", "retained_components"), 0),
        (("histograms", 0, "kind"), "unrelated_metric"),
        (("histograms", 1, "result", "data", "bins", 0, "count"), -1),
        (("companions", "linear_cka", "data"), {"value": 1.0}),
        (("projections", 0, "diagnostic_only"), False),
        (("projections", 0, "method"), "tsne"),
        (("projections", 0, "parameters", "n_neighbors"), 0),
        (("projections", 0, "parameters", "min_dist"), -0.1),
        (("projections", 0, "result", "data", 0, "coordinates"), [0.1]),
        (("projections", 0, "result", "data", 0, "coordinates"), [0.1, 0.2, 0.3]),
        (("projections", 0, "result", "data", 0, "coordinates", 0), float("nan")),
        (("acceptance_tau_reference", "data", "label"), "cluster cut"),
        (("labels", "data", 0, "label"), -2),
    ],
)
def test_rejects_invalid_typed_evidence(path: tuple, value: Any) -> None:
    payload = _payload()
    current = payload["legs"][0]
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value
    with pytest.raises(fc.FrameContractError):
        _validate(payload)


@pytest.mark.parametrize("field", ["real_name", "pixels", "image_data"])
def test_pair_drilldown_has_no_name_or_pixel_field(field: str) -> None:
    payload = _payload()
    payload["legs"][0]["chaining"]["data"]["pairs"][0]["left"][field] = "synthetic forbidden field"
    with pytest.raises(fc.FrameContractError):
        _validate(payload)


@pytest.mark.parametrize(
    "status,reason,data",
    [
        ("available", None, None),
        ("available", "missing", 0.5),
        ("unavailable", None, None),
        ("not_evaluated", "", None),
        ("unavailable", "missing", 0.5),
    ],
)
def test_states_cannot_hide_missing_or_fabricated_values(status: str, reason: Any, data: Any) -> None:
    payload = _payload()
    payload["legs"][0]["chaining"]["data"]["D"] = {"status": status, "reason": reason, "data": data}
    with pytest.raises(fc.FrameContractError):
        _validate(payload)


def test_uncut_state_cannot_claim_cut_labels() -> None:
    payload = _payload()
    payload["legs"][0]["config"].update(similarity_threshold=None, cluster_selection_epsilon=None)
    with pytest.raises(fc.FrameContractError):
        _validate(payload)


def test_unknown_intermediate_can_link_d_but_cannot_establish_c() -> None:
    payload = _payload()
    chaining = payload["legs"][0]["chaining"]["data"]
    pair = chaining["pairs"][0]
    pair.update(through_third_identity=False, third_identity_id=None)
    pair["path"][1] = {
        "face_id": "face-0002",
        "identity_status": "unknown",
        "identity_id": None,
        "verification_ref": None,
    }
    chaining.update(third_identity_linked_pairs=0, C=_available(0.0))
    _validate(payload)
    assert chaining["D"]["data"] == 0.5


def test_path_nodes_cannot_silently_default_identity_status() -> None:
    payload = _payload()
    del payload["legs"][0]["chaining"]["data"]["pairs"][0]["path"][1]["identity_status"]
    with pytest.raises(fc.FrameContractError):
        _validate(payload)


@pytest.mark.parametrize("section", ["projections", "histograms"])
def test_absent_visual_evidence_needs_explicit_state_records(section: str) -> None:
    payload = _payload()
    payload["legs"][0][section] = []
    with pytest.raises(fc.FrameContractError):
        _validate(payload)


def test_histogram_kinds_cannot_omit_norm_or_repeat_cosine() -> None:
    payload = _payload()
    histograms = payload["legs"][0]["histograms"]
    histograms[2] = copy.deepcopy(histograms[1])
    with pytest.raises(fc.FrameContractError):
        _validate(payload)


def test_zero_eligible_pairs_cannot_claim_a_measured_zero_rate() -> None:
    payload = _payload()
    chaining = payload["legs"][0]["chaining"]["data"]
    chaining.update(
        eligible_pairs=0,
        path_linked_pairs=0,
        third_identity_linked_pairs=0,
        pairs=[],
        D=_available(0.0),
        C=_available(0.0),
    )
    with pytest.raises(fc.FrameContractError):
        _validate(payload)


def test_synthetic_fixture_roundtrip_supplies_report_drilldown(tmp_path: Path) -> None:
    """Fake file-only S4/S5 handoff, with independent count/rate/path oracles."""
    payload = json.loads((FIXTURES / "clusters-v1.json").read_text())
    _validate(payload)
    output = tmp_path / "clusters.json"
    output.write_text(json.dumps(payload, sort_keys=True, allow_nan=False), encoding="utf-8")
    received = json.loads(output.read_text(encoding="utf-8"))
    _validate(received)
    leg = received["legs"][0]
    chaining = leg["chaining"]["data"]
    pairs = chaining["pairs"]
    denominator = chaining["eligible_pairs"]
    assert denominator == len(pairs) == 2
    assert chaining["input_pairs"] == denominator + sum(row["count"] for row in chaining["exclusions"])
    assert chaining["path_linked_pairs"] == sum(pair["path_linked"] for pair in pairs) == 1
    assert chaining["third_identity_linked_pairs"] == sum(pair["through_third_identity"] for pair in pairs) == 1
    assert chaining["D"]["data"] == float(Fraction(chaining["path_linked_pairs"], denominator))
    assert chaining["C"]["data"] == float(Fraction(chaining["third_identity_linked_pairs"], denominator))
    graph_edges = {
        frozenset((edge["source_face_id"], edge["target_face_id"])) for edge in leg["mutual_knn"]["data"]["edges"]
    }
    for pair in pairs:
        assert pair["left"]["identity_id"] != pair["right"]["identity_id"]
        assert pair["left"]["verification_ref"] and pair["right"]["verification_ref"]
        if not pair["path_linked"]:
            assert pair["path"] is None and pair["edges"] == []
            continue
        path = pair["path"]
        assert path[0]["face_id"] == pair["left"]["face_id"]
        assert path[-1]["face_id"] == pair["right"]["face_id"]
        assert len(pair["edges"]) == len(path) - 1
        for (left, right), edge in zip(zip(path, path[1:], strict=False), pair["edges"], strict=True):
            assert edge["source_face_id"] == left["face_id"]
            assert edge["target_face_id"] == right["face_id"]
            assert frozenset((left["face_id"], right["face_id"])) in graph_edges
            assert edge["cosine_similarity"] >= leg["config"]["similarity_threshold"]
        third = pair["third_identity_id"]
        assert third not in {pair["left"]["identity_id"], pair["right"]["identity_id"]}
        assert any(node["identity_id"] == third and node["verification_ref"] for node in path[1:-1])
    face_ids = {row["face_id"] for row in leg["labels"]["data"]}
    assert face_ids == set(leg["dendrogram"]["data"]["leaf_face_ids"])
    assert face_ids == {row["face_id"] for row in leg["projections"][0]["result"]["data"]}
    metrics = leg["partition_metrics"]["data"]
    assert metrics["named_faces"] == len(face_ids) == 4
    assert metrics["noise_faces"] == sum(row["label"] == -1 for row in leg["labels"]["data"])
    assert metrics["noise_fraction"]["data"] == float(Fraction(metrics["noise_faces"], metrics["named_faces"]))
    assert metrics["pairwise_precision"]["data"] == float(
        Fraction(metrics["coassigned_true_pairs"], metrics["coassigned_predicted_pairs"])
    )
    assert metrics["true_pairs"] == 0 and metrics["pairwise_recall"]["status"] == "unavailable"
    s = leg["config"]["similarity_threshold"]
    tau = leg["acceptance_tau_reference"]["data"]["tau"]
    assert leg["dendrogram_cut"]["distance"] == pytest.approx(1 - s)
    assert leg["config"]["cluster_selection_epsilon"] ** 2 == pytest.approx(2 * (1 - s))
    assert leg["acceptance_tau_reference"]["data"]["distance"] == pytest.approx(1 - tau)
    assert s != tau
