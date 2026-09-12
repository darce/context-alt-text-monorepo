# E22. Commercial Face Identity Replacement

> **Metadata**
>
> - **Date**: 2026-09-11
> - **Author**: Claude Fable 5.1 (claude-fable-5-1) via sonnet drafting agent
> - **Epic Short ID**: FIR
> - **Target Version**: v0.5.0
> - **Status**: in progress — re-planned 2026-09-11 (Phases A–D)
> - **Original grounding**: [commercial-face-pipeline-replacement-assessment-2026-07-15.md](../../assessments/current/commercial-face-pipeline-replacement-assessment-2026-07-15.md) · research guide `acx_commercial_face_recognition_replacement_guide.docx` (2026-07-14) · QA v8 grounding report `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html`
> - **Re-plan grounding**: [gpu-burst-pipeline-status-and-fir-insightface-replacement-2026-09-11.md](../../assessments/current/gpu-burst-pipeline-status-and-fir-insightface-replacement-2026-09-11.md) §4

## Status 2026-09-11 Re-plan

Decision #10843 (session `firplan-1-replan-20260911`) revises this epic rather than opening a new one. The trigger: `face_pipeline` is fully built and dark, but **no admissible measurement exists that would justify switching it on** — the historical rank-based Golden-150 comparison is inadmissible for an open-gallery system, and the numbers that once looked like evidence (M-12 0.865/0.321, recall 0.504, 2.73 faces/image, every pre-CVUP-1 artifact) are withdrawn. Phases A–D below encode the re-plan grounding assessment's §4 recommended approach (measurement before optimization — [PRINCIPLE #15]) as epic phase gates. No task numbers are reused: FIR-13 through FIR-17 are new; FIR-2..FIR-9, FIR-11, FIR-12, FIR23-STACK keep their existing plans, referenced and not restated.

## Goal

Remove the non-commercial InsightFace buffalo weights from the production face-identity pipeline and replace them with an ACX-owned, commercially licensed stack — YuNet 2026may (MIT) detection → five-point alignment → SFace 2021dec (Apache-2.0) 128D embedding → existing clustering — gated by an **open-set FNIR@FPIR head-to-head** against a licensed-use buffalo_l reference on `acx-dev-fir`, with InsightFace surviving only as a benchmark dependency in a non-commercial eval environment.

## Problem Statement

The identity half of the pipeline is the blocker to commercial launch, and it is a measurement problem, not a code problem. `face_pipeline` (YuNet → align → SFace) is built, tested, and selectable behind `RECOGNITION_FACE_PIPELINE_PROFILE` (default `insightface`) — but every existing comparison against buffalo_l is either unrun (FIR-12's open-set instrument merged, zero bake-offs executed) or inadmissible (rank-based, pre-CVUP-1 toolchain, buffalo-contaminated ground truth). A misidentified face is worse than a missed one for this product: a wrong name is injected verbatim into the `<<<CONTEXT>>>` block the VLM captions from, so an open-gallery system must be scored on its ability to reject non-enrolled subjects, not on rank-1 accuracy among enrolled ones.

## UX Vision

No user-visible change until the gate flips. Pre-flip: alt text continues to use the incumbent buffalo_l pipeline; occlusion-mitigation work (visible-support matching) ships dark behind a knob and is scored only in the eval harness; pose-head rescue is ADR-only in this epic (no runtime code, no knob). Post-flip (Phase D, operator-gated): captions continue naming confirmed people, now sourced from the licensed stack, with an equal-or-better rate of "declines to name a stranger" (FNIR@FPIR) than the incumbent — the failure mode a user notices (a wrong name in their caption) must not get worse.

## Constraints

1. **License isolation**: buffalo weights never in production images at commercial exposure; `insightface` only in a `[bench]` extra; benchmark embeddings never in the production DB. (Fixed-dim pgvector columns enforce this structurally only once prod is 128D — until the FIR-6 flip both are 512D, so pre-cutover separation is procedural: eval-env-only buffalo legs + run-artifact storage.)
2. **Dark until gated** (RLSE-02/07): the new pipeline wires in behind a face-pipeline profile flag; the production default does not change until an **operator-recorded MCP gate decision** exists (bake-off report proposes; operator decides; switch-over slice is blocked without it).
3. **CPU-first**: ARM A1 is the production path; A10/CUDA is bake-off-first, production GPU is follow-on (FIR-7).
4. **Greenfield after verification**: no data migrations — but FIR-2 must first enumerate live tenants and record operator wipe/re-scan sign-off. The dimension **defaults** flip (512→128, `EMBEDDING_DIMENSION` + `PGVECTOR_DIM` + deploy configs) lands only in FIR-6's gated switch-over slice, so every FIR-4 deliverable is mergeable dark (no slice held hostage to a later gate); dev/eval environments exercise the 128D pipeline earlier via the `PGVECTOR_DIM` env without touching defaults.
5. **Thresholds are measured, never copied** (guide §8.1, PERF-06): every similarity/quality/unknown threshold comes from FIR-6 calibration on ACX data.
6. **Reuse VLM-6's Golden-150 harness** — six coordination asks + fallbacks per scope §Coordination; no parallel corpus, no forked walker without a recorded decision.
7. **Corpus locked to FIR-11 R1** [MLDATA-02/09]: Golden-150 as remediated by FIR-11 R1 (150 − 7 celebrity − 3 scraped → 30 entries / 30 probes / 17 identities usable for the paired Nam/Tango non-inferiority check; Product A/B split). FIR-11 rev 7 is the corpus plan of record; new plans consume it, never restate its arithmetic.
8. **No GPU spend, no retrain, before D-01** [COST-03]: no A10 spend before D-01, reached only via T-09 → T-14 → D-01; no SCRFD/AdaFace retrain. Occlusion work (FIR-17) is inference-only — no training — until D-01 says otherwise.
9. **Two embedding spaces, two stacks** [EMB-01, IDX-02]: `acx-dev-fir` (FIR23-STACK) must exist before any head-to-head; the head-to-head runs both stacks over public APIs — a mixed-space query across 512D buffalo and 128D SFace vectors is meaningless, so no shared-threshold comparison is admissible.
10. **D3 is the headline gate metric, declared not copied** [EVAL-18/19]: FNIR at a fixed FPIR (open-set, non-mated probes, score threshold swept), FPI reported as an **integer count, never a rate** (a rate rewards the detector for emitting more false detections). The operator ratifies the fixed FPIR operating point; plans must not hard-code one — they name the parameter and the ratification step.
11. **Withdrawn numbers are never evidence** [DRIFT-03, EVAL-28]: M-12 0.865/0.321, recall 0.504, 2.73 faces/image, every pre-CVUP-1 (OpenCV 4.x) artifact may be mentioned only as "withdrawn." "Embedder leads detector" is a hypothesis pending FIR-15, not a result.

## Terminology

- **FNIR@FPIR**: False Non-Identification Rate at a fixed False Positive Identification Rate — the open-set headline metric (D3); measured with non-mated probes against an open-set gallery at a swept score threshold.
- **FPI**: False-Positive-Identification count — an integer, never a rate.
- **DIAGNOSTIC / DIRECTIONAL / REPORTABLE tiers**: evidence strength tiers a result carries depending on corpus power and exhaustiveness; a DIAGNOSTIC or DIRECTIONAL result cannot gate a decision alone. DIAGNOSTIC/DIRECTIONAL evidence may provisionally PARK a track (e.g. the adapter track, pose rescue); TERMINATING a track requires ADMISSIBLE evidence (post FIR-11 R1).
- **Golden-150**: the locked eval corpus; post-FIR-11-R1 remediation, 30 entries / 30 probes / 17 identities are usable for the gating paired non-inferiority check.
- **acx-dev-fir**: the isolated benchmarking stack (FIR23-STACK) — `PGVECTOR_DIM=128`, DB `alt_context_dev_fir`, standing next to the existing 512D dev stack.
- **pre-CVUP-1**: any artifact produced before the OpenCV 4.x → 5.0.0.93 upgrade; withdrawn as a comparison arm.
- **T-01 / T-09 / T-14**: QA v8 task IDs — T-01 alignment-vs-embedder split (feeds D-02); T-09 face-label rubric (feeds D-09, gates all adjudication); T-14 union adjudication (feeds D-01, the detector-line kill decision).
- **D-01 / D-02 / D-03 / D-08**: QA v8 decision IDs — D-01 detector-line kill/keep; D-02 alignment-vs-embedder attribution verdict; D-03 corpus prevalence (not the gate metric); D-08 the D3 open-set gate metric adoption decision (QA v8 rows 245/250). D3 (the metric) and D-03 (the decision) are distinct; never alias one to the other.

## Current State

- `face_pipeline` (YuNet → FivePointAligner → SFace) is fully built, tested, and dark: `recognition/config/settings.py` `_resolve_face_pipeline_profile()` resolves `RECOGNITION_FACE_PIPELINE_PROFILE` (default `"insightface"`, `ValueError` on unknown) and `build_embedding_runtime(...)` (`recognition/infrastructure/embeddings/runtime_factory.py:37-110`) branches on it.
- The open-set instrument exists but has never produced a number: `scripts/eval_harness/open_set_identification.py` (`IETPoint`, `fnir_fpi_at_threshold`, `iet_curve`) and `scripts/eval_harness/fir_bakeoff_run.py` (`score_run` → `RunReport`) are merged and tested; no bake-off has been run against them.
- The occlusion signal that exists today is disabled and, if enabled, points the wrong way: `compute_quality_adjustment` (`recognition/application/assignment/quality.py:80-138`, line 136 `oact_term = -(coeff * severity)`) makes a positive `oact_coefficient` **lower** the accept threshold as occlusion rises, which raises FPIR under an open-set criterion — the coefficient defaults to `0.0` (dark no-op) and non-negativity (`clustering.py` `QualitySettings.oact_coefficient`, ge=0.0) currently only prevents the opposite mistake, not this one.
- No `[face]` pyproject extra and no `unknown_threshold`/`ambiguity_margin` settings exist in the runtime today (verified negative) — quality gating runs through `ConfidenceCheck.evaluate` (`recognition/application/assignment/checks/confidence.py:91-242`) alone.

### Task ledger (2026-09-11)

| Task | Title | Status |
| --- | --- | --- |
| FIR-2 | Pipeline seam hardening + provenance | done (merged) |
| FIR-3 | YuNet+SFace adapters | done (merged) |
| FIR-4 | Runtime integration (dark) + license isolation | done (merged S1; S2–S5 review docs present) |
| FIR-5 | Bake-off harness extension | done (merged, feature/fir-5 `c10eac1d8`) |
| FIR-6 | Calibration + quality rework + switch-over | in progress — S1, S3a merged; S2, S3b dark; S4/S5 corpus-gated; S6 operator-gated (needs MCP gate decision row) |
| FIR-7 | Occlusion adapters (v6.2) | not started — 0 of 43 checklist items; training slices (2–4) frozen behind `TRAINING_DECISION` / D-01 |
| FIR-8 | Recognition-profile bench toggle (v6.7) | in progress — 56 of 59 checklist items done; `scripts/bench/` package on main; no open-set leg; live E2E blocked on FIR23-STACK |
| FIR-9 | Workbench curation atlas | done (merged) |
| FIR-11 | Gate-corpus remediation and FIR re-baseline | plan only (rev 7); Slices 0–6, S5 = re-baseline with 6-arm decomposition |
| FIR-12 | Open-set identification eval harness | done (merged `d567a341c` 2026-08-22, exemption rule `fa3341409`); instrument only, no bake-off run |
| FIR23-STACK | Isolated `acx-dev-fir` benchmarking backend | plan only (rev 2); Slices 1–3 unmerged; stack never stood up |
| FIR-13..17 | New Phase A–D tasks (this re-plan) | plans drafted 2026-09-11, pending planning review — see Phased Delivery |

## Applied Concepts from Sources

| Source | Concept | Epic application |
| --- | --- | --- |
| Re-plan assessment §4 Phases A–D | measure before optimizing [PRINCIPLE #15] | This epic's Phased Delivery adopts the assessment's ordering as hard phase gates, not a suggestion |
| QA v8 T-14 dead-zone rule | bounded, pre-declared kill criterion for a detector line | FIR-13 S3 (`union_adjudication.py`) encodes the four mandatory T-14 conditions and a `DeadZoneVerdict` that defaults to OPEN, never KILL, on any violated condition |
| PDSN / PLGSA occlusion-recognition literature | visible-support / periocular masking of occluded embedding dimensions | FIR-17 S1 `masked_cosine` — inference-only, no training |
| Heuristics canon [heuristics-canon](https://github.com/darce/heuristics-canon) | EVAL-18/19 (rank-based metrics inadmissible for open-gallery), EMB-01/IDX-02 (no cross-space comparison), AUDIT-04/MEAS-07 (pre-declared bounds, bootstrap over point estimates) | Constraints 9–10 and the evidence gate chain below |

## Target Architecture

The epic's evidence model is a chain of decisions, each with a named cheap-first predecessor, none skippable: a frozen face-definition rubric feeds a bounded detector-line kill test, which feeds the metric declaration that every downstream comparison must use; independently, a $0 attribution split decides which leg (alignment or embedder) is worth building occlusion mitigations for, before any of those mitigations are built. Only after both chains resolve does the program stand up the second stack and spend engineering time on a live head-to-head; only after that head-to-head produces an admissible number does the operator gate decision exist that FIR-6's switch-over slice is blocked on.

### Design Decisions

| Decision | Rationale |
| --- | --- |
| D3 = FNIR@FPIR, not rank-based accuracy | The production system is open-gallery (must reject strangers); rank-based Golden-150 head-to-heads never modeled rejection and are inadmissible as a gate ([EVAL-18/19]) |
| FPI is an integer count, never a rate | A rate improves when the detector emits more false detections — it rewards the failure it exists to catch |
| Corpus locked to FIR-11 R1, never re-derived per-task | Every task inheriting an independently-remediated corpus arithmetic invites drift; one remediation, many consumers |
| Attribution (FIR-15) before occlusion engineering (FIR-17) | Building visible-support matching before knowing whether the embedder or the alignment leg carries the loss risks building the wrong fix at zero information gain over waiting one day for T-01 |
| Two isolated stacks (`acx-dev-fir`), not a runtime profile toggle | A 512D and a 128D embedding space are not comparable in one query; isolation is structural, not a flag ([EMB-01, IDX-02]) |
| Inference-only occlusion mitigations until D-01 | Training spend is gated behind a cheap detector-line kill test (T-14); building trained mitigations first would spend GPU before knowing if the detector line is even open |

### Data Model

The epic's canonical artifact is not a schema but an evidence-gate chain — each node is a recorded decision or frozen document that the next node's plan must cite by ID, never restate:

| Gate | Input | Output | Consumed by |
| --- | --- | --- | --- |
| T-09 rubric frozen | face-definition disagreement cases | `benchmarks/protocols/face-label-rule.md`, `RUBRIC_VERSION` | T-14 adjudication, all downstream labeling |
| T-14 adjudication → D-01 | Golden-150 union-adjudicated boxes at matched-FPPI operating points | `DeadZoneVerdict` {KILL, DEAD_ZONE, OPEN} | FIR-17 branch rule (detector leg open/closed) |
| T-01 split → D-02 | four-arm alignment/embedder attribution, oracle occlusion ladder | attribution verdict (embedder \| detector \| both \| inconclusive) with CIs | FIR-17 branch rule (which slices run) |
| D3 declaration → ratification | `GateContract` (metric, max_fpi, rubric_version, `ratified_by_decision_id: null` until ratified) | operator-ratified fixed FPIR operating point (`firplan_d3_operating_point_<date>` MCP decision) | FIR-16 `select_gate_point`, FIR-6 S4/S5/S6 |
| FIR-16 head-to-head → operator gate decision | FNIR@FPIR on `acx-dev-fir`, remediated corpus, CV5 toolchain | `fir_gate_decision_<date>` MCP decision | FIR-6 S6 switch-over |

## Phased Delivery

### Phase A: Contract + Re-baseline -- in-progress

> **Status**: in-progress (FIR-11 R1 corpus remediation at plan rev 7; FIR-13/FIR-14 plans drafted, pending planning review)
> **Task plans**: FIR-11 `docs/tasks/fir/FIR-11-gate-corpus-remediation-and-fir-rebaseline-task-plan.md` (existing, rev 7) · FIR-13 drafted 2026-09-11 (pending planning review): `docs/tasks/fir/FIR-13-open-set-gate-contract-task-plan.md` · FIR-14 drafted 2026-09-11 (pending planning review): `docs/tasks/fir/FIR-14-opencv5-rebaseline-task-plan.md`

**Goal**: make the open-set question answerable, at $0 GPU spend.

Deliverables:

- Face-label rubric frozen (T-09) with a versioned `RUBRIC_VERSION` stamped into every published eval row (FIR-13).
- D3 gate contract encoded (`GateContract`, `select_gate_point`) with the operating point left `null` pending operator ratification (FIR-13).
- T-14 union-adjudication rule encoded, including the 0.05/0.10 dead-zone bounds and all four mandatory conditions (FIR-13).
- Withdrawal register (`benchmarks/results/WITHDRAWN.md`) naming every pre-CVUP-1 artifact and estimand; OpenCV 5.x re-baseline run on both legs (FIR-14).
- Golden-150 remediated to FIR-11 R1 (30 entries / 30 probes / 17 identities).

Exit criteria:

- `gate_contract.py` loads `benchmarks/manifests/fir-gate-contract-v1.json` and fails closed on a malformed contract (rg-008).
- The withdrawal register exists and no re-baseline report cites a pre-CVUP-1 number.
- FIR-11 R1 corpus lands with the Nam/Tango paired non-inferiority check and Product A/B split usable.

### Phase B: Attribution -- not-started

> **Status**: not-started
> **Task plans**: FIR-15 drafted 2026-09-11 (pending planning review): `docs/tasks/fir/FIR-15-attribution-split-and-oracle-ladder-task-plan.md`

**Goal**: attribute identity error between alignment and embedder, and establish whether an occlusion predictor could ever help, before building either.

Deliverables:

- T-01 alignment-vs-embedder split harness (`attribution_split.py`) with a paired-bootstrap interval on each leg's share.
- Oracle-before-predicted occlusion ladder (`occlusion_ladder.py`); the oracle gap decides whether FIR-17's adapter track is worth building at all.
- D-02 decision packet naming the leg (embedder | detector | both | inconclusive).
- FIR-17 S0 (OACT sign fix): unconditional, lands before the D-02 decision in every branch (EMBEDDER, DETECTOR, INCONCLUSIVE) — `compute_quality_adjustment` (`recognition/application/assignment/quality.py:136`) becomes `oact_term = +(coeff*severity)`, with the leniency assertions in `recognition/tests/unit/test_face_quality_factors.py` updated to the tightening direction; default `0.0` unchanged.

Exit criteria:

- D-02 decision recorded in MCP with the attribution shares and their intervals.
- If the oracle gap's 95% CI includes 0, the record PARKS the adapter track at $0 (DIAGNOSTIC/DIRECTIONAL evidence may provisionally park a track; only ADMISSIBLE evidence, post FIR-11 R1, can terminate it) and FIR-17 is scoped down accordingly pending that admissible evidence.
- FIR-17 S0 merged (OACT sign fix), default `0.0` unchanged, behaviour-neutral until FIR-6 S4.

### Phase C: Inference-Only Occlusion + Head-to-Head Instrument -- not-started

> **Status**: not-started; plans drafted 2026-09-11 (blocked on Phase B's D-02 decision for FIR-17's branch; FIR-16's instrument work does not need D-02)
> **Task plans**: FIR-16 (S1a adds `MediaIdentity.match_score` and `MediaIdentity.match_cluster_id` to the production export so the open-set leg has a real `top1_score`/`top1_name`): `docs/tasks/fir/FIR-16-open-set-head-to-head-task-plan.md` · FIR-17 drafted 2026-09-11 (pending planning review): `docs/tasks/fir/FIR-17-inference-only-occlusion-robustness-task-plan.md` · FIR-6 `docs/tasks/fir/FIR-6-calibration-quality-switchover-task-plan.md` (existing, S4) · FIR23-STACK `docs/tasks/fir23-stack/FIR23-STACK-task-plan.md` (existing, rev 2)

**Goal**: build what D-02 justified, stand up the second stack, and build the head-to-head scoring instrument — without running the live comparison or spending GPU.

Deliverables:

- Visible-support (periocular) matching behind a default-off knob (FIR-17 S1), per the D-02 branch rule; pose-head rescue is ADR-only (FIR-17 S2) — the deliverable is the ADR plus a named follow-up task, no settings knob and no runtime code in FIR-17. (FIR-17 S0, the OACT sign fix, already landed in Phase B — see above.)
- `acx-dev-fir` stood up per FIR23-STACK (compose project `acx-dev-fir`, DB `alt_context_dev_fir` @ `PGVECTOR_DIM=128`).
- Open-set leg added to the cross-stack bench (`scripts/bench/score.py` `score_open_set`, `score_report.py` open-set section) against mocked exports — no live run yet.
- FIR-6 S4 calibration (including the OACT sign fix) on the remediated corpus.

Exit criteria:

- New knob (`visible_support_matching`) merged dark (default off) with unit coverage; `resolve_face_pipeline_knobs` continues to force it off under the `insightface` profile. Pose-head rescue has no knob to force off — it stays ADR-only.
- `acx-dev-fir` `/health` and `/ready` green.
- `scripts/bench/test_score_open_set.py` and `test_score_report_open_set.py` green against mocked exports.
- FIR-6 S4 threshold set (using the sign already fixed in FIR-17 S0) recorded as a decision.

### Phase D: Run + Flip -- not-started

> **Status**: not-started
> **Task plans**: FIR-16 S4 (live run) · FIR-6 `docs/tasks/fir/FIR-6-calibration-quality-switchover-task-plan.md` S5/S6 (existing)

**Goal**: run the re-baselined FNIR@FPIR head-to-head on `acx-dev-fir` and flip the production default only behind an operator-recorded gate decision.

Deliverables:

- Live open-set run on `acx-dev-fir` (both stacks, remediated corpus, CV5 toolchain); `propose-gate` report.
- Operator-recorded MCP gate decision (`fir_gate_decision_<date>`).
- FIR-6 S5 (final threshold) and S6 (switch-over: flip `RECOGNITION_FACE_PIPELINE_PROFILE` + `PGVECTOR_DIM` together, remove `.[bench]` InsightFace install from the production Dockerfile).

Exit criteria:

- Gate decision references FNIR@FPIR at the operator-ratified operating point on the FIR-11 R1 corpus, CV5 toolchain, with all withdrawn artifacts excluded.
- Production defaults flipped together (no split-brain dimension state); buffalo weights removed from production images.

## Exit Criteria

Scope doc [Success criteria 1–7](../../scopes/commercial-face-identity-replacement.md#success-criteria) plus the re-plan addendum, summarized: no buffalo weights in prod images; end-to-end scan→cluster→curate on YuNet+SFace with falsifiable unknown-first behavior; bake-off report incl. occlusion (real + synthetic-paired) and throughput/cost legs; operator-recorded gate decision preceding switch-over; golden parity tests green on `make check-remote`; per-row `embedding_model` provenance + build/boot hash verification; recorded greenfield sign-off; **and**: the gate decision references FNIR@FPIR at the operator-ratified operating point on the FIR-11 R1 corpus, measured on the CV5 toolchain, with withdrawn artifacts excluded from evidence.

## Task Decomposition

Task definitions, dependency edges, and deliverables are canonical in the scope doc's [Task decomposition table](../../scopes/commercial-face-identity-replacement.md#task-decomposition) and its [Re-plan addendum 2026-09-11](../../scopes/commercial-face-identity-replacement.md#re-plan-addendum-2026-09-11). Task plans live in `docs/tasks/fir/` as `FIR-<n>-*-task-plan.md`. **Just-in-time authoring is owned**: the agent starting a phase authors that phase's plans at phase entry (trigger: predecessor task reaches `done`), and every plan passes `/planning-review` with verdict `pass`/`pass_with_findings` before its `make task-start` — no plan, no branch.

## External Dependencies

| Dependency | Owner | Status | Blocks |
| --- | --- | --- | --- |
| Operator T-09 rubric authorship + T-14 dead-zone sign-off | Operator | Not started | Phase A exit, D-01 |
| Operator D3 FPIR operating-point ratification | Operator | Not started | Phase A/D FIR-16 `select_gate_point` |
| `acx-dev-fir` stand-up (FIR23-STACK) | Engineering | Plan only, stack never stood up | Phase C/D head-to-head, FIR-8 live E2E |
| Operator gate decision (fail/pass verdict) | Operator | Not started | FIR-6 S6 switch-over |
| FIR-11 R1 corpus remediation | Engineering | Plan only (rev 7) | Phase A exit, all downstream comparisons |

## Code Anchors

| Layer | File | Note |
| --- | --- | --- |
| Profile resolution | `recognition/config/settings.py` `_resolve_face_pipeline_profile()` (62–69) | Env `RECOGNITION_FACE_PIPELINE_PROFILE`, default `"insightface"`, fails closed on unknown |
| Runtime factory | `recognition/infrastructure/embeddings/runtime_factory.py` `build_embedding_runtime()` (37–110) | Branches on `settings.face_pipeline.profile` (line 59–60) |
| OACT term (to be sign-flipped in FIR-17 S0) | `recognition/application/assignment/quality.py` `compute_quality_adjustment()` (80–138, line 136) | Currently `oact_term = -(coeff * severity)`; positive coefficient lowers the threshold under occlusion |
| Occlusion severity proxy | `recognition/infrastructure/embeddings/face_quality_factors.py` `compute_occlusion_severity()` (82–105) | Two fixed eye patches vs whole-crop baseline; no spatial mask |
| Open-set instrument | `scripts/eval_harness/open_set_identification.py` `fnir_fpi_at_threshold()` (128–167), `IETPoint` (56–99) | FNIR = misses/n_mated or `None`; FPI raw integer count, never a rate |
| Bake-off run scoring | `scripts/eval_harness/fir_bakeoff_run.py` `score_run()` (410–536) | Consumes `SearchResult` lists; no CLI in-module |
| Cross-stack bench package (FIR-8) | `apps/prototype-description-service/scripts/bench/` | 34 modules on main; no open-set leg yet (FIR-16 adds one) |
| Deploy stack iteration | `scripts/deploy/recognition-service.sh` `do_status()` | Iterates `dev dev-fir staging prod` |

---

# Consolidated Checklist

## Phase A: Contract + Re-baseline -- in-progress

- [ ] T-09 face-label rubric frozen (`benchmarks/protocols/face-label-rule.md`, `RUBRIC_VERSION`)
- [ ] D3 `GateContract` + `select_gate_point` encoded, operating point `null` pending ratification
- [ ] T-14 union-adjudication rule encoded (`union_adjudication.py`, `DeadZoneVerdict`)
- [ ] Withdrawal register published (`benchmarks/results/WITHDRAWN.md`)
- [ ] OpenCV 5.x re-baseline run on both legs, DIAGNOSTIC tier
- [ ] FIR-11 R1 corpus remediation landed (30 entries / 30 probes / 17 identities)

## Phase B: Attribution -- not-started

- [ ] T-01 alignment-vs-embedder split harness + report
- [ ] Oracle-before-predicted occlusion ladder scored
- [ ] D-02 decision recorded (embedder | detector | both | inconclusive)
- [ ] FIR-17 S0: OACT sign fix merged (unconditional, before D-02 in every branch; default `0.0` unchanged)

## Phase C: Inference-Only Occlusion + Head-to-Head Instrument -- not-started

- [ ] Visible-support matching merged dark, per D-02 branch rule (FIR-17 S1)
- [ ] Pose-head rescue: ADR + named follow-up task recorded, no runtime code or settings knob (FIR-17 S2)
- [ ] `acx-dev-fir` stood up (FIR23-STACK)
- [ ] Open-set leg added to cross-stack bench, tested against mocked exports
- [ ] FIR-6 S4 calibration landed on remediated corpus

## Phase D: Run + Flip -- not-started

- [ ] Live open-set head-to-head run on `acx-dev-fir`
- [ ] `propose-gate` report published
- [ ] Operator-recorded MCP gate decision
- [ ] FIR-6 S5 final threshold + S6 switch-over (flag + dimension flip, `.[bench]` removed)

## Deferred (Post-v0.5.0)

- [ ] Head/torso secondary channel (C4) — association only, never an identity claim on its own
- [ ] Trained detector/embedder (SCRFD, AdaFace, DCFace-synthesised occlusion) — behind the failed-gate escalation ladder only (unowned, parked; see scope doc Not-Doing — not FIR-8, which is the recognition-profile bench toggle), on a failed gate
- [ ] VLM-6 caption bake-off — separate program; shared eval manifest schema is the only coupling
