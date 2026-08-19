# UXW2-2. Honest review counts — face count matches shown faces; queue header tracks labelling

**Wave**: UX/UI wave 2 (orchestration task `MAINT-uxui-wave2-orch-20260818`, decision 5678) · **Date**: 2026-08-18 · **Author**: Claude (Fable 5)
**Target Branch**: `feature/uxw2-2` · **Worktree**: `context-alt-text-monorepo-uxw2-2` · **Baseline**: main @442d99f93
**Review Coverage Target**: 2 (adversarial `/review-parallel`: 1 local Claude + remote grok-4.6 + kimi-k3 reviewers, canon-cited)
**Diagnosis**: session scratchpad `diag/REPORT_B.md` (root causes with file:line evidence); prior art digest `diag/PRIOR_ART.md`
**Depends on**: none · **Blocks**: none

## Objective

TopClusterCard never claims more faces than it shows; `identity_count` reflects observed members when not truncated; memberless clusters never enter the review queue; the queue header count decrements as items are labelled without a refetch.

## Problem Statement (root cause, verified against main @442d99f93)

B5: `identity-clusters/TopClusterCard.tsx:95-107` renders `representatives.slice(0,4)` but prints `identity_count`; mapper `src/sovereign/mappers/class-cluster-response-mapper.php:251-282` `resolve_identity_count` returns the projected column even when observed rows are fewer (repair only at zero). `class-clusters-read-repository.php::list_top_unlabeled:221-258` filters on the stale `identity_count` column (E21-14-R3-GOLDENS-01/FRONTEND-02 deferred: zero-member clusters queued). B6: header count = `filteredQueue.length` (`ReviewQueue.tsx:439,950-953`) over four caches (`useSuggestionReviewQueries.ts:33-66`); person-commit drops only namePending; label path (`ClusterLabelingPanel.tsx:146-154`, `useClusterMutations.ts:50-56`) drops nothing and ReviewQueue is unmounted while the panel is open so `invalidateQueries` refetches nothing; backend suggestion feeds lag the outbox.

## Decisions (canon defaults recorded in decision 5678 — not re-litigated here)

- Count from what is rendered + "+N more" ([HAI-01], PRINCIPLES §11 unknown is designed).
- Zero-member clusters EXCLUDED from `top-unlabeled` (closes the E21-14 deferral).
- Header count is honest about scope (loaded items); never fabricate totals ([rg-015]).
- One shared `dropClusterFromReviewCaches(queryClient, clusterId)` used by commit/label/merge success ([REF-09], [DATA-01]).

## Constraints

- FE + PHP; no python contract change. Contract doc for `top-unlabeled` gains the invariant `identity_count ≥ representatives.length`, representatives non-empty.
- Repair triggers bounded per request ([rg-007]); no N+1 in the queue SQL ([RES-12]).
- Findings live in workbay-handoff by ID only; this plan tracks work, not finding status.
- No `Co-Authored-By` trailers. Full SHAs in handoff writes. Slice = one user-visible path, RED test first (`/tdd`).

## Slices

### Slice 1 — FE count reflects rendered faces (`TopClusterCard.tsx`, `TopClusterCard.test.tsx`)
- [x] RED: `identity_count=3`, 2 usable reps → "2 faces · +1 more"; missing-image rep not a blank tile.
- [x] Commit `fix(workbench): UXW2-2 face count reflects rendered faces`.
### Slice 2 — PHP `identity_count` honesty + memberless exclusion
- [x] RED `tests/Unit/ClusterResponseMapperTest.php`: projected 3/observed 2 (rn cap 4) → 2 + repair requested; projected 9/observed 4 → 9.
- [x] RED `tests/Unit/ClustersReadRepositoryTest.php`: cluster with 0 member rows not returned by `list_top_unlabeled`.
- [x] `docs/workbay/contracts/clustering-api.md` invariant. Commits `fix(sovereign): UXW2-2 identity_count reflects observed members`, `fix(sovereign): UXW2-2 exclude memberless clusters from top-unlabeled`.
### Slice 3 — FE cache drops (`suggestionProjection.ts`, `useSuggestionReviewMutations.ts`, label/merge success paths)
- [x] RED `useSuggestionReviewMutations.test.tsx`: after person-commit for X all four caches lack X; `ReviewQueue.test.tsx`: header decrements after panel round-trip without refetch.
- [x] Commit `fix(workbench): UXW2-2 drop labelled cluster from review caches`.

## Verification

`npm test`/lint/typecheck + `composer test` green; RED→GREEN evidence per slice; manual: label a face in the panel, close, header count −1; `GET recognition/clusters/top-unlabeled` never returns `representatives: []`.

## Prior art

E21-14-R3-GOLDENS-01/FRONTEND-02 (deferred zero-member queue rows — resolved here); E21-5-REVA-02 / dec 2494 (one atomic POST per card); TopClusterCard.test.tsx:170 earlier sighting; E21-17-R1-TS41-1 (`isValidQueueOrdinalPair`).

## Open questions

B6 backend synchronous suggestion resolution on label/commit (python) is deferred to a follow-up if the FE optimistic drop proves insufficient at runtime.
