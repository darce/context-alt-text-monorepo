# E21-16 TEST-15 red-check
## Edit 1 — at-rest memo else-branch
- Change applied: `(labelMatches ?? atRestLabeledClusters?.clusters ?? [])` -> `(labelMatches ?? [])`
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestions.test.tsx -t "keeps the at-rest labelled page visible"`
- Verdict: FAILED
- Failing assertion: `expect(result.current.options.some((option) => option.label === 'Flaxen Yarrow')).toBe(true);` expected true, received false
- After restore: PASSED
## Edit 2 — limit:null slice (same five fields)
- Change applied: `limit: isAtRestMode ? null : undefined` removed so `buildNamingOptions` uses its default slice of 20
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestions.test.tsx -t "renders a labelled cluster at rest"`
- Verdict: FAILED
- Failing assertion: `expect(optionLabels).toEqual(expect.arrayContaining(labeledPage.map((cluster) => cluster.label)));` expected ArrayContaining of 25 labels (Flaxen Yarrow + Labelled 0–23), received 20 labels (Flaxen Yarrow + Labelled 0–18); `toHaveLength(25)` did not run
- After restore: PASSED
## Conclusion
Edit 1: yes — the visibility test pins the in-flight else-branch fallback; it failed after the at-rest page was dropped and passed after restore.
Edit 2: yes — the 25-row at-rest test pins the unsliced page; it failed after removing `limit: null` and passed after restore.

## Coverage additions (REV1-04, REV1-05)
### Test 1 — one-character gate
- Mutation applied: `const isAtRestMode = debouncedValue.length < ACX_LABEL_SEARCH_MIN_CHARS;` -> `const isAtRestMode = debouncedValue.length < 1;`
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestions.test.tsx -t "treats a one-character query as at-rest and does not search"`
- Verdict: FAILED
- Failing assertion: `expect(result.current.isAtRestMode).toBe(true);`
- After restore: PASSED
### Test 2 — at-rest select filter
- Mutation applied: `clusters: response.clusters.filter((cluster) => cluster.id !== editableClusterId),` -> `clusters: response.clusters,` in the at-rest query `select`
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestions.test.tsx -t "drops the editable cluster from atRestShown while preserving envelope total"`
- Verdict: FAILED
- Failing assertion: `await waitFor(() => expect(result.current.atRestShown).toBe(atRestPage.length - 1));`
- After restore: PASSED
### Test 3 — row past the at-rest page
- Mutation applied: dropped `truncated: response.truncated,` from the at-rest query `select` (smaller edit than raising `AT_REST_LABELED_LIMIT`)
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestions.test.tsx -t "keeps a labelled cluster past the at-rest page unreachable until the operator types"`
- Verdict: FAILED
- Failing assertion: `await waitFor(() => expect(result.current.atRestTruncated).toBe(true));`
- After restore: PASSED

## ORCH-10 — hint counts the rendered rows
- Mutation applied: `displayedOptions.length` -> `49`
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/pages/workbench/identity-clusters/__tests__/ClusterEditForm.test.tsx -t "pins the at-rest hint first number to the rendered overlay row count"`
- Verdict: FAILED
- Failing assertion: `expect(screen.getByText(\`Showing ${renderedOptionRows.length} of 80 labels — type to search for more\`)).toBeInTheDocument();` — Unable to find an element with the text: Showing 5 of 80 labels — type to search for more.
- After restore: PASSED

## ORCH-13 — hint id is per instance
- Mutation applied: `` `acx-identity-cluster-at-rest-hint-${React.useId()}` `` -> `'acx-identity-cluster-at-rest-hint'`
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/pages/workbench/identity-clusters/__tests__/ClusterEditForm.test.tsx -t "scopes the at-rest hint id per form instance"`
- Verdict: FAILED
- Failing assertion: `AssertionError: expected 'acx-identity-cluster-at-rest-hint' not to be 'acx-identity-cluster-at-rest-hint' // Object.is equality`
- After restore: PASSED

## ORCH-11 — at-rest options stay capped
- Mutation applied: `limit` omitted (default NAMING_OPTIONS_LIMIT) -> `limit: isAtRestMode ? null : undefined,`
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestionsLoader.test.tsx`
- Verdict: FAILED
- Failing assertion: `AssertionError: expected [ { …(4) }, { …(4) }, { …(4) }, …(37) ] to have a length of 20 but got 40`
- After restore: PASSED

## REV2-01 — the item actually wires the at-rest props
- Mutation applied: IdentityClusterItem.tsx ClusterEditForm pass-through `atRestTotal={atRestTotal}` / `atRestTruncated={atRestTruncated}` / `isAtRestMode={isAtRestMode}` -> those three lines deleted
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterItem.test.tsx js/admin/pages/workbench/identity-clusters/__tests__/ClusterEditForm.test.tsx`
- Verdict: FAILED
- Failing assertion: `const hint = screen.getByText(/Showing \d+ of 80 labels/);` — Unable to find an element with the text: /Showing \d+ of 80 labels/.
- After restore: PASSED

## REV2-02 — hint is a description, not a second live region
- Assertions touched: none

## REV3-01 — atRestShown removed
- Files touched: apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useClusterSuggestionsLoader.ts, apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useClusterSuggestions.ts, apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx, apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestions.test.tsx, apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestionsLoader.test.tsx, docs/evidence/e21-16-test15-redcheck.md
- Assertions deleted: `expect(result.current.atRestShown).toBe(40)` (useClusterSuggestionsLoader.test.tsx); `expect(result.current.atRestShown).toBe(50)` and `expect(result.current.atRestTotal).not.toBe(result.current.atRestShown)` (useClusterSuggestions.test.tsx envelope test); `expect(result.current.atRestShown).toBe(atRestPage.length - 1)` (useClusterSuggestions.test.tsx self-exclusion test; title no longer names atRestShown)
- tsc --noEmit: EXIT 0
- vitest identity-clusters + IdentityClusterList: EXIT 0, 41/621

## REV3-02 — editable-cluster exclusion is pinned on the output
- Fixture change: none needed — at-rest page already includes `id: 'cluster-self'` (`editableClusterId`) with distinctive label `Flaxen Yarrow`
- MUT-A (select filter deleted): PASSED — expected: `buildNamingOptions({ excludeClusterId })` still drops the editable cluster from hook output
- MUT-B (both layers deleted): FAILED
- Failing assertion: `expect(result.current.options.some((option) => option.label === 'Flaxen Yarrow')).toBe(false);`
- After restore: PASSED
