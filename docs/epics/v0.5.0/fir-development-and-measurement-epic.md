# E24. FIR development installation and comparative measurement

> **Metadata**
>
> - **Date**: 2026-09-19
> - **Author**: Codex
> - **Epic Short ID**: FIRDV
> - **Target Version**: v0.5.0 development qualification
> - **Status**: draft; implementation and live qualification pending
> - **Scope**: [FIR development and measurement](../../scopes/fir-development-and-measurement-wave.md)
> - **Grounding**: [current-state assessment](../../assessments/current/fir-development-wave-assessment-2026-09-19.md), [corpus and metrics](../../assessments/current/fir-occlusion-corpus-and-metrics-2026-09-19.md)

## Goal

Deliver a fresh LocalWP plugin installation backed by an isolated remote in-house FIR service, a correct 512D model-specific identity database, and real self-hosted remote descriptions. Establish the existing 128D SFace route first as a separate baseline; it is not the final development deliverable. The [implementation guide](../../roadmaps/fir-localwp-512d-implementation-roadmap-2026-09-19.md) is the next-session entry point. Extend FIR-16/VLM-6 into a reproducible comparison harness with cluster visualizations, valid occlusion measurements and full description-quality/cost accounting.

This epic owns the **development deployment and comparative measurement integration**. [E22](commercial-face-identity-replacement-epic.md) retains production replacement and its evidence gates. The user explicitly requested a new phase epic; this does not reopen completed FIR implementation or silently supersede E22's production policy.

## Reuse and ownership

| Existing owner | Reuse / reconciliation | FIRDV responsibility |
| --- | --- | --- |
| FIR23-STACK | Tooling merged, physical deployment not established by the available record; handoff 4315 overrides stale “unmerged” prose | Finish independently pinned/authenticated dev-fir deployment and LocalWP integration; record completion back to the existing task |
| FIR-2/3/4 | Runtime seam, YuNet/SFace adapter and dimension assertions | Configure and verify the shipped runtime; no replacement runtime framework |
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
| A — working development installation | [FIRDV-1](../../tasks/firdv/FIRDV-1-isolated-development-install-task-plan.md), S1–S5 | Actual API/worker/model/DB agreement, authenticated LocalWP image-byte upload, FIR enrollment and saved real description, isolation/restart proof |
| B — trustworthy inputs and outcomes | [FIRDV-2](../../tasks/firdv/FIRDV-2-comparative-harness-and-bakeoff-task-plan.md), S1–S3a | Detector-only strict localization report and independent occlusion GT, plus immutable run contract, complete expected-unit ledger, successor corpus schema and human labeling workflow, real similarity exports and metric edge-case tests |
| C — recognition comparisons and visual diagnosis | FIRDV-2 S4–S5 | Replayable paired configuration report, cluster views, original-space metrics, calibration/test separation and attribution report with evidence tier |
| D — description bake-off preparation and gated execution | FIRDV-2 S6–S7 | Frozen FIR evidence, pinned self-hosted candidate manifest, quality rubric and cost ledger; execution only after labels, model feasibility, operating policy and bounded budget are ready |
| 512D delivery and bounded training feasibility | [FIRDV-3](../../tasks/firdv/FIRDV-3-embedder-capacity-and-training-feasibility-task-plan.md), after common score/corpus contracts | Exact 512D artifact and separate store, actual LocalWP route (S6), paired checkpoint evidence, data/hardware feasibility or explicit no-go; functional delivery is separate from quality adoption and training |

Phase A does not depend on proving an occlusion improvement. S3a is the first quality comparison: diagnose detection/localization misses before interpreting clustering or higher-dimensional encoder gains. Detector scoring does not wait for identity-similarity export. CPU-only contract work in Phase B may proceed alongside deployment. Live comparisons depend on A; quality claims depend on labeled B, frozen calibration and sample-size adequacy. Attribution determines which later occlusion branch is justified, not whether the requested development site may exist.

## Acceptance and stop conditions

Scope SC-01–SC-11 are the acceptance map, including the user's capacity follow-up. A demo alone satisfies neither corpus validity nor recognition quality. Conversely, null quality budgets do not block deterministic installation tests.

- Installation fails closed for foreign embedding space, missing model provenance or unintended shared state. It never falls back to InsightFace.
- An unannotated stratum, missing denominator or failed request is visible, never silently zero or absent.
- Golden-150 remains frozen history; the successor has explicit identity/session groups, unknowns and face-instance occlusion. Previously inspected data is not relabeled a blind holdout.
- Projection layout cannot change recognition metrics. Cluster identity/purity claims come from original-space membership and reviewed labels.
- A candidate VLM cannot win through fewer completions, unsafe name placement or hidden startup/retry cost. Missing quality/cost evidence means “not evaluated.”
- PostgreSQL 19, hosted vision APIs, retraining and production cutover stay outside this phase.

## Junior kickoff and review

Start FIRDV-1 S1 as a **tests-only RED dispatch**, review its cases, then use a separate implementation dispatch. Pin `codex-remote`, `gpt-5.6-luna`, effort `max`; no implicit fallback backend. The [first task plan](../../tasks/firdv/FIRDV-1-isolated-development-install-task-plan.md#first-dispatch-brief--tests-only) supplies a bounded handoff. This epic is a draft, not a claimed formal planning-review pass.

## Consolidated checklist

- [ ] FIRDV-1 runtime evidence contract and failure tests implemented
- [ ] Independent deployment image, DB, role, volume, network, blob namespace and authentication verified
- [ ] New LocalWP site completes upload → FIR scan → confirmation → real remote description → saved draft
- [ ] Wrong-space, unknown, outage, restart and isolated rollback cases evidenced
- [ ] Corpus successor and annotation coverage validated against original pixels
- [ ] Complete outcome/provenance ledger and normalized metric adapters implemented
- [ ] Detector baseline/rescue/challenger report, spatial-match tests and miss/false-positive galleries delivered; adoption separately gated by SC-10
- [ ] Paired clustering visualization/report export delivered
- [ ] Oracle/attribution comparison and evidence-tier limits recorded
- [ ] Self-hosted candidate/rubric/cost manifests prepared; numerical policies remain explicitly unratified until decided
- [ ] Bounded live recognition/VLM experiments run when their prerequisites are met
- [ ] Findings and reusable completions linked back to FIR/VLM upstream tasks; no production flip inferred
- [ ] FIRDV-3 checkpoint/training-feasibility exit recorded; greater dimension never substituted for quality evidence
- [ ] FIRDV-3 S6 actual 512D LocalWP/remote model-space and database readiness, isolation, failure handling and rollback verified (SC-11)
