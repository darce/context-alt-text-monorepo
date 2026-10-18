# UXW2-3 × main merge report

**Verdict: gate green.** Union of UXW2-3 naming surface with already-merged UXW2-2 honest counts and UXW2-4 roster/library parity. No conflict markers remain in owned sources.

Baseline on main: phpunit 1939/9534, vitest 219 files / 2460 tests. Merged: phpunit 1942/9558, vitest 224 files / 2592 tests.

## `src/api/class-api.php`

OURS added `class-cluster-person-bind-service.php`. THEIRS added `trait-runs-transactional.php` + `class-cluster-curation-writer.php`. Base had neither. **Union: all three requires.** Pure concatenation.

## `src/api/services/class-cluster-membership-service.php`

OURS added `$binder, $resolved_person` closure captures (roster bind on create-for-identity). THEIRS replaced the `<= 0` check with `is_wp_error($created)` then `<= 0` (name-collision 409). **Union: both.**

**TEST-15.** Drop `is_wp_error` guard. RED: `testCreateForIdentitySurfacesNameCollisionAs409` `Failed asserting that false is true` (line 432, `is_wp_error($response)`). Restore GREEN. Drop `$binder, $resolved_person` captures. RED: `testCreateForIdentityWithRosterEntryIdBindsPersonAndEnqueuesClusterPersonBound` `Failed asserting that null is identical to 7` (person_id). Restore GREEN.

## `tests/Unit/ClusterMembershipServiceTest.php`

OURS added bind/null-person/orphan tests + `queriesContaining`. THEIRS added `testCreateForIdentitySurfacesNameCollisionAs409`. Base empty. **Union: keep all tests.** No collision of names.

## `js/.../useClusterMutations.ts`

OURS added `queryKeys.roster.entries()` invalidation. THEIRS replaced `invalidateSuggestionProjection` with `queryKeys.suggestions.projection.all` + object-form mergePending. **Union: roster.entries + THEIRS projection/mergePending.** Dropped the replaced helper call.

## `js/.../ClusterLabelingPanel.tsx`

OURS added roster.entries invalidation on label success. THEIRS replaced clusters.all + `invalidateSuggestionProjection` with drop-cache (`REVIEW_DROP_MODE.LABEL`) + no-refetch review invalidation. **Union: THEIRS drop-cache path + OURS roster.entries().**

**TEST-15.** Judgement is “keep drop-cache, do not restore the old invalidate”. Covered by THEIRS `R1-17: merge success drops result.source_id from topUnlabeled` (passes) plus OURS `successful label invalidates roster.entries`.

## `js/.../__tests__/ClusterLabelingPanel.test.tsx`

OURS added R6-06 focus, R2-07 bind-not-rename-anyway, `commitClusterToRosterEntry` import. THEIRS added R1-17 drop-cache test + `panel-cluster-id` default. **Union: keep OURS tests, keep R1-17, drop the old rename-anyway assertion (production now binds).** R1-17 adapted to NameFaceControl (`typePanelName` + `Merge into group`) — production `ClusterLabelingPanel.tsx` merge button is `Merge into group "%s"`. Default `renderPanel()` cluster id is `panel-cluster-id`; OURS asserts that used `source-cluster-id` were updated to that production id.

## `js/.../ScanTabContent.tsx`

OURS renamed the review-mode region heading to `Review these faces`. THEIRS deleted it because `ClusterReviewPanel` now owns `#acx-workbench-queue-heading`. **Take THEIRS delete.** Keeping OURS would duplicate the id (mock and production both render the h2).

## `js/.../__tests__/ScanTabContent.controlPaneOrder.test.tsx`

OURS exact `'Review these faces'`. THEIRS regex + not cluster/face group. **Take THEIRS** (superset). Heading comes from the ClusterReviewPanel mock.

## `js/.../ClusterReviewPanel.tsx`

OURS renamed cluster/member copy to faces. THEIRS: Back button, `_n` “All %d face(s) shown”, “Face on media %d”, “from the face group”, ellipsis loading. Post-conflict tree already had `<h2 id="acx-workbench-queue-heading">Review these faces</h2>`. **Union: THEIRS Back + THEIRS more-specific copy + keep the post-conflict heading.**

**TEST-15.** Revert alt to `__('Face')`. RED: `renders members from the cluster-members envelope` `Unable to find … role "img" and name /Face on media/`. Restore GREEN.

## `js/.../__tests__/ClusterReviewPanel.test.tsx`

All 19 hunks were matcher updates tracking the production copy. **Take THEIRS matchers** (`/Face on media/`, `Remove this face from the face group`, `Remove face`, `Loading faces…`, `No faces in this group.`). OURS heading test (`Review these faces`) is outside the hunks and still passes.

## `js/.../TopClusterCard.tsx`

OURS dropped “in cluster” from the count sprintf. THEIRS extracted `groupFaceCountCopy` (shown-of-total when truncated). Skip title: OURS “Skip these faces for now”, THEIRS “Skip this group for now”. **Take THEIRS count helper + THEIRS skip title** (parity with face-group vocab). Count still reads `3 faces` when all thumbs show.

## `js/.../__tests__/TopClusterCard.test.tsx`

OURS `getByText('3 faces')`. THEIRS same plus `.not.toMatch(/cluster/i)`. **Take THEIRS.** Leftover OURS skip-title assert updated to `Skip this group for now` (production line in `TopClusterCard.tsx` skip button `title=`).

## `js/.../ReviewQueue.tsx`

- Imports: OURS `viewInRosterHref` (THEIRS `VIEW_IN_ROSTER_HREF` no longer exists on `personCommitCopy.ts`).
- Constants: THEIRS `REVIEW_QUEUE_POSITION_PAGE` / `_FILTERED` / `LABEL_SAVED_ANNOUNCE`.
- Empty announce: THEIRS `repair_pending` latch (must not regress UXW2-2). OURS only renamed clusters→faces in the same block. **THEIRS structure + OURS `'Unable to load unlabeled faces.'`.**
- QUERY_RETRY: OURS already-translated `QUERY_RETRY_COPY.*` (gettext-literals). Not THEIRS inlines.
- Person-commit fallback: OURS “Could not save the name” / “Name saved.” / `viewInRosterHref(personUuid)` — matches `personCommitCopy.ts`.
- Empty visual: THEIRS `!repairPending` drain + repair branch.
- Hold: OURS `HOLD_*_STATUS_COPY` SSOT (THEIRS inlined the same strings).

**TEST-15.** Replace all four unlabeled-faces strings with groups. RED: `ReviewQueue source does not say unlabeled clusters` `expected … to contain 'Unable to load unlabeled faces.'`. Restore GREEN. Inline `__('Saving…')` instead of HOLD constants. RED: `CommitHoldRegion consumes HOLD_*_STATUS_COPY as SSOT` `expected … not to match /__\(\s*'Saving…/`. Restore GREEN.

## `js/.../__tests__/ReviewQueue.test.tsx`

Union imports (`readFileSync` + `useQueryClient`; `HOLD_COMMITTING_STATUS_COPY` + `useSuggestionReviewMutations`). Take THEIRS reducer harness (post-conflict `makeQueueHarness` already consumes that shape). Unlabeled-error expects updated from THEIRS “groups” to merged production “faces”. One non-conflicted THEIRS test still drove the old combobox (`Search people...` / `Create "…"` / `Save`); adapted to NameFaceControl `Save name`.

## `js/admin/__tests__/banned-vocabulary.test.tsx`

Keep OURS `collectReviewSurfaceText` + uxmap helpers **and** THEIRS `collectVisibleText` (roster sweep uses it). Keep OURS review-surface tests **and** THEIRS roster + toast-source tests. Merge `useShowAllClusterMembers` mocks: THEIRS hoisted members + `vi.fn` so the error fixture can `mockReturnValue`. ReviewQueue fixture props updated to `onClampIndex`/`onStepIndex`/`onClearFilters`. PAGE_SWEEP ignores `._*` AppleDouble names.

## `docs/ux-maps/workbench-operator-loop.md` + `.uxmap.json`

THEIRS split findings / queue header / group card (repair + code_ref). OURS NameFaceControl states. **Union: THEIRS three zones; NameFaceControl label+states on the group card.** JSON findings label is `Identity / findings preview (AI-assisted)` so uxmap-render-parity matches the md verbatim.

## Leftover (not in `.lane/CONFLICTS.txt`)

THEIRS tests outside the 17 files still expected pre-UXW2-3 copy/API:

- `IdentityClusterItem.test.tsx` / `IdentityClusterList.test.tsx`: `Unlabeled identity` → production `Unnamed person` (`IdentityClusterItem.tsx` `derivedLabel ?? __('Unnamed person')`).
- `ScanTabContent.labelPanelReachable.test.tsx`: `dispatchQueue` mock + `MemoryRouter` around `ClusterPanelProvider` (`useSearchParams`).
- `ScanTabContent.labelAnnounce.test.tsx`: same `dispatchQueue` mock.

## Commits (subjects only)

- `chore: drop macOS AppleDouble junk from the plugin tree`
- `fix(php): union UXW2-3 person-bind with main collision guard`
- `fix(fe): union naming surface with honest-count review caches`
- `test(fe): keep both sides' review-surface assertions after merge`
- `test(fe): adapt leftover main tests to merged naming copy`

## Gate

| Step | Exit | Totals |
| --- | --- | --- |
| `UPDATE_CLUSTERS_READ_FIXTURES=1` ClustersControllerCharacterizationTest | 0 | 26 tests, 146 assertions; fixture diff empty |
| `./vendor/bin/phpunit` | 0 | 1942 tests, 9558 assertions (≥ 1939/9534) |
| `./node_modules/.bin/vitest run` | 0 | 224 files, 2592 tests (≥ 219/2460) |
| `npm run typecheck` | 0 | |
| `python3 scripts/check_shared_contract_fixtures.py` | 0 | 4 fixtures |

`git status --porcelain` after regen: empty of fixture churn. Marker grep: only `docs/operator/harness-patch-filter-test-output.md` (pre-existing fixture).
