# E24. FIR development installation and comparative measurement

> **Source-of-truth status — 2026-10-30:** the [current roadmap status and continuation](../../roadmaps/fir-localwp-512d-implementation-roadmap-2026-09-19.md#current-status-2026-10-30) replace this epic's September installation kickoff. Source/runtime fixes and all six LocalWP **0.0.42** installations are complete; independent quality evidence and the listed remaining installed runtime cases are separate. Do not recreate sites, reinstall or restart FIRDV-1 S1.

> **Metadata**
>
> - **Date**: 2026-09-19
> - **Author**: Codex
> - **Epic Short ID**: FIRDV
> - **Target Version**: v0.5.0 development qualification
> - **Status**: installation/runtime baseline complete within recorded scope; independent measurement and remaining acceptance evidence pending (reconciled 2026-10-30)
> - **Scope**: [FIR development and measurement](../../scopes/fir-development-and-measurement-wave.md)
> - **Grounding**: [current-state assessment](../../assessments/current/fir-development-wave-assessment-2026-09-19.md), [corpus and metrics](../../assessments/current/fir-occlusion-corpus-and-metrics-2026-09-19.md)

## Goal

Continue comparative measurement from the installed LocalWP/isolated remote FIR routes and accepted runtime receipts. The 128D SFace route remains an optional separate comparator, not a prerequisite to the installed AuraFace512 route. Reuse FIRBENCH and FIR-16/VLM-6 for cluster visualizations, valid occlusion measurements and description-quality/cost accounting; the [current roadmap status](../../roadmaps/fir-localwp-512d-implementation-roadmap-2026-09-19.md#current-status-2026-10-30) is the continuation entry point.

The accepted source baseline is main `bda5a0d4ac75c5bf4c2ea0a0750252cef84995fc`. Runtime receipt `.task-state/fircold-20261030/runtime-acceptance.json` (decision 20802) and six-site receipt `.task-state/localwp-rollout-20261030/rollout-result.json` cover bounded runtime, served assets and authenticated navigation. They do not establish independent face truth, calibrated recognition quality or every SC-11 failure/restart/rollback case. Retain all four persistent Compose overlays.

Remaining work separates actual in-flight description navigation/remount/client Stop waiting, real credential edit/autosave and installed naming recovery from exhaustive independent face annotations, fixed representative production replay, historical triplicate attribution and calibrated comparisons. The exploratory three-leg manifest has null/unratified prerequisites; it is not a confirmatory study or a model-winner decision.

DESCAUTH-1 and IDWEAVE-1 completed planning, not implementation. [ADR-017](../../adrs/ADR-017-description-authority-wordpress-curation-service-generation.md) and [ADR-018](../../adrs/ADR-018-post-curation-identity-weaving.md) remain Proposed. [ADR-019](../../adrs/ADR-019-person-anchored-curation-surfaces.md) is Accepted with producer verification and real-database gates open. No automatic acceptance or feature promotion follows from an archived `done` state.

This epic owns the **development deployment and comparative measurement integration**. [E22](commercial-face-identity-replacement-epic.md) retains production replacement and its evidence gates. The user explicitly requested a new phase epic; this does not reopen completed FIR implementation or silently supersede E22's production policy.

## Reuse and ownership

| Existing owner | Reuse / reconciliation | FIRDV responsibility |
| --- | --- | --- |
| FIR23-STACK / FIRDV-1 | Tooling and installed runtime baseline complete within current receipt scope; September deployment absence is stale | Consume accepted deployment/runtime receipts; record only genuinely missing acceptance evidence |
| FIR-2/3/4 | Runtime seam, YuNet/SFace adapter and dimension assertions | Consume accepted runtime receipts; identify only a specific remaining evidence gap |
| FIR-11 + DESCQUAL-2 | Corpus remediation, grouped sampling, annotation packets | One versioned successor manifest and face-level annotation ledger shared by recognition and caption evaluations |
| FIR-13/14 | Gate contract exists, ratification incomplete; toolchain rebaseline remains evidence-sensitive | Consume current gate schema and provenance; null budgets remain unratified |
| FIR-15/17 | Attribution/oracle ladder; OACT sign correction already merged, coefficient remains zero | Wire attribution when warranted; do not repeat the fix or enable a coefficient by default |
| FIR-16 + FIR-8 | Open-set cross-stack contract and reusable bench orchestration | Complete missing measurement/export integration once, then consume it from comparisons |
| FIR-9 | Atlas storage/provenance primitives | Add immutable evaluation comparisons and linked views; keep product curation in Workbench |
| VLM-6 + GPU cost debt | Description harness, timing reports, incomplete burst accounting | Self-hosted quality/cost experiment manifest, human evaluation, burst-to-run attribution |
| FIR-6 S6 | Production switch-over | Out of this epic; consumes admissible evidence later |

Before editing an upstream-owned module, claim its slice in handoff and link the existing task. If that task has already delivered the requirement, add only integration/tests. Do not maintain competing scorers, corpus counts or gate schemas.

## Phased delivery

| Phase | Task / slices | Exit evidence |
| --- | --- | --- |
| A — installed development baseline | [FIRDV-1](../../tasks/firdv/FIRDV-1-isolated-development-install-task-plan.md), S1–S5 contracts | Consume completed installation/runtime receipts; S1 is merged. Any unevidenced isolation/restart/rollback criterion remains explicit, not a blanket installation restart |
| B — trustworthy inputs and outcomes | [FIRDV-2](../../tasks/firdv/FIRDV-2-comparative-harness-and-bakeoff-task-plan.md), S1–S3a | Detector-only strict localization report and independent occlusion GT, plus immutable run contract, complete expected-unit ledger, successor corpus schema and human labeling workflow, real similarity exports and metric edge-case tests |
| C — recognition comparisons and visual diagnosis | FIRDV-2 S4–S5 | Replayable paired configuration report, cluster views, original-space metrics, calibration/test separation and attribution report with evidence tier |
| D — description bake-off preparation and gated execution | FIRDV-2 S6–S7 | Frozen FIR evidence, pinned self-hosted candidate manifest, quality rubric and cost ledger; execution only after labels, model feasibility, operating policy and bounded budget are ready |
| Installed 512D route evaluation and bounded training feasibility | [FIRDV-3](../../tasks/firdv/FIRDV-3-embedder-capacity-and-training-feasibility-task-plan.md), after common score/corpus contracts | Reuse exact installed artifact/space and S6 receipts; paired quality evidence, data/hardware feasibility or explicit no-go remain separate from functional delivery |

Installation/runtime completion does not prove an occlusion improvement. S3a's detector-first contract still governs quality comparisons: diagnose detection/localization misses before interpreting clustering or higher-dimensional encoder gains. Reuse merged contracts and scorers. Quality claims depend on independent labels, frozen calibration and sample-size adequacy; attribution determines which later occlusion branch is justified.

## Acceptance and stop conditions

Scope SC-01–SC-11 are the acceptance map, including the user's capacity follow-up. A demo alone satisfies neither corpus validity nor recognition quality. Conversely, null quality budgets do not block deterministic installation tests.

- Installation fails closed for foreign embedding space, missing model provenance or unintended shared state. It never falls back to InsightFace.
- An unannotated stratum, missing denominator or failed request is visible, never silently zero or absent.
- Golden-150 remains frozen history; the successor has explicit identity/session groups, unknowns and face-instance occlusion. Previously inspected data is not relabeled a blind holdout.
- Projection layout cannot change recognition metrics. Cluster identity/purity claims come from original-space membership and reviewed labels.
- A candidate VLM cannot win through fewer completions, unsafe name placement or hidden startup/retry cost. Missing quality/cost evidence means “not evaluated.”
- PostgreSQL 19, hosted vision APIs, retraining and production cutover stay outside this phase.

## Continuation and review

Use the roadmap's current continuation to select an actual unfinished existing-owner delta. The old FIRDV-1 S1 tests-only kickoff and worker pin are superseded: S1 is merged, and the current explicit remote model/effort/FAST launch receipt governs. Read the selected plan and actual producers before focused RED/GREEN work. This documentation reconciliation authorizes no new implementation, runtime mutation, inference or review jobs.

## Consolidated checklist

- [x] FIRDV-1 S1 runtime evidence contract merged; consume its existing tests/validator
- [x] Source/runtime baseline and six-site 0.0.42 installation receipts recorded; retain existing isolation and overlays
- [x] Accepted cold GPU completion/saved-draft navigation and cold SFace persistence/API/projection cases recorded
- [ ] Remaining in-flight/client Stop, actual credential autosave and installed naming recovery acceptance recorded under current scope
- [ ] Any additional SC-11 wrong-space/unknown/outage/restart/rollback criterion mapped to exact evidence; unevidenced cases stay pending
- [ ] Corpus successor and annotation coverage validated against original pixels
- [ ] Remaining outcome/provenance and metric-adapter evidence reconciled against existing implementation
- [ ] Detector baseline/rescue/challenger report, spatial-match tests and miss/false-positive galleries delivered; adoption separately gated by SC-10
- [ ] Paired clustering visualization/report export delivered
- [ ] Oracle/attribution comparison and evidence-tier limits recorded
- [ ] Self-hosted candidate/rubric/cost manifests prepared; numerical policies remain explicitly unratified until decided
- [ ] Bounded live recognition/VLM experiments run when their prerequisites are met
- [ ] Findings and reusable completions linked back to FIR/VLM upstream tasks; no production flip inferred
- [ ] FIRDV-3 checkpoint/training-feasibility exit recorded; greater dimension never substituted for quality evidence
- [ ] FIRDV-3 S6 actual 512D LocalWP/remote model-space and database readiness, isolation, failure handling and rollback verified (SC-11)
