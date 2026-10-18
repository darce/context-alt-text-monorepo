# DEMOLIVE-4 round 3 — DashboardPage caller test

Lane `demolive-4`. Repair the `DashboardPage.test.tsx` Reset-mirror click that round 2 left red.

## Edits

- `apps/prototype-wp-alt-context/js/admin/pages/__tests__/DashboardPage.test.tsx:1` — added `within` to the existing `@testing-library/react` import (`fireEvent, render, screen, within`). No second import.
- `apps/prototype-wp-alt-context/js/admin/pages/__tests__/DashboardPage.test.tsx:1078-1084` — click `[Reset mirror]`, assert `mutate` is **not** called, then confirm inside the dialog, then `toHaveBeenCalledTimes(1)`.

Confirm label used: **`Reset mirror`**.

`pendingReplayCount` in this test: **0**. The `it('renders a reset mirror action…')` block mocks `useSyncStatus` with `last_snapshot_version: 0` and `failed_curation_operations: 2` but **omits** `pending_curation_operations` (`DashboardPage.test.tsx:1043-1051`). `DashboardPage.tsx:73` sets `pendingReplayCount = normalizeCount(syncStatus?.pending_curation_operations)`; `normalizeCount` (`DashboardPage.tsx:39-45`) returns `0` for `undefined`. `DashboardSyncHealthSection.tsx:146-149` therefore uses confirmLabel `__('Reset mirror')`, not `Discard %d and reset`. `within(dialog)` is mandatory: trigger and confirm share that name.

## Green suites

From `apps/prototype-wp-alt-context`:

`npm run test -- js/admin/pages/__tests__/DashboardPage.test.tsx`

```
 Test Files  1 passed (1)
      Tests  33 passed (33)
   Start at  09:11:49
   Duration  2.63s (transform 472ms, setup 252ms, import 641ms, tests 1.11s, environment 469ms)
```

Exit 0. Re-run after M1 revert (09:17:38): same 33 passed, exit 0.

`npm run test -- js/admin` — **not green**. Did not narrow the command.

```
 Test Files  1 failed | 220 passed (221)
      Tests  1 failed | 2618 passed (2619)
   Start at  09:11:55
   Duration  316.78s (transform 10.85s, setup 42.83s, import 36.58s, tests 101.20s, environment 99.20s)
```

Exit 1. Unrelated to this edit (owned files: `DashboardPage.test.tsx` + this report only):

```
FAIL  js/admin/__tests__/dashboard-uxmap-code-parity.test.ts > dashboard ux-map code parity (DUX-W2D14) > RV-16: Sync Health composition prose is falsifiable against the component
AssertionError: map cites :68 for "showMirrorDivergenceBanner" but that line does not mention showMirrorDivergenceBanner: expected 'action={{label:__(\'Opensettings\',\'…' to contain 'showMirrorDivergenceBanner'
```

Round 2 inserted ConfirmDialog state above the banner, so the ux-map line cite drifted. Out of this round's scope (`DashboardSyncHealthSection.tsx` / ux-map files are frozen).

## TEST-15

Mutant M1: `DashboardSyncHealthSection.tsx:95` `onClick={() => setConfirmOpen(true)}` → `onClick={onResetMirror}`.

Re-ran `npm run test -- js/admin/pages/__tests__/DashboardPage.test.tsx`.

Verbatim failing assertion:

```
AssertionError: expected "vi.fn()" to not be called at all, but actually been called 1 times
```

```
 ❯ js/admin/pages/__tests__/DashboardPage.test.tsx:1080:24
    1080|     expect(mutate).not.toHaveBeenCalled();
```

Exit code: `1` (`Tests  1 failed | 32 passed (33)`).

Reverted M1 to `onClick={() => setConfirmOpen(true)}`. Re-ran caller test: 33 passed, exit 0.

`git status --short` after revert (mutant gone):

```
 M apps/prototype-wp-alt-context/js/admin/pages/__tests__/DashboardPage.test.tsx
```

`DashboardSyncHealthSection.tsx` is not in the dirty list.

## Could not falsify

- First-click `expect(mutate).not.toHaveBeenCalled()` **did** go red under M1; the pin holds.
- Confirming through the dialog still calls `mutate` once after revert; that half of the case stayed green under M1 only because the first assertion failed first.
- Could not make `js/admin` fully green without editing the round-2 ux-map / section file, which this round forbids.
