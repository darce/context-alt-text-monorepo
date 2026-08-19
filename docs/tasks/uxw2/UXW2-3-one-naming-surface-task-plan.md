# UXW2-3. One naming surface — NameFaceControl, single-gesture Save name, plain-language wording

**Wave**: UX/UI wave 2 (orchestration task `MAINT-uxui-wave2-orch-20260818`, decision 5678) · **Date**: 2026-08-18 · **Author**: Claude (Fable 5)
**Target Branch**: `feature/uxw2-3` · **Worktree**: `context-alt-text-monorepo-uxw2-3` · **Baseline**: main @442d99f93
**Review Coverage Target**: 2 (adversarial `/review-parallel`: 1 local Claude + remote grok-4.6 + kimi-k3 reviewers, canon-cited)
**Diagnosis**: session scratchpad `diag/REPORT_B.md` (root causes with file:line evidence); prior art digest `diag/PRIOR_ART.md`
**Depends on**: none · **Blocks**: UXW2-5 (FE picker slice adopts NameFaceControl), UXW2-6 (lightbox naming reuses it)

## Objective

Naming a face is one gesture (type → Enter/Save name) and always creates/binds a roster person; Review Suggestions, the label panel and the Library pane share one control; workbench review surfaces stop saying "cluster".

## Problem Statement (root cause, verified against main @442d99f93)

B1: `identity-clusters/PersonCommitControl.tsx:106-158` two-phase popover combobox; `personCommitCopy.ts:13` `JUST_LABEL_COPY` promises no roster write but `class-cluster-label-service.php:117-123` write-through creates a person anyway (E21-5 plan §93 stale post-E21-9). B4: three naming UIs (`ClusterEditForm`, `ClusterLabelingPanel` combobox, `PersonCommitControl`) with reserved-label check ×4 sites. B2: `ClusterReviewPanel.tsx:116` "Review Cluster", `ScanTabContent.tsx:195`, `SuggestionCards.tsx:244`, `TopClusterCard.tsx:196,241`, `MergeSuggestionCard.tsx:102-156`, `ReviewQueue.tsx:1923`; no say/don't-say list; `banned-vocabulary.test.tsx` does not ban "cluster".

## Decisions (canon defaults recorded in decision 5678 — not re-litigated here)

- Naming ALWAYS binds a roster person; retire "Just label"; primary label "Save name" ([INT-06], PRINCIPLES §6).
- Shared presentational `NameFaceControl` (from `ClusterEditForm` pattern) with injectable `onCommit(resolution)`; single reserved-label module ([REF-10], [REF-26]).
- Vocabulary: don't say cluster/identities/instances; say faces / face group (unnamed) / person ([NAV-13]). Roster-page files are UXW2-4's; dashboard/jobs/ops out of scope.

## Constraints

- Frontend only. Server paths unchanged. `docs/ux-maps/workbench-2pane.md` gains a Vocabulary say/don't-say section BEFORE the sweep; `banned-vocabulary.test.tsx` extended for workbench review surfaces.
- Findings live in workbay-handoff by ID only; this plan tracks work, not finding status.
- No `Co-Authored-By` trailers. Full SHAs in handoff writes. Slice = one user-visible path, RED test first (`/tdd`).

## Slices

### Slice 1 — `feat(workbench): UXW2-3 NameFaceControl + single-gesture Save name`
- [x] RED `PersonCommitControl.test.tsx`: novel name + Enter → `newEntryName`; existing name + Enter → `rosterEntryId`; no "Just label" control.
- [x] New `NameFaceControl`; `PersonCommitControl.tsx` inline input; `personCommitCopy.ts` updated.
### Slice 2 — `refactor(workbench): UXW2-3 adopt NameFaceControl in label panel + Library pane`
- [x] `ClusterLabelingPanel.tsx`, `IdentityClusterItem.tsx`/`ClusterEditForm.tsx`; single reserved-label module; tests updated only where DOM contract changed.
### Slice 3 — `fix(workbench): UXW2-3 plain-language wording for review surfaces`
- [x] Vocabulary table in `docs/ux-maps/workbench-2pane.md`; string sweep of the files above; `banned-vocabulary.test.tsx` bans `cluster` on workbench review surfaces; `ClusterReviewPanel.test.tsx` heading updated.

## Verification

`npm test`/lint/typecheck green; RED→GREEN per slice; manual: type a new name in Review Suggestions, press Enter → roster shows the person; no visible "cluster" in the workbench review flow.

## Prior art

E21-5 dec 2719 (`commitClusterToRosterEntry`); E21-9 label→person write-through; UXP-3 `buildNamingOptions`; UXP-4 banned vocabulary; E21-15-BR-22/25 (`isHumanLabeledTarget`, never surface `cluster-7`).

## Open questions

None.
