"""Conditional S4 diagnostics from synthetic frames and the accepted S2 cache producer.

No pixels, models, primary scoring replacements or schema patches are used.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from scripts.eval_harness import firbench_cluster_io as io
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_frames as frames
from scripts.eval_harness.firbench_legs import CachedObservation, LegCache, pack_cache_observations

KEY = "sface__native__ab12cd34__cv4.10.0__ort1.18.0"
ABSENT = "auraface__native__cd34ef56__cv4.10.0__ort1.18.0"
LABEL = "diagnostics conditional on available GT vectors"
VECTORS = ((1.0, 0.0, 0.0), (0.98, 0.2, 0.0), (0.0, 1.0, 0.0), (0.0, 0.97, 0.2))
LANDMARKS = ((10.0, 12.0), (30.0, 12.0), (20.0, 20.0), (13.0, 30.0), (27.0, 30.0))
CONFIG = io.DiagnosticConfig(knn_k=1, n_orders=3)


def _frame(*, statuses=(), empty=False):
    images = tuple(
        frames.ImageUnit(
            f"image-{i}", hashlib.sha256(f"image-{i}".encode()).hexdigest(), fc.SamplingArm.probability, 1.0
        )
        for i in range(5)
    )
    faces = tuple(
        frames.GtFace(
            f"face-{i}",
            image.image_id,
            (10.0, 10.0, 40.0, 40.0),
            statuses[i] if statuses else fc.IdentityStatus.named,
            f"id-{i // 2}" if not statuses or statuses[i] is fc.IdentityStatus.named else None,
            annotation=frames.FaceAnnotation(occluders=()),
        )
        for i, image in enumerate(images[:4])
    )
    frame = frames.build_frame(
        spec=fc.FrameSpec("coverage-fixture", fc.Admissibility.development, False, "5" * 64, True),
        images=images,
        faces=faces,
        planning_icc=0.1,
        k=2,
        seed=2406466110,
        test_fold=0,
        gallery_sha256_by_fold={0: "b" * 64, 1: "c" * 64},
        enrolled_identity_ids=frozenset({"id-0"}),
    )
    if not empty:
        return frame
    # build_frame requires a positive face-count PSU for planning deff. Exercise the
    # serializer's valid zero-GT edge with real background units and PSU/fold producers.
    components = frames.build_psu_components(images, ())
    folds = frames.identity_disjoint_folds(components, {}, k=2, seed=2406466110)
    pool = frames.build_nonmated_pool(
        (),
        images,
        folds,
        fold=0,
        component_map=components,
        exhaustive=True,
        planning_icc=0.1,
        enrolled_identity_ids=frozenset(),
    )
    return replace(
        frame,
        faces=(),
        psu_map=components,
        folds=folds,
        identity_fold={},
        design_effect=1.0,
        n_eff=0.0,
        n_units=pool.n_units,
        n_nonmated_eff=pool.n_nonmated_eff,
    )


def _observations(frame, *, missing=(), state="missed", detections=True):
    images = {image.image_id: image for image in frame.images}
    observations = []
    for i, face in enumerate(frame.faces):
        missed = face.face_id in missing
        stage = state if missed else "embedded"
        availability = "unavailable" if stage == "unavailable" else "available"
        geometry = stage not in {"missed", "unavailable"}
        observations.append(
            CachedObservation(
                leg_key=KEY,
                record_id=face.face_id,
                image_id=face.image_id,
                image_sha256=images[face.image_id].sha256,
                gt_face_id=face.face_id,
                stage=stage,
                arm_availability=availability,
                bbox_px=face.box if geometry else None,
                landmarks_px=LANDMARKS if geometry else None,
                detector_score=0.99 if geometry else None,
                embedding=None if missed else VECTORS[i],
            )
        )
    if detections:
        for i, vector in ((0, (0.99, 0.0, 0.14)), (2, (0.0, 0.0, 1.0))):
            image = frame.images[i]
            observations.append(
                CachedObservation(
                    leg_key=KEY,
                    record_id=f"det-{i}",
                    image_id=image.image_id,
                    image_sha256=image.sha256,
                    gt_face_id=None,
                    stage="embedded",
                    arm_availability="available",
                    bbox_px=(10.0, 10.0, 40.0, 40.0),
                    landmarks_px=LANDMARKS,
                    detector_score=0.7,
                    embedding=vector,
                )
            )
    return tuple(observations)


def _run(tmp_path, *, frame=None, missing=(), state="missed", cache=True, detections=True, observations=None):
    frame = _frame() if frame is None else frame
    root = tmp_path / "repo" / "benchmarks" / "private" / "runs" / "coverage"
    root.mkdir(parents=True)
    frame_payload = json.loads(frames.frame_json(frame))
    manifest = {
        "schema_version": 1,
        "firbench": {
            "run_id": "coverage-fixture",
            "decision_sha256": "d" * 64,
            "frame": {
                name: frame_payload[name]
                for name in ("frame_id", "admissibility", "sealed", "source_sha256", "exhaustive")
            },
            "leg_keys": [ABSENT, KEY],
            "similarity_threshold": 0.8,
            "seeds": {"gallery_split": 2468935812},
        },
    }
    # The frozen scores interchange fixture supplies tau; these tests never rescore primary outcomes.
    scores = json.loads((Path(__file__).parent / "fixtures/firbench_interchange_v1/scores-v1.json").read_text())
    scores.update(decision_sha256="d" * 64, frame_id=frame.spec.frame_id, admissibility="development")
    scores["legs"] = [scores["legs"][0]]
    scores["legs"][0]["leg_key"] = KEY
    fc.validate_interchange("scores-v1", scores)
    for name, payload in (("frame.json", frame_payload), ("manifest.json", manifest), ("scores.json", scores)):
        (root / name).write_text(json.dumps(payload), encoding="utf-8")
    if cache:
        observations = (
            _observations(frame, missing=missing, state=state, detections=detections)
            if observations is None
            else observations
        )
        LegCache(root / "legs" / KEY / "cache.npz", leg_key=KEY).store(
            pack_cache_observations(observations, leg_key=KEY)
        )
    return root


def _coverage(n_gt=4, n_named=4, embedded=3, missing=1, embedded_named=3, detections=2):
    return {
        "label": LABEL,
        "conditional": True,
        "n_gt_faces": n_gt,
        "n_named_gt_faces": n_named,
        "n_embedded_gt_faces": embedded,
        "n_missing_gt_faces": missing,
        "n_embedded_named_faces": embedded_named,
        "n_detector_only_rows": detections,
    }


def _materialize(root, **kwargs):
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    payload = json.loads(io.materialize_clusters(root, config=CONFIG, **kwargs).read_text())
    fc.validate_interchange("clusters-v1", payload)
    assert all(path.read_bytes() == content for path, content in before.items())
    return {leg["leg_key"]: leg for leg in payload["legs"]}


@pytest.mark.parametrize("state", ["missed", "unaligned", "unavailable"])
def test_one_missing_gt_retains_three_faces_and_defined_diagnostics(tmp_path, state):
    root = _run(tmp_path, missing=("face-3",), state=state)
    read = io._read_leg(io._load_run(root), KEY)
    assert read.leg is not None, read.reason
    assert [face.face_id for face in read.leg.faces] == ["face-0", "face-1", "face-2"]
    assert np.array_equal(read.leg.vectors, np.asarray(VECTORS[:3], dtype=np.float32))
    entry = _materialize(root)[KEY]
    assert entry["vector_coverage"] == _coverage()
    assert [row["face_id"] for row in entry["labels"]["data"]] == ["face-0", "face-1", "face-2"]
    assert entry["partition_metrics"]["data"]["named_faces"] == 3
    assert entry["partition_metrics"]["data"]["pairwise_recall"]["status"] == "available"
    pca = next(projection for projection in entry["projections"] if projection["method"] == "pca")
    assert pca["result"]["status"] == "available"
    assert len(pca["result"]["data"]) == 3
    assert entry["chaining"]["status"] == "not_evaluated"


def test_frame_statuses_and_folds_survive_subset_selection(tmp_path):
    frame = _frame(
        statuses=(
            fc.IdentityStatus.named,
            fc.IdentityStatus.named,
            fc.IdentityStatus.unknown,
            fc.IdentityStatus.unknown,
        )
    )
    root = _run(tmp_path, frame=frame, missing=("face-3",))
    run = io._load_run(root)
    read = io._read_leg(run, KEY)
    assert read.leg is not None
    for face in read.leg.faces:
        original = run.frame.faces_by_id[face.face_id]
        assert face.identity_status is original.identity_status
        assert face.identity_id == original.identity_id
        assert face.fold == run.frame.fold_by_image[original.image_id]
        assert face.verification_ref is None
    entry = _materialize(root)[KEY]
    assert entry["vector_coverage"] == _coverage(n_named=2, embedded_named=2)
    assert entry["partition_metrics"]["data"]["named_faces"] == 2
    assert entry["partition_metrics"]["data"]["unknown_faces"] == 1
    assert entry["partition_metrics"]["data"]["unresolved_faces"] == 0


@pytest.mark.parametrize("state", ["missed", "unaligned", "unavailable"])
@pytest.mark.parametrize("detections", [True, False])
def test_no_eligible_gt_remains_unavailable_even_with_detector_vectors(tmp_path, state, detections):
    root = _run(tmp_path, missing=tuple(f"face-{i}" for i in range(4)), state=state, detections=detections)
    arrays = LegCache(root / "legs" / KEY / "cache.npz", leg_key=KEY).load()
    assert arrays["vectors"].shape == ((2, 3) if detections else (0, 0))
    read = io._read_leg(io._load_run(root), KEY)
    assert read.leg is None
    assert "no embedded GT" in read.reason
    entry = _materialize(root)[KEY]
    assert entry["vector_coverage"] == _coverage(
        embedded=0,
        missing=4,
        embedded_named=0,
        detections=2 if detections else 0,
    )
    assert entry["labels"]["status"] == "unavailable"
    assert entry["partition_metrics"]["data"] is None
    assert all(projection["result"]["status"] == "unavailable" for projection in entry["projections"])


def test_absent_cache_has_frame_totals_and_explicit_unknown_cache_counts(tmp_path):
    entries = _materialize(_run(tmp_path, cache=False))
    for entry in entries.values():
        assert entry["vector_coverage"] == _coverage(
            embedded=None,
            missing=None,
            embedded_named=None,
            detections=None,
        )
        assert entry["partition_metrics"]["status"] == "unavailable"
        assert "cache" in entry["partition_metrics"]["reason"]


@pytest.mark.parametrize("cache", [True, False])
def test_no_gt_frame_distinguishes_valid_empty_cache_from_absence(tmp_path, cache):
    entry = _materialize(_run(tmp_path, frame=_frame(empty=True), cache=cache))[KEY]
    assert entry["vector_coverage"] == _coverage(
        n_gt=0,
        n_named=0,
        embedded=0 if cache else None,
        missing=0 if cache else None,
        embedded_named=0 if cache else None,
        detections=2 if cache else None,
    )
    assert entry["partition_metrics"]["status"] == "unavailable"


def test_complete_cache_reports_exact_coverage_and_excludes_detector_rows(tmp_path):
    entry = _materialize(_run(tmp_path))[KEY]
    assert entry["vector_coverage"] == _coverage(embedded=4, missing=0, embedded_named=4)
    assert len(entry["labels"]["data"]) == 4


def test_missing_gt_row_is_rejected_instead_of_shrinking_frame_inventory(tmp_path):
    observations = _observations(_frame())
    root = _run(tmp_path, observations=tuple(o for o in observations if o.gt_face_id != "face-3"))
    with pytest.raises(fc.FrameContractError, match="no row for GT face"):
        io.materialize_clusters(root, config=CONFIG)
    assert not (root / "clusters.json").exists()


@pytest.mark.parametrize("all_missing", [False, True])
def test_detector_bindings_are_validated_before_any_coverage_result(tmp_path, all_missing):
    missing = tuple(f"face-{i}" for i in range(4)) if all_missing else ("face-3",)
    observations = _observations(_frame(), missing=missing)
    observations = tuple(
        replace(o, image_id="image-4", image_sha256="f" * 64) if o.record_id == "det-2" else o for o in observations
    )
    # Packing accepts the isolated cache; the materializer must independently bind it to FRAME.
    root = _run(tmp_path, observations=observations)
    with pytest.raises(fc.FrameContractError, match="image_sha256 differs from the frame"):
        io.materialize_clusters(root, config=CONFIG)
    assert not (root / "clusters.json").exists()


def test_partial_prior_remains_usable_for_actual_shared_face_companions(tmp_path):
    current = _run(tmp_path / "current", missing=("face-3",))
    prior = _run(tmp_path / "prior", missing=("face-2",))
    entry = _materialize(current, prior_run_dir=prior)[KEY]
    assert entry["vector_coverage"] == _coverage()
    assert entry["companions"]["linear_cka"]["status"] == "available"
    assert entry["companions"]["knn_jaccard"]["status"] == "available"
