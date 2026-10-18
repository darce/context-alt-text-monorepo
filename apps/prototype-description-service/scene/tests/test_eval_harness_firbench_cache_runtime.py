"""Frozen S2 cache: actual search/driver, synthetic IO and model kernels only."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from scene.tests.test_eval_harness_firbench_cli_integration import run, runtime_files  # noqa: F401
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_legs as fl

SHA = "a" * 64


class Kernel:
    kind = fc.LegKind.sface
    alignment_mode = fc.AlignmentMode.separable

    def __init__(self):
        self.calls = self.embeds = 0
        self.vector = np.array([3.0, 4.0], dtype=np.float32)

    def leg_id(self, arm):
        return fc.LegId(self.kind, arm, "b" * 64, "fake-cv", "fake-ort")

    def observe(self, image):
        self.calls += 1
        if image.shape[0] == 3:
            return ()
        # One exact match, one duplicate, one background, one alignment failure.
        return tuple(
            fl.Observation(fl.DetectedFace(box, np.arange(10).reshape(5, 2), 0.9), vector, stage)
            for box, vector, stage in [
                ((0, 0, 10, 10), self.vector, fc.SearchStage.embedded),
                ((0, 0, 9, 9), np.array([7.0, 8.0]), fc.SearchStage.embedded),
                ((30, 30, 4, 4), np.array([9.0, 10.0]), fc.SearchStage.embedded),
                ((20, 20, 4, 4), None, fc.SearchStage.unaligned),
            ]
        )

    def align(self, image, landmarks):
        return image

    def embed(self, aligned):
        self.embeds += 1
        return self.vector


def faces():
    return [
        SimpleNamespace(
            face_id=name,
            image_id="image",
            box=box,
            identity_id="id-1",
            identity_status=fc.IdentityStatus.named,
            cohort=None,
        )
        for name, box in [("match", (0, 0, 10, 10)), ("miss", (40, 40, 3, 3)), ("unaligned", (20, 20, 4, 4))]
    ]


def search(kernel, arm=fc.Arm.native, **kwargs):
    return fl.search_leg_arm(
        leg=kernel,
        arm=arm,
        images={"image": np.zeros((64, 64, 3), dtype=np.uint8)},
        image_units={
            "image": SimpleNamespace(sha256=SHA, sampling_arm=fc.SamplingArm.probability, inclusion_probability=1.0)
        },
        faces=faces(),
        gallery=fl.Gallery.enrol({"id-1": [np.array([1.0, 0.0])]}),
        psu_by_image={"image": "psu"},
        fold_by_psu={"psu": 0},
        fold_roles={0: fc.FoldRole.test},
        exhaustive=True,
        top_k=1,
        crop_margin=0.0,
        **kwargs,
    )


def unpack(arrays):
    # Independent reader: the persisted representation needs no producer object or pickle.
    assert set(arrays) == {"metadata_json", "vectors"}
    assert arrays["metadata_json"].shape == () and arrays["metadata_json"].dtype.kind == "U"
    metadata = json.loads(arrays["metadata_json"].item())
    assert set(metadata) == {"format", "leg_key", "rows"}
    assert metadata["format"] == "firbench-cache/v1"
    vectors = arrays["vectors"]
    assert vectors.dtype == np.float32 and vectors.ndim == 2 and np.isfinite(vectors).all()
    rows = metadata["rows"]
    assert rows == sorted(rows, key=lambda r: (r["image_id"], r["record_id"]))
    assert len({r["record_id"] for r in rows}) == len(rows)
    assert sorted(r["embedding_index"] for r in rows if r["embedding_index"] is not None) == list(range(len(vectors)))
    for row in rows:
        assert set(row) == {
            "record_id",
            "image_id",
            "image_sha256",
            "gt_face_id",
            "stage",
            "arm_availability",
            "bbox_px",
            "landmarks_px",
            "detector_score",
            "embedding_index",
        }
    return metadata, {r["record_id"]: r for r in rows}


def packed(result, key):
    return fl.pack_cache_observations(result.cached_observations, leg_key=key)


def test_native_captures_shared_assignment_vectors_duplicates_background_and_nulls():
    kernel = Kernel()
    result = search(kernel)
    key = kernel.leg_id(fc.Arm.native).key()
    arrays = packed(result, key)
    metadata, rows = unpack(arrays)
    assert metadata["leg_key"] == key
    assert kernel.calls == 1 and kernel.embeds == 0
    assert (
        set(rows) == {r.face_id for r in result.records} == {"match", "miss", "unaligned", "det:image:1", "det:image:2"}
    )
    assert {r.face_id for r in result.ledger} == {"match", "miss", "unaligned"}
    assert rows["match"]["gt_face_id"] == "match"
    assert rows["det:image:1"]["gt_face_id"] is None and rows["det:image:2"]["gt_face_id"] is None
    assert rows["miss"]["bbox_px"] is rows["miss"]["embedding_index"] is None
    assert rows["unaligned"]["embedding_index"] is None and rows["unaligned"]["bbox_px"] == [20, 20, 4, 4]
    np.testing.assert_array_equal(arrays["vectors"][rows["match"]["embedding_index"]], [3, 4])
    assert all(r["image_sha256"] == SHA for r in rows.values())
    # Frozen capture survives later model buffer reuse; pack is deterministic, independent of order.
    kernel.vector[:] = 99
    reverse = fl.pack_cache_observations(tuple(reversed(result.cached_observations)), leg_key=key)
    for name in arrays:
        np.testing.assert_array_equal(arrays[name], reverse[name])
    assert fl.ArmResult((), (), {}).cached_observations == ()


@pytest.mark.parametrize("arm", [fc.Arm.gt_crop_redetect, fc.Arm.cached_yunet_landmark_replay])
def test_attribution_uses_single_actual_execution_and_available_geometry(arm):
    kernel = Kernel()
    result = search(kernel, arm, cached_landmarks={"match": np.ones((5, 2))})
    arrays = packed(result, kernel.leg_id(arm).key())
    _, rows = unpack(arrays)
    assert set(rows) == {"match", "miss", "unaligned"}
    if arm is fc.Arm.gt_crop_redetect:
        assert kernel.calls == 3 and kernel.embeds == 0
        assert rows["match"]["bbox_px"] == [0, 0, 10, 10]
        assert rows["miss"]["stage"] == "missed" and rows["miss"]["embedding_index"] is None
    else:
        assert kernel.calls == 0 and kernel.embeds == 1
        assert rows["match"]["bbox_px"] is rows["match"]["detector_score"] is None
        assert rows["match"]["landmarks_px"] == [[1, 1]] * 5
        assert rows["miss"]["arm_availability"] == "unavailable"
    np.testing.assert_array_equal(arrays["vectors"][rows["match"]["embedding_index"]], [3, 4])


@pytest.mark.parametrize("arm", [fc.Arm.gt_crop_redetect, fc.Arm.cached_yunet_landmark_replay])
def test_fused_unavailable_emits_every_gt_without_models_or_fake_vectors(arm):
    kernel = Kernel()
    kernel.alignment_mode = fc.AlignmentMode.fused_internal
    arrays = packed(search(kernel, arm), kernel.leg_id(arm).key())
    _, rows = unpack(arrays)
    assert kernel.calls == kernel.embeds == 0
    assert arrays["vectors"].shape == (0, 0)
    assert all(r["stage"] is r["embedding_index"] is r["bbox_px"] is r["landmarks_px"] is None for r in rows.values())
    assert all(r["arm_availability"] == "unavailable_fused" for r in rows.values())


def test_leg_cache_roundtrip_frame_bindings_and_wrong_leg(tmp_path):
    kernel = Kernel()
    key = kernel.leg_id(fc.Arm.native).key()
    arrays = packed(search(kernel), key)
    cache = fl.LegCache(tmp_path / "cache.npz", leg_key=key)
    assert cache.load() is None
    cache.store(arrays)
    with np.load(cache.path, allow_pickle=False) as data:
        unpack(data)
    for name in arrays:
        np.testing.assert_array_equal(cache.load()[name], arrays[name])
    fl.validate_cache_observations(
        arrays, leg_key=key, image_sha256_by_id={"image": SHA}, gt_image_by_id={f.face_id: "image" for f in faces()}
    )
    with pytest.raises(fc.FrameContractError, match="sha|binding"):
        fl.validate_cache_observations(arrays, leg_key=key, image_sha256_by_id={"image": "c" * 64})
    with pytest.raises(fc.FrameContractError, match="GT|face"):
        fl.validate_cache_observations(arrays, leg_key=key, gt_image_by_id={"absent": "image"})
    with pytest.raises(fc.FrameContractError, match="leg"):
        fl.pack_cache_observations(search(kernel).cached_observations, leg_key="foreign")
    with pytest.raises(fc.FrameContractError, match="leg"):
        fl.LegCache(cache.path, leg_key="foreign").store(arrays)


def test_cache_reader_checks_raw_archive_and_atomic_replacement(tmp_path, monkeypatch):
    kernel = Kernel()
    key = kernel.leg_id(fc.Arm.native).key()
    arrays = packed(search(kernel), key)
    cache = fl.LegCache(tmp_path / "cache.npz", leg_key=key)
    cache.store(arrays)
    original = cache.path.read_bytes()

    def fail_replace(*args):
        raise OSError("replace failed")

    with monkeypatch.context() as patch:
        patch.setattr(fl.os, "replace", fail_replace)
        with pytest.raises(OSError, match="replace failed"):
            cache.store(arrays)
    assert cache.path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [cache.path]
    # Bypass the writer: the reader must validate arbitrary persisted input itself.
    metadata = json.loads(arrays["metadata_json"].item())
    metadata["rows"][0]["embedding_index"] = 999
    arrays["metadata_json"] = np.asarray(json.dumps(metadata))
    np.savez(cache.path, **arrays)
    with pytest.raises(fc.FrameContractError):
        cache.load()


def test_frame_reader_names_absence_and_no_embedded_gt_without_imputing_risk(tmp_path):
    kernel = Kernel()
    key = kernel.leg_id(fc.Arm.native).key()
    cache = fl.LegCache(tmp_path / "cache.npz", leg_key=key)
    bindings = {"image_sha256_by_id": {"image": SHA}, "gt_image_by_id": {f.face_id: "image" for f in faces()}}
    assert cache.read_frame(**bindings) == {"status": "unavailable", "reason": "cache_absent", "data": None}
    result = search(kernel)
    cache.store(packed(result, key))
    assert cache.read_frame(**bindings)["status"] == "available"
    with pytest.raises(fc.FrameContractError):
        cache.read_frame(**{**bindings, "image_sha256_by_id": {"image": "c" * 64}})
    # Background/duplicate vectors remain actual observations, but cannot supply GT risk.
    observe = kernel.observe

    def no_gt_embeddings(image):
        return tuple(
            replace(o, embedding=None, stage=fc.SearchStage.detected)
            if o.detection.bbox_px in {(0, 0, 10, 10), (20, 20, 4, 4)}
            else o
            for o in observe(image)
        )

    kernel.observe = no_gt_embeddings
    cache.store(packed(search(kernel), key))
    assert len(cache.load()["vectors"]) == 2
    assert cache.read_frame(**bindings) == {"status": "unavailable", "reason": "no_embedded_gt", "data": None}


@pytest.mark.parametrize("field,value", [("stage", []), ("arm_availability", {}), ("record_id", [])])
def test_malformed_metadata_types_are_contract_errors(field, value):
    kernel = Kernel()
    key = kernel.leg_id(fc.Arm.native).key()
    arrays = packed(search(kernel), key)
    metadata = json.loads(arrays["metadata_json"].item())
    metadata["rows"][0][field] = value
    arrays["metadata_json"] = np.asarray(json.dumps(metadata))
    with pytest.raises(fc.FrameContractError):
        fl.validate_cache_observations(arrays, leg_key=key)


@pytest.mark.parametrize(
    "defect",
    [
        "object",
        "nan",
        "dim",
        "duplicate",
        "index",
        "unreferenced",
        "json",
        "sha",
        "sha_suffix",
        "geometry",
        "extra",
        "stage",
        "status",
        "null_vector",
        "gt_duplicate",
    ],
)
def test_malformed_cache_rejected_before_replacement(tmp_path, defect):
    kernel = Kernel()
    key = kernel.leg_id(fc.Arm.native).key()
    arrays = packed(search(kernel), key)
    cache = fl.LegCache(tmp_path / "cache.npz", leg_key=key)
    cache.store(arrays)
    original = cache.path.read_bytes()
    meta = json.loads(arrays["metadata_json"].item())
    row = next(r for r in meta["rows"] if r["record_id"] == "match")
    if defect == "object":
        arrays["vectors"] = np.array([[object()]], dtype=object)
    elif defect == "nan":
        arrays["vectors"][0, 0] = np.nan
    elif defect == "dim":
        arrays["vectors"] = arrays["vectors"].ravel()
    elif defect == "duplicate":
        meta["rows"].append(dict(row))
    elif defect == "index":
        row["embedding_index"] = True
    elif defect == "unreferenced":
        arrays["vectors"] = np.vstack([arrays["vectors"], np.array([[1, 2]], dtype=np.float32)])
    elif defect == "sha":
        row["image_sha256"] = "fake"
    elif defect == "sha_suffix":
        row["image_sha256"] = SHA + "\n"
    elif defect == "geometry":
        row["landmarks_px"] = [[1, 2]]
    elif defect == "extra":
        row["timing_ms"] = 4
    elif defect == "stage":
        row["stage"] = "made_up"
    elif defect == "status":
        row["arm_availability"] = "made_up"
    elif defect == "null_vector":
        row["stage"] = "missed"
    elif defect == "gt_duplicate":
        meta["rows"][0]["gt_face_id"] = "match"
    arrays["metadata_json"] = np.asarray("{}" if defect == "json" else json.dumps(meta))
    with pytest.raises(fc.FrameContractError):
        cache.store(arrays)
    assert cache.path.read_bytes() == original


def test_capture_refuses_nonfinite_or_mixed_vector_dimensions():
    kernel = Kernel()
    result = search(kernel)
    key = kernel.leg_id(fc.Arm.native).key()
    observation = result.cached_observations[0]
    for vector in [(float("nan"), 1.0), (1.0, 2.0, 3.0)]:
        bad = (replace(observation, embedding=vector), *result.cached_observations[1:])
        with pytest.raises(fc.FrameContractError):
            fl.pack_cache_observations(bad, leg_key=key)


def test_default_cli_actual_cache_all_folds_and_all_arms(runtime_files, monkeypatch):
    from scripts.eval_harness import face_assignment

    f = runtime_files
    counts = {"separable_observe": 0, "embed": 0, "fused_observe": 0, "assignment": 0}

    def count(method, name):
        def call(*args, **kwargs):
            counts[name] += 1
            return method(*args, **kwargs)

        return call

    monkeypatch.setattr(fl.FacePipelineLeg, "observe", count(fl.FacePipelineLeg.observe, "separable_observe"))
    monkeypatch.setattr(fl.FacePipelineLeg, "embed", count(fl.FacePipelineLeg.embed, "embed"))
    monkeypatch.setattr(fl.BuffaloLeg, "observe", count(fl.BuffaloLeg.observe, "fused_observe"))
    assignment = count(face_assignment.hungarian_iou_pairs, "assignment")
    monkeypatch.setattr(fl, "hungarian_iou_pairs", assignment)
    monkeypatch.setattr(face_assignment, "hungarian_iou_pairs", assignment)
    directory = run(f)
    manifest = json.loads((directory / "manifest.json").read_text())["firbench"]
    hashes = {r["image_id"]: r["sha256"] for r in json.loads(f.source.read_text())["images"]}
    # Two separable kernels: native + crop only; replay must never call detect again.
    assert len(f.callbacks) == 120
    # Per separable leg: 30 enrollment + 30 native + 30 crop + 30 replay embeds.
    assert counts == {"separable_observe": 180, "embed": 240, "fused_observe": 60, "assignment": 90}
    for key in manifest["leg_keys"]:
        path = directory / "legs" / key / "cache.npz"
        with np.load(path, allow_pickle=False) as data:
            metadata, rows = unpack(data)
            vectors = data["vectors"].copy()
        assert metadata["leg_key"] == key
        assert len(rows) == 30
        searches = [json.loads(line) for line in path.with_name("searches.jsonl").read_text().splitlines()]
        assert {r["fold"] for r in searches} == set(range(5))
        for record in searches:
            row = rows[record["face_id"]]
            assert row["gt_face_id"] == record["face_id"]
            assert row["image_sha256"] == hashes[row["image_id"]]
            assert row["stage"] == record["stage_reached"]
            assert row["arm_availability"] == record["arm_availability"]
            if row["embedding_index"] is not None:
                expected = np.zeros(vectors.shape[1], dtype=np.float32)
                expected[int(row["image_id"].split("-")[-1])] = 1
                np.testing.assert_array_equal(vectors[row["embedding_index"]], expected)
        if "insightface__" in key and "__native__" not in key:
            assert vectors.shape == (0, 0)
    repeated = run(f, out_dir=f.private / "repeat")
    assert len(f.callbacks) == 240
    assert counts == {"separable_observe": 360, "embed": 480, "fused_observe": 120, "assignment": 180}
    for key in manifest["leg_keys"]:
        first_leg, second_leg = directory / "legs" / key, repeated / "legs" / key
        assert (first_leg / "searches.jsonl").read_bytes() == (second_leg / "searches.jsonl").read_bytes()
        assert (directory / "ledger" / f"{key}.jsonl").read_bytes() == (
            repeated / "ledger" / f"{key}.jsonl"
        ).read_bytes()
        first = fl.LegCache(first_leg / "cache.npz", leg_key=key).load()
        second = fl.LegCache(second_leg / "cache.npz", leg_key=key).load()
        for name in first:
            np.testing.assert_array_equal(first[name], second[name])
    # Private media/source/template disappearance cannot affect frozen cache reads.
    for path in f.private.glob("*.png"):
        path.unlink()
    f.source.unlink()
    f.templates.unlink()
    f.binding_path.unlink()
    for key in manifest["leg_keys"]:
        unpack(fl.LegCache(directory / "legs" / key / "cache.npz", leg_key=key).load())


@pytest.mark.parametrize("failure", ["late_query", "bad_timing", "bad_vector"])
def test_query_failure_publishes_no_caches_or_other_outcomes(runtime_files, monkeypatch, failure):
    f = runtime_files
    if failure == "bad_timing":
        import itertools

        ticks = itertools.cycle([0.0, float("nan")])
        monkeypatch.setattr(fl, "perf_counter", lambda: next(ticks))
    else:
        original = fl.FacePipelineLeg.embed
        calls = []

        def embed(self, aligned):
            calls.append(None)
            if len(calls) > 75:
                if failure == "late_query":
                    raise fc.FrameContractError("late query failed")
                return np.full(self.embedding_dim, np.nan)
            return original(self, aligned)

        monkeypatch.setattr(fl.FacePipelineLeg, "embed", embed)
    with pytest.raises(fc.FirBenchError):
        run(f)
    assert {p.name for p in (f.private / "run").iterdir()} == {"frame.json", "manifest.json", "attempt-failure.json"}
