"""Persisted-run cluster materializer on synthetic, pseudonymous runs only.

Every run directory is built by the real producers: frames by ``build_frame``/``frame_json``,
caches by ``pack_cache_observations`` and ``LegCache.store`` in the frozen ``firbench-cache/v1``
layout, and scores from the interchange fixture. Only the corrupt caches bypass the strict writer,
as raw NPZ, so that the reader's own boundary is what refuses them. Every run lives under a temporary
repository's ``benchmarks/private/``, the only output root the materializer may write. No pixels,
templates, model loaders or private files are read.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import numpy as np
import pytest

from scripts.eval_harness import firbench_cluster_io as fci
from scripts.eval_harness import firbench_clusters as fcl
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_frames as ff
from scripts.eval_harness.firbench_legs import CachedObservation, LegCache, pack_cache_observations

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "firbench_interchange_v1"
DECISION_SHA = "d" * 64
SOURCE_SHA = "5" * 64
FOLDS_SEED = 2406466110
GALLERY_SEED = 2468935812
BOOTSTRAP_SEED = 2429382368
THRESHOLD = 0.8
TAU = 0.41
SFACE = "sface__native__ab12cd34__cv4.10.0__ort1.18.0"
AURA = "auraface__native__cd34ef56__cv4.10.0__ort1.18.0"
REPLAY = "sface__cached_yunet_landmark_replay__ab12cd34__cv4.10.0__ort1.18.0"
IMAGES = ("image-0001", "image-0002", "image-0003", "image-0004")
# Two identities, each seen in two images: two identity-disjoint PSUs, two GT faces each.
FACES = (
    ("face-0001", "image-0001", "id-0001"),
    ("face-0002", "image-0002", "id-0001"),
    ("face-0003", "image-0003", "id-0002"),
    ("face-0004", "image-0004", "id-0002"),
)
ALL_FACES = tuple(face_id for face_id, _, _ in FACES)
# Same-identity pairs are cosine ~0.98; the two identities are orthogonal.
GT_VECTORS = np.array(
    [[1.0, 0.0, 0.0], [0.98, 0.2, 0.0], [0.0, 1.0, 0.0], [0.0, 0.97, 0.2]],
    dtype=np.float32,
)
DUPLICATE_VECTOR = np.array([0.99, 0.0, 0.14], dtype=np.float32)
BACKGROUND_VECTOR = np.array([0.0, 0.0, 1.0], dtype=np.float32)
BOX = (10.0, 10.0, 40.0, 40.0)
LANDMARKS = ((10.0, 12.0), (30.0, 12.0), (20.0, 20.0), (13.0, 30.0), (27.0, 30.0))
COVERAGE_LABEL = "diagnostics conditional on available GT vectors"


def _sha(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()


def _frame(unknown: tuple[str, ...] = ()) -> ff.Frame:
    images = [ff.ImageUnit(image_id, _sha(image_id), fc.SamplingArm.probability, 1.0) for image_id in IMAGES]
    faces = [
        ff.GtFace(
            face_id,
            image_id,
            (10.0, 10.0, 40.0, 40.0),
            fc.IdentityStatus.unknown if face_id in unknown else fc.IdentityStatus.named,
            None if face_id in unknown else identity,
            annotation=ff.FaceAnnotation(occluders=()),
        )
        for face_id, image_id, identity in FACES
    ]
    spec = fc.FrameSpec("frame-cluster-io", fc.Admissibility.development, False, SOURCE_SHA, True)
    return ff.build_frame(
        spec=spec,
        images=images,
        faces=faces,
        planning_icc=0.1,
        k=2,
        seed=FOLDS_SEED,
        test_fold=FOLDS_SEED % 2,
        gallery_sha256_by_fold={0: "b" * 64, 1: "c" * 64},
        enrolled_identity_ids=frozenset({"id-0001"}),
    )


def _private_run(tmp_path: Path, name: str = "run") -> Path:
    """A run directory under a temporary repository's benchmarks/private/, the only legal output root."""
    return tmp_path / "benchmarks" / "private" / "firbench" / name


def _embedded(
    key: str, record_id: str, image_id: str, *, gt: str | None, vector: np.ndarray, score: float
) -> CachedObservation:
    """An embedded, available row. Replay keeps landmarks but carries no detector box or score."""
    replay = key == REPLAY
    return CachedObservation(
        leg_key=key,
        record_id=record_id,
        image_id=image_id,
        image_sha256=_sha(image_id),
        gt_face_id=gt,
        stage="embedded",
        arm_availability="available",
        bbox_px=None if replay else BOX,
        landmarks_px=LANDMARKS,
        detector_score=None if replay else score,
        embedding=tuple(float(value) for value in vector),
    )


def _observations(
    frame: ff.Frame, key: str = SFACE, *, missed: tuple[str, ...] = (), detections: bool = True
) -> list[CachedObservation]:
    """One leg's producer rows: a row per GT face, then the native detections when asked for.

    A GT row's record_id is its gt_face_id. A missed GT face keeps its row with null geometry and no
    embedding. Detections are the unmatched rows that carry no GT identity.
    """
    rows: list[CachedObservation] = []
    for face, vector in zip(frame.faces, GT_VECTORS, strict=True):
        if face.face_id in missed:
            rows.append(
                CachedObservation(
                    leg_key=key,
                    record_id=face.face_id,
                    image_id=face.image_id,
                    image_sha256=_sha(face.image_id),
                    gt_face_id=face.face_id,
                    stage="missed",
                    arm_availability="available",
                    bbox_px=None,
                    landmarks_px=None,
                    detector_score=None,
                    embedding=None,
                )
            )
        else:
            rows.append(_embedded(key, face.face_id, face.image_id, gt=face.face_id, vector=vector, score=0.99))
    if detections:
        rows.append(_embedded(key, "det-dup-0001", "image-0001", gt=None, vector=DUPLICATE_VECTOR, score=0.7))
        rows.append(_embedded(key, "det-bg-0003", "image-0003", gt=None, vector=BACKGROUND_VECTOR, score=0.3))
    return rows


def _packed(frame: ff.Frame, key: str = SFACE, *, missed: tuple[str, ...] = (), detections: bool = True):
    return pack_cache_observations(_observations(frame, key, missed=missed, detections=detections), leg_key=key)


def _decoded(
    frame: ff.Frame, key: str = SFACE, *, missed: tuple[str, ...] = (), detections: bool = True
) -> tuple[dict, np.ndarray]:
    """The producer's metadata and vectors, decoded so a corrupt-fixture builder can edit one field."""
    arrays = _packed(frame, key, missed=missed, detections=detections)
    return json.loads(str(arrays["metadata_json"].item())), arrays["vectors"]


def _rows(metadata: dict, record_id: str) -> dict:
    return next(row for row in metadata["rows"] if row["record_id"] == record_id)


def _store(root: Path, key: str, arrays: Mapping[str, np.ndarray]) -> None:
    """The strict producer writer. Valid fixtures only."""
    LegCache(root / "legs" / key / "cache.npz", leg_key=key).store(arrays)


def _store_raw(root: Path, key: str, metadata: object, vectors: np.ndarray) -> None:
    """Corrupt consumer fixtures: raw NPZ, so that the reader's boundary is what refuses them."""
    text = metadata if isinstance(metadata, str) else json.dumps(metadata, sort_keys=True)
    path = root / "legs" / key / "cache.npz"
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, metadata_json=np.asarray(text), vectors=np.asarray(vectors))


def _scores(frame: ff.Frame, *, tau: float | None, legs: tuple[str, ...]) -> dict:
    payload = json.loads((FIXTURES / "scores-v1.json").read_text(encoding="utf-8"))
    template = payload["legs"][0]
    payload.update(decision_sha256=DECISION_SHA, frame_id=frame.spec.frame_id, admissibility="development")
    payload["legs"] = []
    for key in legs:
        leg = copy.deepcopy(template)
        leg["leg_key"] = key
        if tau is None:
            leg["tau"] = {"status": "unavailable", "reason": "tau_infeasible", "data": None}
        else:
            leg["tau"]["data"]["value"] = tau
        payload["legs"].append(leg)
    return payload


def _manifest(frame: ff.Frame, *, run_id: str, threshold: float | None, leg_keys: tuple[str, ...]) -> dict:
    return {
        "schema_version": 1,
        "firbench": {
            "run_id": run_id,
            "decision_sha256": DECISION_SHA,
            "frame": {
                "frame_id": frame.spec.frame_id,
                "admissibility": frame.spec.admissibility.value,
                "sealed": frame.spec.sealed,
                "source_sha256": frame.spec.source_sha256,
                "exhaustive": frame.spec.exhaustive,
            },
            "leg_keys": sorted(leg_keys),
            "similarity_threshold": threshold,
            "seeds": {"folds": FOLDS_SEED, "gallery_split": GALLERY_SEED, "bootstrap": BOOTSTRAP_SEED},
        },
    }


def _write_run(
    root: Path,
    *,
    frame: ff.Frame | None = None,
    threshold: float | None = THRESHOLD,
    tau: float | None = TAU,
    run_id: str = "run-0001",
    observations: Mapping[str, Sequence[CachedObservation]] | None = None,
    raw_caches: Mapping[str, tuple[object, np.ndarray]] | None = None,
    leg_keys: tuple[str, ...] = (SFACE, AURA),
) -> Path:
    frame = _frame() if frame is None else frame
    if observations is None and raw_caches is None:
        observations = {SFACE: _observations(frame, SFACE)}
    root.mkdir(parents=True)
    (root / "frame.json").write_text(ff.frame_json(frame) + "\n", encoding="utf-8")
    manifest = _manifest(frame, run_id=run_id, threshold=threshold, leg_keys=leg_keys)
    (root / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")
    for key, rows in (observations or {}).items():
        _store(root, key, pack_cache_observations(rows, leg_key=key))
    for key, (metadata, vectors) in (raw_caches or {}).items():
        _store_raw(root, key, metadata, vectors)
    # scores-v1 needs one native leg; it covers exactly the declared legs that were searched.
    cached = (*(observations or {}), *(raw_caches or {}))
    scored = tuple(key for key in cached if key in leg_keys)
    scores = _scores(frame, tau=tau, legs=scored or (SFACE,))
    (root / "scores.json").write_text(json.dumps(scores, sort_keys=True, indent=2), encoding="utf-8")
    return root


def _materialized(root: Path, **kwargs) -> dict:
    path = fci.materialize_clusters(root, **kwargs)
    payload = json.loads(path.read_text(encoding="utf-8"))
    fc.validate_interchange("clusters-v1", payload)
    return payload


def _entry(payload: dict, key: str) -> dict:
    return next(leg for leg in payload["legs"] if leg["leg_key"] == key)


def _expected_coverage(**counts: int | None) -> dict:
    """The frozen vector_coverage of one leg. A None count is unknown, never a fabricated zero."""
    return {"label": COVERAGE_LABEL, "conditional": True, **counts}


# --- declared choices and the materialized wire ---------------------------------------------


def test_default_diagnostic_choices_are_declared_before_outcomes():
    assert fci.DiagnosticConfig() == fci.DiagnosticConfig(
        linkage="average",
        knn_k=15,
        histogram_bins=20,
        n_orders=20,
        umap_n_neighbors=15,
        umap_min_dist=0.1,
        order_seed=None,
        projection_seed=None,
        production_parameters=(),
    )


def test_materialized_leg_is_schema_valid_and_partitions_only_gt_faces(tmp_path):
    entry = _entry(_materialized(_write_run(_private_run(tmp_path))), SFACE)
    partition = entry["partition_metrics"]
    assert partition["status"] == "available"
    assert partition["data"]["named_faces"] == 4
    assert partition["data"]["pairwise_recall"] == {"status": "available", "reason": None, "data": 1.0}
    # The duplicate and background detections are cached but never GT partition members.
    assert sorted(label["face_id"] for label in entry["labels"]["data"]) == sorted(ALL_FACES)


def test_every_leg_declares_its_vector_coverage_over_the_frame_inventory(tmp_path):
    entry = _entry(_materialized(_write_run(_private_run(tmp_path))), SFACE)
    assert entry["vector_coverage"] == _expected_coverage(
        n_gt_faces=4,
        n_named_gt_faces=4,
        n_embedded_gt_faces=4,
        n_missing_gt_faces=0,
        n_embedded_named_faces=4,
        n_detector_only_rows=2,
    )


def test_partial_gt_embedding_keeps_available_diagnostics_on_the_embedded_faces(tmp_path):
    frame = _frame()
    root = _write_run(
        _private_run(tmp_path),
        frame=frame,
        observations={SFACE: _observations(frame, SFACE, missed=("face-0004",))},
    )
    entry = _entry(_materialized(root), SFACE)
    partition = entry["partition_metrics"]
    assert partition["status"] == "available"
    assert partition["data"]["named_faces"] == 3
    # The missed GT face keeps its row, but a miss never shrinks the usable vectors of the other faces.
    assert sorted(label["face_id"] for label in entry["labels"]["data"]) == sorted(ALL_FACES[:3])
    assert entry["vector_coverage"] == _expected_coverage(
        n_gt_faces=4,
        n_named_gt_faces=4,
        n_embedded_gt_faces=3,
        n_missing_gt_faces=1,
        n_embedded_named_faces=3,
        n_detector_only_rows=2,
    )


def test_absent_leg_is_named_unavailable_with_unknown_coverage_counts(tmp_path):
    payload = _materialized(_write_run(_private_run(tmp_path)))
    entry = _entry(payload, AURA)
    assert entry["partition_metrics"]["status"] == "unavailable"
    assert "cache" in entry["partition_metrics"]["reason"]
    assert entry["projections"][0]["result"]["status"] == "unavailable"
    assert entry["chaining"]["status"] == "not_evaluated"
    assert entry["vector_coverage"] == _expected_coverage(
        n_gt_faces=4,
        n_named_gt_faces=4,
        n_embedded_gt_faces=None,
        n_missing_gt_faces=None,
        n_embedded_named_faces=None,
        n_detector_only_rows=None,
    )


def test_leg_with_no_embedded_gt_face_is_unavailable_even_with_detections(tmp_path):
    frame = _frame()
    root = _write_run(
        _private_run(tmp_path),
        frame=frame,
        observations={SFACE: _observations(frame, SFACE, missed=ALL_FACES)},
    )
    entry = _entry(_materialized(root), SFACE)
    assert entry["partition_metrics"]["status"] == "unavailable"
    assert "no embedded GT face" in entry["partition_metrics"]["reason"]
    assert entry["vector_coverage"] == _expected_coverage(
        n_gt_faces=4,
        n_named_gt_faces=4,
        n_embedded_gt_faces=0,
        n_missing_gt_faces=4,
        n_embedded_named_faces=0,
        n_detector_only_rows=2,
    )


def test_a_cache_with_no_embeddings_is_stored_zero_by_zero_and_named_unavailable(tmp_path):
    frame = _frame()
    root = _write_run(
        _private_run(tmp_path),
        frame=frame,
        observations={SFACE: _observations(frame, SFACE, missed=ALL_FACES, detections=False)},
    )
    assert LegCache(root / "legs" / SFACE / "cache.npz", leg_key=SFACE).load()["vectors"].shape == (0, 0)
    entry = _entry(_materialized(root), SFACE)
    assert entry["partition_metrics"]["status"] == "unavailable"
    assert "no embedded GT face" in entry["partition_metrics"]["reason"]
    assert entry["vector_coverage"]["n_detector_only_rows"] == 0


def test_writes_one_clusters_file_with_sorted_legs(tmp_path):
    root = _write_run(_private_run(tmp_path))
    path = fci.materialize_clusters(root)
    assert path == root / "clusters.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert [leg["leg_key"] for leg in payload["legs"]] == [AURA, SFACE]


def test_production_threshold_and_acceptance_tau_are_distinct_reference_lines(tmp_path):
    entry = _entry(_materialized(_write_run(_private_run(tmp_path))), SFACE)
    assert entry["config"]["similarity_threshold"] == THRESHOLD
    assert entry["dendrogram_cut"]["distance"] == pytest.approx(1.0 - THRESHOLD)
    assert entry["dendrogram_cut"]["caption"] == fcl.CUT_CAPTION
    reference = entry["acceptance_tau_reference"]
    assert reference["data"]["tau"] == TAU
    assert reference["data"]["distance"] == pytest.approx(1.0 - TAU)
    assert reference["data"]["label"] == fcl.TAU_LABEL
    assert entry["dendrogram_cut"]["distance"] != pytest.approx(1.0 - TAU)


def test_missing_production_threshold_stays_null_and_uncut(tmp_path):
    entry = _entry(_materialized(_write_run(_private_run(tmp_path), threshold=None)), SFACE)
    assert entry["config"]["similarity_threshold"] is None
    assert entry["dendrogram_cut"] == {"distance": None, "caption": fcl.UNCUT_CAPTION, "labels": None}
    assert entry["partition_metrics"]["status"] == "unavailable"


def test_unrecorded_tau_is_an_explicit_unavailable_reference(tmp_path):
    reference = _entry(_materialized(_write_run(_private_run(tmp_path), tau=None)), SFACE)["acceptance_tau_reference"]
    assert reference["status"] == "unavailable"
    assert reference["reason"]


@pytest.mark.parametrize("tau", [1.0 + 2**-52, 1.25])
def test_tau_beyond_one_is_an_exact_reference_without_changing_production_diagnostics(tmp_path, tau):
    root = _write_run(_private_run(tmp_path), tau=tau)
    scores = (root / "scores.json").read_bytes()
    entry = _entry(_materialized(root), SFACE)
    assert entry["acceptance_tau_reference"] == {
        "status": "available",
        "reason": None,
        "data": {"tau": tau, "distance": 1.0 - tau, "label": "acceptance tau (not a cluster cut)"},
    }
    assert entry["acceptance_tau_reference"]["data"]["distance"] < 0.0
    assert (root / "scores.json").read_bytes() == scores
    assert entry["config"]["similarity_threshold"] == THRESHOLD
    assert entry["dendrogram_cut"]["distance"] == 1.0 - THRESHOLD
    control = _entry(_materialized(_write_run(_private_run(tmp_path, "control"), tau=None)), SFACE)
    assert {key: value for key, value in entry.items() if key != "acceptance_tau_reference"} == {
        key: value for key, value in control.items() if key != "acceptance_tau_reference"
    }


def test_chaining_is_not_fabricated_without_held_out_verification(tmp_path):
    entry = _entry(_materialized(_write_run(_private_run(tmp_path))), SFACE)
    assert entry["chaining"] == {
        "status": "not_evaluated",
        "reason": "no held-out verified pair evidence supplied",
        "data": None,
    }


def test_materialization_is_byte_deterministic(tmp_path):
    first = fci.materialize_clusters(_write_run(_private_run(tmp_path, "a")))
    second = fci.materialize_clusters(_write_run(_private_run(tmp_path, "b")))
    assert first.read_bytes() == second.read_bytes()


def test_existing_clusters_file_is_never_rewritten(tmp_path):
    root = _write_run(_private_run(tmp_path))
    (root / "clusters.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(fc.FrameContractError, match="already exists"):
        fci.materialize_clusters(root)
    assert (root / "clusters.json").read_text(encoding="utf-8") == "{}\n"


def test_declared_projection_seed_and_knn_are_applied(tmp_path):
    entry = _entry(_materialized(_write_run(_private_run(tmp_path))), SFACE)
    assert [projection["seed"] for projection in entry["projections"]] == [GALLERY_SEED, GALLERY_SEED]
    assert entry["projections"][0]["parameters"] == {"n_neighbors": 15, "min_dist": 0.1}
    assert all(projection["diagnostic_only"] is True for projection in entry["projections"])
    # Four faces cannot supply knn_k=15 neighbours: the declared k is applied and reported unavailable.
    assert entry["neighbours"]["status"] == "unavailable"


def test_config_must_be_a_diagnostic_config(tmp_path):
    with pytest.raises(fc.FrameContractError, match="DiagnosticConfig"):
        fci.materialize_clusters(_write_run(_private_run(tmp_path)), config={"knn_k": 3})


# --- output guard: only a run under benchmarks/private/ may receive clusters.json -----------


def test_run_outside_benchmarks_private_is_refused(tmp_path):
    root = _write_run(tmp_path / "public-run")
    with pytest.raises(fc.NonPrivateOutputError):
        fci.materialize_clusters(root)
    assert not (root / "clusters.json").exists()


def test_traversal_out_of_benchmarks_private_is_refused(tmp_path):
    public = _write_run(tmp_path / "public-run")
    (tmp_path / "benchmarks" / "private" / "firbench").mkdir(parents=True)
    traversal = tmp_path / "benchmarks" / "private" / "firbench" / ".." / ".." / ".." / "public-run"
    with pytest.raises(fc.NonPrivateOutputError):
        fci.materialize_clusters(traversal)
    assert not (public / "clusters.json").exists()


def test_symlinked_run_escaping_benchmarks_private_is_refused(tmp_path):
    public = _write_run(tmp_path / "public-run")
    link = _private_run(tmp_path, "linked-run")
    link.parent.mkdir(parents=True)
    link.symlink_to(public, target_is_directory=True)
    with pytest.raises(fc.NonPrivateOutputError):
        fci.materialize_clusters(link)
    assert not (public / "clusters.json").exists()


def test_redirected_benchmarks_private_directory_is_refused(tmp_path):
    elsewhere_run = _write_run(tmp_path / "elsewhere" / "private" / "firbench" / "run")
    (tmp_path / "benchmarks").mkdir()
    (tmp_path / "benchmarks" / "private").symlink_to(tmp_path / "elsewhere" / "private", target_is_directory=True)
    with pytest.raises(fc.NonPrivateOutputError):
        fci.materialize_clusters(_private_run(tmp_path))
    assert not (elsewhere_run / "clusters.json").exists()


def test_benchmarks_private_root_is_not_a_run_output_path(tmp_path):
    root = _write_run(tmp_path / "benchmarks" / "private")
    with pytest.raises(fc.NonPrivateOutputError):
        fci.materialize_clusters(root)
    assert not (root / "clusters.json").exists()


# --- idempotent replay: a valid identical artifact returns, anything else refuses ------------


def test_identical_rematerialization_returns_the_existing_file_unchanged(tmp_path):
    root = _write_run(_private_run(tmp_path))
    first = fci.materialize_clusters(root)
    written = first.read_bytes()
    assert fci.materialize_clusters(root) == first
    assert first.read_bytes() == written


@pytest.mark.parametrize("change", ["cache", "config", "prior"])
def test_changed_inputs_never_reuse_the_existing_clusters_file(tmp_path, change):
    frame = _frame()
    root = _write_run(_private_run(tmp_path), frame=frame)
    path = fci.materialize_clusters(root)
    written = path.read_bytes()
    kwargs: dict[str, object] = {}
    if change == "cache":
        _store(root, SFACE, _packed(frame, SFACE, missed=("face-0004",)))
    elif change == "config":
        kwargs["config"] = fci.DiagnosticConfig(knn_k=3)
    else:
        kwargs["prior_run_dir"] = _write_run(_private_run(tmp_path, "prior"), frame=frame)
    with pytest.raises(fc.FrameContractError, match="clusters.json"):
        fci.materialize_clusters(root, **kwargs)
    assert path.read_bytes() == written


def test_invalid_inputs_are_refused_even_when_an_identical_clusters_file_exists(tmp_path):
    frame = _frame()
    root = _write_run(_private_run(tmp_path), frame=frame)
    path = fci.materialize_clusters(root)
    written = path.read_bytes()
    metadata, vectors = _decoded(frame, SFACE)
    _store_raw(root, SFACE, metadata, _with_row(vectors, 0, [0.0, 0.0, 0.0]))
    with pytest.raises(fc.FrameContractError):
        fci.materialize_clusters(root)
    assert path.read_bytes() == written


# --- LegInput binding: GT rows, frame identities and folds ----------------------------------


def test_leg_input_takes_identity_status_and_fold_from_the_frame(tmp_path):
    run = fci._load_run(_write_run(_private_run(tmp_path)))
    read = fci._read_leg(run, SFACE)
    assert read.reason is None
    frame = _frame()
    assert [face.face_id for face in read.leg.faces] == list(ALL_FACES)
    for index, (face, gt) in enumerate(zip(read.leg.faces, frame.faces, strict=True)):
        assert face.identity_id == gt.identity_id
        assert face.identity_status is fc.IdentityStatus.named
        assert face.fold == frame.folds[frame.psu_map[gt.image_id]]
        assert face.verification_ref is None
        assert np.allclose(read.leg.vectors[index], GT_VECTORS[index])
    assert read.leg.vectors.shape == (4, 3)


def test_unknown_identity_gt_face_keeps_its_frame_status_and_leaves_named_metrics(tmp_path):
    frame = _frame(unknown=("face-0004",))
    root = _write_run(_private_run(tmp_path), frame=frame)
    read = fci._read_leg(fci._load_run(root), SFACE)
    unknown_face = next(face for face in read.leg.faces if face.face_id == "face-0004")
    assert unknown_face.identity_status is fc.IdentityStatus.unknown
    assert unknown_face.identity_id is None
    entry = _entry(_materialized(root), SFACE)
    assert entry["partition_metrics"]["status"] == "available"
    assert entry["partition_metrics"]["data"]["named_faces"] == 3
    assert entry["partition_metrics"]["data"]["unknown_faces"] == 1
    assert entry["vector_coverage"]["n_named_gt_faces"] == 3
    assert entry["vector_coverage"]["n_embedded_named_faces"] == 3


def test_replay_arm_leg_keeps_geometry_but_no_box_or_score(tmp_path):
    frame = _frame()
    root = _write_run(
        _private_run(tmp_path),
        frame=frame,
        observations={REPLAY: _observations(frame, REPLAY, detections=False)},
        leg_keys=(REPLAY,),
    )
    entry = _entry(_materialized(root), REPLAY)
    assert entry["partition_metrics"]["status"] == "available"
    assert entry["vector_coverage"]["n_embedded_gt_faces"] == 4


def test_replay_arm_row_carrying_a_box_is_refused(tmp_path):
    frame = _frame()
    metadata, vectors = _decoded(frame, REPLAY, detections=False)
    _rows(metadata, "face-0001")["bbox_px"] = list(BOX)
    root = _write_run(_private_run(tmp_path), frame=frame, raw_caches={REPLAY: (metadata, vectors)}, leg_keys=(REPLAY,))
    with pytest.raises(fc.FrameContractError, match="replay"):
        fci.materialize_clusters(root)


# --- prior run companions -------------------------------------------------------------------


def test_prior_run_of_the_same_leg_feeds_the_companion_scope(tmp_path):
    current = _write_run(_private_run(tmp_path, "current"), run_id="run-0002")
    prior = _write_run(_private_run(tmp_path, "prior"), run_id="run-0001")
    companions = _entry(_materialized(current, prior_run_dir=prior), SFACE)["companions"]
    assert companions["linear_cka"]["status"] == "available"
    assert companions["linear_cka"]["data"]["reference_run_id"] == "run-0001"
    assert companions["linear_cka"]["data"]["comparison_run_id"] == "run-0002"


def test_prior_run_without_the_leg_key_is_not_evaluated(tmp_path):
    current = _write_run(_private_run(tmp_path, "current"))
    prior = _write_run(
        _private_run(tmp_path, "prior"),
        observations={AURA: _observations(_frame(), AURA)},
        leg_keys=(AURA,),
    )
    companions = _entry(_materialized(current, prior_run_dir=prior), SFACE)["companions"]
    assert companions["linear_cka"]["status"] == "not_evaluated"


def test_unusable_prior_leg_is_named_unavailable_not_silently_dropped(tmp_path):
    frame = _frame()
    current = _write_run(_private_run(tmp_path, "current"), frame=frame, run_id="run-0002")
    prior = _write_run(
        _private_run(tmp_path, "prior"),
        frame=frame,
        observations={SFACE: _observations(frame, SFACE, missed=ALL_FACES, detections=False)},
    )
    companions = _entry(_materialized(current, prior_run_dir=prior), SFACE)["companions"]
    assert companions["linear_cka"]["status"] == "unavailable"
    assert "prior" in companions["linear_cka"]["reason"]


def test_corrupt_prior_leg_refuses_the_whole_materialization(tmp_path):
    frame = _frame()
    current = _write_run(_private_run(tmp_path, "current"), frame=frame, run_id="run-0002")
    metadata, vectors = _decoded(frame, SFACE)
    prior = _write_run(
        _private_run(tmp_path, "prior"),
        frame=frame,
        raw_caches={SFACE: (metadata, _with_row(vectors, 0, [0.0, 0.0, 0.0]))},
    )
    with pytest.raises(fc.FrameContractError):
        fci.materialize_clusters(current, prior_run_dir=prior)
    assert not (current / "clusters.json").exists()


def test_prior_run_cannot_be_the_current_run(tmp_path):
    root = _write_run(_private_run(tmp_path))
    with pytest.raises(fc.FrameContractError, match="prior"):
        fci.materialize_clusters(root, prior_run_dir=root)


# --- refused cache rows and arrays ----------------------------------------------------------

Build = Callable[[ff.Frame], tuple[object, np.ndarray]]


def _case(mutate: Callable[[dict], None], *, resort: bool = True) -> Build:
    def build(frame: ff.Frame):
        metadata, vectors = _decoded(frame, SFACE)
        mutate(metadata)
        if resort:
            metadata["rows"] = sorted(metadata["rows"], key=lambda row: (row["image_id"], row["record_id"]))
        return metadata, vectors

    return build


def _text(render: Callable[[dict], str]) -> Build:
    def build(frame: ff.Frame):
        metadata, vectors = _decoded(frame, SFACE)
        return render(metadata), vectors

    return build


def _vectors(change: Callable[[np.ndarray], np.ndarray]) -> Build:
    def build(frame: ff.Frame):
        metadata, vectors = _decoded(frame, SFACE)
        return metadata, change(vectors)

    return build


def _set(record_id: str, **changes: object) -> Callable[[dict], None]:
    def mutate(metadata: dict) -> None:
        _rows(metadata, record_id).update(changes)

    return mutate


def _reverse(metadata: dict) -> None:
    metadata["rows"].reverse()


def _duplicate_record(metadata: dict) -> None:
    metadata["rows"][1]["record_id"] = metadata["rows"][0]["record_id"]


def _duplicate_gt(metadata: dict) -> None:
    _rows(metadata, "det-dup-0001")["gt_face_id"] = "face-0001"


def _missing_gt_row(metadata: dict) -> None:
    metadata["rows"] = [row for row in metadata["rows"] if row["gt_face_id"] != "face-0003"]


def _unknown_gt_face(metadata: dict) -> None:
    # Keep record_id equal to gt_face_id, so the reader's frame check is the boundary that refuses it.
    _rows(metadata, "face-0001").update(record_id="face-9999", gt_face_id="face-9999")


def _image_one_sha(metadata: dict) -> None:
    # Every row of the image changes together, so only the frame binding can refuse it.
    for row in metadata["rows"]:
        if row["image_id"] == "image-0001":
            row["image_sha256"] = "0" * 64


def _missed_with_box(frame: ff.Frame):
    metadata, vectors = _decoded(frame, SFACE, missed=("face-0004",))
    _rows(metadata, "face-0004")["bbox_px"] = list(BOX)
    return metadata, vectors


def _with_row(vectors: np.ndarray, index: int, row: list[float]) -> np.ndarray:
    changed = vectors.copy()
    changed[index] = row
    return changed


CACHE_REFUSALS = [
    ("json_syntax", _text(lambda m: "{not json")),
    ("nonfinite_constant", _text(lambda m: json.dumps(m).replace("0.99", "NaN", 1))),
    ("duplicate_json_key", _text(lambda m: '{"format": "firbench-cache/v0", ' + json.dumps(m)[1:])),
    (
        "nonfinite_box",
        _text(lambda m: json.dumps(m).replace("[10.0, 10.0, 40.0, 40.0]", "[10.0, 10.0, Infinity, 40.0]", 1)),
    ),
    ("wrong_format", _case(lambda m: m.update(format="firbench-cache/v0"))),
    ("leg_key_mismatch", _case(lambda m: m.update(leg_key=AURA))),
    ("extra_top_level_key", _case(lambda m: m.update(timing_ms=12.5))),
    ("extra_row_key", _case(lambda m: m["rows"][0].update(timing_ms=12.5))),
    ("duplicate_record_id", _case(_duplicate_record)),
    ("unsorted_rows", _case(_reverse, resort=False)),
    ("unknown_image", _case(_set("face-0001", image_id="image-9999"))),
    ("image_sha_mismatch", _case(_image_one_sha)),
    ("unknown_gt_face", _case(_unknown_gt_face)),
    (
        "gt_face_on_other_image",
        _case(_set("face-0001", image_id="image-0002", image_sha256=_sha("image-0002"))),
    ),
    ("duplicate_gt_row", _case(_duplicate_gt)),
    ("missing_gt_row", _case(_missing_gt_row)),
    ("index_out_of_range", _case(_set("det-bg-0003", embedding_index=99))),
    ("duplicate_embedding_index", _case(_set("det-bg-0003", embedding_index=0))),
    ("unreferenced_vector_row", _vectors(lambda v: np.vstack([v, BACKGROUND_VECTOR]).astype(np.float32))),
    ("embedding_with_missed_stage", _case(_set("face-0001", stage="missed"))),
    ("embedded_stage_without_embedding", _case(_set("face-0001", embedding_index=None))),
    ("embedding_on_unavailable_arm", _case(_set("face-0001", arm_availability="unavailable"))),
    ("boolean_detector_score", _case(_set("face-0001", detector_score=True))),
    ("negative_box_size", _case(_set("face-0001", bbox_px=[10.0, 10.0, -40.0, 40.0]))),
    ("malformed_landmarks", _case(_set("face-0001", landmarks_px=[[1.0, 2.0]]))),
    ("missed_row_with_geometry", _missed_with_box),
]


@pytest.mark.parametrize("build", [build for _, build in CACHE_REFUSALS], ids=[name for name, _ in CACHE_REFUSALS])
def test_malformed_cache_is_refused_not_scored(tmp_path, build):
    frame = _frame()
    metadata, vectors = build(frame)
    root = _write_run(_private_run(tmp_path), frame=frame, raw_caches={SFACE: (metadata, vectors)})
    with pytest.raises(fc.FrameContractError):
        fci.materialize_clusters(root)
    assert not (root / "clusters.json").exists()


@pytest.mark.parametrize(
    "change",
    [
        lambda v: v.astype(np.float64),
        lambda v: _with_row(v, 0, [np.nan, 0.0, 0.0]),
        lambda v: _with_row(v, 0, [0.0, 0.0, 0.0]),
        lambda v: v.reshape(-1),
    ],
    ids=["float64", "nonfinite", "zero_norm", "one_dimensional"],
)
def test_vector_array_dtype_shape_and_finiteness_are_refused(tmp_path, change):
    frame = _frame()
    metadata, vectors = _decoded(frame, SFACE)
    root = _write_run(_private_run(tmp_path), frame=frame, raw_caches={SFACE: (metadata, change(vectors))})
    with pytest.raises(fc.FrameContractError):
        fci.materialize_clusters(root)


def test_pickled_object_array_is_refused_by_the_reader(tmp_path):
    frame = _frame()
    metadata, _ = _decoded(frame, SFACE)
    root = _write_run(
        _private_run(tmp_path),
        frame=frame,
        raw_caches={SFACE: (metadata, np.asarray([object()], dtype=object))},
    )
    with pytest.raises(fc.FrameContractError):
        fci.materialize_clusters(root)


def test_no_embeddings_must_be_stored_as_an_empty_zero_by_zero_array(tmp_path):
    frame = _frame()
    metadata, _ = _decoded(frame, SFACE, missed=ALL_FACES, detections=False)
    root = _write_run(
        _private_run(tmp_path),
        frame=frame,
        raw_caches={SFACE: (metadata, np.zeros((0, 3), np.float32))},
    )
    with pytest.raises(fc.FrameContractError):
        fci.materialize_clusters(root)


def test_cache_under_a_symlinked_leg_directory_is_refused(tmp_path):
    root = _write_run(_private_run(tmp_path))
    (root / "legs" / AURA).symlink_to(root / "legs" / SFACE, target_is_directory=True)
    with pytest.raises(fc.FrameContractError, match="symlink"):
        fci.materialize_clusters(root)


@pytest.mark.parametrize("bad_key", ["../escape", "sface__native__ab12cd34", "a/b__native__x__cv1__ort1"])
def test_unsafe_or_malformed_leg_keys_are_refused(tmp_path, bad_key):
    frame = _frame()
    root = _private_run(tmp_path)
    root.mkdir(parents=True)
    (root / "frame.json").write_text(ff.frame_json(frame) + "\n", encoding="utf-8")
    manifest = _manifest(frame, run_id="run-0001", threshold=THRESHOLD, leg_keys=(bad_key,))
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "scores.json").write_text(json.dumps(_scores(frame, tau=TAU, legs=())), encoding="utf-8")
    with pytest.raises(fc.FrameContractError):
        fci.materialize_clusters(root)


# --- run-level binding ----------------------------------------------------------------------


def test_scores_from_another_decision_are_refused(tmp_path):
    root = _write_run(_private_run(tmp_path))
    payload = json.loads((root / "scores.json").read_text(encoding="utf-8"))
    payload["decision_sha256"] = "e" * 64
    (root / "scores.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(fc.FrameContractError, match="decision"):
        fci.materialize_clusters(root)


def test_manifest_frame_binding_must_match_frame_json(tmp_path):
    root = _write_run(_private_run(tmp_path))
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["firbench"]["frame"]["source_sha256"] = "6" * 64
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(fc.FrameContractError, match="frame"):
        fci.materialize_clusters(root)


def test_frame_json_must_validate_against_its_schema(tmp_path):
    root = _write_run(_private_run(tmp_path))
    payload = json.loads((root / "frame.json").read_text(encoding="utf-8"))
    del payload["faces"]
    (root / "frame.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(fc.FrameContractError, match="frame-v1"):
        fci.materialize_clusters(root)


def test_scores_are_required_for_the_acceptance_reference(tmp_path):
    root = _write_run(_private_run(tmp_path))
    (root / "scores.json").unlink()
    with pytest.raises(fc.FrameContractError, match="scores.json"):
        fci.materialize_clusters(root)


def test_a_missing_frame_is_refused(tmp_path):
    root = _write_run(_private_run(tmp_path))
    (root / "frame.json").unlink()
    with pytest.raises(fc.FrameContractError, match="frame.json"):
        fci.materialize_clusters(root)
