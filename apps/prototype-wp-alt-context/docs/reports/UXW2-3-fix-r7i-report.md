# UXW2-3-fix-r7i report

Singleton Library rows can bind a roster person in one `create-for-identity` request. PHP owns create+bind. FE does not fire a second mutation.

## Result

Closed. `POST /recognition/clusters/create-for-identity` accepts optional `roster_entry_id`. When present, the same request creates the group and binds it with the same cluster-row + `cluster_person_bound` write as `commit_roster_cluster`. Person is resolved before create, so a missing person leaves no orphan. Omit `roster_entry_id` and the response is the old shape plus `person_id` / `person_uuid` / `person_name` all null.

Library singletons (`canSearchForMatch`, no `editableClusterId`, `anchorIdentityId` present) call `createClusterForIdentity(anchorIdentityId, name, signal, rosterEntryId)`. Clustered rows still go through `bindToRosterEntry` → `commitClusterToRosterEntry`. `'Cannot bind this person: missing group.'` stays reachable when both cluster id and anchor identity are missing.

Create+bind share one `run_transactional`. Bind failure rolls back the create. The `acx_cluster_created_bind_failed` code exists only as the FE handler for a non-atomic bind miss; PHP does not emit it.

UX maps not edited. Write-path only.

## Closure

| clause | commit subject | test name | verbatim mutant RED | GREEN selected/total |
| --- | --- | --- | --- | --- |
| PHP bind + enqueue | `fix(php): UXW2-3-R7B-01 bind person on create-for-identity` | `testCreateForIdentityWithRosterEntryIdBindsPersonAndEnqueuesClusterPersonBound` | M2: `Failed asserting that null is identical to 7.` M3: `Failed asserting that actual size 0 matches expected size 1.` | `OK (1 test, 9 assertions)` / 1 selected |
| PHP omit id | same | `testCreateForIdentityWithoutRosterEntryIdLeavesPersonNullAndSkipsBind` | n/a (characterization of the omit path) | included in after suite |
| PHP missing person | same | `testCreateForIdentityMissingPersonDoesNotLeaveOrphanCluster` | n/a (resolve-before-create; no orphan) | included in after suite |
| FE singleton create | `fix(fe): UXW2-3-R7B-01 singleton rows create-and-bind` | `singleton row picks a roster person via createClusterForIdentity (UXW2-3-R7B-01)` | M1: `AssertionError: expected "vi.fn()" to be called 1 times, but got 0 times` | `Tests  1 passed \| 23 skipped (24)` |
| FE missing-group | same | `neither cluster id nor anchor still renders Cannot bind this person: missing group.` | M4: `AssertionError: expected "vi.fn()" to be called with arguments: [ Array(1) ]` / `Number of calls: 0` | `Tests  1 passed \| 23 skipped (24)` |
| FE clustered bind | same | `clustered row still routes through bindToRosterEntry (UXW2-3-R7B-01)` | n/a (unchanged path) | included in after suite |

Unmutated filter counts before each mutant (non-zero):

- M1 filter `-t 'singleton row picks a roster person via createClusterForIdentity'`: `Tests  1 passed | 23 skipped (24)`
- M2/M3 filter `testCreateForIdentityWithRosterEntryIdBindsPersonAndEnqueuesClusterPersonBound`: `OK (1 test, 9 assertions)`
- M4 filter `-t 'neither cluster id nor anchor still renders Cannot bind this person: missing group.'`: `Tests  1 passed | 23 skipped (24)`

### M1 RED (revert singleton branch to missing-group)

```
AssertionError: expected "vi.fn()" to be called 1 times, but got 0 times
 ❯ js/admin/pages/workbench/identity-clusters/__tests__/useClusterSaveAction.test.tsx:604:48
    604|     expect(mutations.createClusterForIdentity).toHaveBeenCalledTimes(1…
```

Restore: `git checkout` `useClusterSaveAction.ts`. GREEN: `Tests  1 passed | 23 skipped (24)`.

### M2 RED (create only, drop bind)

```
Failed asserting that null is identical to 7.

/home/ubuntu/uxw2/uxw2-3-fix-r7i/apps/prototype-wp-alt-context/tests/Unit/ClusterMembershipServiceTest.php:298
```

Restore: `git checkout` `class-cluster-membership-service.php`. GREEN: `OK (1 test, 9 assertions)`.

### M3 RED (keep cluster update, skip enqueue)

Row assertions still ran (8 assertions). Enqueue count failed:

```
Failed asserting that actual size 0 matches expected size 1.

/home/ubuntu/uxw2/uxw2-3-fix-r7i/apps/prototype-wp-alt-context/tests/Unit/ClusterMembershipServiceTest.php:308
```

Restore: `git checkout` `class-cluster-membership-service.php`. GREEN: `OK (1 test, 9 assertions)`.

### M4 RED (drop `anchorIdentityId` guard)

```
AssertionError: expected "vi.fn()" to be called with arguments: [ Array(1) ]

Number of calls: 0
 ❯ js/admin/pages/workbench/identity-clusters/__tests__/useClusterSaveAction.test.tsx:629:22
    629|     expect(setError).toHaveBeenCalledWith('Cannot bind this person: mi…
```

Restore: `git checkout` `useClusterSaveAction.ts`. GREEN: `Tests  1 passed | 23 skipped (24)`.

## Gate

From `apps/prototype-wp-alt-context`.

Before first code commit:

```
composer test
OK (1765 tests, 8518 assertions)
```

```
npx vitest run
 Test Files  211 passed (211)
      Tests  2453 passed (2453)
```

After last code commit:

```
composer test
OK (1768 tests, 8542 assertions)
```

```
npx vitest run
 Test Files  211 passed (211)
      Tests  2458 passed (2458)
```

```
npm run typecheck
```

exit 0, no diagnostics.

Delta: PHP +3 tests / +24 assertions. FE +5 tests. No lost tests.

## file:line

Re-derived with `sed -n '<N>p' <file>` from `apps/prototype-wp-alt-context` after the last code commit.

`sed -n '140p' src/api/services/class-cluster-membership-service.php`

```
		$roster_raw  = $request->get_param( 'roster_entry_id' );
```

`sed -n '181,184p' src/api/services/class-cluster-membership-service.php`

```
		if ( null !== $roster_entry_id ) {
			$resolved_person = $binder->resolve_person( $roster_entry_id );
			if ( is_wp_error( $resolved_person ) ) {
				return $resolved_person;
```

`sed -n '225,226p' src/api/services/class-cluster-membership-service.php`

```
				if ( is_array( $resolved_person ) ) {
					$bound = $binder->bind_cluster_to_person(
```

`sed -n '261,263p' src/api/services/class-cluster-membership-service.php`

```
						'person_id'    => $person_id,
						'person_uuid'  => $person_uuid,
						'person_name'  => $person_name,
```

`sed -n '129,133p' src/api/services/class-cluster-person-bind-service.php`

```
		$queued = $enqueue(
			'cluster_person_bound',
			$cluster_id,
			max( 1, $local_revision ),
			$this->bound_curation_payload( $cluster_id, $person_uuid, $person_name )
```

`sed -n '495,496p' src/api/class-api.php`

```
		if ( null !== $person_id ) {
			$binder = new ClusterPersonBindService();
```

`sed -n '73,75p' js/admin/pages/workbench/identity-clusters/IdentityClusterItem.tsx`

```
  const isSingleton = !editableClusterId && cluster.members.length === 1;
  const canEdit = canLabel && Boolean(editableClusterId) && !cluster.clusteringPending;
  const canSearchForMatch = canLabel && isSingleton && !cluster.clusteringPending;
```

`sed -n '83p' js/admin/pages/workbench/identity-clusters/IdentityClusterItem.tsx`

```
  const anchorIdentityId = representative?.identity_id;
```

`sed -n '175,188p' js/admin/pages/workbench/identity-clusters/useClusterSaveAction.ts`

```
        if (typeof rosterEntryId === 'number') {
          if (editableClusterId && mutations.bindToRosterEntry) {
            mutations.bindToRosterEntry(rosterEntryId, canonical, abortController.signal);
            mutationStarted = true;
          } else if (anchorIdentityId) {
            mutations.createClusterForIdentity(
              anchorIdentityId,
              canonical,
              abortController.signal,
              rosterEntryId,
            );
            mutationStarted = true;
          } else {
            setError(__('Cannot bind this person: missing group.', 'alt-context'));
          }
```

`sed -n '131,132p' js/admin/api/recognition/clusterApiMutations.ts`

```
  if (typeof request.rosterEntryId === 'number') {
    body.roster_entry_id = request.rosterEntryId;
```

`sed -n '152,154p' js/admin/pages/workbench/identity-clusters/useClusterActionMutations.ts`

```
      if (message.includes('acx_cluster_created_bind_failed')) {
        invalidateQueries();
        onError?.(__('The group was created but the person was not bound.', 'alt-context'));
```

`IdentityClusterItem.tsx:168-174` still implements clustered bind via `commitClusterToRosterEntry`. Singleton person-select no longer calls that callback.

## Undone

- PHP does not emit `acx_cluster_created_bind_failed`. Create and bind share one transaction; bind failure rolls back the cluster insert. Missing person is rejected before create. FE still handles that code and invalidates queries if a future non-atomic path appears.
- `IdentityClusterItem` `bindToRosterEntry` still re-raises `'Cannot bind this person: missing group.'` when `editableClusterId` is falsy. Singleton person-select no longer reaches that callback.
- `onPersonSelect` absent still writes a name (`ClusterEditForm`). IdentityClusterItem always passes `onPersonSelect`.
- Proxy-to-backend `create-for-identity` now forwards `roster_entry_id` when present. Recognition-service bind composition is out of this plugin.
- UX maps not updated (in scope: do not touch `docs/ux-maps/**`).
- Handoff Python API / `make context` unavailable on this throwaway mirror. No handoff write.
