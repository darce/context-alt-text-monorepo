# UXW2-4 board audit — shard 1/3

Read-only re-check of 16 board findings against the current tree. Line numbers in CLAIMs were treated as hints; symbols were located with `git grep`.

| Finding | Verdict | One-line reason |
|---|---|---|
| UXW2-4-R5-01 | FIXED | DISTINCT-before-LIMIT SQL + window `total_count`; PHP no longer overwrites |
| UXW2-4-R2-15 | PARTIAL | PHP recovered in r4 report, FE uses brief ids; cat-file still fails; no combined REPORT.md |
| UXW2-4-R1-17 | FIXED | `stateRef` advanced, overlay restore, `{replace:true}`, history tests |
| UXW2-4-R1-03 | PARTIAL | Upgrade/activation heal + admin notice + shared predicate; `formatClusterLabel` still synthesizes `cluster-<hex>` for null |
| UXW2-4-R5-03 | OPEN | `UNIQUE KEY idx_normalized_name (normalized_name)` still has no `tenant_id` |
| UXW2-4-R4-03 | OPEN | `z-review-name` still on the map; `ClusterReviewPanel` has no name control |
| UXW2-4-R3-01 | FIXED | Cap branch now `return`s; test pins one heal across two loads |
| UXW2-4-R2-11 | FIXED | Controller tests observe mapped `cluster_label` through `get_media_identities` |
| UXW2-4-R2-07 | FIXED | Person `DELETE` includes `tenant_id`; cross-tenant test would go red on `WHERE id` only |
| UXW2-4-R1-28 | FIXED | `WorkbenchPanelValue` includes `review`; `reviewPanelUrl`; builder/reader round-trip test |
| UXW2-4-R1-25 | PARTIAL | Real router/filters/lifecycle; spy is `>= 1` not exactly-one write; status has no `name` matcher |
| UXW2-4-R1-22 | FIXED | Open focuses Back; close focuses Review trigger and announces the return |
| UXW2-4-R1-11 | FIXED | Mapper + controller + reserved/already-bound snapshot skip + CLI clamp/stall |
| UXW2-4-R2-19 | PARTIAL | JSON jargon renamed; `z-review-cta` still has no `code_ref`; markdown not re-rendered |
| UXW2-4-R2-13 | FIXED | Merge `409 cluster_already_bound` and `person_id`/`roster_bound` are in `clustering-api.md` |
| UXW2-4-R1-14 | FIXED | Root `REPORT.md` gone; CLI reports clusters/persons/created and has `--dry-run` |

## UXW2-4-R5-01 — FIXED

Assertions:
1. LIMIT applied before dedup, so a page of raw rows starves unique labels — closed at `apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-read-repository.php:154-165`. Dedup is a `SELECT DISTINCT label` subquery; `LIMIT` is outside.

```
"SELECT COUNT(*) OVER() AS total_count, filtered.label FROM (SELECT DISTINCT label FROM %i WHERE tenant_id = %s AND label IS NOT NULL AND label != '' AND person_id IS NOT NULL AND NOT {$this->reserved_label_sql_predicate( 'label' )} ORDER BY label ASC) filtered LIMIT %d"
```

2. `total_count` overwritten with in-page unique count (invented metadata) — closed at `:188-191`. Each row keeps the SQL window total; PHP no longer assigns `count($labels)`.

```
$labels[] = array(
    'label'       => $label,
    'total_count' => max( 0, (int) ( $row['total_count'] ?? 0 ) ),
);
```

3. Test would stay green under the old LIMIT-then-dedup shape — closed at `apps/prototype-wp-alt-context/tests/Unit/ClustersReadRepositoryTest.php:75-82`. Fixture is three `Alice` rows plus Bob/Carol/Dana, `limit=3`. Asserts names `['Alice','Bob','Carol']` and `total_count === 4`. The wpdb stub (`tests/stubs/wp.php`) parses this DISTINCT+`COUNT(*) OVER()`+outer LIMIT shape, dedups, then slices — reverting to raw `label, person_id` + LIMIT would miss that parser and fail the names/`total_count` asserts.

```
$labels = $this->repository->list_labels($tenant, '', 3);
...
$this->assertSame(['Alice', 'Bob', 'Carol'], $names, 'LIMIT 3 must apply after DISTINCT, not to duplicate rows');
$this->assertSame(4, (int) ($labels[0]['total_count'] ?? 0), 'total_count must be the distinct-label set, not the page size');
```

Reserved/`person_id IS NOT NULL` predicates are inside the subquery as the proposed fix required.

## UXW2-4-R2-15 — PARTIAL

Assertions:
1. PHP lane section `# UXW2-4-PHP — persons are the single label authority` deleted from root `REPORT.md` — closed as relocation, not as a restored root file. Root `REPORT.md` is absent (`test -f REPORT.md` → missing). Historical PHP closure was recovered in `docs/tasks/uxw2/UXW2-4-fix-r4-report.md:119-121`. PHP R1-01..R1-14 live in `docs/tasks/uxw2/UXW2-4-r1-fix-report.md`.
2. FE section uses synthesized ids instead of brief `R1-15`..`R1-31` — closed at `docs/tasks/uxw2/UXW2-4-fe-report.md:42-60`. Closure table ids are `R1-15`..`R1-31` verbatim; commits cited by subject line.
3. Pins VM-only SHAs — closed in the FE report header (`docs/tasks/uxw2/UXW2-4-fe-report.md:3`: "Commits cited by **subject line**. Do not treat SHAs as portable.").
4. `git cat-file` loop of the PHP-lane SHA is zero MISSING — NOT closed. FE report still records the restore as blocked:

```
PHP section restore: the brief's `git cat-file -e <php-r1-sha>^{commit}` does **not** resolve here.
```

Remaining: no single restored `REPORT.md` with PHP section then FE section; historical PHP SHA still does not resolve in this clone.

## UXW2-4-R1-17 — FIXED

Assertions:
1. `stateRef` assigned during render and never advanced, so two dispatches in one tick share a pre-commit base — closed at `apps/prototype-wp-alt-context/js/admin/pages/workbench/ClusterPanelContext.tsx:110-114`.

```
const next = clusterPanelReducer(stateRef.current, action);
stateRef.current = next;
dispatch(action);
```

2. Guards read a stale `searchParams` closure — closed at `:115-128`. Writes use RR `setSearchParams` functional `prev`. Close deletes `cluster` and either restores a saved overlay or drops `panel=review` (`applyReviewPanelToSearchParams`, `:74-79`).
3. Second owner of `panel` clobbers conflicts/dead-letter and close cannot restore — closed as coordinated two-writer, not a single owner. Overlay host ignores `review` (`WorkbenchNavContext.tsx:36-43`); review writer saves/restores the overlay (`ClusterPanelContext.tsx:117-126`). Test `opening review over an overlay restores that overlay on close` (`ScanTabContent.reviewUrl.test.tsx:263-276`).
4. Writes omit `{replace:true}` so browser Back reopens — closed at `:128`. Both open and close pass `{ replace: true }`. Test after in-app Back does `router.navigate(-1)` and asserts the queue stays up (`ScanTabContent.reviewUrl.test.tsx:248-250`).

Same-tick open then close is covered (`:253-261`). Residual: the FE report notes deleting the `stateRef.current = next` assignment does not fail that test (tracked as R2-18, not this finding). The production close path encodes `next.mode !== 'review'` against functional `prev`, which is the original reopen bug.

## UXW2-4-R1-03 — PARTIAL

Assertions:
1. No activation/upgrade heal; only a manual WP-CLI command — closed. `activate()` and `maybe_upgrade()` both call `maybe_heal_unbound_human_labels()` (`class-life-cycle-manager.php:102`, `:145`, `:152`). That runs `PersonLabelBackfillService::backfill_tenant` (`:219-220`). Tests: `testMaybeUpgradeHealsUnboundHumanLabelsIncludingUnderscoreSkip`, `testMaybeUpgradeHealsUnboundHumanLabelSoRosterReadIsNotNull`.
2. No admin signal — closed. `admin_notices` → `render_label_heal_notice` (`:81`, `:155-174`). Incomplete heal posts a warning; `tenant_unresolved` names `wp acx bind-unbound-labels`.
3. LIKE `'cluster-%'` drifts from `/^cluster[-_]/i` — closed. Shared `reserved_label_sql_predicate` (`trait-detects-system-defined-labels.php:25-28`) emits both `cluster-%%` and `cluster\_%%`. All four identity-members reads use `projected_cluster_label_sql` (`class-identity-members-read-repository.php:57`, `:75`, `:135`, `:217`).
4. CASE returns NULL for human-labelled-but-unbound; Library then synthesizes `cluster-<hex>` instead of `Unlabeled identity` — NOT closed. SQL still nulls unbound humans:

```
CASE WHEN {$person_col} IS NOT NULL AND {$person_col} <> '' THEN {$person_col} WHEN {$label_col} IS NULL OR {$label_col} = '' OR {$reserved} THEN {$label_col} ELSE NULL END
```

(`trait-detects-system-defined-labels.php:37`.) After heal, `p.name` wins. For remaining null labels, `formatClusterLabel` still builds `cluster-${normalizedId}` (`js/admin/pages/workbench/identity-clusters/utils.ts:33-38`), which is truthy, so `IdentityClusterItem.tsx:74-76` never reaches `__('Unlabeled identity')`. Optional `label_state=` payload was not added.

Remaining: null unbound-human display is still `cluster-<hex>`; no `label_state` flag.

## UXW2-4-R5-03 — OPEN

Assertions:
1. Unique index is global `normalized_name` with no `tenant_id` — still true at `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php:636`.

```
UNIQUE KEY idx_normalized_name (normalized_name),
```

`PersonDedupeSchemaParityTest::testPersonsDdlHasUniqueIndexOnNormalizedName` pins that shape (`['normalized_name']` only) — a tenant-scoped index would fail this test today.

2. Tenant-scoped lookup + global unique converts a handled collision into `acx_db_error` 500 — still true. `PersonResolutionService::find_by_normalized_name` is tenant-scoped (`class-person-resolution-service.php:293`: `WHERE normalized_name = %s AND tenant_id = %s`). `create_person` lookup is still unscoped (`class-api.php:592`: `WHERE normalized_name = %s` only). Same name under another tenant is invisible to the tenant-scoped probe, then `INSERT` hits the global unique.

No test with a same-name row under a different tenant (proposed fix not present). Defect reproduces on the current tree.

## UXW2-4-R4-03 — OPEN

Assertions:
1. `workbench-review-panel` declares zone `z-review-name` (label `Name control`, role `form`) — still true at `apps/prototype-wp-alt-context/docs/ux-maps/workbench-operator-loop.uxmap.json:215-220`.

```
{
  "id": "z-review-name",
  "label": "Name control",
  "role": "form",
  "states": ["default"]
}
```

2. `ClusterReviewPanel` ships no name input / combobox / form control — still true. The panel is header + Back, faces grid, show-all, remove-confirm modal (`ClusterReviewPanel.tsx:118-237`). Naming lives on `ClusterLabelingPanel` (`ScanTabContent.tsx:212-226`, mode `'label'`), a different screen. Markdown `workbench-operator-loop.uxmap.md` does not even list `workbench-review-panel` (screens table ends at dead-letter / exits) — render is also stale.

Defect reproduces: the map invents IA the `code_ref` screen does not have.

## UXW2-4-R3-01 — FIXED

Assertions:
1. When `$attempts >= MAX_HEAL_ATTEMPTS_PER_LOAD` the branch deletes the counter and falls through into another heal, so the cap never returns early — closed at `class-life-cycle-manager.php:181-186`.

```
if ( $attempts >= self::MAX_HEAL_ATTEMPTS_PER_LOAD ) {
    // Bounded per load (rg-007). A later request must reset the counter first.
    delete_option( self::OPTION_HEAL_ATTEMPTS );
    return;
}
```

`MAX_HEAL_ATTEMPTS_PER_LOAD` is `1` (`:39`). First load heals; second hits the cap, deletes the option, returns. Third load sees attempts `0` and heals again (bounded retry, not every-request scan).

2. Comment asserted a guarantee the code did not provide — closed. Comment now matches the early return. `LifecycleManagerTest::testHealDoesNotRunAgainOnceThePerLoadCapIsHit` (`:614-641`) runs `maybe_upgrade()` twice and asserts `$manager->healRuns === 1`. Dropping the `return` would make that test red.

## UXW2-4-R2-11 — FIXED

Assertions:
1. Tests exercise normalizer functions with hand-built arrays, not the controller/mapper — closed. Local projection path maps through `MemberResponseMapper::map_media_identities` (`class-media-identities-controller.php:105`). Proxy path calls `apply_label_authority_to_identities_map` (`:167`).
2. A regression that drops the normalizer call from the controller leaves the suite green — closed at `MediaIdentitiesControllerTest.php:72-125` and `:127-168`. Both hit `get_media_identities` and assert unbound `'Tory Guzman'` → `null`, auto `'cluster-abcdef01'` kept, bound → `'Ada Lovelace'`. Dropping `apply_label_authority_to_identities_map` from the proxy branch leaves `'Tory Guzman'` in the payload and fails `assertNull`.

## UXW2-4-R2-07 — FIXED

Assertions:
1. Person row `DELETE` issued with `WHERE person_id = %d` only — closed at `class-api.php:880-887`.

```
$result = $wpdb->delete(
    $table_persons,
    array(
        'id'        => $id,
        'tenant_id' => $tenant_id,
    ),
    array( '%d', '%s' )
);
```

SELECT of the person (`:812`) and cluster reset (`:822`) are also tenant-scoped.

2. Cross-tenant delete by id — closed at `PersonCrudTest::testDeletePersonDoesNotDeleteOtherTenantSharingPersonId` (`PersonCrudTest.php:313-347`). Two rows share `id=7` under different tenants; after delete, the other-tenant row remains and the DELETE SQL must contain `tenant_id =`. Reverting the where-array to `id` only would drop that remaining row (stub `delete` matches all where keys) and fail `assertCount(1, $remaining)`.

## UXW2-4-R1-28 — FIXED

Assertions:
1. `APP_LINK_VALUES.panelReview` declared but `ToWorkbenchOptions.panel` cannot emit `'review'` — closed. `WorkbenchPanelValue` is `Exclude<WorkbenchOverlay, null> | typeof APP_LINK_VALUES.panelReview` (`appLinks.ts:80-83`). `ToWorkbenchOptions.panel` is that union (`:93`). `toWorkbench` sets `panel` and, for review, `cluster` (`:128-133`). `reviewPanelUrl` is the dedicated builder (`:85-86`).
2. Reader enum incomplete vs three legal `panel` values — closed. Overlay host documents `review | conflicts | dead-letter` and ignores `review` (`WorkbenchNavContext.tsx:36-43`). Reader `readReviewFromParams` keys off `APP_LINK_VALUES.panelReview` (`ClusterPanelContext.tsx:42-48`).
3. No test pinning builder output against the reader — closed at `js/admin/navigation/__tests__/appLinks.test.ts:57-70`. `toWorkbench({panel:'review', cluster:'cluster-42'})` and `reviewPanelUrl` emit the same href; `readReviewFromParams` round-trips review to `{mode:'review'}` and conflicts to `{mode:'none'}`.

## UXW2-4-R1-25 — PARTIAL

Assertions:
1. `useWorkbenchFilters` stubbed so `rq=` coexistence is untested; fixtures never carry `rq=` — closed. Comment at `ScanTabContent.reviewUrl.test.tsx:24-25` says real filters. Mount `'/workbench?tab=scan&rq=assignment.all.0&panel=review&cluster=cluster-42'` (`:234`); after Back, `rq=` and `tab=` survive (`:241-242`).
2. `useOpenReviewTargetLifecycle` stubbed to echo the id — closed. Real `ScanTabContent` is mounted; `MergeSurvivorProvider` wraps; members fetch is mocked (`:70-78`, `:170`). No remaining stub of the lifecycle hook.
3. No history navigation — closed. `createMemoryRouter` (`:164-185`). After Back, `router.navigate(-1)` must not reopen (`:248-250`).
4. `setSearchParams` never spied / one write per transition unasserted — PARTIAL. Spy wraps real `useSearchParams` (`:103-116`). Open test asserts `writes.length >= 1` and last options `{replace:true}` (`:220-222`) — not exactly one functional write deleting both keys.
5. Missing cases: `cluster=` without `panel=review`; `panel=conflicts`; `panel=review` without `cluster` — closed (`:278-298`).
6. A11Y-21 asserted as raw text so deleting `role=status` stays green — closed enough to fail a deleted role: `getByRole('status')` + `toHaveTextContent(...)` (`:215-217`, `:243`). Not the proposed `getByRole('status', {name: ...})`. Members are `[]`, so the panel's empty show-all status node is not mounted; deleting the lifecycle `role` would make `getByRole('status')` throw.

Remaining: spy does not pin exactly one write; status matcher has no `name`; no 404 retire-close case (lifecycle is real, but `fetchClusterMembers` resolves empty members, not 404).

## UXW2-4-R1-22 — FIXED

Assertions:
1. Back/X dispatch `close` and nothing else; focus falls to `document.body` — closed at `ScanTabContent.tsx:231-237`.

```
onClose={() => {
  dispatchClusterPanel({ type: 'close' });
  announceReviewLifecycle(
    __('Returned to review suggestions', 'alt-context'),
  );
  focusQueueRoot();
}}
```

`focusQueueRoot` focuses `[data-acx-review-trigger]` (`:60-74`). Test waits for Review to have focus (`ScanTabContent.reviewUrl.test.tsx:244-246`).

2. Opening never moves focus into the panel — closed at `ClusterReviewPanel.tsx:54-59`. Mount effect focuses the Back button via `backButtonRef`.
3. Panel-local `role=status` born with its text; silent on return to the queue — closed. Durable announcer is always mounted in `ScanTabContent` (`:202-209`). Open announces `'Reviewing faces — press Back...'` (`:91-96`); close announces `'Returned to review suggestions'`. Remaining panel `role=status` (`ClusterReviewPanel.tsx:172-174`) is the show-all node, initialized to `null`, not a born-populated review announcement.

## UXW2-4-R1-11 — FIXED

Assertions:
1. Media-identities test never observes a mapped `cluster_label` (return discarded, CASE not evaluated, only SQL text) — closed. Mapper: `testMapMediaIdentitiesAppliesLabelAuthorityOnLocalProjectionRows` (`MemberResponseMapperTest.php:119-121`) asserts unbound → `null`, auto kept, bound → person name. Controller: `testMediaIdentitiesMapsUnboundHumanAutoAndBoundLabels` (`MediaIdentitiesControllerTest.php:122-124`) goes through `get_media_identities`. Repository SQL-text checks remain (`IdentityMembersRepositoryTest.php:217-234`) but are no longer the only observation.
2. `MediaIdentitiesControllerTest` untouched — closed. Local + proxy cases above.
3. No reserved-label / already-bound no-op on snapshot heal / CLI backfill — closed. Snapshot: `testBackfillSkipsReservedStoredLabel` asserts zero person inserts for `cluster_abcdef01` (`ClusterSnapshotMergerTest.php:422-456`); `testBackfillSkipsAlreadyBoundCluster` (`:458-492`). CLI service: `testBackfillIsIdempotentWhenPersonAlreadyBound`; list SQL includes both reserved LIKE fragments (`PersonLabelBackfillServiceTest.php:46-48`). `bind_row` also skips `is_reserved_label_shape` (`class-person-label-backfill-service.php:181`).
4. `BindUnboundLabelsCommand` has no behavioural test — closed. Clamp + `Bound %d cluster(s) to %d person(s), %d created` (`BindUnboundLabelsCommandTest.php:23-48`); `--dry-run` (`:51-77`); stalled → `RuntimeException` (`:79-101`).

These tests would go red if unbound humans leaked a name, reserved snapshot labels created persons, already-bound rows inserted again, or CLI stall returned success.

## UXW2-4-R2-19 — PARTIAL

Assertions:
1. `z-review-cta` zone added without `code_ref` — NOT closed. Zone block at `apps/prototype-wp-alt-context/docs/ux-maps/roster-people.uxmap.json:62-71` still has only `id`/`label`/`role`/`states`. Screen-level `code_ref` points at `RosterPage.tsx` (`:40`); the CTA itself is `section.acx-roster__review-cta` (`RosterPage.tsx:215-244`). No other zone in this map carries `code_ref` either, but the finding asked for one on this zone.
2. `'Person identity header'` / `'Linked identities'` jargon retained — closed in JSON (`roster-people.uxmap.json:130` `'Person header'`, `:139` `'Linked faces'`). NOT closed in the rendered markdown: `roster-people.md:71-72` still shows `Person identity header` and `Linked identities / faces`. Proposed re-render did not land.

Remaining: zone `code_ref`; markdown jargon.

## UXW2-4-R2-13 — FIXED

Assertions:
1. Contract documents only the PATCH cluster-label response — closed. PATCH now includes `person_id` and `roster_bound` (`docs/workbay/contracts/clustering-api.md:482-502`).
2. Merge failure `WP_Error('cluster_already_bound', …, ['status' => 409])` undocumented — closed at `:525`.

```
If the target cluster is already bound to a **different** person, the plugin returns HTTP `409` with error code `cluster_already_bound`. Remedy: unbind the target cluster first, then retry the merge.
```

3. Merge response `person_id` / `roster_bound` missing — closed at `:514-523`.

Residual (not this finding): `:527` still says the merge 200 is a `ClusterResponse`; r5 report already notes local merge is a six-key object. The R2-13 claims themselves are on disk.

## UXW2-4-R1-14 — FIXED

Assertions:
1. Root `REPORT.md` must not merge — closed. File is absent from the repo root. Successor reports live under `docs/tasks/uxw2/`.
2. CLI `'Bound %d person(s)'` counts clusters; no `--dry-run` — closed at `class-bind-unbound-labels-command.php:39-46` (`[--dry-run]`) and `:71-77`:

```
sprintf(
    'Bound %d cluster(s) to %d person(s), %d created',
    (int) $result['bound'],
    (int) $result['persons'],
    (int) $result['created']
)
```

Test pins that string (`BindUnboundLabelsCommandTest.php:48`) and dry-run (`:75-76`).

3. `MediaIdentitiesControllerTest` skip not listed under Undone — closed by the tests existing (R1-11 / R2-11). Nothing to list as skipped.
4. `'no-op person_created enqueue'` wording — the original root `REPORT.md` is gone. Snapshot/CLI heal still passes `static function (): bool { return true; }` (`class-person-label-backfill-service.php:208-210`, `class-cluster-snapshot-merger.php:229-231`); that is a code fact, not a remaining report-file inaccuracy on the original artifact.

## Undone

(none)
