# UXW2-2 fix r10c report

Cite commits by subject. File:line cites re-derived with `sed -n '<N>p' <file>` after the last code commit.

Canon (grepped): RLSE-04, NAV-11, TEST-15, A11Y-21.

## Closed

| Finding | Clause | Disposition | Subject | RED (verbatim) |
|---|---|---|---|---|
| R3-12 | onLabel announce + focusQueueRoot untested | already-closed-with-evidence | (no new commit; existing `ScanTabContent.labelAnnounce.test.tsx:98`) | Mutant A (delete `announceReviewLifecycle`): `AssertionError: expected '' to be 'Name saved. Back to review suggestion…' // Object.is equality` / `- Name saved. Back to review suggestions.` Mutant B (delete `focusQueueRoot`): `AssertionError: expected <div …(2)>…(1)</div> to be <button type="button"></button> // Object.is equality` — killed at the focus assertion (`:106`); announce assertion (`:105`) stayed GREEN. Did not split. |
| R3-12 | url_params lacks rq | already-closed-with-evidence | (already on tree) | no mutant (data). `rq` already on `workbench-shell` and `workbench-scan`. |
| R3-12 | card zone states invented | fixed | `fix(fe): UXW2-2-R3-12 R5-11 R9-02 card states, gettext literals, r5 RED` | no mutant (data). Before/after state arrays below. |
| R5-11 | i18n constant msgid | fixed | same | `AssertionError: ScanTabContent.tsx:206:43 __(REVIEW_QUEUE_LABEL_SAVED_ANNOUNCE) first argument is not a string literal` |
| R9-02 | r5 report RED prose | fixed | same | pre-existing-suite RED (not TEST-15): `AssertionError: expected false to be true // Object.is equality` at `ReviewQueue.test.tsx:2469`. Recreated by collapsing the empty-announce enter-guard to `if (true)` (first-mount empty always announced); hold stayed on the card. Restore left production unchanged. Quoted into `UXW2-2-fe-r5-report.md:13`. |

GREEN (after last code commit, from `apps/prototype-wp-alt-context`):

```
Test Files  213 passed (213)
Tests  2402 passed (2402)
```

`npm run typecheck` clean (`tsc --noEmit --project tsconfig.type-check.json`).

## R3-12 clause 1 — already closed, kill-power proven

`ScanTabContent.tsx:206` announces `__('Name saved. Back to review suggestions.', 'alt-context')` into the `aria-live="polite"` region at `:183`, then `focusQueueRoot()` (`:207`, defined `:60-62`). Existing test `ScanTabContent.labelAnnounce.test.tsx:98` (`announces name-saved copy and focuses the queue root after a label commit`) asserts live-region text (`:105`) and that `.acx-findings-detail-anchor` is `document.activeElement` (`:106`).

Mutant A: delete the `announceReviewLifecycle(...)` call. Selected 1/1. RED:

```
AssertionError: expected '' to be 'Name saved. Back to review suggestion…' // Object.is equality

- Expected
+ Received

- Name saved. Back to review suggestions.
```

Mutant B: delete `focusQueueRoot()`. Selected 1/1. Announce assertion GREEN; focus assertion RED:

```
AssertionError: expected <div …(2)>…(1)</div> to be <button type="button"></button> // Object.is equality

- Expected
+ Received

+ <div
+   class="acx-findings-detail-anchor"
+   tabindex="-1"
+ >
    <button
      type="button"
    >
      Save name
    </button>
+ </div>
```

Restored after each. No split: each mutant is killed by its own assertion.

## R3-12 clause 2 — already closed

`workbench-operator-loop.uxmap.json:37` (`workbench-shell`): `url_params` includes `rq`.
`workbench-operator-loop.uxmap.json:82` (`workbench-scan`): `url_params` includes `rq`.

## R3-12 clause 3 — fixed (ux-map data)

Zone `z-review-suggestions-group-card` (`code_ref` `TopClusterCard.tsx`).

Before: `["default", "empty"]`

After: `["default", "suggested_label", "busy", "read_only", "missing_image"]`

Derived from `TopClusterCard.tsx` (sed after last code commit):

- `suggested_label` — `:122-124` `Is this <name>?` vs `Name this person`; Yes/No at `:226`
- `busy` — `:147` `isBusy = isDismissing || isConfirming`; `disabled={isBusy}` at `:213`, `:232`, `:241`, `:255`, `:265`
- `read_only` — `:208` title is a span, not a button; `:226` skips confirm; `:248-249` Review stays
- `missing_image` — `:178` / `:194-200` zero reps still render an Avatar; there is no empty branch

Sibling ASCII (`workbench-operator-loop.uxmap.md:60-62`, `workbench-operator-loop.md:72-74`) updated to match.

## R5-11 — gettext literals

`ScanTabContent.tsx:206` now passes a string literal to `__()`. `ReviewQueue.tsx` inlined every `__(_n/_x` first arg that was an identifier, member, ternary, or variable (`holdMessage` → `Saving…` / `Saving… — Undo` at `:1611-1613`). ReviewQueue FE suite (92 tests) stayed GREEN — rendered strings unchanged.

Scoped guard: `ownedGettextLiterals.test.ts:67` — **ScanTabContent.tsx + ReviewQueue.tsx only**, not repo-wide.

Mutant: revert the ScanTabContent literal to `__(REVIEW_QUEUE_LABEL_SAVED_ANNOUNCE, 'alt-context')`. Selected 1/1. RED:

```
AssertionError: ScanTabContent.tsx:206:43 __(REVIEW_QUEUE_LABEL_SAVED_ANNOUNCE) first argument is not a string literal
```

Restored.

## R9-02 — r5 report truth

`UXW2-2-fe-r5-report.md:13` R8-02 follow RED cell was prose. Recreated by collapsing the empty-announce enter-guard in `ReviewQueue.tsx` to `if (true)` (first-mount empty always announced). UI-04 (`ReviewQueue.test.tsx:2424`, assertion `:2469`) went RED; the Yes hold card stayed (`1 left to review on this page`). That is a **pre-existing-suite RED**, not an authored TEST-15 mutant. Restore left behaviour unchanged. Bidirectional R8-02 pin remains `ReviewQueue.test.tsx:2988`.

## Targeted `-t` (selected/total)

From `apps/prototype-wp-alt-context`:

- `ScanTabContent.labelAnnounce.test.tsx -t 'announces name-saved copy and focuses the queue root after a label commit'` → `Tests  1 passed (1)` (1/1)
- `ownedGettextLiterals.test.ts -t 'every __ / _n / _x first argument in ScanTabContent.tsx and ReviewQueue.tsx is a string literal'` → `Tests  1 passed (1)` (1/1)
- `ReviewQueue.test.tsx -t 'UI-04: drain announcement uses error copy when top-unlabeled failed'` (read-only) → `Tests  1 passed | 91 skipped (92)` (1/92)

## Cites (sed after last code commit)

- `ScanTabContent.tsx:183` `aria-live="polite"`
- `ScanTabContent.tsx:206` inlined label-saved msgid
- `ScanTabContent.tsx:207` `focusQueueRoot();`
- `ScanTabContent.tsx:60-62` `focusQueueRoot` definition
- `ScanTabContent.labelAnnounce.test.tsx:98` existing announce+focus test
- `workbench-operator-loop.uxmap.json:37` / `:82` `rq`
- `workbench-operator-loop.uxmap.json:124` card zone states
- `TopClusterCard.tsx:122-124` / `:147` / `:194-200` / `:208` / `:248-249`
- `ownedGettextLiterals.test.ts:17-20` scoped file list; `:67` assertion
- `ReviewQueue.test.tsx:2469` UI-04 pre-existing-suite RED; `:2988` R8-02 pin
- `UXW2-2-fe-r5-report.md:13` quoted RED

## Suite

`npx vitest run` from `apps/prototype-wp-alt-context`:

`Test Files  213 passed (213)`
`Tests  2402 passed (2402)`

`npm run typecheck` clean.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

## Undone

- PHP untouched; `composer test` skipped (out of ownership).
- `useSuggestionReviewMutations.*`, `useClusterMutations.*`, and `ReviewQueue.test.tsx` not edited (sibling lanes).
- Gettext guard is **not** repo-wide. `queryRetry.tsx` still has `__(QUERY_RETRY_COPY.RETRY, …)`; other `__()` identifier sites outside ScanTabContent + ReviewQueue stay.
- Plugin still has no `makepot` / `wp-i18n` extraction step. Inlining makes msgids visible; nothing extracts them yet.
- First-mount true drain is still visual-only. A future collapse of the boolean+string announce latch to one string ref must re-prove UI-04.
- `REVIEW_QUEUE_LABEL_SAVED_ANNOUNCE` remains exported for the existing labelAnnounce expected-copy pin; the live `__()` call no longer uses it.
