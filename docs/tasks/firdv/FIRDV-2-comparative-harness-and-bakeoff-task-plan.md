# Task Plan

> **Metadata**
>
> - **Date**: 2026-09-19
> - **Author**: Codex
> - **Status**: draft; instruments and live experiments pending
> - **Owning Epic**: [E24](../../epics/v0.5.0/fir-development-and-measurement-epic.md)
> - **Epic Short ID**: FIRDV
> - **Task ID**: `FIRDV-2`
> - **Target Branch**: `feature/firdv-2`
> - **Review Coverage Target**: 2

## Objective

Expand the existing FIR-16/VLM-6 instruments into reproducible recognition and description comparisons, including detector-only occlusion evaluation, cluster visualizations and measured quality/cost. The first quality experiment measures face detection independently; downstream embedding or clustering scores cannot stand in for it. Use the [new development installation](FIRDV-1-isolated-development-install-task-plan.md) for live runs. Contract and offline report work may begin before deployment.

This is a parent task plan with bounded slices, not a single junior dispatch. Use `codex-remote`, `gpt-5.6-luna`, effort `max`, tests-only RED followed by separately reviewed implementation for each slice. Do not hand a junior the whole harness as one assignment.

## Context and existing seams

Read the [scope](../../scopes/fir-development-and-measurement-wave.md), [current-state assessment](../../assessments/current/fir-development-wave-assessment-2026-09-19.md), [corpus/metrics assessment](../../assessments/current/fir-occlusion-corpus-and-metrics-2026-09-19.md), [FIR-16 plan](../fir/FIR-16-open-set-head-to-head-task-plan.md), FIR-13/15/17 and VLM-6 prior work. Handoff semantic decisions and current source override stale implementation status in old prose. Claim upstream-owned slices before modifying shared modules.

Code remains under `apps/prototype-description-service/scripts/eval_harness/` and `scripts/bench/`; use `bakeoff.py`, `fir_bakeoff_run.py`, `open_set_identification.py`, `gate_contract.py`, `caption_metrics.py`, `placement_metrics.py`, `report.py`, existing run walkers/rescoring, `audit_sampling.py` and `pilot_draw.py`. Atlas model/repository code is a storage/provenance primitive, not evidence that the comparison UI exists. Reuse `gpu_cost_report.py` and [burst observability debt](../tech-debt/gpu-burst-cost-observability.md); do not build another generic benchmark platform.

Checked-in code, schemas, sanitized fixtures and plans are separate from private media and runs. Current `.gitignore` allowlists benchmark plans/manifests/reports, so place private allocations and image-bearing artifacts under ignored `benchmarks/private/` and verify output paths. No hosted vision APIs in this phase.

## S1 — immutable run contract and complete outcomes

Define one versioned manifest consumed by recognition, VLM and report adapters. Preserve existing artifacts through explicit version adapters; reject unknown/incompatible versions. Proposed additional modules are `eval_harness/experiment_manifest.py` and `eval_harness/outcome_ledger.py`, only if equivalent seams do not already exist.

| Manifest section | Required fields / semantics |
| --- | --- |
| Identity | Schema version, immutable run ID, logical comparison/pair ID, parent run, created time, status and producer/scorer git SHAs |
| Inputs | Source content hashes, corpus and annotation revisions/hashes, rubric version, sampling frame/weights, expected image/face/probe IDs, split/group assignments, consent/access class |
| Recognition | Profile, detector/embedder/preprocessing/weight hashes, dimensionality, normalization/distance, runtime/OpenCV/provider versions, gallery snapshot/hash and size, thresholds/calibration split/hash/decision ID, clustering config/hash and seed |
| Description | Model repository and immutable revision/hash, license record, quantization/dtype, serving/runtime version, prompt/template/identity-evidence hashes, image preprocessing/resolution, decoding controls, token ceilings, seed where supported |
| Execution | Endpoint/environment identifier without secrets, tenant/run workspace, hardware/driver, concurrency, batch/cache/cold-or-warm state, request/attempt/startup IDs, stage timestamps, stop cause and retries |
| Policy | Allowed candidate grid, primary metrics and margins, error/false-name budgets, planned independent units, evidence tier, run lease and spending ceiling; null means unratified, not zero |
| Output | Artifact hashes, expected/completed/failed/unknown/unlabeled counts, metric/scorer version, validation result, missing-evidence reasons, costs and rate provenance |

The expected-unit ledger is created **before requests**, and joins outputs back by stable IDs. Every image and eligible GT face/probe ends as completed, failed, missing, ignored-by-rubric or unscorable-with-reason. Attempt logs are append-only. Resume reuses the same logical observation only when inputs/config match; a changed model/annotation/config makes a new run. An interrupted run remains partial, never an apparently smaller successful run. Non-finite scores are invalid, not a low score.

First RED dispatch covers schema/version/hash mismatches, retry idempotency, changed config, omitted response, duplicated observation, empty strata, wrong-face occlusion tags, artifact redaction and cross-tenant reference refusal. Use deterministic tiny synthetic identifiers and numeric vectors; no real personal media. Proposed test modules: `scene/tests/test_eval_harness_experiment_manifest.py` and `scene/tests/test_eval_harness_outcome_ledger.py`.

## S2 — corpus successor and annotation workflow

Implement the [corpus assessment's](../../assessments/current/fir-occlusion-corpus-and-metrics-2026-09-19.md) schema/validator and annotation packet extensions, reusing FIR-11 and DESCQUAL-2. Golden-150 is unchanged. Version the successor with a content hash and selection lineage; keep deployment-probability and enriched-challenge arms separate. Sampling units and weights must survive report generation.

Attach mask/sunglasses/hand/hair/object/mixed occlusion to **face instances**, including visible regions, partial/out-of-frame vs true obstruction, landmarks/visibility when annotated, identity confidence, adjudication status and “cannot determine.” Image-level retrieval tags are candidate aids only. Human auditors inspect original pixels and negative/no-proposal samples independently of detector output. Synthetic variants inherit their parent's group and are a separate robustness arm.

Keep development, calibration and test groups disjoint by identity/session/near-duplicate components as appropriate to the declared protocol. Within an evaluation split, mated enrollment and probes can share identity but must use separate captures; never put the same capture in gallery and probe. Previously inspected legacy images remain diagnostic data. Acquire independent groups for a genuine sealed test. Report actual annotation coverage: the 646-item inventory is not a fact-annotated golden corpus.

RED cases include wearer mismatch in two-person images, duplicate capture leakage, false-negative detector samples, unknown/fully hidden face distinction, missing annotation, unreviewed auto labels, no-face images, sampling weights, synthetic siblings and all requested occlusion pair cells. Publish selection/annotation packets and validation coverage, not fabricated gold labels. Human completion is a later evidence dependency.

## S3 — score export and normalized metric adapters

Complete FIR-16's real similarity export chain before claiming an open-set comparison. Current `MediaIdentityService.list_by_media_ids` emits detector `confidence`; its debug `match_similarity` is null. Do not use detector confidence as identity similarity. Preserve the pre-threshold best match score and candidate ID, gallery snapshot, rejection reason and model provenance through the actual remote client's consumption path. Updating only the tenant export serializer does not update that path.

Current `CentroidDiscovery._find_best_centroid_match` initializes best similarity to zero, so all-negative galleries and empty galleries are conflated. Follow FIR-16 ownership for the fix; tests must distinguish a valid negative best score, no gallery, rejected candidate and missing measurement. No downstream adapter may invent a score.

Use the existing `GateContract` and open-set primitives; extend reporting through versioned adapters. Freeze each model's own threshold on calibration. Test sweeps may be diagnostic curves but cannot choose the operating threshold used to claim test performance. Report:

- Detection recall (= sensitivity for the same face unit) and precision, localization matching rule, false detections/image and end-to-end miss counts.
- Verification FMR/FNMR on declared pairs; open-set FNIR/TPIR, **FPI integer**, FPIR on a declared fixed non-mated-probe denominator, gallery size and enrollment coverage. Separately report false naming on unknown-only media, including spurious detections; never divide by a detector-dependent number of boxes.
- Cluster pairwise precision/recall, B-cubed scores, false-merge/fragmentation counts, labeled-face coverage and unassigned/noise fraction with an explicit noise policy. Unassigned known faces cannot improve a score by disappearing. Unknown faces with no adjudicated identity do not become a shared “unknown person” gold cluster.
- ANN recall@k against exact original-space retrieval, separately from biometric recognition recall.

Edge tests: no mated/nonmated observations; missed detector/timeout/decode cases; top-1 wrong vs reject; equal-to-threshold boundaries; tied scores; negative/non-finite scores; unlabelable examples and changing gallery size. Current legacy scorer uses `> tau` for non-mated FPI and `>= tau` for mated acceptance. Resolve and version this boundary before new comparisons; preserve old artifact semantics. Do not silently compare incompatible scorer versions.

Keep the existing gate's null budget/ratification fields. The report must refuse an adoption verdict when operating policy, independent sample size or required annotations are missing. A descriptive result remains useful under its diagnostic/directional tier.

## S3a — detector-only occlusion benchmark and localization diagnosis

This is a separately reviewable sub-slice of S3 and the **first quality comparison**, before interpreting embedding/clustering gains. It implements the [detector protocol](../../assessments/current/fir-occlusion-corpus-and-metrics-2026-09-19.md#detector-first-measurement-and-remediation). Its work may proceed independently of identity-similarity export; a detector benchmark does not need identities or embeddings.

Reuse `face_metrics.py::detection_pr`, localization matching and exhaustive-box validation, with an explicit strict adapter for this protocol. Current `detection_pr` falls back to `TP=min(pred_faces,labeled_faces)` when `matched_faces` is absent. That can score the wrong face location as correct when counts match. New detector comparisons must require auditable one-to-one box matches and exhaustive human annotation provenance; reject absent localization evidence. Preserve legacy replay semantics instead of silently changing historical reports. A manifest's `exhaustive` flag and matching box count do not establish an independent human audit.

Freeze box convention, eligible/ignore rules, source-coordinate transform, IoU matching and duplicate handling before scoring. Start with declared IoU 0.50 as a proposed diagnostic operating definition, report IoU sensitivity and matched IoU distribution, and ratify the acceptance convention before the confirmatory run. Record all scored proposals at a declared sufficiently low collection threshold, then score candidate thresholds/NMS/resizing only from development/calibration. Capture inference/transport failures distinctly from successful zero-box output; both remain in end-to-end detection coverage, and a partial run cannot pass a candidate gate.

Produce recall/sensitivity by clean, lower-face mask, sunglasses, hand/object, mixed and occlusion-severity cells, with size/pose controls and actual face/image counts. Report precision, FPPI on a fixed image denominator including no-face images, and recall-versus-FPPI curves. Select each detector's operating point on calibration under the same preregistered FPPI budget; freeze it before held-out scoring. Report held-out FPPI even if it exceeds the budget. A threshold chosen independently inside each test cell is forbidden. Sampling/design weights and image/session dependence follow the corpus protocol; enriched negative/hard samples are not deployment prevalence.

Visual output precedes the clustering explorer: paired original-image GT/prediction overlays, missed-face galleries, false-positive/duplicate galleries, landmark failures and a per-stratum recall/FPPI panel. Every eligible GT face has a stable ID even when no detector proposes it. Do not construct these views solely from embedding rows. Report stage outcomes: no matched proposal → matched box but unusable alignment → usable embedding but wrong/rejected identity → clustering/assignment error → correct result; retain unresolved and failure reasons rather than forcing every case into a causal label.

**RED dispatch:** two GT faces but two predictions over only one face; equal counts at disjoint locations; both detectors miss the same human-annotated face; zero-box success vs timeout; no-face image with a false proposal; duplicate predictions; source/downscale/EXIF mismatch; ambiguous ignore region; unratified FPPI budget; unsupported confidence floor; missing annotation provenance. IoU evidence absent must fail the strict adapter. Tests that exercise only count arithmetic do not satisfy S3a.

**Exit:** reproducible baseline detector report plus a controlled rescue/challenger comparison and stage attribution, or an explicit incomplete-evidence result. A claim of detector improvement needs adequate occluded-face recall gain under the frozen FPPI budget, clean-face non-inferiority and latency/resource limits, with margins/uncertainty preregistered and ratified. Numeric budgets remain unset until the pilot supports them. A no-improvement result completes measurement but does not qualify a replacement. The LocalWP installation can proceed without this quality gate passing.

## S4 — paired cluster visualization and configuration explorer

Deliver a private HTML comparison report first, with a reusable artifact contract for a later Workbench view. It must work from immutable run artifacts and must never mutate live clusters. Use existing atlas stable face IDs/provenance/tenant boundaries where appropriate. Query cached artifacts rather than rerunning embeddings when the user changes the display.

Required views:

1. **Run comparison header:** model/config/corpus/gallery/scorer differences, timing/cost/coverage, compatibility verdict and evidence tier. Make missing fields visible.
2. **Cluster thumbnail grids:** side-by-side memberships, linked selection of the same source face across runs, reviewed identity labels, unassigned column, occlusion and error filters, clear indicators for unknown or unreviewed labels.
3. **Linked projection scatter:** color by cluster or reviewed identity, selectable face/cluster, tooltip with original-space similarity and provenance, explicit “diagnostic projection” label. Include nearby-original-space neighbors for a selected point.
4. **Membership change table and contingency/alluvial view:** false merges, fragmentation, noise transitions, changed assignments and disputed labels. Match runs by stable face IDs, not arbitrary cluster labels or cross-run UUID equality.
5. **Metric panels:** precision/recall or open-set tradeoff curves with selected calibration point, per-stratum counts/intervals, quality-vs-latency/cost frontier and paired deltas. Zero measured errors is not zero uncertainty.

For the **same embeddings and face set**, fit/cache a single projection and reuse its coordinates while comparing clustering configurations; record UMAP/PCA parameters, seed and projection hash. For different embedders or different face sets, use separately labeled panels and link by IDs; do not interpret coordinate alignment or projected distances as cross-model evidence. Any optional display alignment is labeled display-only. Compute all acceptance metrics in original embedding/membership space. Projection parameters cannot affect recognition scores.

Provide keyboard-accessible selection, labels/symbols beyond color and a table/grid alternative. Do not use only a rainbow scatter. Preserve filter state in exported comparison metadata. Sealed test results are read-only report outputs; interactive exploration is confined to development/calibration and cannot feed unnoticed threshold tuning.

RED/verification: fixture has a deliberate merge, split and noise transition; views preserve these after reordering/cluster relabeling, incompatible runs refuse subtraction, projection change leaves metrics byte-identical, shared selection resolves stable IDs, missing labels remain missing, unauthorized artifact references fail. Render the report and inspect populated/empty/error views at desktop and narrow width. Export standalone private HTML plus machine-readable JSON/CSV without network analytics or external media URLs.

## S5 — recognition configuration and oracle experiments

Start with the current YuNet/SFace configuration, OACT coefficient zero. Run S3a first, using a preregistered small grid: current YuNet; low-cost localization rescue (input scale, threshold/NMS or bounded tiling); then an artifact-cleared detector challenger if needed. Hold SFace/gallery/assignment fixed for the end-to-end detector comparison. Only after this report interpret alignment, embedder, clustering/assignment and index comparisons as their own experiments. Each candidate gets its own calibration policy and immutable run. Do not spend a huge grid to discover a favorable test result.

The [capacity follow-up](FIRDV-3-embedder-capacity-and-training-feasibility-task-plan.md) adds a bounded SFace128/AuraFace512 checkpoint comparison after exact artifact/provenance/preprocessing checks. It uses separate model spaces and this same scorer. The baseline is not assumed sufficient forever, and dimensionality alone is not a selection metric.

Integrate FIR-15's attribution split and oracle ladder before implementing a learned visibility branch. Its fixed-detector alignment arms do **not** measure missed-face recall and do not replace S3a. Report a verified-box plus reference-alignment rescue as a combined localization/alignment intervention where native landmarks do not exist; never fabricate landmarks for a missed face or call that delta pure detector gain. Buffalo fused legs that re-detect are whole-pipeline references, never controlled fixed-box embedder arms. Compare actual detections/alignment with manually verified alternatives; then visible-region oracle vs any predicted visibility, preserving a common evaluated population and identifying non-embeddable cases. Oracle benefit is an upper bound, not deployable performance. A negligible or uncertain gain parks the branch pending better evidence. Dense SFace coordinates have no spatial masking contract; implement no arbitrary coordinate mask.

Periocular candidates apply when eyes remain visible, not to sunglasses cases by assumption. Head/torso appearance is a separate association experiment with its own space; it never supplies a confirmed identity. InsightFace is optional isolated historical/research comparison only, with existing license restrictions; the new site's readiness does not require it.

Use paired, identity/session-grouped uncertainty estimates and declared non-inferiority margins when adequately powered. Multiple trials/pairs from one identity do not constitute independent subjects. No universal numeric target is supplied here: report baseline variance/pilot counts, propose budgets and sample sizes, then ratify before the sealed comparison. Preserve FIR-11/FIR-13 gate definitions for any later production claim.

## S6 — self-hosted remote VLM bake-off preparation

First freeze recognition, roster confirmations and structured spatial evidence. The primary comparison sends **identical image bytes and FIR evidence** to each VLM; it measures description differences. Separate diagnostic arms are: image-only, oracle identity/position evidence, and actual FIR evidence. Only the final combined end-to-end run changes recognition and VLM together.

Candidate manifest starts with the current serving baseline and a small shortlist from VLM-6/VECVLM-1 prior art (including the recorded Qwen dense/MoE candidates). Names in old plans are leads, not verified available artifacts. Before accepting a candidate, verify its official model card, actual vision support, immutable weights/revision, license, tokenizer/processor, serving compatibility, context/image limits, GPU memory at the chosen dtype/quantization and hardware cost. Record failure/exclusion rather than silently substitute a different model. Start with the incumbent plus at most two feasible challengers. Hosted OpenAI/Anthropic/other provider vision endpoints remain deferred; Codex is the coding worker, not a caption candidate.

Use existing deterministic caption/placement metrics but add validated reference facts and human judgment. Separate factual precision/hallucination, required-fact coverage, unsupported identity, wrong person/position, useful detail, concision and accessibility usefulness. “Mentions every name” is not grounding correctness. A terse empty caption cannot win on precision alone. The eligible reference facts and applicability rules must be human-authored/adjudicated, with coverage counts.

Reuse DESCQUAL-2 annotation packets: blind candidate identity/order, paired comparisons including ties, a shared rubric, calibration examples and a double-rated subset with agreement/adjudication. Use a qualified accessibility reader where the usefulness claim requires it. Automated judging can assist after calibration against humans; a candidate must not be its own sole judge. Freeze rubric and primary acceptance policy before the held-out run. Report annotator time/nonresponse and disagreement separately from model errors.

Each model gets a bounded development prompt-tuning allowance recorded in the manifest. Freeze the selected prompt before calibration/test, and report both the common-prompt control and any model-specific tuned arm. Keep image preprocessing/output budget/task intent comparable; document necessary model-specific differences. Cache keys include evidence/prompt/model/image hashes. Repeat a small stochastic subset to quantify instability even at deterministic settings.

S6 delivers dry-run candidate manifests, rubric/annotation packet, request/replay fixtures, proposed operating margins and a costed execution plan. It does not claim a model winner or require a paid run to complete its preparation slice.

## S7 — burst cost instrumentation and gated live run

Close or integrate the [existing cost debt](../tech-debt/gpu-burst-cost-observability.md): sanctioned run aggregation plus durable startup/burst IDs, timestamps and priced resource usage. Legacy `--hourly-rate`/`--cost-total` overlays are estimates unless reconciled to a rate and billed interval. No direct ad-hoc production DB query becomes the benchmark's public data contract.

| Measurement | Contract |
| --- | --- |
| Workloads | Batch sizes 1/5/10/50/100 as capacity permits; record actual concurrency. Distinguish cold VM, cold model, warm model, input cache and repeat runs. Balance/randomize candidate order within comparable hardware windows. |
| Time | Upload/queue, VM startup, model load/warmup, FIR, generation, postprocessing, end-to-end and idle/stop separately. p50/p95/p99 plus sample counts; timeouts/failures remain outcomes, not removed to improve latency. |
| Hardware | GPU type/count, memory high-water and OOM, CPU/RAM, serving version, throughput and utilization where available. Token/image quantities accompany dollars. |
| Price | Currency, provider/resource/rate source and effective date, minimum billing increments and actual billed interval. Include startup, retries, failed requests, idle tail and relevant storage/network charges or explicitly scoped exclusions. |
| Attribution | Sum the whole burst once. Allocate shared startup/idle using a declared policy; attributed costs must reconcile to burst total. Report dedicated vs shared assumptions and sensitivity to utilization. |
| Unit economics | Cost per attempted, completed and **quality-accepted** description, with numerators/denominators. Zero accepted outputs yields null/not-computable, never $0. Pilot human-labeling cost is separate from serving cost. |
| Budget and teardown | Proposed model/window/lease ceiling and current price approved before live run; stop on ceiling/lease/OOM policy, record partial results, verify GPU teardown. Unratified budget blocks spending, not offline preparation. |

The existing runner labels its measurements `closed_serial`, concurrency 1. Preserve that label and the coordinated-omission limitation. If making latency-under-arrival-load claims, add scheduled-arrival timestamps, queue delay and an explicit arrival workload; serial service-time percentiles alone cannot support that claim.

Report estimated and measured cost separately. Reconcile available billing evidence; reuse the existing operational reconciliation tolerance only as an operational check, not as proof of precise per-caption economics. Publish both observed workload economics and any projected scenario assumptions. A batch-size-dependent startup amortization chart and quality/latency/cost Pareto view are required.

Run prerequisites: FIRDV-1 readiness; validated annotations/splits; frozen calibration and operating margins; verified candidate artifacts/hardware; bounded rate-backed spending plan; no competing serving workload; working metering and stop path. The live run records all exclusions and emits no adoption verdict if quality or cost evidence is incomplete. Recommend a model/config only after paired quality uncertainty and the accepted-caption cost support it; then rerun the selected combination end to end against the unchanged reference protocol.

## Eval registration and completion

The scope's [eval intent](../../scopes/fir-development-and-measurement-evals.json) is provisional. During S1 implement/register `scripts.eval_harness.firdv_contract_eval` in the installed validation mechanism; proposed invocation from the repository root is:

```sh
cd apps/prototype-description-service
uv run python -m scripts.eval_harness.firdv_contract_eval --cases ../../docs/scopes/fir-development-and-measurement-cases.json
```

The executor must execute cases and consume evidence, not merely check that files exist. Exit nonzero for invalid contracts; emit `pending`/`not_run` for absent live/human evidence and never equate that to passing SC-01–SC-09. Unit suites and a docs-only preparation can pass their own scope while whole-program acceptance remains incomplete. Evidence sink is repository-root `.task-state/evals/results.jsonl`, with task/suite/case/run/artifact hashes.

Complete each slice with targeted tests and affected regressions, a reviewable artifact and linked handoff decisions. For S4 include rendered visual inspection; for S6 include CPU-only request/replay and annotated-fixture scoring; for S7 include metering reconciliation and teardown evidence. No live metric, human label or benchmark result was produced by authoring this plan.

## Consolidated checklist

- [ ] S1 manifest/expected-unit ledger and runnable eval executor registered; RED and implementation reviewed separately
- [ ] S2 successor corpus schema, sampling and annotation packets validated; human coverage recorded
- [ ] S3 real score export and normalized metrics tested at boundaries and missing-evidence cases
- [ ] S3a detector-only strict localization scorer, exhaustive annotation evidence, miss/FP galleries and controlled detector experiment completed before downstream quality interpretation
- [ ] S4 linked cluster comparison, original-space metrics and private report export visually verified
- [ ] S5 calibrated recognition/attribution comparisons recorded with uncertainty and evidence tier
- [ ] S6 self-hosted candidate, rubric and priced run-preparation packet complete
- [ ] S7 metering/stop controls pass; bounded live run and teardown recorded only when prerequisites are met
- [ ] SC-04–SC-08 and SC-10 acceptance recorded with links to tests, human evidence and live artifacts as applicable
