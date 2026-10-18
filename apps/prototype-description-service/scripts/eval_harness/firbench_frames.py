"""FIRBENCH-1 S1 frames: PSU components, face-count design effect, folds and the non-mated pool.

The independent unit is the image-identity connected component, not the image
[AUDIT-11, EXP-23]. Folds are assigned to whole components so no identity leaks
across calibration and test [CAL-07]. The non-mated source-unit inventory comes
from the exhaustive frame only and never from detector output [EVAL-18, EVAL-19].
Binding values such as ``planning_icc`` arrive as arguments from the decision
manifest; nothing here is a module-level constant of that kind [rg-009].
"""

from __future__ import annotations

import json
import math
import random
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from scripts.eval_harness.firbench_contract import (
    FoldRole,
    FrameContractError,
    FrameSpec,
    IdentityStatus,
    SamplingArm,
    validate_interchange,
)

# Schema enums of frame-v1 face annotations. The frame-v1 schema is the authority;
# the test suite checks these sets against it.
OCCLUDER_VALUES = frozenset({"mask", "sunglasses", "clear_glasses", "hand", "phone", "hair", "other_object", "mixed"})
REGION_VALUES = frozenset({"visible", "occluded", "self_occluded", "out_of_frame", "uncertain"})
_ANNOTATION_TIERS = frozenset({"a", "b"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_SEED = 2**32
_BACKGROUND_PREFIX = "background:"


def _fail(message: str) -> FrameContractError:
    return FrameContractError(message)


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise _fail(f"{name} must be a non-empty string")
    return value


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.match(value):
        raise _fail(f"{name} must be a lowercase sha256 hex digest")
    return value


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise _fail(f"{name} must be an integer >= {minimum}")
    return value


def _probability_open(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise _fail(f"{name} must be a finite number")
    if not 0.0 < float(value) < 1.0:
        raise _fail(f"{name} must lie strictly between 0 and 1")
    return float(value)


# --- records ------------------------------------------------------------------


@dataclass(frozen=True)
class Cohort:
    """Cohort labels carried by a face when the frame supplies them; each is a string or None."""

    sex: str | None = None
    age_band: str | None = None
    origin: str | None = None

    def __post_init__(self) -> None:
        for name in ("sex", "age_band", "origin"):
            _optional_text(getattr(self, name), f"cohort.{name}")

    def to_json(self) -> dict[str, str | None]:
        return {"sex": self.sex, "age_band": self.age_band, "origin": self.origin}


@dataclass(frozen=True)
class Visibility:
    """Rubric anatomy states per region; None is unlabelled, which is not the same as visible."""

    left_eye: str | None = None
    right_eye: str | None = None
    nose: str | None = None
    mouth: str | None = None

    def __post_init__(self) -> None:
        for name in ("left_eye", "right_eye", "nose", "mouth"):
            value = getattr(self, name)
            if value is not None and value not in REGION_VALUES:
                raise _fail(f"visibility.{name} {value!r} is not a rubric region state")

    def to_json(self) -> dict[str, str | None]:
        return {"left_eye": self.left_eye, "right_eye": self.right_eye, "nose": self.nose, "mouth": self.mouth}


@dataclass(frozen=True)
class FaceAnnotation:
    """Per-face labels from frame-v1. Missing labels are unknown; ``occluders=()`` is an explicit no-occluder claim."""

    occluders: tuple[str, ...] | None = None
    visibility: Visibility = field(default_factory=Visibility)
    annotation_tier: str | None = None
    exhaustive: bool | None = None
    provenance_ref: str | None = None
    rule_id: str | None = None
    observation_ref: str | None = None
    qc_ref: str | None = None

    def __post_init__(self) -> None:
        if self.occluders is not None:
            values = tuple(self.occluders)
            unknown = sorted({value for value in values if value not in OCCLUDER_VALUES})
            if unknown:
                raise _fail(f"annotation.occluders has unknown members {unknown}")
            object.__setattr__(self, "occluders", tuple(sorted(set(values))))
        if not isinstance(self.visibility, Visibility):
            raise _fail("annotation.visibility must be a Visibility")
        if self.annotation_tier is not None and self.annotation_tier not in _ANNOTATION_TIERS:
            raise _fail(f"annotation.annotation_tier {self.annotation_tier!r} is not a or b")
        if self.exhaustive is not None and not isinstance(self.exhaustive, bool):
            raise _fail("annotation.exhaustive must be a boolean or null")
        if self.exhaustive is True and self.annotation_tier != "b":
            raise _fail("annotation.exhaustive=true requires annotation_tier b")
        for name in ("provenance_ref", "rule_id", "observation_ref", "qc_ref"):
            _optional_text(getattr(self, name), f"annotation.{name}")

    def to_json(self) -> dict[str, Any]:
        return {
            "occluders": None if self.occluders is None else list(self.occluders),
            "visibility": self.visibility.to_json(),
            "annotation_tier": self.annotation_tier,
            "exhaustive": self.exhaustive,
            "provenance_ref": self.provenance_ref,
            "rule_id": self.rule_id,
            "observation_ref": self.observation_ref,
            "qc_ref": self.qc_ref,
        }


@dataclass(frozen=True)
class ImageUnit:
    """One frame image. ``inclusion_probability`` is set on the probability arm and None on challenge."""

    image_id: str
    sha256: str
    sampling_arm: SamplingArm
    inclusion_probability: float | None
    duplicate_group: str | None = None
    session_id: str | None = None
    synthetic_parent_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.image_id, "image_id")
        _sha(self.sha256, f"image {self.image_id}.sha256")
        try:
            object.__setattr__(self, "sampling_arm", SamplingArm(self.sampling_arm))
        except (TypeError, ValueError):
            raise _fail(f"image {self.image_id}: sampling_arm is not a SamplingArm") from None
        if self.sampling_arm is SamplingArm.probability:
            if self.inclusion_probability is None:
                raise _fail(f"image {self.image_id}: probability arm needs an inclusion_probability")
            probability = _finite_number(self.inclusion_probability, f"image {self.image_id}.inclusion_probability")
            if not 0.0 < probability <= 1.0:
                raise _fail(f"image {self.image_id}.inclusion_probability must lie in (0, 1]")
        elif self.inclusion_probability is not None:
            raise _fail(f"image {self.image_id}: challenge arm carries no inclusion_probability")
        _optional_text(self.duplicate_group, f"image {self.image_id}.duplicate_group")
        _optional_text(self.session_id, f"image {self.image_id}.session_id")
        _optional_text(self.synthetic_parent_id, f"image {self.image_id}.synthetic_parent_id")

    def to_json(self) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "sha256": self.sha256,
            "sampling_arm": self.sampling_arm.value,
            "inclusion_probability": self.inclusion_probability,
            "duplicate_group": self.duplicate_group,
            "session_id": self.session_id,
            "synthetic_parent_id": self.synthetic_parent_id,
        }


@dataclass(frozen=True)
class GtFace:
    """One ground-truth face. Only a named face carries an identity; every other status adds no identity edge."""

    face_id: str
    image_id: str
    box: tuple[float, float, float, float]
    identity_status: IdentityStatus
    identity_id: str | None
    cohort: Cohort | None = None
    annotation: FaceAnnotation = field(default_factory=FaceAnnotation)

    def __post_init__(self) -> None:
        _text(self.face_id, "face_id")
        _text(self.image_id, f"face {self.face_id}.image_id")
        object.__setattr__(self, "box", _box_geometry(self.box, f"face {self.face_id}.box"))
        try:
            object.__setattr__(self, "identity_status", IdentityStatus(self.identity_status))
        except (TypeError, ValueError):
            raise _fail(f"face {self.face_id}: identity_status is not an IdentityStatus") from None
        if self.identity_status is IdentityStatus.named:
            _text(self.identity_id, f"face {self.face_id}.identity_id")
            if not self.identity_id.strip():
                raise _fail(f"face {self.face_id}.identity_id must not be blank")
        elif self.identity_id is not None:
            raise _fail(f"face {self.face_id}: a {self.identity_status.value} face carries no identity_id")
        if self.cohort is not None and not isinstance(self.cohort, Cohort):
            raise _fail(f"face {self.face_id}.cohort must be a Cohort or null")
        if not isinstance(self.annotation, FaceAnnotation):
            raise _fail(f"face {self.face_id}.annotation must be a FaceAnnotation")

    def to_json(self) -> dict[str, Any]:
        return {
            "face_id": self.face_id,
            "image_id": self.image_id,
            "box": list(self.box),
            "identity_status": self.identity_status.value,
            "identity_id": self.identity_id,
            "cohort": None if self.cohort is None else self.cohort.to_json(),
            "annotation": self.annotation.to_json(),
        }


@dataclass(frozen=True)
class FrameSource:
    """Images and GT faces read from one manifest or population file."""

    images: tuple[ImageUnit, ...]
    faces: tuple[GtFace, ...]


# --- PSU components -----------------------------------------------------------


def build_psu_components(images: Sequence[ImageUnit], faces: Sequence[GtFace]) -> dict[str, str]:
    """Map each image to its PSU: the sorted smallest image_id of its image-identity component.

    Edges: image to named identity; exact-duplicate groups; shared session; and a
    synthetic sibling to its parent. Unknown and unresolved faces add no edge.
    """
    image_ids = [image.image_id for image in images]
    if len(set(image_ids)) != len(image_ids):
        raise _fail("image_id must be unique within a frame")
    known = set(image_ids)
    face_ids = [face.face_id for face in faces]
    if len(set(face_ids)) != len(face_ids):
        raise _fail("face_id must be unique within a frame")
    for face in faces:
        if face.image_id not in known:
            raise _fail(f"face {face.face_id} references unknown image {face.image_id}")

    parent: dict[str, str] = {}

    def find(node: str) -> str:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: str, right: str) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            keep, drop = sorted((root_left, root_right))
            parent[drop] = keep

    for image_id in image_ids:
        find(f"image:{image_id}")
    for face in faces:
        if face.identity_status is IdentityStatus.named:
            union(f"image:{face.image_id}", f"identity:{face.identity_id}")

    first_by_group: dict[str, str] = {}
    first_by_session: dict[str, str] = {}
    for image in images:
        node = f"image:{image.image_id}"
        if image.duplicate_group is not None:
            union(node, first_by_group.setdefault(image.duplicate_group, node))
        if image.session_id is not None:
            union(node, first_by_session.setdefault(image.session_id, node))
        if image.synthetic_parent_id is not None:
            if image.synthetic_parent_id not in known:
                raise _fail(
                    f"image {image.image_id}: synthetic_parent_id {image.synthetic_parent_id} is not in the frame"
                )
            union(node, f"image:{image.synthetic_parent_id}")

    members: dict[str, list[str]] = {}
    for image_id in image_ids:
        members.setdefault(find(f"image:{image_id}"), []).append(image_id)
    psu_by_image: dict[str, str] = {}
    for group in members.values():
        psu_id = min(group)
        for image_id in group:
            psu_by_image[image_id] = psu_id
    return {image_id: psu_by_image[image_id] for image_id in sorted(image_ids)}


def identity_to_component(faces: Sequence[GtFace], component_map: Mapping[str, str]) -> dict[str, str]:
    """Map each named identity to the PSU of its images. Identities are never assigned folds directly."""
    result: dict[str, str] = {}
    for face in faces:
        if face.identity_status is not IdentityStatus.named:
            continue
        if face.image_id not in component_map:
            raise _fail(f"face {face.face_id} references an image outside the component map")
        psu_id = component_map[face.image_id]
        if result.setdefault(face.identity_id, psu_id) != psu_id:
            raise _fail(f"identity {face.identity_id} spans two PSU components")
    return dict(sorted(result.items()))


def psu_face_counts(component_map: Mapping[str, str], faces: Sequence[GtFace]) -> dict[str, int]:
    """GT face count m per PSU. Components with no face keep m = 0 and still count as their own PSU."""
    counts = dict.fromkeys(sorted(set(component_map.values())), 0)
    for face in faces:
        if face.image_id not in component_map:
            raise _fail(f"face {face.face_id} references an image outside the component map")
        counts[component_map[face.image_id]] += 1
    return counts


# --- design effect ------------------------------------------------------------


def size_weighted_mean(psu_sizes: Sequence[int]) -> float:
    """M-tilde = sum(m^2) / sum(m) over PSUs with m >= 1, in whatever unit m counts (faces here)."""
    sizes = [_integer(size, "psu size") for size in psu_sizes]
    positive = [size for size in sizes if size >= 1]
    if not positive:
        raise _fail("size_weighted_mean needs at least one PSU with m >= 1")
    return float(Fraction(sum(size * size for size in positive), sum(positive)))


def design_effect(psu_sizes: Sequence[int], icc: float) -> float:
    """Design effect 1 + (M-tilde - 1) * icc, with M-tilde from ``size_weighted_mean``."""
    if isinstance(icc, bool) or not isinstance(icc, (int, float)) or not 0.0 <= float(icc) <= 1.0:
        raise _fail("icc must be a number in [0, 1]")
    return 1.0 + (size_weighted_mean(psu_sizes) - 1.0) * float(icc)


def effective_n(n: float, deff: float) -> float:
    """n / deff as a float. Used for sizing and for n_nonmated_eff only; never passed to a binomial function."""
    if isinstance(deff, bool) or not isinstance(deff, (int, float)) or not math.isfinite(deff) or deff <= 0:
        raise _fail("deff must be a positive finite number")
    return float(n) / float(deff)


@dataclass(frozen=True)
class IccEstimate:
    """Observed ICC for reporting only. ``icc`` is None when outcomes are all equal (undefined)."""

    icc: float | None
    n_psu: int


def estimate_icc(outcomes_by_psu: Mapping[str, Sequence[int | bool]]) -> IccEstimate:
    """One-way ANOVA ICC on binary face-level outcomes grouped by PSU, floored at 0."""
    groups: dict[str, list[int]] = {}
    for psu_id in sorted(outcomes_by_psu):
        values = []
        for value in outcomes_by_psu[psu_id]:
            if isinstance(value, bool) or value in (0, 1):
                values.append(int(value))
            else:
                raise _fail(f"PSU {psu_id}: outcomes must be binary, got {value!r}")
        if values:
            groups[psu_id] = values
    k = len(groups)
    total = sum(len(values) for values in groups.values())
    if k < 2 or total <= k:
        return IccEstimate(icc=None, n_psu=k)
    pooled = [value for values in groups.values() for value in values]
    if min(pooled) == max(pooled):
        return IccEstimate(icc=None, n_psu=k)
    grand = Fraction(sum(pooled), total)
    ssb = Fraction(0)
    ssw = Fraction(0)
    size_square_sum = Fraction(0)
    for values in groups.values():
        size = len(values)
        mean = Fraction(sum(values), size)
        ssb += size * (mean - grand) ** 2
        ssw += sum((value - mean) ** 2 for value in values)
        size_square_sum += Fraction(size * size, total)
    msb = ssb / (k - 1)
    msw = ssw / (total - k)
    n0 = (total - size_square_sum) / (k - 1)
    denominator = msb + (n0 - 1) * msw
    if denominator == 0:
        return IccEstimate(icc=None, n_psu=k)
    return IccEstimate(icc=float(max(Fraction(0), (msb - msw) / denominator)), n_psu=k)


# --- folds --------------------------------------------------------------------


def identity_disjoint_folds(
    component_map: Mapping[str, str],
    identity_to_component: Mapping[str, str],
    *,
    k: int,
    seed: int,
) -> dict[str, int]:
    """Assign whole PSU components to k folds, seeded and balanced by component count."""
    _integer(k, "k", minimum=2)
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < _MAX_SEED:
        raise _fail("seed must be an integer in [0, 2**32)")
    psus = sorted(set(component_map.values()))
    if k > len(psus):
        raise _fail(f"k={k} exceeds the {len(psus)} PSU components")
    known = set(psus)
    for identity, psu_id in identity_to_component.items():
        if psu_id not in known:
            raise _fail(f"identity {identity} maps to a component outside the component map")
    order = list(psus)
    random.Random(seed).shuffle(order)
    folds = {psu_id: index % k for index, psu_id in enumerate(order)}
    return dict(sorted(folds.items()))


# --- non-mated pool -----------------------------------------------------------


@dataclass(frozen=True)
class NonMatedUnit:
    """One non-mated source unit: a non-mated GT face (unit_id = face_id) or a background unit per image."""

    unit_id: str
    fold: int
    psu_id: str
    cohort: Cohort | None


@dataclass(frozen=True)
class NonMatedPool:
    """Immutable non-mated source-unit inventory for one fold, built from the exhaustive frame only."""

    fold: int
    units: tuple[NonMatedUnit, ...]
    n_units: int
    n_nonmated_eff: float
    design_effect: float | None


def build_nonmated_pool(
    faces: Sequence[GtFace],
    images: Sequence[ImageUnit],
    folds: Mapping[str, int],
    *,
    fold: int,
    component_map: Mapping[str, str],
    exhaustive: bool,
    planning_icc: float,
    enrolled_identity_ids: frozenset[str],
) -> NonMatedPool:
    """Build non-mated units for a query fold against its explicitly declared gallery.

    Query folds and gallery membership are separate axes [MCP16810]. An empty
    frozenset declares an empty gallery. Detector output cannot shape this pool
    [EVAL-19]; unknown GT faces and one background unit per selected image remain.
    """
    if exhaustive is not True:
        raise _fail("non-mated source units need an exhaustive frame; exhaustive is not established")
    if not isinstance(enrolled_identity_ids, frozenset) or any(
        not isinstance(identity, str) or not identity.strip() for identity in enrolled_identity_ids
    ):
        raise _fail("enrolled_identity_ids must be a frozenset of non-blank identity IDs")
    _integer(fold, "fold")
    _probability_open(planning_icc, "planning_icc")
    for face in faces:
        if face.identity_status is IdentityStatus.unresolved:
            raise _fail(f"face {face.face_id} is unresolved and can never be non-mated")
    image_ids = {image.image_id for image in images}
    if set(component_map) != image_ids:
        raise _fail("component_map must cover exactly the frame images")
    if dict(component_map) != build_psu_components(images, faces):
        raise _fail("component_map must match the canonical PSU partition and IDs")
    psus = set(component_map.values())
    if set(folds) != psus:
        raise _fail("folds must assign exactly the PSU components of component_map")
    for psu_id, assigned in folds.items():
        _integer(assigned, f"fold of {psu_id}")

    identity_fold = {identity: folds[psu] for identity, psu in identity_to_component(faces, component_map).items()}
    units: list[NonMatedUnit] = []
    for face in faces:
        psu_id = component_map[face.image_id]
        if (
            face.identity_status is IdentityStatus.unknown
            and folds[psu_id] == fold
            or face.identity_status is IdentityStatus.named
            and identity_fold[face.identity_id] == fold
            and face.identity_id not in enrolled_identity_ids
        ):
            units.append(NonMatedUnit(face.face_id, fold, psu_id, face.cohort))
    for image in images:
        psu_id = component_map[image.image_id]
        if folds[psu_id] == fold:
            units.append(NonMatedUnit(f"{_BACKGROUND_PREFIX}{image.image_id}", fold, psu_id, None))
    units.sort(key=lambda unit: unit.unit_id)
    if not units:
        return NonMatedPool(fold=fold, units=(), n_units=0, n_nonmated_eff=0.0, design_effect=None)
    unit_sizes = list(Counter(unit.psu_id for unit in units).values())
    deff = design_effect(unit_sizes, planning_icc)
    return NonMatedPool(
        fold=fold,
        units=tuple(units),
        n_units=len(units),
        n_nonmated_eff=effective_n(len(units), deff),
        design_effect=deff,
    )


# --- frame --------------------------------------------------------------------


@dataclass(frozen=True)
class Frame:
    """One rotation's frame, written as frame-v1. Counts and deff describe the held-out test fold where stated."""

    spec: FrameSpec
    images: tuple[ImageUnit, ...]
    faces: tuple[GtFace, ...]
    psu_map: dict[str, str]
    folds: dict[str, int]
    identity_fold: dict[str, int]
    gallery_sha256_by_fold: dict[int, str]
    fold_roles: dict[int, FoldRole]
    planning_icc: float
    design_effect: float
    n_eff: float
    n_units: int
    n_nonmated_eff: float
    sampling_arm_counts: dict[str, int]

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "frame_id": self.spec.frame_id,
            "admissibility": self.spec.admissibility.value,
            "sealed": self.spec.sealed,
            "source_sha256": self.spec.source_sha256,
            "exhaustive": self.spec.exhaustive,
            "planning_icc": self.planning_icc,
            "design_effect": self.design_effect,
            "n_eff": self.n_eff,
            "n_units": self.n_units,
            "n_nonmated_eff": self.n_nonmated_eff,
            "sampling_arm_counts": dict(self.sampling_arm_counts),
            "images": [image.to_json() for image in self.images],
            "faces": [face.to_json() for face in self.faces],
            "psu_map": [{"image_id": image_id, "psu_id": psu_id} for image_id, psu_id in sorted(self.psu_map.items())],
            "folds": [{"psu_id": psu_id, "fold": fold} for psu_id, fold in sorted(self.folds.items())],
            "identity_folds": [
                {"identity_id": identity, "fold": fold} for identity, fold in sorted(self.identity_fold.items())
            ],
            "gallery_sha256_by_fold": [
                {"fold": fold, "sha256": sha} for fold, sha in sorted(self.gallery_sha256_by_fold.items())
            ],
            "fold_roles": [{"fold": fold, "role": role.value} for fold, role in sorted(self.fold_roles.items())],
        }


def frame_json(frame: Frame) -> str:
    """Canonical frame-v1 JSON. Same inputs and seed give the same bytes; the payload is validated first."""
    payload = frame.to_payload()
    validate_interchange("frame-v1", payload)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def build_frame(
    *,
    spec: FrameSpec,
    images: Sequence[ImageUnit],
    faces: Sequence[GtFace],
    planning_icc: float,
    k: int,
    seed: int,
    test_fold: int,
    gallery_sha256_by_fold: Mapping[int, str],
    enrolled_identity_ids: frozenset[str],
) -> Frame:
    """Build one rotation's frame using declared test-gallery membership and hashes.

    Non-mated counts require an exhaustive frame and explicit gallery membership;
    ``frozenset()`` declares an empty gallery, never missing context [MCP16810].
    """
    if not isinstance(spec, FrameSpec):
        raise _fail("spec must be a FrameSpec")
    if spec.exhaustive is not True:
        raise _fail(f"frame {spec.frame_id}: exhaustive is not established, so non-mated counts are refused")
    _probability_open(planning_icc, "planning_icc")
    ordered_images = tuple(sorted(images, key=lambda image: image.image_id))
    ordered_faces = tuple(sorted(faces, key=lambda face: face.face_id))
    component_map = build_psu_components(ordered_images, ordered_faces)
    identity_map = identity_to_component(ordered_faces, component_map)
    folds = identity_disjoint_folds(component_map, identity_map, k=k, seed=seed)
    _integer(test_fold, "test_fold")
    if test_fold >= k:
        raise _fail(f"test_fold {test_fold} is outside 0..{k - 1}")
    if set(gallery_sha256_by_fold) != set(range(k)):
        raise _fail("gallery_sha256_by_fold must give one hash per fold")
    gallery = {fold: _sha(gallery_sha256_by_fold[fold], f"gallery_sha256_by_fold[{fold}]") for fold in range(k)}
    pool = build_nonmated_pool(
        ordered_faces,
        ordered_images,
        folds,
        fold=test_fold,
        component_map=component_map,
        exhaustive=True,
        planning_icc=planning_icc,
        enrolled_identity_ids=enrolled_identity_ids,
    )
    face_sizes = list(psu_face_counts(component_map, ordered_faces).values())
    deff = design_effect(face_sizes, planning_icc)
    arm_counts = {arm.value: 0 for arm in SamplingArm}
    for image in ordered_images:
        arm_counts[image.sampling_arm.value] += 1
    return Frame(
        spec=spec,
        images=ordered_images,
        faces=ordered_faces,
        psu_map=component_map,
        folds=folds,
        identity_fold={identity: folds[psu] for identity, psu in identity_map.items()},
        gallery_sha256_by_fold=gallery,
        fold_roles={fold: FoldRole.test if fold == test_fold else FoldRole.fit for fold in range(k)},
        planning_icc=float(planning_icc),
        design_effect=deff,
        n_eff=effective_n(len(ordered_faces), deff),
        n_units=pool.n_units,
        n_nonmated_eff=pool.n_nonmated_eff,
        sampling_arm_counts=arm_counts,
    )


# --- loaders ------------------------------------------------------------------


def _load_json(path: str | Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise _fail(f"cannot read frame source {Path(path).name}: {error.strerror}") from error
    except ValueError as error:
        raise _fail(f"frame source {Path(path).name} is not valid JSON") from error


def _object(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise _fail(f"{where} must be an object")
    return value


def _array(value: object, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise _fail(f"{where} must be an array")
    return value


def _key(mapping: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise _fail(f"{where} is missing key {key!r}")
    return mapping[key]


def _finite_number(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _fail(f"{where} must be a finite number")
    try:
        number = float(value)
    except OverflowError:
        raise _fail(f"{where} must be a finite number") from None
    if not math.isfinite(number):
        raise _fail(f"{where} must be a finite number")
    return number


def _box_geometry(value: object, where: str) -> tuple[float, float, float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 4:
        raise _fail(f"{where} must be four finite numbers")
    x, y, width, height = (_finite_number(item, where) for item in value)
    if width <= 0 or height <= 0:
        raise _fail(f"{where} width and height must be positive")
    return x, y, width, height


def _reject_unknown_keys(raw: Mapping[str, Any], allowed: set[str], where: str) -> None:
    if set(raw) - allowed:
        raise _fail(f"{where} has unknown keys")


def _gt_name(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _fail("GT name must be a non-blank string or null")
    return value.strip()


def _pseudonyms(names: Sequence[object]) -> dict[str, str]:
    """Stable pseudonyms in sorted-name order. Real names stay in memory and never reach the output."""
    normalized = [_gt_name(name) for name in names]
    distinct = sorted({name for name in normalized if name is not None})
    return {name: f"id-{index + 1:04d}" for index, name in enumerate(distinct)}


def _box_faces(
    boxes: Sequence[object],
    *,
    image_id: str,
    where: str,
    names: Mapping[str, str],
    raw_names: Sequence[object],
) -> list[GtFace]:
    faces: list[GtFace] = []
    for index, raw_box in enumerate(boxes):
        box_where = f"{where}[{index}]"
        box = _object(raw_box, box_where)
        geometry = _box_geometry(tuple(_key(box, key, box_where) for key in ("x", "y", "w", "h")), box_where)
        name = _gt_name(raw_names[index])
        if name is None:
            status, identity = IdentityStatus.unknown, None
        else:
            status, identity = IdentityStatus.named, names[name]
        faces.append(
            GtFace(
                face_id=f"face-{image_id}-{index:03d}",
                image_id=image_id,
                box=geometry,
                identity_status=status,
                identity_id=identity,
            )
        )
    return faces


def load_golden_manifest(path: str | Path) -> FrameSource:
    """Golden-150 manifest. Entries are challenge-arm units: the manifest carries no inclusion probabilities."""
    document = _object(_load_json(path), "golden manifest")
    if "annotation_mode" in document and document["annotation_mode"] not in ("roster_only", "exhaustive"):
        raise _fail("golden manifest.annotation_mode must be roster_only or exhaustive")
    entries = _array(_key(document, "entries", "golden manifest"), "golden manifest.entries")
    images: list[ImageUnit] = []
    faces: list[GtFace] = []
    all_names: list[object] = []
    parsed: list[tuple[str, list[object], list[object]]] = []
    for index, raw_entry in enumerate(entries):
        where = f"golden manifest.entries[{index}]"
        entry = _object(raw_entry, where)
        if "annotation_mode" in entry:
            raise _fail(f"{where}: annotation_mode is document-level")
        media_id = _key(entry, "media_id", where)
        if isinstance(media_id, bool) or not isinstance(media_id, int):
            raise _fail(f"{where}.media_id must be an integer")
        boxes = _array(_key(entry, "face_boxes", where), f"{where}.face_boxes")
        names = [
            _key(_object(box, f"{where}.face_boxes[{box_index}]"), "name", f"{where}.face_boxes[{box_index}]")
            for box_index, box in enumerate(boxes)
        ]
        for box_index, box in enumerate(boxes):
            _key(_object(box, f"{where}.face_boxes[{box_index}]"), "source", f"{where}.face_boxes[{box_index}]")
        images.append(
            ImageUnit(
                image_id=str(media_id),
                sha256=_key(entry, "sha256", where),
                sampling_arm=SamplingArm.challenge,
                inclusion_probability=None,
            )
        )
        all_names.extend(names)
        parsed.append((str(media_id), boxes, names))
    pseudonyms = _pseudonyms(all_names)
    for image_id, boxes, names in parsed:
        faces.extend(
            _box_faces(boxes, image_id=image_id, where=f"golden image {image_id}", names=pseudonyms, raw_names=names)
        )
    return FrameSource(images=tuple(images), faces=tuple(faces))


def load_corpus_manifest(path: str | Path) -> FrameSource:
    """Corpus manifest v3r. Duplicate groups come from path lists; entries are challenge-arm units."""
    document = _object(_load_json(path), "corpus manifest")
    entries = _array(_key(document, "entries", "corpus manifest"), "corpus manifest.entries")
    groups = _array(_key(document, "duplicate_groups", "corpus manifest"), "corpus manifest.duplicate_groups")
    media_by_path: dict[str, str] = {}
    images_by_index: list[tuple[str, Mapping[str, Any]]] = []
    for index, raw_entry in enumerate(entries):
        where = f"corpus manifest.entries[{index}]"
        entry = _object(raw_entry, where)
        media_id = _key(entry, "media_id", where)
        if isinstance(media_id, bool) or not isinstance(media_id, int):
            raise _fail(f"{where}.media_id must be an integer")
        media_by_path[_text(_key(entry, "path", where), f"{where}.path")] = str(media_id)
        images_by_index.append((str(media_id), entry))
    dup_group_of: dict[str, str] = {}
    for group_index, raw_group in enumerate(groups):
        members = _array(raw_group, f"corpus manifest.duplicate_groups[{group_index}]")
        group_id = f"dup-{group_index + 1:04d}"
        for member in members:
            _text(member, "duplicate group member")
            if member not in media_by_path:
                raise _fail("duplicate group member is not a manifest entry")
            image_id = media_by_path[member]
            if dup_group_of.setdefault(image_id, group_id) != group_id:
                raise _fail(f"image {image_id} belongs to two duplicate groups")
    images: list[ImageUnit] = []
    all_names: list[object] = []
    parsed: list[tuple[str, list[object], list[object]]] = []
    for image_id, entry in images_by_index:
        where = f"corpus image {image_id}"
        boxes = _array(_key(entry, "named_boxes", where), f"{where}.named_boxes")
        names = [
            _key(_object(box, f"{where}.named_boxes[{box_index}]"), "name", f"{where}.named_boxes[{box_index}]")
            for box_index, box in enumerate(boxes)
        ]
        for box_index, box in enumerate(boxes):
            _key(_object(box, f"{where}.named_boxes[{box_index}]"), "source", f"{where}.named_boxes[{box_index}]")
        images.append(
            ImageUnit(
                image_id=image_id,
                sha256=_key(entry, "sha256", where),
                sampling_arm=SamplingArm.challenge,
                inclusion_probability=None,
                duplicate_group=dup_group_of.get(image_id),
            )
        )
        all_names.extend(names)
        parsed.append((image_id, boxes, names))
    pseudonyms = _pseudonyms(all_names)
    faces: list[GtFace] = []
    for image_id, boxes, names in parsed:
        faces.extend(
            _box_faces(boxes, image_id=image_id, where=f"corpus image {image_id}", names=pseudonyms, raw_names=names)
        )
    return FrameSource(images=tuple(images), faces=tuple(faces))


def _optional_annotation(value: object, where: str) -> FaceAnnotation:
    if value is None:
        return FaceAnnotation()
    raw = _object(value, where)
    _reject_unknown_keys(
        raw,
        {
            "occluders",
            "visibility",
            "annotation_tier",
            "exhaustive",
            "provenance_ref",
            "rule_id",
            "observation_ref",
            "qc_ref",
        },
        where,
    )
    visibility_value = raw.get("visibility")
    visibility_raw = {} if visibility_value is None else _object(visibility_value, f"{where}.visibility")
    _reject_unknown_keys(visibility_raw, {"left_eye", "right_eye", "nose", "mouth"}, f"{where}.visibility")
    for key, state in visibility_raw.items():
        if state is not None and (not isinstance(state, str) or state not in REGION_VALUES):
            raise _fail(f"{where}.visibility.{key} is not a rubric region state")
    occluders = raw.get("occluders")
    if occluders is not None:
        occluders = _array(occluders, f"{where}.occluders")
        if any(not isinstance(item, str) or item not in OCCLUDER_VALUES for item in occluders):
            raise _fail(f"{where}.occluders has unknown members")
    tier = raw.get("annotation_tier")
    if tier is not None and (not isinstance(tier, str) or tier not in _ANNOTATION_TIERS):
        raise _fail(f"{where}.annotation_tier is not a or b")
    return FaceAnnotation(
        occluders=None if occluders is None else tuple(occluders),
        visibility=Visibility(**{key: visibility_raw.get(key) for key in ("left_eye", "right_eye", "nose", "mouth")}),
        annotation_tier=raw.get("annotation_tier"),
        exhaustive=raw.get("exhaustive"),
        provenance_ref=raw.get("provenance_ref"),
        rule_id=raw.get("rule_id"),
        observation_ref=raw.get("observation_ref"),
        qc_ref=raw.get("qc_ref"),
    )


def load_population_draft(path: str | Path) -> FrameSource:
    """Pseudonymized population frame file with explicit arms. Its key names are unverified against the laptop file."""
    document = _object(_load_json(path), "population draft")
    _reject_unknown_keys(document, {"images", "faces"}, "population draft")
    images: list[ImageUnit] = []
    for index, raw in enumerate(_array(_key(document, "images", "population draft"), "population draft.images")):
        where = f"population draft.images[{index}]"
        image = _object(raw, where)
        _reject_unknown_keys(
            image,
            {"image_id", "sha256", "sampling_arm", "inclusion_probability", "duplicate_group", "session_id", "synthetic_parent_id"},
            where,
        )
        images.append(
            ImageUnit(
                image_id=_key(image, "image_id", where),
                sha256=_key(image, "sha256", where),
                sampling_arm=_key(image, "sampling_arm", where),
                inclusion_probability=_key(image, "inclusion_probability", where),
                duplicate_group=_key(image, "duplicate_group", where),
                session_id=image.get("session_id"),
                synthetic_parent_id=image.get("synthetic_parent_id"),
            )
        )
    faces: list[GtFace] = []
    for index, raw in enumerate(_array(_key(document, "faces", "population draft"), "population draft.faces")):
        where = f"population draft.faces[{index}]"
        face = _object(raw, where)
        _reject_unknown_keys(face, {"face_id", "image_id", "box", "identity_status", "identity_id", "cohort", "annotation"}, where)
        cohort_raw = _key(face, "cohort", where)
        if cohort_raw is not None:
            cohort_raw = _object(cohort_raw, f"{where}.cohort")
            _reject_unknown_keys(cohort_raw, {"sex", "age_band", "origin"}, f"{where}.cohort")
        cohort = None if cohort_raw is None else Cohort(**cohort_raw)
        faces.append(
            GtFace(
                face_id=_key(face, "face_id", where),
                image_id=_key(face, "image_id", where),
                box=tuple(_array(_key(face, "box", where), f"{where}.box")),
                identity_status=_key(face, "identity_status", where),
                identity_id=_key(face, "identity_id", where),
                cohort=cohort,
                annotation=_optional_annotation(face.get("annotation"), f"{where}.annotation"),
            )
        )
    return FrameSource(images=tuple(images), faces=tuple(faces))
