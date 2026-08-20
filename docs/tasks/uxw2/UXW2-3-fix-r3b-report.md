# UXW2-3-fix r3b — guards, surfaces, lint, report truth

Commits by subject. No 40-hex SHAs.

## Items

| Item | Finding ids | Commit subject | Tests | TEST-15 mutant RED | After |
| --- | --- | --- | --- | --- | --- |
| 1 | R3-10 | (no commit — number with proof) | none | n/a | See Lint baseline |
| 2 | R3-09 + R3-18 | `fix(fe): UXW2-3-R3-09 UXW2-3-R3-18 sweep ClusterActions and IdentityClusterItem` | `cluster-actions has no banned review vocabulary`; `identity-cluster-item has no banned review vocabulary` | `AssertionError: expected 'Edit labelRemove from ClusterSplit gr…' not to match /\bclusters?\b/i` Received includes `Remove from Cluster` | sweep GREEN 30/30 |
| 3 | R3-17 | `fix(fe): UXW2-3-R3-17 distinguish queue-empty from queue-pending` | `ReviewQueue empty`; `ReviewQueue pending`; renamed `merge-undo-banner` | Mutant on ReviewQueue empty copy: `AssertionError: expected 'Review SuggestionsClose matchesPossib…' not to match /\bclusters?\b/i` Received includes `No identity clusters to review`. Mutant reverted. | sweep GREEN 30/30; empty anchor `.acx-review-queue__empty` + `/no .*review/i`; pending `/loading/i` |
| 4 | R3-08 + R3-19 + R1-10 | `fix(fe): UXW2-3-R3-08 UXW2-3-R3-19 UXW2-3-R1-10 gettext first-arg literals` | `does not pass CONST identifiers into __() across identity-clusters` (3 `it` blocks kept) | AFTER broaden: `useOpenReviewTargetLifecycle.ts:102 status === 'rebound' ? LIVE_TARGET_REBIND_ANNOUNCE : LIVE_TARGET_CLOSE_ANNOUNCE`. BEFORE (SCREAMING_CASE regex): GREEN against that ternary. | owned ternary split; guard still RED on 8 r3a/unowned hits (not relaxed) |
| 5 | R3-15 | `fix(fe): UXW2-3-R3-15 hidden suggestion-reject is not a click target` | `the hidden suggestion-reject is not click-targetable (UXW2-3-R3-15)` | `AssertionError: expected compiled css to match /__suggestion-reject[^}]*pointer-events:\s*none/` | name-face-surface 4 passed (R1-03 intact) |
| 6 | R3-23 + R3-24 | `fix(fe): UXW2-3-R3-23 UXW2-3-R3-24 ux-map states and render parity` | `workbench-2pane render documents every zone id, state, and action id` | `expected ux-map render to document state 'roster-error' (zone z-name-curate)` | parity 1 passed; `act-name-cluster` and `act-curate-cluster` kept |
| 7 | R2-05 + R3-22 + R3-10 prose | `docs(uxw2): UXW2-3 correct r2 report gate claims` | n/a | n/a | r2 report: gate evidence suite green / lint RED; R1-16 partial |

## Lint baseline

Wave fork subject: `sync: mirror local feature/uxw2-1`. `git diff --name-only <that>..HEAD | grep -c settingsApi` → `0`.

Cheap partition at this HEAD vs that parent: 59 files changed, 3275 insertions, 2453 deletions.

Authoritative eslint tails (verbatim):

Baseline (`npx eslint .` in `.baseline-worktree` at that parent):

```
✖ 120 problems (119 errors, 1 warning)
  32 errors and 0 warnings potentially fixable with the `--fix` option.
```

HEAD (`npx eslint . -f json` then counted; first failure matches prover):

```
js/admin/api/settingsApi.ts:108  error  "error" | "ok" | "partial" is overridden by string in this union type  @typescript-eslint/no-redundant-type-constituents
errors 117 warnings 1
✖ 118 problems (117 errors, 1 warning)
```

Partition of HEAD's 118 problems:

- Pre-existing (files this wave did not touch): **114 errors + 1 warning**. Untouched. Not fixed.
- Wave-touched, this lane does not own: **3 errors** (listed next section + SuggestionCards / useLiveReviewTarget).
- Wave-touched, this lane owns: **0**. `npm run lint` not claimed green.

Net 119 → 117 errors. The 117 are mostly pre-existing; this wave did not introduce the gate-sized pile.

## Lint owned by lane r3a

Branch-introduced / still live in files this lane may not edit:

- `ReviewQueue.tsx:885` QUERY_RETRY_COPY.RETRY_FAILED_SUGGESTIONS (gettext first-arg)
- `ReviewQueue.tsx:886` QUERY_RETRY_COPY.LOAD_FAILED_SUGGESTIONS
- `ReviewQueue.tsx:894` QUERY_RETRY_COPY.RETRYING_SUGGESTIONS
- `ReviewQueue.tsx:1551` holdMessage

Not r3a, also not this lane (wave-touched or scanned; not edited):

- `SuggestionCards.tsx:51` func-style
- `useLiveReviewTarget.ts:34` @typescript-eslint/no-redundant-type-constituents
- `useLiveReviewTarget.ts:132` @typescript-eslint/no-redundant-type-constituents
- `WorkbenchFindingsPanel.tsx:138` QUERY_RETRY_COPY.RETRYING_FINDINGS
- `WorkbenchFindingsPanel.tsx:319` QUERY_RETRY_COPY.RETRY_FAILED_FINDINGS
- `WorkbenchFindingsPanel.tsx:320` QUERY_RETRY_COPY.LOAD_FAILED_FINDINGS
- `queryRetry.tsx:61` QUERY_RETRY_COPY.RETRY

## Before/after mutant pairs (items 2 and 4)

**Item 2 banned-vocabulary vs `ClusterActions.tsx:74` `Remove from Cluster`**

- Before fixtures: sweep GREEN while that string was live (component not mounted).
- After fixtures, before copy rewrite: RED `expected 'Edit labelRemove from ClusterSplit cluster' not to match /\bclusters?\b/i` (also identity-cluster-item received `Unlabeled identity` / `Remove member from cluster` / `Are you sure you want to remove this from the cluster?`).
- After copy rewrite: GREEN.
- TEST-15 revert `:74` only: first GREEN because `textContent` glued `ClusterSplit`; collector then joined per-element text. Second run RED: `expected 'Edit labelRemove from ClusterSplit gr…' not to match /\bclusters?\b/i` Received `"Edit labelRemove from ClusterSplit group Edit label Remove from Cluster Split group"`.

**Item 4 gettext vs ternary at `useOpenReviewTargetLifecycle.ts:102`**

- Before broaden (SCREAMING_CASE `GETTEXT_NON_LITERAL` only): GREEN against `__(status === 'rebound' ? LIVE_TARGET_REBIND_ANNOUNCE : LIVE_TARGET_CLOSE_ANNOUNCE, 'alt-context')`.
- After broaden, before split: RED including `useOpenReviewTargetLifecycle.ts:102 status === 'rebound' ? LIVE_TARGET_REBIND_ANNOUNCE : LIVE_TARGET_CLOSE_ANNOUNCE`.
- After split: that line gone; 8 r3a/unowned hits remain.
- TEST-15 restore ternary: RED names `useOpenReviewTargetLifecycle.ts:102 status === 'rebound' ? LIVE_TARGET_REBIND_ANNOUNCE : LIVE_TARGET_CLOSE_ANNOUNCE`.

## Suite counts (verbatim)

```
npx vitest run js/admin/__tests__/banned-vocabulary.test.tsx
 Test Files  1 passed (1)
      Tests  30 passed (30)
```

```
npx vitest run js/admin/pages/workbench/identity-clusters/__tests__/gettext-literals.test.ts
 Test Files  1 failed (1)
      Tests  1 failed | 2 passed (3)
```

Offenders after owned ternary split (not relaxed): the eight QUERY_RETRY_COPY / holdMessage rows above.

```
npx vitest run js/admin/styles/components/__tests__/name-face-surface.test.ts
 Test Files  1 passed (1)
      Tests  4 passed (4)
```

```
npx vitest run js/admin/__tests__/uxmap-parity.test.ts
 Test Files  1 passed (1)
      Tests  1 passed (1)
```

eslint is **not** green. See Lint baseline.

## Cross-lane fallout

- `IdentityClusterList.test.tsx` `allows unlinking an identity (wrong person) only for singletons` — `Error: Test timed out in 5000ms` waiting on `getByText('Remove from Cluster')` at `:992`. Unedited.

## Corrections to the review

The `queue-pending` / `ReviewQueue.tsx:908` vacuity claim was disproved by the prover (mutating `:908` to `Loading identity clusters…` made the sweep RED). This lane did **not** act on that claim. `queue-pending` still renders the loading branch; a `/loading/i` anchor makes that coverage explicit. Item 3 only made `queue-empty` actually empty.

## Canon IDs

- CLM-03, DBG-01 — lint baseline proof in this report; r2 report no longer says GREEN over a red block (`docs/tasks/uxw2/UXW2-3-fix-lane-report.md` Gate evidence).
- RLSE-04 — `ClusterActions.tsx:74,86`; `IdentityClusterItem.tsx:76,411,413`; `useOpenReviewTargetLifecycle.ts:98-100`; `workbench-2pane.uxmap.json` `z-name-curate.states`.
- TEST-06 — every new fixture/guard observed RED on the live defect first.
- TEST-07 — `banned-vocabulary.test.tsx` `queue-empty` vs `queue-pending` distinct mocks + anchors.
- TEST-15 — mutants recorded in the table (item 2 collector + `:74`; item 3 empty copy; item 4 ternary; item 5 `pointer-events`; item 6 `roster-error`).
- REF-10 — unused `LIVE_TARGET_*` imports dropped from `useOpenReviewTargetLifecycle.ts:29`.
- REF-26 — sweep now mounts `ClusterActions` / `IdentityClusterItem` (`banned-vocabulary.test.tsx` `it.each` `cluster-actions`, `identity-cluster-item`).
- INT-05, A11Y-14, PERC-04 — `_name-face.scss:87` `pointer-events: none`; reveal `:hover`/`:focus-visible` `:96` and row hover/active `:47` restore `auto`.
- REF-25, NAV-11 — `workbench-2pane.uxmap.json` `z-name-curate` states + sibling `.md` + `js/admin/__tests__/uxmap-parity.test.ts`.

Lexicon grep in this checkout: TEST-06/07, DBG-01, RLSE-04, REF-10, A11Y-14, CLM-03 present under `docs/reviews/uxp-2/lexicons/` (and CLM-03 under uxp-1). TEST-15, REF-25, REF-26, INT-05, PERC-04, NAV-11 are used as the brief listed them; TEST-15 is not a row in this checkout's engineering lexicon (stops at TEST-14).

Never cited AGT-*.

## Undone

- Real `merge-dialog-open` fixture: duplicate-guard dialog is only in `ClusterLabelingPanel.tsx` (lane r3a). Existing case renamed to `merge-undo-banner`. Not mounted.
- gettext guard remains RED on 8 r3a/unowned non-literal first args. Guard not narrowed.
- `IdentityClusterItem.tsx` still has `__('Need at least two identities to split.')` on the split-error path (not in the five live strings this lane was asked to rewrite; not in the new fixtures).
- Full `npm test` / `npm run lint` not re-run as a green gate. Do not read this report as lint green.

## Lane diff vs wave parent (for isolation)

`git diff --name-only` from this lane's start (`sync: mirror local feature/uxw2-3`)..HEAD — r3a-owned paths **not** in this list:

```
apps/prototype-wp-alt-context/docs/ux-maps/workbench-2pane.md
apps/prototype-wp-alt-context/docs/ux-maps/workbench-2pane.uxmap.json
apps/prototype-wp-alt-context/js/admin/__tests__/banned-vocabulary.test.tsx
apps/prototype-wp-alt-context/js/admin/__tests__/uxmap-parity.test.ts
apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterActions.tsx
apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/IdentityClusterItem.tsx
apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/ClusterActions.test.tsx
apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/gettext-literals.test.ts
apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useOpenReviewTargetLifecycle.ts
apps/prototype-wp-alt-context/js/admin/styles/components/__tests__/name-face-surface.test.ts
apps/prototype-wp-alt-context/js/admin/styles/components/_name-face.scss
docs/tasks/uxw2/UXW2-3-fix-lane-report.md
docs/tasks/uxw2/UXW2-3-fix-r3b-report.md
```

`.baseline-worktree` removed. `git status --short` clean except `.lane/`.
