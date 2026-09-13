# Assessments

Comparative evaluations, source crosswalks, investigation artifacts, and exploratory notes live here.

## Intent

These docs can inform planning, but they are not themselves active epics or task plans.

## Active Assessments

- [Google Edge-AI Stack Evaluation vs FIR Face Pipeline](current/google-edge-ai-stack-evaluation-fir-2026-07-18.md) rejects LiteRT/MediaPipe/XNNPACK/WebNN/litert-lm for E22 (decision #2685); one open rider: `onnxruntime>=1.22` bump routed to FIR-4.
- [Portfolio Quadrant & MVP Strategy Assessment](current/portfolio-quadrant-mvp-strategy-assessment-2026-06-11.md) is the strategy reference for quadrant placement (Cooper framework), MVP cut list, and non-code moat actions. Review when the demo URL is live or 2026-09-01.
- [Public Demo WP Plugin Launch Assessment](public-demo-wp-plugin-launch-assessment-2026-04-30.md) is the primary product and hosting assessment for `demo.altcontext.com`.
- [WP Demo Provisioning Assessment Triage](wp-demo-provisioning-assessment-triage-2026-04-30.md) orders the current provisioning work and gate sequence.
- [Refactoring Opportunities — `apps/prototype-wp-alt-context`](wp-alt-context-cross-cutting-assessment.md) remains actionable as a plugin hardening backlog.
- [Clustering Pipeline & Postgres Refactor — Literature Crosswalk](clustering-pipeline-postgres-refactor-literature-2026-04-26.md) remains actionable as a backend hardening/source-crosswalk input.
- [PgCache and Description-Service DB Read/Write Mechanics Assessment](pgcache-description-service-db-read-write-assessment-2026-04-30.md) remains actionable as a deferred architecture/performance decision.
- [context7 Usefulness Audit & Reintroduction Criteria](current/context7-usefulness-audit-2026-06-18.md) records why context7 stays removed (zero realized usage in the handoff ledger) and the criteria that would justify reintroduction.
- [Richer Caption Context — Fusion Architecture, OpenCV 5, Brand Detection, PG18/19](current/caption-context-enrichment-assessment-2026-07-05.md) (VLM-2, rev B) recommends the three-stage context-fusion caption contract (arXiv 2606.18553), spike-gated OpenCV 5 dependency reduction, template-matching brand detection reusing the identity curation loop, and PG18-now/PG19-at-GA. Rev B folds a 26-paper sweep (BACON, "Inserting Faces inside Captions", PerceptionRubrics, BLV curator study, local library) + July-2026 VLM survey: deterministic identity merge production-validated, gated-rubric eval harness, opt-in GGUF 4B "detailed description" tier for BLV users.
- [ACE Rule-Curation Framework Usefulness Audit](current/ace-framework-usefulness-audit-2026-06-18.md) finds the `sr-*`/`rg-*` rule set load-bearing but the helpful/harmful curation loop dormant/broken (tools parse the wrong file; `harmful` never nonzero; no pruning pass ever recorded). Repair-or-retire decision pending.
- [Roster + Workbench Identity Chip UX Assessment](current/roster-workbench-identity-ux-assessment-20260913.md) traces the workbench chip same-person-multiple-chips defect (grouped by raw `cluster_id`, not person) and the avatar-shows-wrong-face defect (crops the current item's face, not the cluster representative) to root cause with code refs, plus six roster UX questions (thumbnail size, face-group count, tags, person-level merge, click-name behavior, low-confidence CTA) and a completeness check against the corpus manifest.

## Archived Assessments

Completed, superseded, task-specific, and historical investigation notes live under `docs/assessments/archive/`.
