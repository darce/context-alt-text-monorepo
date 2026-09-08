# dux-w2v-f verdicts

## Probe 1 — BR-82 fixture (file read)

Current file: `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/mediaFooterSinglePrimary.dom.test.tsx`

- Shared fixture `assignmentSuggestion` has `cluster_identity_count: 3` (line 150).
- Helper `oneAssignment()` (lines 247–253) mocks `fetchPendingSuggestions` with that multi-face suggestion.
- BR-82 test `'bulk-tray open (committable selection)'` (lines 436–461) calls `oneAssignment()`, then:
  - `user.click(... 'Review details')`
  - `findByRole('list', { name: 'Stored faces for Alex' })`
  - then opens the tray (`acx-review-select` + `'Review selection'`).
- No `cluster_identity_count: 1` and no inline single-face mock in this file.

HAI-17 is exercised and satisfied, not bypassed.

Git refs `fix/dux-w2r2`, `fix/dux-w2d6c`, and merge `3a47246b7` are **absent** in this history-stripped sandbox (`git rev-parse` fails; only `master` exists).

## Probe 3 — d6c leftovers in the current file

Grep of this file for `cluster_identity_count: 1`, `single-face`, and unused `oneAssignment` deletions: **none**.

Helpers in use: `emptyQueues`, `oneAssignment` (7 call sites), `pending`, `markerCount`, `rosterCommitFixture`. Shared `assignmentSuggestion` is the only assignment fixture and is multi-face.

Possible adjacent-hunk debris (not a functional d6c leftover): `const rosterCommitFixture` (lines 22–31) sits between import blocks; `import { HTTPError }` follows it (line 32). HTTPError is used (retired-head 404). No orphaned single-face mock, unused variable, dead helper, or stale comment describing the d6c bypass.

## Probe 5 — sibling DUX-W2R2-RV-03

Present at lines 493–523: `'DUX-W2R2-RV-03: gate lift while tray open keeps one accent; bulk stays in tab order'`.
Calls `oneAssignment()` (multi-face). Opens tray first (gated: accent stays on Yes, bulk `aria-disabled`), then clicks `'Review details'`, awaits `'Stored faces for Alex'`, then asserts bulk becomes the single accent. Depends on the multi-face HAI-17 scenario.

## Probe 2 — vitest

Command: `cd apps/prototype-wp-alt-context && npx vitest run js/admin/pages/workbench/__tests__/mediaFooterSinglePrimary.dom.test.tsx`

Observed output:
```
✓ js/admin/pages/workbench/__tests__/mediaFooterSinglePrimary.dom.test.tsx (13 tests) 1133ms
Test Files  1 passed (1)
     Tests  13 passed (13)
```
Exit code: 0. Failures: 0.

## Probe 4 — r2 vs d6c assertion diff

`git show fix/dux-w2r2:<path>` → `fatal: invalid object name 'fix/dux-w2r2'.`
`git show fix/dux-w2d6c:<path>` → `fatal: invalid object name 'fix/dux-w2d6c'.`
`git show 3a47246b7` → unknown revision.
No remotes. Sandbox is history-stripped / remote-severed. Comparison not performed; no vanished d6c assertion named.

FINDINGS_BEGIN
FINDING: DUX-W2-INT-RV-16
VERDICT: sustained
EVIDENCE: BR-82 uses multi-face `oneAssignment()` (`assignmentSuggestion.cluster_identity_count: 3`). Gate is exercised: click 'Review details', await list 'Stored faces for Alex', then open tray — not a single-face bypass. `cd apps/prototype-wp-alt-context && npx vitest run js/admin/pages/workbench/__tests__/mediaFooterSinglePrimary.dom.test.tsx` → 13 passed / 0 failed, Test Files 1 passed, exit 0. No d6c single-face mock leftover. Sibling DUX-W2R2-RV-03 present and also `oneAssignment()` + stored-face disclosure. Original hang (single-face fixture + wait for a list it never renders) cannot occur.
FINDING: DUX-W2V-F-NEW-1
VERDICT: not_sustained
EVIDENCE: no d6c assertion lost could be named. `git show fix/dux-w2r2:<path>` and `git show fix/dux-w2d6c:<path>` fail (`fatal: invalid object name`); merge `3a47246b7` unknown; no remotes in this history-stripped sandbox. Current file has 13 tests matching claimed 13/13; no `cluster_identity_count: 1` leftover. Line-by-line d6c-vs-r2 assertion diff was impossible.
FINDINGS_END
