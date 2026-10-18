"""S4 cluster diagnostics on synthetic vectors, pseudonymous identities and fake pairs only.

No real names, pixels or private files. Canon v0.26.2: GRPH-18 (the dendrogram cuts at
1 - s and the acceptance tau is a separate reference), GRPH-17 (mutual kNN), GRPH-22
(partition plus verification), EMB-01 (one space per comparison), VIZ-18/VIZ-19
(projections are pictures, never metric inputs).
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import numpy as np
import pytest

from scripts.eval_harness import firbench_clusters as fcl
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness.firbench_frames import GtFace

NAMED = fc.IdentityStatus.named
UNKNOWN = fc.IdentityStatus.unknown
UNRESOLVED = fc.IdentityStatus.unresolved
S = 0.80
TAU_LABEL = "acceptance tau (not a cluster cut)"
CUT_CAPTION = "Cut at cosine distance 1 minus the production similarity threshold"
UNCUT_CAPTION = "no production cut recorded"
LEG_KEY = "sface__native__ab12cd__cv4.10.0__ort1.18.0"
OTHER_KEY = "auraface__native__cd34ef__cv4.10.0__ort1.18.0"


def _lf(number: int, identity: str | None, status: fc.IdentityStatus = NAMED, *, fold: int = 0, verified: bool = True):
    gt = GtFace(
        face_id=f"face-{number:04}",
        image_id=f"image-{number:04}",
        box=(0.0, 0.0, 10.0, 10.0),
        identity_status=status,
        identity_id=identity,
    )
    return fcl.LegFace.from_gt_face(gt, fold=fold, verification_ref=f"qc-{number:04}" if verified else None)


def _cfg(**overrides: object) -> fcl.ClusterRunConfig:
    base: dict[str, object] = {
        "similarity_threshold": S,
        "linkage": "average",
        "knn_k": 1,
        "histogram_bins": 4,
        "n_orders": 3,
        "order_seed": 7,
        "projection_seed": 11,
        "umap_n_neighbors": 2,
        "umap_min_dist": 0.1,
        "acceptance_tau": 0.41,
        "production_parameters": (("min_cluster_size", 2),),
    }
    base.update(overrides)
    return fcl.ClusterRunConfig(**base)  # type: ignore[arg-type]


def _two_pairs() -> np.ndarray:
    """Two tight pairs: within-pair cosine about 0.99, across-pair cosine about 0.2."""
    return np.array([[1.0, 0.1], [1.0, -0.1], [0.1, 1.0], [-0.1, 1.0]])


def _blobs() -> np.ndarray:
    """Three separated identity blobs of three faces each, in eight dimensions."""
    rows = []
    for group in range(3):
        for member in range(3):
            vector = np.zeros(8)
            vector[group] = 1.0
            vector[3 + member] = 0.05
            rows.append(vector)
    return np.vstack(rows)


def _leg(vectors: np.ndarray, faces: tuple, *, run_id: str = "run-0001", key: str = LEG_KEY, kind=fc.LegKind.sface):
    return fcl.LegInput(leg_key=key, leg_kind=kind, run_id=run_id, faces=faces, vectors=vectors, chaining=None)


def _two_pair_leg(**kwargs: object) -> fcl.LegInput:
    faces = (_lf(1, "id-A"), _lf(2, "id-A"), _lf(3, "id-B"), _lf(4, "id-B"))
    return _leg(_two_pairs(), faces, **kwargs)  # type: ignore[arg-type]


# --- partition metrics against GT identities ------------------------------------------------


def test_known_partition_matches_hand_counted_pairwise_and_bcubed() -> None:
    faces = (
        _lf(1, "id-A"),
        _lf(2, "id-A"),
        _lf(3, "id-A"),
        _lf(4, "id-B"),
        _lf(5, "id-B"),
        _lf(6, "id-C"),
        _lf(7, "id-C"),
    )
    # Planted merge: A and B share cluster 0. Planted split: C spans clusters 1 and 2.
    data = fcl.partition_metrics(faces, np.array([0, 0, 0, 0, 0, 1, 2])).data
    assert data["named_faces"] == 7
    assert data["true_pairs"] == 5
    assert data["coassigned_predicted_pairs"] == 10
    assert data["coassigned_true_pairs"] == 4
    assert data["merges"] == 1
    assert data["fragmentation"] == 1
    assert data["pairwise_precision"].data == pytest.approx(0.4)
    assert data["pairwise_recall"].data == pytest.approx(0.8)
    assert data["bcubed_precision"].data == pytest.approx(4.6 / 7)
    assert data["bcubed_recall"].data == pytest.approx(6 / 7)


def test_relabelling_clusters_leaves_every_partition_value_unchanged() -> None:
    faces = (
        _lf(1, "id-A"),
        _lf(2, "id-A"),
        _lf(3, "id-A"),
        _lf(4, "id-B"),
        _lf(5, "id-B"),
        _lf(6, "id-C"),
        _lf(7, "id-C"),
    )
    original = fcl.partition_metrics(faces, np.array([0, 0, 0, 0, 0, 1, 2]))
    relabelled = fcl.partition_metrics(faces, np.array([7, 7, 7, 7, 7, 3, 9]))
    assert relabelled == original


def test_noise_face_is_a_missed_pair_and_a_bcubed_singleton() -> None:
    faces = (_lf(1, "id-A"), _lf(2, "id-A"))
    data = fcl.partition_metrics(faces, np.array([0, -1])).data
    assert data["noise_faces"] == 1
    assert data["noise_fraction"].data == pytest.approx(0.5)
    assert data["pairwise_precision"].status == "unavailable"
    assert data["pairwise_recall"].data == pytest.approx(0.0)
    assert data["bcubed_precision"].data == pytest.approx(1.0)
    assert data["bcubed_recall"].data == pytest.approx(0.5)


def test_unknown_face_placed_with_a_named_face_adds_no_true_pair() -> None:
    faces = (_lf(1, "id-A"), _lf(2, "id-A"), _lf(3, None, UNKNOWN))
    data = fcl.partition_metrics(faces, np.array([0, 0, 0])).data
    assert data["unknown_absorbed"] == 1
    assert data["unknown_faces"] == 1
    assert data["true_pairs"] == 1
    assert data["coassigned_true_pairs"] == 1
    assert data["pairwise_precision"].data == pytest.approx(1.0)
    assert data["pairwise_recall"].data == pytest.approx(1.0)


def test_unresolved_face_is_excluded_from_every_scored_value() -> None:
    faces = (_lf(1, "id-A"), _lf(2, "id-A"), _lf(3, None, UNRESOLVED))
    data = fcl.partition_metrics(faces, np.array([0, 0, 0])).data
    assert data["unresolved_faces"] == 1
    assert data["unknown_absorbed"] == 0
    assert data["named_faces"] == 2


# --- clustering and order stability ------------------------------------------------------


def test_reference_threshold_cluster_labels_singletons_as_noise() -> None:
    vectors = np.array([[1.0, 0.0], [0.99, 0.01], [0.0, 1.0]])
    labels = fcl.reference_threshold_cluster(vectors, similarity_threshold=S)
    assert labels.tolist() == [0, 0, -1]


def test_order_stability_is_one_for_order_free_clusterer_on_separated_blobs() -> None:
    evidence = fcl.order_stability(
        lambda values: fcl.reference_threshold_cluster(values, similarity_threshold=S),
        _blobs(),
        n_orders=3,
        seed=7,
    )
    assert evidence.status == "available"
    assert evidence.data["fraction"].data == pytest.approx(1.0)
    assert evidence.data["stable_pairs"] == evidence.data["compared_pairs"] > 0


@pytest.mark.parametrize("bad", [float("nan"), 1.5, -1.5])
def test_reference_threshold_refuses_non_similarity_thresholds(bad: float) -> None:
    with pytest.raises(fc.FrameContractError):
        fcl.reference_threshold_cluster(_two_pairs(), similarity_threshold=bad)


def test_zero_norm_vector_is_refused_for_cosine_clustering() -> None:
    with pytest.raises(fc.FrameContractError):
        fcl.reference_threshold_cluster(np.array([[1.0, 0.0], [0.0, 0.0]]), similarity_threshold=S)


# --- dendrogram, cut and acceptance tau ---------------------------------------------------


def test_dendrogram_cut_is_one_minus_s_and_tau_is_a_separate_reference() -> None:
    entry = fcl.build_leg_diagnostics(_two_pair_leg(), config=_cfg())
    cut = entry["dendrogram_cut"]
    assert cut["distance"] == pytest.approx(0.2)
    assert cut["caption"] == CUT_CAPTION
    labels = {row["face_id"]: row["label"] for row in cut["labels"]}
    assert labels["face-0001"] == labels["face-0002"] != labels["face-0003"] == labels["face-0004"]
    tau = entry["acceptance_tau_reference"]
    assert tau["status"] == "available"
    assert tau["data"]["distance"] == pytest.approx(0.59)
    assert tau["data"]["label"] == TAU_LABEL


def test_no_recorded_production_threshold_leaves_cut_labels_null() -> None:
    entry = fcl.build_leg_diagnostics(_two_pair_leg(), config=_cfg(similarity_threshold=None))
    assert entry["dendrogram_cut"] == {"distance": None, "caption": UNCUT_CAPTION, "labels": None}
    assert entry["config"]["cluster_selection_epsilon"] is None
    assert entry["labels"]["status"] == "unavailable"
    assert entry["dendrogram"]["status"] == "available"


@pytest.mark.parametrize("method", ["ward", "median", "centroid", "single"])
def test_non_average_complete_linkage_on_cosine_raises(method: str) -> None:
    with pytest.raises(fc.LinkageMetricError):
        fcl.cosine_dendrogram(_two_pairs(), method=method, similarity_threshold=S)
    with pytest.raises(fc.LinkageMetricError):
        _cfg(linkage=method)


def test_pca_spectrum_keeps_full_rank_and_reports_participation_ratio() -> None:
    vectors = np.array([[1.0, 0.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, -2.0, 0.0]])
    data = fcl.pca_spectrum(vectors).data
    assert data["retained_components"] == 2
    assert data["explained_variance_ratio"] == pytest.approx([0.8, 0.2])
    assert data["effective_dimension"] == pytest.approx(100 / 68)


# --- chaining, mutual kNN and neighbours --------------------------------------------------


def test_chaining_counts_a_path_through_a_third_identity() -> None:
    # A1 and B1 are 60 degrees apart (cosine 0.5 < s); C1 sits at 30 degrees from both.
    vectors = np.array([[1.0, 0.0], [0.5, np.sqrt(3) / 2], [np.sqrt(3) / 2, 0.5]])
    faces = (_lf(1, "id-A"), _lf(2, "id-B"), _lf(3, "id-C", fold=0))
    chaining = fcl.ChainingInput(
        frame_id="frame-0001", fold=0, pair_selection_rule="synthetic", candidate_pairs=(("face-0001", "face-0002"),)
    )
    evidence = fcl.chaining_check(vectors, faces, similarity_threshold=S, chaining=chaining)
    assert evidence.status == "available"
    assert evidence.data["eligible_pairs"] == 1
    assert evidence.data["path_linked_pairs"] == 1
    assert evidence.data["third_identity_linked_pairs"] == 1
    assert evidence.data["D"].data == pytest.approx(1.0)
    assert evidence.data["C"].data == pytest.approx(1.0)


def test_unknown_intermediate_links_d_but_cannot_establish_c() -> None:
    vectors = np.array([[1.0, 0.0], [0.5, np.sqrt(3) / 2], [np.sqrt(3) / 2, 0.5]])
    faces = (_lf(1, "id-A"), _lf(2, "id-B"), _lf(3, None, UNKNOWN, verified=False))
    chaining = fcl.ChainingInput(
        frame_id="frame-0001", fold=0, pair_selection_rule="synthetic", candidate_pairs=(("face-0001", "face-0002"),)
    )
    data = fcl.chaining_check(vectors, faces, similarity_threshold=S, chaining=chaining).data
    assert data["path_linked_pairs"] == 1
    assert data["third_identity_linked_pairs"] == 0
    assert data["D"].data == pytest.approx(1.0)
    assert data["C"].data == pytest.approx(0.0)


def test_unverified_endpoint_is_excluded_and_undefined_rates_stay_unavailable() -> None:
    vectors = np.array([[1.0, 0.0], [0.5, np.sqrt(3) / 2]])
    faces = (_lf(1, "id-A"), _lf(2, "id-B", verified=False))
    chaining = fcl.ChainingInput(
        frame_id="frame-0001", fold=0, pair_selection_rule="synthetic", candidate_pairs=(("face-0001", "face-0002"),)
    )
    evidence = fcl.chaining_check(vectors, faces, similarity_threshold=S, chaining=chaining)
    assert evidence.data["eligible_pairs"] == 0
    assert evidence.data["exclusions"] == [{"reason": "unverified_endpoint", "count": 1}]
    assert evidence.data["D"].status == "unavailable"
    assert evidence.data["pairs"] == []


def test_mutual_knn_keeps_only_reciprocal_neighbours() -> None:
    vectors = np.array([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]])
    assert [(i, j) for i, j, _ in fcl.mutual_knn_graph(vectors, 1)] == [(0, 1)]
    assert len(fcl.knn_neighbours(vectors, 1)) == 3


@pytest.mark.parametrize("k", [0, 3])
def test_knn_k_must_lie_between_one_and_n_minus_one(k: int) -> None:
    with pytest.raises(fc.FrameContractError):
        fcl.mutual_knn_graph(_two_pairs()[:3], k)


# --- histograms and companions ------------------------------------------------------------


def test_histograms_count_intra_inter_and_norm_pairs() -> None:
    entry = fcl.build_leg_diagnostics(_two_pair_leg(), config=_cfg())
    kinds = [item["kind"] for item in entry["histograms"]]
    assert kinds == ["intra_identity_cosine", "inter_identity_cosine", "vector_norm"]
    counts = {item["kind"]: sum(b["count"] for b in item["result"]["data"]["bins"]) for item in entry["histograms"]}
    assert counts == {"intra_identity_cosine": 2, "inter_identity_cosine": 4, "vector_norm": 4}


def test_histogram_without_intra_pairs_is_unavailable_not_zero() -> None:
    faces = (_lf(1, "id-A"), _lf(2, "id-B"), _lf(3, "id-C"), _lf(4, "id-D"))
    entry = fcl.build_leg_diagnostics(_leg(_two_pairs(), faces), config=_cfg())
    intra = entry["histograms"][0]
    assert intra["result"]["status"] == "unavailable"


def test_cka_of_a_space_with_itself_is_one_and_cross_dimension_refuses() -> None:
    vectors = _blobs()
    assert fcl.linear_cka(vectors, vectors) == pytest.approx(1.0)
    with pytest.raises(fc.CrossSpaceComparisonError):
        fcl.linear_cka(vectors, np.hstack([vectors, vectors[:, :1]]))


def test_companions_compare_only_matched_faces_of_one_leg_key() -> None:
    current = _two_pair_leg(run_id="run-0002")
    prior = _two_pair_leg(run_id="run-0001")
    companions = fcl.build_leg_diagnostics(current, config=_cfg(), prior=prior)["companions"]
    assert companions["knn_jaccard"]["data"]["value"] == pytest.approx(1.0)
    assert companions["linear_cka"]["data"]["value"] == pytest.approx(1.0)
    assert companions["linear_cka"]["data"]["dimension"] == 2


def test_companion_refuses_a_prior_run_of_another_leg_kind() -> None:
    current = _two_pair_leg()
    prior = _leg(_two_pairs(), current.faces, key=OTHER_KEY, kind=fc.LegKind.auraface)
    with pytest.raises(fc.CrossSpaceComparisonError):
        fcl.build_leg_diagnostics(current, config=_cfg(), prior=prior)


# --- projections -------------------------------------------------------------------------


def test_umap_missing_is_reported_unavailable_and_pca_fallback_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    def _missing() -> object:
        raise ImportError("No module named 'umap'")

    monkeypatch.setattr(fcl, "_import_umap", _missing)
    coords = fcl.projection_coords(_two_pairs(), n_neighbors=2, min_dist=0.1, seed=7)
    assert coords.status == "unavailable"
    assert "umap-learn" in coords.reason
    assert coords.coordinates is None
    assert coords.diagnostic_only is True
    entry = fcl.build_leg_diagnostics(_two_pair_leg(), config=_cfg())
    assert [p["method"] for p in entry["projections"]] == ["umap", "pca"]
    assert entry["projections"][0]["result"]["status"] == "unavailable"
    assert entry["projections"][1]["result"]["status"] == "available"


def test_available_umap_records_parameters_and_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeUmap:
        def __init__(self, *, n_neighbors: int, min_dist: float, n_components: int, random_state: int) -> None:
            self.params = (n_neighbors, min_dist, n_components, random_state)

        def fit_transform(self, values: np.ndarray) -> np.ndarray:
            return values[:, :2]

    monkeypatch.setattr(fcl, "_import_umap", lambda: types.SimpleNamespace(UMAP=_FakeUmap, __version__="0.0-synthetic"))
    coords = fcl.projection_coords(_two_pairs(), n_neighbors=2, min_dist=0.1, seed=7)
    assert coords.status == "available"
    assert coords.coordinates.shape == (4, 2)
    assert coords.parameters == {"n_neighbors": 2, "min_dist": 0.1}
    assert coords.versions == (("umap-learn", "0.0-synthetic"),)


def test_umap_fit_failure_is_raised_not_hidden_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenUmap:
        def __init__(self, **_: object) -> None:
            pass

        def fit_transform(self, _: np.ndarray) -> np.ndarray:
            raise RuntimeError("synthetic fit failure")

    monkeypatch.setattr(
        fcl, "_import_umap", lambda: types.SimpleNamespace(UMAP=_BrokenUmap, __version__="0.0-synthetic")
    )
    with pytest.raises(fc.FrameContractError):
        fcl.projection_coords(_two_pairs(), n_neighbors=2, min_dist=0.1, seed=7)


@pytest.mark.parametrize(
    "metric",
    [
        lambda p: fcl.reference_threshold_cluster(p, similarity_threshold=S),
        lambda p: fcl.pca_spectrum(p),
        lambda p: fcl.mutual_knn_graph(p, 1),
        lambda p: fcl.order_stability(
            lambda v: fcl.reference_threshold_cluster(v, similarity_threshold=S), p, n_orders=2, seed=1
        ),
        lambda p: fcl.linear_cka(p, p),
    ],
)
def test_projection_coordinates_cannot_reach_a_metric(metric) -> None:
    with pytest.raises(fc.ProjectionLeakError):
        metric(fcl.pca_projection(_two_pairs()))


def test_metrics_are_byte_identical_when_projection_parameters_change(monkeypatch: pytest.MonkeyPatch) -> None:
    def _missing() -> object:
        raise ImportError("No module named 'umap'")

    monkeypatch.setattr(fcl, "_import_umap", _missing)
    first = fcl.build_leg_diagnostics(_two_pair_leg(), config=_cfg(umap_n_neighbors=2, umap_min_dist=0.1))
    second = fcl.build_leg_diagnostics(_two_pair_leg(), config=_cfg(umap_n_neighbors=3, umap_min_dist=0.5))
    metric_sections = (
        "partition_metrics",
        "labels",
        "order_stability",
        "chaining",
        "mutual_knn",
        "neighbours",
        "dendrogram",
        "pca_spectrum",
        "histograms",
    )
    for section in metric_sections:
        assert json.dumps(first[section], sort_keys=True) == json.dumps(second[section], sort_keys=True)
    assert first["projections"][0]["parameters"] != second["projections"][0]["parameters"]


# --- clusters.json producer and writer ----------------------------------------------------


def test_clusters_payload_is_deterministic_and_validates(tmp_path: Path) -> None:
    entry = fcl.build_leg_diagnostics(_two_pair_leg(), config=_cfg())
    payload = fcl.build_clusters_payload([entry])
    (tmp_path / "one").mkdir()
    first = fcl.write_clusters_json(payload, tmp_path / "one" / "clusters.json")
    second = fcl.write_clusters_json(payload, tmp_path / "clusters.json")
    assert first.read_bytes() == second.read_bytes()
    fc.validate_interchange("clusters-v1", json.loads(second.read_text(encoding="utf-8")))


def test_writer_refuses_a_missing_parent_directory_without_partial_output(tmp_path: Path) -> None:
    payload = fcl.build_clusters_payload([fcl.build_leg_diagnostics(_two_pair_leg(), config=_cfg())])
    target = tmp_path / "missing" / "clusters.json"
    with pytest.raises(fc.FrameContractError):
        fcl.write_clusters_json(payload, target)
    assert not target.exists()


def test_writer_refuses_an_invalid_payload_without_writing(tmp_path: Path) -> None:
    payload = fcl.build_clusters_payload([fcl.build_leg_diagnostics(_two_pair_leg(), config=_cfg())])
    payload["schema_version"] = 2
    target = tmp_path / "clusters.json"
    with pytest.raises(fc.FrameContractError):
        fcl.write_clusters_json(payload, target)
    assert not target.exists()


def test_duplicate_leg_keys_are_refused() -> None:
    entry = fcl.build_leg_diagnostics(_two_pair_leg(), config=_cfg())
    with pytest.raises(fc.FrameContractError):
        fcl.build_clusters_payload([entry, entry])


def test_end_to_end_fake_run_writes_two_legs_with_companions_and_chaining(tmp_path: Path) -> None:
    faces = (_lf(1, "id-A"), _lf(2, "id-A"), _lf(3, "id-B"), _lf(4, None, UNKNOWN, verified=False))
    chain = fcl.ChainingInput(
        frame_id="frame-0001", fold=0, pair_selection_rule="synthetic", candidate_pairs=(("face-0001", "face-0003"),)
    )
    sface_now = fcl.LegInput(
        leg_key=LEG_KEY, leg_kind=fc.LegKind.sface, run_id="run-0002", faces=faces, vectors=_blobs()[:4], chaining=chain
    )
    sface_prior = fcl.LegInput(
        leg_key=LEG_KEY, leg_kind=fc.LegKind.sface, run_id="run-0001", faces=faces, vectors=_blobs()[:4], chaining=None
    )
    aura = fcl.LegInput(
        leg_key=OTHER_KEY,
        leg_kind=fc.LegKind.auraface,
        run_id="run-0002",
        faces=faces,
        vectors=_blobs()[:4],
        chaining=None,
    )
    entries = [
        fcl.build_leg_diagnostics(sface_now, config=_cfg(), prior=sface_prior),
        fcl.build_leg_diagnostics(aura, config=_cfg()),
    ]
    written = fcl.write_clusters_json(fcl.build_clusters_payload(entries), tmp_path / "clusters.json")
    payload = json.loads(written.read_text(encoding="utf-8"))
    fc.validate_interchange("clusters-v1", payload)
    assert [leg["leg_key"] for leg in payload["legs"]] == sorted([LEG_KEY, OTHER_KEY])
    sface = next(leg for leg in payload["legs"] if leg["leg_key"] == LEG_KEY)
    assert sface["partition_metrics"]["data"]["unknown_absorbed"] == 0
    assert sface["chaining"]["status"] == "available"
    assert sface["companions"]["linear_cka"]["status"] == "available"


def test_leg_inputs_must_align_faces_with_vector_rows() -> None:
    with pytest.raises(fc.FrameContractError):
        fcl.build_leg_diagnostics(_leg(_two_pairs()[:3], _two_pair_leg().faces), config=_cfg())
