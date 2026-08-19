# UXW2-4 board audit — shard 2/3

Read-only re-check of 15 assigned findings against the tree as of this audit. Line numbers in original CLAIMs were treated as hints; symbols were located by `git grep` and read in full.

| Finding | Verdict | One-line reason |
|---|---|---|
| UXW2-4-R4-02 | FIXED | Dropzone, drag, and `handleDropFace` all gate on `reassignUnavailableReason`; tests assert no mutate. |
| UXW2-4-R2-02 | FIXED | Tombstone is PHP `label_cleared_*` match; stub applies upsert; complementary relabel test can go red. |
| UXW2-4-R1-16 | FIXED | Production boards the picker with honest copy; false "no other face groups" is not shown. |
| UXW2-4-R1-02 | FIXED | `delete_person` → `reset_curation` NULL tombstone; merge does not recreate the person. |
| UXW2-4-R5-02 | OPEN | PHP still re-filters reserved labels; stub never evaluates `NOT (LOWER LIKE …)`; deleting SQL stays green. |
| UXW2-4-R3-03 | FIXED | Seeded `update()` returns matched-row count; empty-table proxy test asserts `roster_bound === false`. |
| UXW2-4-R2-16 | FIXED | Tests wait on `isFetched` then assert null; counted-source `total:0` → `0` positive control exists. |
| UXW2-4-R2-09 | FIXED | Heal runs on every `maybe_upgrade` (not gated by version stamp); stall retries next load + admin notice. |
| UXW2-4-R1-30 | FIXED | `z-needs-assignment` replaced; `workbench-review-panel` exists in JSON + sibling `.md`. |
| UXW2-4-R1-27 | PARTIAL | Bulk mutations/toasts gone from production; `useClusterSelection` + `useRecognitionClusters` still live with no UI caller. |
| UXW2-4-R1-24 | PARTIAL | Locators/copy/CTA walk fixed; drawer walk still skip-gated and `acxE2eSeed.unlabeledClusterId` is never planted. |
| UXW2-4-R1-21 | FIXED | CTA href is `rq=all.all.0`; workbench ALL queue includes top-unlabeled CLUSTER items. |
| UXW2-4-R3-05 | FIXED | `roster_bound` derived from `bind_succeeded`; `find_by_uuid` is tenant-scoped; 0-row tests exist. |
| UXW2-4-R2-18 | FIXED | Comment rewritten; reducer over `stateRef`; same-tick open+close tests exist. |
| UXW2-4-R2-12 | PARTIAL | Exhausted suffixes return `WP_Error`; default `persons_table()` still unguarded `$wpdb->prefix`. |

## UXW2-4-R4-02 — FIXED

Assertions:
1. Mixed-state board-up: copy says moves happen elsewhere while drag still mutates — closed. Production sets the reason whenever a cluster is selected, and `handleDropFace` returns before `mutate`.
2. Dropzone still renders for any non-null cluster — closed. Dropzone and face drag are gated on `hideReassign`.
3. Missing test that a drag with the unavailable reason set never calls `reassignMutation` — closed (component + container).

```119:138:apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx
  const reassignUnavailableReason =
    selectedClusterId === null
      ? null
      : __('Face moves happen in the Workbench review queue.', 'alt-context');

  const handleDropFace = (targetClusterId: string | null): void => {
    const payload = dragDrop.dragPayload;
    if (!payload) {
      return;
    }
    if (reassignUnavailableReason) {
      dragDrop.handleFaceDragEnd();
      return;
    }
```

```512:527:apps/prototype-wp-alt-context/js/admin/pages/roster/ClusterDrawerPanel.tsx
        {cluster && !hideReassign ? (
        <div className="acx-cluster-drawer__dropzone-wrapper">
          <div
            className={`acx-cluster-drawer__dropzone${dropTarget === 'discard' ? ' is-drop-target' : ''}`}
            onDragOver={handleDropzoneDragOver}
            ...
            onDrop={handleDropzoneDrop}
          >
            {__('Drop faces here to remove them from this face group.', 'alt-context')}
```

```175:193:apps/prototype-wp-alt-context/js/admin/pages/roster/__tests__/ClusterDrawerPanel.offline.test.tsx
  it('does not make faces draggable or accept drops when reassign is boarded up', () => {
    ...
    expect(face).not.toHaveAttribute('draggable', 'true');
    fireEvent.dragStart(face);
    expect(onFaceDragStart).not.toHaveBeenCalled();
    expect(screen.queryByText('Drop faces here to remove them from this face group.')).not.toBeInTheDocument();
    expect(onDiscardDrop).not.toHaveBeenCalled();
```

```570:592:apps/prototype-wp-alt-context/js/admin/pages/__tests__/RosterPage.container.test.tsx
  it('does not fire a reassign mutation when a face is dragged on the boarded-up cluster= shim', () => {
    ...
    expect(clusterActionState.reassignMutation.mutate).not.toHaveBeenCalled();
  });
```

Residual: the RosterPage test wraps drop in `if (dropzone)`, so it is weaker if the dropzone is already hidden. The ClusterDrawerPanel test covers that case directly.

## UXW2-4-R2-02 — FIXED

Assertions:
1. Tombstone expressed only in raw SQL `IF(label IS NULL …)` — closed. Decision is PHP, SQL stays "dumb".
2. wpdb stub `query()` never mutates `tableRows` — closed. `applyRawQueryToRows` handles `INSERT … ON DUPLICATE KEY UPDATE`.
3. 'delete then merge → person not recreated' cannot observe the upsert (TEST-15) — closed. Complementary relabel test requires the upsert to land.
4. Plugin never stores NULL (`normalize_label` returns `''`; `reset_curation` writes `''`) — closed. Both write NULL.
5. NULL rows frozen against all future backend labels (no revision/name comparison) — closed for *new* names. Same-name snapshots stay tombstoned by design.

```108:127:apps/prototype-wp-alt-context/src/sovereign/repositories/class-cluster-snapshot-merger.php
			$incoming_label = $this->normalize_label( $cluster );
			$existing       = $this->load_existing_cluster( $cluster_uuid, $normalized_tenant_id );
			$cleared_label  = trim( (string) ( $existing['label_cleared_label'] ?? '' ) );
			...
			$keep_cleared = '' !== $cleared_label && $incoming_label === $cleared_label;
			$label        = $keep_cleared ? null : $incoming_label;
			...
			// Tombstone is decided in PHP (cleared-label match). SQL stays dumb.
```

```355:358:apps/prototype-wp-alt-context/src/sovereign/repositories/class-cluster-snapshot-merger.php
	private function normalize_label( array $cluster ): ?string {
		$label = trim( (string) ( $cluster['label'] ?? $cluster['cluster_label'] ?? '' ) );
		return '' === $label ? null : $label;
	}
```

```347:347:apps/prototype-wp-alt-context/src/sovereign/repositories/class-cluster-curation-writer.php
			'UPDATE %i SET label_cleared_label = label, label = NULL, person_id = NULL, curation_state = %s, is_user_confirmed = 0, local_revision = local_revision + 1, label_cleared_revision = snapshot_version, updated_at = %s WHERE cluster_uuid = %s AND tenant_id = %s',
```

```258:261:apps/prototype-wp-alt-context/tests/Unit/ClusterSnapshotMergerTest.php
        $this->assertCount(0, $personInserts, 'delete must survive a stale-label snapshot; person must not be recreated');
        $this->assertNull(
            $wpdb->tableRows['wp_acx_clusters'][0]['label'],
            'cleared label must persist as NULL, not an empty string or the stale name'
```

```379:380:apps/prototype-wp-alt-context/tests/Unit/ClusterSnapshotMergerTest.php
        $this->assertNotEmpty($personInserts, 'a newer snapshot may re-label only when the incoming label differs');
        $this->assertStringContainsString("'Ada Lovelace'", $personInserts[0]);
```

The original "mutate the SQL `IF()` to `VALUES(label)`" red-check is no longer the guard — tombstone content is in PHP `VALUES`. Stub `applyInsertOnDuplicateToRows` still hardcodes the unconfirmed-overwrite rather than parsing the `ON DUPLICATE` clause; that is leftover stub fidelity, not the filed defect.

`label_cleared_revision` is written but `keep_cleared` matches on cleared *label*, not revision. Tests pin that a newer snapshot with the same name stays cleared. That is durable-deletion, not the "frozen against a different future name" failure.

## UXW2-4-R1-16 — FIXED

Assertions:
1. Production never supplies `reassignTargets` so Move is permanently disabled with false "No other face groups…" copy — closed. Roster always passes `reassignUnavailableReason` on the cluster shim; Move is unmounted; honest copy is shown.
2. Drag-to-dropzone is the only live path — closed (see R4-02).
3. `ClusterDrawerPanel.memberFix.test.tsx` injects targets so a dead production path stays green — remaining as component-level coverage of a restored picker, but production no longer renders that path.

```247:278:apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx
      <ClusterDrawerPanel
        cluster={selectedClusterId === null ? null : drawerCluster}
        requestedClusterId={selectedClusterId}
        reassignUnavailableReason={reassignUnavailableReason}
        ...
        onDiscardDrop={() => handleDropFace(null)}
        // UXW2-4-R1-16: picker boarded up on the cluster= shim (no scoped
        // reassignTargets query). Follow-up: restore via a scoped query (REF-25).
        isReassigning={actions.reassignMutation.isPending}
```

`onReassignFace` and `reassignTargets` are not passed. The panel hides Move when the reason is set:

```394:399:apps/prototype-wp-alt-context/js/admin/pages/roster/ClusterDrawerPanel.tsx
              {hideReassign && reassignUnavailableReason ? (
                <p className="acx-cluster-drawer__reassign-unavailable">{reassignUnavailableReason}</p>
              ) : !hasReassignTargets ? (
                <span id={NO_TARGETS_REASON_ID} className="screen-reader-text">
                  {NO_TARGETS_REASON}
```

```557:567:apps/prototype-wp-alt-context/js/admin/pages/__tests__/RosterPage.container.test.tsx
  it('does not claim the tenant has no other face groups on the cluster= shim', () => {
    ...
    expect(screen.queryByText(/No other face groups available/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Move to/i })).not.toBeInTheDocument();
    expect(screen.getByText('Face moves happen in the Workbench review queue.')).toBeInTheDocument();
```

Proposed-fix option "board it up" is what shipped. Picker internals (`NO_TARGETS_REASON`, `onReassignFace`) remain in the component for a later scoped-query restore; they are not the production defect.

## UXW2-4-R1-02 — FIXED

Assertions:
1. `delete_person` only flips `is_user_confirmed=0`, so the next snapshot writes the stale label back and `resolve_or_create` recreates the person — closed. Delete runs `reset_curation` (NULL label + `label_cleared_label`/`label_cleared_revision`) and also enqueues a label-clear outbox op.
2. Missing RED test `delete_person` then `merge_snapshot_batch_for_tenant` asserts person not recreated — closed.

```841:871:apps/prototype-wp-alt-context/src/api/class-api.php
					if ( $writer->reset_curation( $cluster_uuid, $tenant_id ) <= 0 ) {
						return new WP_Error( 'acx_db_error', __( 'Could not dissociate person from clusters.', 'alt-context' ), array( 'status' => 500 ) );
					}
					...
					$label_cleared = $this->enqueue_curation_operation(
						'cluster_label_updated',
						'cluster',
						$cluster_uuid,
						max( 1, $cluster_revision ),
						array(
							'cluster_uuid' => $cluster_uuid,
							'label'        => null,
						)
					);
```

```220:258:apps/prototype-wp-alt-context/src/sovereign/repositories/class-cluster-snapshot-merger.php
			$stored_label = trim( (string) ( $stored['label'] ?? '' ) );
			if ( '' === $stored_label || $this->is_reserved_label_shape( $stored_label ) ) {
				continue;
			}
```

`ClusterSnapshotMergerTest` (`testDeletePersonThenMergeDoesNotRecreatePerson` body at the `delete_person` + `merge_snapshot_batch_for_tenant` sequence) asserts zero `INSERT INTO wp_acx_persons` and NULL stored label.

## UXW2-4-R5-02 — OPEN

Assertions:
1. SQL reserved predicate is unprovable because PHP re-filters the same rule — still true.
2. wpdb stub never evaluates `NOT` / `LIKE` on that predicate — still true. `parseWhereConditions` has no `NOT (` / `LOWER(` / `OR` branch; the reserved fragment is dropped.
3. Rule duplicated in SQL + PHP and can drift — still true.

```154:187:apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-read-repository.php
			$sql = $this->prepare_projection_read_query(
				"SELECT COUNT(*) OVER() AS total_count, filtered.label FROM (SELECT DISTINCT label FROM %i WHERE tenant_id = %s AND label IS NOT NULL AND label != '' AND person_id IS NOT NULL AND NOT {$this->reserved_label_sql_predicate( 'label' )} AND label LIKE %s ORDER BY label ASC) filtered LIMIT %d",
				...
		foreach ( $rows as $row ) {
			$label = trim( (string) ( $row['label'] ?? '' ) );
			if ( '' === $label || $this->is_reserved_label_shape( $label ) ) {
				continue;
			}
```

```25:28:apps/prototype-wp-alt-context/src/support/trait-detects-system-defined-labels.php
	protected function reserved_label_sql_predicate( string $column ): string {
		$lower = 'LOWER(' . $column . ')';
		return '(' . $lower . " LIKE 'cluster-%%' OR " . $lower . " LIKE 'cluster\\_%%')";
	}
```

```2846:2891:apps/prototype-wp-alt-context/tests/stubs/wp.php
        private function parseWhereConditions(string $where): array
        {
            ...
                if (preg_match('/^`?(?P<column>[A-Za-z0-9_]+)`?\s+LIKE\s+\'(?P<value>.*)\'$/', $condition, $conditionMatches) === 1) {
                    $conditions[] = ['type' => 'like', 'column' => $conditionMatches['column'], 'value' => stripslashes($conditionMatches['value'])];
                    continue;
                }
                ...
                if (preg_match('/^`?(?P<column>[A-Za-z0-9_]+)`?\s+!=\s+\'(?P<value>.*)\'$/', $condition, $conditionMatches) === 1) {
                    $conditions[] = ['type' => 'neq', 'column' => $conditionMatches['column'], 'value' => stripslashes($conditionMatches['value'])];
                }
            }
```

`testListLabelsExcludesReservedAndUnboundLabels` seeds `cluster-abcdef01` / `cluster_x` with `person_id` set and asserts `['Ada Lovelace']`. Because the stub ignores `NOT (LOWER(label) LIKE …)` and PHP still skips reserved shapes, deleting the SQL `NOT {$this->reserved_label_sql_predicate(...)}` clause leaves that test green. Proposed fix (evaluate the predicate in the stub, or assert rather than re-filter) is not on disk.

## UXW2-4-R3-03 — FIXED

Assertions:
1. `update()` returns `defaultUpdateResult` (1) regardless of match — closed when `tableRows` is seeded; returns `$matched`.
2. No test can express a 0-row bind — closed.

```2662:2671:apps/prototype-wp-alt-context/tests/stubs/wp.php
            if (!$hasExplicitOverride && isset($this->tableRows[$table])) {
                $matched = 0;
                foreach ($this->tableRows[$table] as $row) {
                    if ($this->rowMatchesWhere($row, $where)) {
                        ++$matched;
                    }
                }
                $this->applyUpdateToRows($table, $data, $where);
                $this->rows_affected = $matched;
                return $matched;
            }
```

```557:580:apps/prototype-wp-alt-context/tests/Unit/ClusterLabelServiceTest.php
    public function testProxyLabelWriteReportsRosterBoundFalseWhenNoClusterRowMatched(): void
    {
        ...
        $wpdb->tableRows['wp_acx_clusters'] = [];
        ...
        $this->assertFalse($data['roster_bound']);
    }
```

Unseeded tables still fall through to `defaultUpdateResult`; that matches the proposed fallback. The proxy test seeds an empty array so `isset` is true and matched count is 0.

## UXW2-4-R2-16 — FIXED

Assertions:
1. unavailable/endpoint_error tests `await waitFor(fetch called)` then `expect(null)` — null is also pending, so removing `COUNTED_SOURCES` stays green — closed. Tests wait on `isFetched` then assert.
2. Missing counted-source positive control `LOCAL_PROJECTION, total:0 → 0` — closed.

```65:74:apps/prototype-wp-alt-context/js/admin/pages/roster/hooks/__tests__/useTopUnlabeledTotal.test.tsx
const useTopUnlabeledTotalProbe = () => {
  const total = useTopUnlabeledTotal();
  const query = useQuery({
    queryKey: queryKeys.clusters.topUnlabeled('tenant-1'),
    queryFn: () => fetchTopUnlabeledClusters('tenant-1', 20),
    enabled: false,
  });
  return { total, isFetched: query.isFetched, isSuccess: query.isSuccess };
};
```

```115:165:apps/prototype-wp-alt-context/js/admin/pages/roster/hooks/__tests__/useTopUnlabeledTotal.test.tsx
  it('treats unavailable/bootstrapping total:0 as unknown after settle', async () => {
    ...
    await waitFor(() => {
      expect(result.current.isFetched).toBe(true);
    });
    expect(result.current.total).toBeNull();
  });
  ...
  it('returns 0 for a counted-source empty backlog (LOCAL_PROJECTION total:0)', async () => {
    ...
    expect(result.current.total).toBe(0);
  });
```

Production gate is still live:

```31:35:apps/prototype-wp-alt-context/js/admin/pages/roster/hooks/useTopUnlabeledTotal.ts
  const total = query.data?.total;
  if (typeof total !== 'number' || !COUNTED_SOURCES.has(query.data?.data_source ?? '')) {
    return null;
  }
  return total;
```

Removing `COUNTED_SOURCES.has(...)` would make the unavailable `total:0` case return `0` after settle and fail those tests. The loading test still asserts `isFetched === false` + `null` so pending vs settled are distinguished.

## UXW2-4-R2-09 — FIXED

Assertions:
1. `heal_unbound_human_labels()` runs *after* `update_option(OPTION_VERSION, ACX_VERSION)`, so a stall never retries until the next version bump — closed. Heal is outside the version-mismatch branch and is keyed off `OPTION_HEAL_COMPLETE`, not version.
2. Stall log "will retry on next upgrade" is a lie — closed; copy is "next load".
3. No operator signal; NULL labels indefinitely — closed. Admin notice while heal is incomplete; stall does not set `HEAL_COMPLETE`.

```136:152:apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php
		if ( ! $version_matches || ! $fingerprint_matches ) {
			if ( ! $this->maybe_create_projection_tables() ) {
				...
				$this->maybe_heal_unbound_human_labels();
				return;
			}
			update_option( self::OPTION_VERSION, ACX_VERSION );
			update_option( self::OPTION_SCHEMA_FINGERPRINT, $fingerprint );
		}

		$this->maybe_heal_unbound_human_labels();
```

```202:209:apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php
		if ( ! empty( $result['stalled'] ) ) {
			Telemetry::log_line(
				sprintf(
					'[acx] unbound-label heal stalled after %d batches; will retry on next load',
					(int) ( $result['stalls'] ?? 0 )
				)
			);
			return;
		}
```

`plugins_loaded` always calls `maybe_upgrade()` (`alt-context.php`). `LifecycleManagerTest::testStalledHealRetriesOnNextLoad` (healRuns 1 then 2 with version already matching) pins the retry.

R1-03 "healed before the read shape goes live" is still not a hard barrier on a stalled first request; it is no longer a one-shot forever-skip.

## UXW2-4-R1-30 — FIXED

Assertions:
1. `roster-people.uxmap.json` purpose still names the needs-assignment queue; zone `z-needs-assignment` survives; open question about needs-assignment as its own screen — closed.
2. Only the sibling `.md` was patched; operator labels still say cluster/identity — closed in the roster map pair (say/don't-say table).
3. `workbench-operator-loop.uxmap.json` has no `workbench-review-panel` screen — closed. Sibling `.md` ASCII exists.

```28:70:apps/prototype-wp-alt-context/docs/ux-maps/roster-people.uxmap.json
      "purpose": "People-first roster: entries table, Workbench review CTA, person workspace host, face-group drawer shim",
      ...
        {
          "id": "z-review-cta",
          "label": "Unnamed faces CTA → Workbench review queue",
```

```185:190:apps/prototype-wp-alt-context/docs/ux-maps/roster-people.uxmap.json
      "states": [
        "default",
        "loading",
        "empty",
        "error"
      ],
```

```423:425:apps/prototype-wp-alt-context/docs/ux-maps/roster-people.uxmap.json
  "open_questions": [
    "Is person workspace a route-owned screen or always an in-page panel? (modeled as deep-linkable screen with person=)",
    "Face-group drawer max_candidates=8 — confirm product top-k policy"
```

```190:220:apps/prototype-wp-alt-context/docs/ux-maps/workbench-operator-loop.uxmap.json
      "id": "workbench-review-panel",
      "kind": "screen",
      "title": "Review these faces",
      "purpose": "Review the faces in one unnamed group; Back returns to Review Suggestions",
      "route": "#/workbench?tab=scan&panel=review&cluster=",
      "code_ref": "apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterReviewPanel.tsx",
      "states": ["default", "loading", "error", "empty"],
```

`z-needs-assignment` is absent from `roster-people.uxmap.json` / `roster-people.md`. `workbench-2pane.preview.md` still mentions that zone; that is a different map and was not this finding's named surface.

## UXW2-4-R1-27 — PARTIAL

Assertions:
1. `bulkMergeMutation` / `bulkDismissMutation` have zero production callers but the suite still certifies them — closed. Mutations are gone from `useClusterActions`; `useClusterActions.bulkMerge.test.tsx` is gone. Cluster-jargon merge toasts are gone with them.
2. `RosterPage` still builds `useClusterSelection()` and passes bulk settled/failure callbacks — closed on the page. The page no longer imports selection.
3. `useRecognitionClusters` is a dead export the plan said to drop — **not closed**. Still exported; only the cooldown-gate test mounts it.
4. `useClusterSelection` leftover — **not closed**. Hook + unit tests still exist; zero production UI importer. RosterPage tests still mock the hook and bulk mutation fields.

```29:38:apps/prototype-wp-alt-context/js/admin/pages/roster/hooks/useClusterActions.ts
  const reassignMutation = useMutation<void, Error, { faceId: string; targetClusterId: string | null }>({
    mutationFn: (variables) =>
      reassignClusterIdentity({ identityId: variables.faceId, targetClusterId: variables.targetClusterId }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
      success(__('Face moved.', 'alt-context'));
```

Returned surface is `reassignMutation` / `rescanMutation` / `commitMutation` only (no bulk).

```117:124:apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionHooks.ts
/** Cooldown-gate membership: recognitionCooldownGate.test mounts this hook
 *  as one of the six gated pollers. Not a roster UI caller. */
export const useRecognitionClusters = (params: ClusterListParams = {}) =>
  useQuery<ClusterListResponse>({
    queryKey: queryKeys.clusters.list(params),
    queryFn: () => listRecognitionClusters(params),
```

```1:6:apps/prototype-wp-alt-context/js/admin/hooks/useClusterSelection.ts
import { useState, useCallback } from 'react';

/**
 * Hook to manage multi-selection of clusters.
 */
export const useClusterSelection = () => {
```

Remaining: delete or truly quarantine `useClusterSelection` (and its tests) and either drop `useRecognitionClusters` or keep a production mount. RosterPage container tests still mock `bulkMergeMutation` / `useClusterSelection` even though the page does not read them — leftover TEST-15 noise, not the original bulk toast/path.

## UXW2-4-R1-24 — PARTIAL

Assertions:
1. Walk skips unless `E2E_ROSTER_CLUSTER_ID` is set; nothing in repo/CI sets it — closed as an env-var gate. Discovery is seed-or-API.
2. Even with the env var it would fail: `listbox`/`option` vs `role=menu`/`menuitem`; `title` vs `aria-describedby` — closed by rewriting the walk for the boarded-up drawer (no Move picker).
3. Combined with R1-16 the walk would stop at the disabled branch — closed; walk now asserts honest copy and zero Move buttons.
4. Add an e2e that follows the CTA — closed.
5. Seed a deterministic cluster id so the walk runs with no env var — **not closed**. `readSeededUnlabeledClusterId` only *reads* `window.acxE2eSeed.unlabeledClusterId`; no producer in the repo. Drawer walk still `test.skip`s when seed and API both miss.

```63:73:apps/prototype-wp-alt-context/tests/e2e/a11y/roster-keyboard-walk.spec.ts
test('roster review CTA links to the workbench queue; no rail is rendered', async ({ page, baseURL }) => {
  ...
  await expect(cta.getByRole('link', { name: /Review in Workbench/i })).toHaveAttribute(
    'href',
    '#/workbench?tab=scan&rq=all.all.0',
  );
```

```117:136:apps/prototype-wp-alt-context/tests/e2e/a11y/roster-keyboard-walk.spec.ts
  if (!clusterId) {
    test.skip(
      true,
      'seeded fixture acxE2eSeed.unlabeledClusterId / top-unlabeled row absent — drawer walk needs a live face group',
    );
    return;
  }
  ...
  await expect(drawer.getByText(/Face moves happen in the Workbench review queue/i)).toBeVisible();
  await expect(drawer.getByRole('button', { name: /Move to/i })).toHaveCount(0);
```

```41:51:apps/prototype-wp-alt-context/tests/e2e/fixtures/seeded-state.ts
 * Prefer `window.acxE2eSeed.unlabeledClusterId` when the fixture is present.
 * Discovery via AltContextAdmin.endpoints.recognitionClusters /top-unlabeled
 * is fallback only. Skip naming this fixture when both are absent.
 */
export const readSeededUnlabeledClusterId = async (page: Page): Promise<string | null> =>
  page.evaluate(() => {
    const seeded = (window as unknown as { acxE2eSeed?: { unlabeledClusterId?: string } }).acxE2eSeed
      ?.unlabeledClusterId;
    return seeded ?? null;
  });
```

CTA tests always run. The drawer a11y walk is still environment-skippable; a permanently skipped drawer walk still over-reports coverage.

## UXW2-4-R1-21 — FIXED

Assertions:
1. CTA count is top-unlabeled; destination was `rq=assignment.all.0` so N unnamed groups are not in the landing queue — closed. Href is `rq=all.all.0`. Workbench `REVIEW_QUEUE_FILTER.ALL` includes CLUSTER items built from `sortedClusters` (top-unlabeled).
2. Hand-concatenated `rq=` rather than `serializeQueueState` — closed enough. Encoder uses `DEFAULT_QUEUE_STATE` fields (serialize of the default is `null` by design, so they emit the explicit triple). Test pins `parseQueueState(rq) === DEFAULT_QUEUE_STATE`.

```195:208:apps/prototype-wp-alt-context/js/admin/pages/roster/rosterRoute.ts
 * Lands on `rq=all.all.0` so the CTA count (top-unlabeled envelope total)
 * matches the landing filter. `cluster=` emission dropped (jobId precedent).
 */
export const workbenchReviewQueueUrl = (): string => {
  // Explicit default band (not serializeQueueState, which omits fully-default).
  // Encoder vocabulary matches parseQueueState / DEFAULT_QUEUE_STATE.
  const base = toWorkbench({ tab: 'scan' });
  const separator = base.includes('?') ? '&' : '?';
  const rq = `${DEFAULT_QUEUE_STATE.kind}.${DEFAULT_QUEUE_STATE.band}.${DEFAULT_QUEUE_STATE.index}`;
  return `${base}${separator}${APP_LINK_PARAMS.rq}=${rq}`;
};
```

```115:121:apps/prototype-wp-alt-context/js/admin/pages/roster/__tests__/rosterRoute.test.ts
  it('deep-links unlabeled clusters into the workbench review queue', () => {
    const href = workbenchReviewQueueUrl();
    expect(href).not.toContain('cluster=');
    const q = href.indexOf('?');
    const params = new URLSearchParams(q === -1 ? '' : href.slice(q + 1));
    expect(parseQueueState(params.get('rq'))).toEqual(DEFAULT_QUEUE_STATE);
  });
```

ALL is a superset of unnamed groups (also assignment/merge/name chips), so N is not always equal to queue length. The original empty-queue landing is closed: CLUSTER items come from the same top-unlabeled source as the CTA count (`reviewQueueDriver.ts` `sortedClusters` / `useWorkbenchFindings.ts`).

## UXW2-4-R3-05 — FIXED

Assertions:
1. Local PATCH 200 hardcodes `'roster_bound' => true` after only checking bind `=== false` — closed. Field is `bind_succeeded($bound)` (`false !== $bound && 0 !== $bound`).
2. 0-row update reports a successful bind that did not happen — closed; tests assert `false`.
3. `find_by_uuid` is not tenant-scoped so it can disagree with tenant-scoped bind — closed.

```197:225:apps/prototype-wp-alt-context/src/api/services/class-cluster-label-service.php
				$bound  = $writer->bind_person_to_cluster( $cluster_id, (int) $resolved['person_id'], $tenant_id, true );
				if ( false === $bound ) {
					return new WP_Error( 'acx_db_error', 'Could not bind person to cluster.', array( 'status' => 500 ) );
				}
				...
						'roster_bound'  => ClusterCurationWriter::bind_succeeded( $bound ),
```

```254:256:apps/prototype-wp-alt-context/src/sovereign/repositories/class-cluster-curation-writer.php
	public static function bind_succeeded( int|false $bound ): bool {
		return false !== $bound && 0 !== $bound;
	}
```

```315:326:apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-read-repository.php
		$tenant_id = trim( (string) ( TenantIdentity::resolve()['value'] ?? '' ) );
		if ( '' === $tenant_id ) {
			return null;
		}
		...
			 WHERE c.cluster_uuid = %s 
			   AND c.tenant_id = %s
```

`testLocalLabelWriteReportsRosterBoundFalseWhenClusterRowVanished` asserts `roster_bound === false` with empty `wp_acx_clusters`. Proxy path uses the same helper via `bind_persisted_person`. Already-bound same person returns `BIND_ALREADY_BOUND` (−1), which `bind_succeeded` treats as true.

## UXW2-4-R2-18 — FIXED

Assertions:
1. Comment asserts functional prev = fresh snapshot; RR7 updater passes closure `searchParams` — closed. Comment names the RR7 snapshot and the `stateRef` reducer.
2. Same-tick open+close correctness is incidental — closed with tests.

```105:129:apps/prototype-wp-alt-context/js/admin/pages/workbench/ClusterPanelContext.tsx
  // State → URL: one reducer over stateRef, one navigate per tick (close last).
  // RR7's functional updater is the closure snapshot, not a chained prev — we
  // encode `next` rather than no-op on a stale prev. History contract: both
  // open and close use {replace:true} so panel is URL state, not a stack frame.
  // Back after close therefore cannot reopen the panel.
  const dispatchClusterPanel = React.useCallback<React.Dispatch<ClusterPanelAction>>(
    (action) => {
      const next = clusterPanelReducer(stateRef.current, action);
      stateRef.current = next;
      dispatch(action);
      setSearchParams(
        (prev) => {
```

```67:82:apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/ClusterPanelContext.test.tsx
describe('ClusterPanelContext same-tick URL writer (UXW2-4-R1-17)', () => {
  it('same-tick open then close does not leave panel=review in the URL', async () => {
    ...
    expect(screen.getByTestId('route-probe').textContent).not.toContain('panel=review');
    expect(screen.getByTestId('route-probe').textContent).not.toContain('cluster=c-same');
    expect(screen.getByTestId('panel-mode').textContent).toBe('none');
  });
```

## UXW2-4-R2-12 — PARTIAL

Assertions:
1. `create_distinct()` reads `$GLOBALS['wpdb']->prefix` with no isset/instanceof guard — **partially closed**. Optional constructor prefix exists and is tested; the default path still does unguarded `$wpdb->prefix`.
2. Suffix loop 2..99 then silent fallback to the collision path — closed. Exhaustion returns `WP_Error('acx_name_collision')` (tested).

```239:278:apps/prototype-wp-alt-context/src/api/services/class-person-resolution-service.php
	public function create_distinct( string $display_name, callable $enqueue_person_created ): array|WP_Error {
		...
		for ( $suffix = 2; $suffix <= 99; $suffix++ ) {
			...
			return $this->resolve_or_create( $candidate, $enqueue_person_created );
		}

		return new WP_Error(
			'acx_name_collision',
			...
		);
	}

	private function persons_table(): string {
		if ( is_string( $this->table_prefix ) && '' !== $this->table_prefix ) {
			return $this->table_prefix . 'acx_persons';
		}

		global $wpdb;
		return $wpdb->prefix . 'acx_persons';
	}
```

```45:66:apps/prototype-wp-alt-context/tests/Unit/PersonResolutionServiceTest.php
    public function testCreateDistinctReturnsErrorWhenSuffixesExhausted(): void
    {
        ...
        $this->assertInstanceOf(\WP_Error::class, $result);
        $this->assertSame('acx_name_collision', $result->get_error_code());
    }
```

`testCreateDistinctUsesInjectedTablePrefix` covers the injected path. Default construction (and `find_by_normalized_name`'s `$wpdb->get_row`) still fatals if `wpdb` is missing — the original CLI/unstubbed-unit-test scenario.

## Undone

(none)
