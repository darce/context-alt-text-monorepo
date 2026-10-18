"""FIRBENCH-1 S4 run materializer: one persisted run becomes clusters.json (diagnostics only).

Reads one private run directory's manifest.json, frame.json, scores.json and
legs/<leg_key>/cache.npz, and optionally one prior run. Each leg is one embedding space [EMB-01]
handed to the S4 core, which owns every metric, cut and projection. This module only binds the
persisted rows to the frame: GT identities and folds come from frame.json, the acceptance tau
comes from scores.json, and the production similarity comes from the manifest.

It never reads query pixels, templates, model loaders or the sealed-frame source, and it never
rescores or re-searches. Diagnostics condition on the stable subset of GT faces with usable cached
vectors, with explicit vector coverage against the full frame inventory. A leg with no eligible
embedded GT or an absent cache is named unavailable. Detector-only rows never become GT, and missing vectors
never shrink primary GT/outcome denominators or receive zero imputation.
"""

from __future__ import annotations

import json
import math
import os
import re
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from scripts.eval_harness import firbench_clusters as fcl
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_frames as frames
from scripts.eval_harness.firbench_legs import LegCache

CACHE_FORMAT = "firbench-cache/v1"
CLUSTERS_FILE = "clusters.json"
_CACHE_FILE = "cache.npz"
_METADATA_ARRAY = "metadata_json"
_VECTORS_ARRAY = "vectors"
_CACHE_KEYS = frozenset({"format", "leg_key", "rows"})
_ROW_KEYS = frozenset(
    {
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
)
_FRAME_BINDING = ("frame_id", "admissibility", "sealed", "source_sha256", "exhaustive")
_LEG_KEY = re.compile(r"^[A-Za-z0-9._+-]+(?:__[A-Za-z0-9._+-]+){4}$")
_NO_CACHE = "no cache.npz recorded for this leg"
_NO_TAU = "no acceptance tau recorded for this leg in scores.json"
_CHAINING = "no held-out verified pair evidence supplied"


@dataclass(frozen=True)
class DiagnosticConfig:
    """Fixed diagnostic choices, declared before outcomes. A None seed means the manifest gallery split seed.

    These shape pictures and companion statistics only. They never set the production similarity,
    the acceptance tau or any core threshold. ``production_parameters`` is scalar metadata.
    """

    linkage: str = "average"
    knn_k: int = 15
    histogram_bins: int = 20
    n_orders: int = 20
    umap_n_neighbors: int = 15
    umap_min_dist: float = 0.1
    order_seed: int | None = None
    projection_seed: int | None = None
    production_parameters: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True)
class _Frame:
    images: Mapping[str, frames.ImageUnit]
    faces_by_id: Mapping[str, frames.GtFace]
    fold_by_image: Mapping[str, int]

    @property
    def faces(self) -> tuple[frames.GtFace, ...]:
        return tuple(self.faces_by_id[face_id] for face_id in sorted(self.faces_by_id))


@dataclass(frozen=True)
class _Run:
    root: Path
    run_id: str
    leg_keys: tuple[str, ...]
    similarity_threshold: float | None
    gallery_seed: int
    frame: _Frame
    tau_results: Mapping[str, Mapping[str, Any]]


@dataclass(frozen=True)
class _LegRead:
    leg: fcl.LegInput | None
    reason: str | None
    vector_coverage: Mapping[str, Any]


@dataclass(frozen=True)
class _CacheRow:
    record_id: str
    image_id: str
    gt_face_id: str | None
    embedding_index: int | None


def _fail(message: str) -> fc.FrameContractError:
    return fc.FrameContractError(message)


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _fail(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _no_constant(name: str) -> object:
    raise _fail(f"non-finite JSON constant {name!r}")


def _strict_json(text: str, where: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=_no_constant)
    except ValueError as exc:
        raise _fail(f"{where} is not strict JSON: {exc}") from exc


def _child(root: Path, *parts: str) -> Path | None:
    """The regular path root/parts, or None when absent. Symlinks and escapes are refused."""
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise _fail(f"{current.name} is a symlink; run artifacts must be regular files and directories")
    if not current.exists():
        return None
    if not current.resolve().is_relative_to(root.resolve()):
        raise _fail(f"{current.name} resolves outside the run directory")
    return current


def _read_json(root: Path, name: str) -> Any:
    path = _child(root, name)
    if path is None:
        raise _fail(f"missing {name} in the run directory")
    if not path.is_file():
        raise _fail(f"{name} must be a regular file")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise _fail(f"cannot read {name}: {exc}") from exc
    return _strict_json(text, name)


def _enum(enum_cls: type, value: object, where: str) -> Any:
    try:
        return enum_cls(value)
    except ValueError as exc:
        raise _fail(f"{where} {value!r} is not a {enum_cls.__name__}") from exc


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(f"{where} must be a non-empty string")
    return value


def _finite(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise _fail(f"{where} must be a finite number")
    return float(value)


def _parse_leg_key(key: object) -> tuple[fc.LegKind, fc.Arm]:
    if not isinstance(key, str) or not _LEG_KEY.match(key):
        raise _fail(f"leg key {key!r} is not a safe five-part leg key")
    kind, arm, _space, opencv, ort = key.split("__")
    if not (opencv.startswith("cv") and ort.startswith("ort")):
        raise _fail(f"leg key {key!r} lacks its OpenCV and ORT tokens")
    return _enum(fc.LegKind, kind, f"leg key {key!r} kind"), _enum(fc.Arm, arm, f"leg key {key!r} arm")


def _leg_keys(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise _fail("manifest leg_keys must be a non-empty list")
    for key in value:
        _parse_leg_key(key)
    if len(set(value)) != len(value):
        raise _fail("manifest leg_keys repeat a key")
    return tuple(sorted(value))


def _gt_face(raw: Mapping[str, Any]) -> frames.GtFace:
    values = dict(raw)
    annotation = dict(values.pop("annotation"))
    annotation["visibility"] = frames.Visibility(**annotation["visibility"])
    values["annotation"] = frames.FaceAnnotation(**annotation)
    values["cohort"] = None if values["cohort"] is None else frames.Cohort(**values["cohort"])
    values["identity_status"] = fc.IdentityStatus(values["identity_status"])
    values["box"] = tuple(values["box"])
    return frames.GtFace(**values)


def _unique(rows: list[Mapping[str, Any]], key: str, value: str, where: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for row in rows:
        if row[key] in result:
            raise _fail(f"{where} repeats {key} {row[key]!r}")
        result[row[key]] = row[value]
    return result


def _parse_frame(payload: Any) -> _Frame:
    fc.validate_interchange("frame-v1", payload)
    images: dict[str, frames.ImageUnit] = {}
    for raw in payload["images"]:
        image = frames.ImageUnit(**raw)
        if image.image_id in images:
            raise _fail("frame.json repeats an image_id")
        images[image.image_id] = image
    faces_by_id: dict[str, frames.GtFace] = {}
    for raw in payload["faces"]:
        face = _gt_face(raw)
        if face.face_id in faces_by_id:
            raise _fail("frame.json repeats a face_id")
        if face.image_id not in images:
            raise _fail(f"GT face {face.face_id} names an image outside the frame")
        faces_by_id[face.face_id] = face
    psus = _unique(payload["psu_map"], "image_id", "psu_id", "frame psu_map")
    folds = _unique(payload["folds"], "psu_id", "fold", "frame folds")
    identities = _unique(payload["identity_folds"], "identity_id", "fold", "frame identity_folds")
    if set(psus) != set(images):
        raise _fail("frame psu_map must place every frame image in exactly one PSU")
    if psus != frames.build_psu_components(tuple(images.values()), tuple(faces_by_id.values())):
        raise _fail("persisted PSU partition differs from the frame's GT inventory")
    if set(psus.values()) != set(folds):
        raise _fail("frame folds must cover exactly the frame's PSUs")
    components = frames.identity_to_component(tuple(faces_by_id.values()), psus)
    if identities != {identity: folds[psu] for identity, psu in components.items()}:
        raise _fail("frame identity fold provenance contradicts the PSU folds")
    fold_by_image = {image_id: folds[psu] for image_id, psu in psus.items()}
    return _Frame(images=images, faces_by_id=faces_by_id, fold_by_image=fold_by_image)


def _load_run(root: Path) -> _Run:
    manifest = _read_json(root, "manifest.json")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("firbench"), dict):
        raise _fail("manifest.json must hold a firbench object")
    firbench = manifest["firbench"]
    leg_keys = _leg_keys(firbench.get("leg_keys"))
    frame_payload = _read_json(root, "frame.json")
    frame = _parse_frame(frame_payload)
    scores = _read_json(root, "scores.json")
    fc.validate_interchange("scores-v1", scores)
    run_id = _text(firbench.get("run_id"), "manifest run_id")
    fc._require_sha(firbench.get("decision_sha256"), "manifest decision_sha256")
    if firbench.get("frame") != {name: frame_payload[name] for name in _FRAME_BINDING}:
        raise _fail("manifest frame binding differs from frame.json")
    seeds = firbench.get("seeds")
    gallery_seed = seeds.get("gallery_split") if isinstance(seeds, dict) else None
    if isinstance(gallery_seed, bool) or not isinstance(gallery_seed, int) or not 0 <= gallery_seed < 2**32:
        raise _fail("manifest seeds.gallery_split must be an integer in [0, 2**32)")
    if scores["decision_sha256"] != firbench["decision_sha256"]:
        raise _fail("scores.json decision_sha256 differs from the manifest decision binding")
    if scores["frame_id"] != frame_payload["frame_id"] or scores["admissibility"] != frame_payload["admissibility"]:
        raise _fail("scores.json frame binding differs from frame.json")
    tau_results: dict[str, Mapping[str, Any]] = {}
    for leg in scores["legs"]:
        key = leg["leg_key"]
        if key not in leg_keys:
            raise _fail(f"scores.json holds leg {key} that the manifest did not declare")
        if key in tau_results:
            raise _fail(f"scores.json repeats leg {key}")
        tau_results[key] = leg["tau"]
    return _Run(
        root=root,
        run_id=run_id,
        leg_keys=leg_keys,
        similarity_threshold=firbench.get("similarity_threshold"),
        gallery_seed=gallery_seed,
        frame=frame,
        tau_results=tau_results,
    )


def _read_vectors(array: np.ndarray, key: str) -> np.ndarray:
    if array.dtype != np.float32:
        raise _fail(f"{key}: vectors must be float32")
    if array.ndim != 2:
        raise _fail(f"{key}: vectors must be two-dimensional")
    if array.shape[0] == 0 and array.shape != (0, 0):
        raise _fail(f"{key}: a cache without embeddings must hold vectors of shape (0, 0)")
    if array.shape[0] and array.shape[1] < 1:
        raise _fail(f"{key}: vector rows need at least one dimension")
    if not np.isfinite(array).all():
        raise _fail(f"{key}: vectors must be finite")
    if array.shape[0] and np.any(np.linalg.norm(array, axis=1) == 0):
        raise _fail(f"{key}: a zero vector row cannot define cosine similarity")
    return array


def _check_geometry(raw: Mapping[str, Any], arm: fc.Arm, key: str, record_id: str) -> None:
    box, landmarks, score = raw["bbox_px"], raw["landmarks_px"], raw["detector_score"]
    if arm is fc.Arm.cached_yunet_landmark_replay and (box is not None or score is not None):
        raise _fail(f"{key}: replay row {record_id} carries a box or detector score; replay has neither")
    if raw["stage"] == fc.SearchStage.missed.value and (box is not None or landmarks is not None or score is not None):
        raise _fail(f"{key}: row {record_id} is missed yet carries geometry")
    if box is not None:
        if not isinstance(box, list) or len(box) != 4:
            raise _fail(f"{key}: row {record_id} bbox_px must be [x, y, w, h]")
        _x, _y, width, height = (_finite(value, f"{key}: row {record_id} bbox_px") for value in box)
        if width < 0 or height < 0:
            raise _fail(f"{key}: row {record_id} bbox_px needs non-negative width and height")
    if landmarks is not None:
        if not isinstance(landmarks, list) or len(landmarks) != 5:
            raise _fail(f"{key}: row {record_id} landmarks_px must hold five points")
        for point in landmarks:
            if not isinstance(point, list) or len(point) != 2:
                raise _fail(f"{key}: row {record_id} landmarks_px must hold [x, y] points")
            for value in point:
                _finite(value, f"{key}: row {record_id} landmarks_px")
    if score is not None:
        _finite(score, f"{key}: row {record_id} detector_score")


def _read_cache(path: Path, key: str, frame: _Frame) -> tuple[list[_CacheRow], np.ndarray]:
    arm = _parse_leg_key(key)[1]
    try:
        arrays = LegCache(path, leg_key=key).load()
    except (fc.RuntimeMismatchError, OSError, ValueError, EOFError, KeyError, zipfile.BadZipFile) as exc:
        raise _fail(f"{key}: cache.npz is unreadable or holds another leg: {exc}") from exc
    if arrays is None or set(arrays) != {_METADATA_ARRAY, _VECTORS_ARRAY}:
        raise _fail(f"{key}: cache.npz must hold exactly {_METADATA_ARRAY} and {_VECTORS_ARRAY}")
    metadata_array = arrays[_METADATA_ARRAY]
    if metadata_array.shape != () or metadata_array.dtype.kind != "U":
        raise _fail(f"{key}: metadata_json must be one unicode scalar")
    metadata = _strict_json(str(metadata_array.item()), f"{key} metadata_json")
    if not isinstance(metadata, dict) or set(metadata) != _CACHE_KEYS:
        raise _fail(f"{key}: metadata_json must hold exactly {sorted(_CACHE_KEYS)}")
    if metadata["format"] != CACHE_FORMAT or metadata["leg_key"] != key:
        raise _fail(f"{key}: metadata_json names another format or leg")
    if not isinstance(metadata["rows"], list):
        raise _fail(f"{key}: metadata_json rows must be an array")
    vectors = _read_vectors(arrays[_VECTORS_ARRAY], key)
    rows: list[_CacheRow] = []
    seen_records: set[str] = set()
    seen_gt: set[str] = set()
    indices: list[int] = []
    previous: tuple[str, str] | None = None
    for raw in metadata["rows"]:
        if not isinstance(raw, dict) or set(raw) != _ROW_KEYS:
            raise _fail(f"{key}: every row holds exactly the frozen row keys")
        record_id = _text(raw["record_id"], f"{key}: record_id")
        if record_id in seen_records:
            raise _fail(f"{key}: duplicate record_id {record_id!r}")
        seen_records.add(record_id)
        image_id = _text(raw["image_id"], f"{key}: image_id")
        image = frame.images.get(image_id)
        if image is None:
            raise _fail(f"{key}: row {record_id} names an image outside the frame")
        if raw["image_sha256"] != image.sha256:
            raise _fail(f"{key}: row {record_id} image_sha256 differs from the frame")
        if previous is not None and (image_id, record_id) < previous:
            raise _fail(f"{key}: rows must be sorted by image_id then record_id")
        previous = (image_id, record_id)
        gt_face_id = raw["gt_face_id"]
        if gt_face_id is not None:
            face = frame.faces_by_id.get(gt_face_id) if isinstance(gt_face_id, str) else None
            if face is None:
                raise _fail(f"{key}: row {record_id} names a GT face outside the frame")
            if face.image_id != image_id:
                raise _fail(f"{key}: GT face {gt_face_id} is bound to {face.image_id}, not {image_id}")
            if gt_face_id in seen_gt:
                raise _fail(f"{key}: GT face {gt_face_id} has two rows")
            seen_gt.add(gt_face_id)
        stage = raw["stage"]
        if stage is not None:
            _enum(fc.SearchStage, stage, f"{key}: row {record_id} stage")
        availability = _enum(fc.ArmStatus, raw["arm_availability"], f"{key}: row {record_id} arm_availability")
        index = raw["embedding_index"]
        if index is not None:
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < vectors.shape[0]:
                raise _fail(f"{key}: row {record_id} embedding_index is outside the vector store")
            if stage != fc.SearchStage.embedded.value or availability is not fc.ArmStatus.available:
                raise _fail(f"{key}: row {record_id} holds an embedding but is not embedded and available")
            indices.append(index)
        elif stage == fc.SearchStage.embedded.value:
            raise _fail(f"{key}: row {record_id} claims an embedded stage without an embedding")
        _check_geometry(raw, arm, key, record_id)
        rows.append(_CacheRow(record_id, image_id, gt_face_id, index))
    missing = sorted(set(frame.faces_by_id) - seen_gt)
    if missing:
        raise _fail(f"{key}: cache holds no row for GT face {missing[0]}")
    if len(set(indices)) != len(indices) or sorted(indices) != list(range(vectors.shape[0])):
        raise _fail(f"{key}: every vector row must be referenced by exactly one embedding_index")
    return rows, vectors


def _read_leg(run: _Run, key: str) -> _LegRead:
    kind, _arm = _parse_leg_key(key)
    faces = run.frame.faces
    coverage = {
        "label": "diagnostics conditional on available GT vectors",
        "conditional": True,
        "n_gt_faces": len(faces),
        "n_named_gt_faces": sum(face.identity_status is fc.IdentityStatus.named for face in faces),
        "n_embedded_gt_faces": None,
        "n_missing_gt_faces": None,
        "n_embedded_named_faces": None,
        "n_detector_only_rows": None,
    }
    path = _child(run.root, "legs", key, _CACHE_FILE)
    if path is None:
        return _LegRead(None, _NO_CACHE, coverage)
    if not path.is_file():
        raise _fail(f"{key}: cache.npz must be a regular file")
    rows, vectors = _read_cache(path, key, run.frame)
    embedding_of: dict[str, int] = {
        row.gt_face_id: row.embedding_index
        for row in rows
        if row.gt_face_id is not None and row.embedding_index is not None
    }
    embedded = [face for face in faces if face.face_id in embedding_of]
    coverage.update(
        n_embedded_gt_faces=len(embedded),
        n_missing_gt_faces=len(faces) - len(embedded),
        n_embedded_named_faces=sum(face.identity_status is fc.IdentityStatus.named for face in embedded),
        n_detector_only_rows=sum(row.gt_face_id is None for row in rows),
    )
    if not faces:
        return _LegRead(None, "the frame holds no GT faces", coverage)
    if not embedded:
        return _LegRead(None, "no embedded GT face in this leg", coverage)
    leg_faces = tuple(
        fcl.LegFace.from_gt_face(face, fold=run.frame.fold_by_image[face.image_id], verification_ref=None)
        for face in embedded
    )
    leg = fcl.LegInput(
        leg_key=key,
        leg_kind=kind,
        run_id=run.run_id,
        faces=leg_faces,
        vectors=vectors[[embedding_of[face.face_id] for face in embedded]],
        chaining=None,
    )
    return _LegRead(leg, None, coverage)


def _acceptance(run: _Run, key: str) -> tuple[float | None, fcl.Evidence]:
    result = run.tau_results.get(key)
    if result is None:
        return None, fcl.unavailable(_NO_TAU)
    if result["status"] != "available":
        return None, fcl.unavailable(result["reason"] or _NO_TAU)
    tau = result["data"]["value"]
    return tau, fcl.available({"tau": tau, "distance": 1.0 - tau, "label": fcl.TAU_LABEL})


def _leg_config(diagnostic: DiagnosticConfig, run: _Run, tau: float | None) -> fcl.ClusterRunConfig:
    seed = run.gallery_seed
    return fcl.ClusterRunConfig(
        similarity_threshold=run.similarity_threshold,
        linkage=diagnostic.linkage,
        knn_k=diagnostic.knn_k,
        histogram_bins=diagnostic.histogram_bins,
        n_orders=diagnostic.n_orders,
        order_seed=seed if diagnostic.order_seed is None else diagnostic.order_seed,
        projection_seed=seed if diagnostic.projection_seed is None else diagnostic.projection_seed,
        umap_n_neighbors=diagnostic.umap_n_neighbors,
        umap_min_dist=diagnostic.umap_min_dist,
        acceptance_tau=tau,
        production_parameters=diagnostic.production_parameters,
    )


def _config_json(config: fcl.ClusterRunConfig) -> dict[str, Any]:
    threshold = config.similarity_threshold
    return {
        "similarity_threshold": threshold,
        "metric": "cosine",
        "linkage": config.linkage,
        "production_algorithm": "hdbscan",
        "cluster_selection_epsilon": None if threshold is None else math.sqrt(2.0 * (1.0 - threshold)),
        "production_parameters": [{"name": name, "value": value} for name, value in config.production_parameters],
    }


def _unavailable_entry(
    key: str, config: fcl.ClusterRunConfig, reason: str, tau_evidence: fcl.Evidence
) -> dict[str, Any]:
    """A schema-complete leg whose every evidence state is explicitly unavailable, with the reason."""
    threshold = config.similarity_threshold

    def unavailable() -> dict[str, Any]:
        return fcl.unavailable(reason).to_json()

    def projection(name: str, method: str, parameters: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": name,
            "method": method,
            "n_components": 2,
            "seed": config.projection_seed,
            "diagnostic_only": True,
            "caption": fcl.PROJECTION_CAPTION,
            "parameters": parameters,
            "versions": [],
            "result": unavailable(),
        }

    return {
        "leg_key": key,
        "config": _config_json(config),
        # clusters-v1 requires a present production s to carry a cut caption, distance and label array.
        # With no labelled faces the array is empty; the partition evidence names why it is unavailable.
        "dendrogram_cut": {
            "distance": None if threshold is None else 1.0 - threshold,
            "caption": fcl.UNCUT_CAPTION if threshold is None else fcl.CUT_CAPTION,
            "labels": None if threshold is None else [],
        },
        "acceptance_tau_reference": tau_evidence.to_json(),
        "partition_metrics": unavailable(),
        "labels": unavailable(),
        "order_stability": unavailable(),
        "chaining": fcl.not_evaluated(_CHAINING).to_json(),
        "mutual_knn": unavailable(),
        "neighbours": unavailable(),
        "dendrogram": unavailable(),
        "pca_spectrum": unavailable(),
        "histograms": [{"kind": kind, "result": unavailable()} for kind in fcl.HISTOGRAM_KINDS],
        "companions": {"knn_jaccard": unavailable(), "linear_cka": unavailable()},
        "projections": [
            projection(
                "umap-2d",
                "umap",
                {"n_neighbors": config.umap_n_neighbors, "min_dist": float(config.umap_min_dist)},
            ),
            projection("pca-2d", "pca", {"n_neighbors": None, "min_dist": None}),
        ],
    }


def _prior_leg(prior: _Run | None, key: str) -> tuple[fcl.LegInput | None, str | None]:
    """The prior run's leg for companions. A prior that exists but cannot supply the leg is a named reason."""
    if prior is None or key not in prior.leg_keys:
        return None, None
    read = _read_leg(prior, key)
    if read.leg is None:
        return None, f"prior run {prior.run_id} holds no usable leg input: {read.reason}"
    return read.leg, None


def _leg_entry(run: _Run, prior: _Run | None, key: str, diagnostic: DiagnosticConfig) -> dict[str, Any]:
    tau, tau_evidence = _acceptance(run, key)
    config = _leg_config(diagnostic, run, tau)
    read = _read_leg(run, key)
    if read.leg is None:
        entry = _unavailable_entry(key, config, read.reason or _NO_CACHE, tau_evidence)
        entry["vector_coverage"] = dict(read.vector_coverage)
        return entry
    prior_leg, prior_reason = _prior_leg(prior, key)
    entry = fcl.build_leg_diagnostics(read.leg, config=config, prior=prior_leg)
    entry["vector_coverage"] = dict(read.vector_coverage)
    if prior_reason is not None:
        reason = fcl.unavailable(prior_reason).to_json()
        entry["companions"] = {"knn_jaccard": reason, "linear_cka": reason}
    if tau is None:
        entry["acceptance_tau_reference"] = tau_evidence.to_json()
    return entry


def _private_run_context(run_dir: str | os.PathLike[str]) -> tuple[Path, Path]:
    """Bind the lexical run path to its actual repository, including temporary repositories.

    Resolve only after finding the intended benchmarks/private boundary: resolving first
    would erase a redirected private directory or a traversing caller path.
    """
    candidate = Path(run_dir)
    if ".." in candidate.parts:
        raise fc.NonPrivateOutputError("private run paths must not contain traversal segments")
    root = candidate.absolute()
    try:
        index = root.parts.index("benchmarks")
    except ValueError as exc:
        raise fc.NonPrivateOutputError("run directory must lie under benchmarks/private/") from exc
    if root.parts[index + 1 : index + 2] != ("private",):
        raise fc.NonPrivateOutputError("run directory must lie under benchmarks/private/")
    repo = Path(*root.parts[:index])
    for component in (root, *root.parents):
        if component.is_symlink():
            raise fc.NonPrivateOutputError("private run paths must not contain symlinks or redirects")
    fc.require_private_output_path(root, repo_root=repo)
    target = root / CLUSTERS_FILE
    fc.require_private_output_path(target, repo_root=repo)
    if target.is_symlink():
        raise fc.NonPrivateOutputError("clusters.json must not be a symlink")
    return root, repo


def materialize_clusters(
    run_dir: str | os.PathLike[str],
    *,
    config: DiagnosticConfig | None = None,
    prior_run_dir: str | os.PathLike[str] | None = None,
) -> Path:
    """Materialize or verify the exact canonical ``clusters.json`` for one private run.

    Every actual input and the expected payload are validated before accepting an existing
    artifact. Conflicting bytes are never overwritten; publication is atomic and exclusive.
    """
    diagnostic = DiagnosticConfig() if config is None else config
    if not isinstance(diagnostic, DiagnosticConfig):
        raise _fail("config must be a DiagnosticConfig or None")
    root, repo = _private_run_context(run_dir)
    target = root / CLUSTERS_FILE
    run = _load_run(root)
    prior = None
    if prior_run_dir is not None:
        prior_root, _prior_repo = _private_run_context(prior_run_dir)
        if prior_root == root:
            raise _fail("prior run must be a different run directory")
        prior = _load_run(prior_root)
    entries = [_leg_entry(run, prior, key, diagnostic) for key in run.leg_keys]
    payload = fcl.build_clusters_payload(entries)
    try:
        expected = (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n").encode(
            "utf-8"
        )
    except (TypeError, ValueError) as exc:
        raise _fail(f"clusters payload is not finite JSON: {exc}") from exc

    def existing_matches() -> bool:
        path = _child(root, CLUSTERS_FILE)
        if path is None:
            return False
        if not path.is_file() or path.read_bytes() != expected:
            raise _fail(f"{CLUSTERS_FILE} already exists and differs from the expected canonical bytes")
        return True

    staging = None
    try:
        if existing_matches():
            return target
        temporary = fc.require_private_output_path(
            target.with_name(f".{CLUSTERS_FILE}.{os.urandom(8).hex()}.tmp"), repo_root=repo
        )
        with temporary.open("xb") as handle:
            staging = temporary
            handle.write(expected)
        # Recheck the lexical boundary before publication, then link without replacement.
        _private_run_context(root)
        try:
            os.link(staging, target)
        except FileExistsError:
            if not existing_matches():
                raise _fail(f"{CLUSTERS_FILE} changed during publication")
    except OSError as exc:
        raise _fail(f"cannot materialize {CLUSTERS_FILE} at {target}: {exc}") from exc
    finally:
        if staging is not None:
            staging.unlink()
    return target
