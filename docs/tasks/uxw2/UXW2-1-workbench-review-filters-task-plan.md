# UXW2-1. Workbench review filters — single URL owner for `rq=` state

**Wave**: UX/UI wave 2 (orchestration task `MAINT-uxui-wave2-orch-20260818`, decision 5678) · **Date**: 2026-08-18 · **Author**: Claude (Fable 5)
**Target Branch**: `feature/uxw2-1` · **Worktree**: `context-alt-text-monorepo-uxw2-1` · **Baseline**: main @442d99f93
**Review Coverage Target**: 2 (adversarial `/review-parallel`: 1 local Claude + remote grok-4.6 + kimi-k3 reviewers, canon-cited)
**Diagnosis**: session scratchpad `diag/REPORT_D.md` (root causes with file:line evidence); prior art digest `diag/PRIOR_ART.md`
**Depends on**: none · **Blocks**: UXW2-4 (Slice 3 review-panel URL params share `setSearchParams` discipline)

## Objective

Review-queue filter chips (Close matches / Possible duplicates / bands / Clear filters) are stable: click → pressed AND `#/workbench?…rq=` reflects it; Next/Prev keeps it; click again → off; Clear filters clears kind AND band. One owner (URL), one write per action.

## Problem Statement (root cause, verified against main @442d99f93)

CONFIRMED by executable repro (7/7 symptom assertions fail on baseline, control passes): dual ownership of `rq=` — URL (`js/admin/hooks/useWorkbenchFilters.ts:46`) plus a `useState` mirror + URL→local effect in `js/admin/pages/workbench/ScanTabContent.tsx:85-124` — and same-tick double `setSearchParams` in `identity-clusters/ReviewQueue.tsx:726-746` (`onKindChange` + `onIndexChange(0)`) and `:1279-1281` (Clear filters). react-router 7.16 functional updater reads the render snapshot → last write wins → split-brain → chip self-deactivates on the next URL write, cannot activate when index>0, Clear filters leaves kind set.

## Decisions (canon defaults recorded in decision 5678 — not re-litigated here)

- URL is the single owner of `kind/band/index`; local mirror deleted ([DATA-14], [REF-09]).
- Reducer-style `dispatchQueue(action)` in `useWorkbenchFilters` with enum-keyed handler map (`set_kind|set_band|set_index|clear_filters|clamp_index`); kind/band/clear reset index inside the reducer; `pendingRef` write-through defends stray same-tick writes ([REF-02], [RLSE-06]).
- `rq=` grammar unchanged (`hooks/workbenchQueueUrl.ts`, `navigation/appLinks.ts` `APP_LINK_PARAMS.rq`).

## Constraints

- Frontend only (`apps/prototype-wp-alt-context/js/admin/**`, `docs/ux-maps/**`).
- Tests use a real `MemoryRouter` + unmocked `useWorkbenchFilters` ([TEST-19]); existing mocked ScanTabContent tests stay.
- [NAV-11] deep link round-trips chip state; [A11Y-21] live region kept; [NAV-07]/[INT-06] Clear filters clears both groups.
- Findings live in workbay-handoff by ID only; this plan tracks work, not finding status.
- No `Co-Authored-By` trailers. Full SHAs in handoff writes. Slice = one user-visible path, RED test first (`/tdd`).

## Slices

### Slice 1 — RED: repro tests pinned in-repo
- [x] `js/admin/hooks/__tests__/useWorkbenchFilters.rqDoubleWrite.test.tsx` (filename `rqDoubleWrite`, not `doubleWrite`): two writes in one `act` both land — RED on baseline.
- [x] `js/admin/pages/workbench/__tests__/ScanTabContent.reviewQueueUrl.test.tsx` (real router): chip → `aria-pressed` + `rq=assignment.all.0`; Next → still pressed `rq=assignment.all.1`; chip again → `rq` removed; band+kind → `rq=assignment.strong.0`; Clear filters → both unpressed; mount at `rq=merge.all.1` → pressed + second card — RED on baseline.
### Slice 2 — GREEN: single owner + one write per action
- [x] `useWorkbenchFilters.ts`: `dispatchQueue` reducer + `pendingRef`; `setQueueState` internal.
- [x] `ScanTabContent.tsx`: delete `queueIndex/queueKind/queueBand` state + mirror effect; read from `queueState`.
- [x] `ReviewQueue.tsx`: `handleFilterClick`/`handleBandClick` one callback each; `onClearFilters` prop; `ReviewQueue.test.tsx` harness updated.
- [x] `docs/ux-maps/workbench-operator-loop.uxmap.json`: `rq` on `workbench-scan`; `z-review-queue` zone `default|filtered_empty|drained|error`.
- [x] Commit `fix(workbench): UXW2-1 single URL owner for review-queue rq= state`.

## Verification

- `npm test`, `npm run lint`, `npm run typecheck` green in `apps/prototype-wp-alt-context`; new tests proven RED→GREEN ([TEST-15]).
- Manual: click Close matches; hash contains `rq=assignment`; Next keeps chip pressed.
- Gate: `/review-parallel` adversarial (canon-cited) → findings in handoff → `handoff_close_check(enforce=True)`.

## Prior art

E21-5 unified review queue plan §2 (`rq=` encoding; index lifted+mirrored = seed of the bug); E21-14 ReviewQueue chip findings; E21-11 dec 2249 (TanStack Proxy tracking); PR-31/PR-54 lifted index semantics.

## Open questions

None (URL-as-owner is the standing E21-5 decision).
