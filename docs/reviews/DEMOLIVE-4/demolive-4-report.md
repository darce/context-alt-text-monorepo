# DEMOLIVE-4 — act-reset-mirror confirm dialog

Lane `demolive-4`. Round 2.

## Changes (file:line)

- `apps/prototype-wp-alt-context/js/admin/components/ui/ConfirmDialog.tsx:1-51` — moved roster ConfirmDialog here unchanged except `description: React.ReactNode` at L18 (was `string`). Buttons still `disabled={isPending}` (other-lane finding).
- `apps/prototype-wp-alt-context/js/admin/pages/roster/ConfirmDialog.tsx:1` — re-export: `export { ConfirmDialog } from '../../components/ui/ConfirmDialog';`
- `apps/prototype-wp-alt-context/js/admin/pages/dashboard/DashboardSyncHealthSection.tsx:3` — import `Check`.
- `apps/prototype-wp-alt-context/js/admin/pages/dashboard/DashboardSyncHealthSection.tsx:10` — import shared `ConfirmDialog`.
- `apps/prototype-wp-alt-context/js/admin/pages/dashboard/DashboardSyncHealthSection.tsx:55` — `confirmOpen` local state. Props interface unchanged.
- `apps/prototype-wp-alt-context/js/admin/pages/dashboard/DashboardSyncHealthSection.tsx:95` — trigger `onClick={() => setConfirmOpen(true)}` (no longer `onResetMirror`).
- `apps/prototype-wp-alt-context/js/admin/pages/dashboard/DashboardSyncHealthSection.tsx:101-151` — controlled ConfirmDialog (`open` / `onOpenChange` [rg-004]); confirm closes then calls `onResetMirror`.
- `apps/prototype-wp-alt-context/js/admin/pages/dashboard/__tests__/DashboardSyncHealthSection.test.tsx:1` — import `within`.
- `apps/prototype-wp-alt-context/js/admin/pages/dashboard/__tests__/DashboardSyncHealthSection.test.tsx:155-157` — breaker-open recovery now confirms through the dialog.
- `apps/prototype-wp-alt-context/js/admin/pages/dashboard/__tests__/DashboardSyncHealthSection.test.tsx:160-287` — five new confirm-dialog cases.
- `apps/prototype-wp-alt-context/docs/ux-maps/dashboard.uxmap.json:281` — `act-reset-mirror.irreversible` `false` → `true`.
- `apps/prototype-wp-alt-context/docs/ux-maps/dashboard.md:356-363` — documents shipped confirm (replaces the `onResetMirror` direct-click drift note).

## Confirm copy (verbatim)

Title: `Reset the local mirror?`

Always: `Deletes this site's copy of face groups and identity members, then downloads them again from the backend.`

When `pendingReplayCount > 0` (icon `AlertTriangle`, `aria-hidden="true"`, color `var(--acx-color-warning-pill-text)`):

`%d pending local changes have not reached the backend yet. Reset discards them. They cannot be recovered.`

confirmLabel: `Discard %d and reset`

When `pendingReplayCount === 0` (icon `Check`, `aria-hidden="true"`, color `var(--acx-color-success)`):

`No pending local changes. Nothing will be lost.`

confirmLabel: `Reset mirror`

## `irreversible: true` justification

`Sync_Status_Controller::reset_projection_tables_transactionally` (`src/api/class-sync-status-controller.php`) DELETEs from `RESET_TABLE_SUFFIXES = {acx_clusters, acx_identity_members, acx_sync_outbox}`, then re-pulls a backend snapshot. The re-pull restores clusters and identity_members but NOT `acx_sync_outbox` — those are local edits the backend has never seen. Reversible for face groups, irreversible for pending local changes.

## Tests

Command: `cd apps/prototype-wp-alt-context && npm run test -- js/admin/pages/dashboard`

- Before: `DashboardSyncHealthSection.test.tsx` 6 tests.
- After: `DashboardSyncHealthSection.test.tsx` 11 tests (6 + 5).
- Green after revert: 6 files, 61 tests passed.

## TEST-15

Restored `onClick={onResetMirror}` on the trigger, re-ran `js/admin/pages/dashboard/__tests__/DashboardSyncHealthSection.test.tsx`.

Verbatim FAIL line (targeted case "does not call onResetMirror when Reset mirror is clicked"):

```
AssertionError: expected "vi.fn()" to not be called at all, but actually been called 1 times
```

Location:

```
 ❯ js/admin/pages/dashboard/__tests__/DashboardSyncHealthSection.test.tsx:181:31
    181|     expect(onResetMirror).not.toHaveBeenCalled();
```

Exit code: `1` (6 failed | 5 passed).

Reverted trigger to `onClick={() => setConfirmOpen(true)}`. Re-ran `js/admin/pages/dashboard`: 61 passed, exit 0. Confirmed revert.

## Not done

- Did not edit `DashboardPage.tsx` or the props interface (out of scope).
- Did not change ConfirmDialog `disabled={isPending}` (other-lane finding).
- Did not run PHP/Python suites or the full JS suite.
- `js/admin/pages/__tests__/DashboardPage.test.tsx` still clicks `[Reset mirror]` and expects `mutate` immediately. That file is outside this lane's owned paths; the dashboard subdirectory suite does not include it.
