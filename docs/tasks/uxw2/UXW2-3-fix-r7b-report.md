# UXW2-3-fix-r7b report

Person-row confirm on the labelling panel and Library now writes the chosen roster id. Library idle/pending copy matches the other two surfaces.

## Items

| Id | Commit subject | Proving test | Verbatim RED | GREEN |
| --- | --- | --- | --- | --- |
| UXW2-3-R3-12 | `fix(fe): UXW2-3-R3-12 bind chosen roster id on panel and Library person confirm` | `checkmark on the second same-fold person carries that id into the write (UXW2-3-R3-12)`; `clicking the second of two same-fold people binds that roster id (UXW2-3-R3-12)` | See below. Mutant A: bind call count 0. Mutant B: received id `1` not `2`. | Filter GREEN after restore: `Tests  3 passed \| 94 skipped (97)` |
| UXW2-3-R1-16 (i) | `fix(fe): UXW2-3-R1-16i Library commit button says Save name` | `default Library row commit button is Save name (UXW2-3-R1-16i)` | See below. Accname was `Save`. | File `Tests  6 passed (6)` / `Tests  36 passed (36)` |
| type fixture | `test(fe): UXW2-3-R3-12 type bindToRosterEntry on save-action fixture` | n/a | n/a | `tsc` exit 0 |

Commits verified with `git log --format=%s --fixed-strings --grep="<subject>"`.

`useClusterSaveHandlers.ts` was edited because the `ClusterSaveMutations` type change forced it (`bindToRosterEntry` at `:31`). No other sibling.

## 1. UXW2-3-R3-12 — chosen roster id survives the write

Two same-fold people are distinguishable only by id ([TEST-15]). NameFaceControl already emits `{ kind: 'roster', rosterEntryId, name }`. The panel and Library were dropping that id and writing a label string.

**Panel.** `resolveCommit` still calls `submitLabel` — no second write path. Roster resolutions pass `rosterEntryId` (`ClusterLabelingPanel.tsx:414-419`). `submitLabel` still runs, in order:

- double-submit latch: `submittingRef.current \|\| isBusy` then `submittingRef.current = true` (`:359-362`); cleared in `finally` (`:399`)
- reserved-label check: `isReservedLabel(trimmed)` (`:367`)
- duplicate guard: local (`:372-378`) then remote (`:379-383`), including `skipPersonOnlyGuard`

Only after those does the write choose the id-preserving call (`:390-394`): `bindMutation.mutateAsync({ rosterEntryId, name })` → `commitClusterToRosterEntry` (`:258-266`). No `rosterEntryId` still uses `updateClusterLabel`.

**Library.** `onPersonSelect` is now `(label: string, rosterEntryId: number)` (`ClusterEditForm.tsx:44`). Same-fold confirm passes the chosen id (`:131-137`). Comment updated to match the code.

**Downstream can accept an id.** `handlePersonSelect` consumes `rosterEntryId` (`useClusterSaveAction.ts:134, :170-172`) and calls `mutations.bindToRosterEntry` when an id is present. `IdentityClusterItem.tsx:174` implements that as `commitClusterToRosterEntry({ clusterId, rosterEntryId })`. Did not fall back to `mutations.rename` (that path is still name-in/rename-out at `applyPersonLabel` `:119-120` — used only when no id is supplied).

Pinned: panel write is `commitClusterToRosterEntry({ clusterId, rosterEntryId: 2 })` not id `1` (`ClusterLabelingPanel.test.tsx:1213-1220`). Library `onPersonSelect` is called with `('ALEX CARTER', 2)` not `1` (`ClusterEditForm.test.tsx:169-171`).

### TEST-15 mutant A RED (panel write name only)

Filter `-t 'checkmark on the second same-fold person carries that id into the write'` selected 1 test.

```
AssertionError: expected "vi.fn()" to be called with arguments: [ { …(2) } ]

Number of calls: 0
```

Restore: id branch back at `submitLabel` write step. `git diff` on the panel showed only the intended bind path.

### TEST-15 mutant B RED (Library first matching id)

Filter `-t 'clicking the second of two same-fold people binds that roster id'` selected 1 test.

```
AssertionError: expected "vi.fn()" to be called with arguments: [ 'ALEX CARTER', 2 ]

Received:

  1st vi.fn() call:

  [
    "ALEX CARTER",
-   2,
+   1,
  ]
```

Fixture people are distinguishable. Restore: `onPersonSelect(resolution.name, resolution.rosterEntryId)`. `git diff` on ClusterEditForm showed only the intended id pass.

UX map: no new zone/state. Write-path only.

## 2. UXW2-3-R1-16 (i) — Library idle/pending copy

`ClusterEditForm.tsx:81` default is `'Save name'` / `'Saving name…'`. Queued/saved/matched labels in `IdentityClusterItem.tsx:317-329` unchanged (`Saving…` / `Saved!` / Assign / Merge). Default Library row still passes `saveLabel={undefined}`.

`workbench-2pane.uxmap.json` `act-name-cluster` already said `Save name (NameFaceControl)`. Code was the drift; map + render not edited.

### TEST-15 mutant RED (default reverted to `'Save'`)

Filter `-t 'default Library row commit button is Save name'` selected 1 test.

```
TestingLibraryElementError: Unable to find an accessible element with the role "button" and name "Save name"
```

Accessible roles listed `Name "Save"`. Restore: `'Save name'` default. `git diff` on ClusterEditForm showed only that copy pair.

## Gate

From `apps/prototype-wp-alt-context`, at the last code commit:

```
npm test
```

```
 Test Files  211 passed (211)
      Tests  2434 passed (2434)
```

```
npm run typecheck
```

exit 0, no diagnostics.

## Undone

- Singleton Library rows (`!editableClusterId`) cannot bind by id. `handlePersonSelect` with a `rosterEntryId` then hits `useClusterSaveAction.ts:174-175` (`Cannot bind this person: missing group.`) instead of `createClusterForIdentity` (`:123-124`), which is still name-in. `commitClusterToRosterEntry` needs a cluster id; `useClusterMutations.ts` is out of bounds so there is no create-then-bind. IdentityClusterItem always has a cluster when `canEdit` is true; the hole is `canSearchForMatch` singletons.
- `onSave` fallback when `onPersonSelect` is absent still writes a name (`ClusterEditForm.tsx:138-139`). IdentityClusterItem always passes `onPersonSelect`.
- Duplicate-guard **Rename anyway** still writes the label string (`submitLabel(duplicateGuard.label, { skipDuplicateGuard: true })`). That is the explicit rename path, not a person-row bind.
- Panel pending copy is still `'Saving...'` / `'Merging...'` (`ClusterLabelingPanel.tsx` pendingLabel). Item 2 was Library-only.
- `bindToRosterEntry` cannot abort the HTTP request: `commitClusterToRosterEntry` takes no signal (`rosterApi.ts` out of bounds). Timeout wrapper still races the promise.
- `ClusterEditForm.tsx` still pairs `ariaLabel` + `visibleLabel` both `'Person name'`. Other lane.
- No contract edit: no payload, endpoint, or enum change. Reused existing `commitClusterToRosterEntry`.
- Handoff Python API / `make context` unavailable on this throwaway mirror. No handoff write.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.
