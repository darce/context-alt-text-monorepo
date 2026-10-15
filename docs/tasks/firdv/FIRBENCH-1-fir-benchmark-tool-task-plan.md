# Task Plan

> **Metadata**
>
> - **Date**: 2026-10-15 (revision v4; v2 dated 2026-10-14)
> - **Author**: Claude Opus 5.5 (claude-opus-5-5); revision v4 by Claude Haiku 5.5 (claude-haiku-5-5)
> - **Project**: prototype-description-service eval harness (related epic: [E24 FIRDV](../../epics/v0.5.0/fir-development-and-measurement-epic.md))
> - **Task ID**: `FIRBENCH-1`
> - **Target Branch**: `feature/firbench-1`
> - **Review Coverage Target**: 2
> - **Status**: draft v4, second gate-defect dispatch after FB1-DPLAN-01. Reconciles MCP 16732–16736 and clarifications 16756, 16763 and 16773. The prior 29 fixes and checklist states are retained; this reconciliation does not claim new review coverage or completed implementation.
> - **Source HEAD (second dispatch)**: `ccf4119ccf3c81f34477aba80e84a4a7a454cc1c`
> - **Historical source HEAD**: `b6dcaad70f93c2d385d30b31b148e83265d43874`
>
> Review counts and findings live in the handoff DB, not in this file. Canon citations are Canon v0.26.2 row IDs. Revision v4 decisions, seams and the canon key are in [Delegated choices and frozen seams (revision v4)](#delegated-choices-and-frozen-seams-revision-v4).

---

## FIRBENCH-1. FIR benchmark tool: paired embedder comparison and development loop

## Objective

Build the benchmark tool that guides in-house FIR development and selects the in-house pipeline: SFace-128 vs AuraFace-512 (same YuNet detector; each embedder uses its model-compatible five-point alignment, so the estimand is the model-compatible native pipeline, not an embedder-only contrast), with InsightFace buffalo_l as a judge-side reference only. The tool completes the unbuilt FIRDV-2 parts (S3 metric adapters, S3a stage attribution, S4 cluster views, S5 oracle arms) and the FIRDV-3 S2 controlled checkpoint comparison, inside `scripts/eval_harness/`. It is not a new platform (FIRDV-2: "do not build another generic benchmark platform").

**This wave is benchmark tooling only.** No training, no detector replacement, no deployment, no labelling execution, no confirmatory claim.

## Problem Statement

- The model choice is undecided. Current evidence (30 probes, 17 identities) cannot pick a winner, and M-11 (+0.012 hard-face margin) has no artifact, predates CVUP-1 (OpenCV 5) and is rank-only.
- FIRDV-2 is marked done but only S1 (`experiment_manifest.py`, `outcome_ledger.py`) and the S3a strict detection scorer (`face_metrics.detection_pr_strict`) landed. Nothing composes detect → align → embed → search → accept for three legs on one frame with a fixed non-mated denominator, frozen thresholds, paired intervals and a sealed decision.
- The QA report (`benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html`, v5–v8) and the 2026-09-19 assessments already set most rules. The tool has to enforce them, not restate them.

## Constraints

- All execution on the VM. No local inference, no local lanes (8 GB laptop).
- Pseudonymized IDs only. Real-name alias maps (`benchmarks/private/priv1-*`) never leave the laptop and never enter a lane brief, artifact or report.
- Retain legitimate source provenance: pinned model/input manifests and hashes, source revision, preprocessing/runtime identity, annotation provenance and rule IDs remain required. Alias-map privacy does not waive lineage requirements; exported evidence uses pseudonymous IDs and excludes alias mappings.
- Image-bearing outputs (crops, overlays, label-queue HTML, notebooks) go to ignored `benchmarks/private/`. `benchmarks/reports/*.html` is already ignored. Committed artifacts are code, schemas, synthetic fixtures, manifests without pixels, and this plan.
- InsightFace/buffalo_l: internal bench reference only, never user-facing, never training data.
- One embedding space per comparison: SFace-128, AuraFace-512 and InsightFace-512 vectors are never compared across legs (EMB-01). A preprocessing or runtime change invalidates the cache, and the OpenCV/ORT version is part of the leg identity; cross-version comparisons are refused (PROV-01).
- Greenfield: no data migrations. Legacy artifacts stay readable through explicit version adapters.

## Scope and binding parameters

Scope, operator Q&A answers (Golden-150, design changes, notebooks, clustering, D2/D3, occlusion, definitions) live in [FIRBENCH-1-scope.md](FIRBENCH-1-scope.md). Lane-ready briefs live in [firbench-1/](firbench-1/README.md).

Binding defaults the S0 decision manifest must carry (values live in the manifest, never in code [rg-009, repository rule]):

| Parameter | Value |
| --- | --- |
| Primary estimand | paired ΔFNIR (SFace − AuraFace) at FPIR 0.01, end to end, fixed non-mated source-unit denominator |
| Secondary points | FPIR 0.05 and 0.001, each "unresolvable" until n_nonmated_eff ≥ 3/FPIR |
| Primary resolvability | The primary FPIR point is unresolvable until n_nonmated_eff ≥ 3/FPIR (300 at 0.01). An unresolvable primary point makes the verdict `inconclusive` (`primary_fpir_unresolvable`), with no winner named. |
| Interval | paired cluster percentile bootstrap, PSU = image–identity component. Two-sided 95% for step 1 (H1) and two-sided 90% for step 2 (H2), from one-sided levels 0.025 and 0.05 |
| Family α | 0.05 one-sided, fixed-order Holm: H1 (AuraFace superior to SFace) first; H2 (the in-house leg named in the sealed manifest non-inferior to InsightFace, δ = 0.05) only if H1 is rejected. Decisions use intervals only; no p-values. |
| Hypothesis margins | Original `hypotheses[].margin`: H1 superiority = 0 (95% paired lower bound > 0); H2 non-inferiority = 0.05 (90% paired upper bound < 0.05). Planted/sizing Δ = 0.10 and computed MDE are distinct; no new minimum-effect field. |
| Guardrails | Veto: per-cohort FPIR, false names per 1k mentions, worst pair-cell FNIR floor, p95 ms/face. Report-only until wired: cost per accepted description. Each role is sealed in the manifest. A null or unscored veto gives `inconclusive` (`required_guardrail_unscored`). |
| Threshold τ | identity-disjoint calibration folds, pooled, frozen before any test read. τ is the smallest threshold whose pooled calibration FPI (a count of non-mated source units with a false accept) is ≤ ⌊fpir_target × N⌋, N being the pooled calibration source-unit count (S3 Build 3). |
| Cluster cut | production similarity threshold `s` recorded in the run manifest; dendrogram cut at cosine distance d = 1 − s. τ appears only as a reference line at d = 1 − τ, labelled acceptance τ, never as a cluster cut (S4 Build 5). |
| Verdict states | superior · non-inferior · inconclusive · guardrail-vetoed · unratified |
| Global eligibility floor | `DecisionManifest.min_n_independent = 50` independent PSUs per frame, checked before FPIR eligibility and intervals (`InconclusiveReason.insufficient_independent_psus`). A declared project floor, not evidence of adequate power. |
| Pair-cell floor | `cell_floor_n_independent = 30` independent PSUs per query × enrolled cell (below it: "not scored"). Separate from the global floor. |
| Design discordance | `p_d = 0.15`, a design assumption, not observed. S3 imports it from the manifest; there is no implicit or global default. |
| Power | 0.80 (`z_β = 0.8416`), a design assumption for sizing only. |
| Planning ICC | `planning_icc = 0.10`, a declared design assumption, not an observed ICC. Reported with sensitivity 0.05 and 0.20. The observed ICC is measured by S1 and shown beside the assumption. |
| Fold protocol | k = 5 identity- and PSU-disjoint rotating folds; seed 2406466110 |
| Gallery split | seed 2468935812 |
| Interval resampling | paired cluster percentile bootstrap, `n_boot = 10000`, seed 2429382368 |
| Label queue | seed 336880394; QC values in [Delegated choices](#delegated-choices-and-frozen-seams-revision-v4) |

Seeds are the first 32 bits, big-endian, of SHA-256 of `FIRBENCH-1/v1/{folds,gallery,bootstrap,label_queue}`, declared before outcomes. Revision v4 re-derived all four and they match the values above.

## Delegated choices and frozen seams (revision v4)

Source: MCP decisions 16732–16736, explicit frozen-input clarification 16756 (`p_d`, `build_nonmated_pool`, runtime binding), grounded annotation contract 16763 and timestamp/receipt clarification 16773. These are reversible project policies chosen under the canon-first delegation (MCP 16732). They are declared policy, not values the canon prescribes. AE-2 to AE-4 validate the numeric choices on simulated data before any real-data gate uses them. Nothing in this section is a human observation, a real hash, or a ratification.

Second-dispatch adjudication: S0 Build 2 preserves H1 margin 0 and H2 margin 0.05; the exact CARD-27 supplement requires pre-sealing margins and sizing from n_eff, not a new Δ = 0.10 minimum-effect field. Accepted W2 inventory §§4–5 supports only conditional image-proxy arithmetic and leaves admissible non-mated counts unresolved without exhaustive GT. The supplied S0 implementation (`s0.delta.bundle`, head `4d17a6315428042e464ec59a02fc29f6440a6962`) confirms the `consumed_at` keyword and `UnsealToken` return below. MCP 16773 supersedes the older requirement that seal and ratification timestamps agree. These findings are upheld; AE-1 through AE-12 remain required. The supplied source SHA is provenance; this history-stripped checkout began at `4d793be5b6c68ef3f3a27a6a67f108227db4add2`, with the original returned artifact already present.

**Protocol and eligibility**

- Folds: k = 5 identity- and PSU-disjoint rotating folds. Threshold τ is selected on identity-disjoint calibration folds and frozen before the test read ([CAL-07], [EXP-22], [EVAL-07]).
- Floors: ≥ 50 independent PSUs per frame (global) and ≥ 30 per pair cell are necessary, not sufficient. Adequacy still requires the effective-power/MDE check, FPIR resolvability (≥ 3/FPIR non-mated source units) and exhaustive GT. Floors alone prove no adequacy ([EXP-12]).
- N is the independent PSU, never the image or face count ([EXP-23], [AUDIT-11]).

**Design assumptions versus estimates**

- Planning ICC 0.10 is a design assumption. Sensitivity points 0.05 and 0.20 are reported alongside it. No ICC is estimated until S1 measures PSUs on the pinned frame; the measured value is shown beside the assumption and never substituted for it ([AUDIT-11]).
- `p_d = 0.15` and power 0.80 are sizing assumptions ([EXP-12]).
- Accepted W2 inventory measures named-face M̃ = 24.401 over 584 named boxes versus image-count M̃ = 18.192. Conditional image-proxy deff/n_eff/MDE arithmetic establishes no current real face-level power. Neither quantity establishes the non-mated source-unit PSU structure. W2 found no raw provenance for the historical 207 probes; admissible non-mated N, n_eff and resolvability remain unknown without exhaustive GT. S1 measures these on the pinned exhaustive frame.
- Seal H1 superiority margin 0 and H2 non-inferiority margin 0.05, the paired interval class, harm directions and α allocation ([EXP-12], CARD-27). Δ = 0.10 remains the sizing/planted alternative, and MDE is computed; neither adds a minimum-effect field or changes the hypotheses.

**Label QC** (pre-data project policy; not source-established accuracy guarantees)

- Queue `gold_share` 0.10 and `repeat_fraction` 0.10. Gold mixes random, batch-matched and hard items, authored independently by SMEs as non-caption answers ([HITL-03]).
- Per-field repeat percent agreement ≥ 0.90; per-field Cohen's kappa ≥ 0.80; per-annotator independent-gold accuracy ≥ 0.90. These are not an α ≈ 0.8 equivalence ([HITL-05]).
- Support: ≥ 20 known-answer gold decisions per annotator (`min_gold_decisions_per_annotator = 20`) and ≥ 20 repeat decisions per evaluated field (`min_repeat_decisions_per_field = 20`), across the declared annotation run. A small batch exports but cannot import before support accrues ([HITL-03]).
- Below-floor, uncertain, eval-critical or undefined-kappa fields route to SME adjudication or repair ([HITL-07], [HITL-05]). Workers are never deleted to chase agreement. Pre-adjudication labels are kept ([MLDATA-03]).

**Units and annotations**

- One background source unit per exhaustive frame image, plus independently verified non-mated GT-face units. A duplicate detection that overlaps an already represented GT face creates no unit; its extra names count only as spurious names. Detector alarms never add to the FPIR denominator ([EVAL-19], [EVAL-18]; CARD-11 measurement-integrity, by ID in the release manifest).
- Required real-eval annotations: stable image and face IDs and hashes; valid GT boxes; explicit named / unknown / unresolved identity status (an unresolved identity never enters the non-mated pool); annotation tier and exhaustiveness; provenance and rule IDs ([PROV-01]); face-specific occluder set and eye/nose/mouth visibility; duplicate, session and synthetic-sibling metadata when known; sampling arm and inclusion probability; and, for tier (a), a valid QC result and an observation reference. Unknown metadata stays explicit.
- MCP 16763 producer contract: persisted `GoldenManifest` is document-homogeneous and `GoldenEntry` forbids `annotation_mode`. Only flattened raw score mappings receive parent stamps (`report._resolve_score_annotation_mode`, `manifest._reject_per_entry_annotation_mode`). Mixed/missing/empty entries fail closed; an explicit exhaustive request cannot upgrade `roster_only`. S1 and S3 preserve this contract.
- Measurement evidence gate: before real tier-(a) labels feed analysis, a bounded contextual observation of the production process is recorded, with exceptions, scope and limits ([MEAS-29]). Tooling and fixtures may proceed without it. No observation is invented here.

**Timestamps and receipts**

- Semantic `created_at` selects `seal.sealed_at`, else `ratification.ratified_at`, else an explicit `--created-at` (CLI) or `run_frame(created_at=...)` ISO 8601 literal. Seal and ratification describe different events and may differ. Only a supplied explicit literal must match the highest-priority derived value, comparing parsed instants. Missing/invalid values or a conflicting explicit literal raise existing `FrameContractError` (MCP 16773); do not introduce `RunTimestampError`. Semantic writers never read the wall clock. Implementation tests supply fixed literals ([FLOW-18], [PROV-01]).
- `timings.json` and actual attempt/private unseal-ledger consumption receipts are non-replayable and separate from deterministic manifests, ledgers and searches. `scores.json` carries the timings receipt's sha256 and the p95 veto state, and the report may display receipt-derived timing values, so their byte replay requires the same pinned receipt (MCP 16777; AE-7). The receipt is reconciled, never regenerated on replay ([FLOW-18]). Pass `consumed_at` explicitly from an allowed nonsemantic attempt-receipt boundary; an old seal date is not actual consumption time. Static clock scans target semantic writers with explicit receipt-boundary exceptions; they do not ban harmless set operations, seeded RNG or receipt timing globally (MCP 16773; [FLOW-18]).

**Frozen S0 seams** (fixed before consumers; these supersede older signatures only at the seams listed)

- `DecisionManifest` requires `p_d=0.15` (MCP 16756), `min_n_independent=50` and `cell_floor_n_independent=30`, with the planning ICC, fold, gallery, bootstrap and label-queue fields above. S3 imports `p_d` with no implicit/global default.
- `InconclusiveReason.insufficient_independent_psus`, checked before FPIR eligibility and intervals.
- Private queue QC adds `min_gold_decisions_per_annotator=20` and `min_repeat_decisions_per_field=20`.
- `run_frame(..., created_at: str | None = None)`; CLI `--created-at` takes an ISO 8601 literal.
- `build_nonmated_pool(faces: Sequence[GtFace], images: Sequence[ImageUnit], folds: Mapping[str, int], *, fold: int, component_map: Mapping[str, str], exhaustive: bool, planning_icc: float) -> NonMatedPool` (MCP 16756). It raises existing `FrameContractError` for `exhaustive=False` and malformed component or fold coverage. It cannot recover PSU IDs from the old `faces`, `images` and `folds` inputs alone. Source units stay detector-independent.
- Actual frozen helper: `require_frame_read_allowed(frame: FrameSpec, token: UnsealToken | None, *, decision_sha256: str, run_id: str, code_sha: str, scorer_sha: str, repo_root: Path, consumed_at: str) -> UnsealToken`. Runtime context is explicit, never globals or token-to-itself comparisons. `consumed_at` is the actual nonsemantic attempt-receipt timestamp; the helper returns the consumed token and appends it to the private ledger. Missing/spent/mismatched tokens and failed spending/recording raise `SealedFrameReadError`; malformed `consumed_at` or an open frame passed to this sealed-read helper raises `FrameContractError`. Per-frame `O_EXCL` spending, exact binding, first and second reads, and concurrent-read tests are retained (MCP 16756, 16773).

**UI policy (W2 ux-map and L1 label queue)**

- Keep the supported MapState enums with bench semantics in purpose and zones. Add no enum values ([INT-21]).
- Every interactive object specifies its default, activated and updated states ([INT-21]).
- Result display: show the evidence path, meaning the data shown, the comparison basis, the interval and n_eff ([VIZ-23]), and explain the result from the state it produces ([INT-22]). WRIT-81 applicability remains conditional until actual executive-summary prose is rendered and inspected: if that prose asserts a decision with an unconditional assurance that contradicts a decision-changing uncertainty or untested condition in the supporting analysis, retain the qualification. The structured verdict label alone does not establish that prose trigger.
- Image-selection pool (S5 failures): overall and selected pool counts, the selection rule and pseudonymous IDs ([VIZ-41]).
- L1 queue: one draw mode (`a`, add missed face) ([INT-23]). The next item opens only on operator Enter, with no auto-advance deadline; Esc undoes; export keeps recoverable work and offers a repair path on error ([INT-24], [FORM-11]). Queue, export, import and report handoffs are mapped ([INT-25]).
- Static exit markers need no fabricated loading screen. [RLSE-04] (practice label, *bootstrap*) asks for designed loading, empty, error and offline states on a screen with states. A static exit marker has no load, fetch or content state in the artifact, so its trigger does not fire. This is the adjudicated exemption. Any other screen stays subject to RLSE-04.

**Canon key (Canon v0.26.2)**

Rule names are the bold text at the start of each Rule cell. Source locators are as each Source cell prints them. This key covers the rows cited in revision v4, in this plan and in the scope. Cards are cited by ID and slug from the release manifest (`card_ids`); the pinned mirror has partial card coverage. The exact CARD-27 body was read from the supplied sibling `canon-supplement/margin-and-design-effect-before-the-run.md`. It supports pre-sealed margins and design-effect sizing, and prescribes no project-specific numeric margin or extra manifest field.

| ID | Rule | Source (as printed) | Used for |
| --- | --- | --- | --- |
| CAL-07 | Select face thresholds on identity-disjoint folds | Video-to-Video Face Recognition for Low-Quality Surveillance Data, ch. 6 | k = 5 folds; τ on calibration folds |
| EXP-22 | No circular analysis (double-dipping) | Statistics Done Wrong, ch. 6 | Protocol and seeds before outcomes; τ frozen before test |
| EVAL-07 | Validation-only selection | Designing Machine Learning Systems | Test read once |
| EXP-12 | Power and practical significance | Trustworthy Online Controlled Experiments, ch. 2 | Declared effect, p_d, power, MDE; floors ≠ adequacy |
| EXP-23 | Pseudoreplication check | Statistics Done Wrong, ch. 3 | N = independent PSUs |
| EXP-19 | Significance of the difference | Statistics Done Wrong, ch. 5 | A − B tested by contrast, not chained |
| EXP-10 | Primary metric and multiplicity | Trustworthy Online Controlled Experiments, ch. 3 | Primary point and α split |
| EXP-13 | A/A before A/B | Trustworthy Online Controlled Experiments, ch. 19 | AE-2 null; AE-5 deliberate canary |
| AUDIT-11 | Account for cluster design effect | Sampling: Design and Analysis, ch. 5 | Planning ICC, deff, n_eff, sensitivity |
| EVAL-18 | Non-mated probes and a score threshold, not rank | IARPA Janus Benchmark-C, § 2.3.4 | Non-mated denominator |
| EVAL-19 | Do not let detector alarms dilute FPIR | IARPA Janus Benchmark-C, § 2.3.4 | Source-unit denominator |
| EVAL-16 | Upstream failure counts against the end-to-end metric | IARPA Janus Benchmark-C, § 2.3.4 | End-to-end FNIR |
| EVAL-20 | The slice is a cell of the pair, not a stratum of one side | Handbook of Face Recognition (3rd ed.), ch. 11 + A novel Facial Recognition technique with Focusing on Masked Faces | Pair cells and cell floor |
| HITL-03 | Gold-embedded annotator QC | Human-in-the-Loop ML | Gold share, support, gold accuracy |
| HITL-05 | Agreement is a diagnostic, not the truth | Human-in-the-Loop ML | Percent agreement and kappa floors |
| HITL-07 | SME adjudication escalation | Human-in-the-Loop ML | Routing to SME |
| MLDATA-03 | Resolve label multiplicity in writing | Designing Machine Learning Systems | Pre-adjudication labels kept |
| MEAS-29 | Observe measurement production | Seeing with Fresh Eyes: Meaning, Space, Data, Truth, ch. 4 | Observation evidence gate |
| FLOW-18 | Make report recomputation deterministic or mark it non-replayable | Designing Data-Intensive Applications, ch. 10 | `created_at` seam; timings receipt pinned by sha256 for scores and report replay (AE-7) |
| PROV-01 | Every output walks back to its evidence | Model Cards + AI Engineering | Leg identity, cache keys, provenance fields |
| EMB-01 | One embedding space per comparison | Foundations of Vector Retrieval, ch. 1 | Cross-space refusal |
| VIZ-23 | Show the evidence path | Richard Feynman's Mental Models, ch. 5 + Envisioning Information, ch. 4 | Result display |
| VIZ-41 | Reveal the image-selection pool | Visual Explanations, ch. 1 | S5 pool accounting |
| INT-21 | Specify interaction states | Microinteractions, ch. 3 | States of each interactive object |
| INT-22 | Explain the result | Microinteractions, ch. 4 | Result explanation |
| INT-23 | Limit and mark modes | Microinteractions, ch. 5 | One draw mode |
| INT-24 | Specify loop exits | Microinteractions, ch. 5 | Queue exits, no auto-advance |
| INT-25 | Map the handoffs | Microinteractions, ch. 6 | Queue, export, import, report |
| FORM-11 | Constrain before error | Microinteractions, ch. 3 | Preserve work; repair path |
| WRIT-81 | Keep decision-changing limits in summary prose | tufte-beautiful-evidence § cognitive-style-of-powerpoint | Conditional until render review: actual executive-summary prose contradicts supporting decision-changing limits |
| RLSE-04 | Undesigned state is a bug | bootstrap (practice label) | Static exit marker exemption |
| HAI-11 | Interface-mode trade-off | Human-in-the-Loop ML | Edit path for missed faces |

**Repository rules** (not canon rows): `rg-008`, `rg-009`, `sr-006`, `sr-007`, as used in the lane briefs, are defined in [docs/workbay/constitution.md](../../workbay/constitution.md).

## Current State Analysis (verified 2026-10-14, codemap + `wc -l`)

| Seam | Path | Reuse |
| --- | --- | --- |
| Run identity, expected-unit ledger | `eval_harness/experiment_manifest.py` (221), `outcome_ledger.py` (58) | Every bench run is one manifest. Every GT face ends in a ledger state. |
| Open-set primitives | `open_set_identification.fnir_fpi_at_threshold` (194 lines) | Curve and operating-point core |
| Gallery/probe split | `gallery_split.py` (511) | Identity-disjoint gallery and non-mated source-unit inventory |
| Threshold calibration | `calibrate_face_thresholds.py` (1,322) | Subject-disjoint K-fold |
| Strict detection | `face_metrics.detection_pr_strict` | One-to-one IoU matching, exhaustive-provenance guard |
| Bake-off composition | `fir_bakeoff_run.py` (1,010), `face_bakeoff.py`, `fir_search_adapter.py`, `landmark_cache.py` | Inject per-leg search results |
| Sampling | `audit_sampling.py` (825), `pilot_draw.py` (450), `strata.py` (1,079) | Arms, inclusion probabilities, strata |
| Gate contract | `gate_contract.py`, `benchmarks/manifests/fir-gate-contract-v1.json` (ratification fields null) | D3 point and T-14 thresholds |
| Union adjudication | `union_adjudication.py` (384) | T-14 bound and bootstrap UCL |
| Synthetic occlusion | `synthetic_occlusion.py` (800) | Separate robustness arm, inherits parent PSU |
| Paired stats | `scripts/bench/score_report.py` (`holm_bonferroni`, paired bootstrap) | `holm_bonferroni` is not called by the verdict; the image-level bootstrap is not used for verdicts. The PSU resampling pattern is reused. |
| Legs | `recognition/infrastructure/embeddings/face_pipeline_adapter.py` (SFace and AuraFace profiles, runtime fingerprint in model id), `eval_harness/buffalo_bench.py` | In-process legs |
| Existing annotator | `benchmarks/tools/golden150-box-annotator.html` (local, ignored, 1.9 MB) | Pattern for the label queue |
| Populations | `benchmarks/private/fir-capacity-20260919/fir-occ-population-review-draft-20260919.{csv,json}` | Queue membership and probabilities |

## Target Outcome

`make fir-bench-run FRAME=<id> LEGS=sface,auraface,insightface` on the VM produces an immutable run (manifest, ledger, per-leg caches). `fir-bench-score` produces the frozen-τ scores. `fir-bench-report` writes a private static HTML (screens below) plus JSON/CSV. `fir-bench-compare A B` gives paired deltas, or refuses when the runs are incompatible. `fir-bench-unseal --decision <id>` refuses unless the decision manifest is sealed and ratified and the frame has no unseal token.

## Proposed Solution: modules (inside `scripts/eval_harness/`, 1–3 files per lane)

| Slice | New file(s) | Job |
| --- | --- | --- |
| S0 contract | `firbench_contract.py`, `benchmarks/manifests/fir-bench-decision-v1.json`, interchange schemas and fixtures | Decision-manifest schema: estimand, δ, α split, interval method, guardrails, harm direction, disconfirmers and their dates, seal hash, planning ICC, fold protocol, gallery lineage. Frame registry with admissibility. Null means unratified. Frame-read tokens live in a local-only unseal ledger; a sealed frame is read once per token. Unseal refusal. Shared enums (`SearchStage`, `IdentityStatus`, `SamplingArm`, `FoldRole`, `AlignmentMode`), versioned `frame-v1`, `face-search-record-v1`, `scores-v1`, `clusters-v1`, `comparison-v1` schemas, and the entry-point signatures fixed before batch B. |
| S1 frames | `firbench_frames.py` | Load population queues. Build PSU components (union-find over image–identity, duplicate, session and synthetic-sibling edges), then identity-disjoint folds over whole components. Build the immutable non-mated source-unit inventory (non-mated GT faces plus one background unit per frame image; never detector-derived). Estimate deff and n_eff, emit admissibility. |
| S2 legs | `firbench_legs.py` | In-process legs `sface` and `auraface` built from pinned manifests by an offline factory (not the shared runtime), and `insightface` (judge, fused: no separate alignment stage). Arms `native`, `gt_crop_redetect` (GT box crop re-detection) and `cached_yunet_landmark_replay` (cached YuNet landmarks; no human landmarks exist). Attribution arms apply to `sface` and `auraface` only. Per-leg cache keyed by the model-manifest fingerprint (weights sha, preprocessing, OpenCV/ORT). Raw detections are kept, and ledger rows are written per GT face. |
| S3 score | `firbench_score.py` | FNIR-vs-FPIR curves on the fixed non-mated source-unit denominator, calibration-fold τ (smallest feasible on the pooled calibration pool of source units; calibration-leak refusal), paired PSU cluster intervals, fixed-order step decision on intervals only, primary-FPIR and MDE eligibility, pair cells, stage waterfall, guardrails (veto or report-only), versioned boundary semantics |
| S4 clusters | `firbench_clusters.py` | Cluster metrics, mutual-kNN, pure-numpy reference threshold clustering (`reference_threshold_cluster`), dendrogram cut at the production threshold s with τ as a reference line, PCA spectra, UMAP diagnostic coordinates and companions. The production loader `prepare_cluster_caches` is DB-coupled and is not called. |
| S5 report | `firbench_report.py` | Static HTML (light/dark, no network, keyboard accessible, glyph plus colour) plus JSON/CSV, with a private-path guard |
| S6a CLI | `firbench_cli.py`, `mk/evals.mk` | `run` and `score` (batch B, needed by the AE-12 tracer) |
| S6b CLI | same files, after S6a merges | `report`, `compare`, `unseal` |
| S7 label queue | `benchmarks/tools/fir_occ_label_queue.py` (allowlisted), `eval_harness/fir_occ_labels.py` | Generate the private single-file HTML queue. Import and validate exports into the fir-occ-v1 face-instance schema. Union-delta mode for T-14. |
| W2 ux-map | `benchmarks/ux-maps/fir-bench.uxmap.json`, `fir-bench.md` (rendered by the coordinator's canvas CLI; the `.gitignore` allowlist line already exists) | Screen/zone/state/flow inventory, rendered with `ux-map render --path benchmarks/ux-maps/fir-bench.uxmap.json --format markdown`, then critique |
| S9 acceptance | `firbench_selftest.py`, `mk/evals.mk` target `fir-bench-acceptance` | Seeded clustered simulator (PSU sizes, ICC, per-leg error rates, planted effects by cell and stage), A/A and planted-effect Monte Carlo, determinism and replay checks. Runs the completion evals below. |

Tests: `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_*.py`, synthetic vectors and identifiers only.

## Screens (ux-map seeds; values are placeholders)

```
S1 VERDICT ─ run r-0007 · frame fir-occ-v1/dev [development] · OpenCV 5.0.0 · ORT 1.28 · git a1b2c3d
 Question  AuraFace-512 vs SFace-128 · FNIR @ FPIR 0.01 · end-to-end (misses count)
 Answer    Δ(SF−AF) +#.### [−#.###, +#.###] paired · PSU image–identity · n_eff ### (deff #.##)
           → INCONCLUSIVE: interval spans 0 · H2 not evaluated
 Admissible as: development evidence — frame inspected before; not confirmatory
                                   FNIR@FPIR.01   FPIR measured [UCL]   τ (calib folds)
   sface-128           ├────●────┤     #.###      #.### [#.###]         #.## frozen
   auraface-512      ├────●────┤       #.###      #.### [#.###]         #.## frozen
   insightface (judge)   ├──●──┤       #.###      #.### [#.###]         #.## frozen
 Guardrails (veto)          SF128  AF512  rule
   false names /1k mentions  #.#    #.#   ≤ sealed           ✓
   worst pair cell FNIR      #.##   #.##  floor              ✗ clear→mask
   worst cohort FPIR         #.###  #.### ≤ sealed           ○ unresolvable (n<300)
   p95 ms/face               ##     ##    ≤ budget           ✓
 [Curves] [Pair cells] [Stages] [Failures] [Clusters] [Compare] [Frames & power]   (NAV-06)
```

```
S2 OPERATING CURVES ─ FNIR vs FPIR (log) · τ frozen on calibration folds · test read once
 FNIR                                         ░ = FPIR below 3/n_nonmated_eff (unresolvable)
  .40┤╲ SF128
     │ ╲__ AF512
  .20┤░░░╲___ IF
     │░░░░░░●── τ point (FPIR .01)
     └┬─────┬─────┬── FPIR
     .001  .01   .05      non-mated source units ### · gallery ### identities
 At τ: SF FNIR #.### FPI # / ### · AF #.### FPI # / ### · IF #.### FPI # / ###   (INT-22)
 [explore τ] dev frames only, writes nothing, sealed frames read-only        (INT-23, VIZ-37)
```

```
S3 PAIR CELLS ─ query × enrolled · FNIR@τ per leg · faces/identities/PSUs per cell
 probe ↓ / gallery →   clear                 mask              sunglasses
 clear                 SF .## AF .## n###/##   SF .## AF .## n##  …
 mask                  SF .## AF .## n##/#     ○ no data → collect  …
 sunglasses            …                       …                 …
 mixed                 ○ no data → collect
 Real and synthetic in separate panes · n<30 independent = "not scored"      (EVAL-20, CARD-32)
 cell → S5 Failures(cell × leg)                                               (INT-25)
```

```
S4 STAGES ─ where each GT face ended (end-to-end ledger)        SF128   AF512
 GT faces (exhaustive frame only)                                ###     ###
  └ detected (IoU≥.50, one-to-one)                               ###     ###   same YuNet
     └ aligned (5-pt usable)                                     ###     ###
        └ top-1 correct identity                                 ###     ###
           └ accepted at τ (correct name)                        ###     ###
 Joint gaps vs native (paired PSU CI)   gt_crop_redetect  −#.### [−#.###, −#.###]   cached_yunet_landmark_replay  −#.### [−#.###, −#.###]
 → unavailable faces: gt_crop_redetect #  ·  cached_yunet_landmark_replay #  ·  no shares apportioned (joint intervention gaps, not causal)
```

```
S5 FAILURES ─ clear→mask × sface-128 · ## errors · pool ### mated / ### non-mated   (VIZ-41)
 stage: missed # · unaligned # · wrong-name # · rejected-mated # · false-accept non-mated #
 [crop, private only] face f-0412 · pseudonym amber_falcon · gallery G1
   SF128 rejected  top1 quiet_heron .38 < τ .41
   AF512 correct   amber_falcon .57 · IF correct .61
 ← Pair cells (sort, scroll and filter kept)
```

```
S6 COMPARE ─ B "auraface preproc fix" d4e5f6 vs A baseline a1b2c3 · same frame, same faces
 compatibility: frame ✓ · scorer v2 ✓ · OpenCV 5.0.0 ✓ · leg contract changed: auraface (expected)
 metric               A      B      Δ [95% paired CI]     moved?
 AF FNIR@FPIR.01      #.###  #.###  −#.### [−#.###, −#.###]  ▼ better
 worst pair cell      …
 history AF FNIR  ▁▂▃▂▁ latest #.###                                        (VIZ-24)
 τ spread over 5 folds #.##–#.## → FNIR #.###–#.###                          (EXP-30)
 incompatible runs → refuse with reason, no subtraction
```

```
S7 CLUSTERS ─ per leg, own space only · s-cut (d = 1 − s) · noise policy: singletons stay unassigned
                  pair P/R     B³ P/R      merges  frags  unknown-absorbed  order-stab
   sface-128      .##/.##      .##/.##     ##      ##     ##                .##
   auraface-512   .##/.##      .##/.##     ##      ##     ##                .##
 Dendrogram (average, cosine) cut at s .## (d = 1 − s) · acceptance τ .41 line at d .59, not a cluster cut · cophenetic r .##
 PCA spectrum ▇▅▃▂▁… (variance only; retained components ##)
 UMAP — DIAGNOSTIC PROJECTION · n_neighbors 15 · min_dist .1 · seed 7 · distances not meaningful
 [table alternative] [select face → nearest neighbours in original space]     (VIZ-18/19)
```

```
S8 FRAMES & POWER ─ admissibility and what each frame can claim
 frame              units          ids  PSUs  deff  n_eff  admissible as   MDE(Δ)
 golden150-v1       150 img        ##   ##    #.##  ###    diagnostic      —  verification-biased
 fir-occ-v1/prob    120 img p=.204 ##   ##    #.##  ###    development     .##
 fir-occ-v1/chal    106 img        ##   ##    #.##  ###    development     cells only
 confirm-v1         not acquired   —    —     —     —      confirmatory    needs ≥### PSUs
 Decision manifest fir-bench-decision-v1: SEALED 2026-10-## · sha ####### · disconfirmers 3 dated
```

```
L1 OCCLUSION LABEL QUEUE (private single-file HTML) ─ item 37/150
 [full image, no detector boxes, no caption shown]
 face 1  box ✓  occluder: [m]ask [s]unglasses [h]and [o]bject [x]mixed [n]one [?]can't tell
         regions: eyes ○ nose ○ mouth ○ (v cycles visible/occluded/out-of-frame/uncertain)
 [a] add missed face · [u] unknown person · [Enter] next · [Esc] undo · export JSON
 rule face-label-rule/v1 (T-09) · 37 done · 0 skipped (skips recorded as nonresponse)
```

**Canon checks.**

- **Tufte:**
  - evidence path (VIZ-23)
  - range frame (VIZ-35)
  - no content-empty decoration (VIZ-27)
  - direct labels (VIZ-40)
  - tables for exact lookup (VIZ-32)
  - sparkline history (VIZ-24)
  - selection pool (VIZ-41)
  - aggregation sensitivity (EXP-31)
- **Saffer:**
  - specify states (INT-21)
  - explain the result (INT-22)
  - limit and mark modes (INT-23)
  - loop exits (INT-24)
  - handoffs (INT-25)
  - least useful feedback (PERC-10)
  - constrain before error (FORM-11)
- **Projection:** VIZ-18 and VIZ-19.
- **Colour:** every colour state is paired with a glyph (✓ ✗ ○ ▼).

## Verification Strategy

- Per-lane VM test command: `env -u ACX_EVAL_BENCH uv run --exact --directory apps/prototype-description-service --locked --extra dev pytest scene/tests/test_eval_harness_firbench_<slice>.py -q`. This is the future implementation-lane command; this documentation-only dispatch adds and runs no tests.
- Every slice starts RED: tests committed and failing for the stated reason before any implementation.
- `make lint-task-plans` passes. The canvas CLI renders `fir-bench` (`ux-map render`), and the coordinator critique has no high findings.

## Open questions

Revision v4 closes the operator-choice items that v2 listed. MCP 16732–16736 decided them as declared project policy, validated by AE-2 to AE-4 before real-data gating (see [Delegated choices](#delegated-choices-and-frozen-seams-revision-v4)):

- Minimum independent PSUs before H1 or H2 can reject: 50 per frame (global), with 30 per pair cell. Below the global floor the verdict is `insufficient_independent_psus` (S3 Build 6, eligibility).
- Annotations a frame must carry before a verdict is eligible: the required list in Delegated choices.
- A duplicate detection that overlaps an already represented GT face (not its one-to-one match) opens no additional source unit. Its extra names count only as spurious names (S3 Build 2).
- Manifest values before seal: `fold_protocol` (k = 5, seed 2406466110), `gallery_lineage.split_seed` (2468935812), `interval.n_boot` (10000) and `interval.seed` (2429382368) are delegated values. The committed manifest still carries null until S0 writes them, and seal keeps refusing null (S0 Build 2).
- `planning_icc` = 0.10 is a declared design assumption with sensitivity 0.05 and 0.20. It is not an observed value.
- Queue QC values: gold share 0.10, repeat fraction 0.10, percent-agreement floor 0.90, kappa floor 0.80, gold-accuracy floor 0.90, support 20 gold and 20 repeat decisions. The queue `qc` block takes these values, and the importer keeps refusing null (S7 Build 1 and 2).

Evidence gates. These are not operator-choice loops. They stay unresolved until the evidence exists:

- Real frame and template hashes: unresolved until S1 measures the pinned frames on the VM. The plan carries no hash values, and sealing refuses absent inputs.
- Observed ICC: unresolved until S1 measures PSUs on the pinned frame. The planning value 0.10 remains a design assumption until then.
- Measurement observation for real tier-(a) labels (MEAS-29): unresolved. A bounded contextual observation record is required before real tier-(a) labels feed analysis. Tooling and fixtures may proceed without it. None is invented here.
- Policy validation: the floors, folds, bootstrap and QC values are checked by AE-2 to AE-4 on simulated data before any real gate uses them.

## Completion evals (definition of done for the tool)

The tool is done when it is trustworthy, not when it has picked a model. A benchmark that has never been shown to detect a known effect, or to stay quiet on a null, cannot guide development (EXP-13). Each eval below runs on the VM at the merge-candidate HEAD and is recorded as a `test_result` tied to that SHA. `make fir-bench-acceptance` runs all simulated and fixture evals; the real-data evals run through the CLI.

| ID | Eval | Pass rule | Canon |
| --- | --- | --- | --- |
| AE-1 | Known answers | Synthetic fixtures with analytic FNIR, FPIR, FPI, B-cubed and ledger counts match. Counts (FPI, ledger states, pair-cell and stage counts, B-cubed counts) compare as exact integers. Analytic rates are checked against `fractions.Fraction` oracles with float tolerance 1e-12. | EVAL-18 |
| AE-2 | A/A null (simulated Type-I behaviour) | Simulated only: 2,000 seeded null replicates at the planning ICC 0.10, reported alongside the 0.05 and 0.20 sensitivity points. Scenario parameters: face-count size-weighted PSU size ≈ 13 and n_eff ≈ 300. The report's M̃ = 12.925 does not reproduce from the tracked manifest, so these are scenario values, not measured frame properties. Step 1: the full decision procedure says "superior" in ≤ 0.032 of replicates (nominal one-sided 0.025 + 2 MC SE, SE = 0.00349). Step 2: at the boundary Δ = δ, with H1 forced to pass, step 2 rejects in ≤ 0.060 of replicates (nominal 0.05 + 2 MC SE, SE = 0.00487). | EXP-13 |
| AE-3 | Interval coverage | In 2,000 planted-effect replicates the 95% paired cluster interval covers the true Δ in 93–97% of replicates. The report also shows the image-level bootstrap's coverage on the same replicates, so the PSU correction is visible. | AUDIT-11, EXP-23 |
| AE-4 | Planted-effect sensitivity | A planted ΔFNIR 0.10 at n_eff 115 (the step-1 requirement for Δ 0.10) is detected by H1 in ≥ 0.77 of 2,000 replicates (0.80 power minus 3 SE; SE = 0.0089). An effect planted only in the clear→mask cell appears in that cell and not in clear→clear. A planted 10% detection drop appears in the "missed" stage count, and the wrong-identity rate among embedded faces changes by at most 0.05 (absolute) between planted and control runs. | EXP-12, EVAL-16 |
| AE-5 | Real-data canary | On the Golden-150 diagnostic frame, using the 54-entry draft roster (`golden150-draft-20260723.json`, not the 17-identity evidence set) as the gallery, a canary copy of the AuraFace leg relabels a declared set of k = 5 identities (⌊0.10 × 54⌋) by seeded derangement. The run reports the measured FNIR and false-name effect with its paired CI; significance is not guaranteed. The RED pass runs on a powered synthetic fixture whose changed search ids and effect are precomputed, and the canary must detect that planted effect. Legs tagged canary are refused in sealed runs. | EXP-13 |
| AE-6 | Legacy parity | In `legacy_v1` boundary mode the bench reproduces the pinned historical counts exactly (the W2 inventory pins the artifacts, including `face_unknown_rejection` 204/207). The `v2` mode lists every item whose outcome changes. Historical 204/207 is report-level evidence; raw per-probe provenance is still needed to verify replay, and is not supplied by that report count. | CAL-02 |
| AE-7 | Determinism and replay | Two cold runs from pinned inputs (same frame, sealed decision, legs, seeds, resolved `created_at`, code SHA, and the same `--out` basename under different parents) give byte-identical `searches.jsonl` and per-recognition `ledger/` files. Seeds come from the manifest. Iteration is sorted. Each cold run writes its own `timings.json`, a fresh physical receipt that is non-replayable and excluded from this comparison. `scores.json` and the report are not compared byte-for-byte across cold runs, because they carry the receipt's `timings_sha256` and the p95 veto state, and the report may display receipt-derived timing values. Fresh cold-run timings are different assessment inputs and can change the actual p95 veto: `fail` gives `guardrail_vetoed` at S3 check-order step 3, and the stop rule then leaves H2 without a state. Full `scores.json` and report byte replay therefore requires the SAME PINNED receipt (MCP 16777). Re-running `score` or `report` on one run directory reads the same immutable receipt and must reproduce the same bytes. Cross-run checks use verification snapshots: a new directory holding byte copies of one run's semantic inputs plus exactly one receipt copied byte-for-byte as `timings.json`, with no copied `scores.json`, `clusters.json` or `report/`. Original run directories and receipts are never rewritten, and no test-only CLI flag is added. Two snapshots with the same receipt bytes must give byte-identical `scores.json` and report output, with the receipt sha, p95 state and veto fields compared as they are, never masked or stripped. Regression: a snapshot whose receipt differs only in p95 ms values must change the p95 guardrail's `timings_sha256`, and where the new value crosses the sealed p95 budget it must also change the p95 state and the verdict path. This uses a synthetic fixture decision with fixed literals and a synthetic p95 rule; the real budget stays unset until AE-12 preregisters it. Semantic `created_at` selects `seal.sealed_at`, else `ratification.ratified_at`, else an explicit `--created-at` or `run_frame(created_at=...)` literal. Seal and ratification may differ; only a supplied explicit literal must match the highest-priority derived value as a parsed instant. Missing/invalid values or conflicting explicit literals raise `FrameContractError` (MCP 16773). Semantic writers never read the wall clock; actual attempt/private consumption timestamps use separate non-replayable receipt boundaries. Implementation tests pass fixed literals. A warm-cache run gives identical searches, ledger and per-face outcomes to the cold run; its timings are a separate receipt, so its scores and report are compared only on a snapshot with the same receipt. Identical inputs run twice (cold runs, real data, one leg) give identical per-face outcomes and Δ = 0 on searches and ledger; the verdict is `inconclusive` unless the p95 state is `fail` (`guardrail_vetoed`). A changed p95 state is an assessment result, not a replay defect. | FLOW-18, PROV-01 |
| AE-8 | Cache invalidation | Changing weights sha, preprocessing parameters, OpenCV or ORT version gives a cache miss and a new leg id. Cross-version compare refuses. | PROV-01 |
| AE-9 | Refusal suite | Each refusal raises its named error and returns no numbers: cross-space compare, cross-runtime compare, sealed-frame read without an unspent token for that run, a second unseal of a frame under any decision sha, τ fit on a test fold (`CalibrationLeakError`), an undeclared compare field difference, unratified point used as a verdict, detector-dependent FPIR denominator, Ward/median/centroid linkage on cosine, projection coordinates feeding a metric (metrics byte-identical across projection parameters), image-bearing output outside `benchmarks/private/`; an H2 leg the manifest does not name (`UndeclaredH2LegError`); τ from an empty calibration pool (`TauInfeasibleError`). Also refused: `build_nonmated_pool` with `exhaustive=False` or malformed component or fold coverage (`FrameContractError`); `run_frame` with missing/invalid timestamp inputs or a conflicting explicit `created_at` (`FrameContractError`, MCP 16773); `require_frame_read_allowed` without its required keyword context (call-signature refusal), with a missing/spent/mismatched token or failed spending/recording (`SealedFrameReadError`), or with malformed `consumed_at` or an open frame (`FrameContractError`). No parallel shared error class is added. First/second and concurrent sealed-read checks retain exact binding, per-frame `O_EXCL` spending and the returned consumed `UnsealToken`. The verdict cases return `inconclusive` with the named reason and name no winner: a superior or non-inferior verdict attempted with n_nonmated_eff < 3/FPIR (`primary_fpir_unresolvable`); fewer than 50 independent PSUs on the frame (`insufficient_independent_psus`, checked before FPIR eligibility and intervals); a null or unscored veto guardrail (`required_guardrail_unscored`); `non_inferior` on a non-confirmatory frame (`non_confirmatory_frame`). | EMB-01, EVAL-07, VIZ-18 |
| AE-10 | Privacy | The branch diff contains no image bytes or data URIs and nothing under `benchmarks/private/`; the VM lane checks this. The coordinator runs a read-only static privacy scan on the laptop against the private alias map and records the hit count, scanned/run revision `code_sha`, scanner identity/digest and report digest. `code_sha` must match the scanned revision and the run revision; scanner/report content digests need not equal a git commit SHA. The alias map never leaves the laptop, and product tests and models stay on the VM. | Repository privacy rule (no canon row) |
| AE-11 | Report task eval | Given only the HTML, the operator (or a reviewer agent) answers six questions correctly within 5 minutes: which leg wins at the primary point and whether it is conclusive; the frame's admissibility; the worst pair cell; the dominant failure stage; whether FPIR 0.001 is resolvable; whether runs A and B are comparable. All screens work keyboard-only, in light and dark, with glyph plus colour, and with no network requests. | INT-22, VIZ-23, VIZ-32 |
| AE-12 | Early tracer and budget | After S0–S3 land, one three-leg run on a 20-image diagnostic subset completes on the VM with every GT face in exactly one ledger state, before S4–S6b start. Cold and warm times are recorded in `timings.json`. Before W5 budgets are set, a warm budget is preregistered from this measurement on the VM, and the warm rerun passes if it meets that budget. | PROD-31 |

AE-2 to AE-4 use the S9 simulator. Its generator parameters (ICC, PSU size distribution, per-leg error rates, planted effects) live in a committed fixture, and the same seeds reproduce the same table.

## Lane Decomposition (all remote; none on this host)

Lane-ready briefs: [firbench-1/README.md](firbench-1/README.md). Current implementation/grunt routing is remote `claude-haiku-5-5` xhigh. This gate-defect second dispatch is `codex-remote gpt-6.1-sol` high, standard tier. These current routes supersede older implementation model pins in lane briefs; historical review and inventory pins below remain labelled historical. This table describes the project schedule, not authorization for this dispatch to launch agents or merge.

| Wave | Who / model | Output |
| --- | --- | --- |
| W0 | coordinator (done) | `make task-start TASK=FIRBENCH-1`, handoff row |
| W1 (historical review pins) | adversarial review in parallel: codex-remote gpt-6.1-sol xhigh standard + Muse muse-wonder-1.0 high, read-only on a frozen snapshot | Findings in MCP. A REVISE verdict goes to claude-remote claude-haiku-5-5 xhigh adjudication, then plan v3. |
| W2 (historical dispatch pins) | inventory: gpt-6-luna max fast. ux-map: gpt-6.1-sol xhigh standard. | Inventory: artifact pins and hashes, reused-API signatures, VM corpus location, non-mated frame count, PSU/deff estimate, dependency check. ux-map: JSON, render, critique. |
| W3 batch A | claude-remote claude-haiku-5-5 xhigh | S0 contract |
| W3 batch B | claude-remote claude-haiku-5-5 xhigh, parallel | S1, S2, S3, S6a, S7 |
| Gate | coordinator, VM | AE-12 tracer run |
| W3 batch C | claude-remote claude-haiku-5-5 xhigh | S4 and S6b in parallel; then S5 (after S4) and S9 (after S6b). `mk/evals.mk` is edited serially: S6a, S6b, S9 |
| W4 | harmonizing review (historical sol xhigh pin); implementation fixes: remote Haiku 5.5 xhigh; gate-defect second dispatch: remote Sol 6.1 high standard | AE-1 to AE-12 green, merge on green |
| W5 | first VM run | Golden-150 (diagnostic) and the fir-occ development frames, three legs, private report |

Every launch prints a reaper command, but only for lanes whose result is terminal and landed.

**Operator track (parallel, not lanes):**

1. T-09 written face-label rule, ≈ 1 h.
2. Tier-(a) occlusion queue.
3. Optional union-delta adjudication.
4. Later, acquisition of the confirmatory frame (out of this wave).

## Not Doing

Training, detector replacement, deployments, stack mode, the description-utility rubric, labelling execution, confirmatory claims, cross-space vector comparison, Jupyter as system of record, any local inference, an independent landmark or region alignment intervention, and a buffalo recognizer seam (both later tasks).

## Consolidated Checklist

- [ ] W1 parallel adversarial review completed and adjudicated; plan v3 committed
- [ ] W2 inventory committed; ux-map rendered and critiqued
- [ ] S0 decision manifest, frame registry, shared enums and errors, unseal refusal
- [ ] S1 frames, PSU components, folds, non-mated source-unit inventory, deff/n_eff
- [ ] S2 in-process legs, gt_crop_redetect and cached_yunet_landmark_replay arms, fused insightface, contract-keyed cache, ledger
- [ ] S3 scoring, calibration folds, paired PSU cluster intervals, fixed-order step decision, pair cells, stage waterfall, guardrails
- [ ] S6a CLI `run` and `score`
- [ ] S7 label queue generator and importer
- [ ] AE-12 tracer run on the VM
- [ ] S4 cluster diagnostics
- [ ] S5 private static report S1–S8
- [ ] S6b CLI `report`, `compare`, `unseal`
- [ ] S9 simulator and `fir-bench-acceptance`
- [ ] AE-1 to AE-12 green at the merge-candidate HEAD
- [ ] W5 first VM run report (development/diagnostic tier only)

## Success Criteria

- AE-1 to AE-12 pass on the VM at the merged HEAD, each recorded as a `test_result` tied to the SHA.
- One command reproduces a run's searches and ledger from manifest hashes; `scores.json` and the report reproduce byte-for-byte under the same pinned timings receipt (AE-7). Every GT face ends in exactly one ledger state.
- The verdict line can say "inconclusive", and does so whenever the interval spans the boundary.
- No number appears without its frame admissibility, n_eff and interval.
- No image-bearing artifact is tracked by git.
