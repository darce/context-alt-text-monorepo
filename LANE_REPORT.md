# Lane Report — degraded

## DEMO-UX-1-UXA-01 — PARTIAL

canon rows satisfied:

- INT-10 — satisfied for the owned remote-compute stop gate: only an explicitly online health result enables remote actions.
- RLSE-05 — satisfied for the owned failure path: unavailable health can no longer fall through as apparent online success.
- RLSE-04 — partially satisfied by making online, offline, and unavailable explicit designed domain states in the shared hook.
- INT-08 and NAV-07 remain incomplete for the global banner because its rendering and Retry action are outside this lane's file ownership.

what changed (files + why):

- `apps/prototype-wp-alt-context/js/admin/hooks/useSyncOffline.ts` — added the `SYNC_AVAILABILITY` as-const domain status (`online`, `offline`, `unavailable`), a resolver, and an exhaustive switch. Offline and unavailable/unknown now gate remote compute; only online enables it. Existing Analyze/Describe consumers already use this hook and their existing disabled-reason controls now activate for unavailable health too.
- `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useSyncOffline.test.ts` — replaced the binary assertions with the complete observable table: online, offline, loading/unknown, and failed/unavailable.
- A future burst-compute warming state slots into `SYNC_AVAILABILITY`, is mapped in `resolveSyncAvailability`, and gets a non-online branch beside the existing offline/unavailable cases in `useSyncOffline`; consumers do not need to return to a boolean-only health model.

RED output (test-first lanes):

```text
❯ js/admin/hooks/__tests__/useSyncOffline.test.ts (3 tests | 1 failed)
FAIL  ... > maps unavailable health ...
AssertionError: expected false to be true
- Expected: true
+ Received: false
Test Files  1 failed (1)
Tests  1 failed | 2 passed (3)
```

GREEN output:

```text
Test Files  1 passed (1)
Tests  4 passed (4)
```

residual risk / what a reviewer should attack:

- `pages/workbench/DegradedModeBanner.tsx` independently returns `null` when sync-health data is absent and has no retry control. That file is outside this lane's ownership, so the named unavailable banner and Retry requirement are not fixed here. Reviewers should require its owning lane to consume the explicit availability state, name the recognition component, state what local work remains available, and call the health query's `refetch` from Retry.
- The current shared hook API remains boolean for compatibility with non-owned consumers. The enum/resolver is the extension seam, but the presentation layer must adopt it to distinguish offline, unavailable, and the future additional named state in copy.

## DEMO-UX-1-UXA-02 — FIXED

canon rows satisfied:

- INT-08 — the dialog exposes job progress without presenting a fake cancellation action.
- INT-10 — the running status is preserved and the next effect of closing is explicit; the unsupported stop capability is not misrepresented.
- HAI-18 — on-screen copy explicitly states that closing does not stop the export and tells the operator where its future status remains available.

what changed (files + why):

- `apps/prototype-wp-alt-context/js/admin/pages/retention/RetentionDialogs.tsx` — renamed the lying export `Cancel` action to `Close`, added explicit continuation/reopen copy, kept progress visible, and centralized terminal export statuses in an as-const object.
- `apps/prototype-wp-alt-context/js/admin/pages/retention/useRetentionPageState.ts` — closing now preserves the export job ID, so polling continues and reopening restores the same visible job status. Successful download explicitly clears the ID.
- `apps/prototype-wp-alt-context/js/admin/pages/__tests__/RetentionPage.test.tsx` — proves there is no control claiming cancellation and that Close/reopen preserves a pending job and disables duplicate start.
- Repository API inspection found start, status, and data endpoints for retention export, but no export-cancel endpoint; the supported no-false-cancel branch was therefore implemented.

RED output (test-first lanes):

```text
❯ js/admin/pages/__tests__/RetentionPage.test.tsx (12 tests | 1 failed)
FAIL  ... > closes a running export without claiming cancellation and preserves its visible status
Error: expect(element).not.toBeInTheDocument()
expected document not to contain element, found <button>Cancel</button> instead
Test Files  1 failed (1)
Tests  1 failed | 11 passed (12)
```

GREEN output:

```text
Test Files  1 passed (1)
Tests  12 passed (12)
```

residual risk / what a reviewer should attack:

- The backend still provides no actual export cancellation capability, so a running export cannot be stopped from this UI. The fix removes the deceptive claim and preserves truthful status; adding a real stop later requires a backend cancel endpoint plus a dedicated mutation.
- Review escape-key and overlay-close behavior manually to confirm the retained job status is equally clear for every dialog dismissal path; all paths share the same reducer action.

## DEMO-UX-1-UXA-09 — FIXED

canon rows satisfied:

- NAV-07 — the terminal load-error screen now has a labelled route to the known Dashboard surface.
- A11Y-17 — the alert names the Recognition API settings load failure and gives concrete Retry/return recovery choices in text.

what changed (files + why):

- `apps/prototype-wp-alt-context/js/admin/pages/SettingsPage.tsx` — replaced the dead-end sentence with an alert that names the failed settings resource, provides a Retry button wired to `settingsQuery.refetch`, exposes retry-in-progress state, and links to Dashboard through the canonical `toDashboard()` builder.
- `apps/prototype-wp-alt-context/js/admin/pages/__tests__/SettingsPage.test.tsx` — verifies the actionable error text, Retry effect, accessible labels, and canonical Dashboard href.

RED output (test-first lanes):

```text
❯ js/admin/pages/__tests__/SettingsPage.test.tsx (48 tests | 1 failed)
FAIL  ... > offers retry and a labelled Dashboard escape when Recognition API settings fail to load
TestingLibraryElementError: Unable to find an accessible element with the role "alert"
Test Files  1 failed (1)
Tests  1 failed | 47 passed (48)
```

GREEN output:

```text
Test Files  1 passed (1)
Tests  48 passed (48)
```

residual risk / what a reviewer should attack:

- Verify in the WordPress host that hash navigation from the error state retains the normal plugin shell and that focus placement after a failed Retry remains understandable to keyboard and screen-reader users.

## Final verification

```text
npx vitest run js/admin/hooks/__tests__/useSyncOffline.test.ts js/admin/pages/__tests__/RetentionPage.test.tsx js/admin/pages/__tests__/SettingsPage.test.tsx
Test Files  3 passed (3)
Tests  64 passed (64)

npm run typecheck
tsc --noEmit --project tsconfig.type-check.json
exit 0

npx eslint <changed TypeScript files>
exit 0

npx prettier --check <changed TypeScript files>
All matched files use Prettier code style!
```
