# UXW2-3-R2 — close R2 findings + remaining R1s

Lane cwd. Commits cited by subject line only.

## Closure table

| Finding | Commit subject | Test | TEST-15 mutant / RED line |
| --- | --- | --- | --- |
| R2-01 | `fix(fe): UXW2-3-R2-01 overlay filters query; confirm binds chosen id` | NameFaceControl R2-01 / R2-01a / R2-01b | `Unable to find an element with the text: Zed Offslice`; `expected "vi.fn()" to be called with arguments` Ada vs Grace; `Number of calls: 0` on second-id bind |
| R2-02 | `fix(fe): UXW2-3-R2-02 sync submittingRef across remote guard` | `{Enter}{Enter}` 50ms delayed list | `expected "vi.fn()" to be called 1 times, but got 2 times` |
| R2-04 + R1-14 + R1-02(panel) | `fix(fe): UXW2-3-R2-04 R1-14 R1-02 panel roster error + invalidate + live region` | roster alert; invalidate roster.entries; 400ms filtered announce | `Unable to find role="alert"`; invalidateQueries missing `roster.entries`; naming status length 1 before debounce |
| R2-07 + R1-08 + R1-12 | `fix(fe): UXW2-3-R2-07 R1-08 R1-12 R1-16 unify person bind; drop dead onLabel` | ✓-person bind; initialLabel Enter; no form; per-state header; source pin | `Expected the element to have value: Alex Carter Received:`; `Number of calls: 0` on person ✓; `expect(queue).not.toMatch(/onLabel:\s*_onLabel/)` |
| R1-16 | **partial** — same subject as R2-07; residual R1-16d / R1-16h mutant rows from the R1 report are not claimed (see Undone) | not re-verified | n/a |
| R2-03 | `fix(fe): UXW2-3-R2-03 APG overlay close + option reject without nested buttons` | aria-expanded toggle; Delete reject | `aria-labelledby` Received: null; Delete `Number of calls: 0` |
| R2-06 + R1-05 + R1-06 + R1-10 | `fix(fe): UXW2-3-R2-06 R1-05 R1-06 R1-10 copy sweep, banned words, gettext literals` | banned sweep + gettext-literals | Mutant: `Unable to load unlabeled clusters.` in ReviewQueue; `__(\s*[A-Z_][A-Z0-9_]*\s*,` |
| R1-03 | `fix(fe): UXW2-3-R1-03 compile SCSS mixin onto shared naming prefixes` | name-face-surface compile | `.acx-person-commit__suggestions-overlay missing`; `@include` length 3 got 2 |
| R2-08 | `docs(uxmap): UXW2-3-R2-08 face-group/people wording on workbench-2pane` | n/a (JSON SSOT + render) | n/a |
| R2-05 | this rewrite | n/a | n/a |

Follow-ups (same subjects as finding they serve):
- `fix(fe): UXW2-3-R2-01 typecheck NameFaceControl test props`
- `fix(fe): UXW2-3-R2-03 IdentityClusterList overlay option query`
- `fix(fe): UXW2-3 lint cleanup on naming-surface tests and unused imports`

## RED evidence (verbatim)

- R2-01: `Unable to find an element with the text: Zed Offslice`
- R2-01a: `expected "vi.fn()" to be called with arguments: [ { kind: 'roster', …(2) } ]` Received Ada Lovelace / rosterEntryId 1
- R2-01b: `Number of calls: 0`
- R2-02: `expected "vi.fn()" to be called 1 times, but got 2 times`
- R2-04: `Unable to find role="alert"`
- R2-03: `Expected the element to have attribute: aria-labelledby=... Received: null`
- R1-03 mutant drop `@include`: `expected [ …(2) ] to have a length of 3 but got 2`

## Gate evidence (suite green, lint RED)

Prover re-ran `npm test && npm run typecheck && npm run lint` at the r2 HEAD:

```
Test Files  209 passed (209)
Tests  2403 passed (2403)
typecheck ok
✖ 118 problems (117 errors, 1 warning)
```

Item-1 baseline (subject `sync: mirror local feature/uxw2-1`): `✖ 120 problems (119 errors, 1 warning)`. settingsApi not in the wave diff. Partition at HEAD: 114 errors + 1 warning in files the wave did not touch (pre-existing); 3 errors in wave-touched files this lane does not own (`SuggestionCards.tsx:51 func-style`, `useLiveReviewTarget.ts:34` and `:132` `@typescript-eslint/no-redundant-type-constituents`). Net 119 → 117 errors. The 117 are not a silent-green gate.

Correction: the round-2 diagnosis of the labeling-panel opener was wrong. The opener was removed by this wave's own first commit (`feat(workbench): UXW2-3 NameFaceControl + single-gesture Save name`), not by round 2.

## Superseded (round 2, before the last fix)

Stale r2 observation (2026-08, before `fix(fe): UXW2-3-R2-03 IdentityClusterList overlay option query` and the prover re-run). Kept as history, not as the gate claim.

```
Test Files  1 failed | 208 passed (209)
      Tests  1 failed | 2402 passed (2403)
   Duration  481.62s
```

Fail: `IdentityClusterList` `getByRole('button', { name: /Ada Lovelace \(Group\)/ })` after R2-03 option-not-button. Isolated re-run after that fix: 23 passed; 1 timed out (`resolves an inline prompt on every one of 60 unlabeled cards`, 5s) — that case passed in the full 481s run. R2 lint paste under the old GREEN heading: `✖ 118 problems (117 errors, 1 warning)` (same RED lint, mislabeled).

## Files changed (this r2)

- `NameFaceControl.tsx` — query-filtered overlay; chosen-row bind; isOpen/Escape; option not nested buttons; Delete reject
- `ClusterLabelingPanel.tsx` — submittingRef; roster error+Retry; roster.entries invalidate; NameFaceControl live region; person ✓ → resolveCommit; initialLabel; per-state header
- `ReviewQueue.tsx` — drop dead `onLabel`; gettext literals; unlabeled-faces copy
- `ScanTabContent.tsx` — drop `open_label` dispatch
- `PersonCommitControl.tsx` — gettext literals
- `MergeUndoBanner.tsx` / `clusterMutationUtils.ts` — surviving cluster copy → group
- `_name-face.scss` + `--acx-opacity-*` tokens; mixin compile test
- UX map JSON + render
- Tests: NameFaceControl, ClusterLabelingPanel, ClusterEditForm, banned-vocabulary, gettext-literals, IdentityClusterList, name-face-surface

## Undone / OPEN

- Full `npm test` not re-run after the IdentityClusterList option query + lint-cleanup commits. Last complete suite: 2402 passed / 1 failed (that fail is the one those commits fix).
- Isolated IdentityClusterList 60-card batch test 5s timeout not re-proven here (passed in the 481s full run).
- `open_label` remains on `ClusterPanelContext` reducer (only the ScanTab/ReviewQueue dead wire removed).
- R1-16d / R1-16h mutant rows from the R1 report are **not** claimed — not re-verified this lane.

## Final HEAD

`docs(plan): UXW2-3-R2-05 rewrite fix-lane report at task path` (this commit).
