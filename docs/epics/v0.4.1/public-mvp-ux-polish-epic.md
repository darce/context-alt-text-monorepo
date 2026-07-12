# E21. Public MVP UX/UI Polish

> **Metadata**
>
> - **Date**: 2026-07-04
> - **Author**: Claude Fable 5 (claude-fable-5)
> - **Epic Short ID**: E21
> - **Target Version**: v0.4.1
> - **Status**: planned — decomposed from [public-mvp-ux-polish-roadmap-2026-07-04.md](../../roadmaps/public-mvp-ux-polish-roadmap-2026-07-04.md) (planning-review pass, run `planrev-roadmap-realign-20260704-01`) · **re-baselined 2026-07-12** (planning review `planrev-e21-uxui-20260712-01`, verdict `conditional_pass`; findings `UXPR-01..15` live in handoff — query, do not mirror)
> - **Grounding**: WBUX-1 ([workbench-ui-refactor-assessment-2026-07-04.md](../../assessments/current/workbench-ui-refactor-assessment-2026-07-04.md)) + WBUX-2 ([roster-dashboard-workbench-ux-assessment-2026-07-04.md](../../assessments/current/roster-dashboard-workbench-ux-assessment-2026-07-04.md))

## Goal

Take the public demo's WordPress admin surfaces (Workbench, Roster, Dashboard) from "functionally live" to **polished public MVP**: one status surface per page, one primary CTA per screen state, a real design-token system, person-first roster, and a coherent cross-surface link contract — without changing backend contracts or regressing data-sovereignty invariants.

## Hard Constraints

- **Data sovereignty (must not regress)**: cluster/person/member/findings display renders offline from the local WP projection (`acx_clusters`, `acx_persons`, `acx_identity_members`); curation writes queue to the outbox; compute (scan/cluster) stays remote and fails fast when the breaker is open. Acceptance contract: WBUX-1 §5 invariants table.
- **No backend contract changes**: every task consumes existing endpoints and `data_source` markers (rg-015). Bulk-merge atomicity is handled as progressive client UI, not a new batch endpoint.
- **Deep-link compatibility**: `?tab=`, `?overlay=`, `?cluster=` keep redirect shims until e2e specs migrate (E21-10 owns the migration).
- **Design rules as gates**: sr-004 (icon+color+word status), sr-007 (centralized status enums), sr-008 (grouped context/params), rg-002, rg-003 (zero-state reachability).
- **Accessibility floor (WCAG 2.2 AA)**: admin surfaces target WCAG 2.2 AA (self-assessed; per-page scope listed at epic close — [A11Y-22]). Every phase's acceptance includes a keyboard-only walkthrough of the changed flow and aria-live/announcement coverage for every async status surface ([A11Y-11]/[A11Y-21]); axe is the floor, not the gate ([A11Y-23]). Any drag interaction ships with a click/keyboard alternative ([A11Y-15]); destructive bulk ops are reversible or confirmed ([A11Y-18]).

## Phases

| Phase | Theme | Tasks | Rationale (impact order) |
| --- | --- | --- | --- |
| 1 | Status truth & dead-weight deletion | E21-1, E21-2, E21-3, E21-12 | First-impression surfaces; mostly deletion + the standing rg-003 fix |
| 2 | Design-token foundation | E21-4 | Preparatory (Fowler); one visual re-baseline |
| 3 | Review flow unification | E21-5, E21-7 (E21-6 done 2026-07-08) | The demo's core loop |
| 4 | Person-first roster & link contract | E21-9, E21-10 (+ E15-17 s3–4 under its existing plan) | Curation depth; removes duplicate surface |
| 5 | Structural enablers | E21-11 | Velocity + regression resistance; invisible to visitors |

Phase 0 (launch completion) stays under E15/E15-29. Phase R (planning-surface realignment) runs as MAINT doc slices, not epic tasks.

## Task Decomposition

| Task | Title | Depends on | Task Plan |
| --- | --- | --- | --- |
| E21-1 | Sync status view-model + single status strip | — | authored at `make task-start` |
| E21-2 | Dashboard cull pass | — (CTA retargeting waits on E21-10) | authored at `make task-start` |
| E21-3 | Confirm-tab removal + Advanced drawer | E21-1 | authored at `make task-start` |
| E21-4 | Design-token system + sr-004 sweep | — | authored at `make task-start` |
| E21-5 | Unified review queue + person-commit | E21-1, E21-4 | authored at `make task-start` |
| E21-6 | Media step compaction | E21-1, E21-4 (landed out of order) | **done** 2026-07-08 — [E21-6](../../tasks/21.0/E21-6-media-step-compaction-task-plan.md) |
| E21-7 | Offline fail-fast + read-only mode | E21-1 | authored at `make task-start` |
| E21-9 | Roster Clusters-tab retirement, person-first roster | E21-5, E15-17 s3–4 | authored at `make task-start` |
| E21-10 | Cross-surface link contract + shim/spec migration | E21-9 | authored at `make task-start` |
| E21-11 | Workbench context decomposition + phase strategy map | E21-1 | authored at `make task-start` |
| E21-12 | Roster zero-state reachability (rg-003) + Retention discoverability | — (Phase 1) | authored at `make task-start` |
| WBUX-3 | Bulk Florence-describe with honest progress (epic lineage) | — | **done** 2026-07-08 — [WBUX-3](../../tasks/21.0/WBUX-3-bulk-describe-progress-task-plan.md) |
| WBUX-4 | Bulk-describe integration loop (drafts apply, reclaim, SSE cull) | WBUX-3 | **done** 2026-07-09 — [WBUX-4](../../tasks/21.0/WBUX-4-bulk-describe-integration-loop-task-plan.md) |

Task plans for undone tasks are authored on the feature branch at `make task-start TASK=<id>` (Startup Protocol step 6) — the table intentionally carries no dead links. E21-8 is intentionally unassigned: E15-17 slices 3–4 execute under the existing [E15-17 task plan](../../tasks/15.0/E15-17-roster-person-review-scrub-workspace-task-plan.md) to avoid duplicate ownership.

### Re-baseline (2026-07-12)

Planning review `planrev-e21-uxui-20260712-01` re-anchored this epic against live `main` (all WBUX-1/2 diagnoses re-verified still present). Landed since decomposition: **E21-6** (merged 2026-07-08 *before* its declared E21-1/E21-4 dependencies — the Phase 2 "one visual re-baseline" premise no longer holds; snapshots still re-baseline once at E21-4), **WBUX-3/WBUX-4** (bulk describe + run-apply), **E20-5/E20-10** (Description History page + roster person workspace). Scope amendments:

| Task | Amendment |
| --- | --- |
| E21-1 | Consolidates **five** job-status surfaces — `BulkDescribeProgress` (`MediaSelection.tsx`) added by WBUX-3 is the fifth; describe-run status joins the single view-model. Banned-strings list gains "Source version", "projected instances", "Curriculum" (now shipping on `PersonWorkspacePanel.tsx`) and its test covers **all** `js/admin` pages, including Roster and Description History. |
| E21-2 | Owns the dashboard cull rows verbatim from WBUX-2 §4, including the dead `before_grid` branch and heading-case normalization. |
| E21-4 | Sweep scope includes the Description History page and `PersonWorkspacePanel`. The plan opens with a **design-direction preamble** — grey temperature choice ([COL-05]), anchor colour + dominant/support/accent roles ([COL-03]), value-ranked ramps ([COL-04]), modular type-scale rationale ([TYPE-05]) — so tokens encode a chosen direction, not framework defaults ([LAY-10]). Every token pair ships with 4.5:1 / 3:1 contrast acceptance on real grounds ([A11Y-01]). |
| E21-5 | Owns CTA hierarchy between "Analyze selected" and "Describe with AI" in the media footer (one primary per screen state). Also owns the `DebugMetricsPanel` dev-flag gate and the hard-examples "coming soon" chip. Acceptance includes the state matrix (loading/empty/error/offline × focus + announcement — [A11Y-24]) and undo-toast announcement ([A11Y-21]). |
| E21-9 | Every drag operation (face scrubber, member fix) ships a click/keyboard alternative ([A11Y-15]); hover-only selection affordances become always-visible ([A11Y-14]). Progressive bulk merge gets live-region progress + designed mid-sequence-failure state. |
| E21-10 | Link vocabulary extends to the Description History surface (`#/description-history?run=<id>`); the cross-surface model becomes "Workbench decides, Roster curates, Dashboard orients, **History audits & applies**". |
| E21-12 | **New, Phase 1**: always-visible person list + `Add Person` + designed empty state on Roster (standing rg-003 violation; `RosterPage.tsx` default mode currently unmounts `RosterEntriesSection`). Independent of E21-5/E15-17 — pulled forward from E21-9. Also resolves the Retention discoverability decision (menu item vs dashboard footer link). |

## Exit Criteria

Success criteria are owned by the roadmap §8 and repeated per-task; the epic closes when all remaining tasks pass `handoff_close_check(enforce=True)` and the roadmap's success checklist is verifiable on the live demo.

Outcome criteria (behavior, not output — [PROD-01]/[PROD-07]): (1) a first-time visitor completes scan → review → first named person **unaided** in a scripted walkthrough on the live demo, with time-to-first-named-person recorded as the epic's before/after metric; (2) the same core loop passes a keyboard-only + screen-reader walkthrough ([A11Y-23]). A scripted first-visitor session runs after Phase 1 lands and **before** Phase 3 construction is funded ([PROD-03]/[PROD-12]) — its findings re-rank Phases 3–4.

## Verification

Shared harnesses: `tests/e2e/a11y/workbench-axe.spec.ts`, `tests/e2e/visual/workbench-visual.spec.ts` (re-baseline once at E21-4), `tests/e2e/evidence/workbench-evidence.spec.ts`, `js/admin/styles/tokens/__tests__/workbench-tokenization.test.ts`, per-component unit suites. Per-phase evidence captured against the live demo URL.

Gap being closed (verified 2026-07-12): the repo currently has **zero** keyboard-navigation and **zero** aria-live/announcement tests. E21-1 (first Phase 1 task) adds the shared harness — Playwright keyboard-walk pattern (`.press()`/`toBeFocused()`) and live-region assertions (`role="status"`/`aria-live`) — and every subsequent task extends it to its changed flows. Axe alone does not gate any E21 task.
