# UXW2-2 FE r4 report

Cite commits by subject. Subjects verified with `git log --format=%H --fixed-strings --grep="<subject>"` (count 1 each). File:line cites re-derived with `sed -n '<N>p'` after the last code commit.

Canon (grepped): DATA-14, REF-25, RLSE-04, RLSE-06, TEST-06, TEST-15, rg-015.

Not closed (follow-up owns): R5-08 ux-map `z-identity-preview`, R5-09 two simultaneous `Resync` names, R5-11 / R3-11 i18n literal msgids.

## Verify (item 8)

- Root `REPORT.md`: gone.
- `docs/tasks/uxw2/UXW2-2-r4-fix-report.md`: not on this branch. Nothing to strip. Did not invent a gitignored-contract claim.
- `docs/tasks/uxw2/UXW2-2-fe-report.md`: one 40-hex line removed; subjects remain.
- `docs/tasks/uxw2/UXW2-2-r1-fix-report.md`: brief said clean; it was not (40 hex). Stripped to subjects so `git grep -cE '[0-9a-f]{40}' -- docs/tasks/uxw2/` prints nothing.

## Closed

| Finding | Subject | RED (verbatim) |
|---|---|---|
| R7-01 | `fix(fe): UXW2-2-R7-01 page-scoped repair count on findings panel` | `Unable to find an element with the text: 3 groups elsewhere are missing face data.` |
| R7-02 | `fix(fe): UXW2-2-R7-02 latch repair announce on every first-mount branch` | `expected 4 to be 1` |
| R7-03 | `test(fe): UXW2-2-R7-03 exact gated-copy sentences with distinct counts` | same Math.max line as R7-01 |
| R7-04 | `fix(fe): UXW2-2-R7-04 do not announce 0 of 0 on filtered-empty` | `Expected element not to have text content: 0 of 0` / `Received: 0 of 0` |
| R7-05 | `test(fe): UXW2-2-R7-05 UXW2-2-R7-06 pin invalidate and ReviewQueue header` | `expected "invalidateQueries" to be called with arguments: [ { queryKey: [ 'clusters', …(1) ] } ]` |
| R7-06 | same | `expected '2 left to review on this page' to be '1 left to review on this page'` |
| R7-07 | `fix(fe): UXW2-2-R7-07 reconcile full-accept eviction with accepted_count` | `expected [] to deeply equal [ 'name-1', 'name-2' ]` |
| R7-07 follow | `fix(fe): UXW2-2-R7-07 disagreement fallback also invalidates review caches` | empty-cache full accept skipped projection invalidate |
| R5-06 | `test(fe): UXW2-2-R5-06 pin all five cluster-mutation invalidation keys` | `expected "vi.fn()" to be called at least once` |

## Cites (sed after last code commit)

- `WorkbenchFindingsPanel.tsx:424` `gatedClusterCopy(`
- `WorkbenchFindingsPanel.tsx:430` `? repairGatedCount(zeroEvidenceClusterCount, counts.unlabeledClusters)`
- `WorkbenchFindingsPanel.tsx:433` `previews.length,`
- `representativeVocabulary.ts:13` `repairGatedCount` — contract unchanged. Call site computes page-scoped count (DATA-14, rg-015).
- `representativeVocabulary.ts:20` `if (servedCount === 0)`
- `ReviewQueue.tsx:585` `(!findings.repairPending && repairAnnouncedRef.current)`
- `ReviewQueue.tsx:603` / `:607` latch on error and filtered-empty
- `ReviewQueue.tsx:621` drain clears latch
- `ReviewQueue.tsx:1043` `filteredEmptyWithWork` in the position guard
- `useSuggestionReviewMutations.ts:349` `applySuccessSideEffects` `acceptName` (the path ReviewQueue actually takes)
- `useSuggestionReviewMutations.ts:1038` `matched.length !== data.accepted_count`
- `useClusterMutations.ts:50` identities invalidate; `:57` mergePending (TEST-15 mutant target)

## TEST-15 notes

- R7-01 / R7-03: `Math.max(previews.length, zeroEvidenceClusterCount)` → elsewhere test RED. Truncated/plain with all three counts non-zero stay GREEN (servedCount only branches on `=== 0`).
- R7-02: drop filtered/error latch → `expected 4 to be 1`.
- R7-05: delete top-unlabeled invalidate → spy RED. Without that assert the partial-accept test stayed green.
- R7-06: drop `applySuccessSideEffects` acceptName eviction → header stays `2 left`. Mutating `acceptNameMutation.onSuccess` (the r3 sibling-hook target) left this test GREEN.
- R5-06: `refetchType: 'none'` on `mergePending` RED. Same mutant on `clusters.labels()` stays GREEN because `clusters.all` still refetches that observer.

## Suite

`npx vitest run` from `apps/prototype-wp-alt-context`:

`Test Files  212 passed (212)`
`Tests  2395 passed (2395)`

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

## Undone

- ReviewQueue has no chrome that calls `mutations.bulkAccept`. R7-06 pins header decrement via `Accept suggestion` → `applySuccessSideEffects`. The r3 sibling-hook R5-07 test was replaced here; the r3 report still describes the sibling-hook proof and was not edited (out of ownership).
- `refetchType: 'none'` on `clusters.labels()` still survives because `clusters.all` is a prefix. R5-06 is not 5/5 independent kills.
- `UXW2-2-r4-fix-report.md` is absent. The mirror-overlay gitignore sentence was not rewritten because the file is not here.
- `UXW2-2-r1-fix-report.md` still has an `(empty)` Undone section; only 40-hex was stripped.
- R5-08, R5-09, R5-11 / R3-11 remain open on purpose.
