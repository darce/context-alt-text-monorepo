# Scope: FIR development installation and comparative measurement

Date: 2026-09-19 · `/wb-scope` · Epic short ID: **FIRDV**
Status: draft for implementation planning; quality operating points unratified
Intake decisions: handoff **12780**, **12781**, **12782** (`MAINT-FIRWAVE-20260919`).

## Recorded intake

| Question | Answer / disposition |
| --- | --- |
| Deployment topology? | **User confirmed:** a fresh LocalWP installation with an isolated remote development service/database. No public WP endpoint is required. |
| Recognition requirement? | **User required:** use the partly implemented in-house FIR pipeline in place of InsightFace, including the correct backend embeddings database. |
| Harness home? | **User clarified:** FIR-16/VLM-6 can be the starting point if expanded to meet requirements; include visualizations of clusterings to compare configurations. |
| Description candidates? | **User confirmed:** self-hosted remote models only. Hosted image-capable provider APIs may be considered later before launch. |
| Evidence basis and worker? | **User required:** requested v11 HTML research, assessments/scopes/debt/epics/roadmaps, OCC research, canon `distilled/` original-source mechanisms, codemap and semantic handoff history; `codex-remote` Luna MAX for grunt work. |
| Unknown face / FIR unavailable? | Asked; no explicit answer. **Proposed:** never fall back to InsightFace. Omit unverified names where the description path can safely continue; return a typed retryable error if required service functionality is unavailable. Do not invent an identity or silently substitute a caption model. |
| First completion gate? | Asked; no explicit answer. **Proposed:** end-to-end FIR development installation first; occlusion and production-quality qualification later. This matches the existing dark-launch topology decision 3250. |

The last two are visible planning assumptions, not operator-ratified quality policies. This intake does not authorize replacing production defaults or executing a paid bake-off. Work below is sufficiently bounded to draft and start its contract tests without resolving numerical quality budgets.

## MVP

- A new LocalWP site with its own WP database and plugin settings, real image upload to remote `dev-fir`, FIR recognition on API/worker, its own model-specific pgvector database and confirmed roster, and real remote self-hosted descriptions. Establish 128D SFace as the initial baseline, then deliver the separately isolated 512D development route under FIRDV-3 S6.
- Repeatable readiness proof covering effective settings, loaded models, actual DB schema, model provenance, authentication, failure behavior and image/run correlation. A green `/health` alone is insufficient.
- An expanded FIR-16/VLM-6 harness with a common immutable run manifest, complete expected-unit outcomes, standardized metrics, annotation coverage, calibration provenance and resumable comparisons.
- Detector-first quality comparison: YuNet baseline, bounded localization rescue and a permitted challenger where justified; stage attribution precedes claims about embedding capacity.
- Cluster configuration comparisons: paired runs, cluster membership grids, linked thumbnail scatter and failure tables, false-merge/fragmentation/noise views, parameter and cost/latency deltas.
- A versioned successor to Golden-150 with face-instance occlusion labels, grouped allocation, deployment and challenge arms, unknowns, independent negatives and bounded human visibility annotations. Preserve Golden-150 history.
- A prepared self-hosted VLM quality/cost bake-off using frozen FIR evidence; run it only once annotation, serving and spending gates are concrete.

## Non-functional decisions and assumptions

| Constraint | Proposed contract |
| --- | --- |
| Scale | Development/benchmark use, one isolated tenant per mutable run workspace; no production-scale throughput claim. Record tested gallery size, batch sizes 1/5/10/50/100 and concurrency. |
| Latency | Record upload, queue, FIR, model load/warmup, generation and whole-request p50/p95/p99 separately. Existing VLM-6 170 s GPU p95 ceiling is historical, not a new ratified SLO; verify current timeout chain before applying it. |
| Retry | One logical image/run outcome per idempotency key and input/config fingerprint; preserve attempt logs and retry cost. Changed config creates a new run. |
| Freshness | No reuse across model, annotation, gallery or config hash changes. Stale/incomplete runs visibly unscoreable for adoption. |
| Failure | Unknown/abstained identity is explicit; outages, decode errors, zero vectors and alignment drops remain recorded. No InsightFace fallback. |
| Isolation | Independent DB/role/volume/network/blob namespace and independently recoverable image reference. API-key auth even for private development ingress; no keys in WP browser code or report artifacts. |
| Durability | Resumable immutable artifact manifest plus append-only attempts. A completed report references exact inputs and scorers; source data remains read-only. |
| GPU cost | Preflight offline, bounded run budget and lease, teardown verified, actual burst metering reconciled. Historical dollars/hour are estimates until a priced usage record is attached. |

## Success criteria and eval mapping

| ID | Observable criterion | Evidence owner |
| --- | --- | --- |
| SC-01 | Fresh LocalWP → authenticated remote upload → FIR scan → roster confirmation → remote description → saved draft works without remote access to `.local` URLs | FIRDV-1 live smoke |
| SC-02 | API, worker, loaded model and actual DB agree on 128D SFace; 512D/mixed-space/missing-model inputs fail closed; reset/rollback affects only dev-fir | FIRDV-1 contract and PG tests |
| SC-03 | No runtime InsightFace fallback; unknown, missing landmark and outage cases cannot create an unverified name | FIRDV-1 + grounding regressions |
| SC-04 | Every sampled image and eligible GT face has a terminal outcome; wrong-wearer tags, drops, duplicates, nonresponse and empty strata are visible | FIRDV-2 corpus/denominator suite |
| SC-05 | Paired config comparison reports original-space cluster metrics and linked visualizations; changing only projection parameters cannot change recognition metrics | FIRDV-2 visualization suite |
| SC-06 | Thresholds/gallery/splits are frozen before test; unknown probes, FPI count and fixed-denominator FPIR/FNIR are reported, including missing evidence status | FIRDV-2 recognition suite |
| SC-07 | VLM report separates factuality, name correctness/placement, coverage, human preference, latency and measured/estimated cost; failed/empty cases cannot win | FIRDV-2 VLM suite |
| SC-08 | One run traces through app/model/runtime/config/corpus hashes and burst metering, re-scores offline, resumes without duplicate logical observations, and respects tenant/artifact privacy | FIRDV-2 provenance/cost suite |
| SC-09 | Capacity follow-up distinguishes dimensions from measured recognition gain; any 512D candidate passes artifact/preprocessing and space-isolation checks, and a training proposal proves data/implementation readiness before spending | FIRDV-3 feasibility extension |
| SC-10 | Detector-only occlusion comparison uses independent exhaustive GT, strict spatial matching, calibration-frozen FPPI budget, per-stratum recall/precision/FPPI and miss/false-positive galleries; downstream scores cannot qualify a detector or hide missed faces | FIRDV-2 S3a/S5 detection suite |
| SC-11 | The new LocalWP site explicitly uses the approved 512D in-house FIR service: loaded weights/preprocessing, API/worker, actual vector/centroid schema and fresh enrollment agree; real remote description, failure/restart and rollback evidenced; 128D baseline remains separate | FIRDV-3 S6 live/contract suite |

Machine-readable [eval intent](fir-development-and-measurement-evals.json) and [case map](fir-development-and-measurement-cases.json) accompany this scope. The suite is **provisional, not executable today**. This consumer checkout has no `packages/workbay-system/config/evals/`; the intent uses the live upstream suite-v1 fields and lives beside the scope, following consumer-local precedent. FIRDV-2 must register an executor and runnable tests in the installed harness; merely listing the suite is not passing it.

## Not doing

No production-wide cutover, PG19 upgrade, external vector database, hosted vision API evaluation, broad model-training campaign, inferred demographic labeling, public benchmark hosting, or automatic identification from clothing/head appearance. No blanket recaptioning of the 646-image corpus. No performance claim from unratified or underpowered data. InsightFace may remain only as an explicitly isolated historical/research comparator, never a dependency or fallback of the new installation.

## Deliverables and sequence

The [assessment](../assessments/current/fir-development-wave-assessment-2026-09-19.md) establishes code/prior-art status; the [corpus/metrics assessment](../assessments/current/fir-occlusion-corpus-and-metrics-2026-09-19.md) defines permissible claims; the [epic](../epics/v0.5.0/fir-development-and-measurement-epic.md) sequences FIRDV-1 deployment and FIRDV-2 harness/bake-off. Start a separate tests-only RED dispatch, review and commit it, then dispatch implementation. Human labels, quality-budget ratification and any later GPU window remain explicit later gates, not blockers for the initial contract slice.

The user's dimension/training follow-up adds [FIRDV-3](../tasks/firdv/FIRDV-3-embedder-capacity-and-training-feasibility-task-plan.md): prepare a controlled higher-dimensional checkpoint comparison and bounded training-feasibility decision. It does not authorize broad retraining or delay the baseline installation. [Concrete population allocation](../assessments/current/fir-corpus-population-allocation-2026-09-19.md) supplies exact review queues; final face labels and experiment splits remain pending pixel/session verification.

The final consolidation makes functional 512D development delivery explicit, independent of any claim of quality superiority. [Start here next session](../roadmaps/fir-localwp-512d-implementation-roadmap-2026-09-19.md) for the complete sequence, corpus additions and underlined human-input gates. Existing permissions/topology are settled; only actual missing inputs and unratified quality/spend decisions require operator attention.
