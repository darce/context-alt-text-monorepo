# FIR Open-Set Gate and Occlusion Specification

> **Metadata**
>
> - **Date**: 2026-09-11
> - **Author**: Claude Fable 5.1 (claude-fable-5-1) via sonnet drafting agent
> - **Status**: draft
> - **Assessment**: [docs/assessments/current/gpu-burst-pipeline-status-and-fir-insightface-replacement-2026-09-11.md](../assessments/current/gpu-burst-pipeline-status-and-fir-insightface-replacement-2026-09-11.md) §4
> - **Owning epic**: E22 [docs/epics/v0.5.0/commercial-face-identity-replacement-epic.md](../epics/v0.5.0/commercial-face-identity-replacement-epic.md)
> - **Package version target**: v0.5.0

---

# FIR Open-Set Gate and Occlusion Specification

Defines the machine-checkable contract for the D3 gate metric (FNIR@FPIR), the T-14 detector-kill adjudication rule, toolchain-provenance discipline for the pre-CVUP-1 withdrawal, alignment-vs-embedder attribution, and inference-only occlusion robustness (visible-support matching, pose-head rescue, OACT sign fix). No item in this spec authorizes GPU spend or training; that gate is D-01, reached only via T-09 → T-14 → D-01 per the program decision. Heuristics canon: [PRINCIPLE #15](https://github.com/darce/heuristics-canon), [AUDIT-04], [EVAL-01/16/18/19/28], [EMB-01/11/12], [MLDATA-02/03/04/09/16], [DRIFT-03], [IDX-02], [CAL-01/04], [PROV-01], [TEST-03], [DBG-03].

**Constraints:** Greenfield policy — no backward-compat shims. CPU-only ($0) for Phases A/B/C; acx-dev-fir head-to-head (Phase D) is public-API only, no GPU spend before D-01. `oact_coefficient` stays non-negative post sign-flip (sr-006/rg-008 apply: load-time validation, no assert for production paths). Withdrawn numbers (M-12 0.865/0.321, recall 0.504, 2.73 faces/image, all pre-CVUP-1 artifacts) may appear only under the label "withdrawn," never as evidence.

---

## Spec Items

### Gate contract (FIRG-001..009)

#### FIRG-001: `gate_contract.py` module and `GateContract` dataclass

**Trace:** FIR-13 S2 (D3 declaration)
**Priority:** P0

New module `apps/prototype-description-service/scripts/eval_harness/gate_contract.py`. `GateContract` is a frozen dataclass: `metric: Literal["FNIR@FPIR"]`, `max_fpi: int | None`, `n_nonmated_declared: int | None`, `rubric_version: str`, `ratified_by_decision_id: str | None`. Loaded from `benchmarks/manifests/fir-gate-contract-v1.json`. The operating point (`max_fpi`, `ratified_by_decision_id`) stays `null` until the operator ratifies it — this spec does not hard-code a fixed FPIR.

**Before:** no `gate_contract.py` module exists in `apps/prototype-description-service/scripts/eval_harness/` (checked via codemap 2026-09-11: `search_graph` for `gate_contract` returns 0 results).

**After:**
```python
@dataclass(frozen=True)
class GateContract:
    metric: str  # always "FNIR@FPIR"
    max_fpi: int | None
    n_nonmated_declared: int | None
    rubric_version: str
    ratified_by_decision_id: str | None

class GateContractError(ValueError):
    """Raised on missing/malformed gate-contract JSON keys (rg-008)."""

def load_gate_contract(path: Path) -> GateContract: ...
```

**Done when:**
- `scripts/eval_harness/test_eval_harness_gate_contract.py::test_load_gate_contract_round_trip` passes
- `GateContract.metric` is always the literal string `"FNIR@FPIR"` — no other metric value is accepted

---

#### FIRG-002: `select_gate_point` lowest-tau rule

**Trace:** FIR-13 S2
**Priority:** P0

`select_gate_point(points: Sequence[IETPoint], *, max_fpi: int) -> IETPoint | None` returns the measured point (`IETPoint.measured is True`, `open_set_identification.py` 56–99) with the lowest `tau` whose `fpi <= max_fpi`. Returns `None` — never `0.0` or a synthetic zero-FNIR point — when no measured point qualifies. Depends on `IETPoint.__post_init__` (68–79) enforcing `measured ⇔ fnir is not None`.

**Before:** no gate-selection function exists over `iet_curve()` (`open_set_identification.py` 170–186) output; callers would otherwise pick an arbitrary or first point.

**After:**
```python
def select_gate_point(points: Sequence[IETPoint], *, max_fpi: int) -> IETPoint | None:
    qualifying = [p for p in points if p.measured and p.fpi <= max_fpi]
    if not qualifying:
        return None
    return min(qualifying, key=lambda p: p.tau)
```

**Done when:**
- `test_eval_harness_gate_contract.py::test_select_gate_point_lowest_tau_wins` passes
- `test_eval_harness_gate_contract.py::test_select_gate_point_returns_none_when_unmeasured` passes (no measured point ⇒ `None`, never `0.0`)

---

#### FIRG-003: `rubric_version` stamped into every published row

**Trace:** FIR-13 S1 (T-09 rubric)
**Priority:** P1

`fir_bakeoff_run.RunReport.to_rows()` (`fir_bakeoff_run.py` 183–260) gains one new column, `rubric_version`, sourced from `gate_contract.RUBRIC_VERSION` (`"face-label-rule/v1"`). Every row in every published report names the label rubric it was adjudicated under.

**Before** (`fir_bakeoff_run.py::RunReport.to_rows`): rows carry no rubric identifier — the schema predates FIR-13.

**After:** `to_rows()` appends `rubric_version=RUBRIC_VERSION` to each emitted row dict.

**Done when:**
- `scene/tests/test_eval_harness_fir_bakeoff_run.py` gains a case asserting every row of `to_rows()` output carries a non-empty `rubric_version` key
- Existing 111 tests in `test_eval_harness_fir_bakeoff_run.py` stay green (additive column only)

---

#### FIRG-004: Rank-1/CMC excluded from gate inputs

**Trace:** FIR-13 S2 [EVAL-18]
**Priority:** P0

`select_gate_point` and `GateSummary` accept only `IETPoint` sequences (open-set FNIR@FPIR at a swept `tau`). No rank-1 accuracy, CMC curve, or closed-set metric is a legal input to gate selection. `fir_bakeoff_run.score_run(..., closed_set=False)` (410–536) confirms the open-set path is the one wired to the gate.

**Done when:**
- `gate_contract.py` has no import of, or dependency on, any rank-N/CMC computation
- A type-level test (`test_eval_harness_gate_contract.py::test_select_gate_point_rejects_closed_set_input` or equivalent doc assertion) records that `IETPoint` has no rank field

---

#### FIRG-005: Both stacks scored at their own swept `tau`

**Trace:** FIR-16 S1 [EMB-01], [IDX-02]
**Priority:** P0

The 512-D `buffalo_l` space and the 128-D `face_pipeline`/SFace space (`_common.py` `SFACE_EMBEDDING_DIM=60`, value 128) are never compared under a shared threshold. `score_open_set` (FIRG-060) sweeps `tau` independently per stack and calls `select_gate_point` once per stack's own `IETPoint` sequence.

**Before:** no cross-stack open-set scoring exists; `scripts/bench/score.py` (verified via codemap: `clamp01`, `iou_tl`, `hungarian_iou_matches` 21–83) is detection-IOU-only today, with no identification/threshold logic.

**After:** `score_open_set(exports, manifest, *, contract, thresholds: dict[str, Sequence[float]])` sweeps `thresholds[stack_name]` per stack and returns one `GateSummary` per stack (FIRG-060 wins on the return shape):
```python
@dataclass(frozen=True)
class GateSummary:
    points: tuple[IETPoint, ...]          # full tau sweep for this stack
    selected: IETPoint | None             # select_gate_point's chosen point, or None
    tau: float | None                     # the selected point's tau (per-stack; never shared)
    probe_outcomes: dict[str, bool]       # keyed f"{media_id}:{probe_index}" for the paired NI test
```
`RunReport` is not extended to carry this shape — `GateSummary` is `score_open_set`'s own return type, one instance per stack.

**Done when:**
- `scripts/bench/tests/test_score_open_set.py::test_stacks_never_share_a_threshold_sweep` passes
- No literal float threshold constant appears shared between the two stacks' sweep ranges in `score_open_set`'s call sites
- `scripts/bench/tests/test_score_open_set.py::test_gate_summary_probe_outcomes_keyed_by_media_and_probe_index` passes

---

#### FIRG-006: Operator ratification required before REPORTABLE tier

**Trace:** FIR-13 S2, FIR-16 S3
**Priority:** P0

A `GateSummary` whose `contract.ratified_by_decision_id is None` can never be tagged tier REPORTABLE; it stays DIAGNOSTIC or DIRECTIONAL (`scripts/bench/score_report.py::assign_tier` 305–335 is the existing tier-assignment anchor for the cross-stack bench and gains this precondition). `propose-gate` (FIRG-063) prints the ratification decision the operator must record before any REPORTABLE claim is made; the decision id pattern is `firplan_d3_operating_point_<date>` (FIR-13 S2) and its id is what `GateContract.ratified_by_decision_id` carries.

**Done when:**
- `scripts/bench/tests/test_score_report_open_set.py::test_unratified_contract_caps_tier_below_reportable` passes
- `assign_tier` (or its open-set extension) never returns REPORTABLE when `ratified_by_decision_id is None`

---

### Adjudication rule — T-14 (FIRG-010..019)

#### FIRG-010: `union_adjudication.py` module and `UnionAdjudicationInput`

**Trace:** FIR-13 S3 (T-14, D-01)
**Priority:** P0

New module `apps/prototype-description-service/scripts/eval_harness/union_adjudication.py`. `UnionAdjudicationInput` is a per-image row: `image_id`, `union_boxes`, `human_true_faces` (U_i), `tp_buffalo_i`, `tp_candidate_i`, `matched_fppi_declared: float`, `thresholds_declared_before_run: dict[str, float]`. `detector_gap_bound(rows) -> float` computes `(ΣTP_b − ΣTP_c) / ΣU`.

**Before:** no `union_adjudication.py` module exists (codemap: 0 results for `paired_ni_score_test`-adjacent T-14 symbols; this module is wholly new).

**Done when:**
- `scene/tests/test_eval_harness_union_adjudication.py::test_detector_gap_bound_matches_hand_computation` passes on the 5-synthetic-image fixture

---

#### FIRG-011: Four T-14 conditions as machine-checked preconditions

**Trace:** FIR-13 S3, QA v8 T-14
**Priority:** P0

`check_conditions(rows, *, declared: GateContract, signed_decision_id: str | None) -> DeadZoneVerdict` evaluates all four named condition keys (`conditions_met: dict[str, bool]`, four keys required, no fifth/partial set accepted) before `KILL` can be emitted: (i) `U` = human-verified true faces in the union, never the union box count; (ii) both detectors ran at the matched-FPPI operating point D1 declares (`matched_fppi_declared` equal across rows for a given run); (iii) the kill decision uses the bootstrap UCL, never the point estimate; (iv) `thresholds_declared_before_run` is fixed before scoring and never revised — checked by hashing `declared`'s thresholds and comparing to the pre-run manifest hash. `check_conditions` refuses (raises) when `signed_decision_id is None` (FIRG-015).

**Done when:**
- `test_eval_harness_union_adjudication.py::test_any_condition_false_forces_open_verdict` passes for each of the four conditions individually violated
- `test_eval_harness_union_adjudication.py::test_check_conditions_refuses_without_signed_decision_id` passes
- `test_eval_harness_union_adjudication.py::test_check_conditions_refuses_on_threshold_hash_mismatch` passes

---

#### FIRG-012: Bootstrap UCL, B=2000, image-level resampling unit

**Trace:** FIR-13 S3, QA v8 T-14 condition (iii)
**Priority:** P0

`bootstrap_ucl(rows, *, b=2000, seed, resampling_unit="image", level=0.95) -> float` resamples whole images (not individual faces) with replacement, recomputes `detector_gap_bound` per resample, and returns the 95th percentile.

**Done when:**
- `test_eval_harness_union_adjudication.py::test_bootstrap_ucl_is_deterministic_given_seed` passes (same seed ⇒ same UCL to float tolerance)
- `test_eval_harness_union_adjudication.py::test_bootstrap_resamples_whole_images_not_faces` passes

---

#### FIRG-013: `miss_inflate` from the 30 exhaustively annotated images

**Trace:** FIR-13 S3, executive summary (`benchmarks/reports/fir-executive-summary-20260728.md:83–84, 95–96, 111`)
**Priority:** P1

`miss_inflate(rows, *, exhaustive_image_ids: frozenset[str]) -> tuple[float, float]` computes the inflation factor from the 30+ exhaustively-annotated images (misses found by exhaustive adjudication ÷ detector-flagged misses, on exhaustive images only) and applies it only to non-exhaustive rows' `U_i`, per the executive summary's miss-inflation instruction. Rounds the factor half-up to 4 decimal places. Refuses (raises a `GateContractError`-family exception) when `len(exhaustive_image_ids) < 30`. Zero-denominator (no detector-flagged misses on the exhaustive subset) yields factor `1.0` with a flag rather than a `ZeroDivisionError` or a silently wrong ratio. Bootstrap resampling (FIRG-012) resamples whole images, consistent with `bootstrap_ucl`'s resampling unit.

**Done when:**
- `test_eval_harness_union_adjudication.py::test_miss_inflate_only_adjusts_non_exhaustive_rows` passes
- `test_eval_harness_union_adjudication.py::test_miss_inflate_requires_at_least_30_exhaustive_images` passes (raises `GateContractError`-family exception below the floor)
- `test_eval_harness_union_adjudication.py::test_miss_inflate_zero_denominator_returns_factor_one_with_flag` passes
- `test_eval_harness_union_adjudication.py::test_miss_inflate_rounds_half_up_to_4dp` passes

---

#### FIRG-014: `DeadZoneVerdict` enum and kill rule

**Trace:** FIR-13 S3, QA v8 T-14
**Priority:** P0

`DeadZoneVerdict` StrEnum {`KILL`, `DEAD_ZONE`, `OPEN`} (sr-007: centralized enum, no scattered string comparison). `verdict(ucl, *, kill_below=0.05, dead_zone_upper=0.10, conditions_met) -> DeadZoneVerdict`: `KILL` only when `ucl < 0.05 AND all(conditions_met.values())`; `0.05 <= ucl < 0.10` ⇒ `DEAD_ZONE`; `ucl >= 0.10` ⇒ `OPEN` (detector line stays open); any condition False ⇒ `OPEN` regardless of `ucl`.

**Done when:**
- `test_eval_harness_union_adjudication.py::test_verdict_kill_requires_ucl_and_all_conditions` passes
- `test_eval_harness_union_adjudication.py::test_verdict_dead_zone_band_is_neither_kill_nor_open` passes

---

#### FIRG-015: Dead-zone rule text signed before the run

**Trace:** FIR-13 S3, executive summary
**Priority:** P1

`benchmarks/protocols/t14-dead-zone-rule.md` — template with blanks for the operator to fill (kill threshold, dead-zone band, the 30-image exhaustive subset identity) and an MCP decision id field the operator records before T-14 executes. Not a code item; verified by file existence and a non-empty decision-id field once signed.

**Done when:**
- `benchmarks/protocols/t14-dead-zone-rule.md` exists and its blanks are unfilled at spec-review time (signing happens later, at T-14 run time, by the operator)
- `union_adjudication.check_conditions` (FIRG-011) refuses to run (raises) if invoked with `signed_decision_id=None`, i.e. without a decision id referencing the signed template

---

### Face-label rule — T-09 (FIRG-020..029)

#### FIRG-020: `face-label-rule.md` rubric document

**Trace:** FIR-13 S1, QA v8 T-09
**Priority:** P0

New `benchmarks/protocols/face-label-rule.md` with a frozen-version header (`RUBRIC_VERSION = "face-label-rule/v1"`, matching the constant in FIRG-021) stating what counts as a face, refusal classes, and the disagreement procedure.

**Before:** `benchmarks/protocols/` has no `face-label-rule.md` file today (this is a new artifact per FIR-13 S1; not a codemap-scoped path — `benchmarks/` is docs-scope per house rule).

**Done when:**
- `benchmarks/protocols/face-label-rule.md` exists with a version header matching `RUBRIC_VERSION` in `gate_contract.py`
- The document is frozen (no sample may be drawn against a rubric version whose header postdates the sample's draw date — checked at review, not by code)

---

#### FIRG-021: Five refusal/inclusion classes and disagreement procedure

**Trace:** FIR-13 S1, QA v8 T-09
**Priority:** P0

The rubric covers, verbatim, the five classes named in the T-09 QA row: hand-only, back-of-head, heavy occlusion, depiction (photo-of-a-photo / poster / screen), sub-threshold size. Disagreement procedure: named adjudicator, escalation queue is [HITL-07]-only (not general HITL), pre-adjudication labels retained by policy (never overwritten in place — a new adjudicated label is appended, the draft label stays queryable).

**Done when:**
- `face-label-rule.md` has one subsection per refusal/inclusion class (5 total) plus a "Disagreement Procedure" section naming the escalation queue
- `gate_contract.RUBRIC_VERSION` matches the document's header string exactly (string equality check in `test_eval_harness_gate_contract.py::test_rubric_version_matches_frozen_doc`)

---

### Toolchain provenance and withdrawal (FIRG-030..039)

#### FIRG-030: `WITHDRAWN.md` register

**Trace:** FIR-14 S1 [DRIFT-03], [EVAL-28]
**Priority:** P0

New `benchmarks/results/WITHDRAWN.md` lists the five `golden150-fir-{baseline,v2,final,buffalo,buffalo-baseline}-20260723/` result directories plus the numeric artifacts M-12 (0.865/0.321), recall 0.504, and 2.73 faces/image, each with a withdrawal reason drawn from: pre-CVUP-1 toolchain, contaminated GT, apparent-not-prevalence. No task plan, report, or decision may cite these five directories or three numbers as evidence going forward — "withdrawn" is the only permitted context per the common brief.

**Done when:**
- `benchmarks/results/WITHDRAWN.md` lists all five directories (verified against `ls benchmarks/results/golden150-fir-*-20260723/`) and all three numeric artifacts, each with a reason from the fixed set above
- `make eval-anchor-check` (root Makefile ~839–895) does not read from any withdrawn directory as an active baseline

---

#### FIRG-031: Toolchain block in every face report

**Trace:** FIR-14 S1
**Priority:** P0

`score_face_run_record` (`report.py` 4224–4987, the function `build_face_reports` at 5609–5637 calls to produce the scored dict) gains a top-level `toolchain` key with the canonical schema (D8, shared verbatim with FIR-14's task-plan doc): `{"opencv": str, "onnxruntime": str, "numpy": str, "opencv_major": int}`, sourced field-for-field from `provenance.numeric_runtime_fingerprint()` (verified at `provenance.py` 382–401; `NumericRuntimeFingerprint` fields `opencv_version`/`opencv_major`/`onnxruntime_version`/`numpy_version` verified via codemap at `provenance.py` 333–379). `NumericRuntimeFingerprint.compact` IS a `@property` (`provenance.py` 372–379) — where a single human-readable log line is wanted elsewhere (never as a substitute for this structured block), write `fingerprint.compact` with no call parentheses.

**Before:** `score_face_run_record`'s returned dict has no `toolchain` key (verified via codemap: function exists at `report.py` 4224–4987; the specific absence of a `toolchain` field was not exhaustively diffed against all 763 lines — treat as `[UNVERIFIED — confirm via codemap]` at implementation time for the exact insertion point, though the anchor itself is verified).

**After:** the returned dict gains
```python
fp = numeric_runtime_fingerprint()
scored["toolchain"] = {
    "opencv": fp.opencv_version,
    "onnxruntime": fp.onnxruntime_version,
    "numpy": fp.numpy_version,
    "opencv_major": fp.opencv_major,
}
```
before serialization in `build_face_reports`.

**Done when:**
- `scene/tests/test_eval_harness_report.py` gains `test_score_face_run_record_includes_toolchain_block` asserting all four keys (`opencv`, `onnxruntime`, `numpy`, `opencv_major`) are present and non-empty
- `build_face_reports` output JSON has a `toolchain` top-level key on every call, public and non-public

---

#### FIRG-032: `score-face --allow-toolchain-drift` refusal gate

**Trace:** FIR-14 S1
**Priority:** P0

`cli.py score-face` (3266–3321, `--manifest`, `--run-record`, `--check-determinism`, `--expect-report`, `--freeze-certification`, `--public`, `--allow-overwrite-report`, `--allow-refused`) gains `--allow-toolchain-drift` (new flag). When `--expect-report` is passed, `score-face` reads the expected report's `toolchain.opencv_major` and the current run's `toolchain.opencv_major` (FIRG-031's typed field — no string parsing of the `opencv` version string) at the expected-report comparison boundary; if they differ and `--allow-toolchain-drift` is absent, the command refuses (non-zero exit) rather than silently comparing across toolchains.

**Before** (`cli.py::main`, `score-face` subcommand argparse block 3246–3321): no `--allow-toolchain-drift` flag exists; `--expect-report` comparisons do not check toolchain major-version parity.

**After:** the subcommand parser gains `parser.add_argument("--allow-toolchain-drift", action="store_true")`; the comparison path raises/exits when majors differ and the flag is absent.

**Done when:**
- `scripts/eval_harness/tests/test_calibrate_face_thresholds.py`-adjacent CLI test (new: `test_eval_harness_cli_score_face.py::test_toolchain_major_drift_without_flag_refuses`) passes
- `test_eval_harness_cli_score_face.py::test_toolchain_major_drift_with_flag_allowed` passes

---

### Attribution — T-01 (FIRG-040..049)

#### FIRG-040: Interim "identity error" definition stated

**Trace:** FIR-15, QA v8 T-01
**Priority:** P0

A mated open-set search unit (`fir_bakeoff_run.MatedSearchUnit`, 151–163) that is an FNIR miss (`open_set_identification._is_fnir_miss`, 102–112) at the FIR-13 gate `tau`, measured on the FIR-14 CV5 re-baseline run, DIAGNOSTIC tier. This definition is interim — it does not distinguish alignment failure from embedding failure by itself; that split is FIRG-041's job.

**Done when:**
- `attribution_split.py` module docstring states this definition verbatim
- `attribution.json` (FIRG-042 output) records the definition string alongside the results, so a later reader cannot misattribute a different identity-error definition to the same numbers

---

#### FIRG-041: Four-arm split harness

**Trace:** FIR-15 S1
**Priority:** P0

New `apps/prototype-description-service/scripts/eval_harness/attribution_split.py`. Detector fixed at YuNet's declared operating point across all four arms: (a) detector landmarks → `FivePointAligner.align` (`aligner.py` 164–198) → SFace (production path); (b) reference landmarks (`landmark_cache.py`) → `FivePointAligner.align` → SFace; (c) detector landmarks → `buffalo_bench.BuffaloFusedLeg` (287–382) fused embed (`ACX_EVAL_BENCH=1`); (d) reference landmarks → buffalo. `BuffaloFusedLeg` performs its own detection/alignment internally and does not accept externally supplied landmarks or crop pixels (`buffalo_bench.py` 287–382 — verified via codemap 2026-09-11) and uses cached embeddings, so it is **inseparable**: arms (c) and (d) cannot hold detector/landmarks fixed the way (a)/(b) do, and must not be read as a controlled landmark-source contrast. Arms (c)/(d) are therefore labeled **reference** in the four-arm table and reported as a **whole-pipeline reference contrast** (`buffalo_l` end-to-end FNIR vs the SFace pipeline's end-to-end FNIR) — never decomposed into a share. Attribution shares and the D-02 branch (FIRG-042/045) are computed from the SFace arms (a)/(b) alone.

**Before:** no `attribution_split.py` module exists (new per FIR-15 S1).

**Done when:**
- `scene/tests/test_eval_harness_attribution_split.py::test_four_arms_share_the_same_detector_operating_point` passes (checked for arms a/b only — c/d are exempted as inseparable reference legs)
- `test_eval_harness_attribution_split.py::test_reference_arms_c_d_are_not_used_in_share_arithmetic` passes

---

#### FIRG-042: Alignment share and buffalo reference gap with paired-bootstrap intervals

**Trace:** FIR-15 S1
**Priority:** P0

`alignment_share = FNIR(a) − FNIR(b)` is the only isolated share: the SFace embedder is held fixed while the landmark source swaps, so the difference is alignment/landmark-quality error (D11). No arm pair in this task holds landmarks fixed while varying only the embedder, so there is **no `embedder_share` field** — the second quantity is `buffalo_reference_gap = FNIR(a) − mean(FNIR(c), FNIR(d))`, a whole-pipeline reference contrast (different detector-alignment-embedder stack), never an isolated embedder attribution. Each quantity carries a paired-bootstrap interval (`B=2000`, `resampling_unit="image"`, fixed `seed`) computed over the same mated-unit population. No single `tau` spans both embedding spaces (FIRG-005): `AttributionResult.tau_by_space: dict[str, float]` keyed `"sface128"` / `"buffalo512"`, each chosen by `select_gate_point(points, max_fpi=...)` at the same declared FPI budget; bootstrap resampling holds each space's `tau` fixed. Arms (a)/(b) are scored at `tau_by_space["sface128"]`, arms (c)/(d) at `tau_by_space["buffalo512"]`. `run_attribution_split` (FIR-15) returns and persists `tau_by_space`. Output `benchmarks/results/attribution-t01-<date>/attribution.json`: `{alignment_share, buffalo_reference_gap, ci: {alignment: [lo, hi], buffalo_reference: [lo, hi]}, reference_fnir: {c: float, d: float}, n_units, tau_by_space: {sface128: float, buffalo512: float}, toolchain}`. The D-02 leg verdict is derived from these two intervals plus `n_units` by the deterministic five-row table pinned in FIR-15 S1 (`MATERIAL_SHARE_FLOOR = 0.03`, `MIN_ATTRIBUTABLE_UNITS = 10`); an EMBEDDER verdict is reached **by elimination only** and must carry the `embedder_verdict_by_elimination_not_isolation` caveat.

**Done when:**
- `test_eval_harness_attribution_split.py::test_share_bootstrap_ci_is_deterministic_given_seed` passes
- `test_eval_harness_attribution_split.py::test_alignment_share_equals_arm_a_minus_arm_b_fnir` passes
- `test_eval_harness_attribution_split.py::test_d02_verdict_table_all_five_rows` passes (unit floor, DETECTOR, EMBEDDER-by-elimination, BOTH, INCONCLUSIVE)
- `attribution.json` schema validated: all required top-level keys present including `reference_fnir`, `ci` has both `alignment` and `buffalo_reference` two-element arrays, and no `embedder_share` key

---

#### FIRG-043: Oracle-before-predicted occlusion ladder

**Trace:** FIR-15 S2
**Priority:** P0

New `apps/prototype-description-service/scripts/eval_harness/occlusion_ladder.py`. `LadderRung` StrEnum {`NONE`, `ORACLE`, `PREDICTED`} (sr-007). Rung 0 (`NONE`) = no occlusion handling. Rung 1 (`ORACLE`) = exact masks: synthetic twins via `synthetic_occlusion.generate_twin_specs` (337–368) by construction, real probes (strata `A_true_occluder`/`B_eyewear`) via hand-drawn masks read through `synthetic_occlusion.anatomy_region_stats(mask, landmarks_px)` (762–784), operator labour, ≤30 probes. Rung 2 (`PREDICTED`) = `face_quality_factors.compute_occlusion_severity` (82–105) eye-patch proxy today; a full per-landmark visibility predictor is FIR-17's deliverable (FIRG-050/052), not this spec's Rung 2. `masked_cosine` (FIRG-044) is first defined in `recognition/infrastructure/embeddings/masked_similarity.py` (settings-independent — see FIRG-055) and this ladder imports it from there rather than defining an eval-local copy. "Oracle gap" = `FNIR(rung0) − FNIR(rung1 with visible-support matching applied)`; if the 95% CI on the oracle gap includes 0, FIR-17's adapter track is **provisionally parked** at $0 (DIAGNOSTIC/DIRECTIONAL evidence parks; it does not terminate — termination requires ADMISSIBLE evidence post FIR-11 R1) and FIR-17 must record that as its exit condition rather than proceeding to S1.

**Before:** no `occlusion_ladder.py` module exists (new per FIR-15 S2).

**Done when:**
- `scene/tests/test_eval_harness_occlusion_ladder.py::test_rung_ordering_is_none_oracle_predicted` passes
- `test_eval_harness_occlusion_ladder.py::test_oracle_gap_ci_includes_zero_flags_parked_track` passes

---

#### FIRG-044: `masked_cosine` invariants

**Trace:** FIR-15 S2, FIR-17 S1/S4
**Priority:** P0

`masked_cosine(probe_vec, gallery_vec, support_mask)` is a dimension-masked cosine over the 128-D SFace embedding space. Two invariants are load-bearing across both the eval-only (FIR-15) and production (FIR-17) call sites: a full mask (`support_mask` all-True) is bit-identical to plain cosine similarity; an empty mask (`support_mask` all-False) raises rather than returning a degenerate `0.0` or `NaN` similarity. There is exactly one definition: `recognition/infrastructure/embeddings/masked_similarity.py::masked_cosine` (settings-independent — no import of `recognition.config.settings`). FIR-15's `occlusion_ladder.py` imports it from there rather than defining an eval-local copy, and FIR-17 S1 (FIRG-052) reuses the same import. `centroid_utils.py` is not used as a location for this function (superseded — see FIRG-055).

**Before:** no `masked_cosine` function and no `masked_similarity.py` module exist in the tree (both new per FIR-15 S2; FIR-17 S4 adds the import-isolation test — see FIRG-055).

**After:**
```python
def masked_cosine(probe_vec: np.ndarray, gallery_vec: np.ndarray, support_mask: np.ndarray) -> float:
    if not support_mask.any():
        raise ValueError("masked_cosine: support_mask has no active dimensions")
    p, g = probe_vec[support_mask], gallery_vec[support_mask]
    return float(np.dot(p, g) / (np.linalg.norm(p) * np.linalg.norm(g)))
```

**Done when:**
- `test_eval_harness_occlusion_ladder.py::test_masked_cosine_full_mask_equals_plain_cosine` passes
- `test_eval_harness_occlusion_ladder.py::test_masked_cosine_empty_mask_raises` passes

---

#### FIRG-045: D-02 decision packet

**Trace:** FIR-15 S3
**Priority:** P1

`benchmarks/results/attribution-t01-<date>/REPORT.md` names the attributed leg (`alignment` | `embedder` | `both` | `inconclusive`) with the FIRG-042 intervals inline (the leg follows FIR-15 S1's deterministic D-02 verdict table over `alignment_share_ci`, `buffalo_reference_gap_ci`, and `n_units`; per D11 the buffalo arms enter only as a whole-pipeline reference gap, so an `embedder` leg is by elimination and carries the mandatory caveat), and the MCP decision template text for `firplan_d02_attribution_<date>`. FIR-17's branch rule (FIRG-050 gating; FIRG-053 is ADR-only per D4, so this decision names its follow-up task rather than gating in-tree code) reads this decision, not the raw JSON. This is decision D-02, distinct from D-03 (corpus prevalence) and D-08 (the D3 open-set adoption decision, QA v8 rows 245/250).

**Done when:**
- `REPORT.md` exists after an attribution run and names exactly one of the four legs
- The MCP decision template text block is present verbatim, ready for `record_event` at run time (not pasted as a finding list — this is a decision template, not a findings list, so the guard-task-plan-findings hook does not apply to a spec)

---

### Inference-only robustness (FIRG-050..059)

#### FIRG-050: `visible_support_matching` knob, default off, forced off under insightface

**Trace:** FIR-17 S1
**Priority:** P0

New `FacePipelineSettings.visible_support_matching: bool` (default `False`, env `RECOGNITION_FACE_VISIBLE_SUPPORT_MATCHING`), validated at load the same way `oact_coefficient` is (`settings.py` 377–384 pattern). `resolve_face_pipeline_knobs` (`settings.py` 549–599) gains a `visible_support_matching` field on `ResolvedFacePipelineKnobs`, forced to `False` under the `"insightface"` branch (mirroring the existing `oact_coefficient=0.0` profile-gate at line ~589) regardless of any env override on `FacePipelineSettings`.

**Before** (`recognition/config/settings.py::resolve_face_pipeline_knobs`, insightface branch, 578–591):
```python
    if profile == "insightface":
        return ResolvedFacePipelineKnobs(
            profile=profile,
            ...
            oact_coefficient=0.0,
            factor_floor_sharpness=float(ENROLLMENT_NOOP_FLOOR_SHARPNESS),
            factor_floor_embedding_norm=float(ENROLLMENT_NOOP_FLOOR_EMBEDDING_NORM),
            factor_ceiling_occlusion=float(ENROLLMENT_NOOP_CEILING_OCCLUSION),
            joint_assignment_enabled=bool(face_pipeline.joint_assignment_enabled),
        )
```

**After:**
```python
    if profile == "insightface":
        return ResolvedFacePipelineKnobs(
            profile=profile,
            ...
            oact_coefficient=0.0,
            visible_support_matching=False,  # profile gate: FIR6S1-M-02-style — never active under insightface
            factor_floor_sharpness=float(ENROLLMENT_NOOP_FLOOR_SHARPNESS),
            factor_floor_embedding_norm=float(ENROLLMENT_NOOP_FLOOR_EMBEDDING_NORM),
            factor_ceiling_occlusion=float(ENROLLMENT_NOOP_CEILING_OCCLUSION),
            joint_assignment_enabled=bool(face_pipeline.joint_assignment_enabled),
        )
```

**Done when:**
- `recognition/tests/unit/test_face_pipeline_knobs.py` gains `test_visible_support_matching_forced_off_under_insightface`
- `RECOGNITION_FACE_VISIBLE_SUPPORT_MATCHING=1` under `profile=insightface` still resolves `visible_support_matching=False`

---

#### FIRG-051: Support-map asset, sha256-verified like models

**Trace:** FIR-17 S1
**Priority:** P1

`recognition/infrastructure/face_pipeline/assets/sface-support-map-v1.json` is a versioned JSON asset (landmark-region → embedding-dimension attribution, derived per FIR-15's attribution recipe run on clean twins). Integrity is verified via an **external manifest entry**, the same sha256 pattern `provenance.py::load_verified_model` (120–182, `~157`) uses for models — NOT a self-hash field embedded in the asset file itself, which would be circular (the digest would need to hash its own bytes including the digest field). The loader is `recognition/infrastructure/face_pipeline/support_map.py::load_support_map(path: Path, *, expected_sha256: str) -> SupportMap`, which validates: region names are exactly the five expected regions (no more, no fewer, no typos); every dimension index is within the 128-D SFace bound `[0, 128)`; no dimension index is duplicated across regions; and the file's sha256 matches `expected_sha256` (sourced from the model-manifest entry, not from the file). Fails closed (raises) on any mismatch or malformed structure.

**Done when:**
- `recognition/tests/unit/test_support_map.py::test_rejects_bad_sha256` passes (external manifest sha256 mismatch)
- `recognition/tests/unit/test_support_map.py::test_rejects_out_of_range_dim` passes (dimension index outside `[0, 128)`)
- `recognition/tests/unit/test_support_map.py::test_rejects_unknown_region` passes (region name not in the fixed five)
- Loading the asset with a corrupted sha256 raises the same exception family `load_verified_model` raises for models

---

#### FIRG-052: `masked_cosine` re-rank site — in-process, not a pgvector post-query re-rank

**Trace:** FIR-17 S1
**Priority:** P0

Verified via codemap (2026-09-11): assignment-candidate similarity is **not** computed by a raw pgvector `<=>` operator at the check-evaluation site. `ConfidenceCheck.evaluate` (`confidence.py` 91–242) reads `similarity = candidate.discovery_similarity` (line ~184), a value already computed upstream. The producing site is `CentroidDiscovery._find_best_centroid_match` (`recognition/application/discovery/centroid.py` 62–87): an in-process `float(np.dot(face_vector, centroid_vec))` over `centroids_by_cluster` (already-materialized numpy arrays), called from `CentroidDiscovery.discover` (30–60), which loops over multiple identities in one call. `masked_cosine` (FIRG-044) therefore substitutes directly for the `np.dot(...)` comparison inside `_find_best_centroid_match` when `visible_support_matching` is on — no DB-level re-rank over top-K candidates is required, because the comparison already happens in Python against materialized vectors, not inside the SQL query itself.

**Per-identity mask data flow (D15):** at runtime there is no oracle occlusion mask — `face_quality_factors.py::estimate_region_visibility(crop: np.ndarray, landmarks: np.ndarray | None) -> RegionVisibility` (five floats in `[0,1]`, a texture proxy per region, no oracle mask) produces the per-face visibility used to build the mask. It is transported as `AssignmentCandidate.region_visibility: tuple[float, float, float, float, float] | None`, set by `CentroidDiscovery.discover` once per face (not once per call) and threaded through to `_find_best_centroid_match`; `None` maps to an all-ones mask (no-op — behaviour-neutral when visibility estimation is unavailable). The mask consumed by `masked_cosine` is built **inside** `_find_best_centroid_match` from that per-face `region_visibility` field for the face currently being matched — never from `self.support_mask` alone, since `self.support_mask` (the static region→dimension map, FIRG-051) has no per-face visibility information and `discover`'s loop compares one face against many identities/centroids in a single call. The static `self.support_mask` and the per-face `region_visibility`-derived mask are combined (AND, or equivalent) to produce the mask actually passed to `masked_cosine`.

**Before** (`recognition/application/discovery/centroid.py::_find_best_centroid_match`, 62–87):
```python
        for cluster_id, centroid in centroids_by_cluster.items():
            centroid_vec = normalize_face_embedding(np.asarray(centroid, dtype=np.float32))
            similarity = float(np.dot(face_vector, centroid_vec))
            if similarity > best_similarity:
                best_similarity = similarity
                best_cluster = cluster_id
```

**After:**
```python
        best_similarity = float("-inf")
        best_cluster: str | None = None
        if not centroids_by_cluster:
            return None, None
        face_mask = self._build_face_mask(region_visibility)  # self.support_mask ∧ per-face visibility; None → all-ones
        for cluster_id, centroid in centroids_by_cluster.items():
            centroid_vec = normalize_face_embedding(np.asarray(centroid, dtype=np.float32))
            if self.visible_support_matching and face_mask is not None:
                similarity = masked_cosine(face_vector, centroid_vec, face_mask)
            else:
                similarity = float(np.dot(face_vector, centroid_vec))
            if similarity > best_similarity:
                best_similarity = similarity
                best_cluster = cluster_id
        return best_cluster, best_similarity
```

Event tag `visible_support_applied` is per-face metadata recorded on the assignment candidate (set whenever `face_mask` narrowed matching for this face); the per-media event aggregates it as `visible_support_applied_count: int`.

**Done when:**
- `recognition/tests/unit/test_visible_support_matching.py::test_knob_off_preserves_plain_dot_product_similarity` passes (bit-identical to current behavior when off)
- `test_visible_support_matching.py::test_knob_on_uses_masked_cosine` passes
- `test_visible_support_matching.py::test_two_faces_with_different_occlusion_regions_in_one_discover_call` passes (two faces, different `region_visibility`, one `discover()` call, each gets its own mask)
- `test_visible_support_matching.py::test_missing_region_visibility_falls_back_to_all_ones_mask` passes
- `test_confidence_check.py` expectations unaffected when the knob is off (default)

---

#### FIRG-053: Pose-head rescue — ADR-only deliverable, no runtime code in FIR-17

**Trace:** FIR-17 S2 (ADR-only)
**Priority:** P1

D4: pose-head rescue's FIR-17 S2 deliverable is the ADR plus a named follow-up task — no settings knob, no runtime code, and no stratum tests land in FIR-17. No COCO-keypoint or person-detector anchor exists in the service today (verified 2026-09-11 via codemap `search_graph` sweep for keypoint|pose|yolo|person: every hit is a landmark-derived proxy or a test fake). A permissively licensed CPU keypoint model has not been selected (Ultralytics AGPL is banned per FIR-7 `license_policy`), so implementing even a no-op stub ahead of that choice would be runtime code with no model to eventually back it — out of scope for S2. `RECOGNITION_FACE_POSE_HEAD_RESCUE` and `FacePipelineSettings.pose_head_rescue` are therefore **not** added by FIR-17; they may be *mentioned* in the ADR as a proposed future knob, and its stratum-isolation contract (rescued crops tagged `rescue=pose_head`, scored as their own eval stratum, never merged into the headline FNIR@FPIR row, FPI reported separately) is *specified* in the ADR for whichever task eventually implements it.

**Done when:**
- The ADR exists, names the proposed knob (`pose_head_rescue` / `RECOGNITION_FACE_POSE_HEAD_RESCUE`) and its stratum-isolation contract as *proposed*, and names a concrete follow-up task id
- No `pose_head_rescue` field is added to `ResolvedFacePipelineKnobs` or `FacePipelineSettings` by FIR-17 S2
- No `test_eval_harness_synthetic_occlusion.py` stratum-isolation test is added by FIR-17 S2 (that lands with the follow-up task's implementation, not here)

---

#### FIRG-054: OACT sign fix — occlusion never lowers the threshold

**Trace:** FIR-17 **S0** ("OACT sign fix") — unconditional, runs before D-02 (FIRG-045) in every FIR-17 branch: EMBEDDER (S0, S1, S4), DETECTOR (S0, S3), INCONCLUSIVE (S0, S2, S3). Every branch includes S0.
**Priority:** P0

`compute_quality_adjustment` (`recognition/application/assignment/quality.py` 80–138, term at line ~136) currently computes `oact_term = -(coeff * severity)`, which — per the runtime inventory's verified fact chain through `ConfidenceCheck.evaluate`'s `final_threshold = base + maturity_adj + quality_adj + curriculum_adj` (`confidence.py` line ~176) — **lowers** the accept threshold as occlusion severity rises, which under an open-set FNIR@FPIR criterion raises FPIR (more false accepts survive under occlusion cover). The fix flips the sign so occlusion only ever makes acceptance **stricter**, never more lenient: `oact_term = +(coeff * severity)`. `oact_coefficient` stays `>= 0` (`clustering.py` `QualitySettings.oact_coefficient` 66–70, `ge=0.0`; `settings.py::_resolve_face_oact_coefficient` 265–267, default `0.0`) — under the new sign, non-negativity now means "never rewards occlusion" rather than its old meaning. The default stays `0.0`, so this sign flip is behaviour-neutral until FIR-6 S4 sets a non-zero value on the remediated corpus. This fix is unconditional (S0) precisely because it must land before the D-02 attribution decision (FIRG-045) is even read — the branch that D-02 selects (EMBEDDER/DETECTOR/INCONCLUSIVE) determines which *later* slices run, not whether S0 runs.

**Before** (`recognition/application/assignment/quality.py::compute_quality_adjustment`, 133–138):
```python
    # OACT: undamped -(coeff × severity); maturity damps base band only (see notes).
    oact_term = 0.0
    if occlusion_severity is not None:
        coeff = float(s.oact_coefficient)
        if coeff != 0.0:
            severity = max(0.0, min(1.0, float(occlusion_severity)))
            oact_term = -(coeff * severity)
```

**After:**
```python
    # OACT (post-FIR-17 sign fix): undamped +(coeff × severity) — occlusion can
    # only make the gate stricter, never more lenient, under the D3 FNIR@FPIR
    # criterion. Maturity damps base band only (see notes). Default coeff=0.0
    # keeps this behaviour-neutral until FIR-6 S4 sets a non-zero value.
    oact_term = 0.0
    if occlusion_severity is not None:
        coeff = float(s.oact_coefficient)
        if coeff != 0.0:
            severity = max(0.0, min(1.0, float(occlusion_severity)))
            oact_term = +(coeff * severity)
```

Docstring line ~96 ("positive = stricter, negative = more lenient" — this describes the return value's overall sign convention, unaffected by the OACT-term flip itself, but the design-notes block above it must be updated to state the new OACT direction explicitly) updated accordingly. `calibrate_face_thresholds.py --oact-coefficient` (1256–1289) documentation updated to "stricter-with-occlusion" semantics.

S0 owns `recognition/application/assignment/quality.py::compute_quality_adjustment` (line ~136) and the existing leniency assertions in `recognition/tests/unit/test_face_quality_factors.py` — lines ~152–153 (`assert on < off`) and ~206–207 (`final_threshold` `<`) — which must flip to the tightening direction, plus any identity-quality/confidence expectations that assumed the old (lenient) sign.

**Done when:**
- `recognition/tests/unit/test_face_quality_factors.py::TestOactDarkScaffold::test_oact_moves_gate_time_threshold_adjustment` (156–207) updated to assert the new (tightening) sign and passes
- `test_face_quality_factors.py` lines ~152–153 (`assert on < off`) and ~206–207 (`final_threshold` comparison) updated to the tightening direction
- `test_identity_quality.py` and `test_confidence_check.py` OACT-dependent expectations updated and pass
- `oact_coefficient=0.0` still produces bit-identical output to pre-fix behavior (behaviour-neutral-at-default regression test)

---

#### FIRG-055: Single shared `masked_cosine` for eval and production

**Trace:** FIR-17 S4
**Priority:** P1

The `masked_cosine` used by FIR-15's `occlusion_ladder.py` (FIRG-044) and the one used by FIR-17's `_find_best_centroid_match` (FIRG-052) must be the same function, imported from one shared pure module, `recognition/infrastructure/embeddings/masked_similarity.py` (D14; `face_pipeline/_common.py`, home to `SFACE_METRIC="cosine"` and `embed_batch` at 27–171, is the settings-free precedent but not the location), that does not import `recognition.config.settings`, preserving `buffalo_bench`'s negative-import isolation pattern (`buffalo_bench.py`'s guarded import at 55–66 is the precedent for "importable by the harness without pulling settings").

**Done when:**
- `grep -rn "def masked_cosine" apps/prototype-description-service/` returns exactly one definition
- Both `occlusion_ladder.py` and `centroid.py` import `masked_cosine` from that one module
- The shared module has no import of `recognition.config.settings` (verified by `python -c "import ast; ..."` or an explicit import-linter rule)

---

### Head-to-head — FIR-16 (FIRG-060..069)

#### FIRG-059: Persisted per-face match score AND winning cluster for the open-set export

**Trace:** FIR-16 S1a
**Priority:** P0

The production export carries no per-face identification score today: `export_map._identities_list` rows are `{media_id, identity_id, bbox, cluster_label, is_auto_label}` (`scripts/bench/export_map.py` 222–258) and `TenantExportService._serialize_identity` (`recognition/application/services/export_service.py` 295–317) emits `confidence` = `MediaIdentity.confidence` (detector confidence, `db/models/identity.py` 56), not a gallery-match similarity. `open_set_identification._is_fpi` / `_is_fnir_miss` need a real `top1_score`, so FIR-16 adds one rather than fabricating it downstream [rg-015]. Persisting only a score cannot reconstruct a rejected search — a rejected face's score with no corresponding gallery identity leaves `top1_name` unrecoverable, and `open_set_identification.py:123` returns no FPI when `top1_name` is absent — so this requirement persists BOTH the score and the pre-gate winning gallery identity together.

**Before:** `MediaIdentity` (`db/models/identity.py` 41–105) has no match-score or match-cluster column; `_serialize_identity` emits no score. `CentroidDiscovery._find_best_centroid_match` (`recognition/application/discovery/centroid.py` 62–87) initializes `best_similarity = 0.0` and updates only on strictly-greater values, so a nonempty gallery whose every similarity is `<= 0.0` returns `best_cluster = None` — indistinguishable from an empty gallery, and the emitted `0.0` is an invented similarity rather than a measured one.

**After:** `MediaIdentity.match_score: Mapped[float | None]` AND `MediaIdentity.match_cluster_id: Mapped[str | None]` (both nullable, no check constraints) written for EVERY detected face from the pre-gate best-centroid match `CentroidDiscovery.discover` (`recognition/application/discovery/centroid.py` 30–60) computes, captured BEFORE the `similarity_threshold` filter is applied (never inside `ConfidenceCheck`) and independent of the confidence-gate accept decision (a sweep truncated at the deployed tau cannot trace the IET curve). `_find_best_centroid_match` (62–87) is fixed to initialise `best_similarity = float("-inf")` / `best_cluster: str | None = None` and to return `(None, None)` when `centroids_by_cluster` is empty — so a real (possibly negative) best-centroid similarity is always returned for a nonempty gallery, and `NULL`/`NULL` is reserved for the genuinely empty-gallery case. `001_identity_schema.py` edited directly (greenfield, no migration chain).

Export path: `MediaIdentityService.list_by_media_ids` (`recognition/interface_adapters/http/deps/stores.py` 165–284) adds `match_score`/`match_cluster_id` to its row shape → `RemoteSceneClient.media_identities` (`scripts/eval_harness/remote_client.py` 212–218) passes them through → `scripts/bench/export_map.py` rows gain `match_score` and `match_cluster_id`. `top1_name` for the gate metric is the enrollment-gallery name of `match_cluster_id` — ground-truth-derived optimistic labels are prohibited as a `top1_name` source for the gate metric. `_serialize_identity` adds `"match_score": identity.match_score, "match_cluster_id": identity.match_cluster_id`; `score_open_set` (FIRG-060) maps `match_score` to `SearchResult.top1_score` and `match_cluster_id` (resolved to its enrollment name) to `SearchResult.top1_name`.

**Done when:**
- `recognition/tests/api/test_media_identities_match_score.py::test_list_by_media_ids_round_trips_match_score` passes
- `recognition/tests/api/test_media_identities_match_score.py::test_rejected_face_keeps_best_centroid_score` passes (score AND cluster id present when the confidence gate rejected the assignment)
- `scripts/bench/tests/test_export_map_match_score.py::test_export_rows_carry_match_score_and_cluster` passes
- `recognition/tests/unit/test_centroid_discovery.py::test_find_best_centroid_match_returns_negative_similarity_when_all_negative` passes (all-negative gallery)
- `recognition/tests/unit/test_centroid_discovery.py::test_find_best_centroid_match_returns_none_for_empty_gallery` passes (empty gallery, distinguished from all-negative)

---

#### FIRG-060: Open-set leg in `scripts/bench/score.py`

**Trace:** FIR-16 S1
**Priority:** P0

`scripts/bench/score.py` (verified via codemap: currently detection-IOU only — `clamp01` 21–22, `iou_tl` 44–57, `hungarian_iou_matches` 60–83, no identification/threshold logic) gains `score_open_set(exports, manifest, *, contract: GateContract, thresholds) -> dict[str, GateSummary]`, one `GateSummary` per stack (schema defined at FIRG-005: `points`, `selected`, `tau`, `probe_outcomes`). It maps each stack's public export into `open_set_identification.SearchResult` lists (mated + non-mated from FIR-11's `probe_only_identities`/strangers), calls `fir_bakeoff_run.score_run` → `RunReport` → `gate_contract.select_gate_point`, one call per stack at its own swept `tau` (FIRG-005); FIR-16 S1/S2 align to this shape, and `RunReport` itself is not extended. `SearchResult.top1_name` is resolved from the export's `match_cluster_id` (FIRG-059) against the enrollment gallery's name table — never a ground-truth-derived optimistic label. FPI is always reported as an integer count; unmeasured cells render `None`, never `0.0`.

**Before:** no identification scoring path exists in `scripts/bench/score.py`.

**Done when:**
- `scripts/bench/tests/test_score_open_set.py::test_maps_export_to_search_results` passes
- `test_score_open_set.py::test_unmeasured_cell_renders_none_not_zero` passes

---

#### FIRG-061: Per-stack `tau` enforcement in the head-to-head report

**Trace:** FIR-16 S1/S2 [EMB-01], [IDX-02]
**Priority:** P0

`scripts/bench/score_report.py` (verified anchors: `assign_tier` 305–335, `build_dual_frames` 733–743) gains an `open_set` section keyed per stack: `{fnir_at_gate, tau, fpi, n_mated, n_nonmated, coverage_gaps, toolchain, contract}`. The section schema enforces one `tau` field per stack — there is no shared/top-level `tau`.

**Done when:**
- `scripts/bench/tests/test_score_report_open_set.py::test_open_set_section_has_per_stack_tau_no_shared_field` passes

---

#### FIRG-062: Paired non-inferiority test with FIR-11 power banner

**Trace:** FIR-16 S2, FIR-11 Slice 4/Slice 5
**Priority:** P0

The head-to-head report's non-inferiority test on FNIR reuses FIR-11's paired procedure (`docs/tasks/fir/FIR-11-gate-corpus-remediation-and-fir-rebaseline-task-plan.md` — the Nam/Tango score-test construction named `paired_ni_score_test`, one-sided α = 0.025, null discordant split `π₀ = (p_d − δ)/(2·p_d)` per FIR-11 §Slice 5 "Re-baseline with 6-arm decomposition and an under-powered banner"; **not yet implemented in code** — `search_graph` for `paired_ni_score_test` returns 0 results as of 2026-09-11, so this is a design-time reference to the FIR-11 plan, not a codemap anchor `[UNVERIFIED — confirm via codemap once FIR-11 lands the function]`). The report carries FIR-11's power ceiling banner: rows under FIR-11's declared power floor render tier DIRECTIONAL at best, never REPORTABLE, regardless of the point estimate.

**Done when:**
- `scripts/bench/tests/test_score_report_open_set.py::test_underpowered_row_capped_at_directional` passes
- The non-inferiority test call site names `paired_ni_score_test` (or FIR-11's eventual export name) rather than reimplementing McNemar/Tango logic locally — single source of truth for the statistical procedure

---

#### FIRG-063: `propose-gate` output block and decision template

**Trace:** FIR-16 S3
**Priority:** P0

`scripts/bench/cross_stack_bench.py propose-gate --report ... --contract ...` (verified via codemap: `cross_stack_bench.py` is a listed module in the FIR-8 package inventory; the `propose-gate` subcommand itself is new) prints a fixed-format block: candidate FNIR@FPIR vs incumbent, non-inferiority margin δ, CI, tier, coverage gaps, the withdrawn-artifact statement (referencing FIRG-030's `WITHDRAWN.md`), and the exact `record_event` decision template text for `fir_gate_decision_<date>`. FIR-6 S6's switch-over cites that decision id — this spec does not perform the switch-over.

**Done when:**
- `scripts/bench/tests/test_propose_gate.py::test_output_block_has_all_required_fields` passes
- `test_propose_gate.py::test_decision_template_names_fir_6_s6_as_consumer` passes

---

#### FIRG-064: FIR-6 S4 precedes the head-to-head run

**Trace:** FIR-16 S3
**Priority:** P0

The head-to-head must not run until FIR-6 S4 (calibration on the remediated corpus, incorporating the FIR-17 OACT sign fix's calibrated coefficient) has produced a calibrated `oact_coefficient` for the candidate stack. `propose-gate` refuses (or emits a DIAGNOSTIC-only tier) when no FIR-6 S4 calibration artifact is referenced in the run's provenance.

**Done when:**
- `test_propose_gate.py::test_missing_fir6_s4_calibration_artifact_caps_tier_diagnostic` passes

---

#### FIRG-065: Licence banner retained

**Trace:** FIR-16 S2
**Priority:** P1

The InsightFace (`buffalo_l`) non-commercial licence banner present in FIR-8's existing cross-stack bench report carries forward unchanged into the `open_set` section — the head-to-head report never implies `buffalo_l` results are licence-clear for commercial use.

**Done when:**
- `test_score_report_open_set.py::test_licence_banner_present_in_open_set_section` passes

---

## Entity / Payload Schemas

### `fir-gate-contract-v1.json` (`benchmarks/manifests/`)
```json
{
  "metric": "FNIR@FPIR",
  "max_fpi": null,
  "n_nonmated_declared": null,
  "rubric_version": "face-label-rule/v1",
  "ratified_by_decision_id": null
}
```
`max_fpi` and `ratified_by_decision_id` stay `null` until the operator ratifies the fixed FPIR operating point (program decision #10843).

### `attribution-t01-<date>/attribution.json`
```json
{
  "alignment_share": "float",
  "buffalo_reference_gap": "float",
  "ci": {"alignment": ["float", "float"], "buffalo_reference": ["float", "float"]},
  "reference_fnir": {"c": "float", "d": "float"},
  "n_units": "int",
  "tau_by_space": {"sface128": "float", "buffalo512": "float"},
  "toolchain": {"opencv": "string", "onnxruntime": "string", "numpy": "string", "opencv_major": "int"},
  "identity_error_definition": "string (verbatim FIRG-040 text)"
}
```
`alignment_share`/`ci.alignment` are computed from the SFace arms alone at `tau_by_space["sface128"]` (D11); `buffalo_reference_gap`/`ci.buffalo_reference` contrast arm (a) against the mean of arms c/d, which are measured at `tau_by_space["buffalo512"]` and reported raw in `reference_fnir` (no CI of their own).

### `sface-support-map-v1.json` (`recognition/infrastructure/face_pipeline/assets/`)
```json
{
  "version": "sface-support-map-v1",
  "region_to_dimensions": {"left_eye": [0], "right_eye": [0], "nose": [0], "mouth_left": [0], "mouth_right": [0]}
}
```
The asset carries no self-hash field — integrity is verified by an external manifest sha256 entry (same scheme as `load_verified_model`, `provenance.py` ~157), never a digest embedded in this file (D13 — a self-hash would be circular). `region_to_dimensions` values are index lists into the 128-D SFace embedding — placeholder shape shown; real indices come from the FIR-15 attribution recipe run on clean twins. `load_support_map` (FIRG-051) rejects any region name outside this fixed five-key set and any dimension index outside `[0, 128)`.

---

## Implementation Tiers

### Tier 1 — Ready to implement

Task plan: `docs/tasks/fir/FIR-13-open-set-gate-contract-task-plan.md`

```
FIRG-001  gate_contract.py + GateContract dataclass       CPU, $0 — no upstream dep
FIRG-002  select_gate_point lowest-tau rule                depends on FIRG-001
FIRG-003  rubric_version stamped into RunReport.to_rows()   depends on FIRG-001 (RUBRIC_VERSION constant); stamping wired into FIR-14's rebaseline output, but the constant + row-stamping requirement is FIR-13 S1
FIRG-004  rank-1/CMC exclusion (design constraint)          independent
FIRG-010  union_adjudication.py + UnionAdjudicationInput    CPU, $0 — no upstream dep
FIRG-011  four T-14 conditions                              depends on FIRG-010
FIRG-012  bootstrap_ucl B=2000                              depends on FIRG-010
FIRG-013  miss_inflate                                      depends on FIRG-010, FIRG-012
FIRG-014  DeadZoneVerdict enum + verdict()                  depends on FIRG-011, FIRG-012
FIRG-020  face-label-rule.md                                independent, docs-only
FIRG-021  five refusal classes + disagreement procedure     depends on FIRG-020, FIRG-003
```

FIRG-001/002/003 and FIRG-010–014 are independent tracks and can be parallelized (D6: FIRG-003 depends on FIRG-001, not the reverse — FIRG-021 depends on FIRG-003, so FIRG-003 freezes first and there is no cycle). FIRG-015 (dead-zone rule signing) and T-14 execution itself are operator labour, not implementation — out of Tier 1.

### Tier 2 — Ready after Tier 1

Task plan: `docs/tasks/fir/FIR-14-opencv5-rebaseline-task-plan.md`

```
FIRG-030  WITHDRAWN.md register                             independent, docs-only
FIRG-031  toolchain block in score_face_run_record          independent
FIRG-032  score-face --allow-toolchain-drift                depends on FIRG-031
```

FIRG-031 must land before FIRG-032 (the flag compares a field FIRG-031 introduces).

### Tier 2 — Attribution and robustness (Phase B/C, CPU, $0)

Phases A–C are corpus-remediation-independent only for scaffolding and DIAGNOSTIC-tier measurement; anything ADMISSIBLE (calibration tagged REPORTABLE in Phase C, D-02/D3 ratification) still waits for FIR-11 R1's remediated manifest (D9).

Task plans: `docs/tasks/fir/FIR-15-attribution-split-and-oracle-ladder-task-plan.md`, `docs/tasks/fir/FIR-17-inference-only-occlusion-robustness-task-plan.md`

```
FIRG-040  interim identity-error definition                 depends on FIRG-002 (gate tau), FIRG-032 (CV5 run)
FIRG-041  four-arm split harness                             depends on FIRG-040
FIRG-042  shares + paired-bootstrap intervals                 depends on FIRG-041
FIRG-043  oracle-before-predicted occlusion ladder            depends on FIRG-002
FIRG-044  masked_cosine invariants                            independent (pure function)
FIRG-045  D-02 decision packet                                depends on FIRG-042, FIRG-043
FIRG-054  OACT sign fix (FIR-17 S0)                            independent — unconditional, runs before D-02 in every branch; default-0.0 keeps it behaviour-neutral
FIRG-050  visible_support_matching knob                       depends on FIRG-044, FIRG-054 (S0); gated on FIR-15 D-02 naming EMBEDDER leg
FIRG-051  support-map asset sha256-verified                   depends on FIRG-045 (attribution recipe output)
FIRG-052  masked_cosine re-rank site                           depends on FIRG-044, FIRG-050
FIRG-053  pose-head rescue ADR (no runtime code)               depends on FIRG-054 (S0); FIR-15 D-02 naming DETECTOR leg names the follow-up task, does not gate FIR-17 code
FIRG-055  shared masked_cosine module                          depends on FIRG-044, FIRG-052
```

FIR-17's branch rule is decided by FIR-15's D-02 output (FIRG-045): every branch runs S0 (FIRG-054) first; EMBEDDER = S0, S1 (FIRG-050/052), S4 (FIRG-055); DETECTOR = S0, S3 (docs-only handoff — FIRG-053's ADR); INCONCLUSIVE = S0, S2 (FIRG-053's ADR), S3. FIRG-050/052/055 (S1/S4) are Tier 3 relative to the EMBEDDER-leg decision even though their code shape is fully specified here; FIRG-053 (S2) never gains code regardless of leg.

### Tier 3 — Blocked on acx-dev-fir stand-up and FIR-6 S4

Design task: `docs/tasks/fir23-stack/FIR23-STACK-task-plan.md` (stand-up, unmerged Slices 1–3)
Task plan: `docs/tasks/fir/FIR-16-open-set-head-to-head-task-plan.md`

```
FIRG-005  both stacks at own tau                             blocked on acx-dev-fir up
FIRG-059  MediaIdentity.match_score persisted + exported       production schema, greenfield edit
FIRG-060  score_open_set in scripts/bench/score.py            blocked on FIRG-005, FIRG-059
FIRG-061  per-stack tau in score_report.py                    depends on FIRG-060
FIRG-062  paired non-inferiority + FIR-11 power banner         depends on FIRG-061, FIR-11 S5 landing paired_ni_score_test
FIRG-063  propose-gate output + decision template              depends on FIRG-061, FIRG-062
FIRG-064  FIR-6 S4 precedes head-to-head                        blocking precondition on FIRG-063
FIRG-065  licence banner retained                                depends on FIRG-061
FIRG-006  operator ratification caps REPORTABLE tier             depends on FIRG-063
```

The head-to-head cannot execute (Phase D) until: acx-dev-fir is standing (FIR23-STACK), FIR-11 R1's remediated manifest exists, the FIR-13 gate contract is ratified, and FIR-6 S4 has produced calibrated knobs including the FIR-17 OACT-fixed coefficient. Phase C ships the instrument (FIRG-060/061 code) without running Phase D.

---

## Spec-Review Gate

No implementation tasks may be created from this spec until:

1. The spec has been reviewed with findings recorded in MCP
2. All review findings are resolved (fixed, deferred with rationale, or wontfix)
3. Validation snippets have been verified against the current package (not guessed)

Reviews of this spec run on codex-remote gpt-6-astra, low effort, per program decision #10843.

---

## Validation

Each block below declares its working directory once (`cd apps/prototype-description-service`); every subsequent command in that block runs relative to it. Repo-root paths (e.g. `benchmarks/`) are written relative to that same working directory as `../../benchmarks/...`, or accessed via an explicit subshell that does not disturb the block's cwd (D19).

### Tier 1 validation

```bash
cd apps/prototype-description-service

# --- FIRG-001/002: gate contract module and selection rule ---
python -m pytest scene/tests/test_eval_harness_gate_contract.py -q

# --- FIRG-010..014: union adjudication ---
python -m pytest scene/tests/test_eval_harness_union_adjudication.py -q

# --- FIRG-003: rubric_version does not regress fir_bakeoff_run ---
python -m pytest scene/tests/test_eval_harness_fir_bakeoff_run.py -q

# --- make surface (repo-root target; run in a subshell so this block's cwd is untouched) ---
(cd ../.. && make test-eval-surface)
```

### Tier 2 validation

```bash
cd apps/prototype-description-service

# --- FIRG-030..032: withdrawal register + toolchain gate ---
python -m pytest scene/tests/test_eval_harness_report.py -k toolchain -q
cat ../../benchmarks/results/WITHDRAWN.md  # manual: 5 dirs + 3 numbers present

# --- FIRG-040..045: attribution split + ladder ---
python -m pytest \
  scene/tests/test_eval_harness_attribution_split.py \
  scene/tests/test_eval_harness_occlusion_ladder.py -q

# --- FIRG-050..055: production robustness knobs (dark by default) ---
python -m pytest \
  recognition/tests/unit/test_face_pipeline_knobs.py \
  recognition/tests/unit/test_visible_support_matching.py \
  recognition/tests/unit/test_face_quality_factors.py \
  recognition/tests/unit/test_confidence_check.py -q
```

### Tier 3 validation (post acx-dev-fir stand-up, FIR-6 S4 done)

```bash
cd apps/prototype-description-service

# --- FIRG-059: persisted match score + cluster export round-trip ---
python -m pytest \
  recognition/tests/api/test_media_identities_match_score.py \
  scripts/bench/tests/test_export_map_match_score.py -q

# --- FIRG-060..065: cross-stack open-set head-to-head (mocked exports, no network) ---
python -m pytest \
  scripts/bench/tests/test_score_open_set.py \
  scripts/bench/tests/test_score_report_open_set.py \
  scripts/bench/tests/test_propose_gate.py -q
```

---

## Requirement → Task plan trace

| Requirement | Task plan / slice |
| --- | --- |
| FIRG-001..006 | FIR-13 S2 |
| FIRG-010..015 | FIR-13 S3 |
| FIRG-020..021 | FIR-13 S1 |
| FIRG-003 | FIR-13 S1 (stamped in FIR-14's rebaseline output) |
| FIRG-030 | FIR-14 S1 |
| FIRG-031..032 | FIR-14 S1 |
| FIRG-040..042, FIRG-045 | FIR-15 S1, S3 |
| FIRG-043..044 | FIR-15 S2 |
| FIRG-054 | FIR-17 S0 (unconditional, all branches, runs before D-02) |
| FIRG-050..051 | FIR-17 S1 |
| FIRG-052 | FIR-17 S1 |
| FIRG-053 | FIR-17 S2 (ADR-only, no runtime code) |
| FIRG-055 | FIR-17 S4 |
| FIRG-059 | FIR-16 S1a |
| FIRG-005, FIRG-060..061 | FIR-16 S1b |
| FIRG-062, FIRG-065 | FIR-16 S2 |
| FIRG-063..064 | FIR-16 S3 |
| FIRG-006 | FIR-16 S3 / FIR-13 S2 (joint) |
