# E21. Public MVP UX/UI Polish

> **Metadata**
>
> - **Date**: 2026-07-04
> - **Author**: Claude Fable 5 (claude-fable-5)
> - **Epic Short ID**: E21
> - **Target Version**: v0.4.1
> - **Status**: planned — decomposed from [public-mvp-ux-polish-roadmap-2026-07-04.md](../../roadmaps/public-mvp-ux-polish-roadmap-2026-07-04.md) (planning-review pass, run `planrev-roadmap-realign-20260704-01`)
> - **Grounding**: WBUX-1 ([workbench-ui-refactor-assessment-2026-07-04.md](../../assessments/current/workbench-ui-refactor-assessment-2026-07-04.md)) + WBUX-2 ([roster-dashboard-workbench-ux-assessment-2026-07-04.md](../../assessments/current/roster-dashboard-workbench-ux-assessment-2026-07-04.md))

## Goal

Take the public demo's WordPress admin surfaces (Workbench, Roster, Dashboard) from "functionally live" to **polished public MVP**: one status surface per page, one primary CTA per screen state, a real design-token system, person-first roster, and a coherent cross-surface link contract — without changing backend contracts or regressing data-sovereignty invariants.

## Hard Constraints

- **Data sovereignty (must not regress)**: cluster/person/member/findings display renders offline from the local WP projection (`acx_clusters`, `acx_persons`, `acx_identity_members`); curation writes queue to the outbox; compute (scan/cluster) stays remote and fails fast when the breaker is open. Acceptance contract: WBUX-1 §5 invariants table.
- **No backend contract changes**: every task consumes existing endpoints and `data_source` markers (rg-015). Bulk-merge atomicity is handled as progressive client UI, not a new batch endpoint.
- **Deep-link compatibility**: `?tab=`, `?overlay=`, `?cluster=` keep redirect shims until e2e specs migrate (E21-10 owns the migration).
- **Design rules as gates**: sr-004 (icon+color+word status), sr-007 (centralized status enums), sr-008 (grouped context/params), rg-002, rg-003 (zero-state reachability).

## Phases

| Phase | Theme | Tasks | Rationale (impact order) |
| --- | --- | --- | --- |
| 1 | Status truth & dead-weight deletion | E21-1, E21-2, E21-3 | First-impression surfaces; mostly deletion |
| 2 | Design-token foundation | E21-4 | Preparatory (Fowler); one visual re-baseline |
| 3 | Review flow unification | E21-5, E21-6, E21-7 | The demo's core loop |
| 4 | Person-first roster & link contract | E21-9, E21-10 (+ E15-17 s3–4 under its existing plan) | Curation depth; removes duplicate surface |
| 5 | Structural enablers | E21-11 | Velocity + regression resistance; invisible to visitors |

Phase 0 (launch completion) stays under E15/E15-29. Phase R (planning-surface realignment) runs as MAINT doc slices, not epic tasks.

## Task Decomposition

| Task | Title | Depends on | Task Plan |
| --- | --- | --- | --- |
| E21-1 | Sync status view-model + single status strip | — | [E21-1](../../tasks/21.0/E21-1-sync-status-view-model-task-plan.md) |
| E21-2 | Dashboard cull pass | — (CTA retargeting waits on E21-10) | [E21-2](../../tasks/21.0/E21-2-dashboard-cull-task-plan.md) |
| E21-3 | Confirm-tab removal + Advanced drawer | E21-1 | [E21-3](../../tasks/21.0/E21-3-confirm-tab-removal-task-plan.md) |
| E21-4 | Design-token system + sr-004 sweep | — | [E21-4](../../tasks/21.0/E21-4-design-token-system-task-plan.md) |
| E21-5 | Unified review queue + person-commit | E21-1, E21-4 | [E21-5](../../tasks/21.0/E21-5-unified-review-queue-task-plan.md) |
| E21-6 | Media step compaction | E21-1, E21-4 | [E21-6](../../tasks/21.0/E21-6-media-step-compaction-task-plan.md) |
| E21-7 | Offline fail-fast + read-only mode | E21-1 | [E21-7](../../tasks/21.0/E21-7-offline-fail-fast-task-plan.md) |
| E21-9 | Roster Clusters-tab retirement, person-first roster | E21-5, E15-17 s3–4 | [E21-9](../../tasks/21.0/E21-9-roster-person-first-task-plan.md) |
| E21-10 | Cross-surface link contract + shim/spec migration | E21-9 | [E21-10](../../tasks/21.0/E21-10-cross-surface-link-contract-task-plan.md) |
| E21-11 | Workbench context decomposition + phase strategy map | E21-1 | [E21-11](../../tasks/21.0/E21-11-workbench-context-decomposition-task-plan.md) |

E21-8 is intentionally unassigned: E15-17 slices 3–4 execute under the existing [E15-17 task plan](../../tasks/15.0/E15-17-roster-person-review-scrub-workspace-task-plan.md) to avoid duplicate ownership.

## Exit Criteria

Success criteria are owned by the roadmap §8 and repeated per-task; the epic closes when all ten tasks pass `handoff_close_check(enforce=True)` and the roadmap's success checklist is verifiable on the live demo.

## Verification

Shared harnesses: `tests/e2e/a11y/workbench-axe.spec.ts`, `tests/e2e/visual/workbench-visual.spec.ts` (re-baseline once at E21-4), `tests/e2e/evidence/workbench-evidence.spec.ts`, `js/admin/styles/tokens/__tests__/workbench-tokenization.test.ts`, per-component unit suites. Per-phase evidence captured against the live demo URL.
