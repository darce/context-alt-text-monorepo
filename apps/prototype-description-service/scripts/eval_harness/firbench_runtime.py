"""Lazy offline S6a adapter for the accepted S1/S2/S3 producers.

Private binding: ``benchmarks/private/firbench/inputs/<frame_id>.json``.
``firbench-inputs/v1`` has the exact required fields in :class:`InputBinding`;
``crop_margin`` (default 0.0), ``identity_folds`` and ``label_evidence`` are optional.
Paths are repository-relative private paths. Query source kind is
``population_draft`` or ``golden_manifest``; bytes bind FrameSpec.source_sha256.
The separate ``firbench-templates/v1`` document has ``schema`` and ``templates``
(a nonempty list of TemplateRow). Its bytes bind GalleryLineage.templates_sha256.
Identity IDs are S1 pseudonyms, never predictions or names. Boxes are pixel xywh.
A full optional identity_folds map must agree with canonical S1 query folds;
otherwise template-only identities use SHA256(seed + identity) modulo k before
outcomes. Every query fold splits only its identity-eligible roster using the
actual gallery_split producer, fixed G1 direction. No sample fallback/download.

Real tier-a source annotations additionally require label_evidence =
{export_path, queue_path, gold_path}; S7 requalifies the linked QC and observation
before conversion and checks the corresponding source annotation/geometry/hash.
No reference string alone confers evidence eligibility.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, NotRequired, TypedDict

import numpy as np

from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_frames as ff
from scripts.eval_harness import firbench_legs as fl
from scripts.eval_harness import gallery_split


class DocumentBinding(TypedDict):
    path: str
    sha256: str


class SourceBinding(DocumentBinding):
    kind: str


class QueryImageBinding(TypedDict):
    path: str
    media_ids: list[int]


class InputBinding(TypedDict):
    schema: str
    query_source: SourceBinding
    gallery_templates: DocumentBinding
    query_images: dict[str, QueryImageBinding]
    identity_folds: NotRequired[dict[str, int]]
    crop_margin: NotRequired[float]
    label_evidence: NotRequired[dict[str, str]]


class TemplateRow(TypedDict):
    template_id: str
    identity_id: str
    media_ids: list[int]
    path: str
    sha256: str
    box: list[float]
    occluders: list[str] | None


def _json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_bytes(), object_pairs_hook=fc._reject_duplicate_keys, parse_constant=fc._reject_non_finite
        )
    except (OSError, ValueError, UnicodeError) as exc:
        raise fc.FrameContractError(f"cannot read input binding/document {path.name}: {exc}") from exc


def _private(root: Path, value: str) -> Path:
    if not isinstance(value, str) or Path(value).is_absolute():
        raise fc.FrameContractError("input binding paths must be repository-relative private paths")
    return fc.require_private_output_path(root / value, repo_root=root)


def _bytes(path: Path, sha: str) -> bytes:
    fc._require_sha(sha, "input sha256")
    try:
        value = path.read_bytes()
    except OSError as exc:
        raise fc.FrameContractError(f"missing input asset {path.name}") from exc
    if hashlib.sha256(value).hexdigest() != sha:
        raise fc.FrameContractError(f"input sha256 mismatch: {path.name}")
    return value


def _pixels(path: Path, sha: str) -> np.ndarray:
    import cv2

    value = cv2.imdecode(np.frombuffer(_bytes(path, sha), dtype=np.uint8), cv2.IMREAD_COLOR)
    if value is None:
        raise fc.FrameContractError(f"cannot decode input asset {path.name}")
    return value


def _media_inventory(values):
    if (
        not isinstance(values, list)
        or not values
        or any(type(i) is not int or i < 0 for i in values)
        or len(set(values)) != len(values)
    ):
        raise fc.FrameContractError("media_ids must explicitly list unique nonnegative media IDs")


def _in_image(box, pixels):
    x, y, width, height = ff._box_geometry(box, "GT/template box")
    if x < 0 or y < 0 or x + width > pixels.shape[1] or y + height > pixels.shape[0]:
        raise fc.FrameContractError("GT/template box is outside its bound image")


def scorer_sha256() -> str:
    """One ordered source identity for both core statistics and persisted IO assembly."""
    base = Path(__file__).parent
    digest = hashlib.sha256()
    for name in ("firbench_score.py", "firbench_score_io.py"):
        digest.update(name.encode() + b"\0" + (base / name).read_bytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class PreparedRun:
    """Validated declaration plus a callback that may produce query outcomes only later."""

    frame: ff.Frame
    gallery_membership: tuple[dict[str, Any], ...]
    gallery_hash_basis: str
    run_legs: Any
    crop_margin: float
    canary_permutations: dict[int, dict[str, str]]


def _qualified_source(path: Path, binding: InputBinding, root: Path) -> None:
    """Check original rows before S1's annotation conversion can discard evidence."""
    raw = _json(path)
    tier_a = [r for r in raw.get("faces", []) if r.get("annotation", {}).get("annotation_tier") == "a"]
    if not tier_a:
        return
    from scripts.eval_harness import fir_occ_labels as labels

    evidence = binding.get("label_evidence")
    if not isinstance(evidence, dict) or set(evidence) != {"export_path", "queue_path", "gold_path"}:
        raise fc.FrameContractError("real tier-a GT requires qualified S7 QC/observation label_evidence")
    export = labels.load_label_export(_private(root, evidence["export_path"]))
    queue = labels.load_queue(_private(root, evidence["queue_path"]), _private(root, evidence["gold_path"]))
    qualified = labels.to_face_instances(export, queue)
    labels.require_real_analysis_rows(qualified)
    images = {r["image_id"]: r["sha256"] for r in raw["images"]}
    for face in tier_a:
        matches = [
            r
            for r in qualified
            if r["image_id"] == face["image_id"]
            and r.get("box") == face["box"]
            and r.get("image_sha256") == images[face["image_id"]]
            and r.get("identity_status") == face["identity_status"]
            and r.get("annotation") == face["annotation"]
        ]
        if len(matches) != 1:
            raise fc.FrameContractError("tier-a GT does not match qualified S7 annotation evidence")


def _native(kind: fc.LegKind, settings: Any) -> fl.LegRuntime:
    """Factory uses actual settings locations and accepted independent pinned factory."""
    if kind in (fc.LegKind.sface, fc.LegKind.auraface):
        from recognition.infrastructure.face_pipeline.provenance import ModelIntegrityError, ModelMissingError

        try:
            return fl.load_pinned_face_pipeline_leg(
                kind,
                models_dir=settings.face_pipeline.resolved_models_dir,
                embedder_models_dir=settings.auraface_models_dir if kind is fc.LegKind.auraface else None,
            )
        except (OSError, ValueError, RuntimeError, ImportError, ModelIntegrityError, ModelMissingError) as exc:
            raise fc.FrameContractError(f"{kind.value} pinned runtime/assets unavailable: {exc}") from exc
    if kind is not fc.LegKind.insightface:
        raise fc.FrameContractError(f"unsupported native leg {kind}")
    return _load_buffalo_leg(settings)


def _load_buffalo_leg(settings):
    """Offline fused model factory; optional dependencies keep their honest refusal."""
    try:
        from scripts.eval_harness import buffalo_bench as bench

        bench._require_eval_bench()  # Also guard a previously cached module import.
        bench._load_insightface()
        if settings.insightface.model_name != "buffalo_l":
            raise fc.FrameContractError("FIRBENCH requires the offline buffalo_l bundle")
        factory_root = Path(bench._resolve_insightface_root() or Path.home() / ".insightface").resolve()
        if factory_root != settings.insightface.cache_dir.resolve():
            raise fc.FrameContractError("buffalo factory/settings model-root mismatch; downloads disabled")
        bundle = settings.insightface.model_cache_dir / "buffalo_l"
        # FaceAnalysis otherwise auto-acquires missing bundles. Require the full offline bundle.
        names = ("1k3d68.onnx", "2d106det.onnx", "det_10g.onnx", "genderage.onnx", "w600k_r50.onnx")
        digest = hashlib.sha256()
        for name in names:
            target = bundle / name
            if not target.is_file():
                raise fc.FrameContractError(f"missing offline buffalo_l asset {name}; downloads disabled")
            digest.update(name.encode() + b"\0" + target.read_bytes())
        from recognition.infrastructure.face_pipeline.provenance import numeric_runtime_fingerprint

        runtime = numeric_runtime_fingerprint()
        return fl.BuffaloLeg(
            weights_sha256=digest.hexdigest(),
            opencv_version=runtime.opencv_version,
            ort_version=runtime.onnxruntime_version,
        )
    except (ImportError, RuntimeError, OSError) as exc:
        raise fc.FrameContractError(f"insightface optional bench runtime unavailable: {exc}") from exc


class _Adapter:
    def __init__(self, settings: Any):
        self.settings = settings
        self.models: dict[fc.LegKind, fl.LegRuntime] = {}

    def model(self, kind):
        if kind not in self.models:
            self.models[kind] = _native(kind, self.settings)
        return self.models[kind]

    def leg_keys(self, *, legs, arms):
        kinds = [k for k in legs if k is not fc.LegKind.canary]
        if len(kinds) != len(set(kinds)) or len(arms) != len(set(arms)):
            raise fc.FrameContractError("duplicate legs or arms")
        if fc.Arm.native not in arms or not kinds:
            raise fc.FrameContractError("default runtime requires native arms and a native leg")
        keys = [self.model(k).leg_id(a).key() for k in kinds for a in arms]
        if fc.LegKind.canary in legs:
            base_kind = fc.LegKind.sface if fc.LegKind.sface in kinds else kinds[0]
            base = self.model(base_kind).leg_id(fc.Arm.native)
            keys.extend(
                fc.LegId(fc.LegKind.canary, a, base.space_fingerprint, base.opencv_version, base.ort_version).key()
                for a in arms
            )
        return tuple(sorted(keys))

    def prepare_run(self, **kwargs):
        try:
            return self._prepare_run(**kwargs)
        except fc.FirBenchError:
            raise
        except (KeyError, TypeError, ValueError, OSError, ImportError, RuntimeError, AssertionError) as exc:
            raise fc.FrameContractError(f"invalid runtime input binding/GT/template context: {exc}") from exc

    def _prepare_run(self, *, frame, legs, arms, subset, subset_seed, decision, out_dir, repo_root):
        root = Path(repo_root)
        binding_path = root / "benchmarks/private/firbench/inputs" / f"{frame.frame_id}.json"
        binding = _json(_private(root, binding_path.relative_to(root).as_posix()))
        required = {"schema", "query_source", "gallery_templates", "query_images"}
        if (
            not isinstance(binding, dict)
            or not required <= set(binding)
            or set(binding) - required - {"crop_margin", "identity_folds", "label_evidence"}
            or binding["schema"] != "firbench-inputs/v1"
        ):
            raise fc.FrameContractError("invalid firbench-inputs/v1 binding")
        if subset is not None:
            raise fc.FrameContractError(
                "default runtime requires the complete declared frame; subset is diagnostic-only"
            )
        if frame.source_sha256 is None or decision.gallery_lineage.templates_sha256 is None:
            raise fc.FrameContractError("source_sha256 and templates_sha256 must be declared before private reads")
        if frame.exhaustive is not True:
            raise fc.FrameContractError("exhaustive GT is required")
        k, seed = decision.fold_protocol.k, decision.fold_protocol.seed
        if type(k) is not int or type(seed) is not int or decision.planning_icc is None:
            raise fc.FrameContractError("declared folds and planning_icc are required")
        required_legs = set(decision.primary.comparison) | {leg for h in decision.hypotheses for leg in h.legs}
        if not required_legs <= set(legs):
            raise fc.FrameContractError(
                "missing native hypothesis legs: " + ",".join(sorted(leg.value for leg in required_legs - set(legs)))
            )
        source_binding, template_binding = binding["query_source"], binding["gallery_templates"]
        for item, fields, expected in (
            (source_binding, {"kind", "path", "sha256"}, frame.source_sha256),
            (template_binding, {"path", "sha256"}, decision.gallery_lineage.templates_sha256),
        ):
            if not isinstance(item, dict) or set(item) != fields or item["sha256"] != expected:
                raise fc.FrameContractError("source/template binding sha256 differs from decision")
            _bytes(_private(root, item["path"]), expected)
        source_path = _private(root, source_binding["path"])
        kind = source_binding["kind"]
        if kind == "population_draft":
            _qualified_source(source_path, binding, root)
            source = ff.load_population_draft(source_path)
        elif kind == "golden_manifest":
            raw_golden = _json(source_path)
            if any(
                box.get("annotation_tier", box.get("annotation", {}).get("annotation_tier")) == "a"
                for entry in raw_golden.get("entries", [])
                for box in entry.get("face_boxes", [])
            ):
                raise fc.FrameContractError("tier-a golden rows require population source with qualified S7 evidence")
            if raw_golden.get("annotation_mode") != "exhaustive":
                raise fc.FrameContractError("golden source requires document-level exhaustive annotation_mode")
            source = ff.load_golden_manifest(source_path)
        else:
            raise fc.FrameContractError("unknown query source kind in binding")
        if any(face.identity_id is not None and not face.identity_id.startswith("id-") for face in source.faces):
            raise fc.FrameContractError("query source requires S1 pseudonymous identity IDs")
        doc = _json(_private(root, template_binding["path"]))
        fields = set(TemplateRow.__required_keys__)
        if not isinstance(doc, dict) or set(doc) != {"schema", "templates"} or doc["schema"] != "firbench-templates/v1":
            raise fc.FrameContractError("invalid firbench-templates/v1 document")
        rows = doc["templates"]
        if not isinstance(rows, list) or not rows:
            raise fc.FrameContractError("missing gallery templates")
        if any(not isinstance(r, dict) or set(r) != fields for r in rows):
            raise fc.FrameContractError("invalid template row fields")
        for row in rows:
            for key in ("identity_id", "template_id"):
                fc._require_safe_token(row[key], key)
            if not row["identity_id"].startswith("id-"):
                raise fc.FrameContractError("templates require S1 pseudonymous identity IDs")
            ff._box_geometry(row["box"], "template box")
            ff.FaceAnnotation(occluders=None if row["occluders"] is None else tuple(row["occluders"]))
            _media_inventory(row["media_ids"])
        if len({r["template_id"] for r in rows}) != len(rows):
            raise fc.FrameContractError("duplicate template_id")
        image_paths = binding["query_images"]
        if not isinstance(image_paths, dict) or set(image_paths) != {i.image_id for i in source.images}:
            raise fc.FrameContractError("query_images binding must cover exactly the complete frame")
        for image in source.images:
            media = image_paths[image.image_id]
            if not isinstance(media, dict) or set(media) != {"path", "media_ids"}:
                raise fc.FrameContractError("query_images rows require path and media_ids")
            _media_inventory(media["media_ids"])
            if image.image_id.isdecimal() and int(image.image_id) not in media["media_ids"]:
                raise fc.FrameContractError("query media inventory contradicts source media ID")
        query_paths = {_private(root, p["path"]) for p in image_paths.values()}
        template_paths = {_private(root, r["path"]) for r in rows}
        query_hashes = {i.sha256 for i in source.images}
        if query_paths & template_paths or query_hashes & {r["sha256"] for r in rows}:
            raise fc.FrameContractError("query/enrollment media or hash inventory overlap")
        query_media = {mid for media in image_paths.values() for mid in media["media_ids"]}
        if query_media & {m for r in rows for m in r["media_ids"]}:
            raise fc.FrameContractError("query/enrollment media inventory overlap")
        components = ff.build_psu_components(source.images, source.faces)
        identities = ff.identity_to_component(source.faces, components)
        folds = ff.identity_disjoint_folds(components, identities, k=k, seed=seed)
        identity_folds = {i: folds[p] for i, p in identities.items()}
        all_ids = set(identity_folds) | {r["identity_id"] for r in rows}
        declared = binding.get("identity_folds")
        if declared is not None:
            if (
                not isinstance(declared, dict)
                or set(declared) != all_ids
                or any(type(f) is not int or not 0 <= f < k for f in declared.values())
                or any(declared[i] != f for i, f in identity_folds.items())
            ):
                raise fc.FrameContractError("contradictory or incomplete identity_folds binding")
            identity_folds = dict(declared)
        else:
            for identity in sorted(all_ids - set(identity_folds)):
                identity_folds[identity] = (
                    int.from_bytes(hashlib.sha256(f"{seed}/{identity}".encode()).digest()[:4], "big") % k
                )
        # A shared enrollment medium cannot bridge fit/test identity folds.
        template_media_folds = {}
        for row in rows:
            fold = identity_folds[row["identity_id"]]
            media_keys = [("media", mid) for mid in row["media_ids"]]
            media_keys += [("path", _private(root, row["path"])), ("sha", row["sha256"])]
            for media_key in media_keys:
                if template_media_folds.setdefault(media_key, fold) != fold:
                    raise fc.FrameContractError("enrollment media contradicts identity fold provenance")
        by_id = {r["template_id"]: r for r in rows}
        memberships = {}
        for fold in range(k):
            roster = defaultdict(list)
            for r in rows:
                if identity_folds[r["identity_id"]] == fold:
                    roster[r["identity_id"]].append(
                        gallery_split.Template(r["template_id"], r["identity_id"], tuple(r["media_ids"]))
                    )
            try:
                memberships[fold] = gallery_split.build_disjoint_galleries(
                    templates_by_subject=roster, seed=decision.gallery_lineage.split_seed
                ).g1
            except ValueError as exc:
                raise fc.FrameContractError(f"fold {fold} eligible template roster refused: {exc}") from exc
        # Each private media asset is decoded once and kept only in this attempt's RAM.
        query_pixels = {}
        pixels = {}
        for image in source.images:
            key = (_private(root, image_paths[image.image_id]["path"]), image.sha256)
            if key not in query_pixels:
                query_pixels[key] = _pixels(*key)
            pixels[image.image_id] = query_pixels[key]
        template_pixels = {}
        for r in rows:
            key = (_private(root, r["path"]), r["sha256"])
            if key not in template_pixels:
                template_pixels[key] = _pixels(*key)
        for face in source.faces:
            _in_image(face.box, pixels[face.image_id])
        for row in rows:
            _in_image(row["box"], template_pixels[_private(root, row["path"]), row["sha256"]])
        margin = binding.get("crop_margin", 0.0)
        if isinstance(margin, bool) or not isinstance(margin, (int, float)) or not math.isfinite(margin) or margin < 0:
            raise fc.FrameContractError("crop_margin must be finite and nonnegative")
        models = {kind: self.model(kind) for kind in legs if kind is not fc.LegKind.canary}
        galleries, registry = {}, []
        for kind, model in models.items():
            vectors = {}
            template_observations = {}
            for template_id, r in by_id.items():
                image = template_pixels[_private(root, r["path"]), r["sha256"]]
                box = r["box"]
                media_key = (_private(root, r["path"]), r["sha256"])
                if media_key not in template_observations:
                    template_observations[media_key] = model.observe(image)
                observations = [o for o in template_observations[media_key] if o.embedding is not None]
                from scripts.eval_harness.face_assignment import iou_pixel_corner

                matches = [o for o in observations if iou_pixel_corner(o.detection.bbox_px, box) >= 0.5]
                if len(matches) != 1:
                    raise fc.FrameContractError(
                        f"template {template_id}: requires exactly one spatially matched embedding"
                    )
                vectors[template_id] = matches[0].embedding
            for fold, membership in memberships.items():
                gallery = fl.Gallery.enrol({i: [vectors[t.template_id]] for i, t in membership.items()})
                galleries[kind, fold] = gallery
        if fc.LegKind.canary in legs:
            # Use a per-fold declared set; S2 owns the one and only relabel at search time.
            base_kind = decision.primary.comparison[0]
            for fold, membership in memberships.items():
                canary = fl.CanaryLeg(
                    models[base_kind], canary_identities=sorted(membership), seed=decision.gallery_lineage.split_seed
                )
                galleries[fc.LegKind.canary, fold] = galleries[base_kind, fold]
                models.setdefault(fc.LegKind.canary, {})[fold] = canary
        enrolled_annotations = {}
        for kind, model in models.items():
            for fold, membership in memberships.items():
                runtime = model[fold] if kind is fc.LegKind.canary else model
                gallery = galleries[kind, fold]
                snapshot = gallery.relabelled(runtime) if kind is fc.LegKind.canary else gallery
                annotations = {i: by_id[t.template_id]["occluders"] for i, t in membership.items()}
                if kind is fc.LegKind.canary:
                    annotations = {runtime.permutation[i]: value for i, value in annotations.items()}
                enrolled_annotations[kind, fold] = annotations
                for arm in arms:
                    registry.append(
                        {
                            "leg_key": runtime.leg_id(arm).key(),
                            "fold": fold,
                            "gallery_sha256": snapshot.gallery_sha256,
                            "enrolled_identity_ids": sorted(membership),
                            "identity_folds": dict(sorted(identity_folds.items())),
                            "enrolled_occluders": annotations,
                        }
                    )
        basis_kind = decision.primary.comparison[0]
        basis = models[basis_kind].leg_id(fc.Arm.native).key()
        prepared_frame = ff.build_frame(
            spec=frame,
            images=source.images,
            faces=source.faces,
            planning_icc=decision.planning_icc,
            k=k,
            seed=seed,
            test_fold=seed % k,
            gallery_sha256_by_fold={f: galleries[basis_kind, f].gallery_sha256 for f in range(k)},
            enrolled_identity_ids=frozenset(memberships[seed % k]),
        )
        ff.frame_json(prepared_frame)

        def run_legs(**_):
            from scripts.eval_harness.firbench_cli import LegRunResult, _check_run_result

            searches, ledger, timings = {}, {}, {}
            observations = defaultdict(list)
            for kind, model in models.items():
                for fold in range(k):
                    runtime = model[fold] if kind is fc.LegKind.canary else model
                    selected = {i: p for i, p in pixels.items() if folds[components[i]] == fold}
                    faces = [f for f in source.faces if f.image_id in selected]
                    landmarks = {}
                    for arm in sorted(arms, key=lambda a: a is not fc.Arm.native):
                        key = runtime.leg_id(arm).key()
                        cells = {
                            f.face_id: (
                                _occluder(f.annotation.occluders),
                                _occluder(enrolled_annotations[kind, fold][f.identity_id])
                                if f.identity_id in memberships[fold]
                                else "unknown",
                            )
                            for f in faces
                        }
                        result = fl.search_leg_arm(
                            leg=runtime,
                            arm=arm,
                            images=selected,
                            image_units={i.image_id: i for i in source.images},
                            faces=faces,
                            gallery=galleries[kind, fold],
                            psu_by_image=components,
                            fold_by_psu=folds,
                            fold_roles=prepared_frame.fold_roles,
                            exhaustive=True,
                            top_k=20,
                            cells=cells,
                            cached_landmarks=landmarks,
                            crop_margin=float(margin),
                        )
                        if arm is fc.Arm.native and runtime.alignment_mode is fc.AlignmentMode.separable:
                            # Replay the very same native assignment; no private reads,
                            # detector calls or repeated Hungarian matching.
                            landmarks = {
                                o.gt_face_id: np.asarray(o.landmarks_px)
                                for o in result.cached_observations
                                if o.gt_face_id is not None and o.landmarks_px is not None
                            }
                        observations[key].extend(result.cached_observations)
                        searches.setdefault(key, []).extend(r.to_dict() for r in result.records)
                        ledger.setdefault(key, []).extend(
                            {
                                **asdict(r),
                                "arm": r.arm.value,
                                "stage_reached": r.stage_reached.value if r.stage_reached else None,
                                "arm_availability": r.arm_availability.value,
                                "alignment_mode": r.alignment_mode.value,
                            }
                            for r in result.ledger
                        )
                        timings.update(result.timings_ms)
            result = LegRunResult(tuple(f.face_id for f in source.faces), searches, ledger, timings)
            keys = tuple(sorted({row["leg_key"] for row in registry}))
            # Validate ALL query outcomes and ALL packed caches before publishing any cache.
            # The driver keeps immutable declarations/failure evidence on an exception here.
            _check_run_result(result, leg_keys=keys, arms=arms)
            packed = {key: fl.pack_cache_observations(observations[key], leg_key=key) for key in keys}
            for key, arrays in packed.items():
                fl.validate_cache_observations(
                    arrays,
                    leg_key=key,
                    image_sha256_by_id={i.image_id: i.sha256 for i in source.images},
                    gt_image_by_id={f.face_id: f.image_id for f in source.faces},
                )
            for key, arrays in packed.items():
                fl.LegCache(Path(out_dir) / "legs" / key / "cache.npz", leg_key=key).store(arrays)
            return result

        registry.sort(key=lambda row: (row["leg_key"], row["fold"]))
        return PreparedRun(
            prepared_frame,
            tuple(registry),
            basis,
            run_legs,
            float(margin),
            {fold: dict(model.permutation) for fold, model in models.get(fc.LegKind.canary, {}).items()},
        )


def _occluder(values):
    return "unknown" if values is None else "+".join(sorted(values)) if values else "clear"


def default_collaborators():
    """Create settings/identities lazily. No query data, pixels or bench import here."""
    from recognition.config import get_settings
    from recognition.config.settings import resolve_face_pipeline_knobs
    from scripts.eval_harness import firbench_score_io
    from scripts.eval_harness.firbench_cli import FirBenchCollaborators

    settings = get_settings()
    knobs = resolve_face_pipeline_knobs(
        face_pipeline=settings.face_pipeline,
        clustering=settings.clustering,
        clustering_limits=settings.clustering_limits,
        identity_detection=settings.identity_detection,
    )
    adapter = _Adapter(settings)
    return FirBenchCollaborators(
        leg_keys=adapter.leg_keys,
        run_legs=None,
        score_run=firbench_score_io.score_run,
        scorer_sha=scorer_sha256(),
        similarity_threshold=knobs.similarity_threshold,
        prepare_run=adapter.prepare_run,
    )
