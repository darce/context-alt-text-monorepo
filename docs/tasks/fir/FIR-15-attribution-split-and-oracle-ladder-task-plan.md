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
- **`masked_cosine` here is EVAL-ONLY.** It is a diagnostic function inside `occlusion_ladder.py`; FIR-17 S4 later moves the *production* equivalent into a shared pure module so both read the same code path — this task does not perform that move, it only defines the eval-only version and states the shared-module obligation FIR-17 inherits.
- **No golden-150 figure produced here may be quoted as a live baseline outside this task's own report** — every number cites the FIR-14 CV5 run id and the DIAGNOSTIC tier label.

## Workflow Principles

- Measure before optimizing [PRINCIPLE #15] — this task exists so FIR-17 does not guess which stage to fix.
- Selection and gating are different data: the attribution split reads FIR-14's already-sealed CV5 run; it opens no new seal (FIR-13's K/α budget is untouched by this task).
- Every share and every ladder gap reports a paired-bootstrap CI, never a point estimate alone [EVAL-19] [AUDIT-04].
- The oracle-before-predicted rung ordering is deliberate: it establishes the ceiling (oracle mask) before spending any engineering effort on the predicted-mask approximation FIR-17 would ship.

## Terminology

- **Identity error**: per the interim definition above (verbatim, task-scoped).
- **Alignment share**: `FNIR(a) − FNIR(b)` — the fraction of identity error attributable to using detector-native landmarks vs reference landmarks, holding the embedder fixed.
- **Embedder share**: `FNIR(b) − FNIR(d)` — the fraction attributable to the embedder family, holding landmarks fixed at the reference set.
- **Reference landmarks**: landmarks NOT produced by the detector under test. **Verified: no such artifact exists for Golden-150 today** — `landmark_cache.py` (`apps/prototype-description-service/scripts/eval_harness/landmark_cache.py`) freezes landmarks from a single **YuNet** detector pass (`LANDMARK_CACHE_MODEL_ID = "yunet"`, `build_landmark_cache()`), i.e. it caches the *candidate detector's own* output for placement geometry, not an independent/GT landmark set. S1a below is therefore operator labour: hand-marked 5-point landmarks for the FIR-11 R1 probe subset.
- **Oracle mask**: ground-truth occlusion region, known by construction (synthetic twins) or hand-labeled (real occluded probes, ≤30, via `anatomy_region_stats`).
- **Predicted mask**: the mask a runtime-feasible detector would produce today — `compute_occlusion_severity`'s two-eye-patch proxy (`face_quality_factors.py:82-105`), the only predictor that exists pre-FIR-17.
- **`LadderRung`**: `{NONE, ORACLE, PREDICTED}` — see S2.
- **`masked_cosine`** (eval-only, this task): cosine similarity restricted to a dimension support mask on the 128-D SFace vector.

## Current State Analysis

- **Works**: `fir_bakeoff_run.py` (`MatedSearchUnit`, `_is_fnir_miss`, `RunReport`), `open_set_identification.py` (`IETPoint`, `fnir_fpi_at_threshold`), `synthetic_occlusion.py` (`generate_twin_specs`, `anatomy_region_stats(mask, landmarks_px)` verified at lines 762–784 matching the packet exactly), `buffalo_bench.py` (`BuffaloFusedLeg`, CPU-only via `_ort_session_options()`), `landmark_cache.py` (offline YuNet-only landmark freeze) — all exist on `main` per the packet's verified anchor inventory.
- **Broken/missing**: no attribution harness (T-01 unaddressed, QA v8: "NO anchor exists in the tree today"); no reference/GT landmark artifact for Golden-150 (verified above — `landmark_cache.py` is detector-native, not reference); no oracle-occlusion-ladder scorer.
- **Misleading if untouched**: it is tempting to assume FIR-11 R1's remediated corpus is already the input here — it is not. This task deliberately runs on the FIR-14 CV5 DIAGNOSTIC-tier baseline (pre-remediation); re-running on the remediated corpus is FIR-16's job, not this task's.
- **Adjacent**: FIR-13 supplies the gate tau this task's FNIR-miss definition reads; FIR-14 supplies the CV5 run this task scores; FIR-17 consumes this task's D-02 decision as its branch condition.

## Target Outcome

Two artifacts land: `benchmarks/results/attribution-t01-<date>/attribution.json` (shares + CIs + toolchain) and `benchmarks/results/attribution-t01-<date>/REPORT.md` (leg verdict in prose). Plus the oracle-ladder result showing whether visible-support matching has any headroom at all: if the oracle gap's 95% CI includes 0, FIR-17's adapter track (S1) is dead at $0 before any production code is written. An MCP decision (`firplan_d02_attribution_<date>`) records the verdict FIR-17 branches on.

## Context Loading

- Rules: `docs/workbay/rules/testing-python.md`, `docs/workbay/rules/backend-python-guidelines.md`.
- Contracts: none external (eval-harness internal).
- Prior plans (read, do not restate): `docs/tasks/fir/FIR-13-open-set-gate-contract-task-plan.md` (gate tau / `GateContract` / `select_gate_point`), `docs/tasks/fir/FIR-14-opencv5-rebaseline-task-plan.md` (CV5 run id, toolchain block), `docs/tasks/fir/FIR-11-gate-corpus-remediation-and-fir-rebaseline-task-plan.md` rev 7 (corpus status — Golden-150 30/30/17 remediation; NOT yet the input here).
- Handoff/MCP: FIR-13 gate-contract decision, FIR-14 CV5 run decision, this task's own decision `firplan_d02_attribution_<date>` once recorded.
- Heuristics: MEAS-07, EXP-24, AGT-02 (QA v8 T-01 canon set), AUDIT-04, EVAL-19, EVAL-01/16/18/28, EMB-01/11/12, CAL-01/04 — https://github.com/darce/heuristics-canon.

## Contract and Boundary Impact

None. Eval-harness-internal work under `apps/prototype-description-service/scripts/eval_harness/`; no production runtime, schema, or cross-service surface is touched.

## Proposed Solution

Four fixed-detector arms isolate alignment from embedder; a three-rung ladder isolates mask-prediction cost from matching-approach ceiling. Both read the FIR-13 tau and the FIR-14 CV5 run; neither opens a new FIR-13 seal.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| eval harness | `apps/prototype-description-service/scripts/eval_harness/attribution_split.py` (new) | 4-arm T-01 split harness |
| eval harness | `apps/prototype-description-service/scripts/eval_harness/occlusion_ladder.py` (new) | oracle/predicted ladder + eval-only `masked_cosine` |
| protocol | `benchmarks/protocols/` (reference-landmark hand-marking procedure, if S1a proceeds) | operator runbook |
| tests | `apps/prototype-description-service/scene/tests/test_eval_harness_attribution_split.py` (new) | arm math, share formulas, bootstrap determinism |
| tests | `apps/prototype-description-service/scene/tests/test_eval_harness_occlusion_ladder.py` (new) | `masked_cosine` invariants, ladder rungs, oracle-gap CI |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/scripts/eval_harness/fir_bakeoff_run.py` | `MatedSearchUnit`, `_is_fnir_miss` — the identity-error unit this task scores |
| `apps/prototype-description-service/scripts/eval_harness/landmark_cache.py` | source of detector-native landmarks; confirmed NOT a reference/GT source (see Terminology) |
| `apps/prototype-description-service/scripts/eval_harness/buffalo_bench.py` | `BuffaloFusedLeg` (287–382) — arms (c)/(d) embedder; CPU-only, re-detects internally (ambiguity noted in S1) |
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

**Goal**: Produce `alignment_share` and `embedder_share` with paired-bootstrap CIs from four fixed-detector arms.

Changes:

- New `apps/prototype-description-service/scripts/eval_harness/attribution_split.py`:

```python
from dataclasses import dataclass
from collections.abc import Sequence

@dataclass(frozen=True)
class AttributionArm:
    """One of the four T-01 arms. Detector is fixed at the FIR-13 declared
    operating point across all four arms; only landmarks and embedder vary."""
    name: str  # "a_detector_landmarks_sface" | "b_reference_landmarks_sface"
               # | "c_detector_landmarks_buffalo" | "d_reference_landmarks_buffalo"
    uses_reference_landmarks: bool
    embedder: str  # "sface" | "buffalo_l"

@dataclass(frozen=True)
class AttributionResult:
    alignment_share: float          # FNIR(a) - FNIR(b)
    alignment_share_ci: tuple[float, float]
    embedder_share: float           # FNIR(b) - FNIR(d)
    embedder_share_ci: tuple[float, float]
    n_units: int
    tau: float                      # from FIR-13 gate_contract.select_gate_point
    toolchain: dict[str, str]       # from FIR-14 CV5 run's toolchain block
    caveats: tuple[str, ...]        # e.g. cross-family arm ambiguity (below)

def run_attribution_split(
    *,
    mated_units: Sequence["fir_bakeoff_run.MatedSearchUnit"],
    reference_landmarks: dict[tuple[int, int], "np.ndarray"],  # (media_id, box_index) -> (5,2)
    tau: float,
    seed: int,
    b: int = 2000,
) -> AttributionResult: ...
```

- Arms (a) and (b) share the SFace embedder (`OrtSFaceEmbedder` / `OpenCVSFaceEmbedder` — `embed_batch` from `_common.py`); arms (c) and (d) route through `buffalo_bench.BuffaloFusedLeg` (287–382). **State explicitly in code comments and `REPORT.md`**: `BuffaloFusedLeg.detect` (317–341) re-detects internally rather than accepting externally supplied landmarks — arm (c)/(d)'s "detector landmarks"/"reference landmarks" distinction is therefore not perfectly isolated for the buffalo arms the way it is for arms (a)/(b); this is the caveat field in `AttributionResult`, and `embedder_share` for this reason carries a wider uncertainty band that the paired bootstrap alone does not capture — the report must say so in prose, not just in the CI width.
- Paired-bootstrap interval procedure (step by step, both shares):
  1. Resample images with replacement, `B=2000`, fixed `seed`.
  2. Recompute both FNIR values in the share formula on the **same** resampled image set each iteration (paired — never resample the two arms independently).
  3. `alignment_share_ci` = 2.5th/97.5th percentile of the resampled `FNIR(a) − FNIR(b)` distribution; same for `embedder_share_ci`.
  4. Report `n_units` (mated search units entering the resample) alongside the CI so a narrow interval from a small `n_units` is visible, not hidden.
- **S1a (reference landmarks are operator labour — state this, do not silently substitute)**: since `landmark_cache.py` provides only detector-native (YuNet) landmarks, arm (b)/(d) needs an independent landmark set. S1a produces hand-marked 5-point landmarks (eye centers, nose tip, mouth corners) for the FIR-11 R1 30-probe subset only, using `benchmarks/tools/golden150-box-annotator.html` as the marking tool (existing corpus artifact, not code — verify current form supports 5-point landmark output before use, else extend it as an in-slice sub-task). This is **operator labour**, not automatable, and is called out as such in the slice checklist.

Proof:

- `cd apps/prototype-description-service && python3 -m pytest scene/tests/test_eval_harness_attribution_split.py -q` — asserts share-formula arithmetic on synthetic fixtures, bootstrap determinism with a fixed seed, and that the buffalo-arm caveat field is populated whenever arms (c)/(d) are used.

### Slice 2: Oracle-before-predicted occlusion ladder

**Goal**: Measure the oracle-mask ceiling before the predicted-mask approximation, and decide whether FIR-17's masking approach has any headroom.

Changes:

- New `apps/prototype-description-service/scripts/eval_harness/occlusion_ladder.py`:

```python
from enum import StrEnum
from dataclasses import dataclass

class LadderRung(StrEnum):
    NONE = "none"           # baseline, no occlusion handling
    ORACLE = "oracle"       # ground-truth mask (synthetic twins, or hand-drawn for real probes)
    PREDICTED = "predicted" # compute_occlusion_severity eye-patch proxy (today's only predictor)

@dataclass(frozen=True)
class LadderPoint:
    rung: LadderRung
    fnir: float | None
    n_mated: int
    measured: bool

def masked_cosine(
    probe_vec: "np.ndarray",       # (128,) SFace embedding
    gallery_vec: "np.ndarray",     # (128,)
    support_mask: "np.ndarray",    # (128,) bool — True = dimension retained
) -> float:
    """EVAL-ONLY in this task. Cosine restricted to `support_mask` dimensions.
    Invariants (asserted by tests):
      - full mask (all True)  == ordinary cosine similarity (matches
        recognition.application.clustering.centroid_utils.compute_similarity
        on the same pair, up to float32 rounding)
      - empty mask (all False) raises ValueError
    """

def score_ladder(
    *,
    twin_specs: "Sequence[synthetic_occlusion.OcclusionTwinSpec]",
    real_probes: "Sequence[AttributionArm]",  # A_true_occluder / B_eyewear strata only
    support_mask_recipe: "Callable[[np.ndarray], np.ndarray]",
    tau: float,
    seed: int,
) -> dict[LadderRung, LadderPoint]: ...
```

- **Rung 0 (NONE)**: baseline FNIR on the occluded stratum, no masking.
- **Rung 1 (ORACLE)**: exact masks. Synthetic twins get their mask by construction (`synthetic_occlusion.generate_twin_specs`); real probes in `A_true_occluder`/`B_eyewear` get hand-drawn masks (operator labour, ≤30 probes) labeled via `anatomy_region_stats(mask, landmarks_px)` (verified signature, `synthetic_occlusion.py:762–784`) into per-landmark-region visibility.
- **Rung 2 (PREDICTED)**: today's only predictor — `compute_occlusion_severity`'s two-eye-patch proxy (`face_quality_factors.py:82–105`). This rung exists to quantify the gap FIR-17's `compute_landmark_visibility` (a 5-patch extension) would need to close, not to ship anything.
- **Support-mask attribution recipe (spelled out step by step, PDSN-style)**: to build `support_mask_recipe`, (1) take a set of clean (unoccluded) twin bases; (2) for each of 5 landmark regions (left eye, right eye, nose, mouth-left, mouth-right), synthetically occlude only that region and re-embed; (3) compute the per-dimension absolute delta between the clean and region-occluded embedding vectors; (4) rank the 128 dimensions by delta magnitude per region; (5) a dimension is attributed to a region if that region's delta ranks in its top decile across a fixed sample of clean twins (threshold pinned in code, not tuned per run); (6) `support_mask_recipe(visibility_scores)` then returns `True` for every dimension whose attributed region has visibility above a floor, `False` otherwise. This attribution step runs once (offline, seeded) and its output ships as the same versioned JSON asset FIR-17 S1 loads (`sface-support-map-v1.json`) — this task produces the recipe and a first version of the asset; FIR-17 owns shipping it behind a knob.
- **Oracle gap** = `FNIR(rung0) − FNIR(rung1 with masked_cosine applied)`. If the oracle gap's 95% CI includes 0, record that verbatim in `REPORT.md` as the reason FIR-17 S1 is dead at $0 (per the branch rule FIR-17 opens with).

Proof:

- `cd apps/prototype-description-service && python3 -m pytest scene/tests/test_eval_harness_occlusion_ladder.py -q` — asserts `masked_cosine` invariants (full mask == `compute_similarity`; empty mask raises), rung ordering (rung1 FNIR ≤ rung0 FNIR on synthetic fixtures where the mask is exact by construction), and bootstrap determinism on the oracle-gap CI.

### Slice 3: Attribution report + D-02 decision packet

**Goal**: Name the leg FIR-17 branches on, in a decision the MCP records.

Changes:

- `benchmarks/results/attribution-t01-<date>/REPORT.md`: states the leg (`alignment` | `embedder` | `both` | `inconclusive`) with both shares' CIs, the buffalo cross-family caveat from S1, the oracle-gap verdict from S2, and the DIAGNOSTIC tier label on every number.
- MCP decision `firplan_d02_attribution_<date>` template text (operator-facing, recorded via `record_event`):

  ```
  decision_id: firplan_d02_attribution_<date>
  task_ref: FIR-15
  summary: T-01 attribution split + oracle occlusion ladder, DIAGNOSTIC tier (FIR-14 CV5 run <run-id>)
  alignment_share: <value> CI[<lo>, <hi>]
  embedder_share: <value> CI[<lo>, <hi>]
  oracle_gap: <value> CI[<lo>, <hi>]
  verdict: EMBEDDER | DETECTOR | BOTH | INCONCLUSIVE
  fir17_branch: <slices FIR-17 runs per this verdict, per FIR-17's branch rule>
  caveats: buffalo cross-family arm ambiguity (see S1); DIAGNOSTIC tier (Golden-150 not yet FIR-11-remediated)
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

- [ ] `attribution_split.py` implements the four arms with detector fixed at the FIR-13 operating point.
- [ ] Buffalo cross-family caveat (arms c/d re-detect internally) is recorded in `AttributionResult.caveats` and surfaced in `REPORT.md`.
- [ ] S1a reference-landmark production is scoped as operator labour on the FIR-11 R1 30-probe subset, not silently automated.
- [ ] `test_eval_harness_attribution_split.py` covers share arithmetic and paired-bootstrap determinism.

### Checklist for Slice 2: Oracle-before-predicted occlusion ladder

- [ ] `occlusion_ladder.py` implements `LadderRung`, `score_ladder`, and the eval-only `masked_cosine` with the stated invariants.
- [ ] Support-mask attribution recipe implemented exactly as spelled out (5-region occlusion deltas → per-dimension attribution → versioned JSON asset).
- [ ] Oracle-gap CI computed and its zero-inclusion case recorded verbatim as FIR-17's kill condition for S1.
- [ ] `test_eval_harness_occlusion_ladder.py` covers `masked_cosine` invariants and ladder-rung ordering.

### Checklist for Slice 3: Attribution report + D-02 decision packet

- [ ] `REPORT.md` states the leg verdict with both shares' CIs and the DIAGNOSTIC tier label.
- [ ] MCP decision `firplan_d02_attribution_<date>` recorded with the `verdict` and `fir17_branch` fields FIR-17 reads.

## Review Readiness

- [ ] No boundary-touching implementation (none exists in this task) is left without matching test evidence.
- [ ] Runtime-parity checks: n/a (CPU-only offline scoring).
- [ ] Handoff decision records the verdict, the shares, the oracle-gap result, and the FIR-17 branch it implies.

## Stretch Goals

- [ ] Extend `benchmarks/tools/golden150-box-annotator.html` with native 5-point landmark output if S1a's hand-marking proves too slow in the existing tool.

## Success Criteria

- [ ] `alignment_share` and `embedder_share` each report a paired-bootstrap CI on the FIR-14 CV5 DIAGNOSTIC-tier run.
- [ ] Oracle-before-predicted ladder reports a gap with a CI; the zero-inclusion case is explicitly actionable for FIR-17.
- [ ] MCP decision `firplan_d02_attribution_<date>` recorded and cited by FIR-17's branch rule.
- [ ] `handoff_close_check(enforce=True)` passes; task `done` + archived.
