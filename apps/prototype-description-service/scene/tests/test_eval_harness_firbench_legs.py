"""FIRBENCH-1 S2: in-process legs, arms, contract-keyed cache, per-face search records.

Fakes only: no model weights, no buffalo_bench import, no private frames.
Synthetic ids (id-0001, image-0001) and numpy-generated images only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from recognition.application.embedding.manifest import EmbeddingModelManifest
from recognition.infrastructure.face_pipeline._common import EmbedBatchResult, RawDetection
from recognition.infrastructure.face_pipeline.aligner import AlignmentError
from scripts.eval_harness.firbench_contract import (
    AlignmentMode,
    Arm,
    ArmStatus,
    CrossSpaceComparisonError,
    FoldRole,
    FrameContractError,
    IdentityStatus,
    LegId,
    LegKind,
    RuntimeMismatchError,
    SamplingArm,
    SearchStage,
    validate_interchange,
)
from scripts.eval_harness.firbench_legs import (
    CanaryConfigError,
    CanaryLeg,
    DetectedFace,
    FaceSearchRecord,
    FusedLegProtocolError,
    Gallery,
    LegCache,
    Observation,
    build_face_pipeline_leg,
    compare_guard,
    derangement,
    expected_changed_search_ids,
    search_leg_arm,
    space_fingerprint,
    write_searches_jsonl,
)

OPENCV = "5.0.0"
ORT = "1.28.0"
SHA_A = "a" * 64


# --- S1 name fakes (firbench_frames is not merged; field names follow S1 Build 1) ---


@dataclass(frozen=True)
class _ImageUnit:
    image_id: str
    sha256: str
    sampling_arm: SamplingArm
    inclusion_probability: float | None
    duplicate_group: str | None = None
    session_id: str | None = None
    synthetic_parent_id: str | None = None


@dataclass(frozen=True)
class _GtFace:
    face_id: str
    image_id: str
    box: tuple[float, float, float, float]  # pixel [x, y, w, h]
    identity_status: IdentityStatus
    identity_id: str | None
    cohort: dict[str, str | None] | None = None


def _image(seed: int, *, value: int) -> np.ndarray:
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    img[:] = value
    return img


def _fake_detect(dets_by_image: dict[str, list[DetectedFace]], images: dict[str, np.ndarray]):
    """Map image sha to its scripted detections (the detector is a fake, not YuNet)."""
    by_sha = {_sha(images[k]): v for k, v in dets_by_image.items()}

    def detect(image_bgr: np.ndarray) -> tuple[DetectedFace, ...]:
        return tuple(by_sha.get(_sha(image_bgr), ()))

    return detect


def _sha(image: np.ndarray) -> str:
    import hashlib

    return hashlib.sha256(np.ascontiguousarray(image).tobytes()).hexdigest()


def _det(x: float, y: float, w: float, h: float, score: float = 0.9) -> DetectedFace:
    lm = np.array(
        [
            [x + 0.3 * w, y + 0.4 * h],
            [x + 0.7 * w, y + 0.4 * h],
            [x + 0.5 * w, y + 0.6 * h],
            [x + 0.35 * w, y + 0.8 * h],
            [x + 0.65 * w, y + 0.8 * h],
        ],
        dtype=np.float64,
    )
    return DetectedFace(bbox_px=(x, y, w, h), landmarks_px=lm, score=score)


class _FakeSeparableLeg:
    """Separable fake: detect/align/embed, deterministic 128-dim unit embeddings."""

    alignment_mode = AlignmentMode.separable

    def __init__(self, *, kind: LegKind, dim: int, dets_by_image, images):
        self.kind = kind
        self._dim = dim
        self._detect = _fake_detect(dets_by_image, images)
        self._fingerprint = space_fingerprint({"kind": kind.value, "dim": dim, "weights_sha256": SHA_A})
        self.detect_shapes: list[tuple[int, ...]] = []

    def leg_id(self, arm: Arm) -> LegId:
        return LegId(self.kind, arm, self._fingerprint, OPENCV, ORT)

    def detect(self, image_bgr: np.ndarray):
        self.detect_shapes.append(tuple(image_bgr.shape))
        return self._detect(image_bgr)

    def align(self, image_bgr: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
        return np.full((112, 112, 3), int(round(float(image_bgr.mean()))), dtype=np.uint8)

    def embed(self, aligned: np.ndarray) -> np.ndarray:
        vec = np.zeros(self._dim, dtype=np.float32)
        vec[int(aligned[0, 0, 0]) % self._dim] = 1.0
        return vec

    def observe(self, image_bgr: np.ndarray) -> tuple[Observation, ...]:
        out = []
        for det in self.detect(image_bgr):
            aligned = self.align(image_bgr, det.landmarks_px)
            vec = self.embed(aligned)
            out.append(Observation.embedded(det, vec))
        return tuple(out)


def _gallery(values: dict[str, int], dim: int = 128) -> Gallery:
    templates = {}
    for ident, value in values.items():
        vec = np.zeros(dim, dtype=np.float32)
        vec[value % dim] = 1.0
        templates[ident] = [vec]
    return Gallery.enrol(templates)


def _run(leg, arm, images, faces, *, gallery=None, cached=None, crop_margin=None, cells=None):
    units = {iid: _ImageUnit(iid, _sha(img), SamplingArm.probability, 0.5) for iid, img in images.items()}
    return search_leg_arm(
        leg=leg,
        arm=arm,
        images=images,
        image_units=units,
        faces=faces,
        gallery=gallery or _gallery({"id-0001": 10, "id-0002": 20}),
        psu_by_image={iid: f"psu-{iid}" for iid in images},
        fold_by_psu={f"psu-{iid}": 0 for iid in images},
        fold_roles={0: FoldRole.test},
        exhaustive=True,
        top_k=2,
        cells=cells,
        cached_landmarks=cached,
        crop_margin=crop_margin,
    )


# --- RED: ledger, arms and background units -----------------------------------


def test_ledger_has_one_row_per_gt_face_per_leg_and_arm_and_missed_face_is_missed():
    images = {"image-0001": _image(1, value=10)}
    dets = {"image-0001": [_det(4, 4, 20, 20)]}
    leg = _FakeSeparableLeg(kind=LegKind.sface, dim=128, dets_by_image=dets, images=images)
    faces = [
        _GtFace("face-0001", "image-0001", (4, 4, 20, 20), IdentityStatus.named, "id-0001"),
        _GtFace("face-0002", "image-0001", (40, 40, 16, 16), IdentityStatus.named, "id-0002"),
    ]
    result = _run(leg, Arm.native, images, faces)
    gt_rows = list(result.ledger)
    assert sorted((row.face_id, row.stage_reached) for row in gt_rows) == [
        ("face-0001", SearchStage.embedded),
        ("face-0002", SearchStage.missed),
    ]
    assert {row.leg_key for row in gt_rows} == {leg.leg_id(Arm.native).key()}
    assert all(row.arm == Arm.native for row in gt_rows)


def test_native_background_detection_is_searched_with_background_unit_id():
    images = {"image-0001": _image(2, value=30)}
    dets = {"image-0001": [_det(4, 4, 20, 20), _det(40, 40, 10, 10, score=0.7)]}
    leg = _FakeSeparableLeg(kind=LegKind.sface, dim=128, dets_by_image=dets, images=images)
    faces = [_GtFace("face-0001", "image-0001", (4, 4, 20, 20), IdentityStatus.named, "id-0001")]
    result = _run(leg, Arm.native, images, faces)
    background = [r for r in result.records if r.unit_id is not None and r.unit_id.startswith("background:")]
    assert len(background) == 1
    row = background[0]
    assert row.unit_id == "background:image-0001"
    assert row.face_id == "det:image-0001:1"
    assert row.identity_id is None
    assert row.cohort is None
    assert row.top_k, "background detection must be searched like any other detection"


def test_duplicate_detection_over_mated_face_has_no_unit_and_is_not_background():
    images = {"image-0001": _image(3, value=40)}
    dets = {"image-0001": [_det(4, 4, 20, 20, score=0.95), _det(5, 5, 20, 20, score=0.6)]}
    leg = _FakeSeparableLeg(kind=LegKind.sface, dim=128, dets_by_image=dets, images=images)
    faces = [_GtFace("face-0001", "image-0001", (4, 4, 20, 20), IdentityStatus.named, "id-0001")]
    result = _run(leg, Arm.native, images, faces)
    dupes = [r for r in result.records if r.face_id.startswith("det:")]
    assert len(dupes) == 1
    assert dupes[0].unit_id is None
    assert not any(r.unit_id and r.unit_id.startswith("background:") for r in result.records)
    assert all(r.face_id != "face-0001" or r.unit_id is None for r in result.records)


def test_gt_crop_redetect_runs_detector_on_a_margin_crop_and_records_its_arm():
    images = {"image-0001": _image(4, value=50)}
    dets = {"image-0001": [_det(4, 4, 20, 20)]}
    leg = _FakeSeparableLeg(kind=LegKind.sface, dim=128, dets_by_image=dets, images=images)
    faces = [_GtFace("face-0001", "image-0001", (4, 4, 20, 20), IdentityStatus.named, "id-0001")]
    result = _run(leg, Arm.gt_crop_redetect, images, faces, crop_margin=0.25)
    rows = list(result.records)
    assert [r.arm for r in rows] == [Arm.gt_crop_redetect]
    assert rows[0].arm_availability == ArmStatus.available
    assert rows[0].stage_reached in {SearchStage.missed, SearchStage.embedded}
    assert leg.detect_shapes, "the leg detector must run on the crop"
    assert all(shape != (64, 64, 3) for shape in leg.detect_shapes), "crop, not the full image"
    assert not any(r.unit_id and r.unit_id.startswith("background:") for r in rows)


def test_landmark_replay_without_cached_landmark_is_unavailable_and_never_falls_back():
    images = {"image-0001": _image(5, value=60)}
    dets = {"image-0001": [_det(4, 4, 20, 20), _det(40, 40, 16, 16)]}
    leg = _FakeSeparableLeg(kind=LegKind.sface, dim=128, dets_by_image=dets, images=images)
    faces = [
        _GtFace("face-0001", "image-0001", (4, 4, 20, 20), IdentityStatus.named, "id-0001"),
        _GtFace("face-0002", "image-0001", (40, 40, 16, 16), IdentityStatus.named, "id-0002"),
    ]
    cached = {"face-0001": np.zeros((5, 2))}
    result = _run(leg, Arm.cached_yunet_landmark_replay, images, faces, cached=cached)
    by_face = {r.face_id: r for r in result.records}
    assert by_face["face-0001"].arm_availability == ArmStatus.available
    assert by_face["face-0001"].stage_reached == SearchStage.embedded
    missing = by_face["face-0002"]
    assert missing.arm_availability == ArmStatus.unavailable
    assert missing.stage_reached == SearchStage.unavailable
    assert missing.top_k == ()
    assert not any(r.face_id.startswith("det:") for r in result.records), "replay has no background units"


def test_cache_miss_in_replay_is_unavailable_not_fallback_landmarks():
    images = {"image-0001": _image(6, value=70)}
    leg = _FakeSeparableLeg(kind=LegKind.sface, dim=128, dets_by_image={"image-0001": []}, images=images)
    faces = [_GtFace("face-0009", "image-0001", (4, 4, 20, 20), IdentityStatus.named, "id-0001")]
    result = _run(leg, Arm.cached_yunet_landmark_replay, images, faces, cached={})
    (row,) = result.records
    assert row.arm_availability == ArmStatus.unavailable
    assert row.stage_reached == SearchStage.unavailable
    assert row.top_k == ()


def test_fused_leg_writes_no_unaligned_rows_and_attribution_arms_are_unavailable_fused():
    class _FusedFake:
        kind = LegKind.insightface
        alignment_mode = AlignmentMode.fused_internal

        def __init__(self, faces_by_sha):
            self._faces = faces_by_sha

        def leg_id(self, arm: Arm) -> LegId:
            return LegId(self.kind, arm, space_fingerprint({"kind": "insightface", "dim": 512}), OPENCV, ORT)

        def observe(self, image_bgr: np.ndarray) -> tuple[Observation, ...]:
            return tuple(self._faces.get(_sha(image_bgr), ()))

    images = {"image-0001": _image(7, value=80)}
    det = _det(4, 4, 20, 20)
    fused = _FusedFake(
        {_sha(images["image-0001"]): [Observation.fused(det, np.ones(512, dtype=np.float32) / np.sqrt(512))]}
    )
    faces = [_GtFace("face-0001", "image-0001", (4, 4, 20, 20), IdentityStatus.named, "id-0001")]
    native = _run(fused, Arm.native, images, faces, gallery=_gallery({"id-0001": 3}, dim=512))
    (row,) = native.ledger
    assert row.stage_reached == SearchStage.embedded
    assert row.alignment_mode == AlignmentMode.fused_internal
    for arm in (Arm.gt_crop_redetect, Arm.cached_yunet_landmark_replay):
        rows = _run(fused, arm, images, faces, gallery=_gallery({"id-0001": 3}, dim=512)).records
        (attr,) = rows
        assert attr.arm_availability == ArmStatus.unavailable_fused
        assert attr.stage_reached is None
        assert attr.top_k == ()
    all_stages = {r.stage_reached for r in native.records}
    assert SearchStage.unaligned not in all_stages


def test_fused_leg_refuses_separable_only_calls():
    from scripts.eval_harness.firbench_legs import BuffaloLeg

    leg = BuffaloLeg(process=lambda _image: [], weights_sha256=SHA_A, opencv_version=OPENCV, ort_version=ORT)
    with pytest.raises(FusedLegProtocolError):
        leg.align(_image(1, value=1), np.zeros((5, 2)))
    with pytest.raises(FusedLegProtocolError):
        leg.embed(_image(1, value=1))


# --- RED: factory, space fingerprint, cache, compare guard ---------------------


def _fake_embedder(dim: int):
    class _Emb:
        embedding_dim = dim

        def embed(self, crops):
            # Same return type as the production embedder: EmbedBatchResult(vectors, norms).
            vectors = np.zeros((len(crops), dim), dtype=np.float32)
            return EmbedBatchResult(vectors=vectors, norms=np.ones(len(crops), dtype=np.float32))

    return _Emb()


def test_factory_builds_128_and_512_legs_in_one_process_without_global_dimension_reads():
    import scripts.eval_harness.firbench_legs as legs_module

    source = Path(legs_module.__file__).read_text(encoding="utf-8")
    assert "get_shared_face_pipeline_runtime" not in source
    assert "assert_three_way_embedding_dimensions" not in source
    assert "get_database_settings" not in source and "get_settings" not in source
    sface = build_face_pipeline_leg(
        LegKind.sface,
        manifest=_manifest(128),
        detector=object(),
        aligner=object(),
        embedder=_fake_embedder(128),
        weights_sha256=SHA_A,
        preprocessing={"input_size": [112, 112]},
        opencv_version=OPENCV,
        ort_version=ORT,
    )
    auraface = build_face_pipeline_leg(
        LegKind.auraface,
        manifest=_manifest(512),
        detector=object(),
        aligner=object(),
        embedder=_fake_embedder(512),
        weights_sha256=SHA_A,
        preprocessing={"input_size": [112, 112]},
        opencv_version=OPENCV,
        ort_version=ORT,
    )
    assert sface.embedding_dim == 128
    assert auraface.embedding_dim == 512
    assert sface.leg_id(Arm.native).space_fingerprint != auraface.leg_id(Arm.native).space_fingerprint


def test_factory_refuses_an_embedder_whose_dimension_differs_from_its_own_manifest():
    with pytest.raises(RuntimeMismatchError):
        build_face_pipeline_leg(
            LegKind.sface,
            manifest=_manifest(128),
            detector=object(),
            aligner=object(),
            embedder=_fake_embedder(512),
            weights_sha256=SHA_A,
            preprocessing={"input_size": [112, 112]},
            opencv_version=OPENCV,
            ort_version=ORT,
        )


class _FakeDetector:
    """Returns production RawDetection objects, batch-shaped like OrtYuNetDetector.detect."""

    def __init__(self, dets):
        self._dets = dets

    def detect(self, images):
        return [
            [
                RawDetection(bbox=np.asarray(b, dtype=np.float32), landmarks=lm.astype(np.float32), score=s)
                for b, lm, s in self._dets
            ]
            for _ in images
        ]


class _FakeAligner:
    def __init__(self, *, fail: bool = False):
        self._fail = fail

    def align(self, image, landmarks):
        if self._fail:
            raise AlignmentError("no valid similarity transform")
        return SimpleNamespace(crop=np.full((112, 112, 3), 7, dtype=np.uint8), affine=np.eye(2, 3))


def _pipeline_leg(*, aligner_fail: bool):
    det = _det(4, 4, 20, 20)
    return build_face_pipeline_leg(
        LegKind.sface,
        manifest=_manifest(128),
        detector=_FakeDetector([((det.bbox_px), det.landmarks_px, det.score)]),
        aligner=_FakeAligner(fail=aligner_fail),
        embedder=_fake_embedder(128),
        weights_sha256=SHA_A,
        preprocessing={"input_size": [112, 112]},
        opencv_version=OPENCV,
        ort_version=ORT,
    )


def test_face_pipeline_leg_runs_detect_align_embed_on_its_own_dimension():
    leg = _pipeline_leg(aligner_fail=False)
    (obs,) = leg.observe(_image(12, value=5))
    assert obs.stage == SearchStage.embedded
    assert obs.embedding is not None and obs.embedding.shape == (128,)


def test_face_pipeline_leg_aligner_failure_is_unaligned_not_embedded():
    leg = _pipeline_leg(aligner_fail=True)
    (obs,) = leg.observe(_image(12, value=5))
    assert obs.stage == SearchStage.unaligned
    assert obs.embedding is None


def test_corrupt_cache_file_raises_instead_of_reporting_a_miss(tmp_path: Path):
    path = tmp_path / "legs" / "k" / "cache.npz"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not an npz archive")
    with pytest.raises((OSError, ValueError)):
        LegCache(path, leg_key="k").load()


def _manifest(dim: int) -> EmbeddingModelManifest:
    return EmbeddingModelManifest(
        framework="opencv" if dim == 128 else "insightface",
        name=f"fake{dim}+cv{OPENCV}/ort{ORT}",
        dimensions=dim,
        normalization="l2",
        metric="cosine",
    )


def test_changed_preprocessing_changes_key_and_misses_cache_and_corrupt_key_raises(tmp_path: Path):
    base = {"kind": "sface", "weights_sha256": SHA_A, "preprocessing": {"input_size": [112, 112]}}
    changed = {"kind": "sface", "weights_sha256": SHA_A, "preprocessing": {"input_size": [96, 96]}}
    key_a = LegId(LegKind.sface, Arm.native, space_fingerprint(base), OPENCV, ORT).key()
    key_b = LegId(LegKind.sface, Arm.native, space_fingerprint(changed), OPENCV, ORT).key()
    assert key_a != key_b

    cache_a = LegCache(tmp_path / "legs" / key_a / "cache.npz", leg_key=key_a)
    cache_a.store({"sha-1": np.zeros((1, 128), dtype=np.float32)})
    assert LegCache(tmp_path / "legs" / key_b / "cache.npz", leg_key=key_b).load() is None, "new key is a miss"

    corrupt = LegCache(tmp_path / "legs" / key_a / "cache.npz", leg_key=key_b)
    with pytest.raises(RuntimeMismatchError):
        corrupt.load()


def test_compare_guard_rejects_vectors_across_fingerprints_and_runtime_mismatch_within_kind():
    a = LegId(LegKind.sface, Arm.native, space_fingerprint({"k": 1}), OPENCV, ORT)
    b = LegId(LegKind.auraface, Arm.native, space_fingerprint({"k": 2}), OPENCV, ORT)
    with pytest.raises(CrossSpaceComparisonError):
        compare_guard(a, b)
    a_bumped = LegId(LegKind.sface, Arm.native, a.space_fingerprint, OPENCV, "1.29.0")
    with pytest.raises(RuntimeMismatchError):
        compare_guard(a, a_bumped)
    compare_guard(a, LegId(LegKind.sface, Arm.native, a.space_fingerprint, OPENCV, ORT))


# --- RED: canary ----------------------------------------------------------------


def test_canary_relabels_every_selected_identity_and_is_reproducible_from_seed():
    perm_one = derangement(["id-0001", "id-0002", "id-0003"], seed=7)
    perm_two = derangement(["id-0001", "id-0002", "id-0003"], seed=7)
    assert perm_one == perm_two
    assert all(src != dst for src, dst in perm_one.items())
    assert sorted(perm_one.values()) == ["id-0001", "id-0002", "id-0003"]


def test_canary_leg_relabels_gallery_templates_and_has_canary_kind():
    base = _FakeSeparableLeg(kind=LegKind.sface, dim=128, dets_by_image={}, images={})
    canary = CanaryLeg(base, canary_identities=["id-0001", "id-0002"], seed=11)
    gallery = {"id-0001": np.eye(128, dtype=np.float32)[0], "id-0002": np.eye(128, dtype=np.float32)[1]}
    relabelled = canary.relabel_gallery(gallery)
    assert set(relabelled) == {"id-0001", "id-0002"}
    for identity in ("id-0001", "id-0002"):
        assert not np.array_equal(relabelled[identity], gallery[identity]), "every selected label changes"
    assert canary.leg_id(Arm.native).kind == LegKind.canary


def test_canary_rejects_fewer_than_two_identities_and_fixed_points():
    base = _FakeSeparableLeg(kind=LegKind.sface, dim=128, dets_by_image={}, images={})
    with pytest.raises(CanaryConfigError):
        CanaryLeg(base, canary_identities=["id-0001"], seed=1)
    with pytest.raises(CanaryConfigError):
        CanaryLeg(
            base,
            canary_identities=["id-0001", "id-0002"],
            seed=1,
            permutation={"id-0001": "id-0001", "id-0002": "id-0002"},
        )


def test_expected_changed_search_ids_are_accepted_mated_probes_of_the_canary_set():
    accepted = {"search-1": "id-0001", "search-2": "id-0002", "search-3": "id-0009"}
    assert expected_changed_search_ids(accepted, ["id-0001", "id-0002"]) == ["search-1", "search-2"]


# --- RED: schema and determinism ------------------------------------------------


def test_every_search_row_validates_against_face_search_record_v1(tmp_path: Path):
    images = {"image-0001": _image(8, value=90)}
    dets = {"image-0001": [_det(4, 4, 20, 20), _det(40, 40, 10, 10, score=0.6)]}
    leg = _FakeSeparableLeg(kind=LegKind.sface, dim=128, dets_by_image=dets, images=images)
    faces = [
        _GtFace(
            "face-0001",
            "image-0001",
            (4, 4, 20, 20),
            IdentityStatus.named,
            "id-0001",
            {"sex": None, "age_band": "adult", "origin": None},
        ),
        _GtFace("face-0002", "image-0001", (40, 40, 16, 16), IdentityStatus.unknown, None),
    ]
    result = _run(leg, Arm.native, images, faces)
    out = tmp_path / "searches.jsonl"
    write_searches_jsonl(out, result.records)
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert rows, "searches.jsonl must not be empty"
    for row in rows:
        validate_interchange("face-search-record-v1", row)


def test_two_runs_on_the_same_inputs_write_byte_identical_searches_jsonl(tmp_path: Path):
    images = {"image-0001": _image(9, value=100)}
    dets = {"image-0001": [_det(4, 4, 20, 20), _det(40, 40, 10, 10, score=0.6)]}
    faces = [_GtFace("face-0001", "image-0001", (4, 4, 20, 20), IdentityStatus.named, "id-0001")]
    paths = []
    for name in ("first", "second"):
        leg = _FakeSeparableLeg(kind=LegKind.sface, dim=128, dets_by_image=dets, images=images)
        result = _run(leg, Arm.native, images, faces)
        path = tmp_path / name / "searches.jsonl"
        path.parent.mkdir()
        write_searches_jsonl(path, result.records)
        paths.append(path)
    assert paths[0].read_bytes() == paths[1].read_bytes()


def test_search_record_row_fails_schema_when_a_required_key_is_removed():
    images = {"image-0001": _image(11, value=120)}
    leg = _FakeSeparableLeg(
        kind=LegKind.sface, dim=128, dets_by_image={"image-0001": [_det(4, 4, 20, 20)]}, images=images
    )
    faces = [_GtFace("face-0001", "image-0001", (4, 4, 20, 20), IdentityStatus.named, "id-0001")]
    (row,) = [r for r in _run(leg, Arm.native, images, faces).records if r.face_id == "face-0001"]
    payload = row.to_dict()
    validate_interchange("face-search-record-v1", payload)
    assert isinstance(row, FaceSearchRecord)
    del payload["gallery_sha256"]
    with pytest.raises(FrameContractError):
        validate_interchange("face-search-record-v1", payload)


def test_unknown_identity_is_nonmated_only_on_exhaustive_frame_and_unresolved_is_never_nonmated():
    images = {"image-0001": _image(10, value=110)}
    faces = [
        _GtFace("face-0001", "image-0001", (4, 4, 20, 20), IdentityStatus.unresolved, None),
    ]
    leg = _FakeSeparableLeg(
        kind=LegKind.sface, dim=128, dets_by_image={"image-0001": [_det(4, 4, 20, 20)]}, images=images
    )
    result = _run(leg, Arm.native, images, faces)
    (row,) = [r for r in result.records if r.face_id == "face-0001"]
    assert row.unit_id is None
    assert row.identity_status == IdentityStatus.unresolved


def test_end_to_end_two_images_two_arms_write_validated_searches_and_one_ledger_row_per_face(tmp_path: Path):
    """Clean dev-only integration: fakes for every leg, real search, validation and writer."""
    images = {"image-0001": _image(21, value=130), "image-0002": _image(22, value=140)}
    dets = {"image-0001": [_det(4, 4, 20, 20), _det(40, 40, 10, 10, score=0.6)], "image-0002": []}
    leg = _FakeSeparableLeg(kind=LegKind.sface, dim=128, dets_by_image=dets, images=images)
    faces = [
        _GtFace("face-0001", "image-0001", (4, 4, 20, 20), IdentityStatus.named, "id-0001"),
        _GtFace("face-0002", "image-0002", (8, 8, 16, 16), IdentityStatus.unknown, None),
    ]
    native = _run(leg, Arm.native, images, faces)
    replay = _run(
        leg,
        Arm.cached_yunet_landmark_replay,
        images,
        faces,
        cached={"face-0001": np.zeros((5, 2))},
    )
    write_searches_jsonl(tmp_path / "searches.jsonl", native.records + replay.records)
    rows = [json.loads(line) for line in (tmp_path / "searches.jsonl").read_text(encoding="utf-8").splitlines()]
    for row in rows:
        validate_interchange("face-search-record-v1", row)
    assert {r["unit_id"] for r in rows if r["unit_id"]} == {"face-0002", "background:image-0001"}
    assert len(native.ledger) == len(faces) and len(replay.ledger) == len(faces)
    assert all(row.stage_reached is not None for row in replay.ledger)
    assert {row.arm for row in native.ledger} == {Arm.native}
