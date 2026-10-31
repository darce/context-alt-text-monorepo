"""Experimental offline A/B/C views, separate from FIRBENCH's pipeline ``Arm``.

Recipe v1 keeps native source resolution: A=whole scene; B=whole + four 3/4-size
corner crops; C=whole + first four identity-blind person proposals sorted by ID.
There is no resize, enhancement, face rescue, model loading, or threshold change.
Inputs are already oriented uint8 BGR. Boxes use continuous pixel *edges* (xywh);
landmarks use OpenCV pixel centers (integer origin). Quarter-turn inverses differ
by one pixel for those two conventions. Out-of-view detections are never clipped.

[PROV-01] Every output walks back to its evidence (Model Cards + AI Engineering):
source bytes, oriented pixel digest, view transforms and unchanged native leg ID
travel together. [EVAL-28] Real-occlusion protocol for real-occlusion claims
(A survey of face recognition techniques under occlusion): synthetic checks here
prove software only. No quality or acceptance claim follows from this producer.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from time import perf_counter

import numpy as np

from scripts.eval_harness.firbench_contract import (
    Arm,
    FrameContractError,
    RuntimeMismatchError,
    SearchStage,
    _require_sha,
)
from scripts.eval_harness.firbench_legs import DetectedFace, FacePipelineLeg, LegRuntime, Observation


class ViewPolicy(StrEnum):
    scene_only = "scene_only"
    fixed_overlap = "fixed_overlap"
    person_boxes = "person_boxes"


@dataclass(frozen=True)
class ViewBudget:
    """Per-source limits, explicitly supplied; calls count observe invocations, not FLOPs.

    Stage calls count detect/align/embed on FacePipelineLeg, or one opaque fused
    observe invocation. These are admission limits, not a measured compute match.

    The in-process deadline is cooperative: late results are rejected and no next
    call starts. A caller must provide process isolation for hard interruption.
    Candidate overflow fails the entire view, never a truncated successful view.
    """

    max_views: int
    max_pixels: int
    max_calls: int
    max_candidates: int
    max_stage_calls: int
    deadline_seconds: float
    max_proposals: int = 64

    def __post_init__(self):
        for name in ("max_views", "max_pixels", "max_calls", "max_candidates", "max_stage_calls", "max_proposals"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise FrameContractError(f"{name} must be a positive integer")
        if self.max_views > 5:
            raise FrameContractError("experimental recipe has at most five views")
        if (
            isinstance(self.deadline_seconds, bool)
            or not math.isfinite(self.deadline_seconds)
            or self.deadline_seconds <= 0
        ):
            raise FrameContractError("deadline_seconds must be finite and positive")


def _text(value: str, name: str):
    if not isinstance(value, str) or not value.strip():
        raise FrameContractError(f"{name} must be nonempty")


def _box(value):
    box = np.asarray(value, dtype=np.float64)
    if box.shape != (4,) or not np.isfinite(box).all() or min(box[2:]) <= 0:
        raise FrameContractError("box must be finite pixel xywh with positive size")
    return tuple(float(v) for v in box)


@dataclass(frozen=True)
class PersonBox:
    """External proposal in the oriented source frame; never an identity assertion."""

    proposal_id: str
    bbox_px: tuple[float, float, float, float]
    provenance_ref: str

    def __post_init__(self):
        _text(self.proposal_id, "proposal_id")
        _text(self.provenance_ref, "proposal provenance_ref")
        object.__setattr__(self, "bbox_px", _box(self.bbox_px))


@dataclass(frozen=True)
class View:
    view_id: str
    crop_xyxy: tuple[int, int, int, int]
    quarter_turns: int = 0  # clockwise, after cropping
    proposal_id: str | None = None
    proposal_ref: str | None = None

    def __post_init__(self):
        _text(self.view_id, "view_id")
        if (
            len(self.crop_xyxy) != 4
            or any(type(i) is not int for i in self.crop_xyxy)
            or min(self.crop_xyxy[:2]) < 0
            or self.crop_xyxy[2] <= self.crop_xyxy[0]
            or self.crop_xyxy[3] <= self.crop_xyxy[1]
        ):
            raise FrameContractError("view crop must be nonempty nonnegative integer xyxy")
        if type(self.quarter_turns) is not int or self.quarter_turns not in (0, 1, 2, 3):
            raise FrameContractError("quarter_turns must be 0, 1, 2 or 3")

    @property
    def pixels(self):
        x0, y0, x1, y1 = self.crop_xyxy
        return (x1 - x0) * (y1 - y0)

    def _inverse(self, centers: bool):
        x0, y0, x1, y1 = self.crop_xyxy
        w, h = x1 - x0 - int(centers), y1 - y0 - int(centers)
        return (
            ((1, 0, x0), (0, 1, y0), (0, 0, 1)),
            ((0, 1, x0), (-1, 0, y0 + h), (0, 0, 1)),
            ((-1, 0, x0 + w), (0, -1, y0 + h), (0, 0, 1)),
            ((0, -1, x0 + w), (1, 0, y0), (0, 0, 1)),
        )[self.quarter_turns]

    @property
    def box_inverse(self):
        return self._inverse(False)

    @property
    def point_inverse(self):
        return self._inverse(True)

    def render(self, image_bgr):
        x0, y0, x1, y1 = self.crop_xyxy
        if x1 > image_bgr.shape[1] or y1 > image_bgr.shape[0]:
            raise FrameContractError("view extends outside source")
        # Copy even the whole view: a collaborator cannot mutate source pixels.
        return np.array(np.rot90(image_bgr[y0:y1, x0:x1], -self.quarter_turns), copy=True, order="C")

    def to_source(self, observation: Observation) -> Observation:
        x, y, w, h = _box(observation.detection.bbox_px)
        corners = np.array([[x, y, 1], [x + w, y, 1], [x, y + h, 1], [x + w, y + h, 1]])
        mapped = corners @ np.asarray(self.box_inverse).T
        low, high = mapped[:, :2].min(axis=0), mapped[:, :2].max(axis=0)
        points = np.asarray(observation.detection.landmarks_px, dtype=np.float64)
        if points.shape != (5, 2) or not np.isfinite(points).all() or not math.isfinite(observation.detection.score):
            raise FrameContractError("detection needs finite 5x2 landmarks and score")
        points = (np.c_[points, np.ones(5)] @ np.asarray(self.point_inverse).T)[:, :2].copy()
        points.setflags(write=False)
        vector = observation.embedding
        if vector is not None:
            vector = np.array(vector, copy=True)
            if (
                vector.ndim != 1
                or not np.isfinite(vector).all()
                or np.linalg.norm(vector) == 0
                or observation.stage is not SearchStage.embedded
            ):
                raise RuntimeMismatchError("invalid embedded observation")
            vector.setflags(write=False)
        elif observation.stage is SearchStage.embedded:
            raise RuntimeMismatchError("embedded observation has no vector")
        return Observation(
            DetectedFace((*low, *(high - low)), points, float(observation.detection.score)), vector, observation.stage
        )


@dataclass(frozen=True)
class Candidate:
    view_id: str
    detection_index: int
    local_observation: Observation
    observation: Observation  # in oriented source coordinates
    source_id: str
    source_sha256: str
    leg_key: str


@dataclass(frozen=True)
class CandidateGroup:
    """One conservative geometric sighting group; all members retained, never vector-fused."""

    members: tuple[Candidate, ...]


def deduplicate(candidates: Sequence[Candidate], *, tolerance_px: float = 0.0) -> tuple[CandidateGroup, ...]:
    """Cross-view only, mutual-unique and complete-link geometry; ambiguity stays separate.

    Default is exact geometry coincidence. A nonzero experimental tolerance must
    be declared by the caller; detector confidence and embedding similarity never
    decide whether two overlapping people are one. No transitive chaining.
    """
    if not math.isfinite(tolerance_px) or tolerance_px < 0:
        raise FrameContractError("duplicate tolerance must be finite and nonnegative")
    if len({(c.source_id, c.source_sha256, c.leg_key) for c in candidates}) > 1:
        raise RuntimeMismatchError("cannot deduplicate different sources or model spaces")

    def same(a, b):
        if a.view_id == b.view_id:
            return False
        da, db = a.observation.detection, b.observation.detection
        return (
            np.max(np.abs(np.asarray(da.bbox_px) - db.bbox_px)) <= tolerance_px
            and np.max(np.abs(da.landmarks_px - db.landmarks_px)) <= tolerance_px
        )

    groups: list[list[Candidate]] = []
    for view_id in sorted({c.view_id for c in candidates}):
        batch = sorted((c for c in candidates if c.view_id == view_id), key=lambda c: c.detection_index)
        options = [[i for i, group in enumerate(groups) if all(same(c, member) for member in group)] for c in batch]
        uses = [i for choices in options for i in choices]
        for candidate, choices in zip(batch, options, strict=True):
            if len(choices) == 1 and uses.count(choices[0]) == 1:
                groups[choices[0]].append(candidate)
            else:
                groups.append([candidate])
    return tuple(CandidateGroup(tuple(group)) for group in groups)


@dataclass(frozen=True)
class ViewReceipt:
    view: View | None
    status: str
    proposal_id: str | None = None
    error_type: str | None = None


@dataclass(frozen=True)
class ViewResult:
    source_id: str
    source_sha256: str
    oriented_pixels_sha256: str
    orientation: str
    source_shape: tuple[int, ...]
    leg_key: str
    policy: ViewPolicy
    recipe_sha256: str
    recipe_json: str
    budget: ViewBudget
    receipts: tuple[ViewReceipt, ...]
    candidates: tuple[Candidate, ...]
    groups: tuple[CandidateGroup, ...]
    calls: int
    pixels_submitted: int
    stage_calls: int

    def to_dict(self) -> dict:
        """Lossless, JSON-safe offline evidence; never the native searches wire."""

        def observation(obs):
            return {
                "bbox_px": list(obs.detection.bbox_px),
                "landmarks_px": obs.detection.landmarks_px.tolist(),
                "detector_score": obs.detection.score,
                "stage": obs.stage.value,
                "embedding": None if obs.embedding is None else obs.embedding.tolist(),
            }

        indices = {id(candidate): i for i, candidate in enumerate(self.candidates)}
        return {
            "schema": "firbench-offline-view-evidence/v1",
            "source_id": self.source_id,
            "source_sha256": self.source_sha256,
            "oriented_pixels_sha256": self.oriented_pixels_sha256,
            "orientation": self.orientation,
            "source_shape": list(self.source_shape),
            "leg_key": self.leg_key,
            "recipe_sha256": self.recipe_sha256,
            "recipe": json.loads(self.recipe_json),
            "receipts": [
                {
                    "status": r.status,
                    "error_type": r.error_type,
                    "proposal_id": r.proposal_id,
                    "view": None
                    if r.view is None
                    else {**asdict(r.view), "box_inverse": r.view.box_inverse, "point_inverse": r.view.point_inverse},
                }
                for r in self.receipts
            ],
            "candidates": [
                {
                    "view_id": c.view_id,
                    "detection_index": c.detection_index,
                    "source_id": c.source_id,
                    "source_sha256": c.source_sha256,
                    "leg_key": c.leg_key,
                    "local": observation(c.local_observation),
                    "source": observation(c.observation),
                }
                for c in self.candidates
            ],
            "groups": [[indices[id(c)] for c in g.members] for g in self.groups],
            "calls": self.calls,
            "pixels_submitted": self.pixels_submitted,
            "stage_calls": self.stage_calls,
        }


class _ComputeBudgetError(RuntimeError):
    pass


def produce_views(
    *,
    leg: LegRuntime,
    image_bgr: np.ndarray,
    source_id: str,
    source_sha256: str,
    orientation: str,
    policy: ViewPolicy,
    budget: ViewBudget,
    person_boxes: Sequence[PersonBox] = (),
    quarter_turns: int = 0,
    proposal_status: str | None = None,
    proposal_source_ref: str | None = None,
    duplicate_tolerance_px: float = 0.0,
    offline: bool = False,
    clock: Callable[[], float] = perf_counter,
) -> ViewResult:
    """Run only an explicitly supplied leg, without model factories or filesystem IO.

    Missing, failed, timeout, proposal miss and exhausted-budget entries remain
    attached to the source [EVAL-16, Upstream failure counts against the end-to-end
    metric, IARPA Janus Benchmark-C, § 2.3.4]. No fallback silently replaces them.
    """
    if offline is not True:
        raise FrameContractError("experimental views require offline=True")
    if not isinstance(policy, ViewPolicy) or not isinstance(budget, ViewBudget):
        raise FrameContractError("explicit ViewPolicy and ViewBudget required")
    _text(source_id, "source_id")
    _text(orientation, "orientation")
    _require_sha(source_sha256, "source_sha256")
    if (
        not isinstance(image_bgr, np.ndarray)
        or image_bgr.dtype != np.uint8
        or image_bgr.ndim != 3
        or image_bgr.shape[2] != 3
        or min(image_bgr.shape[:2]) < 1
    ):
        raise FrameContractError("source must be nonempty already-oriented uint8 BGR")
    if len(person_boxes) > budget.max_proposals or any(not isinstance(p, PersonBox) for p in person_boxes):
        raise FrameContractError("person proposals exceed declared bound or have invalid type")
    if len({p.proposal_id for p in person_boxes}) != len(person_boxes):
        raise FrameContractError("duplicate person proposal IDs")
    if policy is not ViewPolicy.person_boxes and person_boxes:
        raise FrameContractError("person proposals require person_boxes policy")
    if proposal_status is not None or proposal_source_ref is not None:
        if policy is not ViewPolicy.person_boxes:
            raise FrameContractError("proposal status/reference requires person_boxes policy")
        _text(proposal_source_ref, "proposal_source_ref")
    if proposal_status is None:
        proposal_status = "ok" if person_boxes else "missing"
    if proposal_status not in {"ok", "empty", "missing", "failed", "timeout"}:
        raise FrameContractError("invalid person proposal status")
    if (proposal_status == "ok") != bool(person_boxes) and policy is ViewPolicy.person_boxes:
        raise FrameContractError("person boxes must agree with proposal status")
    deduplicate((), tolerance_px=duplicate_tolerance_px)  # validate before any model call
    height, width = image_bgr.shape[:2]
    planned: list[ViewReceipt] = [ViewReceipt(View("whole", (0, 0, width, height), quarter_turns), "planned")]
    if policy is ViewPolicy.fixed_overlap:
        cw, ch = math.ceil(3 * width / 4), math.ceil(3 * height / 4)
        for i, (x, y) in enumerate(((0, 0), (width - cw, 0), (0, height - ch), (width - cw, height - ch))):
            planned.append(ViewReceipt(View(f"overlap:{i}", (x, y, x + cw, y + ch), quarter_turns), "planned"))
    elif policy is ViewPolicy.person_boxes:
        for index, proposal in enumerate(sorted(person_boxes, key=lambda p: p.proposal_id)):
            if index >= 4:
                planned.append(ViewReceipt(None, "view_budget", proposal.proposal_id))
                continue
            x, y, w, h = proposal.bbox_px
            box = (
                max(0, math.floor(x)),
                max(0, math.floor(y)),
                min(width, math.ceil(x + w)),
                min(height, math.ceil(y + h)),
            )
            view = (
                View(
                    f"person:{proposal.proposal_id}", box, quarter_turns, proposal.proposal_id, proposal.provenance_ref
                )
                if box[2] > box[0] and box[3] > box[1]
                else None
            )
            planned.append(ViewReceipt(view, "planned" if view else "proposal_miss", proposal.proposal_id))
        if not person_boxes:
            planned.append(ViewReceipt(None, f"proposal_{proposal_status}"))
    recipe = {
        "schema": "firbench-offline-views/v1",
        "policy": policy.value,
        "box_coordinates": "xywh-continuous-pixel-edges",
        "landmarks": "opencv-integer-pixel-centers",
        "crop_fraction": "3/4",
        "resize": "none",
        "proposal_order": "id-first-four-no-backfill",
        "quarter_turns": quarter_turns,
        "duplicate_tolerance_px": duplicate_tolerance_px,
        "proposal_status": proposal_status if policy is ViewPolicy.person_boxes else None,
        "proposal_source_ref": proposal_source_ref,
        "budget": asdict(budget),
        "proposals": [asdict(p) for p in sorted(person_boxes, key=lambda p: p.proposal_id)],
    }
    recipe_json = json.dumps(recipe, sort_keys=True, separators=(",", ":"))
    recipe_sha = hashlib.sha256(recipe_json.encode()).hexdigest()
    pixel_sha = hashlib.sha256(str(image_bgr.shape).encode() + b"\0uint8-bgr\0" + image_bgr.tobytes()).hexdigest()
    key = leg.leg_id(Arm.native).key()
    receipts, candidates = [], []
    calls, pixels, stage_calls = 0, 0, 0
    exhausted_candidates = False
    start = clock()

    def before_stage(_stage: str):
        nonlocal stage_calls
        if clock() - start >= budget.deadline_seconds:
            raise TimeoutError("offline view deadline reached before next stage")
        if stage_calls >= budget.max_stage_calls:
            raise _ComputeBudgetError("offline stage-call budget exhausted")
        stage_calls += 1

    for slot, entry in enumerate(planned):
        view, status, error = entry.view, entry.status, None
        if status == "planned":
            if width * height > budget.max_pixels:
                status = "pixel_budget"  # never silently run a local-only version of A/B/C
            elif exhausted_candidates:
                status = "candidate_budget"
            elif slot >= budget.max_views:
                status = "view_budget"
            elif calls >= budget.max_calls:
                status = "call_budget"
            elif stage_calls >= budget.max_stage_calls:
                status = "compute_budget"
            elif pixels + view.pixels > budget.max_pixels:
                status = "pixel_budget"
            elif clock() - start >= budget.deadline_seconds:
                status = "timeout"
            else:
                rendered = view.render(image_bgr)
                try:
                    if isinstance(leg, FacePipelineLeg):
                        calls += 1
                        pixels += view.pixels
                        observations = leg.observe(rendered, before_stage=before_stage)
                    else:
                        before_stage("observe")  # fused internals are opaque: one admission per fused call
                        calls += 1
                        pixels += view.pixels
                        observations = leg.observe(rendered)
                except _ComputeBudgetError:
                    status = "compute_budget"
                except RuntimeMismatchError:
                    raise  # space/shape corruption is a contract refusal, never a soft model failure
                except (OSError, RuntimeError, ValueError) as exc:
                    status = (
                        "timeout"
                        if isinstance(exc, TimeoutError)
                        else "missing"
                        if isinstance(exc, FileNotFoundError)
                        else "failed"
                    )
                    error = type(exc).__name__
                else:
                    if clock() - start >= budget.deadline_seconds:
                        status = "timeout"
                    elif len(candidates) + len(observations) > budget.max_candidates:
                        status, exhausted_candidates = "candidate_budget", True
                    else:
                        status = "ok" if observations else "empty"
                        for index, observation in enumerate(observations):
                            mapped = view.to_source(observation)
                            if mapped.embedding is not None and mapped.embedding.size != leg.embedding_dim:
                                raise RuntimeMismatchError("candidate dimension differs from leg")
                            # Copy local output too, even when a model reuses its buffers.
                            local = View("local", (0, 0, rendered.shape[1], rendered.shape[0])).to_source(observation)
                            candidates.append(
                                Candidate(view.view_id, index, local, mapped, source_id, source_sha256, key)
                            )
        receipts.append(ViewReceipt(view, status, entry.proposal_id, error))
    return ViewResult(
        source_id,
        source_sha256,
        pixel_sha,
        orientation,
        tuple(image_bgr.shape),
        key,
        policy,
        recipe_sha,
        recipe_json,
        budget,
        tuple(receipts),
        tuple(candidates),
        deduplicate(candidates, tolerance_px=duplicate_tolerance_px),
        calls,
        pixels,
        stage_calls,
    )
