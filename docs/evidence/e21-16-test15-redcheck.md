# E21-16 TEST-15 red-check
## Edit 1 — at-rest memo else-branch
- Change applied: `(labelMatches ?? atRestLabeledClusters?.clusters ?? [])` -> `(labelMatches ?? [])`
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestions.test.tsx -t "keeps the at-rest labelled page visible"`
- Verdict: FAILED
- Failing assertion: `expect(result.current.options.some((option) => option.label === 'Tory Guzman')).toBe(true);` expected true, received false
- After restore: PASSED
## Edit 2 — limit:null slice (same five fields)
- Change applied: `limit: isAtRestMode ? null : undefined` removed so `buildNamingOptions` uses its default slice of 20
- Command: `cd apps/prototype-wp-alt-context && ./node_modules/.bin/vitest run js/admin/pages/workbench/identity-clusters/__tests__/useClusterSuggestions.test.tsx -t "renders a labelled cluster at rest"`
- Verdict: FAILED
- Failing assertion: `expect(optionLabels).toEqual(expect.arrayContaining(labeledPage.map((cluster) => cluster.label)));` expected ArrayContaining of 25 labels (Tory Guzman + Labelled 0–23), received 20 labels (Tory Guzman + Labelled 0–18); `toHaveLength(25)` did not run
- After restore: PASSED
## Conclusion
Edit 1: yes — the visibility test pins the in-flight else-branch fallback; it failed after the at-rest page was dropped and passed after restore.
Edit 2: yes — the 25-row at-rest test pins the unsliced page; it failed after removing `limit: null` and passed after restore.
