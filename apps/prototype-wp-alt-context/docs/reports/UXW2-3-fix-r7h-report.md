# UXW2-3-fix-r7h report

Close UXW2-3-R1-07: create-vs-bind no longer resolves against a prefix-filtered, truncated naming slice.

## Files / line ranges

| File | Range | Change |
|---|---|---|
| `js/admin/pages/workbench/identity-clusters/buildNamingOptions.ts` | 44–45 | `filter` JSDoc: prefix → substring |
| same | 121–163 | `matchesFilter` (includes) + stable exact/prefix/substring rank |
| same | 171–172 | `buildNamingOptions` JSDoc filter-before-slice line |
| same | 206, 232 | call `matchesFilter` |
| same | 259–260 | rank, then slice |
| `js/admin/pages/workbench/identity-clusters/NameFaceControl.tsx` | 154–158, 212 | optional `resolutionOptions` (default `options`) |
| same | 284–286, 297–299, 329–331, 360 | four resolution sites use `resolutionOptions` |
| `js/admin/pages/workbench/identity-clusters/ClusterLabelingPanel.tsx` | 247–267 | unfiltered `limit: null` resolution memo |
| same | 667–668 | pass `resolutionOptions` |
| `js/admin/pages/workbench/identity-clusters/__tests__/buildNamingOptions.test.ts` | 193–226 | tests 1–2 |
| `js/admin/pages/workbench/identity-clusters/__tests__/ClusterLabelingPanel.test.tsx` | 8, 1484–1538 | tests 3–5 |

`PersonCommitControl` unchanged. It still passes only `options` built with `labelMatches: []` and `limit: null`; the new prop defaults to `options`.

Displayed combobox + `"%d naming options"` still use `options` / `matchTotal`. Resolution set is not announced.

UX maps not edited. No new screen/zone/state/primary action. Bind-vs-create is resolution of the existing NameFaceControl surface (`workbench-2pane` `z-name-curate` already lists loading/empty/error/suggestions-open/ambiguous).

## Tests added

| File | `it(...)` |
|---|---|
| `identity-clusters/__tests__/buildNamingOptions.test.ts` | `returns a mid-label substring match for filter carter (UXW2-3-R1-07)` |
| same | `ranks exact, then prefix, then substring matches without alphabetical sort (UXW2-3-R1-07)` |
| `identity-clusters/__tests__/ClusterLabelingPanel.test.tsx` | `type Carter + Enter binds Alex Carter by roster id (UXW2-3-R1-07)` |
| same | `type + Enter binds a roster person past the naming-options limit (UXW2-3-R1-07)` |
| same | `naming-options announcement counts the displayed list not the resolution set (UXW2-3-R1-07)` |

Test 3 types `Carter`, asserts the Alex Carter overlay row, ArrowDown, Enter, then `commitClusterToRosterEntry({ clusterId, rosterEntryId: 42 })` and `updateClusterLabel` not called. ArrowDown is required because `resolveNameFaceInput` is still exact-fold match: Enter on the typed fragment `Carter` creates, even when `Alex Carter` is in the list.

## TEST-15 mutants

Mutants applied one at a time, then reverted. Filter: `-t "UXW2-3-R1-07"`.

### M1 — `matchesFilter` back to `startsWith`

RED test 1 and test 3.

Test 1 first assertion:

```
AssertionError: expected [] to deeply equal [ 'Alex Carter' ]
```

at `buildNamingOptions.test.ts:202` `expect(options.map((option) => option.label)).toEqual(['Alex Carter'])`.

Test 3 first assertion:

```
TestingLibraryElementError: Unable to find role="option" and name `/Confirm match with Alex Carter/i`
```

at `ClusterLabelingPanel.test.tsx:1491` `expect(await screen.findByRole('option', { name: /Confirm match with Alex Carter/i }))`.

Ranking test also RED (`expected [ 'Carter', 'Carter Zhao' ]` missing `Alex Carter`); not required.

### M2 — `commitValue` uses `options` instead of `resolutionOptions`

GREEN on tests 3 and 4. Honest non-closure.

`commitValue` is exact-fold. Displayed `options` are filter-before-slice of the current input.

- Test 3 confirms the overlay row (`confirmDisplayedOption`), not `commitValue`. M2 does not run.
- Test 4 types the unique full name `Person 21`. Filter-before-slice puts that row in displayed `options`, so `commitValue(options, "Person 21")` still binds.

A unique exact label always ranks into the displayed 20. Cannot drop it from `options` while keeping it in `resolutionOptions` without dropping `filter: labelInput` on the displayed memo (forbidden: displayed stays filtered + limited).

### M3 — resolution memo `limit: null` → `limit: NAMING_OPTIONS_LIMIT`

RED test 4.

```
AssertionError: expected "vi.fn()" to be called with arguments: [ { …(2) } ]

Number of calls: 0
```

at `ClusterLabelingPanel.test.tsx:1512` `expect(commitClusterToRosterEntry).toHaveBeenCalledWith({ clusterId: 'source-cluster-id', rosterEntryId: target.id })`.

Unfiltered resolution truncated past `Person 21` → create path → duplicate guard. Bind not called.

## Gates

### `cd apps/prototype-wp-alt-context && npx vitest run`

```
 Test Files  211 passed (211)
      Tests  2458 passed (2458)
   Start at  14:29:41
   Duration  329.41s (transform 13.44s, setup 44.77s, import 38.22s, tests 105.20s, environment 102.75s)
```

0 failed.

### `cd apps/prototype-wp-alt-context && npm run typecheck`

```
> prototype-wp-alt-context@0.0.4 typecheck
> tsc --noEmit --project tsconfig.type-check.json
```

exit 0.

## Open, not fixed

- Enter on a unique substring overlay row without ArrowDown still creates (`resolveNameFaceInput` exact-fold; BR-35). Substring filter only makes the row visible.
- M2 cannot be made RED without changing displayed filter-before-slice (see above).
- Panel labeled-cluster query still `search`s the typed string with `limit: 20`; out of scope. Roster resolution uses the full `useRosterEntries` list.
