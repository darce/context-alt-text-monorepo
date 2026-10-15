"""FIRBENCH-1 S2: in-process legs, arms, contract-keyed cache and per-face search records.

Each leg is its own embedding space [EMB-01]. A change to the leg's contract (model manifest,
preprocessing, OpenCV or ORT version) changes ``LegId.key()`` and so invalidates its cache.
A separable leg runs its own pinned detector, five-point aligner and embedder. The fused leg
(InsightFace buffalo_l) has no separable alignment stage and is recorded as ``fused_internal``.

The factory reads only the pieces it is given and the leg's own manifest dimension. It never
reads the shared runtime or the global dimension settings.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np

from recognition.infrastructure.face_pipeline.aligner import AlignmentError
from scripts.eval_harness.face_assignment import (
    IOU_MATCH_THRESHOLD,
    hungarian_iou_pairs,
    iou_pixel_corner,
    mean_prototype,
)
from scripts.eval_harness.firbench_contract import (
    AlignmentMode,
    Arm,
    ArmStatus,
    CanaryConfigError,
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

if TYPE_CHECKING:
    # S1 Build 1 names. firbench_frames is not merged yet; these are read by attribute only.
    from scripts.eval_harness.firbench_frames import GtFace, ImageUnit

    from recognition.application.embedding.manifest import EmbeddingModelManifest


_FACE_PIPELINE_KINDS = frozenset({LegKind.sface, LegKind.auraface})
_ATTRIBUTION_ARMS = frozenset({Arm.gt_crop_redetect, Arm.cached_yunet_landmark_replay})
# Sentinels for the cell pair when no occluder label is supplied. Explicit labels always win.
_UNKNOWN_CELL = ("unknown", "unknown")
_BACKGROUND_CELL = ("background", "background")
_DUPLICATE_CELL = ("duplicate", "duplicate")


class FusedLegProtocolError(RuntimeError):
    """A fused leg was asked for a separable stage (align or embed on its own)."""


# --- observations and the leg protocol --------------------------------------------


@dataclass(frozen=True)
class DetectedFace:
    """One detector output in image pixels: xywh box, 5x2 landmarks, detector score."""

    bbox_px: tuple[float, float, float, float]
    landmarks_px: np.ndarray
    score: float


@dataclass(frozen=True)
class Observation:
    """One detection after a leg ran, with the furthest stage it reached."""

    detection: DetectedFace
    embedding: np.ndarray | None
    stage: SearchStage

    @classmethod
    def embedded(cls, detection: DetectedFace, embedding: np.ndarray) -> Observation:
        return cls(detection=detection, embedding=np.asarray(embedding, dtype=np.float32), stage=SearchStage.embedded)

    @classmethod
    def unaligned(cls, detection: DetectedFace) -> Observation:
        return cls(detection=detection, embedding=None, stage=SearchStage.unaligned)

    @classmethod
    def fused(cls, detection: DetectedFace, embedding: np.ndarray | None) -> Observation:
        if embedding is None:
            return cls(detection=detection, embedding=None, stage=SearchStage.detected)
        return cls(detection=detection, embedding=np.asarray(embedding, dtype=np.float32), stage=SearchStage.embedded)


class LegRuntime(Protocol):
    """One leg in one embedding space. ``observe`` is the single entry point for both leg kinds.

    A separable leg runs detect, align and embed inside ``observe``. The fused leg runs one call.
    """

    kind: LegKind
    alignment_mode: AlignmentMode

    def leg_id(self, arm: Arm) -> LegId: ...

    def observe(self, image_bgr: np.ndarray) -> tuple[Observation, ...]: ...


# --- space identity ----------------------------------------------------------------


def space_fingerprint(payload: Mapping[str, object]) -> str:
    """sha256 over the canonical model manifest payload (weights, input, normalization, metric)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _unit(vector: np.ndarray) -> np.ndarray:
    arr = np.asarray(vector, dtype=np.float64).reshape(-1)
    norm = float(np.linalg.norm(arr))
    if not np.isfinite(norm) or norm == 0.0:
        raise RuntimeMismatchError("embedding has a zero or non-finite norm")
    return arr / norm


def _check_dimension(vector: np.ndarray, expected: int, *, leg: str) -> np.ndarray:
    arr = np.asarray(vector).reshape(-1)
    if arr.size != expected:
        raise RuntimeMismatchError(f"{leg}: embedder output dimension {arr.size} != manifest dimension {expected}")
    return arr


# --- separable face-pipeline legs (SFace-128, AuraFace-512) -------------------------


@dataclass(frozen=True)
class FacePipelineLeg:
    """YuNet detect, model-compatible five-point align, then embed. Each leg is its own space [EMB-01]."""

    kind: LegKind
    manifest: EmbeddingModelManifest
    detector: Any
    aligner: Any
    embedder: Any
    space: str
    opencv_version: str
    ort_version: str
    alignment_mode: AlignmentMode = field(default=AlignmentMode.separable, init=False)

    @property
    def embedding_dim(self) -> int:
        return int(self.manifest.dimensions)

    def leg_id(self, arm: Arm) -> LegId:
        return LegId(self.kind, arm, self.space, self.opencv_version, self.ort_version)

    def detect(self, image_bgr: np.ndarray) -> tuple[DetectedFace, ...]:
        raw = self.detector.detect([image_bgr])[0]
        return tuple(
            DetectedFace(
                bbox_px=(float(d.bbox[0]), float(d.bbox[1]), float(d.bbox[2]), float(d.bbox[3])),
                landmarks_px=np.asarray(d.landmarks, dtype=np.float64).reshape(5, 2),
                score=float(d.score),
            )
            for d in raw
        )

    def align(self, image_bgr: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
        return np.asarray(self.aligner.align(image_bgr, np.asarray(landmarks, dtype=np.float64)).crop)

    def embed(self, aligned: np.ndarray) -> np.ndarray:
        result = self.embedder.embed([aligned])
        return _check_dimension(np.asarray(result.vectors)[0], self.embedding_dim, leg=self.kind.value)

    def observe(self, image_bgr: np.ndarray) -> tuple[Observation, ...]:
        out: list[Observation] = []
        for detection in self.detect(image_bgr):
            try:
                aligned = self.align(image_bgr, detection.landmarks_px)
            except AlignmentError:
                # The aligner found no valid transform: the detector fired, but no embedding was made.
                out.append(Observation.unaligned(detection))
                continue
            out.append(Observation.embedded(detection, self.embed(aligned)))
        return tuple(out)


def build_face_pipeline_leg(
    kind: LegKind,
    *,
    manifest: EmbeddingModelManifest,
    detector: Any,
    aligner: Any,
    embedder: Any,
    weights_sha256: str,
    preprocessing: Mapping[str, object] | None,
    opencv_version: str,
    ort_version: str,
) -> FacePipelineLeg:
    """Assemble one face-pipeline leg from its own pinned pieces.

    Refuses an embedder whose output dimension differs from this leg's own manifest dimension.
    """
    if kind not in _FACE_PIPELINE_KINDS:
        raise RuntimeMismatchError(f"{kind.value} is not a face-pipeline leg kind")
    embedder_dim = int(embedder.embedding_dim)
    if embedder_dim != int(manifest.dimensions):
        raise RuntimeMismatchError(
            f"{kind.value}: embedder dimension {embedder_dim} != manifest dimension {manifest.dimensions}"
        )
    space = space_fingerprint(
        {
            "kind": kind.value,
            "framework": manifest.framework,
            "name": manifest.name,
            "dimensions": int(manifest.dimensions),
            "normalization": manifest.normalization,
            "metric": manifest.metric,
            "weights_sha256": weights_sha256,
            "preprocessing": dict(preprocessing) if preprocessing is not None else None,
        }
    )
    return FacePipelineLeg(
        kind=kind,
        manifest=manifest,
        detector=detector,
        aligner=aligner,
        embedder=embedder,
        space=space,
        opencv_version=opencv_version,
        ort_version=ort_version,
    )


def load_pinned_face_pipeline_leg(
    kind: LegKind, *, models_dir: Path, embedder_models_dir: Path | None = None
) -> FacePipelineLeg:
    """Offline factory: one leg from the pinned weights on disk (needs the weights; VM only).

    Builds the pinned YuNet detector, five-point aligner and embedder directly. It does not go
    through the shared runtime loader, so the global three-way dimension guard does not run here.
    """
    from recognition.infrastructure.embeddings.face_pipeline_adapter import (
        auraface_embedding_model_manifest,
        sface_embedding_model_manifest,
    )
    from recognition.infrastructure.face_pipeline._common import (
        DEFAULT_NMS_THRESHOLD,
        DEFAULT_SCORE_THRESHOLD,
        DEFAULT_TOP_K,
    )
    from recognition.infrastructure.face_pipeline.aligner import FivePointAligner
    from recognition.infrastructure.face_pipeline.model_space import ModelSpace
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtSFaceEmbedder, OrtYuNetDetector
    from recognition.infrastructure.face_pipeline.provenance import MODEL_MANIFEST, numeric_runtime_fingerprint

    if kind not in _FACE_PIPELINE_KINDS:
        raise RuntimeMismatchError(f"{kind.value} is not a face-pipeline leg kind")
    runtime = numeric_runtime_fingerprint()
    is_aura = kind is LegKind.auraface
    manifest = auraface_embedding_model_manifest(_fingerprint=runtime) if is_aura else sface_embedding_model_manifest()
    provenance = MODEL_MANIFEST[kind.value]
    detector = OrtYuNetDetector(
        models_dir=Path(models_dir),
        score_threshold=DEFAULT_SCORE_THRESHOLD,
        nms_threshold=DEFAULT_NMS_THRESHOLD,
        top_k=DEFAULT_TOP_K,
        **({"acquire_verified": True} if is_aura else {}),
    )
    embed_dir = Path(embedder_models_dir) if embedder_models_dir is not None else Path(models_dir)
    if is_aura:
        embedder = OrtSFaceEmbedder(model_name="auraface", models_dir=embed_dir, acquire_verified=True)
    else:
        embedder = OrtSFaceEmbedder(models_dir=embed_dir)
    return build_face_pipeline_leg(
        kind,
        manifest=manifest,
        detector=detector,
        aligner=FivePointAligner(space=ModelSpace.AURAFACE if is_aura else ModelSpace.FACE_PIPELINE),
        embedder=embedder,
        weights_sha256=provenance.sha256,
        preprocessing=asdict(provenance.preprocessing) if provenance.preprocessing is not None else None,
        opencv_version=runtime.opencv_version,
        ort_version=runtime.onnxruntime_version,
    )


# --- fused InsightFace buffalo_l leg (judge-side reference) ----------------------


class BuffaloLeg:
    """InsightFace buffalo_l: one fused call per image. Alignment is internal, so it is never 'unaligned'."""

    kind = LegKind.insightface
    alignment_mode = AlignmentMode.fused_internal

    def __init__(
        self,
        *,
        process: Callable[[np.ndarray], Sequence[Mapping[str, Any]]] | None = None,
        embedding_dim: int = 512,
        weights_sha256: str,
        opencv_version: str,
        ort_version: str,
    ) -> None:
        self._process = process
        self._embedding_dim = embedding_dim
        self._space = space_fingerprint(
            {
                "kind": "insightface",
                "model": "buffalo_l",
                "dimensions": embedding_dim,
                "weights_sha256": weights_sha256,
                "alignment": "fused_internal",
            }
        )
        self._opencv_version = opencv_version
        self._ort_version = ort_version

    def leg_id(self, arm: Arm) -> LegId:
        return LegId(self.kind, arm, self._space, self._opencv_version, self._ort_version)

    def observe(self, image_bgr: np.ndarray) -> tuple[Observation, ...]:
        if self._process is None:
            self._process = _default_buffalo_process(embedding_dim=self._embedding_dim)
        out: list[Observation] = []
        for face in self._process(image_bgr):
            detection = DetectedFace(
                bbox_px=tuple(float(v) for v in face["bbox_px"]),  # type: ignore[arg-type]
                landmarks_px=np.asarray(face["landmarks_px"], dtype=np.float64).reshape(5, 2),
                score=float(face["det_score"]),
            )
            raw = face.get("embedding")
            embedding = None
            if raw is not None:
                embedding = _check_dimension(np.asarray(raw), self._embedding_dim, leg=self.kind.value)
            out.append(Observation.fused(detection, embedding))
        return tuple(out)

    def detect(self, image_bgr: np.ndarray) -> tuple[DetectedFace, ...]:
        raise FusedLegProtocolError("the buffalo leg detects, aligns and embeds in one call; use observe")

    def align(self, image_bgr: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
        raise FusedLegProtocolError("the buffalo leg aligns inside insightface; it has no separable align stage")

    def embed(self, aligned: np.ndarray) -> np.ndarray:
        raise FusedLegProtocolError("the buffalo leg embeds inside insightface; it has no separable embed stage")


def _default_buffalo_process(*, embedding_dim: int) -> Callable[[np.ndarray], Sequence[Mapping[str, Any]]]:
    """Build one leg-owned app on first observe; the lazy bench import retains its eval-only refusal."""
    from scripts.eval_harness import buffalo_bench

    app = buffalo_bench._build_face_analysis()

    def process(image_bgr: np.ndarray) -> Sequence[Mapping[str, Any]]:
        return buffalo_bench.process_image_bgr_buffalo(image_bgr, app=app, embedding_dim=embedding_dim)

    return process


# --- canary (declared identity relabel) ----------------------------------------


def derangement(identities: Sequence[str], *, seed: int) -> dict[str, str]:
    """Seeded derangement over the declared canary set S. Sattolo's algorithm gives one cycle, so no fixed point."""
    ids = sorted(identities)
    if len(ids) < 2:
        raise CanaryConfigError(f"a canary needs at least two identities, got {len(ids)}")
    if len(set(ids)) != len(ids):
        raise CanaryConfigError("canary identities must be distinct")
    rng = np.random.default_rng(seed)
    order = list(range(len(ids)))
    for i in range(len(ids) - 1, 0, -1):
        j = int(rng.integers(0, i))
        order[i], order[j] = order[j], order[i]
    return {ids[i]: ids[order[i]] for i in range(len(ids))}


def _validate_permutation(identities: Sequence[str], permutation: Mapping[str, str]) -> dict[str, str]:
    ids = sorted(identities)
    if len(ids) < 2:
        raise CanaryConfigError(f"a canary needs at least two identities, got {len(ids)}")
    if sorted(permutation) != ids or sorted(permutation.values()) != ids:
        raise CanaryConfigError("canary permutation must be a bijection on the declared identity set")
    fixed = sorted(src for src, dst in permutation.items() if src == dst)
    if fixed:
        raise CanaryConfigError(f"permutation leaves selected labels fixed: {fixed}")
    return dict(permutation)


class CanaryLeg:
    """Wraps a leg. Relabels the gallery templates of a declared identity set S, so every selected label changes."""

    kind = LegKind.canary

    def __init__(
        self,
        base: LegRuntime,
        *,
        canary_identities: Sequence[str],
        seed: int,
        permutation: Mapping[str, str] | None = None,
    ) -> None:
        self._base = base
        self.alignment_mode = base.alignment_mode
        self.canary_identities = tuple(sorted(canary_identities))
        if permutation is None:
            self.permutation = derangement(self.canary_identities, seed=seed)
        else:
            self.permutation = _validate_permutation(self.canary_identities, permutation)

    def leg_id(self, arm: Arm) -> LegId:
        base = self._base.leg_id(arm)
        return LegId(LegKind.canary, arm, base.space_fingerprint, base.opencv_version, base.ort_version)

    def observe(self, image_bgr: np.ndarray) -> tuple[Observation, ...]:
        return self._base.observe(image_bgr)

    def relabel_gallery(self, gallery: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]:
        relabelled: dict[str, np.ndarray] = {}
        for identity, vector in gallery.items():
            relabelled[self.permutation.get(identity, identity)] = vector
        return relabelled


def expected_changed_search_ids(accepted_mated: Mapping[str, str], canary_identities: Sequence[str]) -> list[str]:
    """Search ids of the accepted mated probes whose identity is in S. A canary must change these."""
    selected = set(canary_identities)
    return sorted(search_id for search_id, identity in accepted_mated.items() if identity in selected)


# --- compare guard -------------------------------------------------------------


def compare_guard(leg_a: LegId, leg_b: LegId) -> None:
    """Refuse vector operations across spaces [EMB-01], and across runtime versions of one leg kind."""
    versions_a = (leg_a.opencv_version, leg_a.ort_version)
    versions_b = (leg_b.opencv_version, leg_b.ort_version)
    if leg_a.kind == leg_b.kind and versions_a != versions_b:
        raise RuntimeMismatchError(f"{leg_a.kind.value}: OpenCV/ORT versions differ ({versions_a} vs {versions_b})")
    if leg_a.space_fingerprint != leg_b.space_fingerprint:
        raise CrossSpaceComparisonError("vectors from different space_fingerprint values cannot be compared")


# --- contract-keyed cache ------------------------------------------------------


class LegCache:
    """``legs/<leg_key>/cache.npz``. A key mismatch on read raises. It never recomputes into the same file."""

    _KEY_FIELD = "__leg_key__"
    _ARRAY_PREFIX = "a_"

    def __init__(self, path: Path, *, leg_key: str) -> None:
        self.path = Path(path)
        self.leg_key = leg_key

    def load(self) -> dict[str, np.ndarray] | None:
        if not self.path.exists():
            return None
        with np.load(self.path, allow_pickle=False) as data:
            stored = str(data[self._KEY_FIELD])
            if stored != self.leg_key:
                raise RuntimeMismatchError(f"cache {self.path} holds key {stored!r}, expected {self.leg_key!r}")
            prefix = self._ARRAY_PREFIX
            return {name[len(prefix) :]: data[name] for name in data.files if name.startswith(prefix)}

    def store(self, arrays: Mapping[str, np.ndarray]) -> None:
        self.load()  # refuses to overwrite a file written under another key
        payload: dict[str, np.ndarray] = {self._KEY_FIELD: np.asarray(self.leg_key)}
        for name in sorted(arrays):
            payload[f"{self._ARRAY_PREFIX}{name}"] = np.asarray(arrays[name])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(self.path, **payload)


# --- search records and ledger --------------------------------------------------


@dataclass(frozen=True)
class FaceSearchRecord:
    """One ``searches.jsonl`` row (README table; schema ``face-search-record-v1``)."""

    face_id: str
    image_id: str
    psu_id: str
    identity_id: str | None
    identity_status: IdentityStatus
    fold: int
    fold_role: FoldRole
    cell: tuple[str, str]
    unit_id: str | None
    sampling_arm: SamplingArm
    inclusion_probability: float | None
    cohort: Mapping[str, str | None] | None
    leg_key: str
    arm: Arm
    arm_availability: ArmStatus
    alignment_mode: AlignmentMode
    stage_reached: SearchStage | None
    top_k: tuple[tuple[str, float], ...]
    gallery_sha256: str
    timing_receipt_ref: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "face_id": self.face_id,
            "image_id": self.image_id,
            "psu_id": self.psu_id,
            "identity_id": self.identity_id,
            "identity_status": IdentityStatus(self.identity_status).value,
            "fold": int(self.fold),
            "fold_role": FoldRole(self.fold_role).value,
            "cell": list(self.cell),
            "unit_id": self.unit_id,
            "sampling_arm": SamplingArm(self.sampling_arm).value,
            "inclusion_probability": self.inclusion_probability,
            "cohort": dict(self.cohort) if self.cohort is not None else None,
            "leg_key": self.leg_key,
            "arm": Arm(self.arm).value,
            "arm_availability": ArmStatus(self.arm_availability).value,
            "alignment_mode": AlignmentMode(self.alignment_mode).value,
            "stage_reached": SearchStage(self.stage_reached).value if self.stage_reached is not None else None,
            "top_k": [[identity, score] for identity, score in self.top_k],
            "gallery_sha256": self.gallery_sha256,
            "timing_receipt_ref": self.timing_receipt_ref,
        }


@dataclass(frozen=True)
class LedgerRow:
    """One (GT face, leg, arm) outcome row. Background and duplicate detections never appear here."""

    face_id: str
    leg_key: str
    arm: Arm
    stage_reached: SearchStage | None
    arm_availability: ArmStatus
    alignment_mode: AlignmentMode


@dataclass(frozen=True)
class ArmResult:
    records: tuple[FaceSearchRecord, ...]
    ledger: tuple[LedgerRow, ...]
    timings_ms: Mapping[str, float]


def write_searches_jsonl(path: Path, records: Sequence[FaceSearchRecord]) -> None:
    """Canonical JSON lines, one per record. Each row is validated before it is written."""
    lines = []
    for record in records:
        payload = record.to_dict()
        validate_interchange("face-search-record-v1", payload)
        lines.append(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    Path(path).write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


# --- gallery and search -----------------------------------------------------------


@dataclass(frozen=True)
class Gallery:
    """Enrolled identities (mean prototypes) for one fold's gallery. ``gallery_sha256`` is its snapshot id."""

    prototypes: Mapping[str, np.ndarray]
    gallery_sha256: str

    @classmethod
    def enrol(cls, templates: Mapping[str, Sequence[np.ndarray]]) -> Gallery:
        prototypes = {identity: mean_prototype(list(vectors)) for identity, vectors in sorted(templates.items())}
        return cls._snapshot(prototypes)

    @classmethod
    def _snapshot(cls, prototypes: Mapping[str, np.ndarray]) -> Gallery:
        digest = hashlib.sha256()
        for identity in sorted(prototypes):
            digest.update(identity.encode("utf-8"))
            digest.update(b"\0")
            digest.update(np.asarray(prototypes[identity], dtype=np.float32).tobytes())
        return cls(prototypes=dict(prototypes), gallery_sha256=digest.hexdigest())

    def relabelled(self, canary: CanaryLeg) -> Gallery:
        """Snapshot a single declared relabel without re-enrolling or modifying the input gallery."""
        missing = sorted(set(canary.canary_identities) - set(self.prototypes))
        if missing:
            raise CanaryConfigError(f"canary identities absent from gallery: {missing}")
        return self._snapshot(canary.relabel_gallery(self.prototypes))


def _top_k(vector: np.ndarray, gallery: Gallery, k: int) -> tuple[tuple[str, float], ...]:
    identities = sorted(gallery.prototypes)
    if not identities:
        return ()
    query = _unit(vector)
    scores = [float(np.dot(np.asarray(gallery.prototypes[i], dtype=np.float64), query)) for i in identities]
    order = sorted(range(len(identities)), key=lambda i: (-scores[i], identities[i]))[:k]
    return tuple((identities[i], scores[i]) for i in order)


def _cohort(face: GtFace) -> dict[str, str | None] | None:
    if face.cohort is None:
        return None
    # S1 produces a frozen Cohort, not a mapping. Keep mapping inputs usable for wire callers.
    cohort = face.cohort if isinstance(face.cohort, Mapping) else face.cohort.to_json()
    return {key: cohort.get(key) for key in ("sex", "age_band", "origin")}


def _is_nonmated(status: IdentityStatus, *, mated: bool, exhaustive: bool) -> bool:
    # A named face is non-mated only when its identity is held out of this gallery.
    # An unknown face is non-mated only on an exhaustive frame. An unresolved face is never non-mated.
    if status == IdentityStatus.named:
        return not mated
    if status == IdentityStatus.unknown:
        return exhaustive
    return False


@dataclass(frozen=True)
class _Pending:
    """One record to build: a GT face or a detection-only unit (background or duplicate)."""

    face_id: str
    image_id: str
    identity_id: str | None
    status: IdentityStatus
    cohort: Mapping[str, str | None] | None
    unit_id: str | None
    cell: tuple[str, str]


def search_leg_arm(
    *,
    leg: LegRuntime,
    arm: Arm,
    images: Mapping[str, np.ndarray],
    image_units: Mapping[str, ImageUnit],
    faces: Sequence[GtFace],
    gallery: Gallery,
    psu_by_image: Mapping[str, str],
    fold_by_psu: Mapping[str, int],
    fold_roles: Mapping[int, FoldRole],
    exhaustive: bool,
    top_k: int,
    cells: Mapping[str, tuple[str, str]] | None = None,
    cached_landmarks: Mapping[str, np.ndarray] | None = None,
    crop_margin: float | None = None,
) -> ArmResult:
    """Run one leg and arm over every frame image. Write one record per GT face, plus native background units.

    Attribution arms (gt_crop_redetect, cached_yunet_landmark_replay) create no background units.

    Native receipt milliseconds cover observe, matching, top-k search and record construction for
    the image, divided equally across its emitted GT and unmatched-detection rows. These are
    amortized shares of shared image work, not independently measured face latencies; duplicates
    and misses also receive a share. A row-free image retains its elapsed cost under
    ``<leg_key>/native/image:<image_id>`` (an image receipt, not a face p95 sample).
    Attribution receipts measure each face's crop/replay through top-k. All clocks and milliseconds
    stay in the non-replayable receipt; semantic rows contain only stable receipt references [FLOW-18].
    """
    if top_k < 1:
        raise FrameContractError("top_k must be at least 1")
    if isinstance(leg, CanaryLeg):
        # The invocation owns the single relabel. Never mutate or reuse a changed input snapshot.
        gallery = gallery.relabelled(leg)
    runtime = leg._base if isinstance(leg, CanaryLeg) else leg
    leg_key = leg.leg_id(arm).key()
    fused = leg.alignment_mode is AlignmentMode.fused_internal
    alignment = AlignmentMode.fused_internal if fused else AlignmentMode.separable
    cell_of = dict(cells or {})
    gt_records: list[FaceSearchRecord] = []
    det_records: list[FaceSearchRecord] = []
    timings: dict[str, float] = {}

    def _emit(
        pending: _Pending,
        *,
        image_id: str,
        arm_availability: ArmStatus,
        stage: SearchStage | None,
        hits: tuple[tuple[str, float], ...],
        ms: float,
    ) -> FaceSearchRecord:
        if image_id not in psu_by_image:
            raise FrameContractError(f"image {image_id!r} has no PSU component")
        psu_id = psu_by_image[image_id]
        if psu_id not in fold_by_psu:
            raise FrameContractError(f"PSU {psu_id!r} has no fold")
        fold = int(fold_by_psu[psu_id])
        if fold not in fold_roles:
            raise FrameContractError(f"fold {fold} has no role")
        if image_id not in image_units:
            raise FrameContractError(f"image {image_id!r} has no image unit")
        unit = image_units[image_id]
        ref = f"{leg_key}/{arm.value}/{pending.face_id}"
        timings[ref] = ms
        return FaceSearchRecord(
            face_id=pending.face_id,
            image_id=image_id,
            psu_id=psu_id,
            identity_id=pending.identity_id,
            identity_status=pending.status,
            fold=fold,
            fold_role=fold_roles[fold],
            cell=pending.cell,
            unit_id=pending.unit_id,
            sampling_arm=SamplingArm(unit.sampling_arm),
            inclusion_probability=unit.inclusion_probability,
            cohort=pending.cohort,
            leg_key=leg_key,
            arm=arm,
            arm_availability=arm_availability,
            alignment_mode=alignment,
            stage_reached=stage,
            top_k=hits,
            gallery_sha256=gallery.gallery_sha256,
            timing_receipt_ref=ref,
        )

    def _gt_pending(face: GtFace) -> _Pending:
        status = IdentityStatus(face.identity_status)
        if status == IdentityStatus.named and not face.identity_id:
            raise FrameContractError(f"named face {face.face_id} has no identity_id")
        mated = status == IdentityStatus.named and face.identity_id in gallery.prototypes
        nonmated = _is_nonmated(status, mated=mated, exhaustive=exhaustive)
        return _Pending(
            face_id=face.face_id,
            image_id=face.image_id,
            identity_id=face.identity_id if mated else None,
            status=status,
            cohort=_cohort(face),
            unit_id=face.face_id if nonmated else None,
            cell=tuple(cell_of.get(face.face_id, _UNKNOWN_CELL)),  # type: ignore[arg-type]
        )

    by_image: dict[str, list[GtFace]] = {}
    for face in faces:
        if face.image_id not in images:
            raise FrameContractError(f"face {face.face_id} references image {face.image_id!r} with no pixels")
        by_image.setdefault(face.image_id, []).append(face)

    if fused and arm in _ATTRIBUTION_ARMS:
        # The fused leg has no separable align stage, so both attribution arms are unavailable per face.
        for face in faces:
            gt_records.append(
                _emit(
                    _gt_pending(face),
                    image_id=face.image_id,
                    arm_availability=ArmStatus.unavailable_fused,
                    stage=None,
                    hits=(),
                    ms=0.0,
                )
            )
    elif arm is Arm.gt_crop_redetect:
        if crop_margin is None:
            raise FrameContractError("gt_crop_redetect needs the declared crop margin from the run manifest")
        for face in faces:
            t0 = perf_counter()
            stage, hits = SearchStage.missed, ()
            best = _best_crop_detection(leg, images[face.image_id], face, float(crop_margin))
            if best is not None:
                stage = best.stage
                if best.embedding is not None:
                    hits = _top_k(best.embedding, gallery, top_k)
            gt_records.append(
                _emit(
                    _gt_pending(face),
                    image_id=face.image_id,
                    arm_availability=ArmStatus.available,
                    stage=stage,
                    hits=hits,
                    ms=(perf_counter() - t0) * 1000.0,
                )
            )
    elif arm is Arm.cached_yunet_landmark_replay:
        landmarks_by_face = dict(cached_landmarks or {})
        for face in faces:
            t0 = perf_counter()
            landmarks = landmarks_by_face.get(face.face_id)
            if landmarks is None:
                # No cached landmark: unavailable, and never a fallback to other landmarks.
                gt_records.append(
                    _emit(
                        _gt_pending(face),
                        image_id=face.image_id,
                        arm_availability=ArmStatus.unavailable,
                        stage=SearchStage.unavailable,
                        hits=(),
                        ms=0.0,
                    )
                )
                continue
            stage, hits = SearchStage.embedded, ()
            try:
                aligned = runtime.align(images[face.image_id], np.asarray(landmarks))  # type: ignore[attr-defined]
            except AlignmentError:
                stage = SearchStage.unaligned
            else:
                hits = _top_k(runtime.embed(aligned), gallery, top_k)  # type: ignore[attr-defined]
            gt_records.append(
                _emit(
                    _gt_pending(face),
                    image_id=face.image_id,
                    arm_availability=ArmStatus.available,
                    stage=stage,
                    hits=hits,
                    ms=(perf_counter() - t0) * 1000.0,
                )
            )
    else:
        # Native arm. Every frame image runs, including images with no GT face (their background unit).
        for image_id in sorted(images):
            t0 = perf_counter()
            observations = leg.observe(images[image_id])
            image_gt_records: list[FaceSearchRecord] = []
            image_det_records: list[FaceSearchRecord] = []
            image_faces = sorted(by_image.get(image_id, []), key=lambda f: f.face_id)
            gt_boxes = [face.box for face in image_faces]
            matrix = np.array(
                [[iou_pixel_corner(obs.detection.bbox_px, box) for box in gt_boxes] for obs in observations],
                dtype=np.float64,
            ).reshape(len(observations), len(gt_boxes))
            matched = {det_i: gt_j for det_i, gt_j, _ in hungarian_iou_pairs(matrix, threshold=IOU_MATCH_THRESHOLD)}
            gt_to_det = {gt_j: det_i for det_i, gt_j in matched.items()}
            for gt_j, face in enumerate(image_faces):
                if gt_j in gt_to_det:
                    obs = observations[gt_to_det[gt_j]]
                    hits = _top_k(obs.embedding, gallery, top_k) if obs.embedding is not None else ()
                    stage: SearchStage = obs.stage
                else:
                    hits, stage = (), SearchStage.missed
                image_gt_records.append(
                    _emit(
                        _gt_pending(face),
                        image_id=image_id,
                        arm_availability=ArmStatus.available,
                        stage=stage,
                        hits=hits,
                        ms=0.0,
                    )
                )
            for det_i, obs in enumerate(observations):
                if det_i in matched:
                    continue
                overlaps_gt = any(iou_pixel_corner(obs.detection.bbox_px, box) > 0.0 for box in gt_boxes)
                hits = _top_k(obs.embedding, gallery, top_k) if obs.embedding is not None else ()
                # A duplicate over a GT face is not a unit: it is an extra spurious name only.
                # Any other detection is the background unit of its image [README: non-mated source unit].
                pending = _Pending(
                    face_id=f"det:{image_id}:{det_i}",
                    image_id=image_id,
                    identity_id=None,
                    status=IdentityStatus.unknown,
                    cohort=None,
                    unit_id=None if overlaps_gt else f"background:{image_id}",
                    cell=_DUPLICATE_CELL if overlaps_gt else _BACKGROUND_CELL,
                )
                image_det_records.append(
                    _emit(
                        pending,
                        image_id=image_id,
                        arm_availability=ArmStatus.available,
                        stage=obs.stage,
                        hits=hits,
                        ms=0.0,
                    )
                )
            elapsed_ms = (perf_counter() - t0) * 1000.0
            image_records = image_gt_records + image_det_records
            if image_records:
                share = elapsed_ms / len(image_records)
                for record in image_records:
                    timings[record.timing_receipt_ref] = share  # type: ignore[index]
            else:
                timings[f"{leg_key}/{arm.value}/image:{image_id}"] = elapsed_ms
            gt_records.extend(image_gt_records)
            det_records.extend(image_det_records)

    gt_records.sort(key=lambda r: (r.image_id, r.face_id))
    det_records.sort(key=lambda r: (r.image_id, r.face_id))
    records = tuple(gt_records + det_records)
    ledger = tuple(
        LedgerRow(
            face_id=r.face_id,
            leg_key=r.leg_key,
            arm=r.arm,
            stage_reached=r.stage_reached,
            arm_availability=r.arm_availability,
            alignment_mode=r.alignment_mode,
        )
        for r in gt_records
    )
    return ArmResult(records=records, ledger=ledger, timings_ms=dict(timings))


def _best_crop_detection(leg: LegRuntime, image: np.ndarray, face: GtFace, margin: float) -> Observation | None:
    """Detect on the GT crop with margin, then keep the detection with the highest IoU to the GT box.

    A detection with no overlap is not a match. This changes crop scale, context and landmarks together.
    """
    x, y, w, h = (float(v) for v in face.box)
    height, width = image.shape[0], image.shape[1]
    x0 = max(0, int(np.floor(x - margin * w)))
    y0 = max(0, int(np.floor(y - margin * h)))
    x1 = min(width, int(np.ceil(x + w + margin * w)))
    y1 = min(height, int(np.ceil(y + h + margin * h)))
    crop = image[y0:y1, x0:x1]
    best: Observation | None = None
    best_iou = 0.0
    offset = np.array([x0, y0], dtype=np.float64)
    for obs in leg.observe(crop):
        dx, dy, dw, dh = obs.detection.bbox_px
        overlap = iou_pixel_corner((dx + x0, dy + y0, dw, dh), face.box)
        if overlap > best_iou:
            best_iou = overlap
            shifted = DetectedFace(
                bbox_px=(dx + x0, dy + y0, dw, dh),
                landmarks_px=obs.detection.landmarks_px + offset,
                score=obs.detection.score,
            )
            best = Observation(detection=shifted, embedding=obs.embedding, stage=obs.stage)
    return best
