# REPORT — UXW2-2 FE fix lane r3

Cite commits by subject line. No SHAs.

## Items

| Finding | Subject | Tests | Mutant + RED | GREEN |
|---|---|---|---|---|
| R5-01 + live half of R1-24 | `fix(fe): UXW2-2-R5-01 stop draining the queue when bulk accept accepted nothing` | `R5-01: a 200 with accepted_count 0 evicts nothing`; `R5-01: a partial accept refetches instead of guessing`; kept `R1-24: bulkAccept name type decrements the header count` | revert `onSuccess` to `min_confidence` loop → `AssertionError: expected [ 'name-low' ] to deeply equal [ 'name-1', 'name-low' ]` | `npx vitest run …/useSuggestionReviewMutations.test.tsx -t 'R5-01\|R1-24: bulkAccept'` → `Tests  6 passed \| 42 skipped (48)` |
| R5-02 | `fix(fe): UXW2-2-R5-02 server-scoped copy on an empty served page` + follow-up `fix(fe): UXW2-2-R5-02 pass unlabeled served length not queue length` | `R5-02: an empty served page uses server-scoped wording`; `R5-02: a non-empty page keeps page-scoped wording`; `R5-02: the repair-empty page does not claim groups are on this page` | `servedCount === 0` falls through to page-scoped string → `AssertionError: expected 'At least 24 groups on this page missing face data' not to match /on this page/` | `npx vitest run …/representativeVocabulary.test.ts …/ReviewQueue.test.tsx -t 'R5-02'` → `Tests  3 passed \| 82 skipped (85)` |
| R5-03 | `fix(fe): UXW2-2-R5-03 do not announce 0 of 0 on a repair-empty page` | `R5-03: the repair-empty page does not announce 0 of 0` | delete `findings.repairPending` branch → `expected document not to contain element, found <span class="acx-review-queue__position">0 of 0</span>` | `npx vitest run …/ReviewQueue.test.tsx -t 'R5-03'` → `Tests  1 passed \| 82 skipped (83)` |
| R5-04 | `fix(fe): UXW2-2-R5-04 announce repair_pending on first empty mount` | `R5-04: an already-empty repair_pending mount announces the repair state`; `R5-04: the repair-empty mount announces only once across a re-render` | restore bare `previousItemKeyRef.current !== null` → `TestingLibraryElementError: Unable to find an element with the text: /missing face data/i` | `npx vitest run …/ReviewQueue.test.tsx -t 'R5-04'` → `Tests  2 passed \| 83 skipped (85)` |
| R5-07 | `fix(fe): UXW2-2-R5-07 assert the real header count after full bulk accept` | `R5-07: the queue header count decrements after a full bulk accept` (renders `.acx-review-queue__count`; drives `bulkAcceptSuggestions` `{accepted_count:2,skipped_count:0}` on the shared QueryClient) | `length >= 0` so the span renders at zero → `AssertionError: expected <span …(2)></span> to be null` | first write GREEN (item 1 already drains); after revert, same `-t 'R5-07'` passes |
| R5-05 (S1) | `fix(fe): UXW2-2-R5-05 direct tests for apply*Tombstones selects` | `suggestionProjection.tombstones.test.ts` — `applyTopUnlabeledTombstones` / `applyAssignmentTombstones` / `applyNameTombstones` | see before/after pair below | `npx vitest run …/suggestionProjection.tombstones.test.ts` → `Tests  4 passed (4)` |

### Item 4 before/after mutant pair

The pre-fix branch was unreachable on first mount. `R2-12: repair_pending with empty served page…` asserted `live.textContent` `.not.toBe(DRAIN)` / `.not.toContain('All caught up')`.

- **BEFORE** (bare `previousItemKeyRef.current !== null`, current HEAD mutant): `R2-12` GREEN. Live region is empty: `<div class="acx-review-queue__live" data-announce-seq="0" role="status"/>`. A `.not.toBe(DRAIN)` holds either way.
- **AFTER** (same mutant + new positive `within(liveRegion).getByText(/missing face data/i)`): RED `TestingLibraryElementError: Unable to find an element with the text: /missing face data/i`.

### S1 before/after mutant pair

Mutant: add `has_clusters: filtered.length > 0` to `applyTopUnlabeledTombstones` return.

- **BEFORE** (unmutated, first write): `Tests  4 passed (4)` — the prover's GREEN. No direct select test existed.
- **AFTER**: `expected { clusters: [], data_source: 'local_projection', has_clusters: true, limit: 20, total: 10, truncated: true }` / received `has_clusters: false`.

## Suite

Observed, not copied from the brief.

```
cd apps/prototype-wp-alt-context && npm test
> vitest run
Test Files  212 passed (212)
      Tests  2386 passed (2386)
   Start at  06:18:37
   Duration  300.85s
```

Zero new failures. Lint and typecheck not run; do not treat them as green.

Targeted RED first-writes (non-zero counts):

- R5-01 `accepted_count 0`: `Tests  1 failed | 47 skipped (48)`
- R5-02: `Tests  2 failed | 1 passed | 82 skipped (85)` (non-empty-page pin already GREEN)
- R5-03: `Tests  1 failed | 82 skipped (83)`
- R5-04: `Tests  2 failed | 83 skipped (85)`
- R5-07 first write GREEN (tests-only; killing RED is the `length >= 0` mutant)

## Design changes to existing assertions

- **Item 1** — `R1-24: bulkAccept name type drops every accepted group` mock `{accepted_count:1,skipped_count:1}` → `{accepted_count:1,skipped_count:0}`. Old mock was the partial path; after the fix that path must not evict. Assertions unchanged.
- **Item 2 follow-up** — `REV2-09` `screen.getByText('1 group missing face data')` → `within(repair).getByText(...)`. Same string, scoped to `#acx-review-queue-repair`. R5-04 now announces the same copy in `.acx-review-queue__live`, so unscoped `getByText` throws multiples. Not a weakening.
- S4 not done — no accessible-name query updates.

## Cross-lane fallout

- `BulkAcceptResponse` is still `{accepted_count, skipped_count}` only. Partial accept cannot evict by id without guessing. If PHP adds accepted ids, FE can drop those rows instead of refetching.
- Do not shrink `total` in TypeScript. Served-page vs server-wide `total` is the PHP lane's call. FE consumers (`gatedClusterCopy` `servedCount`, header `length`) read `total` / served arrays; they do not recompute envelope `total`.
- Full-accept still drops by `min_confidence` when `skipped_count === 0`. That is still a local guess, gated on a complete accept. A contract with accepted ids would kill that last guess.

## Canon

Grep'd in `~/uxw2/canon/lexicons`. `rg-015` is the repo regression guard, not a lexicon id. Not citing `AGT-*`. Dropped `A11Y-11` (not used).

- REF-09 `useSuggestionReviewMutations.ts:1017-1028` — eviction from response counts, not a derived `min_confidence` replica
- DATA-01 `useSuggestionReviewMutations.ts:1021-1028` — partial accept: consistency is refetch, not a guessed cache write
- TEST-15 each item's mutant RED above
- TEST-06 item 4 / S1 first-write + mutant pairs
- TEST-08 R5-07 header assert is the rendered span, not a cache length labelled as header
- COG-03 `representativeVocabulary.ts:20-29` — empty served page does not require the operator to notice "on this page" over a blank list
- A11Y-06 `representativeVocabulary.ts:20-29` + `ReviewQueue.tsx:1330-1334` — copy + icon; scope matches what is rendered
- A11Y-21 `ReviewQueue.tsx:583-611` first-mount repair announce; `ReviewQueue.tsx:1033-1039` no false `0 of 0`
- RLSE-04 `ReviewQueue.tsx:1033-1039` repair-empty is a designed unmeasurable position, not a fake drain
- NAV-11 not exercised this lane (S3 skipped)

## Undone

- **R5-11** — deliberately not patched. `ScanTabContent.tsx:207` is `announceReviewLifecycle(__(REVIEW_QUEUE_LABEL_SAVED_ANNOUNCE, 'alt-context'))`: a constant passed to `__()`. Same pattern at ~a dozen `ReviewQueue.tsx` sites. Plugin has no `makepot` / `wp-i18n` extraction step. Patching one call site is a fake closure. Home is the `gettext-literals` guard on UXW2-3.
- **R5-06 (S2)** — skipped (budget). `useClusterMutations.ts:49-58` invalidates five keys; `R3-05` still only observes `queryKeys.media.identities()`. Mutant `refetchType: 'none'` on `clusters.labels()` is still GREEN.
- **R5-08 (S3)** — skipped. `z-identity-preview` still `["default","empty","loading"]`, no `code_ref`. Sibling `.uxmap.md` stale.
- **R5-09 (S4)** — skipped. Two simultaneous `Resync` buttons (`ReviewQueue.tsx:1338`, `WorkbenchFindingsPanel.tsx:461`).
- **R5-10 (S5)** — skipped. Dead SHA column remains in `docs/tasks/uxw2/UXW2-2-fe-report.md`.
- **R3-03** — already satisfied at this HEAD: `WorkbenchFindingsPanel.test.tsx:1168-1171` asserts the panel's own empty copy and `getByText(/missing face data/i)`.
- **R3-12** — announce/focus exists (`ScanTabContent.labelAnnounce.test.tsx:98-106`); `url_params` already has `rq` (`workbench-operator-loop.uxmap.json:37` and `:82`). Residual: `z-review-suggestions-group-card` states `["default","empty"]` vs `TopClusterCard.tsx` (always given a cluster; missing-image / busy / suggested-label are real, `empty` is not).
- **R3-11** — msgids are inline; residual is duplicated plural `_n('%d shown', '%d shown', …)` at `ReviewQueue.tsx:970`.
- **UXW2-2-R3-01, R2-01, R1-08** — open on this task ref; outside both lanes.
- Full-accept `bulkAccept` still loops `min_confidence` when `skipped_count === 0` (`useSuggestionReviewMutations.ts:1031-1036`).
