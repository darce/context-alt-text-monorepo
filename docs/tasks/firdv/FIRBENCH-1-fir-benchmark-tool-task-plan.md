# Task Plan

> **Metadata**
>
> - **Date**: 2026-10-15 (revision v6; v5 and v4 2026-10-15; v2 dated 2026-10-14)
> - **Author**: revisions v2 and v4 as recorded in the handoff record (claude-opus-5-5; claude-haiku-5-5); revision v6 reconciles to the current remote lane route (see Lane Decomposition)
> - **Project**: prototype-description-service eval harness (related epic: [E24 FIRDV](../../epics/v0.5.0/fir-development-and-measurement-epic.md))
> - **Task ID**: `FIRBENCH-1`
> - **Target Branch**: `feature/firbench-1`
> - **Review Coverage Target**: 2
> - **Status**: draft v6. Reconciles the v5 plan and scope to the landed c274 producers and to the frozen S9 pre-outcome contract, before any Monte Carlo outcome. Earlier v5 reconciliations (FB1-DGAL-02, MCP 16810, MCP 16848/16855/16856, MCP 16732–16736, clarifications 16756, 16763, 16773 and 16777) stand unless this revision marks them superseded. The 29 original high/medium fixes are retained; the three deferred low findings (SOL17, MUSE11, MUSE12) are folded in. Canon-qualified citations, AE numeric gates and bootstrap and H1/H2 margins are unchanged. Implementation-status statements from v2–v5 (for example "only S1 landed" or "producer obligations still open") are superseded by [Current State](#current-state-analysis-verified-2026-10-15-on-the-c274-tree-code-read-wc--l-grep). The checklist is not ticked. This revision claims no S9 pass, no implementation completion, no real-data evidence, no observed ICC, no human observation, no ratification, no seal and no budget.
> - **Source (v6)**: `9bcb442e71e238de879ab7db651587e04c8e2320`. Where a declared SHA is not present in the local history, the source tree and actual producers govern. Revision v5 source (post-gate reconciliation): `44fa2defc2f07aa5665c9de0e2b9d36e8cf86dbf`.
> - **Source HEAD (second dispatch)**: `ccf4119ccf3c81f34477aba80e84a4a7a454cc1c`
> - **Historical source HEAD**: `b6dcaad70f93c2d385d30b31b148e83265d43874`
>
> Review counts and findings live in the handoff DB, not in this file. Canon citations are Canon v0.26.2 row IDs. Revision v5 decisions, seams and the canon key are in [Delegated choices and frozen seams (revision v5)](#delegated-choices-and-frozen-seams-revision-v5). Revision v6 additions (label evidence, prior art, asset audit) sit in the same section, and the frozen S9 pre-outcome contract is in [S9 acceptance contract (revision v6, pre-outcome)](#s9-acceptance-contract-revision-v6-pre-outcome).

---

## FIRBENCH-1. FIR benchmark tool: paired embedder comparison and development loop

## Objective

Build the benchmark tool that guides in-house FIR development and selects the in-house pipeline: SFace-128 vs AuraFace-512 (same YuNet detector; each embedder uses its model-compatible five-point alignment, so the estimand is the model-compatible native pipeline, not an embedder-only contrast), with InsightFace buffalo_l as a judge-side reference only. The tool completes the FIRDV-2 parts that were unbuilt when this plan was first written (S3 metric adapters, S3a stage attribution, S4 cluster views, S5 oracle arms) and the FIRDV-3 S2 controlled checkpoint comparison, inside `scripts/eval_harness/`. It is not a new platform (FIRDV-2: "do not build another generic benchmark platform").

**This wave is benchmark tooling only.** No training, no detector replacement, no deployment, no labelling execution, no confirmatory claim.

## Problem Statement

- The model choice is undecided. Current evidence (30 probes, 17 identities) cannot pick a winner, and M-11 (+0.012 hard-face margin) has no artifact, predates CVUP-1 (OpenCV 5) and is rank-only.
- FIRDV-2 was marked done while only S1 (`experiment_manifest.py`, `outcome_ledger.py`) and the S3a strict detection scorer (`face_metrics.detection_pr_strict`) had landed. The c274 tree now carries the composed path: the S0–S7 producers, the S6a and S6b CLI, the S4 materializer and the S5 report. Still open: the simulated acceptance suite (S9, not landed) and every real-data gate (AE-12 and the real-data evals), so no verdict is established yet.
- The QA report (`benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html`, v5–v8) and the 2026-09-19 assessments already set most rules. The tool has to enforce them, not restate them.

## Constraints

- All execution on the VM. No local inference, no local lanes (8 GB laptop). One explicit exception: the AE-10 read-only static privacy scan runs on the laptop against the private alias map and records the scanned code SHA, scanner digest and report digest (AE-10). Nothing else runs locally.
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
| Fold protocol | k = 5 identity- and PSU-disjoint rotating folds; seed 2406466110. One preregistered primary rotation, `test_fold = fold_protocol.seed % k` (0 at the declared seed); its four complementary folds are the single calibration fit. Other rotations are unsealed development diagnostics only (MCP 16810). |
| Gallery split | seed 2468935812. Enrolled membership is independent of the query fold and is declared per leg and fold in `manifest.firbench.gallery_membership` before outcomes (MCP 16810). |
| Interval resampling | paired cluster percentile bootstrap, `n_boot = 10000`, seed 2429382368 |
| Label queue | seed 336880394; QC values in [Delegated choices](#delegated-choices-and-frozen-seams-revision-v5) |
| S9 simulator | master seed 2208172209 (generator); fixed size tables and joint coupling declared before outcomes; [S9 contract](#s9-acceptance-contract-revision-v6-pre-outcome) |

Seeds are the first 32 bits, big-endian, of SHA-256 of `FIRBENCH-1/v1/{folds,gallery,bootstrap,label_queue}`, declared before outcomes. Revision v4 re-derived all four and they match the values above. Revision v6 re-derived them again and re-derived the simulator seed from `FIRBENCH-1/simulator/v1` (2208172209); all five match.

## Delegated choices and frozen seams (revision v5)

Source: MCP decisions 16732–16736, explicit frozen-input clarification 16756 (`p_d`, `build_nonmated_pool`, runtime binding), grounded annotation contract 16763, timestamp/receipt clarification 16773, and gallery, rotation and scorer-boundary decision 16810 (see *Gallery, rotation and scorer boundary (MCP 16810)*). These are reversible project policies chosen under the canon-first delegation (MCP 16732). They are declared policy, not values the canon prescribes. AE-2 to AE-4 validate the numeric choices on simulated data before any real-data gate uses them. Nothing in this section is a human observation, a real hash, or a ratification.

Second-dispatch adjudication: S0 Build 2 preserves H1 margin 0 and H2 margin 0.05; the exact CARD-27 supplement requires pre-sealing margins and sizing from n_eff, not a new Δ = 0.10 minimum-effect field. Accepted W2 inventory §§4–5 supports only conditional image-proxy arithmetic and leaves admissible non-mated counts unresolved without exhaustive GT. The supplied S0 implementation (`s0.delta.bundle`, head `4d17a6315428042e464ec59a02fc29f6440a6962`) confirms the `consumed_at` keyword and `UnsealToken` return below. MCP 16773 supersedes the older requirement that seal and ratification timestamps agree. These findings are upheld; AE-1 through AE-12 remain required.

**Protocol and eligibility**

- Folds: k = 5 identity- and PSU-disjoint rotating folds. Threshold τ is selected on identity-disjoint calibration folds and frozen before the test read ([CAL-07], [EXP-22], [EVAL-07]).
- Primary rotation (MCP 16810): exactly one preregistered rotation, `test_fold = fold_protocol.seed % k` (0 at seed 2406466110, k = 5). Its four complementary folds form the single pooled calibration fit for τ, and the verdict reads only that test fold. The per-fold τ spread is computed from calibration folds of that same rotation, never from the test fold, and never feeds the test read ([EXP-22], [EXP-30]).
- Floors: ≥ 50 independent PSUs per frame (global) and ≥ 30 per pair cell are necessary, not sufficient. Adequacy still requires the effective-power/MDE check, FPIR resolvability (≥ 3/FPIR non-mated source units) and exhaustive GT. Floors alone prove no adequacy ([EXP-12]).
- N is the independent PSU, never the image or face count ([EXP-23], [AUDIT-11]).

**Design assumptions versus estimates**

- Planning ICC 0.10 is a design assumption. Sensitivity points 0.05 and 0.20 are reported alongside it. No ICC is estimated until S1 measures PSUs on the pinned frame; the measured value is shown beside the assumption and never substituted for it ([AUDIT-11]).
- `p_d = 0.15` and power 0.80 are sizing assumptions ([EXP-12]).
- Two counts, two questions (MCP 16810). H1 MDE is computed from effective mated queries (n_eff of the actual mated queries, the paired-FNIR unit). FPIR resolvability is computed from n_nonmated_eff of the non-mated source units. `Frame.n_eff` records the whole GT inventory for admissibility; inference uses actual mated queries only. Neither count substitutes for the other.
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
- Measurement evidence gate: before real tier-(a) labels feed analysis, a bounded contextual observation of the production process is recorded, with exceptions, scope and limits ([MEAS-29]). The observation is a person's observation of how the values were produced: observe a sample of the process in context and ask operators about values, exceptions and outliers. A JSON link, a reference string or a manifest field is not an observation. Tooling and fixtures may proceed without it. No observation is invented here.

**Timestamps and receipts**

- Semantic `created_at` selects `seal.sealed_at`, else `ratification.ratified_at`, else an explicit `--created-at` (CLI) or `run_frame(created_at=...)` ISO 8601 literal. Seal and ratification describe different events and may differ. Only a supplied explicit literal must match the highest-priority derived value, comparing parsed instants. Missing/invalid values or a conflicting explicit literal raise existing `FrameContractError` (MCP 16773); do not introduce `RunTimestampError`. Semantic writers never read the wall clock. Implementation tests supply fixed literals ([FLOW-18], [PROV-01]). Priority and conflict checks are implemented in `resolve_created_at` (`firbench_cli.py:111`): the explicit literal is compared with the highest-priority derived instant only when one exists.
- `timings.json` and actual attempt/private unseal-ledger consumption receipts are non-replayable and separate from deterministic manifests, ledgers and searches. `scores.json` carries the timings receipt's sha256 and the p95 veto state, and the report may display receipt-derived timing values, so their byte replay requires the same pinned receipt (MCP 16777; AE-7). The receipt is reconciled, never regenerated on replay ([FLOW-18]). Pass `consumed_at` explicitly from an allowed nonsemantic attempt-receipt boundary; an old seal date is not actual consumption time. Static clock scans target semantic writers with explicit receipt-boundary exceptions; they do not ban harmless set operations, seeded RNG or receipt timing globally (MCP 16773; [FLOW-18]).

**Frozen S0 seams** (fixed before consumers; these supersede older signatures only at the seams listed)

- `DecisionManifest` requires `p_d=0.15` (MCP 16756), `min_n_independent=50` and `cell_floor_n_independent=30`, with the planning ICC, fold, gallery, bootstrap and label-queue fields above. S3 imports `p_d` with no implicit/global default.
- `InconclusiveReason.insufficient_independent_psus`, checked before FPIR eligibility and intervals.
- Private queue QC adds `min_gold_decisions_per_annotator=20` and `min_repeat_decisions_per_field=20`.
- `run_frame(..., created_at: str | None = None)`; CLI `--created-at` takes an ISO 8601 literal.
- `build_nonmated_pool(faces: Sequence[GtFace], images: Sequence[ImageUnit], folds: Mapping[str, int], *, fold: int, component_map: Mapping[str, str], exhaustive: bool, planning_icc: float, enrolled_identity_ids: frozenset[str]) -> NonMatedPool` (MCP 16756; MCP 16810 adds the required keyword `enrolled_identity_ids`). It raises existing `FrameContractError` for `exhaustive=False` and malformed component or fold coverage. It cannot recover PSU IDs from the old `faces`, `images` and `folds` inputs alone. Source units stay detector-independent.
- Actual frozen helper: `require_frame_read_allowed(frame: FrameSpec, token: UnsealToken | None, *, decision_sha256: str, run_id: str, code_sha: str, scorer_sha: str, repo_root: Path, consumed_at: str) -> UnsealToken`. Runtime context is explicit, never globals or token-to-itself comparisons. `consumed_at` is the actual nonsemantic attempt-receipt timestamp; the helper returns the consumed token and appends it to the private ledger. Missing/spent/mismatched tokens and failed spending/recording raise `SealedFrameReadError`; malformed `consumed_at` or an open frame passed to this sealed-read helper raises `FrameContractError`. Per-frame `O_EXCL` spending, exact binding, first and second reads, and concurrent-read tests are retained (MCP 16756, 16773).
- MCP 16810 seams (detailed in *Gallery, rotation and scorer boundary (MCP 16810)* below): required keyword `enrolled_identity_ids: frozenset[str]` on `build_nonmated_pool` and `build_frame`; optional `identity_folds: Mapping[str, int] | None` on `calibrate_tau`; the public file scorer `firbench_score_io.score_run(run_dir, *, decision, pair_scores=None) -> dict`; the persisted `manifest.firbench.gallery_membership` registry. The CLI API is unchanged.

**Gallery, rotation and scorer boundary (MCP 16810)**

Declared before real outcomes. The query fold and the searched-gallery membership are separate axes; neither is inferred from the other.

- **Primary rotation.** One preregistered rotation: `test_fold = fold_protocol.seed % k` (0 at the declared seed). Its four complementary folds are pooled as the single calibration fit for τ, and τ is frozen before the one test read ([EXP-22], [EVAL-07]). Other rotations (`test_fold` 1 to 4) are unsealed development diagnostics only: labelled as development, excluded from the verdict, never pooled into a CV verdict, and never a repeated private read of a test fold.
- **Gallery membership is independent of the query fold.** Enrolled identities come from the gallery split (seed 2468935812). Before query outcomes, every leg key (including attribution) and fold writes one entry to `manifest.firbench.gallery_membership` with `leg_key`, `fold`, `gallery_sha256`, `enrolled_identity_ids`, `identity_folds` (every enrolled identity mapped to its fold, whether or not it has a mated probe on the frame) and `enrolled_occluders` (optional, when known). All native legs share per-fold membership, reused by attribution; each leg retains its own vector space and gallery hash ([EMB-01]). An empty `enrolled_identity_ids` is an explicit declared empty gallery, not missing context.
- **Required enrolled identities.** `build_nonmated_pool` and `build_frame` each take the required keyword `enrolled_identity_ids: frozenset[str]`. In `build_frame` it defines the test gallery. Omitting it is a call-signature refusal. `frozenset()` is accepted only as a declared empty gallery.
- **Persistence.** The run persists the full validated `frame.json` (`frame-v1`) and the `gallery_membership` list in the run manifest before running query outcomes. Preparation may compute template vectors and membership first, without query scores. A missing registry refuses scoring.
- **Fold provenance in calibration.** `calibrate_tau` takes an optional `identity_folds: Mapping[str, int] | None`. The file scorer always passes the full enrolled map from `gallery_membership`. A top-k gallery identity whose fold is missing, or whose fold contradicts the fold provenance on its record, raises `CalibrationLeakError`; this fails closed and adds no error class. With `identity_folds=None`, the same rule applies to provenance carried on the record, and the file scorer never takes that path. A known-gallery identity with no mated probe still needs its fold in the map, and its lack of a probe is not missing provenance ([CAL-07]).
- **File scorer boundary.** `firbench_score_io.score_run(run_dir, *, decision, pair_scores=None) -> dict` reads the run directory and returns the `scores-v1` document. `decision` and `pair_scores` are keyword-only. The CLI `score` command keeps its existing arguments and calls this function; the in-memory S3 functions stay pure.
- **Score wire.** The actual `scores-v1` schema and core/IO producers govern the field names and estimands below. Confirmatory inference, guardrails and p95 use native probability records in the single primary test fold; fit folds and challenge records stay separate. Challenge diagnostics use explicit `::sampling=challenge` leg keys; other rotations never enter the verdict.
- **Decision trace.** Required `decision_path: string[]` serializes `list(verdict.decision_path)` in its actual order, without invented steps, sorting or deduplication. An empty trace is only for explicitly labelled legacy/no-trace fixtures.
- **`joint_gaps`.** An array of typed rows, unique by `(leg_key, arm)`: `leg_key: string`, `arm: gt_crop_redetect | cached_yunet_landmark_replay`, `scored: bool`, `reason: string | null`, `n_pairs: int`, `n_psu: int`, `n_eff: number`, `delta: number | null`, `interval: {lower: number, upper: number, level: number} | null`, `unavailable_counts: {native: int, attribution: int}`. The actual IO contrast is FNIR(native) − FNIR(attribution), with a paired 95% PSU percentile interval on the same available mated faces. Native and attribution unavailable counts are separate (including missing attribution records); excluded faces are never imputed as misses. Scored rows have null reason and numeric delta/interval; unscored rows retain support and counts, name a reason and have null delta/interval. These are joint intervention gaps, not causal shares ([EVAL-16]).
- **Cells.** Each row is `{leg_key, query_occluder, enrolled_occluder, data_origin, n_units, n_identities, n_psu, n_eff, scored, fnir, interval}`. Keys/occluders are strings, `data_origin` is `real | synthetic | unknown`, counts are nonnegative integers, `n_eff` is numeric, `scored` is boolean and FNIR/interval are nullable. `n_units` counts mated GT faces, not FPIR source units. The interval estimates this leg's single FNIR rate: the IO reuses `paired_cluster_bootstrap` against an all-correct reference, so it is a 95% PSU percentile single-rate interval, not a between-leg paired difference. Wire interval objects carry only `lower`, `upper`, `level`; method is documented here, not added to the schema. Below the cell floor, retain counts and set FNIR/interval null. Global eligibility gates interval computation separately; a cell rate can be scored while its interval is null. Occluders serialize as sorted `+` composites; null annotations become `unknown`, an empty set becomes `clear`.
- **Provenance and enrollment.** `data_origin` is `synthetic` only with an explicit synthetic parent, `real` only with explicit real provenance, otherwise `unknown`. Unknown stays separate. The enrolled occluder comes only from registry `enrolled_occluders`, never a predicted identity ([PROV-01]).
- **Per-leg `pair_fmr`.** A status wrapper `{status, reason, data}`. Explicit complete 1:1 pair scores alone produce `status: available`, `reason: null`, `data: {false_matches: int, n_nonmated_pairs: int, rate: number}`. Without scores: `status: not_evaluated`, `reason: pair_scores_not_supplied`, `data: null`. Unavailable calibration or no nonmated pairs gives `status: unavailable`, a named reason and null data. Never substitute truncated top-k searches or a fabricated zero.
- **Guardrail evidence.** Rows carry `id`, `metric`, `role`, `state`, nullable `value` and nullable `timings_sha256`. Optional typed `evidence` carries all of `leg_key: string | null`, `cohort: string | null`, `n_units: int | null`, `n_psu: int | null`, `n_eff: number | null`, `limit: number | null`, `reason: string | null`. Support retains its metric-specific units. P95 uses semantic state/digest only (`value: null`, evidence `limit: null`); no numeric milliseconds enter semantic state or evidence ([FLOW-18]).
- **p95 cost conservation (MCP 16856).** Within scored native primary-test probability scope, fix `N_GT` independently from exhaustive GT. For image i with `m_i > 0`, each GT-face exposure is `image_total_i / m_i + sum(empty_GT_image_total) / N_GT`, where image totals include all native image and record work (detection, alignment, embedding, search). There are exactly `N_GT` samples and their sum equals ALL native work in scope. Extra detections add cost and mint no samples; empty images add no fake bins. At `N_GT = 0`, p95 is unscored. Use the linear 95th percentile in `ms/GT_face`. The raw receipt key `timing_receipt_ms` explicitly declares raw milliseconds; it needs no invented mandatory unit field. The executable guardrail rule must declare the derived unit `ms/GT_face`; missing/incomplete costs or an unsupported rule/unit is unscored. Numeric milliseconds remain in RAM/receipt, with only actual veto state and receipt SHA in semantic output.
- **Producer obligations (verified in code 2026-10-15).** `firbench_score_io.py` serializes the actual core trace as `decision_path` (`list(verdict.decision_path)`). `timing_exposure` adds the empty-image share to every GT-face sample and returns `no_gt_face_timing_exposure` when N_GT is 0. The p95 guardrail's `evidence.limit` is null, so milliseconds stay out of semantic output. These satisfy MCP 16856 as read. Timing-exposure tests exist in the tree and were not run in this revision. Default-wire join and AE-12 evidence still establish nothing until a real run completes. This revision changes no producer or test.
- **Replay.** Unchanged by this revision: the MCP 16777 pinned timing receipt governs `scores.json` and report byte replay. No veto, receipt or outcome is masked, normalized or overwritten.

**Private runtime binding (MCP 16848/16855; implementation contract)**

- Read `benchmarks/private/firbench/inputs/<frame_id>.json`, schema `firbench-inputs/v1`, without new choices or CLI flags. Bind query source kind/path + SHA separately from the gallery-template document path + SHA; verify their bytes against `FrameSpec.source_sha256` and `GalleryLineage.templates_sha256`. The owning runtime module and tests must freeze the exact minimal typed binding/template-row shape; this plan does not invent a competing schema. Missing context, assets, hashes or GT produce named refusals, never `NotImplemented`, made-up data, downloads or automatic sample fallback.
- Query and enrollment media/hash inventories must be disjoint; refuse overlap rather than drop queries. For each query fold, use only that fold's identity-eligible template roster, the actual `gallery_split.build_disjoint_galleries` seed and fixed G1 direction. G2/nonenrolled query identities are nonmated; never infer template/probe identity from predictions. Known identity folds come from canonical S1 PSUs; template-only folds come from a declared full map or deterministic pre-outcome seed binding. Persist the full map. All native legs share membership per fold and retain their own vector/hash spaces.
- The DRIVER owns S0 once-only authorization before any source/GT/template/pixel read. Default collaborators are created lazily; settings/model identity may be prepared without query data. Cache authorized pixels in RAM and never reopen them for scoring. Before annotation loss, real tier-(a) source rows must pass the actual S7 qualified QC/observation consumer boundary; a reference string is no evidence.
- Persist full validated `frame.json` and registry rows for EVERY leg key/fold, including attribution, before query outcomes. Frame gallery hashes use the primary native leg and persist that basis. Failed query attempts retain immutable declaration metadata and attempt failure evidence, publishing no invalid searches/ledger/scores/timing outcomes. Static refusals write/spend nothing. Scorer identity hashes core + IO source consistently for later unseal. Existing S2 record/ledger/timing keys are conserved. These obligations supply no real-data evidence, observation, seal or measured hash.

**Packaged label evidence (`firbench-label-evidence/v1`; FB1-S6A-04; implemented in `fir_occ_labels.py`)**

- `freeze_label_evidence(export_path, queue_path, gold_path, *, repo_root, frame_sha256) -> LabelEvidenceBundle` is read-only. It calls the actual S7 readers (`load_label_export`, `load_queue`, `to_face_instances`, `require_real_analysis_rows`) and captures the exact bytes of the closure they read. It opens no images, model files or alias maps.
- The descriptor has exactly the keys `schema` (`firbench-label-evidence/v1`), `frame_sha256`, `export_path`, `queue_path`, `gold_path` and `files` (sorted `{path, sha256}`). Every path is run-relative, `label-evidence/<original repo-relative private path>`, which preserves relative link topology and bytes. Hashed queue, export, acceptance and observation documents are never rewritten.
- Named support edges only: `queue.acceptance_path`; the acceptance links `prior_export`, `validation_queue`, `validation_gold` and `validation_export`; and `export.observation_ref` for tier (a). Arbitrary image or path links and directory copies are not followed. Absolute, escaping, symlinked, ambiguous or cyclic links fail with a named error before any write.
- `requalify_label_evidence(run_dir, descriptor, *, frame_sha256) -> tuple[dict, ...]` is read-only. It validates the descriptor and frame strictly, refuses symlinks, and reads only the enumerated run-local `label-evidence/` files through the same S7 readers. Missing, corrupt or changed proof raises `FrameContractError`.
- The CLI persists exactly `bundle.files` with `O_EXCL` before any query outcome and sets `manifest.firbench.label_evidence` to the descriptor (`firbench_cli.py`, label-evidence persistence block). `frame_sha256` is the SHA-256 of `frame_json(prepared_frame) + "\n"` in UTF-8 and must match the immutable `frame.json`. `PreparedRun.label_evidence` defaults to `None` as its last field, so injected collaborators without it still work.
- Static invalid evidence writes and spends nothing. Evidence checks that need protected sealed GT or source reads run after the S0 token is consumed; if they refuse, the attempt is a failed attempt. Tokens are never refunded, and no prepare, image or GT read moves ahead of the S0 gate. Snapshot persistence precedes query outcomes.
- A reference string, a JSON boolean or a cached decision is never evidence. Synthetic generated fixtures may model a complete real-evidence wire, but their assertions are software-only and never confer real eligibility or prove human conduct.

**UI policy (W2 ux-map and L1 label queue)**

- Keep the supported MapState enums with bench semantics in purpose and zones. Add no enum values ([INT-21]).
- Every interactive object specifies its default, activated and updated states ([INT-21]).
- Result display: show the evidence path, meaning the data shown, the comparison basis, the interval and n_eff ([VIZ-23]), and explain the result from the state it produces ([INT-22]). WRIT-81 applicability remains conditional until actual executive-summary prose is rendered and inspected: if that prose asserts a decision with an unconditional assurance that contradicts a decision-changing uncertainty or untested condition in the supporting analysis, retain the qualification. The structured verdict label alone does not establish that prose trigger.
- Image-selection pool (S5 failures): overall and selected pool counts, the selection rule and pseudonymous IDs ([VIZ-41]).
- L1 queue: one draw mode (`a`, add missed face) ([INT-23]). The next item opens only on operator Enter, with no auto-advance deadline; Esc undoes; export keeps recoverable work and offers a repair path on error ([INT-24], [FORM-11]). Queue, export, import and report handoffs are mapped ([INT-25]).
- Static exit markers need no fabricated loading screen. [RLSE-04] (practice label, *bootstrap*) asks for designed loading, empty, error and offline states on a screen with states. A static exit marker has no load, fetch or content state in the artifact, so its trigger does not fire. This is the adjudicated exemption. Any other screen stays subject to RLSE-04.

**Prior art and asset audit (revision v6)**

- **FIR-12-BR-22** (handoff finding 9818; superseded via EVAL-LANDING-1; the lesson is taken from the original finding text): mixed `media_id` and SHA aliases counted one still twice. Rule: join by the declared canonical `image_id` plus the exact frame `ImageUnit.sha256`; keep the PSU duplicate-unit rule; mint no extra units.
- **Semantic prior art**: a FIR-12 GT face that the pipeline misses remains an FNIR miss even when a semantic name match recovers the name. The semantic matcher named in the handoff record (gte-base-en-v1.5) is handoff tooling only, not a bench leg. Names are normalized before any comparison.
- **MAINT-FIR-DETECTION-20260919** (handoff record, verified prior art): exhaustive GT is built independently of the detector, and the detector-only comparison is reported separately from the end-to-end metric. The end-to-end FNIR is never replaced by the detector-only figure ([EVAL-16], [EVAL-19]).
- **EMB-01** is unchanged: one embedding space per comparison. Cross-space and cross-runtime comparisons stay refused.
- **AuraFace normalization.** The raw model output is not L2-normalized by itself (`provenance.py:65`, where `output_l2_normalized` describes the raw graph output). The accepted runtime L2-normalizes through the shared `embed_batch` contract (`recognition/infrastructure/face_pipeline/_common.py`).
- **Asset audit (2026-10-15).** The three primary native weights are located and fully hash-verified on the VM under `/opt/acx-backend/data/dev-models/face_pipeline/`: `glintr100.onnx`, `face_recognition_sface_2021dec.onnx` and `face_detection_yunet_2026may.onnx`. Sizes and SHA-256 values match the pins in `provenance.py` (lines 107, 121 and 138). This supersedes only the W2 bounded not-found results for these three files (`firbench-1/inventory.md`, section 1d). It does not establish corpus, GT or observation availability. Nothing was downloaded, inferred or changed. A file-hash check does not establish container or live-stack state.

**Canon key (Canon v0.26.2)**

Rule names are the bold text at the start of each Rule cell. Source locators are as each Source cell prints them. This key covers the rows cited in revisions v4 and v5, in this plan and in the scope. Cards are cited by ID and slug from the release manifest (`card_ids`); the pinned mirror has partial card coverage. The exact CARD-27 body was read from the supplied sibling `canon-supplement/margin-and-design-effect-before-the-run.md` (SHA-256 `186c94c2b0ba88897cebea26c39752d6f0e87bbab8bff3ec1fa9aace79f85aad`, verified 2026-10-15; manifest slug `margin-and-design-effect-before-the-run`). It supports pre-sealed margins and design-effect sizing, and prescribes no project-specific numeric margin or extra manifest field.

Cards cited in revision v6 (manifest slugs): CARD-03 `designed-unknown`, CARD-08 `falsification-disconfirmers`, CARD-11 `measurement-integrity`, CARD-27 `margin-and-design-effect-before-the-run`, CARD-32 `condition-matched-reference`. CARD-29 (`runtime-fork-is-part-of-provenance`) and IDX-02 are not cited for offline version or cache identity. Leg and cache identity cite PROV-01 and EMB-01 instead.

| ID | Rule | Source (as printed) | Used for |
| --- | --- | --- | --- |
| CAL-07 | Select face thresholds on identity-disjoint folds | Video-to-Video Face Recognition for Low-Quality Surveillance Data, ch. 6 | k = 5 folds; τ on calibration folds |
| EXP-22 | No circular analysis (double-dipping) | Statistics Done Wrong, ch. 6 | Protocol and seeds before outcomes; one primary rotation fixed before outcomes; τ frozen before test |
| EVAL-07 | Validation-only selection | Designing Machine Learning Systems | Test read once |
| EXP-12 | Power and practical significance | Trustworthy Online Controlled Experiments, ch. 2 | Declared effect, p_d, power, MDE; floors ≠ adequacy |
| EXP-23 | Pseudoreplication check | Statistics Done Wrong, ch. 3 | N = independent PSUs |
| EXP-24 | Interval over bare p | Statistics Done Wrong, ch. 1 | An interval on every reported effect and verdict. EXP-12 does not exempt EXP-24 here, even though the EXP-24 row exempts systems that already mandate CI-on-delta under EXP-12. This plan applies EXP-24 directly. |
| EXP-19 | Significance of the difference | Statistics Done Wrong, ch. 5 | A − B tested by contrast, not chained |
| EXP-30 | Disclose specification spread | Seeing with Fresh Eyes: Meaning, Space, Data, Truth, ch. 4 | Per-fold τ spread; ICC sensitivity rows |
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
| VIZ-35 | Use a range-frame for observed extrema | The Visual Display of Quantitative Information, ch. 6 | S5 scatterplots that meet the stated trigger only (audit FB1R-SOL-17) |
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
| PROD-31 | Release-manifest rule ID only (business-marketing lexicon, not in the pinned mirror, so its text was not read) | Release manifest | AE-12 bounded tracer citation; the ID is cited, its rule text is not relied on |

**Repository rules** (not canon rows; actual source [docs/workbay/constitution.md](../../workbay/constitution.md), verified 2026-10-15): `rg-008` validate config at load time; `rg-009` no task-specific logic in generic modules (policy values come from config and manifests, not code); `sr-006` `assert` only for narrow internal invariants; `sr-007` centralized status enums. AE-10 privacy is a repository rule with no canon row and no constitution ID; its procedure is in [scripts/privacy/README.md](../../../scripts/privacy/README.md).

## Current State Analysis (verified 2026-10-15 on the c274 tree: code read, `wc -l`, grep)

Paths are under `apps/prototype-description-service/scripts/` unless a full path is shown. "Landed" below means the producer is present in the tree and was read; it does not mean its tests were run in this revision or that any real-data gate passed.

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
| Paired stats | `scripts/bench/score_report.py` (`holm_bonferroni`, paired bootstrap) | `holm_bonferroni` is not called by the verdict; the image-level bootstrap is not used for verdicts. The PSU resampling pattern is reused. `bootstrap_paired_delta` (`score_report.py:178`) is the actual image comparator; S9 coverage calls it. |
| Legs | `recognition/infrastructure/embeddings/face_pipeline_adapter.py` (SFace and AuraFace profiles, runtime fingerprint in model id), `eval_harness/buffalo_bench.py` | In-process legs |
| Existing annotator | `benchmarks/tools/golden150-box-annotator.html` (local, ignored, 1.9 MB; not present in this checkout) | Pattern for the label queue |
| Populations | `benchmarks/private/fir-capacity-20260919/fir-occ-population-review-draft-20260919.{csv,json}` | Queue membership and probabilities |
| Landed S0 contract | `eval_harness/firbench_contract.py` (1253): `DecisionManifest` (`p_d`, floors, seal), `UnsealToken`, `require_frame_read_allowed(..., consumed_at)`, errors `SealedFrameReadError`, `CalibrationLeakError`, `FrameContractError`, `TauInfeasibleError`, `UndeclaredH2LegError`; enums `Arm` (`gt_crop_redetect`, `cached_yunet_landmark_replay`), `LegKind`, `SearchStage`, `IdentityStatus`, `SamplingArm` | Frozen seams in Delegated choices |
| Landed S1 frames | `eval_harness/firbench_frames.py` (952): `build_nonmated_pool` and `build_frame`, both with required `enrolled_identity_ids`; `NonMatedPool`, `Frame` | Non-mated source units, PSU components |
| Landed S2 legs | `eval_harness/firbench_legs.py` (1252): `sface`, `auraface`, fused `insightface` (attribution `unavailable_fused`); native and the two attribution arms | Per-leg runtime contract and cache keys |
| Landed S3 core | `eval_harness/firbench_score.py` (1053): `finish_outcomes`, `calibrate_tau` (optional `identity_folds`), `paired_cluster_bootstrap`, `decide` | Scoring core; in-memory functions stay pure |
| Landed S3 file IO | `eval_harness/firbench_score_io.py` (1244): `score_run(run_dir, *, decision, pair_scores=None)`; writes `decision_path`, `joint_gaps`, cells, `pair_fmr` and guardrail evidence; p95 through `timing_exposure` (empty-image share added, `N_GT` samples, linear 95th percentile, `ms/GT_face`) | `scores-v1` writer |
| Landed S4 | `eval_harness/firbench_clusters.py` (1233); `eval_harness/firbench_cluster_io.py` (675; `materialize_clusters`) | Cluster diagnostics and S4 materializer |
| Landed S5 | `eval_harness/firbench_report.py` (2930); interaction test `scene/tests/test_eval_harness_firbench_report_interactions.py` | Static private report |
| Landed S6a and S6b | `eval_harness/firbench_cli.py` (1442): `run`, `score`, `report`, `compare`, `unseal`; `eval_harness/firbench_runtime.py` (620): `default_collaborators`, `PreparedRun` (`label_evidence` last field, default `None`) | CLI and default loader |
| Landed S7 | `eval_harness/fir_occ_labels.py` (1767): `load_label_export`, `load_queue`, `to_face_instances`, `require_real_analysis_rows`, `freeze_label_evidence`, `requalify_label_evidence`; `benchmarks/tools/fir_occ_label_queue.py` (590); keyboard test `scene/tests/test_eval_harness_fir_occ_label_queue_interaction.py` | Label queue, importer, packaged evidence |
| Landed W2 ux-map | `benchmarks/ux-maps/fir-bench.uxmap.json` and `fir-bench.md` (733 lines) | Screen inventory and render |
| Not landed: S9 | `eval_harness/firbench_selftest.py`, `scene/tests/fixtures/firbench_sim_v1.json`, `scene/tests/test_eval_harness_firbench_acceptance.py`, and a `fir-bench-acceptance` target in `mk/evals.mk` (none present) | Gated by the S9 launch rule in the S9 contract |
| Weight files (2026-10-15) | `/opt/acx-backend/data/dev-models/face_pipeline/`: `glintr100.onnx`, `face_recognition_sface_2021dec.onnx`, `face_detection_yunet_2026may.onnx`; sizes and SHA-256 match `recognition/infrastructure/face_pipeline/provenance.py` (lines 107, 121, 138) | Located and hash-verified; no inference, download or change |

## Target Outcome

`make fir-bench-run FRAME=<id> RUN_DIR=<dir> LEGS=sface,auraface,insightface` on the VM produces an immutable run (manifest, ledger, per-leg caches). `make fir-bench-score RUN_DIR=<dir>` writes the frozen-τ `scores.json`. `make fir-bench-report RUN_DIR=<dir>` writes a private static HTML (screens below) plus JSON/CSV. `make fir-bench-compare RUN_A=<dir> RUN_B=<dir> OUT=<private dir>` gives paired deltas, or refuses when the runs are incompatible. `make fir-bench-unseal FRAME=<frame_id> RUN_ID=<run_id>` appends one unspent unseal token to the private ledger; the sealed-read helper refuses a missing, spent or mismatched token.

## Proposed Solution: modules (inside `scripts/eval_harness/`, separate core and IO lanes)

| Slice | New file(s) | Job |
| --- | --- | --- |
| S0 contract | `firbench_contract.py`, `benchmarks/manifests/fir-bench-decision-v1.json`, interchange schemas and fixtures | Decision-manifest schema: estimand, δ, α split, interval method, guardrails, harm direction, disconfirmers and their dates, seal hash, planning ICC, fold protocol, gallery lineage. Frame registry with admissibility. Null means unratified. Frame-read tokens live in a local-only unseal ledger; a sealed frame is read once per token. Unseal refusal. Shared enums (`SearchStage`, `IdentityStatus`, `SamplingArm`, `FoldRole`, `AlignmentMode`), versioned `frame-v1`, `face-search-record-v1`, `scores-v1`, `clusters-v1`, `comparison-v1` schemas, and the entry-point signatures fixed before batch B. |
| S1 frames | `firbench_frames.py` | Load population queues. Build PSU components (union-find over image–identity, duplicate, session and synthetic-sibling edges), then identity-disjoint folds over whole components. Build the immutable non-mated source-unit inventory (non-mated GT faces plus one background unit per frame image; never detector-derived). Estimate deff and n_eff, emit admissibility. |
| S2 legs | `firbench_legs.py` | In-process legs `sface` and `auraface` built from pinned manifests by an offline factory (not the shared runtime), and `insightface` (judge, fused: no separate alignment stage). Arms `native`, `gt_crop_redetect` (GT box crop re-detection) and `cached_yunet_landmark_replay` (cached YuNet landmarks; no human landmarks exist). Attribution arms apply to `sface` and `auraface` only. Per-leg cache keyed by the model-manifest fingerprint (weights sha, preprocessing, OpenCV/ORT). Raw detections are kept, and ledger rows are written per GT face. |
| S3 score core | `firbench_score.py` plus its main test (two owned paths; [S3 brief](firbench-1/S3-score.md)) | FNIR-vs-FPIR curves on the fixed non-mated source-unit denominator, calibration-fold τ (smallest feasible on the pooled calibration pool of source units; calibration-leak refusal), paired PSU cluster intervals, fixed-order step decision on intervals only, primary-FPIR and MDE eligibility, pair cells, stage waterfall, guardrails (veto or report-only), versioned boundary semantics |
| S3 file IO companion | `firbench_score_io.py` plus its main test (separate two-path ownership) | Frozen `score_run(run_dir, *, decision, pair_scores=None) -> dict`; validates and joins frame, registry, searches, ledgers and timing receipt into `scores-v1`. |
| S4 clusters | `firbench_clusters.py` | Cluster metrics, mutual-kNN, pure-numpy reference threshold clustering (`reference_threshold_cluster`), dendrogram cut at the production threshold s with τ as a reference line, PCA spectra, UMAP diagnostic coordinates and companions. The production loader `prepare_cluster_caches` is DB-coupled and is not called. |
| S5 report | `firbench_report.py` | Static HTML (light/dark, no network, keyboard accessible, glyph plus colour) plus JSON/CSV, with a private-path guard |
| S6a CLI | `firbench_cli.py`, `mk/evals.mk` | `run` and `score` (batch B, needed by the AE-12 tracer) |
| S6b CLI | same files, after S6a merges | `report`, `compare`, `unseal` |
| S7 label queue | `benchmarks/tools/fir_occ_label_queue.py` (allowlisted), `eval_harness/fir_occ_labels.py` | Generate the private single-file HTML queue. Import and validate exports into the fir-occ-v1 face-instance schema. Union-delta mode for T-14. Packaged evidence (`freeze_label_evidence`, `requalify_label_evidence`, `firbench-label-evidence/v1`) lives in the same file; see Delegated choices. |
| W2 ux-map | `benchmarks/ux-maps/fir-bench.uxmap.json`, `fir-bench.md` (rendered by the coordinator's canvas CLI; the `.gitignore` allowlist line already exists) | Screen/zone/state/flow inventory, rendered with `ux-map render --path benchmarks/ux-maps/fir-bench.uxmap.json --format markdown`, then critique |
| S9 acceptance | Two independent owners after S6b merges: S9-simulator (`firbench_selftest.py`, `scene/tests/fixtures/firbench_sim_v1.json`) and S9-checks (`test_eval_harness_firbench_acceptance.py`, `mk/evals.mk` target `fir-bench-acceptance`, edited after S6a and S6b). A third owner, S9-comparator-perf, owns the measured comparator change. See the [S9 contract](#s9-acceptance-contract-revision-v6-pre-outcome). | Seeded clustered simulator (PSU sizes, ICC, per-leg error rates, planted effects by cell and stage), A/A and planted-effect Monte Carlo, determinism and replay checks. Runs the completion evals below. Not landed in this tree. |

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
 τ spread over 4 calibration folds (primary rotation) #.##–#.##          (EXP-30)
 other-rotation FNIR diagnostics: development frames only, outside the verdict
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
  - range frame (VIZ-35), qualified: it applies only to a scatterplot that serves a stated bivariate-pattern task, where decision-relevant measured extrema are hidden by round-number frame tails that no task reference needs. Trim only the unneeded tails and label the measured endpoints. Check each actual rendered chart against that trigger (the same trigger as the accepted S5 brief). This is neither a blanket mandate for every SVG nor a ban; the FPIR 0.001, 0.01 and 0.05 task references on the operating curves are retained either way.
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
- Static checks for this revision: markdown link and anchor validation, `git diff --check`, and the affected signature contracts (Delegated choices and the S9 contract). `make lint-task-plans` calls `scripts/hooks/guard-task-plan-findings.py`, which is absent from this tree, so it is not claimed as passed. The canvas CLI renders `fir-bench` (`ux-map render`), and the coordinator critique has no high findings.
- Prior receipts, recorded from the handoff record and not re-run in this revision: CLI 518 tests, report 178 tests (actual Chrome light and dark render), joined-label 284. Their counts overlap existing suites. They are not counts of the S9 acceptance tests and are not AE evidence.

## Open questions

Revisions v4 and v5 close the operator-choice items that v2 listed. MCP 16732–16736 decided them as declared project policy, validated by AE-2 to AE-4 before real-data gating (see [Delegated choices](#delegated-choices-and-frozen-seams-revision-v5)):

- Minimum independent PSUs before H1 or H2 can reject: 50 per frame (global), with 30 per pair cell. Below the global floor the verdict is `insufficient_independent_psus` (S3 Build 6, eligibility).
- Annotations a frame must carry before a verdict is eligible: the required list in Delegated choices.
- A duplicate detection that overlaps an already represented GT face (not its one-to-one match) opens no additional source unit. Its extra names count only as spurious names (S3 Build 2).
- Manifest values before seal: `fold_protocol` (k = 5, seed 2406466110), `gallery_lineage.split_seed` (2468935812), `interval.n_boot` (10000) and `interval.seed` (2429382368) are delegated values. The committed manifest still carries null until S0 writes them, and seal keeps refusing null (S0 Build 2).
- `planning_icc` = 0.10 is a declared design assumption with sensitivity 0.05 and 0.20. It is not an observed value.
- Queue QC values: gold share 0.10, repeat fraction 0.10, percent-agreement floor 0.90, kappa floor 0.80, gold-accuracy floor 0.90, support 20 gold and 20 repeat decisions. The queue `qc` block takes these values, and the importer keeps refusing null (S7 Build 1 and 2).
- Primary rotation and gallery membership (MCP 16810): one primary `test_fold = fold_protocol.seed % k` and the per-leg, per-fold `gallery_membership` registry are declared before outcomes. The registry is persisted in the run manifest before any outcome is written, and the scorer refuses a run whose registry is absent. The membership counts are measured by S1 on the pinned frame, not chosen here.

Evidence gates. These are not operator-choice loops. They stay unresolved until the evidence exists:

- Real frame, corpus and template hashes: unresolved until S1 measures the pinned frames on the VM. The plan carries no frame hash values, and sealing refuses absent inputs. The three primary weight files are resolved separately (Current State and Delegated choices).
- Real source and template bindings, exhaustive independent GT, admissible counts, human observation and QC, ratification, seal and budget: all unresolved. Simulated, fixture and fake evidence establish none of them.
- Observed ICC: unresolved until S1 measures PSUs on the pinned frame. The planning value 0.10 remains a design assumption until then.
- Measurement observation for real tier-(a) labels (MEAS-29): unresolved. A bounded contextual observation record is required before real tier-(a) labels feed analysis. Tooling and fixtures may proceed without it. None is invented here.
- Policy validation: the floors, folds, bootstrap and QC values are checked by AE-2 to AE-4 on simulated data before any real gate uses them.

## Completion evals (definition of done for the tool)

The tool is done when it is trustworthy, not when it has picked a model. A benchmark that has never been shown to detect a known effect, or to stay quiet on a null, cannot guide development (EXP-13). Each eval below runs on the VM at the merge-candidate HEAD and is recorded as a `test_result` tied to that SHA. `make fir-bench-acceptance` runs all simulated and fixture evals; the real-data evals run through the CLI.

| ID | Eval | Pass rule | Canon |
| --- | --- | --- | --- |
| AE-1 | Known answers | Synthetic fixtures with analytic FNIR, FPIR, FPI, B-cubed and ledger counts match. Counts (FPI, ledger states, pair-cell and stage counts, B-cubed counts) compare as exact integers. Analytic rates are checked against `fractions.Fraction` oracles with float tolerance 1e-12. | EVAL-18 |
| AE-2 | A/A null (simulated Type-I behaviour) | Simulated only: 2,000 seeded null replicates at the planning ICC 0.10, reported alongside the 0.05 and 0.20 sensitivity points. Scenario parameters: face-count size-weighted PSU size ≈ 13 and n_eff ≈ 300. The report's M̃ = 12.925 does not reproduce from the tracked manifest, so these are scenario values, not measured frame properties. Step 1: the full decision procedure says "superior" in ≤ 0.032 of replicates (nominal one-sided 0.025 + 2 MC SE, SE = 0.00349). Step 2: at the boundary Δ = δ, with H1 forced to pass, step 2 rejects in ≤ 0.060 of replicates (nominal 0.05 + 2 MC SE, SE = 0.00487). Step 2 is evaluated on the reviewed 400 H2 design, the meaningful boundary control (H2 MDE 0.0480 is below δ at n_eff 400). The 300-design H2 path is the MDE refusal case: it must give `margin_unreachable_mde_gt_delta` (H2 MDE 0.0554 is above δ at n_eff 300). Full runs use 2,000 replicates and the manifest `n_boot`. | EXP-13 |
| AE-3 | Interval coverage | In 2,000 planted-effect replicates the 95% paired cluster interval covers the true Δ in 93–97% of replicates. The report also shows the image-level bootstrap's coverage on the same replicates, so the PSU correction is visible. | AUDIT-11, EXP-23 |
| AE-4 | Planted-effect sensitivity | A planted ΔFNIR 0.10 at n_eff 115 (the step-1 requirement for Δ 0.10) is detected by H1 in ≥ 0.77 of 2,000 replicates (0.80 power minus 3 SE; SE = 0.0089). An effect planted only in the clear→mask cell appears in that cell and not in clear→clear. A planted 10% detection drop appears in the "missed" stage count, and the wrong-identity rate among embedded faces changes by at most 0.05 (absolute) between planted and control runs. | EXP-12, EVAL-16 |
| AE-5 | Real-data canary | On the Golden-150 diagnostic frame, using the 54-entry draft roster (`golden150-draft-20260723.json`, not the 17-identity evidence set) as the gallery, a canary copy of the AuraFace leg relabels a declared set of k = 5 identities (⌊0.10 × 54⌋) by seeded derangement. The run reports the measured FNIR and false-name effect with its paired CI; significance is not guaranteed. The RED pass runs on a powered synthetic fixture whose changed search ids and effect are precomputed, and the canary must detect that planted effect. Legs tagged canary are refused in sealed runs. The canary is a deliberate canary governed by EXP-13, not a surprise-investigation rule. | EXP-13 |
| AE-6 | Legacy parity | In `legacy_v1` boundary mode the bench reproduces the pinned historical counts exactly (the W2 inventory pins the artifacts, including `face_unknown_rejection` 204/207). The `v2` mode lists every item whose outcome changes. Historical 204/207 is report-level evidence; raw per-probe provenance is still needed to verify replay, and is not supplied by that report count. | CAL-02 |
| AE-7 | Determinism and replay | Two cold runs from pinned inputs (same frame, sealed decision, legs, seeds, resolved `created_at`, code SHA, and the same `--out` basename under different parents) give byte-identical `searches.jsonl` and per-recognition `ledger/` files. Seeds come from the manifest. Iteration is sorted. Each cold run writes its own `timings.json`, a fresh physical receipt that is non-replayable and excluded from this comparison. `scores.json` and the report are not compared byte-for-byte across cold runs, because they carry the receipt's `timings_sha256` and the p95 veto state, and the report may display receipt-derived timing values. Fresh cold-run timings are different assessment inputs and can change the actual p95 veto: `fail` gives `guardrail_vetoed` at S3 check-order step 3, and the stop rule then leaves H2 without a state. Full `scores.json` and report byte replay therefore requires the SAME PINNED receipt (MCP 16777). Re-running `score` or `report` on one run directory reads the same immutable receipt and must reproduce the same bytes. Cross-run checks use verification snapshots: a new directory holding byte copies of one run's semantic inputs plus exactly one receipt copied byte-for-byte as `timings.json`, with no copied `scores.json`, `clusters.json` or `report/`. Original run directories and receipts are never rewritten, and no test-only CLI flag is added. Two snapshots with the same receipt bytes must give byte-identical `scores.json` and report output, with the receipt sha, p95 state and veto fields compared as they are, never masked or stripped. Regression: a snapshot whose receipt differs only in p95 ms values must change the p95 guardrail's `timings_sha256`, and where the new value crosses the sealed p95 budget it must also change the p95 state and the verdict path. This uses a synthetic fixture decision with fixed literals and a synthetic p95 rule; the real budget stays unset until AE-12 preregisters it. Semantic `created_at` selects `seal.sealed_at`, else `ratification.ratified_at`, else an explicit `--created-at` or `run_frame(created_at=...)` literal. Seal and ratification may differ; only a supplied explicit literal must match the highest-priority derived value as a parsed instant. Missing/invalid values or conflicting explicit literals raise `FrameContractError` (MCP 16773). Semantic writers never read the wall clock; actual attempt/private consumption timestamps use separate non-replayable receipt boundaries. Implementation tests pass fixed literals. A warm-cache run gives identical searches, ledger and per-face outcomes to the cold run; its timings are a separate receipt, so its scores and report are compared only on a snapshot with the same receipt. Identical inputs run twice (cold runs, real data, one leg) give identical per-face outcomes and Δ = 0 on searches and ledger; the verdict is `inconclusive` unless the p95 state is `fail` (`guardrail_vetoed`). A changed p95 state is an assessment result, not a replay defect. Same-receipt replay (one pinned `timings.json`) and fresh physical timing (a new receipt) are separate tests; fresh timing bytes are never compared with pinned replay bytes. | FLOW-18, PROV-01 |
| AE-8 | Cache invalidation | Changing weights sha, preprocessing parameters, OpenCV or ORT version gives a cache miss and a new leg id. Cross-version compare refuses. | PROV-01 |
| AE-9 | Refusal suite | Each refusal raises its named error and returns no numbers: cross-space compare, cross-runtime compare, sealed-frame read without an unspent token for that run, a second unseal of a frame under any decision sha, τ fit on a test fold (`CalibrationLeakError`), an undeclared compare field difference, unratified point used as a verdict, detector-dependent FPIR denominator, Ward/median/centroid linkage on cosine, projection coordinates feeding a metric (metrics byte-identical across projection parameters), image-bearing output outside `benchmarks/private/`; an H2 leg the manifest does not name (`UndeclaredH2LegError`); τ from an empty calibration pool (`TauInfeasibleError`). Also refused (MCP 16810): `build_nonmated_pool` or `build_frame` called without `enrolled_identity_ids` (call-signature refusal, Python `TypeError`; `frozenset()` is the valid declared empty gallery); `score_run` called with positional `decision` or `pair_scores` (`TypeError`); a top-k gallery identity with missing or contradictory fold provenance (`CalibrationLeakError`); `score_run` on a run whose manifest lacks `gallery_membership` (`FrameContractError`, before any outcome is read). Also refused: `build_nonmated_pool` with `exhaustive=False` or malformed component or fold coverage (`FrameContractError`); `run_frame` with missing/invalid timestamp inputs or a conflicting explicit `created_at` (`FrameContractError`, MCP 16773); `require_frame_read_allowed` without its required keyword context (call-signature refusal), with a missing/spent/mismatched token or failed spending/recording (`SealedFrameReadError`), or with malformed `consumed_at` or an open frame (`FrameContractError`). No parallel shared error class is added. First/second and concurrent sealed-read checks retain exact binding, per-frame `O_EXCL` spending and the returned consumed `UnsealToken`. The verdict cases return `inconclusive` with the named reason and name no winner: a superior or non-inferior verdict attempted with n_nonmated_eff < 3/FPIR (`primary_fpir_unresolvable`); fewer than 50 independent PSUs on the frame (`insufficient_independent_psus`, checked before FPIR eligibility and intervals); a null or unscored veto guardrail (`required_guardrail_unscored`); `non_inferior` on a non-confirmatory frame (`non_confirmatory_frame`). | EMB-01, EVAL-07, VIZ-18 |
| AE-10 | Privacy | The branch diff contains no image bytes or data URIs and nothing under `benchmarks/private/`; the VM lane checks this. The coordinator runs a read-only static privacy scan on the laptop against the private alias map and records the hit count, scanned/run revision `code_sha`, scanner identity/digest and report digest. `code_sha` must match the scanned revision and the run revision; scanner/report content digests need not equal a git commit SHA. This laptop scan is the explicit VM-only eval exception (Constraints). It records the scanned code SHA, scanner digest and report digest. The alias map never leaves the laptop, and product tests and models stay on the VM. A missing laptop result stays pending; a VM substitute never passes it. | Repository privacy rule (no canon row; procedure in `scripts/privacy/README.md`) |
| AE-11 | Report task eval | Given only the HTML, the operator (or a reviewer agent) answers six questions correctly within 5 minutes: which leg wins at the primary point and whether it is conclusive; the frame's admissibility; the worst pair cell; the dominant failure stage; whether FPIR 0.001 is resolvable; whether runs A and B are comparable. All screens work keyboard-only, in light and dark, with glyph plus colour, and with no network requests. Actual S5 and S7 keyboard tests are required (`test_eval_harness_firbench_report_interactions.py` and `test_eval_harness_fir_occ_label_queue_interaction.py`); a markup check does not count. WRIT-81 applies only once the executive-summary prose is rendered and inspected (UI policy). | INT-22, VIZ-23, VIZ-32 |
| AE-12 | Bounded tracer and budget | After the actual S3 core/file-IO/default-wire join and required lanes land, one three-leg run on a 20-image diagnostic subset completes on the VM with every GT face in exactly one ledger state, before claiming completion. S4 may start after verified S1/S2; AE-12 does not block that start. Cold and warm times are recorded in `timings.json`. Before W5 budgets are set, a warm budget is preregistered from this measurement on the VM, and the warm rerun passes if it meets that budget. Real AE-12 is still outstanding; a simulated, fixture or fake trial never substitutes for it. | PROD-31 (release-manifest rule ID only; see canon key) |

AE-2 to AE-4 use the S9 simulator. Its generator parameters (ICC, PSU size distribution, per-leg error rates, planted effects) live in a committed fixture, and the same seeds reproduce the same table.

## S9 acceptance contract (revision v6, pre-outcome)

This is the frozen pre-outcome contract for the S9 simulator and acceptance runner. It resolves the open implementation choices in the S9 brief ([firbench-1/S9-acceptance.md](firbench-1/S9-acceptance.md)). Where the brief names one owner with three paths, this section governs. It is declared project policy under the canon-first delegation. It is not a canon constant, not a measured ICC, not a ratification, and not a simulated pass. Canon basis: [EXP-12] with [EXP-24] (power and interval on the effect; no exemption), [EXP-13] (A/A before A/B), [EXP-23] (pseudoreplication), [AUDIT-11] (design effect) and CARD-27 (sealed margins and design-effect sizing; supplement SHA-256 `186c94c2…`). The reviewed numerical pass rules stay exactly as written.

### Status and launch gate

- The current S9 implementation is not accepted. Nothing here claims an S9 result.
- S6b must be merged into `feature/firbench-1` before either S9 owner starts. The `mk/evals.mk` writers run in order: S6a, then S6b, then S9-checks.
- Owners are independent. Each uses an isolated native checkout and basetemp, and each checkout runs one test process at a time, because fixtures write under `benchmarks/private/`.
  - **S9-simulator**: `scripts/eval_harness/firbench_selftest.py` and `scene/tests/fixtures/firbench_sim_v1.json`.
  - **S9-checks**: `scene/tests/test_eval_harness_firbench_acceptance.py` and the `fir-bench-acceptance` target in `mk/evals.mk`.
  - **S9-comparator-perf** (an independent first-Haiku owner): the actual existing comparator and its parity tests (see Coverage and comparator performance). Its owned paths are declared in its own dispatch before it starts.
- Tests may be RED until the other owner's actual producer exists. A fake substitute for the simulator, the S0 gate, the S3 classifier, `decide()` or the bootstrap is never allowed. Temporary RED test files on the VM are allowed for the simulator owner's TDD. No unowned tracked path is added.
- Actual sources and fixtures are exchanged before the joined gate.

### Frozen public API

- `firbench_selftest.SimulationParams`: a frozen dataclass with `decision: DecisionManifest`, `fixture: Mapping[str, Any]`, `suite: str = 'null'` and `icc: float = 0.10`. Independent designs use `dataclasses.replace(params, suite=..., icc=...)`. Every public suite revalidates its parameters, so mutated or hand-built invalid values are rejected. No module-level policy globals.
- `load_params(path, *, decision) -> SimulationParams`: strict unknown-key rejection; schema `firbench-simulator/v1`; complete keys and values; exact `p_d` match with `DecisionManifest.p_d`; manifest policy; supported suite and ICC. The fixture's nested layout is documented by its author; callers depend only on the schema and the acceptance report.
- `simulate(params, *, seed) -> tuple[firbench_frames.Frame, tuple[SearchRecord, ...], tuple[SearchRecord, ...]]`: a paired control packet and planted packet. Each contains all three native `LegKind` values, explicit attribution rows when the scenario needs them, and every mated GT face, including upstream misses. They are real immutable record types consumed by S3. No model inference and no real pixels. A null packet has equal marginal laws, not forced equal observations across legs.
- Suites: `run_null_suite`, `run_selection_control`, `run_coverage_suite`, `run_power_suite`, `run_noninferiority_suite`, `run_mde_suite`, `run_floor_suite`, `run_stage_suite`. Each takes `(params, *, replicates: int, seed: int)` and returns JSON-serializable `{'semantic': ROW, 'timing': {'seconds': number}}`. Cell-only planting is part of `run_power_suite`. R = 1 or another small count is a software check with `full_acceptance_evidence = false`.
- `ROW` keys: `suite`, `icc`, `replicates_requested`, `replicates_completed`, `n_boot`, `seed`, `full_acceptance_evidence`, `design`, `metrics`, `passed`. `design` holds mated `raw_n`, `n_psu`, `size_counts`, `sum_squared_sizes`, `size_weighted_mean`, `deff` and `attained_n_eff`. Image and nonmated source-unit sizing are named separately. Multi-design suites label each branch's own design. Per-cell design carries its own floor, size and n_eff; no cell is claimed to have 115.
- `metrics` keys: `null.h1_superior_count` and `rate`; `null.h2_boundary_reject_count` and `rate` (meaningful 400 branch); `selection.h2_postselection_reject_count` and `rate`; `coverage.psu_coverage_count` and `rate`, and `image_coverage_count` and `rate`; `power.h1_detect_count` and `rate`, and `cell_only` (`clear_mask` and `clear_clear` counts and rates, with exact planted and observed contrasts); `noninferiority.equal_reject_count` and `rate`, `boundary_reject_count` and `rate`, and `spanning_noninferior_count`; `mde.refusal_count` and `noninferior_count`; `floor.below_floor_reason`, `below_floor_interval_count`, `at_floor_passed` and `cell_below_floor_scored`; `stage.control` and `planted` missed and embedded-wrong counts and rates, exact `drop_count`, and `native_attribution_gaps`. Also Monte Carlo standard errors, theoretical versus empirical discordance and ICC, and failure details.
- `acceptance_report(results) -> {'semantic': {...}, 'timing': {...}}`: the semantic part has schema `firbench-acceptance/v1`, `rows`, `evals`, `full_acceptance_evidence`, and which supplied suites actually ran. It is stable JSON for the same fixture, manifest and seed; timing is excluded from identity. AE-10 and the real-data AE-5, AE-6 and AE-12 stay pending unless separately supplied and verified. A subset or small-R run never marks full acceptance passed, and "not run" never becomes a pass.
- CLI: `python -m scripts.eval_harness.firbench_selftest --params PATH --decision PATH --out PRIVATE_DIR [--replicates INT] [--seed INT] [--suites null,selection,coverage,power,noninferiority,mde,floor,stage]`. Defaults are the fixture's R = 2000 and the master seed below. Full defaults run every required case at ICC 0.05, 0.10 and 0.20 for null, coverage and power. The 0.10 rows gate; 0.05 and 0.20 are report-only, and a failing sensitivity row is written as a finding. `--suites` supports independent remote shards with separate output directories and no concurrent tests in one checkout. The CLI writes only below canonical `benchmarks/private/`, never changes the decision, fixture or real inputs, and never returns a full-success claim for incomplete or failed evidence.
- `make fir-bench-acceptance` invokes this CLI and the actual AE-1 and AE-6 to AE-9 fixture modules. Fixture checks are separate from unsupported historical or real-data claims.

### Predeclared generator

- **Seeds.** Master seed `2208172209` is the first 32 bits, big-endian, of SHA-256 of `FIRBENCH-1/simulator/v1` (re-derived 2026-10-15). Derived suite, ICC and replicate seeds come from a documented fixed integer registry and `SeedSequence`. Forbidden: Python `hash()`, reseeding until a pass, dropping replicates, and post-result parameter tuning. The bootstrap seed `2429382368` and `n_boot` `10000` stay manifest-owned.
- **Miss patterns.** Three-leg miss bits are ordered SFace, AuraFace, InsightFace. The eight patterns run from binary 000 to 111, with integer weights over 400 (weights are listed in that order):

  | Law | Weights (000 to 111) | Theoretical FNIR (SF, AF, IF) | Pairwise discordance (each pair) |
  | --- | --- | --- | --- |
  | null | 300, 10, 10, 20, 10, 20, 20, 10 | .15, .15, .15 | .15 |
  | H1 power / H2 equal | 285, 5, 5, 5, 25, 25, 25, 25 | .25, .15, .15 | .15 |
  | H2 boundary | 270, 0, 10, 0, 30, 20, 30, 40 | .30, .20, .15 | .15 |
  | unsealed selection control | 280, 10, 20, 10, 20, 10, 20, 30 | .20, .20, .15 | .15 |

  These sums were rechecked by hand in revision v6.
- **Dirichlet joint law.** Each PSU draws a probability vector over its positive-mass categories with `k = 1/ICC − 1`. Equivalently, `softmax(log Gamma(k·q))` gives Dirichlet probabilities. Exactly-zero `q` categories are excluded before drawing; no epsilon mass is invented. Conditional on a PSU's probabilities, its images and faces draw patterns independently. Under this law the intra-PSU correlation of each binary leg, and of every linear paired contrast, equals `1/(k+1) = ICC`. Fraction oracles prove it, and the report shows the theoretical cross-leg covariance beside the declared `p_d`. There is no Gaussian-logit claim. Each mated GT face is one face per image, and several images share a PSU, so image resampling is the pseudoreplication control.
- **Real pipeline.** The simulator uses the actual S1 PSU components and session metadata, and the actual S3 `finish_outcomes`, `paired_cluster_bootstrap` and `decide`. No statistical decision is duplicated.
- **Paired packets.** The control and planted packets share one latent Dirichlet on a declared joint control-planted categorical law whose marginals are the table rows. Two independent Gamma vectors with the same seed are not a paired experiment. For H1 power the coupling is exact and monotone: of the null masses at 000, 001, 010 and 011 (300, 10, 10 and 20), 15, 5, 5 and 15 move to 100, 101, 110 and 111 in the planted packet. Only the SFace miss bit changes, and the AuraFace and reference observations stay identical. Dirichlet aggregation keeps each packet's exact marginal law and ICC. Any other multi-arm coupling is declared in the fixture before outcomes, and the unchanged reference bit is preserved.
- **Mated and nonmated units.** The nonmated GT-face count is 0 by synthetic design. Exactly 3000 background source units come from known synthetic empty images, distributed over existing PSUs by session metadata. They add no independent unit and no detector-derived denominator, and they do not change the mated effective size. Image and nonmated M-tilde are disclosed separately. The 49- and 50-PSU floor cases keep all negatives in those same PSUs.

### Fixed integer sizes

| Suite / ICC | Size counts (size:PSUs) | raw_n | n_PSU | M-tilde | n_eff |
| --- | --- | --- | --- | --- | --- |
| power / .05 | 1:59, 7:4, 8:3, 9:3 | 138 | 69 | 5 | 115 |
| power / .10 | 1:46, 4:23 | 138 | 69 | 3 | 115 |
| power / .20 | 1:26, 2:14, 3:9, 4:20 | 161 | 69 | 3 | 115 |
| null and coverage / .05 | 1:96, 16:24 | 480 | 120 | 13 | 300 |
| null and coverage / .10 | 11:30, 15:22 | 660 | 52 | 13 | 300 |
| null and coverage / .20 | 11:37, 12:2, 13:12, 14:2, 15:27 | 1020 | 80 | 13 | 300 |
| H2 / .10 | 1:176, 16:44 | 880 | 220 | 13 | 400 |

- Arithmetic (verified 2026-10-15): `M-tilde = Σm²/Σm`, `deff = 1 + (M-tilde − 1)·ICC`, `n_eff = raw_n / deff`. Every row above reproduces its stated n_eff.
- **Power allocation.** Whole PSUs are sorted and allocated alternately: clear→mask gets 35 PSUs and clear→clear gets 34. At ICC 0.10 this reproduces 23 singletons plus 12 four-face PSUs for clear→mask, and 23 singletons plus 11 four-face PSUs for clear→clear. Other ICC allocations are frozen in the fixture before outcomes, must satisfy both cell floors, and report their actual cell n_eff.
- The sizing is arithmetic only. It supplies no coverage or power evidence.

### Decision branches and negative controls

- **H1 and overall state.** The H1 state and the overall state are both counted. Overall H2 ineligibility never drops H1 rows. The AE-2 300-design case stays, including the actual H2 MDE refusal (H2 MDE 0.0554 at n_eff 300, above δ 0.05).
- **Boundary and selection use the reviewed 400 design.** The meaningful H2 boundary and selection controls use the reviewed 400 H2 design (1:176 and 16:44 PSUs; H2 MDE 0.0480, below δ). The false-positive bound stays 0.060.
- **H2-spanning branch.** Fixed design of 880 faces over 220 PSUs. Each 16-face PSU has 2 positive contrasts, 1 negative contrast, 2 both-miss faces and 11 both-correct faces. Every singleton PSU is both-correct. Exact H2 and reference rates are .20 and .15, discordance .15 and delta .05. The actual 10000-draw 90% interval must span the margin; bounds are never fabricated.
- **H1 forcing.** Every boundary H1-forced case changes ONLY the nonselected in-house arm. If H2 is AuraFace, SFace is made all-miss. If H2 is SFace, AuraFace is made all-correct. The selected arm and the reference observations are preserved. The real `decide()` is called, H1 is asserted to pass, and no replicate is discarded.
- **Selection control (an INVALID negative control).** Selection chooses the leg with the smaller estimate before H1 forcing, and the run is labelled an invalid postselection negative control. The selected H2 leg is judged by a separately self-consistent synthetic decision. The product never allows postselection or an unknown H2 leg (`UndeclaredH2LegError`).
- **Synthetic decisions.** Synthetic-only S0 decisions are derived from the supplied statistical policy, with correct generated frame and template hashes, literal synthetic reference and timestamps, and all required real S0 validators. Margins, alpha, bootstrap, floors, `p_d` and FPIR are unchanged. A named report-only simulation-scope guardrail has a non-null declared rule, with no fabricated p95 measurement and no veto pass. The real decision manifest is never mutated or ratified. This tests the inference mechanism only. The full AE-7 and AE-9 real CLI fixtures still exercise the real receipt-dependent veto and fail-closed unscored guardrails.
- **MDE branch (MCP 16945).** `run_mde_suite` also forces H1 with the same declared mechanism, preserving equal H2 and reference observations. A finite planted H1 effect has power below 1 and sometimes stops before H2. Those replicates are never dropped, and no H2 state is fabricated. Ordinary power and noninferiority suites keep the actual H1 probability. No gate, count or seed changes.

### Stage planting

- Upstream detection drops: `floor(0.10 × n_mated)` predeclared drops, stratified between the already generated embedded-correct and embedded-wrong classes, with integer rounding disclosed. The drops are shared between the in-house native arms. Reference and latent identities stay fixed.
- The actual `finish_outcomes` and stage counts must show exactly those new missed rows. Both separable attribution arms restore baseline on the same GT IDs. InsightFace attribution stays `unavailable_fused`.
- Embedded wrong-identity rate: the control-versus-planted absolute difference is ≤ 0.05, computed with the actual paired-gap implementation where it applies. No cached outcome or interval is fabricated.
- Cell-only planting changes only the predeclared clear→mask PSUs and keeps the clear→clear control observations identical. Both cell detection rates and their contrasts are reported. Neither cell is labelled with the global 115.

### Coverage and comparator performance

- Coverage calls the actual `score_report.bootstrap_paired_delta` (`scripts/bench/score_report.py:178`) on the SAME replicate image arrays with B = 10000, next to the PSU interval at the manifest `n_boot`.
- Every full case uses all 2000 replicates and 10000 draws. Requested and completed counts, and any omitted case, are explicit. Failures become findings, never new pass limits.
- The ICC 0.3 broken-image coverage check is a separate, declared negative-control case with multiple images per PSU. It is not a gated sensitivity row.
- **Measured pre-run exception.** Before any outcome, the actual existing image comparator took 23.590922 s at 0.25 CPU for one replicate at n = 660 and B = 10000, projecting about 13.1 h for 2000 replicates at that allocation. S9-comparator-perf, an independent first-Haiku owner, implements bounded reuse of the identical `random.Random(seed).randrange(n)` draw counts for repeated calls with the same (n, B, seed) binary-mean arguments, inside the actual function, with parity tests. S9 may use that implementation only if its parity, source and memory gates pass. Every replicate still evaluates all 10000 statistics with the SAME logical draws, order, quantiles and return fields. There is no new RNG, no reduced count and no changed estimand. All other modes keep the original slow fallback. Cold draw construction and warm repeated timing are reported explicitly. This declared, measured optimization is not a silent alternate backend, a lookalike comparator, a vectorization that changes draw order, or a mocked method.

### Numeric comparison rules

- Counts are integers compared with `==`, with no tolerance.
- An analytic rate's oracle is a `fractions.Fraction`. The float must satisfy `abs(value − float(oracle)) <= 1e-12`. That is the only tolerance in the lane.
- Monte Carlo rates are never compared with a tolerance. They are judged by the bounds below. The standard error is `sqrt(p(1 − p)/R)`: at R = 2000 it is 0.00349 for p = 0.025, 0.00487 for p = 0.05 and 0.0089 for p = 0.80 (arithmetic verified 2026-10-15).
- The bound of 9 of 200 is the 95% upper quantile of Binomial(200, 0.025): P(X ≤ 8) = 0.9344 and P(X ≤ 9) = 0.9700 (verified). It is carried in the fixture.

### Pass rules (reviewed; unchanged)

| Eval | Rule |
| --- | --- |
| AE-2, step 1 | `superior` rate ≤ 0.032 at 2,000 replicates |
| AE-2, step 2 | step-2 boundary rate ≤ 0.060 at 2,000 replicates, on the 400 design |
| Selection control | `non_inferior` rate under post-run selection > 0.060; a value within the bound fails the suite |
| AE-3 | PSU-bootstrap coverage in [0.93, 0.97] |
| AE-4 | Planted Δ 0.10 at n_eff 115 detected by H1 in ≥ 0.77 of 2,000 replicates; the cell-only effect appears in its own cell and clear→clear no more often than the null rate; the stage defect appears in the `missed` count; the embedded wrong-identity difference is ≤ 0.05 absolute |
| H2 branches | (a) H2 rejects in ≥ 0.77 of replicates; (b) H2 false rejection ≤ 0.060; (c) zero `non_inferior` where the 90% interval spans δ |
| MDE refusal | at n_eff 300 and δ 0.05, every replicate gives `margin_unreachable_mde_gt_delta`; zero `non_inferior` |
| Eligibility floors | fewer than 50 distinct PSUs gives `insufficient_independent_psus` with no interval; pair cells below 30 PSUs are not scored |
| ICC sensitivity | 0.05 and 0.20 rows are reported beside the 0.10 gate and are not gated |
| AE-10 | coordinator-recorded on the laptop; not run by S9; pending until recorded |

### Policy, measured and unresolved (recorded explicitly)

| Item | Status | Basis |
| --- | --- | --- |
| Seeds 2406466110, 2468935812, 2429382368, 336880394 and 2208172209 | Declared policy; re-derived 2026-10-15 | First 32 bits of SHA-256 of the labelled strings |
| Planning ICC 0.10; sensitivity 0.05 and 0.20 | Design assumption; not observed | AUDIT-11; `DecisionManifest.planning_icc` |
| `p_d` 0.15; power 0.80 | Design assumption; not observed | EXP-12; `DecisionManifest.p_d` |
| Sizing and planted Δ 0.10 | Sizing and planted only; MDE is computed; no manifest field | EXP-12; scope, Power section |
| H1 margin 0; H2 margin 0.05 | Sealed in the manifest before the run | CARD-27 supplement; S0 |
| Size tables (115, 300, 400 effective searches) | Declared sizing arithmetic (verified) | n, Σm², design effect |
| Face-count M-tilde ≈ 13; image-count 12.925 | Simulator choice; historical report figure, not a measurement | S1 measures the real values |
| Dirichlet joint law and paired coupling | Declared simulator policy | AUDIT-11; EXP-23 |
| Comparator timing 23.590922 s per replicate | Measured before outcomes (one replicate, VM) | Timing record |
| Three primary weight files | Measured: located and hash-verified on the VM, 2026-10-15 | `provenance.py` lines 107, 121, 138 |
| Observed ICC; real frame, corpus and template hashes; exhaustive independent GT; admissible counts; real source and template bindings; human observation and QC; ratification; seal; budget | Unresolved evidence gates | S1, MEAS-29, S0 ratification, AE-12 |
| Real AE-12 tracer | Outstanding; a fake or simulated trial never substitutes | AE-12 |

## Lane Decomposition (all remote; none on this host)

Lane-ready briefs: [firbench-1/README.md](firbench-1/README.md). Current user override: all remote implementation lanes use Haiku xhigh first; post-gate adjudication uses `codex-remote gpt-6.1-sol` high STANDARD. These current routes supersede older implementation model pins in lane briefs; historical review and inventory pins below remain labelled historical. This table describes the project schedule, not authorization for this dispatch to launch agents or merge.

| Wave | Who / model | Output |
| --- | --- | --- |
| W0 | coordinator (done) | `make task-start TASK=FIRBENCH-1`, handoff row |
| W1 (historical review pins) | adversarial review in parallel: codex-remote gpt-6.1-sol xhigh standard + Muse muse-wonder-1.0 high, read-only on a frozen snapshot | Findings in MCP. A REVISE verdict goes to claude-remote claude-haiku-5-5 xhigh adjudication, then plan v3. |
| W2 (historical dispatch pins) | inventory: gpt-6-luna max fast. ux-map: gpt-6.1-sol xhigh standard. | Inventory: artifact pins and hashes, reused-API signatures, VM corpus location, non-mated frame count, PSU/deff estimate, dependency check. ux-map: JSON, render, critique. |
| W3 batch A | claude-remote claude-haiku-5-5 xhigh | S0 contract |
| W3 batch B | claude-remote claude-haiku-5-5 xhigh, parallel | S1, S2, S3, S6a, S7 |
| W3 batch C | claude-remote claude-haiku-5-5 xhigh | S4 is authorized after verified S1/S2, independently of AE-12; S6b follows S6a; S5 follows S4. S9 starts only after S6b is merged: S9-simulator and S9-checks are independent owners, and S9-comparator-perf (first Haiku owner) runs on the actual comparator separately. `mk/evals.mk` is edited serially: S6a, then S6b, then S9-checks. |
| Post-lane gate | coordinator, VM | After actual S3/default-wire join and required lanes: AE-12 bounded tracer and preregistered warm-budget rerun, before completion claims. |
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
- [ ] S0 decision manifest, frame registry, shared enums and errors, unseal refusal (code landed in `firbench_contract.py`; acceptance pending)
- [ ] S1 frames, PSU components, folds, non-mated source-unit inventory, deff/n_eff (code landed in `firbench_frames.py`; observed ICC and admissible counts pending S1 measurement)
- [ ] S2 in-process legs, gt_crop_redetect and cached_yunet_landmark_replay arms, fused insightface, contract-keyed cache, ledger (code landed in `firbench_legs.py`; real leg runs pending)
- [ ] S3 scoring, calibration folds, paired PSU cluster intervals, fixed-order step decision, pair cells, stage waterfall, guardrails (code landed in `firbench_score.py` and `firbench_score_io.py`; real AE-12 join pending)
- [ ] S6a CLI `run` and `score` (code landed in `firbench_cli.py`)
- [ ] S7 label queue generator and importer, packaged label evidence (code landed in `fir_occ_labels.py` and `fir_occ_label_queue.py`; real evidence and the MEAS-29 observation pending)
- [ ] S4 cluster diagnostics (start authorized after verified S1/S2; code landed in `firbench_clusters.py` and `firbench_cluster_io.py`)
- [ ] S5 private static report S1–S8 (code landed in `firbench_report.py`; light and dark, keyboard and no-network checks per AE-11)
- [ ] S6b CLI `report`, `compare`, `unseal` (code landed in `firbench_cli.py`)
- [ ] S9 simulator, S9-checks and S9-comparator-perf, and `fir-bench-acceptance` (not landed; launch gate in the S9 contract)
- [ ] AE-12 bounded tracer on the VM after actual S3/default-wire join and required lanes; warm budget preregistered before W5
- [ ] AE-1 to AE-12 green at the merge-candidate HEAD
- [ ] W5 first VM run report (development/diagnostic tier only)

## Success Criteria

- AE-1 to AE-12 pass on the VM at the merged HEAD, each recorded as a `test_result` tied to the SHA.
- One command reproduces a run's searches and ledger from manifest hashes; `scores.json` and the report reproduce byte-for-byte under the same pinned timings receipt (AE-7). Every GT face ends in exactly one ledger state.
- The verdict line can say "inconclusive", and does so whenever the interval spans the boundary.
- No number appears without its frame admissibility, n_eff and interval.
- No image-bearing artifact is tracked by git.
- The S9 acceptance report is not claimed until S9 lands and its full-replicate runs complete. A small-R or subset run is never full acceptance evidence.
