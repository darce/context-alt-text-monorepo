# E22. Commercial Face Identity Replacement

> **Metadata**
>
> - **Date**: 2026-07-15
> - **Author**: Claude Fable 5 (claude-fable-5)
> - **Epic Short ID**: FIR
> - **Target Version**: v0.5.0
> - **Status**: planned — decomposed from [commercial-face-identity-replacement.md](../../scopes/commercial-face-identity-replacement.md) after /review-parallel round `r0715d3e2` (verdict `conditional_pass`, 23 findings fixed @ b8e3877d; findings live in handoff under FIR-1 — query, do not mirror)
> - **Grounding**: [commercial-face-pipeline-replacement-assessment-2026-07-15.md](../../assessments/current/commercial-face-pipeline-replacement-assessment-2026-07-15.md) · research guide `acx_commercial_face_recognition_replacement_guide.docx` (2026-07-14)

## Goal

Remove the non-commercial InsightFace buffalo weights from the production face-identity pipeline and replace them with an ACX-owned, commercially licensed stack — YuNet 2026may (MIT) detection → five-point alignment → SFace 2021dec (Apache-2.0) 128D embedding → existing clustering — gated by an ACX-domain bake-off against a licensed-use buffalo_l reference, with InsightFace surviving only as a benchmark dependency in a non-commercial eval environment.

## Hard Constraints

1. **License isolation**: buffalo weights never in production images at commercial exposure; `insightface` only in a `[bench]` extra; benchmark embeddings never in the production DB. (Fixed-dim pgvector columns enforce this structurally only once prod is 128D — until the FIR-6 flip both are 512D, so pre-cutover separation is procedural: eval-env-only buffalo legs + run-artifact storage.)
2. **Dark until gated** (RLSE-02/07): the new pipeline wires in behind a face-pipeline profile flag; the production default does not change until an **operator-recorded MCP gate decision** exists (bake-off report proposes; operator decides; switch-over slice is blocked without it).
3. **CPU-first**: ARM A1 is the production path; A10/CUDA is bake-off-first, production GPU is follow-on (FIR-7).
4. **Greenfield after verification**: no data migrations — but FIR-2 must first enumerate live tenants and record operator wipe/re-scan sign-off. The dimension **defaults** flip (512→128, `EMBEDDING_DIMENSION` + `PGVECTOR_DIM` + deploy configs) lands only in FIR-6's gated switch-over slice, so every FIR-4 deliverable is mergeable dark (no slice held hostage to a later gate); dev/eval environments exercise the 128D pipeline earlier via the `PGVECTOR_DIM` env without touching defaults.
5. **Thresholds are measured, never copied** (guide §8.1, PERF-06): every similarity/quality/unknown threshold comes from FIR-6 calibration on ACX data.
6. **Reuse VLM-6's Golden-150 harness** — six coordination asks + fallbacks per scope §Coordination; no parallel corpus, no forked walker without a recorded decision.

## Phases

| Phase | Tasks | Outcome |
| --- | --- | --- |
| P1 Seam + adapters | FIR-2, FIR-3 | Model-neutral seams, provenance column, consumer audit, YuNet+SFace adapters with golden parity tests |
| P2 Dark integration + harness | FIR-4 (after FIR-3) ∥ FIR-5 (scaffolding starts after FIR-2; candidate legs need FIR-3) | Pipeline wired dark with observability + boot-time hash verification; bake-off harness with occlusion-first slices + perf leg |
| P3 Calibrate + gate + switch | FIR-6 | Quality rework, hard-case recovery (gate→weight→aggregate→constrain), bake-off report, operator gate, switch-over |
| P4 Follow-ons | FIR-7 (GPU), FIR-8 (contingent escalation) | Production CUDA path; escalation ladder only on a failed gate |

## Task Decomposition

Task definitions, dependency edges, and deliverables are canonical in the scope doc's [Task decomposition table](../../scopes/commercial-face-identity-replacement.md#task-decomposition). Task plans live in `docs/tasks/fir/` as `FIR-<n>-*-task-plan.md`; FIR-2 and FIR-3 plans are written (P1). **Just-in-time authoring is owned**: the agent starting a phase authors that phase's plans at phase entry (trigger: predecessor task reaches `done`), and every plan passes `/planning-review` with verdict `pass`/`pass_with_findings` before its `make task-start` — no plan, no branch.

## Exit Criteria

Scope doc [Success criteria 1–7](../../scopes/commercial-face-identity-replacement.md#success-criteria), summarized: no buffalo weights in prod images; end-to-end scan→cluster→curate on YuNet+SFace with falsifiable unknown-first behavior; bake-off report incl. occlusion (real + synthetic-paired) and throughput/cost legs; operator-recorded gate decision preceding switch-over; golden parity tests green on `make check-remote`; per-row `embedding_model` provenance + build/boot hash verification; recorded greenfield sign-off.

## Verification

- Per-slice: scoped TDD locally, full suite via `make check-remote` (never local full-suite).
- Golden parity tests (landmark order, affine alignment, normalization) are the FIR-3 merge gate.
- Bake-off runs are deterministic re-scorable (`score --check-determinism`) with buffalo legs confined to eval-env run artifacts.
- Pre-merge: `handoff_close_check(enforce=True)` per repo rule; `/review-parallel` per slice and at branch end.
