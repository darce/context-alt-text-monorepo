LANE: dux-w2e-d7
STATUS: complete
COMMITS: 8fd847421fa7bee405c2204f2e7f18f2be303fcc test(admin,DUX-W2D7-RV-01,DUX-W2D7-RV-02): RED guard missing activeStep and unique nav name
0ae122b7c0621c8cf04cc7ddcbd430a9832ab1d4 fix(admin,DUX-W2D7-RV-01,DUX-W2D7-RV-02): guard missing activeStep and label nav only
TESTS: focused Vitest StepMap.test.tsx + WorkbenchPage.test.tsx — 18 passed / 0 failed (v4.1.5)
RED: StepMap.test.tsx 2 failed / 1 passed against HEAD 877dc6c4 before the fix commit
HOUSE RULES: i18n __(..., "alt-context"); --acx-* tokens only; sr-007 STEP_MAP_VALUES; sr-001 no assertion weakening; TEST-15 RED proven; NAV-09 progress map; A11Y-21 position live region kept on the hit path

## DUX-W2D7-RV-01 — STATUS: fixed

Guard `activeIndex >= 0` before reading `steps[activeIndex].label`. On miss, render the nav + ordered steps with no position line, no `aria-current`, all items Remaining (`index < -1` is false). Does not clamp (would lie about the current step).

RED proof (vitest, current HEAD before fix):
```
FAIL  js/admin/components/ui/__tests__/StepMap.test.tsx > StepMap > renders without throwing when activeStep is absent from steps
TypeError: Cannot read properties of undefined (reading 'label')
 ❯ StepMap js/admin/components/ui/StepMap.tsx:33:12
     33|     active.label,
```
GREEN: same test asserts no throw, 2 list items Remaining, no status region, no aria-current.

## DUX-W2D7-RV-02 — STATUS: fixed

Label the `<nav>` only. Removed duplicate `aria-label="Progress"` from `<ol>`. Existing test now asserts nav name Progress and that the list is not named Progress (correction of a wrong list-name assertion, not a weakening: nav name still required; list existence/OL/items/current/complete/remaining/position text still required).

RED proof:
```
FAIL  ... maps the ordered flow, current position, completed steps, and remaining steps without color alone
Error: expect(element).not.toHaveAccessibleName()
Expected element not to have accessible name:
  Progress
Received:
  Progress
 ❯ js/admin/components/ui/__tests__/StepMap.test.tsx:27:22
```
GREEN: nav named Progress; list unnamed; rotor can tell chrome from content.

## Extraction parity vs 5da328f3 WorkbenchStepMap

Pre-extraction (`git show 5da328f3a:apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx` L79–145): labelled nav only; never dereferenced `findIndex`; no position line; Review is a span; Scan/Confirm buttons.

Restored by this lane: nav-only name (RV-02); miss path no longer throws (RV-01; old map was already non-throwing because it never read `steps[-1]`).

Intentional D-7 extras still present (not silent regressions of these findings):
- Happy-path `role="status"` “Step N of M: Label” (NAV-09 / A11Y-21) — pre-extraction had none.
- Always-visible Remaining/Current/Completed text; completed marker is ✓ instead of the step number; `--remaining` class. Pre-extraction used numbered markers always, SR-only Completed, and no Remaining chip.
- Generic `steps[]` + optional `onSelect`. Wrapper `WorkbenchStepMap` still wires Scan/Confirm `onSelect` and Review as informational — reachability parity held.

No other throw or white-screen behaviour change found. WorkbenchPage “exposes an accessible name on the step list” already queried the nav; still passes.

## Residual risk

- Miss path omits the status region rather than leaving a stable empty live region. Workbench wrapper always passes the full 3-step list with a matching `activeStep`, so hit→miss unmount of a populated region is not a current caller. Empty `steps=[]` shares the same guard; not a separate test.
- Handoff MCP and `workbay_handoff_mcp` Python API are unavailable in this worktree (`ModuleNotFoundError`); findings were not marked fixed in the handoff DB from this lane.
