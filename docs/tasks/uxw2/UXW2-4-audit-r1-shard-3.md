# UXW2-4 board audit — shard 3/3

| Finding | Verdict | One-line reason |
|---|---|---|
| UXW2-4-R4-01 | PARTIAL | Report no longer claims R2-18/stateRef TEST-15 RED; same-tick tests still would not go red if `stateRef.current = next` were deleted. |
| UXW2-4-R2-01 | FIXED | Closure table cites commit subjects; the eight fabricated SHA prefixes are gone. |
| UXW2-4-R1-15 | FIXED | `?cluster=` mounts the drawer shell from the URL id; loading/error/Close are reachable and tested. |
| UXW2-4-R5-04 | FIXED | Local merge asserts `roster_bound` true and false with no recognition_url; hardcoded `true` would fail the false test. |
| UXW2-4-R4-04 | OPEN | `roster-people.md` still lags the json on all three named labels; no render-parity gate found. |
| UXW2-4-R3-02 | FIXED | `update_person` load/conflict/update/revision/re-read are tenant-scoped; two-tenant test does not pin `mockRow`. |
| UXW2-4-R2-05 | FIXED | Proxy and local paths derive `roster_bound` from bind outcome; false and DB-error tests exist. |
| UXW2-4-R2-08 | FIXED | `create_local_cluster` uses `resolve_for_automatic_bind`, binds via the writer, and enqueues `person_created`. |
| UXW2-4-R1-29 | FIXED | `&__back` and `.acx-roster__review-cta` exist, use `--acx-*` tokens, back target is `--acx-space-24`. |
| UXW2-4-R1-26 | FIXED | Hook tests mock `fetchTopUnlabeledClusters` at the IO seam; competing List Person row is restored. |
| UXW2-4-R1-23 | FIXED | Sweep uses `BANNED_STRINGS ∪ ROSTER_BANNED`, positive controls, and `wrap()`; workspace copy is rewritten. |
| UXW2-4-R1-12 | FIXED | Proxy normalizer, read SQL, and `create_local_cluster` all apply label authority / bind. |
| UXW2-4-R3-04 | OPEN | Scanner still skips identifier `this` and never expands `projected_cluster_label_sql` / `reserved_label_sql_predicate`. |
| UXW2-4-R2-17 | FIXED | Status live region is always mounted; text is empty until the total settles. |
| UXW2-4-R1-31 | FIXED | Root `REPORT.md` is gone; FE report cites subjects only and names no dead SHAs. |

## UXW2-4-R4-01 — PARTIAL

Assertions:
1. Closure-table R2-18 and the stateRef half of R1-17 claim a TEST-15 RED that does not exist — closed at `docs/tasks/uxw2/UXW2-4-fe-report.md:46` and `:67`. R2-18 is not in the closed table. R1-17's mutant line is `{replace:true}`, not the ref write. The report now states the gap:
```
| R1-17 | `fix(nav\|tests): panel owner` | `ScanTabContent.reviewUrl` history + same-tick | drop `{replace:true}` on close → `navigate(-1)` reopens |
```
```
Same-tick `stateRef.current = next` behaviour is unproven. Deleting that assignment does not fail `same-tick open then close does not leave panel=review in the URL` (ClusterPanelContext or ScanTabContent.reviewUrl). UXW2-4-R2-18 is still open.
```
2. Untested same-tick invariant (second dispatch must read the first's result) — NOT closed. `stateRef.current = next` is still there (`ClusterPanelContext.tsx:112-113`) and line 87 still syncs on render:
```
  const stateRef = React.useRef(clusterPanel);
  stateRef.current = clusterPanel;
```
```
      const next = clusterPanelReducer(stateRef.current, action);
      stateRef.current = next;
```
   Same-tick tests exist (`ClusterPanelContext.test.tsx:68-118`, `ScanTabContent.reviewUrl.test.tsx:253-261`) but they only inspect the **last** URL. The reducer fully replaces state and ignores the previous value for `open_review` / `open_label` / `close` (`ClusterPanelContext.tsx:18-26`), so deleting the assignment would still leave those tests green. That matches the report's own admission. R2-18 remains the open residue.

## UXW2-4-R2-01 — FIXED

Assertions:
1. The eight SHA prefixes in the R1 closure table fail `git cat-file -e` — closed: those prefixes are absent from `docs/tasks/uxw2/UXW2-4-r1-fix-report.md` (repo-wide grep for each prefix is empty). The R2 section cites subjects and records the DoD explicitly:
```
| R2-01 | this R2 report section | subjects only; no new 40-char SHAs | n/a |
```
2. Lane DoD "No REPORT.md SHA failing git cat-file -e" / R1-14 self-refuted — closed. Commits are listed by subject (`UXW2-4-r1-fix-report.md:158-171`). R1-14 is restated as `git cat-file -e` **on this file**, not as portable hex. `git cat-file -e` on the originally named prefixes still fails here; they are no longer cited.

## UXW2-4-R1-15 — FIXED

Assertions:
1. `?cluster=` paints nothing while loading or on error because the panel returns null when `!cluster` — closed. Open id comes from the URL (`RosterPage.tsx:35-36`, `rosterRoute.ts:120-126`), not a lagged effect. The host always passes that id (`RosterPage.tsx:247-257`):
```
      <ClusterDrawerPanel
        cluster={selectedClusterId === null ? null : drawerCluster}
        requestedClusterId={selectedClusterId}
        ...
        isDetailLoading={clusterDetailQuery.isLoading}
        detailError={
          clusterDetailQuery.isError
            ? (clusterDetailQuery.error?.message ?? __('Unable to load face group details.', 'alt-context'))
            : null
        }
```
   The panel mounts the shell whenever the requested id is set (`ClusterDrawerPanel.tsx:283-285`) and the loading / error branches are on the mounted tree (`:386-389`):
```
  if (!cluster && !requestedClusterId) {
    return null;
  }
```
```
          {isDetailLoading ? (
            <p>{__('Loading faces…', 'alt-context')}</p>
          ) : detailError && !cluster ? (
            <p className="acx-cluster-drawer__status acx-cluster-drawer__status--error">{detailError}</p>
```
   Close is in the header for every shell state (`:374-382`).
2. Missing RED tests for pending fetch and 404 — closed at `RosterPage.container.test.tsx:514-555`. Loading expects Close + `Loading faces…`. Error expects the error string and Close actually dismissing the shell. Panel-level coverage is in `ClusterDrawerPanel.offline.test.tsx`.
3. REPORT claimed gating on `selectedClusterId` while it was not — closed. Gating is `selectedClusterId === null` for the cluster object **and** `requestedClusterId` for the shell. `defaultWorkspaceRoute` is still suppressed while a cluster id is in the URL (`RosterPage.tsx:66-72`); that is now paired with a rendered drawer, so the dual-blank is gone.

## UXW2-4-R5-04 — FIXED

Assertions:
1. `roster_bound` value asserts only ran on the proxy path — closed. Local tests do not set `acx_recognition_url` and assert no HTTP (`ClusterMergeServiceTest.php:225-265`):
```
    public function testLocalMergeReportsRosterBoundFalseWhenBindMatchesNoRow(): void
    {
        ...
        $this->assertEmpty($this->getHttpCalls(), 'local merge must not proxy');
        $this->assertFalse($response->get_data()['roster_bound']);
    }
```
   The true sibling is `testLocalMergeReportsRosterBoundTrueWhenBindMatches` (`:225-244`).
2. Hardcoding the local path to `$roster_bound = true` stays green — closed. Production still assigns the bind result (`class-cluster-merge-service.php:154-165`, `:192-193`):
```
				$roster_bound  = false;
                ...
					$roster_bound = $bound;
                ...
					$response_data['roster_bound'] = $roster_bound;
```
   The R5 report records the mutant `$response_data['roster_bound'] = true;` failing `testLocalMergeReportsRosterBoundFalseWhenBindMatchesNoRow` (`Failed asserting that true is false`). That is a real kill, not a tautology.

## UXW2-4-R4-04 — OPEN

Assertions:
1. `roster-people.md` is a stale render of `roster-people.uxmap.json` — NOT closed. All three named mismatches are still on disk:

| json | md |
|---|---|
| `Face-group drawer host (cluster= shim)` (`roster-people.uxmap.json:94`) | `Face-group drawer host (other)` (`roster-people.md:51`) |
| `Linked faces` (`roster-people.uxmap.json:139`) | `Linked identities / faces` (`roster-people.md:72`) |
| `Face-group drawer (deep-link shim)` (`roster-people.uxmap.json:175`) | `Face-group drawer (shim)` (`roster-people.md:33`) |

```
|   - Face-group drawer host (other) states=[default,empty]  |
```
```
          "label": "Face-group drawer host (cluster= shim)",
```
2. Operator-facing `identities` copy that R2-19 claimed removed — NOT closed on the rendered md (`roster-people.md:72`). Json label is `Linked faces`; zone **id** `z-person-identities` is an identifier, not operator copy.
3. Render-parity in the GREEN gate — NOT closed. Grep of Makefiles / workflows / tests found no ux-map md↔json parity check.

## UXW2-4-R3-02 — FIXED

Assertions:
1. `update_person` load / revision bump / re-read / `wpdb->update` keyed on id alone — closed (`class-api.php:689`, `:739`, `:751-768`):
```
			$person     = $wpdb->get_row( $wpdb->prepare( 'SELECT * FROM %i WHERE id = %d AND tenant_id = %s', $table_name, $id, $tenant_id ) );
```
```
		$result = $wpdb->update( $table_name, $update_data, array( 'id' => $id, 'tenant_id' => $tenant_id ), $update_fmt, array( '%d', '%s' ) );
```
```
				'UPDATE %i SET local_revision = local_revision + 1 WHERE id = %d AND tenant_id = %s',
```
2. Duplicate-name check compared `normalized_name` across every tenant — closed (`class-api.php:703-710`):
```
						'SELECT id FROM %i WHERE normalized_name = %s AND id != %d AND tenant_id = %s',
```
3. Missing two-tenant `PersonCrudTest` that does not pin `$wpdb->mockRow` — closed at `PersonCrudTest.php:375-410`. The test seeds two `id=7` rows in `tableRows` (current vs `other-tenant`) and asserts Bob's name and revision are untouched. It does not set `mockRow`. Residual: no dedicated case that a cross-tenant same `normalized_name` must **not** 409; the SQL already scopes that probe.

## UXW2-4-R2-05 — FIXED

Assertions:
1. Proxy label/merge emit `roster_bound: true` unconditionally after persist — closed. Proxy label writes the bind boolean (`class-cluster-label-service.php:104-108`); DB failure returns 500 before the field is set (`:247-260`). Proxy merge uses `bind_succeeded` after a `false` check (`class-cluster-merge-service.php:120-129`):
```
			$bound                = $this->bind_persisted_person( $cluster_id, (int) $resolved['person_id'], $tenant_id );
			if ( is_wp_error( $bound ) ) {
				return $bound;
			}
			$data['roster_bound'] = $bound;
```
```
				if ( false === $bind_result ) {
					return new WP_Error( 'acx_db_error', 'Could not bind person to cluster.', array( 'status' => 500 ) );
				}
				$data['roster_bound'] = ClusterCurationWriter::bind_succeeded( $bind_result );
```
   Local label uses the same helper (`class-cluster-label-service.php:224`). `bind_succeeded` is `false !== $bound && 0 !== $bound` (`class-cluster-curation-writer.php:254-256`).
2. No test that the flag can be false — closed. `testProxyLabelWriteReportsRosterBoundFalseWhenNoClusterRowMatched` (`ClusterLabelServiceTest.php:557-580`) and `testLocalLabelWriteReportsRosterBoundFalseWhenClusterRowVanished` (`:616-632`) assert `assertFalse`. Hardcoding `true` would fail those.

## UXW2-4-R2-08 — FIXED

Assertions:
1. `create_local_cluster` uses `resolve_or_create(..., fn => true)` and bypasses automatic-bind policy — closed. It calls `resolve_for_automatic_bind` (`class-cluster-projection-writer.php:51-73`), whose policy is created / bound-to-this-cluster / unbound-orphan / else `create_distinct` (`class-person-resolution-service.php:152-184`).
2. Skips `person_created` outbox — closed. The allow callback is an `OutboxWriter::enqueue('person_created', ...)` (`class-cluster-projection-writer.php:57-72`). Test: `testCreateLocalClusterUsesAutomaticBindAndEnqueuesPersonCreated` (`ClusterProjectionWriterTest.php:53-78`) asserts the outbox insert.
3. Divergent bind via `resolve_or_create` instead of `bind_person_to_cluster` — closed (`class-cluster-projection-writer.php:103-112`). Collision test `testCreateLocalClusterCreatesDistinctPersonOnNameCollision` / `testCreateLocalClusterBindsResolvedPersonAndStoresItsName` (`ClusterProjectionWriterTest.php:81-123`) would fail a silent same-name reuse (`Ada Lovelace (2)` + new `person_id`).

## UXW2-4-R1-29 — FIXED

Assertions:
1. No `.acx-cluster-review-panel__back` rule — closed (`_cluster-panels.scss:32-43`), imported from `styles/components/index.scss:18`. Tokens only; min size is `--acx-space-24` (`tokens/_spacing.scss:10` → `1.5rem`). Header wraps (`_cluster-panels.scss:20`). Markup: `ClusterReviewPanel.tsx:121-128`.
```
  &__back {
    min-width: var(--acx-space-24);
    min-height: var(--acx-space-24);
    padding: var(--acx-space-8) var(--acx-space-12);
    border: 1px solid var(--acx-color-border);
    border-radius: var(--acx-radius-sm);
    background: var(--acx-color-surface);
    color: var(--acx-color-text);
    font-size: var(--acx-text-sm);
    font-weight: var(--acx-font-weight-medium);
```
2. No `.acx-roster__review-cta` rule — closed (`_roster.scss:638-659`): flex column, gap/padding `--acx-space-12`/`-24`, border, radius, surface-alt. Markup: `RosterPage.tsx:215-217`. Back still does not use `acx-button`; the token `&__back` rule is the other allowed path.

## UXW2-4-R1-26 — FIXED

Assertions:
1. Every roster test mocks `useTopUnlabeledTotal`, so envelope-total honesty cannot go red — closed at the IO seam `useTopUnlabeledTotal.test.tsx:76-87`. It mocks `fetchTopUnlabeledClusters` only and asserts `total === 99` not `clusters.length` (2). Loading / error / missing total / `unavailable` / `endpoint_error` → `null` (`:89-148`). Counted-source `total:0` → `0` (`:150-165`). Replacing the hook body with `clusters.length` or default `0` would fail those. Query-key coupling is the shared-cache probe (`:66-74`, `:167-177`); the last `toEqual(['clusters', 'top-unlabeled', 'tenant-1'])` line only pins the helper, but `waitFor(isFetched)` on that key would time out if the production hook used a different key.
2. Container `List Person` negative is amputated / vacuously green — closed (`RosterPage.container.test.tsx:452-512`). Fixture has both List Person and Detail Person; after Open person review it asserts Detail Person present and List Person absent. Restoring a name-based resolver to the first roster row would fail.

## UXW2-4-R1-23 — FIXED

Assertions:
1. Roster sweep uses a narrowed three-word list instead of `BANNED_STRINGS` — closed (`banned-vocabulary.test.tsx:655-657`, `:750-758`):
```
    const ROSTER_BANNED = ['cluster', 'identity', 'identities', 'member', 'projected instances'] as const;
    const SURFACE_BANNED = [...BANNED_STRINGS, ...ROSTER_BANNED];
```
   `BANNED_STRINGS` still includes `projection`, `Source version`, `Curriculum` (`:48-66`). Putting `Projection status: %s` back on the workspace would fail `projection`.
2. Negative-only (empty container would pass) — closed. Each surface has a positive control first (`:740-748`): drawer `unnamed face group`, workspace `alice` + `data status`, page unnamed-faces/workbench copy, review `review these faces`.
3. `ClusterDrawerPanel` rendered without `wrap()` — closed (`:670-691` uses `wrap(`; `wrap` is `:498-509`).
4. PersonWorkspacePanel still emits banned copy — closed. Operator strings are rewritten (`PersonWorkspacePanel.tsx:223-229`, `:353`): `Data status` / `Last refreshed` / `Record version` / `Review queues`. Empty-state copy is `after the next refresh` (`:27-39`), not `projection refresh`.

## UXW2-4-R1-12 — FIXED

Assertions:
1. Proxy normalizer still surfaces unbound human labels — closed (`class-media-identities-controller.php:167`, `:205`, `:322-323`) via `MemberResponseMapper::apply_label_authority`. Unbound human name → `null` (`class-member-response-mapper.php:114-129`). Kill: `testProxyMediaIdentitiesAppliesLabelAuthorityOnHttpPayload` (`MediaIdentitiesControllerTest.php:127-167`) expects `'Tory Guzman'` → `null`. Local mapper: `testMapMediaIdentitiesAppliesLabelAuthorityOnLocalProjectionRows` (`MemberResponseMapperTest.php:95-121`).
2. Cluster reads still `COALESCE(p.name,c.label)` — closed. Reads use `projected_cluster_label_sql('p.name', 'c.label')` (`class-clusters-read-repository.php:61`). Tests assert the COALESCE form is absent (`ClustersRepositoryTest.php:288`, `IdentityMembersRepositoryTest.php:187`). Trait body (`trait-detects-system-defined-labels.php:34-37`) returns person name, else reserved/empty label, else `NULL`.
3. `create_local_cluster` writes a confirmed human label with no `person_id` — closed; see R2-08. `list_labels` also requires `person_id IS NOT NULL` (`class-clusters-read-repository.php:155`).

## UXW2-4-R3-04 — OPEN

Assertions:
1. `isPlausibleColumnIdentifier` excludes `this` so helper interpolations are certified without seeing the trait body — NOT closed (`ProjectionQueryColumnParityTest.php:1781-1784`):
```
    private function isPlausibleColumnIdentifier(string $id): bool
    {
        if ($id === '' || str_starts_with($id, '%') || strtolower($id) === 'this') {
            return false;
```
   Call sites still interpolate `{$this->projected_cluster_label_sql(...)}` / `{$this->reserved_label_sql_predicate(...)}` (`class-clusters-read-repository.php:61`, `:155`). Extractor regexes (`:2074-2094`) match `{$ident}` or bare `$ident`, not `{$this->method(...)}`, so the CASE / LIKE fragments inside the trait are never expanded. `'p.name'` / `'c.label'` / `'label'` string args stay visible as literals; any extra column added **inside** the trait would still be invisible. No test invokes the trait and scans the expanded SQL. The `this` skip itself is defensible; the unexpanded-fragment hole is the live residue.

## UXW2-4-R2-17 — FIXED

Assertions:
1. `<p role="status">` is born-populated (role and text land together) — closed. Role is unconditional; text is `''` until the total is a number (`RosterPage.tsx:227-237`):
```
          <p role="status">
            {topUnlabeledTotal === null
              ? ''
              : topUnlabeledTotal === 0
                ? __('Nothing waiting in the review queue.', 'alt-context')
                : sprintf(
                    _n('%d face group waiting', '%d face groups waiting', topUnlabeledTotal, 'alt-context'),
                    topUnlabeledTotal,
                  )}
          </p>
```
2. No test that the node exists empty then fills — closed (`RosterPage.reviewCta.test.tsx:199-224`). It asserts `getByRole('status')` with empty text at `total=null`, rerenders to `7`, and `expect(next).toBe(status)` so role is not remounted with content.

## UXW2-4-R1-31 — FIXED

Assertions:
1. FE section lists commits `9ea1512` / `0bd168f` / `43ad0dc` and a 40-char HEAD that do not resolve — closed. Root `REPORT.md` is absent (`test ! -f REPORT.md`). R3 report records the removal (`UXW2-4-fix-r3-report.md:7`):
```
Root `REPORT.md` was `git rm`'d: it was the FE lane's R1-15..31 record (wrong location, three dead SHAs). Not migrated into any `*-fe-report*.md`.
```
   Current FE report (`UXW2-4-fe-report.md:1-3`, `:43-60`) cites **subject lines** and says not to treat SHAs as portable. Repo grep for those three prefixes is empty. `git cat-file -e` on them still fails; they are no longer claimed.
2. Two lanes in one root `REPORT.md` — closed. PHP is `docs/tasks/uxw2/UXW2-4-r1-fix-report.md`; FE is `docs/tasks/uxw2/UXW2-4-fe-report.md`.
3. Unverifiable suite counts in a worktree without `node_modules` — restated in the FE report from a named `npx vitest run` / `npm run typecheck` (`UXW2-4-fe-report.md:31-37`). Counts are still not re-run in this audit (out of scope); provenance of SHAs is the defect that shipped.

## Undone

(none)
