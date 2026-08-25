# DEMOLIVE-9 demolive-f2 — delete the roster ConfirmDialog re-export shim

Lane: `demolive-f2`
Task: `DEMOLIVE-9`
Policy: Greenfield delete-over-flag. Did not change ConfirmDialog behaviour, props, or exports. Shared copy keeps `description: React.ReactNode`.

## Importers found

Searched `apps/prototype-wp-alt-context/js` for `from '...ConfirmDialog'` and `roster/ConfirmDialog`.

| File | Old specifier | Action |
| --- | --- | --- |
| `js/admin/pages/roster/RosterEntriesTable.tsx` | `./ConfirmDialog` | Updated to `../../components/ui/ConfirmDialog` |
| `js/admin/pages/workbench/identity-clusters/ClusterConfirmDialog.tsx` | `../../roster/ConfirmDialog` | Updated to `../../../components/ui/ConfirmDialog` |
| `js/admin/pages/roster/__tests__/ConfirmDialog.test.tsx` | `../ConfirmDialog` | `git mv` beside the component; specifier stays `../ConfirmDialog` |
| `js/admin/pages/dashboard/DashboardSyncHealthSection.tsx` | already `../../components/ui/ConfirmDialog` | Left alone |

Work order named the first and the test. ClusterConfirmDialog was a third live importer of the roster path.

## Move and delete

- `git mv` `js/admin/pages/roster/__tests__/ConfirmDialog.test.tsx` → `js/admin/components/ui/__tests__/ConfirmDialog.test.tsx` (rename, 100% similarity; import still `from '../ConfirmDialog'`).
- Deleted `js/admin/pages/roster/ConfirmDialog.tsx` (one-line re-export shim).
- Canonical component unchanged: `js/admin/components/ui/ConfirmDialog.tsx`.

## Baseline typecheck

`node_modules` was absent in this sandbox, so the named script could not run until `npm ci`.

```
cd apps/prototype-wp-alt-context && npm run typecheck; echo "exit=$?"
```

Before install (repo root, no package.json):

```
npm error enoent Could not read package.json
exit=254
```

Before install (plugin dir):

```
> prototype-wp-alt-context@0.0.4 typecheck
> tsc --noEmit --project tsconfig.type-check.json

sh: 1: tsc: not found
exit=127
```

After `npm ci` the files were already edited, so there is no post-install pre-change typecheck. Post-change typecheck is below.

## Verify (verbatim)

Scripts used: `typecheck` and `test` from `apps/prototype-wp-alt-context/package.json` (`tsc --noEmit --project tsconfig.type-check.json`, `vitest run`). npm, not pnpm.

```
cd apps/prototype-wp-alt-context && npm run typecheck; echo "exit=$?"
```

```
> prototype-wp-alt-context@0.0.4 typecheck
> tsc --noEmit --project tsconfig.type-check.json

exit=0
```

```
cd apps/prototype-wp-alt-context && npm test -- ConfirmDialog; echo "exit=$?"
```

```
> prototype-wp-alt-context@0.0.4 test
> vitest run ConfirmDialog

 RUN  v4.1.5 /home/gate/grok-sandbox/feature-demolive-f2-1219eb61/apps/prototype-wp-alt-context

 ✓ js/admin/components/ui/__tests__/ConfirmDialog.test.tsx (2 tests) 392ms
     ✓ renders copy and handles confirm/cancel/escape interactions  350ms

 Test Files  1 passed (1)
      Tests  2 passed (2)
   Start at  11:45:26
   Duration  2.59s (transform 400ms, setup 603ms, import 421ms, tests 392ms, environment 882ms)

exit=0
```

## Leftover-import search (empty)

```
grep -RIn "roster/ConfirmDialog" apps/prototype-wp-alt-context/js; echo "grep_exit=$?"
```

```
grep_exit=1
```

No output. Exit 1 is grep's no-match status. No importer of `roster/ConfirmDialog` remains under `js/`.
