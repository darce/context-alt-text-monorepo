lane dux-w2f-a
STATUS: DONE

## EDIT 4 mutant

First mutant (EDIT 2c regex still baked into the test; suite stayed green):

```
 RUN  v4.1.11 /home/gate/grok-sandbox/fix-dux-w2f-a-61cad1a7

 ✓ apps/prototype-wp-alt-context/js/admin/__tests__/dashboard-uxmap-code-parity.test.ts (8 tests) 18ms

 Test Files  1 passed (1)
      Tests  8 passed (8)
   Start at  03:36:35
   Duration  276ms (transform 73ms, setup 0ms, import 96ms, tests 18ms, environment 0ms)
```

Assertion compared dashboard.md to a literal inside the test, not to DashboardRecentActivitySection.tsx. Fixed RV-04 to extract the UNAVAILABLE EmptyState i18n heading from the component and assert the error sketch contains that heading.

Mutant after the fix (suite red):

```
 ❯ apps/prototype-wp-alt-context/js/admin/__tests__/dashboard-uxmap-code-parity.test.ts:236:25
    234|     expect(unavailableHeadingMatch, 'expected an i18n heading on the U…
    235|     const unavailableHeading = (unavailableHeadingMatch?.[1] ?? '').re…
    236|     expect(errorSketch).toContain(unavailableHeading);
       |                         ^
    237|
    238|     expect(dashboardSrc).toMatch(/acx-dashboard__hero/);

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[1/1]⎯


 Test Files  1 failed (1)
      Tests  1 failed | 7 passed (8)
   Start at  03:37:20
   Duration  304ms (transform 69ms, setup 0ms, import 93ms, tests 42ms, environment 0ms)
```

Component reverted after both mutant runs.

## Final gate

```
 ✓ apps/prototype-wp-alt-context/js/admin/__tests__/dashboard-uxmap-code-parity.test.ts (8 tests) 19ms
 ✓ apps/prototype-wp-alt-context/js/admin/__tests__/uxmap-render-parity.test.ts (11 tests) 24ms

 Test Files  2 passed (2)
      Tests  19 passed (19)
   Start at  03:37:29
   Duration  571ms (transform 168ms, setup 0ms, import 209ms, tests 42ms, environment 0ms)
```
