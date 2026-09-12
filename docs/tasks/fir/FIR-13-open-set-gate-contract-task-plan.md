# Task Plan

> **Metadata**
>
> - **Date**: 2026-09-11
> - **Author**: Claude Fable 5.1 (claude-fable-5-1) via sonnet drafting agent
> - **Status**: draft
> - **Owning Epic**: [docs/epics/v0.5.0/commercial-face-identity-replacement-epic.md](../../epics/v0.5.0/commercial-face-identity-replacement-epic.md)
> - **Epic Short ID**: FIR
> - **Task ID**: `FIR-13`
> - **Target Branch**: `feature/fir-13`
> - **Review Coverage Target**: 2

---

## FIR-13. Open-set gate contract: face rubric, D3 declaration, T-14 adjudication rule

## Objective

Encode the three pieces of the open-set gate that exist today only as prose in the QA v8 report and the 2026-09-11 assessment: a written face-label rubric (T-09), a machine-checkable D3 (FNIR@FPIR) declaration whose operating point stays unset until the operator ratifies it, and the T-14 union-adjudication dead-zone rule as a testable module. No production code, no GPU, no corpus re-run — this is contract scaffolding over the existing FIR-12 harness.

## Intake

- **Scope one-pager**: none new — this task is decomposed from the 2026-09-11 program re-plan (decision #10843, session firplan-1-replan-20260911); no separate scope doc.
- **Key Q&A decisions**: decision #10843 (program re-plan: D3 = FNIR@FPIR, no epic rewrite, operator ratifies the FPIR operating point).
- **Not-Doing**: running T-14 itself (operator labour — 20–34 person-h against Golden-150, tracked by FIR-11); choosing the FPIR operating point (operator ratifies via an MCP decision named `firplan_d3_operating_point_<date>` — this task only builds the code path that consumes whatever value that decision records).

### QA v8 rows quoted verbatim (source: `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html`, revised 2026-07-28)

**T-09 (D-09)**: "Written face-label rule — what counts, what is refused, how disputes resolve"; artifact `benchmarks/protocols/face-label-rule.md` (new); covers hand-only, back-of-head, heavy occlusion, depiction, sub-threshold size; disagreement procedure; pre-adjudication labels retained by policy; frozen before any sample is drawn. Canon [MLDATA-03], [HITL-07] escalation queue only.

**T-14 (D-01)**: "Union adjudication — the cheap kill path for D-01"; runs after T-09; input Golden-150 (~410 faces) + candidate detector output at the declared operating point; 20–34 person-h, $0; bound = (TP_b − TP_c)/U. Four mandatory conditions: (i) U = human-verified true faces in the union, not the union box count; (ii) both detectors run at the matched-FPPI operating point D1 declares; (iii) kill on the upper confidence limit of a bootstrap interval (B=2000, resampling_unit=image), not the point estimate; (iv) declare both thresholds before the run and never revise them after (U is partly controlled by the systems under test). Canon [AUDIT-04], [MEAS-07], [EVAL-19], [EXP-24], [EXP-12].

### Dead-zone rule (executive summary, `benchmarks/reports/fir-executive-summary-20260728.md:83–84, 95–96, 111`)

Operator signs the 0.05–0.10 dead-zone rule in writing BEFORE T-14 runs. Kill only if the miss-inflated bootstrap 95% UCL < 0.05 (30 images annotated exhaustively supply the miss inflation). A UCL in 0.05–0.10 is neither kill nor pass. ≥0.10 means D1 is not killed — the detector line stays open.

## Problem Statement

`fir_bakeoff_run.py` (merged, FIR-12) computes `RunReport` rows with FNIR/FPI per stratum but no row names the rubric under which faces were adjudicated, and nothing in the tree encodes the D3 metric declaration or the T-14 kill/dead-zone/open decision rule. Every downstream task (FIR-14 re-baseline, FIR-15 attribution, FIR-16 head-to-head) needs a single `GateContract` object to score against; without it, each task would re-invent its own threshold-selection and FPI-ceiling logic, and the T-14 result (when the operator eventually runs it) would have no canonical place to land.

## Constraints

- CPU-only, $0. No A10/GPU spend before D-01 (reached only via T-09 → T-14 → D-01).
- No corpus changes — Golden-150 as remediated by FIR-11 R1 is consumed, never restated (FIR-11 rev 7 owns the corpus plan).
- The FPIR operating point is never hard-coded; the contract's `max_fpi`/`n_nonmated_declared` stay `null` in the shipped JSON until an operator MCP decision ratifies them.
- Rank-1 / CMC numbers are not gate inputs [EVAL-18].
- Withdrawn numbers (M-12 0.865/0.321, recall 0.504, 2.73 faces/image, every pre-CVUP-1 artifact) may not be cited as evidence anywhere in this task's artifacts.
- `sr-006`: no `assert` for the load-time contract validation — raise `GateContractError`.
- `sr-007`: dead-zone verdict is a `StrEnum`, not string comparison.
- `rg-008`: `gate_contract.py` validates the manifest JSON structurally at load time; missing/malformed keys fail closed.

## Workflow Principles

- Measure before optimising [PRINCIPLE #15] — this task only wires the measurement contract; it draws no conclusion about detector or embedder quality.
- [AUDIT-04]: gold review only ever covers what was actually adjudicated — `select_gate_point` must never synthesize a measured point from an unmeasured cell.
- [EVAL-19]: FPI stays an integer count end to end; no derived rate replaces it as a gate criterion.
- [rg-009]: no task-specific literals (e.g. a hard-coded FPIR number) inside generic modules — the operating point is always read from the ratified contract JSON.

## Terminology

- **D3**: the headline gate metric, FNIR at a fixed FPIR, measured with non-mated probes on an open-set gallery, score threshold swept, FPI reported as an integer count.
- **FPI**: integer false-positive-identification count (never a rate) — see `open_set_identification.IETPoint.fpi`.
- **Rubric version**: `RUBRIC_VERSION = "face-label-rule/v1"`, the frozen version tag every adjudicated row must carry.
- **Dead zone**: the T-14 UCL band 0.05–0.10 in which the detector-gap-bound bootstrap upper confidence limit is neither a kill nor a pass signal.
- **DIAGNOSTIC / DIRECTIONAL / REPORTABLE**: existing eval-harness evidence tiers; this task produces no scored run, so no tier is claimed by its own artifacts.

## Current State Analysis

- FIR-12's `open_set_identification.py` (194 lines) computes `IETPoint`/`iet_curve` per threshold but has no concept of a declared gate contract or an FPI ceiling to select against.
- `fir_bakeoff_run.RunReport.to_rows()` (`apps/prototype-description-service/scripts/eval_harness/fir_bakeoff_run.py:202-260`, verified via `get_code_snippet`) emits one dict per stratum with keys `stratum, n_images, unique_subjects, fnir, fpi, n_mated, n_nonmated, declared_empty, measured, incomplete, manifest_images, tau, fpi_per_enrolled_subject, n_enrolled_gallery_subjects, gallery, n_withheld_probe_templates, search_shortfall, nonmated_shortfall` — no rubric field.
- No `benchmarks/protocols/face-label-rule.md`, no `benchmarks/protocols/t14-dead-zone-rule.md`, no `gate_contract.py`, no `union_adjudication.py` exist (checked via `check_index_coverage`: all four report `freshness: missing`).
- No bake-off has been run against any of this — FIR-12's report states explicitly "the instrument, not a result."

## Target Outcome

Three new artifacts land: a frozen face-label rubric doc, a `GateContract` dataclass + loader + `select_gate_point` that any downstream task can import, and a `union_adjudication.py` module encoding the T-14 bound, bootstrap UCL, and dead-zone verdict as pure, independently testable functions. Every `RunReport.to_rows()` row carries the rubric version it was scored under. The contract JSON ships with `ratified_by_decision_id: null` — FIR-16 refuses to propose a gate off an unratified contract (enforced by that task, not this one).

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`.
- Contracts: none cross-service — this task is internal to `apps/prototype-description-service/scripts/eval_harness/`.
- Handoff/MCP state: task ref `FIR-13`; upstream decision #10843; FIR-12 findings (`review_findings(review={"operation":"list","task_ref":"FIR-12"})`) for house style on `IETPoint`-style invariant-by-construction dataclasses.

## Proposed Solution

Add two new pure modules under `scripts/eval_harness/` with zero production-code coupling: `gate_contract.py` (rubric constant + `GateContract` + `select_gate_point` + `GateSummary`) and `union_adjudication.py` (the T-14 bound, bootstrap UCL, dead-zone verdict). Stamp the rubric version into `fir_bakeoff_run.RunReport.to_rows()`. Freeze the two protocol docs the operator will later sign against.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| docs | `benchmarks/protocols/face-label-rule.md` | New — T-09 rubric: what counts as a face, refusal classes, dispute procedure, retained pre-adjudication labels, frozen-version header. |
| docs | `benchmarks/protocols/t14-dead-zone-rule.md` | New — template with blanks for the operator to fill and sign before any T-14 run; states the 0.05/0.10 bounds verbatim. |
| eval-harness | `scripts/eval_harness/gate_contract.py` | New module (see Slice 1/2 below). |
| eval-harness | `scripts/eval_harness/union_adjudication.py` | New module (see Slice 3 below). |
| eval-harness | `scripts/eval_harness/fir_bakeoff_run.py` | `RunReport.to_rows()` (202-260) gains a `rubric_version` key in both the gallery-stratum branch and the per-stratum branch. |
| config | `benchmarks/manifests/fir-gate-contract-v1.json` | New — the `GateContract` source-of-truth JSON, `ratified_by_decision_id: null` at creation. |
| tests | `scene/tests/test_eval_harness_gate_contract.py` | New. |
| tests | `scene/tests/test_eval_harness_union_adjudication.py` | New. |
| tests | `scene/tests/test_eval_harness_fir_bakeoff_run.py` | Existing (111 tests) — add one test asserting the new `rubric_version` key appears on every row from `to_rows()`. |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/scripts/eval_harness/open_set_identification.py` | `IETPoint` (56-99), `iet_curve` (170-186, keyword-only `mated`, `nonmated`, `thresholds`, `n_enrolled_gallery_subjects`) — `select_gate_point` consumes `IETPoint` sequences from here. |
| `docs/tasks/fir/FIR-12-phase1-implementation-report.md` | House style for invariant-by-construction dataclasses (`IETPoint.__post_init__` pattern) and the "instrument, not a result" framing this task preserves. |
| `docs/tasks/fir/FIR-11-gate-corpus-remediation-and-fir-rebaseline-task-plan.md` | Corpus this contract will eventually score against (Golden-150 R1: 30 entries / 30 probes / 17 identities) — referenced, not restated. |
| `docs/tasks/fir/FIR-16-open-set-head-to-head-task-plan.md` | Consumes `GateContract`/`select_gate_point` once written (out of this task's scope). |

## Verification Strategy

- Deterministic tests:
  - `uv run --extra dev pytest scene/tests/test_eval_harness_gate_contract.py scene/tests/test_eval_harness_union_adjudication.py scene/tests/test_eval_harness_fir_bakeoff_run.py -q`
  - `make test-eval-surface` (`mk/evals.mk:33-35`)
- Runtime-parity / environment checks: none — no runtime code touched.
- Contract/fixture verification: `benchmarks/manifests/fir-gate-contract-v1.json` round-trips through `gate_contract.py`'s loader without raising, and raises `GateContractError` on each of: missing `metric`, non-integer `max_fpi`, missing `rubric_version`.
- Manual verification: none.

## Slice Delivery

### Slice 1: Face-label rubric (T-09)

Implements: FIRG-003, FIRG-020..021.

**Goal**: Freeze the rubric the operator adjudicates against, and stamp it into every scored row.

Changes:

- `benchmarks/protocols/face-label-rule.md` (new): rule text + refusal classes (hand-only, back-of-head, heavy occlusion, depiction, sub-threshold size) + dispute procedure + retained pre-adjudication labels + a frozen-version header naming `RUBRIC_VERSION`.
- `scripts/eval_harness/gate_contract.py` (new): module-level constant.

```python
RUBRIC_VERSION = "face-label-rule/v1"
```

- `scripts/eval_harness/fir_bakeoff_run.py`: `RunReport.to_rows()` (202-260) adds `"rubric_version": gate_contract.RUBRIC_VERSION` to both the `GALLERY_STRATUM` dict literal and the per-point dict literal (new import `from scripts.eval_harness import gate_contract` at module top, matching the module's existing import style).

Proof:

- `uv run --extra dev pytest scene/tests/test_eval_harness_fir_bakeoff_run.py -k rubric_version -q` — new test asserts every row dict from a synthetic `RunReport.to_rows()` call carries `rubric_version == "face-label-rule/v1"`.

### Slice 2: D3 declaration encoded

Implements: FIRG-001..006 (FIRG-006 jointly with FIR-16 S3).

**Goal**: A machine-checkable D3 contract object with the operating point held unset until ratified.

Changes:

- `scripts/eval_harness/gate_contract.py`:

```python
class GateContractError(Exception): ...

@dataclass(frozen=True)
class GateContract:
    metric: str  # always "FNIR@FPIR"
    max_fpi: int | None
    n_nonmated_declared: int | None
    rubric_version: str
    ratified_by_decision_id: str | None
    t14_thresholds_declared: dict[str, float] | None  # {"buffalo": ..., "candidate": ...}
    t14_thresholds_sha256: str | None  # sha256 of t14_thresholds_declared, frozen pre-run

def load_gate_contract(path: str | Path) -> GateContract: ...

@dataclass(frozen=True)
class GateSummary:
    fnir_at_gate: float | None
    tau_at_gate: float
    fpi_at_gate: int
    measured: bool
    contract: GateContract

def select_gate_point(
    points: Sequence[IETPoint],
    *,
    max_fpi: int,
) -> IETPoint | None: ...
```

  `load_gate_contract` raises `GateContractError` on any missing/malformed required key (`rg-008` — fail fast, no silent default; `t14_thresholds_declared`/`t14_thresholds_sha256` are required keys too — present and `null` until T-14 ratification, never absent). `select_gate_point` returns the measured point with the lowest `tau` whose `fpi <= max_fpi`, or `None` when no measured point qualifies — **never** `0.0` (mirrors `IETPoint`'s own unmeasured-is-not-zero invariant, `open_set_identification.py:56-99`).
- `benchmarks/manifests/fir-gate-contract-v1.json` (new): `{"metric": "FNIR@FPIR", "max_fpi": null, "n_nonmated_declared": null, "rubric_version": "face-label-rule/v1", "ratified_by_decision_id": null, "t14_thresholds_declared": null, "t14_thresholds_sha256": null}`. The plan does not name a fixed FPIR value anywhere — the operator ratification step is `set_handoff_state`/`record_event` recording an MCP decision `firplan_d3_operating_point_<date>` that then edits `max_fpi`/`n_nonmated_declared`/`ratified_by_decision_id` in place. A separate, later MCP decision (`firplan_t14_thresholds_<date>`) edits `t14_thresholds_declared`/`t14_thresholds_sha256` in place — the two ratifications are independent edits to the one contract file; neither implies the other.

Proof:

- `scene/tests/test_eval_harness_gate_contract.py::test_load_gate_contract_round_trips`, `::test_load_gate_contract_raises_on_missing_metric`, `::test_load_gate_contract_raises_on_missing_t14_threshold_keys`, `::test_select_gate_point_never_returns_zero_for_unmeasured`, `::test_select_gate_point_picks_lowest_qualifying_tau`.

### Slice 3: T-14 adjudication rule encoded

Implements: FIRG-010..015.

**Goal**: The union-adjudication bound, its bootstrap UCL, and the kill/dead-zone/open verdict as pure functions the operator's eventual T-14 run can call — this slice never runs T-14 itself.

Changes:

- `scripts/eval_harness/union_adjudication.py` (new):

```python
@dataclass(frozen=True)
class UnionAdjudicationInput:
    image_id: str
    union_boxes: int
    human_true_faces: int          # U_i
    tp_buffalo_i: int
    tp_candidate_i: int
    matched_fppi_declared: float
    thresholds_declared_before_run: dict[str, float]  # {"buffalo": ..., "candidate": ...}

def detector_gap_bound(rows: Sequence[UnionAdjudicationInput]) -> float: ...
    # (sum(tp_buffalo_i) - sum(tp_candidate_i)) / sum(human_true_faces)

def bootstrap_ucl(
    rows: Sequence[UnionAdjudicationInput],
    *,
    b: int = 2000,
    seed: int,
    resampling_unit: str = "image",
    level: float = 0.95,
) -> float: ...
    # image-level resampling only (rg per D16): draw len(rows) images with
    # replacement b times (seeded numpy Generator), recompute
    # detector_gap_bound on each resample, return the `level` percentile
    # (default 95th) of the resulting distribution.

def miss_inflate(
    rows: Sequence[UnionAdjudicationInput],
    *,
    exhaustive_image_ids: frozenset[str],
) -> tuple[float, float]: ...
    # factor = (misses found by exhaustive adjudication) / (detector-flagged
    # misses), both counted ONLY over rows whose image_id is in
    # exhaustive_image_ids; the resulting factor is what the caller applies
    # to non-exhaustive rows' miss counts before they feed bootstrap_ucl —
    # miss_inflate itself never mutates rows, it only returns the factor.
    # Rounds half-up to 4 dp (Decimal ROUND_HALF_UP). Raises
    # UnionAdjudicationError if len(exhaustive_image_ids) < 30 (D16 floor).
    # Zero-denominator (no detector-flagged misses on the exhaustive subset)
    # returns (1.0, 1.0) — factor 1.0 (no-op) with the second element as an
    # explicit degenerate-case flag (0.0 in the normal, measured case).
    # Returns (factor, flag).

class DeadZoneVerdict(StrEnum):
    KILL = "kill"
    DEAD_ZONE = "dead_zone"
    OPEN = "open"

class UnionAdjudicationError(Exception): ...
    # fail-closed refusal (sr-006/rg-008) — never a silent OPEN downgrade.

_REQUIRED_CONDITION_KEYS = frozenset({
    "union_uses_human_true_faces",       # (i) U from human_true_faces, never union_boxes
    "matched_fppi_equal_across_rows",    # (ii) both detectors at the same declared operating point
    "verdict_from_bootstrap_ucl",        # (iii) kill/dead-zone/open reads the UCL, never the point estimate
    "thresholds_frozen_before_run",      # (iv) thresholds_declared_before_run identical on every row
})

def check_conditions(
    rows: Sequence[UnionAdjudicationInput],
    *,
    declared: GateContract,
    signed_decision_id: str | None,
    kill_below: float = 0.05,
    dead_zone_upper: float = 0.10,
    b: int = 2000,
    seed: int,
) -> DeadZoneVerdict: ...
    # Refuses (raises UnionAdjudicationError, never returns) when:
    #   - signed_decision_id is None (FIRG-015: no unsigned run may be adjudicated).
    #   - sha256(json.dumps(rows[0].thresholds_declared_before_run, sort_keys=True))
    #     != declared.t14_thresholds_sha256 (declared.t14_thresholds_sha256 is
    #     itself None → refuse: T-14 has not been ratified against this
    #     contract yet).
    #   - any of the four `_REQUIRED_CONDITION_KEYS` evaluates False (i–iv above).
    # Only once all four conditions hold and the signature/hash checks pass
    # does it compute `bootstrap_ucl(rows, b=b, seed=seed)` and return
    # DeadZoneVerdict.KILL (ucl < kill_below), DEAD_ZONE (kill_below <= ucl <
    # dead_zone_upper), or OPEN (ucl >= dead_zone_upper) per the executive
    # summary's bounds.
```

- `benchmarks/protocols/t14-dead-zone-rule.md` (new): blanks for the operator's signature, run date, and the four condition confirmations, with the 0.05/0.10 bounds and the "declared before the run, never revised" clause quoted verbatim from the executive summary.

Proof:

- `scene/tests/test_eval_harness_union_adjudication.py` — fixture: 5 synthetic images; `test_check_conditions_kill_below_005`, `test_check_conditions_dead_zone_between_005_and_010`, `test_check_conditions_open_above_010`, `test_check_conditions_refuses_without_signed_decision_id`, `test_check_conditions_refuses_on_threshold_hash_mismatch`, `test_check_conditions_refuses_on_missing_condition_key`, `test_bootstrap_ucl_deterministic_with_seed`, `test_miss_inflate_refuses_under_30_exhaustive_images`, `test_miss_inflate_zero_denominator_returns_factor_one_with_flag`, `test_miss_inflate_computed_only_from_exhaustive_subset`.

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- |
| `fir-13` | `apps/prototype-description-service/scripts/eval_harness/gate_contract.py`, `apps/prototype-description-service/scripts/eval_harness/union_adjudication.py`, `apps/prototype-description-service/scripts/eval_harness/fir_bakeoff_run.py`, `apps/prototype-description-service/scene/tests/test_eval_harness_gate_contract.py`, `apps/prototype-description-service/scene/tests/test_eval_harness_union_adjudication.py`, `apps/prototype-description-service/scene/tests/test_eval_harness_fir_bakeoff_run.py` (existing — Slice 1 adds the `rubric_version` test), `apps/prototype-description-service/benchmarks/protocols/face-label-rule.md`, `apps/prototype-description-service/benchmarks/protocols/t14-dead-zone-rule.md`, `apps/prototype-description-service/benchmarks/manifests/fir-gate-contract-v1.json` | FIR-12 (merged) | `python3 -m pytest scene/tests/test_eval_harness_gate_contract.py scene/tests/test_eval_harness_union_adjudication.py scene/tests/test_eval_harness_fir_bakeoff_run.py -q` |

### Merge Order

`fir-13` (single lane; no internal ordering).

### Manifest

```bash
make lane-manifest-init TASK=FIR-13 LANE_IDS='fir-13' TASK_PLAN=docs/tasks/fir/FIR-13-open-set-gate-contract-task-plan.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: Use MCP worker lifecycle tools with the declared lane ownership and verification boundaries.
- **Shell fallback**: Use repo lane helpers or manual worktrees while preserving the same ownership and evidence requirements.

---

## Consolidated Checklist

> **Checklist scope rule:** Describe work being delivered, not finding status. Finding status is queried from the handoff DB via `review_findings(review={"operation":"list","status":"open","task_ref":"FIR-13"})` or read from `DASHBOARD.txt`.

## Context and Ownership

- [ ] Loaded FIR-12's implementation report and `IETPoint`'s invariant-by-construction pattern before writing `GateContract`/`UnionAdjudicationInput`.
- [ ] Confirmed no cross-service/cross-language boundary is touched (internal to `scripts/eval_harness/`).

### Checklist for Slice 1: Face-label rubric (T-09)

- [ ] `benchmarks/protocols/face-label-rule.md` written with all five refusal classes and the dispute procedure.
- [ ] `RUBRIC_VERSION` constant added to `gate_contract.py`.
- [ ] `RunReport.to_rows()` stamps `rubric_version` on every row (both branches).
- [ ] New `test_eval_harness_fir_bakeoff_run.py` test for the stamped field passes.

### Checklist for Slice 2: D3 declaration encoded

- [ ] `GateContract`, `GateContractError`, `load_gate_contract`, `GateSummary`, `select_gate_point` implemented in `gate_contract.py`.
- [ ] `benchmarks/manifests/fir-gate-contract-v1.json` created with `ratified_by_decision_id: null`.
- [ ] Load-time validation raises `GateContractError` on each malformed-key case tested.
- [ ] `select_gate_point` never returns a point for an unmeasured cell; test asserts `None` in that case.

### Checklist for Slice 3: T-14 adjudication rule encoded

- [ ] `UnionAdjudicationInput`, `detector_gap_bound`, `bootstrap_ucl`, `miss_inflate`, `DeadZoneVerdict`, `UnionAdjudicationError`, `check_conditions` implemented in `union_adjudication.py`.
- [ ] `check_conditions` refuses (raises) without a `signed_decision_id` and on a `t14_thresholds_sha256` mismatch, before it ever computes a UCL.
- [ ] `miss_inflate` refuses below the 30-exhaustive-image floor and reports the zero-denominator degenerate case via its flag return, never a silent 1.0.
- [ ] `benchmarks/protocols/t14-dead-zone-rule.md` written with the 0.05/0.10 bounds and operator sign-off blanks.
- [ ] Kill / dead-zone / open / signature-refusal / hash-mismatch-refusal tests all pass with a deterministic bootstrap seed.

## Review Readiness

- [ ] No boundary-touching implementation is left without matching contract/doc/fixture evidence.
- [ ] `GateContract`'s `max_fpi`/`n_nonmated_declared`/`ratified_by_decision_id` fields are `null` in the shipped manifest — no fixed FPIR value is hard-coded anywhere in this task's diff.
- [ ] Handoff decision records the change, verification, and the fact that no contract implication crosses a service boundary.

## Stretch Goals

- [ ] A small CLI (`gate_contract.py --check <manifest>`) that exits non-zero on a malformed contract, for pre-commit use by later FIR tasks.

## Success Criteria

- [ ] `gate_contract.py` and `union_adjudication.py` exist, are imported by no production code, and pass their test suites.
- [ ] Every `RunReport.to_rows()` row carries `rubric_version`.
- [ ] `benchmarks/manifests/fir-gate-contract-v1.json` loads cleanly and round-trips through `GateContract`.
- [ ] `benchmarks/protocols/face-label-rule.md` and `benchmarks/protocols/t14-dead-zone-rule.md` are frozen documents ready for operator sign-off.
