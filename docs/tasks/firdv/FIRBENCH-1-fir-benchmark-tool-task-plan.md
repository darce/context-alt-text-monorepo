# Task Plan

> **Metadata**
>
> - **Date**: 2026-10-14
> - **Author**: Claude Opus 5.5 (claude-opus-5-5)
> - **Project**: prototype-description-service eval harness (related epic: [E24 FIRDV](../../epics/v0.5.0/fir-development-and-measurement-epic.md))
> - **Task ID**: `FIRBENCH-1`
> - **Target Branch**: `feature/firbench-1`
> - **Review Coverage Target**: 2
> - **Status**: draft v2, out for parallel adversarial review (codex-remote gpt-6.1-sol xhigh standard + Muse muse-wonder-1.0 high, both on the VM)
>
> Review counts and findings live in the handoff DB, not in this file. Canon citations are Canon v0.26.2 row IDs.

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
- Image-bearing outputs (crops, overlays, label-queue HTML, notebooks) go to ignored `benchmarks/private/`. `benchmarks/reports/*.html` is already ignored. Committed artifacts are code, schemas, synthetic fixtures, manifests without pixels, and this plan.
- InsightFace/buffalo_l: internal bench reference only, never user-facing, never training data.
- One embedding space per comparison: SFace-128, AuraFace-512 and InsightFace-512 vectors are never compared across legs (EMB-01). A preprocessing or runtime change invalidates the cache (IDX-02). The OpenCV/ORT version is part of the leg identity, and cross-version comparisons are refused (PROV-01, CARD-29).
- Greenfield: no data migrations. Legacy artifacts stay readable through explicit version adapters.

## Scope and binding parameters

Scope, operator Q&A answers (Golden-150, design changes, notebooks, clustering, D2/D3, occlusion, definitions) live in [FIRBENCH-1-scope.md](FIRBENCH-1-scope.md). Lane-ready briefs live in [firbench-1/](firbench-1/README.md).

Binding defaults the S0 decision manifest must carry (values live in the manifest, never in code [rg-009]):

| Parameter | Value |
| --- | --- |
| Primary estimand | paired ΔFNIR (SFace − AuraFace) at FPIR 0.01, end to end, fixed non-mated source-unit denominator |
| Secondary points | FPIR 0.05 and 0.001, each "unresolvable" until n_nonmated_eff ≥ 3/FPIR |
| Primary resolvability | The primary FPIR point is unresolvable until n_nonmated_eff ≥ 3/FPIR (300 at 0.01). An unresolvable primary point makes the verdict `inconclusive` (`primary_fpir_unresolvable`), with no winner named. |
| Interval | paired cluster percentile bootstrap, PSU = image–identity component. Two-sided 95% for step 1 (H1) and two-sided 90% for step 2 (H2), from one-sided levels 0.025 and 0.05 |
| Family α | 0.05 one-sided, fixed-order Holm: H1 (AuraFace superior to SFace) first; H2 (the in-house leg named in the sealed manifest non-inferior to InsightFace, δ = 0.05) only if H1 is rejected. Decisions use intervals only; no p-values. |
| Guardrails | Veto: per-cohort FPIR, false names per 1k mentions, worst pair-cell FNIR floor, p95 ms/face. Report-only until wired: cost per accepted description. Each role is sealed in the manifest. A null or unscored veto gives `inconclusive` (`required_guardrail_unscored`). |
| Threshold τ | identity-disjoint calibration folds, pooled, frozen before any test read. τ is the smallest threshold whose pooled calibration FPI (a count of non-mated source units with a false accept) is ≤ ⌊fpir_target × N⌋, N being the pooled calibration source-unit count (S3 Build 3). |
| Verdict states | superior · non-inferior · inconclusive · guardrail-vetoed · unratified |

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
| S0 contract | `firbench_contract.py`, `benchmarks/manifests/fir-bench-decision-v1.json` | Decision-manifest schema: estimand, δ, α split, interval method, guardrails, harm direction, disconfirmers and their dates, seal hash. Frame registry with admissibility. Null means unratified. Frame-read tokens live in a local-only unseal ledger; a sealed frame is read once per token. Unseal refusal. |
| S1 frames | `firbench_frames.py` | Load population queues. Build PSU components (union-find over image–identity, duplicate, session and synthetic-sibling edges), then identity-disjoint folds over whole components. Build the immutable non-mated source-unit inventory (non-mated GT faces plus one background unit per frame image; never detector-derived). Estimate deff and n_eff, emit admissibility. |
| S2 legs | `firbench_legs.py` | In-process legs `sface` and `auraface` built from pinned manifests by an offline factory (not the shared runtime), and `insightface` (judge, fused: no separate alignment stage). Arms `native`, `gt_crop_redetect` (GT box crop re-detection) and `cached_yunet_landmark_replay` (cached YuNet landmarks; no human landmarks exist). Attribution arms apply to `sface` and `auraface` only. Per-leg cache keyed by the model-manifest fingerprint (weights sha, preprocessing, OpenCV/ORT). Raw detections are kept, and ledger rows are written per GT face. |
| S3 score | `firbench_score.py` | FNIR-vs-FPIR curves on the fixed non-mated source-unit denominator, calibration-fold τ (smallest feasible on the pooled calibration pool of source units; calibration-leak refusal), paired PSU cluster intervals, fixed-order step decision on intervals only, primary-FPIR and MDE eligibility, pair cells, stage waterfall, guardrails (veto or report-only), versioned boundary semantics |
| S4 clusters | `firbench_clusters.py` | Cluster metrics, mutual-kNN, dendrogram at τ, PCA spectra, UMAP diagnostic coordinates and companions |
| S5 report | `firbench_report.py` | Static HTML (light/dark, no network, keyboard accessible, glyph plus colour) plus JSON/CSV, with a private-path guard |
| S6a CLI | `firbench_cli.py`, `mk/evals.mk` | `run` and `score` (batch B, needed by the AE-12 tracer) |
| S6b CLI | same files, after S6a merges | `report`, `compare`, `unseal` |
| S7 label queue | `benchmarks/tools/fir_occ_label_queue.py` (allowlisted), `eval_harness/fir_occ_labels.py` | Generate the private single-file HTML queue. Import and validate exports into the fir-occ-v1 face-instance schema. Union-delta mode for T-14. |
| S8 ux-map | `benchmarks/ux-maps/fir-bench.uxmap.json`, `.md`, `.gitignore` | Screen/zone/state/flow inventory, rendered with `UX_MAPS_DIR=benchmarks/ux-maps python3 apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.py fir-bench`, then critique |
| S9 acceptance | `firbench_selftest.py`, `mk/evals.mk` target `fir-bench-acceptance` | Seeded clustered simulator (PSU sizes, ICC, per-leg error rates, planted effects by cell and stage), A/A and planted-effect Monte Carlo, determinism and replay checks. Runs the completion evals below. |

Tests: `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_*.py`, synthetic vectors and identifiers only.

## Screens (ux-map seeds; values are placeholders)

```
S1 VERDICT ─ run r-0007 · frame fir-occ-v1/dev [development] · OpenCV 5.0.0 · ORT 1.28 · git a1b2c3d
 Question  AuraFace-512 vs SFace-128 · FNIR @ FPIR 0.01 · end-to-end (misses count)
 Answer    Δ(SF−AF) +#.### [−#.###, +#.###] paired · PSU image–identity · n_eff ### (deff #.##)
           → INCONCLUSIVE: interval spans 0 · H2 not evaluated                              (WRIT-81)
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
S7 CLUSTERS ─ per leg, own space only · τ-cut · noise policy: singletons stay unassigned
                  pair P/R     B³ P/R      merges  frags  unknown-absorbed  order-stab
   sface-128      .##/.##      .##/.##     ##      ##     ##                .##
   auraface-512   .##/.##      .##/.##     ##      ##     ##                .##
 Dendrogram (average, cosine) cut at τ .41 · cophenetic r .##       PCA spectrum ▇▅▃▂▁…
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
L1 OCCLUSION LABEL QUEUE (private single-file HTML) ─ item 37/150 · blind repeat ○ · gold ○
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

- Per-lane VM test command: `uv run --directory apps/prototype-description-service --locked --extra dev pytest scene/tests/test_eval_harness_firbench_<slice>.py -q`.
- Every slice starts RED: tests committed and failing for the stated reason before any implementation.
- `make lint-task-plans` passes. The renderer `--check` passes for `fir-bench`. Critique has no high findings.

## Open questions

- Minimum independent PSUs in a frame before H1 or H2 can reject, and the list of annotations a frame must carry before a verdict is eligible. Neither has a value yet. The manifest needs both before seal (S3 Build 6, eligibility).
- Whether a duplicate detection that overlaps a mated GT face (not its one-to-one match) should open its own non-mated source unit. Until decided, its above-threshold names count only as additional spurious names (S3 Build 2).

## Completion evals (definition of done for the tool)

The tool is done when it is trustworthy, not when it has picked a model. A benchmark that has never been shown to detect a known effect, or to stay quiet on a null, cannot guide development (EXP-13, EXP-06). Each eval below runs on the VM at the merge-candidate HEAD and is recorded as a `test_result` tied to that SHA. `make fir-bench-acceptance` runs all simulated and fixture evals; the real-data evals run through the CLI.

| ID | Eval | Pass rule | Canon |
| --- | --- | --- | --- |
| AE-1 | Known answers | Synthetic fixtures with analytic FNIR, FPIR, FPI, B-cubed and ledger counts match exactly (rational arithmetic, no tolerance) | EVAL-18 |
| AE-2 | A/A null (simulated Type-I behaviour) | Simulated only: 2,000 seeded null replicates at ICC 0.10, face-count size-weighted PSU size ≈ 13, n_eff ≈ 300. Step 1: the full decision procedure says "superior" in ≤ 0.032 of replicates (nominal one-sided 0.025 + 2 MC SE, SE = 0.00349). Step 2: at the boundary Δ = δ, with H1 forced to pass, step 2 rejects in ≤ 0.060 of replicates (nominal 0.05 + 2 MC SE, SE = 0.00487). | EXP-13 |
| AE-3 | Interval coverage | In 2,000 planted-effect replicates the 95% paired cluster interval covers the true Δ in 93–97% of replicates. The report also shows the image-level bootstrap's coverage on the same replicates, so the PSU correction is visible. | AUDIT-11, EXP-23 |
| AE-4 | Planted-effect sensitivity | A planted ΔFNIR 0.10 at n_eff 115 (the step-1 requirement for Δ 0.10) is detected by H1 in ≥ 0.77 of 2,000 replicates (0.80 power minus 3 SE; SE = 0.0089). An effect planted only in the clear→mask cell appears in that cell and not in clear→clear. A planted 10% detection drop appears in the "missed" stage count, and the wrong-identity rate among embedded faces changes by at most 0.05 (absolute) between planted and control runs. | EXP-12, EVAL-16 |
| AE-5 | Real-data canary | On the Golden-150 diagnostic frame, using the 54-entry draft roster (`golden150-draft-20260723.json`, not the 17-identity evidence set) as the gallery, a canary copy of the AuraFace leg relabels a declared set of k = 5 identities (⌊0.10 × 54⌋) by seeded derangement. The run reports the measured FNIR and false-name effect with its paired CI; significance is not guaranteed. The RED pass runs on a powered synthetic fixture whose changed search ids and effect are precomputed, and the canary must detect that planted effect. Legs tagged canary are refused in sealed runs. | EXP-06 |
| AE-6 | Legacy parity | In `legacy_v1` boundary mode the bench reproduces the pinned historical counts exactly (the W2 inventory pins the artifacts, including `face_unknown_rejection` 204/207). The `v2` mode lists every item whose outcome changes. | CAL-02 |
| AE-7 | Determinism and replay | Two cold runs from pinned inputs give byte-identical semantic outputs (searches, ledger, scores JSON, and the report with timing sections excluded); `timings.json` is excluded. Seeds come from the manifest, timestamps from the manifest, iteration is sorted. A warm-cache run gives identical semantic outputs and per-face outcomes to the cold run; its timings are a separate receipt. Identical inputs run twice give identical per-face outcomes, Δ = 0, and verdict "inconclusive" (real data, one leg, cold runs). | FLOW-18, PROV-01 |
| AE-8 | Cache invalidation | Changing weights sha, preprocessing parameters, OpenCV or ORT version gives a cache miss and a new leg id. Cross-version compare refuses. | IDX-02, CARD-29 |
| AE-9 | Refusal suite | Each refusal raises its named error and returns no numbers: cross-space compare, cross-runtime compare, sealed-frame read without an unspent token for that run, a second unseal of a frame under any decision sha, τ fit on a test fold (`CalibrationLeakError`), an undeclared compare field difference, unratified point used as a verdict, detector-dependent FPIR denominator, Ward/median/centroid linkage on cosine, projection coordinates feeding a metric (metrics byte-identical across projection parameters), image-bearing output outside `benchmarks/private/`; an H2 leg the manifest does not name (`UndeclaredH2LegError`); τ from an empty calibration pool (`TauInfeasibleError`). The verdict cases return `inconclusive` with the named reason and name no winner: a superior or non-inferior verdict attempted with n_nonmated_eff < 3/FPIR (`primary_fpir_unresolvable`); a null or unscored veto guardrail (`required_guardrail_unscored`); `non_inferior` on a non-confirmatory frame (`non_confirmatory_frame`). | EMB-01, EVAL-07, VIZ-18 |
| AE-10 | Privacy | The branch diff contains no image bytes or data URIs, nothing under `benchmarks/private/`, and (coordinator-run on the laptop, never shipped) zero hits against the private alias map. | PROV-01 |
| AE-11 | Report task eval | Given only the HTML, the operator (or a reviewer agent) answers six questions correctly within 5 minutes: which leg wins at the primary point and whether it is conclusive; the frame's admissibility; the worst pair cell; the dominant failure stage; whether FPIR 0.001 is resolvable; whether runs A and B are comparable. All screens work keyboard-only, in light and dark, with glyph plus colour, and with no network requests. | INT-22, VIZ-32, WRIT-81 |
| AE-12 | Early tracer and budget | After S0–S3 land, one three-leg run on a 20-image diagnostic subset completes on the VM with every GT face in exactly one ledger state, before S4–S6b start. Cold and warm times are recorded in `timings.json`. Before W5 budgets are set, a warm budget is preregistered from this measurement on the VM, and the warm rerun passes if it meets that budget. | PROD-31 |

AE-2 to AE-4 use the S9 simulator. Its generator parameters (ICC, PSU size distribution, per-leg error rates, planted effects) live in a committed fixture, and the same seeds reproduce the same table.

## Lane Decomposition (all remote; none on this host)

Lane-ready briefs: [firbench-1/README.md](firbench-1/README.md).

| Wave | Who / model | Output |
| --- | --- | --- |
| W0 | coordinator (done) | `make task-start TASK=FIRBENCH-1`, handoff row |
| W1 | adversarial review in parallel: codex-remote gpt-6.1-sol xhigh standard + Muse muse-wonder-1.0 high, read-only on a frozen snapshot | Findings in MCP. A REVISE verdict goes to claude-remote claude-haiku-5-5 xhigh adjudication, then plan v3. |
| W2 | inventory: gpt-6-luna max fast. ux-map: gpt-6.1-sol xhigh standard. | Inventory: artifact pins and hashes, reused-API signatures, VM corpus location, non-mated frame count, PSU/deff estimate, dependency check. ux-map: JSON, render, critique. |
| W3 batch A | gpt-6.1-sol xhigh standard | S0 contract |
| W3 batch B | gpt-6.1-sol xhigh standard, parallel | S1, S2, S3, S6a, S7 |
| Gate | coordinator, VM | AE-12 tracer run |
| W3 batch C | gpt-6.1-sol xhigh standard, parallel | S4, S5, S6b, S9 |
| W4 | one harmonizing review (sol xhigh) and one fix wave | AE-1 to AE-12 green, merge on green |
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
- One command reproduces a run from manifest hashes. Every GT face ends in exactly one ledger state.
- The verdict line can say "inconclusive", and does so whenever the interval spans the boundary.
- No number appears without its frame admissibility, n_eff and interval.
- No image-bearing artifact is tracked by git.
