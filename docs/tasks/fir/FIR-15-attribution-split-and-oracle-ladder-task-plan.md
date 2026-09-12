# Task Plan — FIR-15. Attribution: alignment-vs-embedder split and oracle occlusion ladder

> **Metadata**
>
> - **Date**: 2026-09-11
> - **Author**: Claude Fable 5.1 (claude-fable-5-1) via sonnet drafting agent
> - **Owning Epic**: `docs/epics/v0.5.0/commercial-face-identity-replacement-epic.md`
> - **Epic Short ID**: FIR
> - **Task ID**: FIR-15
> - **Target Branch**: `feature/fir-15`
> - **Review Coverage Target**: 2
> - **Status**: draft
>
> Review counts/finding totals live in the handoff DB, not this file.

---

## FIR-15. Attribution: alignment-vs-embedder split and oracle occlusion ladder

## Objective

Answer T-01/FIRTRAIN-06 (D-02): apportion Golden-150 open-set identity error between the alignment stage and the embedder stage, with an interval on each share, and measure whether an oracle occlusion mask closes any of that gap (the oracle-before-predicted ladder). The output is a single MCP decision — `firplan_d02_attribution_<date>` — naming the leg (alignment | embedder | both | inconclusive) that FIR-17 branches on. No production code changes; CPU only, $0.

## Problem Statement

No artifact in the tree apportions identity error between alignment and embedding today: `face_metrics.py::face_identification_pr` is pooled precision/recall with no alignment intervention (QA v8 T-01). Absent this split, FIR-17's occlusion work (visible-support matching, pose rescue) has no evidence for which stage to target, and the "embedder leads detector" claim stays an unresolved hypothesis (withdrawn as QA v7 result, per program decision). This task is CPU-only and gates FIR-17 entirely — no FIR-17 slice runs before this task's D-02 decision is recorded.

**Interim identity-error definition (verbatim from the program packet — do not paraphrase):**

> a mated open-set search unit (`fir_bakeoff_run.MatedSearchUnit`) that is an FNIR miss at the FIR-13 gate tau (`_is_fnir_miss`), on the FIR-14 CV5 re-baseline run, DIAGNOSTIC tier.

This definition is provisional to this task: it reads FIR-13's gate contract (`select_gate_point`) for `tau`, and FIR-14's CV5 re-baseline output (DIAGNOSTIC tier — Golden-150 is not yet FIR-11-remediated) as the run it measures. Both are hard dependencies (below).

## Constraints

- **CPU only, $0.** No GPU leg beyond the buffalo comparison arms, which run on CPU via `buffalo_bench.py` (`_ort_session_options()` pins single-thread CPUExecutionProvider).
- **No training anywhere.** This task measures; it does not adapt weights. Distinct from FIR-7's PEFT adapters, which stay behind `TRAINING_DECISION`/D-01.
- **DIAGNOSTIC tier ceiling.** Golden-150 is not yet remediated by FIR-11 R1 at the time this task runs against the FIR-14 CV5 baseline; every number here is DIAGNOSTIC, never CONFIRMATORY. State this on every output artifact.
- **Withdrawn numbers never cited as evidence**: M-12 (0.865/0.321), recall 0.504, 2.73 faces/image, any pre-CVUP-1 artifact. "Embedder leads detector" stays a hypothesis this task tests, not evidence this task assumes.
- **Buffalo output ban applies to arms (c)/(d).** Buffalo (`buffalo_bench.BuffaloFusedLeg`) is used only as a comparison arm's embedder, never as a training target or pseudo-label source (mirrors FIR-7's Buffalo Output Ban — Wall 1 license, Wall 2 judge contamination — even though this task trains nothing, the same non-contamination discipline applies to arm selection: buffalo scores here are diagnostic output, never used to filter or re-weight the FIR-17 D-02 decision beyond the share numbers themselves).
- **Paired-bootstrap discipline on every share and every ladder gap** (B=2000, `resampling_unit="image"`, fixed seed, reported per run).
- **`masked_cosine` has exactly one definition, in production infrastructure, from the start (DD-14 — supersedes any eval-local draft).** This task defines `masked_cosine(a, b, mask) -> float` in NEW `apps/prototype-description-service/recognition/infrastructure/embeddings/masked_similarity.py` (settings-independent, no eval-harness or settings imports); `occlusion_ladder.py` imports it rather than redefining it. FIR-17 S1 reuses the same import; FIR-17 S4 only adds the import-isolation confirmation test (`test_masked_similarity.py::test_single_definition_no_settings_import`) — it does not move or duplicate the function. `centroid_utils.py` is explicitly NOT this location (DD-14).
- **No golden-150 figure produced here may be quoted as a live baseline outside this task's own report** — every number cites the FIR-14 CV5 run id and the DIAGNOSTIC tier label.

## Workflow Principles

- Measure before optimizing [PRINCIPLE #15] — this task exists so FIR-17 does not guess which stage to fix.
- Selection and gating are different data: the attribution split reads FIR-14's already-sealed CV5 run; it opens no new seal (FIR-13's K/α budget is untouched by this task).
- Every share and every ladder gap reports a paired-bootstrap CI, never a point estimate alone [EVAL-19] [AUDIT-04].
- The oracle-before-predicted rung ordering is deliberate: it establishes the ceiling (oracle mask) before spending any engineering effort on the predicted-mask approximation FIR-17 would ship.

## Terminology

- **Identity error**: per the interim definition above (verbatim, task-scoped).
- **Alignment share**: `FNIR(a) − FNIR(b)` — the fraction of identity error attributable to using detector-native landmarks vs reference landmarks, holding the embedder fixed at SFace. This is the ONLY cleanly isolated share this task computes (per DD-11: `BuffaloFusedLeg` re-detects internally and cannot honor externally supplied landmarks, so no arm pair holds landmarks fixed while swapping embedder family — see "Buffalo reference gap" below).
- **Buffalo reference gap**: `FNIR(a) − FNIR(buffalo_reference)`, where `buffalo_reference = mean(FNIR(c), FNIR(d))` (arms (c)/(d) are expected statistically indistinguishable from each other since `BuffaloFusedLeg.detect` ignores the nominal landmark-source distinction — reporting both is transparency, not two independent measurements). This is a **whole-pipeline reference contrast** (own detection + own alignment + own embedder, all three confounded together), NOT an isolated embedder share. It is never used to assign the D-02 leg by direct isolation, only as elimination evidence in the verdict table below (DD-11).
- ~~Embedder share~~ (removed per DD-11): no arm pair in this task holds landmarks fixed while varying only the embedder, so an isolated "embedder share" is not measurable here. `AttributionResult` therefore does not carry an `embedder_share` field (see S1 below); the D-02 verdict's EMBEDDER branch is inferred by elimination from the buffalo reference gap, never from a direct share.
- **Reference landmarks**: landmarks NOT produced by the detector under test. **Verified: no such artifact exists for Golden-150 today** — `landmark_cache.py` (`apps/prototype-description-service/scripts/eval_harness/landmark_cache.py`) freezes landmarks from a single **YuNet** detector pass (`LANDMARK_CACHE_MODEL_ID = "yunet"`, `build_landmark_cache()`), i.e. it caches the *candidate detector's own* output for placement geometry, not an independent/GT landmark set. S1a below is therefore operator labour: hand-marked 5-point landmarks for the FIR-11 R1 probe subset.
- **Oracle mask**: ground-truth occlusion region, known by construction (synthetic twins) or hand-labeled (real occluded probes, ≤30, via `anatomy_region_stats`).
- **Predicted mask**: the mask a runtime-feasible detector would produce today — `compute_occlusion_severity`'s two-eye-patch proxy (`face_quality_factors.py:82-105`), the only predictor that exists pre-FIR-17.
- **`LadderRung`**: `{NONE, ORACLE, PREDICTED}` — see S2.
- **`masked_cosine`** (production, DD-14): cosine similarity restricted to a dimension support mask on the 128-D SFace vector; single definition in `masked_similarity.py`, imported (not redefined) by the eval harness.
- **`RegionVisibility`**: a `tuple[float, float, float, float, float]` in fixed `REGION_NAMES` order `("right_eye", "left_eye", "nose", "mouth_right", "mouth_left")`, each value in `[0.0, 1.0]` (DD-15).
- **`SupportMap`**: the loaded/validated form of `sface-support-map-v1.json` — exactly 5 region names, 128-D index bounds, no duplicate dims (DD-13).

## Current State Analysis

- **Works**: `fir_bakeoff_run.py` (`MatedSearchUnit`, `_is_fnir_miss`, `RunReport`), `open_set_identification.py` (`IETPoint`, `fnir_fpi_at_threshold`), `synthetic_occlusion.py` (`generate_twin_specs`, `anatomy_region_stats(mask, landmarks_px)` verified at lines 762–784 matching the packet exactly), `buffalo_bench.py` (`BuffaloFusedLeg`, CPU-only via `_ort_session_options()`), `landmark_cache.py` (offline YuNet-only landmark freeze) — all exist on `main` per the packet's verified anchor inventory.
- **Broken/missing**: no attribution harness (T-01 unaddressed, QA v8: "NO anchor exists in the tree today"); no reference/GT landmark artifact for Golden-150 (verified above — `landmark_cache.py` is detector-native, not reference); no oracle-occlusion-ladder scorer.
- **Misleading if untouched**: it is tempting to assume FIR-11 R1's remediated corpus is already the input here — it is not. This task deliberately runs on the FIR-14 CV5 DIAGNOSTIC-tier baseline (pre-remediation); re-running on the remediated corpus is FIR-16's job, not this task's.
- **Adjacent**: FIR-13 supplies the gate tau this task's FNIR-miss definition reads; FIR-14 supplies the CV5 run this task scores; FIR-17 consumes this task's D-02 decision as its branch condition.

## Target Outcome

Two artifacts land: `benchmarks/results/attribution-t01-<date>/attribution.json` (shares + CIs + toolchain) and `benchmarks/results/attribution-t01-<date>/REPORT.md` (leg verdict in prose). Plus the oracle-ladder result showing whether visible-support matching has any headroom at all: if the oracle gap's 95% CI includes 0, FIR-17's masking track (S1) is PROVISIONALLY PARKED at $0 before any production code is written — DIAGNOSTIC-tier evidence can park a track, never terminate it; termination requires ADMISSIBLE evidence post FIR-11 R1. An MCP decision (`firplan_d02_attribution_<date>`) records the verdict FIR-17 branches on.

## Context Loading

- Rules: `docs/workbay/rules/testing-python.md`, `docs/workbay/rules/backend-python-guidelines.md`.
- Contracts: none external (eval-harness internal).
- Prior plans (read, do not restate): `docs/tasks/fir/FIR-13-open-set-gate-contract-task-plan.md` (gate tau / `GateContract` / `select_gate_point`), `docs/tasks/fir/FIR-14-opencv5-rebaseline-task-plan.md` (CV5 run id, toolchain block), `docs/tasks/fir/FIR-11-gate-corpus-remediation-and-fir-rebaseline-task-plan.md` rev 7 (corpus status — Golden-150 30/30/17 remediation; NOT yet the input here).
- Handoff/MCP: FIR-13 gate-contract decision, FIR-14 CV5 run decision, this task's own decision `firplan_d02_attribution_<date>` once recorded.
- Heuristics: MEAS-07, EXP-24, AGT-02 (QA v8 T-01 canon set), AUDIT-04, EVAL-19, EVAL-01/16/18/28, EMB-01/11/12, CAL-01/04 — https://github.com/darce/heuristics-canon.

## Contract and Boundary Impact

Mostly none: eval-harness-internal work under `apps/prototype-description-service/scripts/eval_harness/`; no production runtime, schema, or cross-service surface is touched. One narrow exception (DD-14): `recognition/infrastructure/embeddings/masked_similarity.py::masked_cosine` is a new pure-math module in the production source tree (no settings import, no runtime call site added by this task) so FIR-17 S1 can import the same function instead of a second definition landing later. It is dead code from production's point of view until FIR-17 wires a caller.

## Proposed Solution

Four fixed-detector arms isolate the alignment share within SFace (arms a/b) and report Buffalo (arms c/d) as a whole-pipeline reference contrast only — never as an isolated embedder share (DD-11); a three-rung ladder isolates mask-prediction cost from matching-approach ceiling. Both read per-embedding-space operating points from FIR-13's `select_gate_point` (`tau_by_space`, keyed `"sface128"`/`"buffalo512"` — DD-01, never a single shared tau) and the FIR-14 CV5 run; neither opens a new FIR-13 seal.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| eval harness | `apps/prototype-description-service/scripts/eval_harness/attribution_split.py` (new) | 4-arm T-01 split harness |
| eval harness | `apps/prototype-description-service/scripts/eval_harness/occlusion_ladder.py` (new) | oracle/predicted ladder; imports `masked_cosine` (does not redefine it, DD-14) |
| production (pure math, DD-14) | `apps/prototype-description-service/recognition/infrastructure/embeddings/masked_similarity.py` (new) | single definition of `masked_cosine(a, b, mask) -> float`, settings-independent |
| eval harness | `apps/prototype-description-service/scripts/eval_harness/synthetic_occlusion.py` | new `oracle_region_visibility(mask, landmarks_px) -> tuple[float, float, float, float, float]` (DD-15/DD-13 five-region conversion) |
| production | `apps/prototype-description-service/recognition/infrastructure/face_pipeline/face_quality_factors.py` | new `estimate_region_visibility(crop_bgr, landmarks_112) -> RegionVisibility` (DD-15); `compute_occlusion_severity` unchanged |
| production (asset, DD-13) | `apps/prototype-description-service/recognition/infrastructure/face_pipeline/assets/sface-support-map-v1.json` (new) | versioned support-map asset produced by the offline attribution recipe |
| production (loader, DD-13) | `apps/prototype-description-service/recognition/infrastructure/face_pipeline/support_map.py` (new) | `load_support_map(path, *, expected_sha256) -> SupportMap`, fail-closed validation |
| protocol | `benchmarks/protocols/` (reference-landmark hand-marking procedure, if S1a proceeds) | operator runbook |
| tests | `apps/prototype-description-service/scene/tests/test_eval_harness_attribution_split.py` (new) | arm math, share formulas, bootstrap determinism, D-02 verdict table |
| tests | `apps/prototype-description-service/scene/tests/test_eval_harness_occlusion_ladder.py` (new) | `masked_cosine` invariants, `oracle_region_visibility`, ladder rungs, oracle-gap CI, empty-support handling |
| tests | `apps/prototype-description-service/recognition/tests/unit/test_face_quality_factors.py` | new case: `estimate_region_visibility` five-value/order/range contract, `landmarks=None` no-op |
| tests | `apps/prototype-description-service/recognition/tests/unit/test_support_map.py` (new) | `test_rejects_bad_sha256`, `test_rejects_out_of_range_dim`, `test_rejects_unknown_region` |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/scripts/eval_harness/fir_bakeoff_run.py` | `MatedSearchUnit`, `_is_fnir_miss` — the identity-error unit this task scores |
| `apps/prototype-description-service/scripts/eval_harness/landmark_cache.py` | source of detector-native landmarks; confirmed NOT a reference/GT source (see Terminology) |
| `apps/prototype-description-service/scripts/eval_harness/buffalo_bench.py` | `BuffaloFusedLeg` (287–382) — arms (c)/(d) whole-pipeline reference only, never an isolated embedder; CPU-only, re-detects internally (DD-11, caveat detailed in S1) |
| `apps/prototype-description-service/scripts/eval_harness/synthetic_occlusion.py` | `generate_twin_specs`, `anatomy_region_stats` — oracle-mask source for synthetic + hand-labeled real probes |
| `apps/prototype-description-service/scripts/eval_harness/gate_contract.py` (FIR-13) | `select_gate_point` — tau this task's FNIR-miss definition reads |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-description-service && python3 -m pytest scene/tests/test_eval_harness_attribution_split.py scene/tests/test_eval_harness_occlusion_ladder.py -q`
- Runtime-parity / environment checks: none (CPU-only offline scoring).
- Contract/fixture verification: `attribution.json` schema asserted by its own test; no external contract.
- Manual verification: operator reviews `REPORT.md` before recording the D-02 decision.

## Slice Delivery

### Slice 1: T-01 alignment-vs-embedder split harness

Implements: FIRG-040, FIRG-041, FIRG-042 (D-02 verdict table lives here).
**Goal**: Produce `alignment_share` (isolated, SFace-only) and the `buffalo_reference_gap` (whole-pipeline reference, DD-11) with paired-bootstrap CIs from four fixed-detector arms.

Changes:

- New `apps/prototype-description-service/scripts/eval_harness/attribution_split.py`:

```python
from dataclasses import dataclass
from collections.abc import Sequence

@dataclass(frozen=True)
class AttributionArm:
    """One of the four T-01 arms. Detector is fixed at the FIR-13 declared
    operating point across all four arms; only landmarks and embedder vary.
    Arms (c)/(d) are whole-pipeline reference arms only (DD-11) — see caveats."""
    name: str  # "a_detector_landmarks_sface" | "b_reference_landmarks_sface"
               # | "c_detector_landmarks_buffalo" | "d_reference_landmarks_buffalo"
    uses_reference_landmarks: bool
    embedder: str  # "sface" | "buffalo_l"

@dataclass(frozen=True)
class AttributionResult:
    alignment_share: float          # FNIR(a) - FNIR(b), SFace arms only (DD-11)
    alignment_share_ci: tuple[float, float]
    buffalo_reference_gap: float    # FNIR(a) - mean(FNIR(c), FNIR(d)); whole-pipeline
                                     # reference contrast, NEVER an isolated embedder
                                     # share (DD-11) — read only by the elimination rule
                                     # in the D-02 verdict table below.
    buffalo_reference_gap_ci: tuple[float, float]
    n_units: int
    tau_by_space: dict[str, float]  # {"sface128": ..., "buffalo512": ...} — DD-01,
                                     # each from FIR-13 gate_contract.select_gate_point
                                     # at the same declared FPI budget; bootstrap
                                     # resampling holds each space's tau fixed.
    toolchain: dict[str, str]       # from FIR-14 CV5 run's toolchain block
    caveats: tuple[str, ...]        # e.g. cross-family arm ambiguity (below)

def run_attribution_split(
    *,
    mated_units: Sequence["fir_bakeoff_run.MatedSearchUnit"],
    reference_landmarks: dict[tuple[int, int], "np.ndarray"],  # (media_id, box_index) -> (5,2)
    tau_by_space: dict[str, float],   # DD-01 — "sface128" / "buffalo512" keys, each a
                                       # fixed per-space operating point; never a single
                                       # shared tau across the 128-D and 512-D spaces
    seed: int,
    b: int = 2000,
) -> AttributionResult: ...
```

- Arms (a) and (b) share the SFace embedder (`OrtSFaceEmbedder` / `OpenCVSFaceEmbedder` — `embed_batch` from `_common.py`) and are scored at `tau_by_space["sface128"]`; arms (c) and (d) route through `buffalo_bench.BuffaloFusedLeg` (287–382) and are scored at `tau_by_space["buffalo512"]`. **State explicitly in code comments and `REPORT.md`**: `BuffaloFusedLeg.detect` (317–341) re-detects internally rather than accepting externally supplied landmarks — arm (c)/(d)'s "detector landmarks"/"reference landmarks" distinction therefore does not hold for the buffalo arms the way it does for arms (a)/(b) (this is the finding DD-11 fixes). Consequently arms (c)/(d) are reported ONLY as `buffalo_reference_gap`, a whole-pipeline reference contrast against arm (a); they are never combined with arm (b) to form an isolated embedder share, and never feed the D-02 branch by direct isolation — only by the elimination rule in the verdict table below. This is the caveat field in `AttributionResult`; the report must say so in prose, not just in the CI width.
- Paired-bootstrap interval procedure (step by step, both quantities):
  1. Resample images with replacement, `B=2000`, fixed `seed`, holding each arm's `tau_by_space` entry fixed across all resamples (DD-01 — alignment interventions never re-select tau).
  2. Recompute both FNIR values in the share formula on the **same** resampled image set each iteration (paired — never resample the two arms independently).
  3. `alignment_share_ci` = 2.5th/97.5th percentile of the resampled `FNIR(a) − FNIR(b)` distribution; `buffalo_reference_gap_ci` = same percentiles of the resampled `FNIR(a) − mean(FNIR(c), FNIR(d))` distribution.
  4. Report `n_units` (mated search units entering the resample) alongside the CI so a narrow interval from a small `n_units` is visible, not hidden.
- **S1a (reference landmarks are operator labour — state this, do not silently substitute)**: since `landmark_cache.py` provides only detector-native (YuNet) landmarks, arm (b)/(d) needs an independent landmark set. S1a produces hand-marked 5-point landmarks (eye centers, nose tip, mouth corners) for the FIR-11 R1 30-probe subset only, using `benchmarks/tools/golden150-box-annotator.html` as the marking tool (existing corpus artifact, not code — verify current form supports 5-point landmark output before use, else extend it as an in-slice sub-task). This is **operator labour**, not automatable, and is called out as such in the slice checklist.

**D-02 verdict table (deterministic, pinned constants)** — inputs are `alignment_share`/`alignment_share_ci`, `buffalo_reference_gap`/`buffalo_reference_gap_ci`, and `n_units`. Pinned constant: `MATERIAL_SHARE_FLOOR = 0.03` (3 percentage points of FNIR — the minimum share magnitude treated as a real effect rather than noise) and `MIN_ATTRIBUTABLE_UNITS = 10` (below this, `n_units` is too small to trust any CI regardless of point estimate). Evaluated in this order:

  1. `n_units < MIN_ATTRIBUTABLE_UNITS` → **INCONCLUSIVE** (`caveats` includes `"insufficient_units"`), regardless of the two point estimates below.
  2. `alignment_share_ci` excludes 0 AND `alignment_share_ci[0] >= MATERIAL_SHARE_FLOOR` AND (`buffalo_reference_gap_ci` includes 0 OR `buffalo_reference_gap_ci[0] < MATERIAL_SHARE_FLOOR`) → **DETECTOR** (alignment leg drives the error; FIR-17 targets pose/landmark work).
  3. `alignment_share_ci` includes 0 OR `alignment_share_ci[0] < MATERIAL_SHARE_FLOOR` (alignment intervention within SFace shows no material effect) AND `buffalo_reference_gap_ci` excludes 0 AND `buffalo_reference_gap_ci[0] >= MATERIAL_SHARE_FLOOR` → **EMBEDDER** (by elimination only: the isolated alignment intervention failed to close the gap, but a different whole pipeline does materially better; caveat `"embedder_verdict_by_elimination_not_isolation"` is mandatory in `REPORT.md`).
  4. Both `alignment_share_ci[0] >= MATERIAL_SHARE_FLOOR` AND `buffalo_reference_gap_ci[0] >= MATERIAL_SHARE_FLOOR` → **BOTH**.
  5. Any other combination (both CIs include 0, or both point estimates fall below `MATERIAL_SHARE_FLOOR`) → **INCONCLUSIVE**.

Proof:

- `cd apps/prototype-description-service && python3 -m pytest scene/tests/test_eval_harness_attribution_split.py -q` — asserts share-formula arithmetic on synthetic fixtures, bootstrap determinism with a fixed seed, that the buffalo-arm caveat field is populated whenever arms (c)/(d) are used, that `tau_by_space` is never collapsed to a single value, and all five rows of the D-02 verdict table (including the `n_units` floor and the negative/overlapping/inconclusive interval cases).

### Slice 2: Oracle-before-predicted occlusion ladder

Implements: FIRG-043, FIRG-044 (`masked_cosine` in `masked_similarity.py`, reused by FIR-17 S1).
**Goal**: Measure the oracle-mask ceiling before the predicted-mask approximation, and decide whether FIR-17's masking approach has any headroom.

Changes:

- **Five-region geometry (pinned, shared by both conversion functions below)**: exactly five named regions, in this fixed order, keyed to `aligner.SFACE_CANONICAL_LANDMARKS_112` (`recognition/infrastructure/face_pipeline/aligner.py:28-37` — the same reference points `FivePointAligner` aligns to, so both conversions read patches from the same 112×112 canonical crop space):
  `REGION_NAMES: tuple[str, ...] = ("right_eye", "left_eye", "nose", "mouth_right", "mouth_left")`, centered respectively on `SFACE_CANONICAL_LANDMARKS_112[0..4]`. Patch half-width `_REGION_PATCH_HALF_PX = 8` (matches `face_quality_factors._EYE_PATCH_HALF`, reused for all five regions, not just the two eyes). Denominator for every region's visibility fraction is the clipped-to-image-bounds patch pixel count (never the nominal `(2*half)**2` — patches at crop edges are smaller); a region whose clipped patch has zero pixels reports visibility `0.0` (fully occluded/out-of-frame, fail-closed toward "not visible").

- New `apps/prototype-description-service/scripts/eval_harness/occlusion_ladder.py`:

```python
from enum import StrEnum
from dataclasses import dataclass
from recognition.infrastructure.embeddings.masked_similarity import masked_cosine  # DD-14 — single definition, imported not redefined

class LadderRung(StrEnum):
    NONE = "none"           # baseline, no occlusion handling
    ORACLE = "oracle"       # ground-truth mask (synthetic twins, or hand-drawn for real probes)
    PREDICTED = "predicted" # estimate_region_visibility five-region proxy (DD-15)

@dataclass(frozen=True)
class LadderPoint:
    rung: LadderRung
    fnir: float | None
    n_mated: int
    measured: bool

def score_ladder(
    *,
    twin_specs: "Sequence[synthetic_occlusion.OcclusionTwinSpec]",
    real_probes: "Sequence[AttributionArm]",  # A_true_occluder / B_eyewear strata only
    support_mask_recipe: "Callable[[np.ndarray], np.ndarray]",
    tau: float,
    seed: int,
) -> dict[LadderRung, LadderPoint]: ...
```

`masked_cosine` itself is NOT redefined here (DD-14): `apps/prototype-description-service/recognition/infrastructure/embeddings/masked_similarity.py` (new) is the single production-tree definition —

```python
def masked_cosine(
    a: "np.ndarray",               # (128,) SFace embedding
    b: "np.ndarray",                # (128,)
    mask: "np.ndarray",             # (128,) bool — True = dimension retained
) -> float:
    """Cosine restricted to `mask` dimensions. Settings-independent — no
    settings/runtime import (asserted by test_masked_similarity.py's
    import-isolation test, added in full by FIR-17 S4; this task's own test
    file only asserts the invariants below).
    Invariants:
      - full mask (all True)  == ordinary cosine similarity (matches
        recognition.application.clustering.centroid_utils.compute_similarity
        on the same pair, up to float32 rounding)
      - empty mask (all False) raises ValueError
    """
```

- **Two conversion functions turn today's two occlusion helpers into the five-region visibility `score_ladder`/`support_mask_recipe` need (neither existing helper produces this shape today):**
  1. **Oracle conversion (ground-truth mask → exact visibility)** — new `synthetic_occlusion.py::oracle_region_visibility(mask: np.ndarray, landmarks_px: np.ndarray | Sequence[Sequence[float]]) -> tuple[float, float, float, float, float]`. For each of the five `REGION_NAMES` points (scaled from `SFACE_CANONICAL_LANDMARKS_112` into `mask`'s pixel space via the same affine used to build the twin, `landmarks_px` gives the five real-image landmark positions directly so no rescale is needed when `mask` is already in image space), extract the `_REGION_PATCH_HALF_PX`-half square patch, clip to `mask` bounds, and return `1.0 − (occluded_pixels_in_patch / clipped_patch_pixel_count)` per region, in `REGION_NAMES` order. This supersedes `anatomy_region_stats` for ladder purposes (`anatomy_region_stats`'s three face-relative *band* fractions — `lower_face_frac`/`eye_band_frac`/`upper_frac`, verified `synthetic_occlusion.py:762-784` — are a different, coarser aggregation kept for its own existing pin tests and NOT reused here, since it cannot report the five discrete regions this ladder needs). Zero-pixel-mask input (`np.where(mask)` empty) returns all-ones (no occlusion) rather than a divide-by-zero.
  2. **Predicted conversion (crop → estimated visibility)** — new `face_quality_factors.py::estimate_region_visibility(crop_bgr: np.ndarray, landmarks_112: np.ndarray | None) -> tuple[float, float, float, float, float]`. Extends `compute_occlusion_severity`'s existing two-eye-patch activity computation (`_patch_stats`, `_as_gray_u8`, same `base_var`/`base_edge` normalization, `face_quality_factors.py:82-105`) to all five `REGION_NAMES` points instead of averaging just the two eyes into one float: compute `activity = 0.5*(var/base_var) + 0.5*(edge/base_edge)` per region exactly as today's two-eye loop does, then `visibility = clamp(activity, 0.0, 1.0)` per region (activity≥1 → fully visible; activity→0 → fully occluded — same mapping direction `compute_occlusion_severity` already uses, just per-region instead of pre-averaged). `landmarks_112=None` (no landmarks available) returns `(1.0, 1.0, 1.0, 1.0, 1.0)` (all-visible no-op, matching DD-15's production no-op convention so FIR-17 can promote this function verbatim). `compute_occlusion_severity` itself is unchanged and stays the two-eye-only production severity scalar other callers already depend on; `estimate_region_visibility` is additive.
  - Both conversions are covered by `test_eval_harness_occlusion_ladder.py` (oracle) and a matching case in `recognition/tests/unit/test_face_quality_factors.py` (predicted) asserting: output length 5, order matches `REGION_NAMES`, every value in `[0.0, 1.0]`, and the `landmarks=None` all-ones no-op.

- **Rung 0 (NONE)**: baseline FNIR on the occluded stratum, no masking.
- **Rung 1 (ORACLE)**: exact masks via `oracle_region_visibility` above. Synthetic twins get their mask by construction (`synthetic_occlusion.generate_twin_specs`); real probes in `A_true_occluder`/`B_eyewear` get hand-drawn masks (operator labour, ≤30 probes).
- **Rung 2 (PREDICTED)**: `estimate_region_visibility` above (five-region extension of the former two-eye-patch proxy). This rung exists to quantify the gap FIR-17's production wiring would need to close, not to ship anything.
- **Support-mask attribution recipe (spelled out step by step, PDSN-style, constants pinned)**: to build `support_mask_recipe`, (1) take a set of clean (unoccluded) twin bases; (2) for each of the five `REGION_NAMES`, synthetically occlude only that region (using the same patch geometry above) and re-embed; (3) compute the per-dimension absolute delta between the clean and region-occluded embedding vectors; (4) rank the 128 dimensions by delta magnitude per region; (5) a dimension is attributed to a region if that region's delta ranks in its top decile (`ATTRIBUTION_DECILE = 0.10`, pinned) across a fixed sample of clean twins (`N_ATTRIBUTION_TWINS = 30`, pinned — same as the FIR-11 R1 probe-subset size, reusing that sample); if two regions both rank a dimension in their top decile (multi-region overlap), attribute the dimension to BOTH regions (a dimension may support more than one region — this is not a partition); a dimension attributed to zero regions across all twins is left permanently unattributed and `support_mask_recipe` always maps it to `False` (masked out) regardless of any region's visibility, since no region's occlusion measurably moves it; (6) `support_mask_recipe(visibility_scores: tuple[float, float, float, float, float]) -> np.ndarray` (128,) bool) then returns `True` for every dimension whose attributed region(s) have visibility ABOVE `VISIBILITY_FLOOR = 0.5` for AT LEAST ONE of their attributed regions (union rule — a multi-region dimension survives if any one of its regions is visible), `False` otherwise; if `support_mask_recipe`'s output would be all-`False` (every attributed region below the floor and no unattributed dimensions rescue it), `masked_cosine` receives an all-`False` mask and — per `masked_cosine`'s own invariant above — raises `ValueError`; `score_ladder` catches this per-probe and records that probe as `measured=False` for Rung 1/2 rather than crashing the whole run (empty-support handling). This attribution step runs once (offline, seeded) and its output ships as `recognition/infrastructure/face_pipeline/assets/sface-support-map-v1.json` (DD-13) — this task produces the recipe and a first version of the asset; FIR-17 owns the runtime loader (`support_map.py::load_support_map`, DD-13) and shipping it behind a knob.
- **Oracle gap** = `FNIR(rung0) − FNIR(rung1 with masked_cosine applied)`. If the oracle gap's 95% CI includes 0, record that verbatim in `REPORT.md` as the reason FIR-17 S1 is PARKED (not terminated) at $0 (per the branch rule FIR-17 opens with) — DIAGNOSTIC-tier oracle evidence may only provisionally park the masking track; a permanent kill requires ADMISSIBLE-tier evidence post FIR-11 R1.

Proof:

- `cd apps/prototype-description-service && python3 -m pytest scene/tests/test_eval_harness_occlusion_ladder.py -q` — asserts `masked_cosine` invariants (full mask == `compute_similarity`; empty mask raises), `oracle_region_visibility`'s five-value/order/range contract, rung ordering (rung1 FNIR ≤ rung0 FNIR on synthetic fixtures where the mask is exact by construction), the `VISIBILITY_FLOOR`/`ATTRIBUTION_DECILE` constants, the all-`False`-mask → `measured=False` empty-support path, and bootstrap determinism on the oracle-gap CI.
- `cd apps/prototype-description-service && python3 -m pytest recognition/tests/unit/test_face_quality_factors.py -q` — covers the new `estimate_region_visibility` case (five-value/order/range contract, `landmarks=None` no-op) alongside the existing `compute_occlusion_severity` tests (unchanged).

### Slice 3: Attribution report + D-02 decision packet

Implements: FIRG-045 (decision D-02).
**Goal**: Name the leg FIR-17 branches on, in a decision the MCP records.

Changes:

- `benchmarks/results/attribution-t01-<date>/REPORT.md`: states the leg (`alignment` | `embedder` | `both` | `inconclusive`) per the deterministic D-02 verdict table (S1), with `alignment_share`'s and `buffalo_reference_gap`'s CIs, the buffalo whole-pipeline-reference caveat (and, when the verdict is EMBEDDER, the mandatory elimination-not-isolation caveat), the oracle-gap verdict from S2, and the DIAGNOSTIC tier label on every number.
- MCP decision `firplan_d02_attribution_<date>` template text (operator-facing, recorded via `record_event`):

  ```
  decision_id: firplan_d02_attribution_<date>
  task_ref: FIR-15
  summary: T-01 attribution split + oracle occlusion ladder, DIAGNOSTIC tier (FIR-14 CV5 run <run-id>)
  alignment_share: <value> CI[<lo>, <hi>]
  buffalo_reference_gap: <value> CI[<lo>, <hi>]  # whole-pipeline reference only, DD-11
  tau_by_space: {sface128: <value>, buffalo512: <value>}
  oracle_gap: <value> CI[<lo>, <hi>]
  verdict: EMBEDDER | DETECTOR | BOTH | INCONCLUSIVE  # per the D-02 verdict table, S1
  fir17_branch: <slices FIR-17 runs per this verdict, per FIR-17's branch rule>
  caveats: buffalo whole-pipeline reference is never an isolated embedder share (see S1, DD-11); EMBEDDER verdict (if any) is by elimination, not isolation; DIAGNOSTIC tier (Golden-150 not yet FIR-11-remediated)
  ```

- This decision is the sole input FIR-17 branches on — FIR-17's task plan opens with the branch-rule table keyed to this decision's `verdict` field.

Proof:

- `REPORT.md` reviewed by the operator before the decision is recorded (manual verification step; no automated proof beyond S1/S2's tests, which this slice's numbers are drawn from verbatim).

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- |
| `fir15-eval` | `apps/prototype-description-service/scripts/eval_harness/attribution_split.py`, `occlusion_ladder.py`, `apps/prototype-description-service/scene/tests/test_eval_harness_attribution_split.py`, `test_eval_harness_occlusion_ladder.py` | FIR-13 (gate contract merged), FIR-14 (CV5 re-baseline run available) | `python3 -m pytest scene/tests/test_eval_harness_attribution_split.py scene/tests/test_eval_harness_occlusion_ladder.py -q` |

Single lane — S1/S2/S3 are sequential within it (S3 is a report + decision, not code).

### Merge Order

`fir15-eval` → `feature/fir-15` → `main` (after FIR-13 and FIR-14 are both merged; this task cannot start its measurement until both land).

### Manifest

```bash
make lane-manifest-init TASK=fir-15 LANE_IDS='fir15-eval' TASK_PLAN=docs/tasks/fir/FIR-15-attribution-split-and-oracle-ladder-task-plan.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: single-lane dispatch via `dispatch_lane_work`.
- **Shell fallback**: direct implementation in `feature/fir-15` worktree.

---

## Consolidated Checklist

> **Checklist scope rule:** describes work being delivered, not finding status. Finding status is queried from the handoff DB.

## Context and Ownership

- [ ] Loaded FIR-13's gate contract and FIR-14's CV5 re-baseline run before writing `attribution_split.py`.
- [ ] Confirmed no external contract is touched (eval-harness internal).

### Checklist for Slice 1: T-01 alignment-vs-embedder split harness

- [ ] `attribution_split.py` implements the four arms with detector fixed at the FIR-13 operating point, each embedding space scored at its own `tau_by_space` entry (DD-01).
- [ ] `AttributionResult` carries `alignment_share` (SFace arms a/b only) and `buffalo_reference_gap` (whole-pipeline reference, arms c/d) — no `embedder_share` field (DD-11).
- [ ] Buffalo whole-pipeline caveat (arms c/d re-detect internally, never an isolated embedder share) is recorded in `AttributionResult.caveats` and surfaced in `REPORT.md`.
- [ ] The deterministic D-02 verdict table (`MATERIAL_SHARE_FLOOR`, `MIN_ATTRIBUTABLE_UNITS`, all five rows) is implemented exactly as specified.
- [ ] S1a reference-landmark production is scoped as operator labour on the FIR-11 R1 30-probe subset, not silently automated.
- [ ] `test_eval_harness_attribution_split.py` covers share arithmetic, `tau_by_space` per-space isolation, and paired-bootstrap determinism.

### Checklist for Slice 2: Oracle-before-predicted occlusion ladder

- [ ] `occlusion_ladder.py` implements `LadderRung` and `score_ladder`, importing production `masked_cosine` from `masked_similarity.py` (DD-14) rather than redefining it.
- [ ] `oracle_region_visibility` (`synthetic_occlusion.py`) and `estimate_region_visibility` (`face_quality_factors.py`) both implemented against the pinned `REGION_NAMES` order and `_REGION_PATCH_HALF_PX = 8` geometry (DD-15).
- [ ] Support-mask attribution recipe implemented exactly as spelled out (5-region occlusion deltas → per-dimension attribution with `ATTRIBUTION_DECILE`/`N_ATTRIBUTION_TWINS` pinned → `VISIBILITY_FLOOR` union rule → versioned JSON asset), including the all-`False`-mask empty-support path (`measured=False`, DD-13).
- [ ] `sface-support-map-v1.json` produced and validated at load time via `support_map.py::load_support_map` (exactly-5 region names, 128-D index bounds, no duplicate dims, sha256 against the external manifest entry, fail-closed) (DD-13).
- [ ] Oracle-gap CI computed and its zero-inclusion case recorded verbatim as FIR-17's kill condition for S1.
- [ ] `test_eval_harness_occlusion_ladder.py` covers `masked_cosine` invariants, `oracle_region_visibility`'s contract, ladder-rung ordering, and the empty-support path; `test_face_quality_factors.py` covers `estimate_region_visibility`; `test_support_map.py` covers the three fail-closed loader cases.

### Checklist for Slice 3: Attribution report + D-02 decision packet

- [ ] `REPORT.md` states the leg verdict (per the D-02 verdict table) with `alignment_share`'s and `buffalo_reference_gap`'s CIs and the DIAGNOSTIC tier label.
- [ ] MCP decision `firplan_d02_attribution_<date>` recorded with the `verdict` and `fir17_branch` fields FIR-17 reads.

## Review Readiness

- [ ] No boundary-touching implementation (none exists in this task) is left without matching test evidence.
- [ ] Runtime-parity checks: n/a (CPU-only offline scoring).
- [ ] Handoff decision records the verdict, the shares, the oracle-gap result, and the FIR-17 branch it implies.

## Stretch Goals

- [ ] Extend `benchmarks/tools/golden150-box-annotator.html` with native 5-point landmark output if S1a's hand-marking proves too slow in the existing tool.

## Success Criteria

- [ ] `alignment_share` and `buffalo_reference_gap` each report a paired-bootstrap CI on the FIR-14 CV5 DIAGNOSTIC-tier run; `tau_by_space` carries one independently selected operating point per embedding space (DD-01).
- [ ] Oracle-before-predicted ladder reports a gap with a CI; the zero-inclusion case is explicitly actionable for FIR-17.
- [ ] MCP decision `firplan_d02_attribution_<date>` recorded and cited by FIR-17's branch rule.
- [ ] `handoff_close_check(enforce=True)` passes; task `done` + archived.
