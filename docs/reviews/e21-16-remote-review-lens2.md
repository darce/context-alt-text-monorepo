# E21-16 remote review — test falsifiability lens

Reviewed: `46d0d7c408dc47909f3fc7e4c722ddd07ef7453c` against main

This sandbox is history-stripped (`main` is absent; `HEAD` is a single commit). Review is of the current identity-cluster tests + `docs/evidence/e21-16-test15-redcheck.md` at that SHA. The evidence file has eight mutation blocks, not four.

## Verdict

pass_with_findings

## Findings

### 1. medium — hook-to-form at-rest props are untested at the only production call site

- File: `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/IdentityClusterItem.tsx:368-370`
- What is wrong: `ClusterEditForm` hint tests inject `atRestTotal` / `atRestTruncated` / `isAtRestMode` as props. The only production pass-through is these three JSX lines. No test in `identity-clusters/__tests__` renders `IdentityClusterItem` (or the list) and asserts the hint.
- Mutation that still ships green: delete the three props. Form defaults (`ClusterEditForm.tsx:104-106`) are `atRestTotal=0`, `atRestTruncated=false`, `isAtRestMode=false`, so `showAtRestTruncationHint` stays false. Hook tests still pass; form tests still pass.
- Smallest assertion: open edit on a labelled cluster while the hook returns `atRestTruncated && isAtRestMode` and `atRestTotal=80`; expect `Showing ${n} of 80 labels — type to search for more` in that item.

## Checked and clean

1. All eight recorded reds are plausible for the named mutation. Edit 1 (`useClusterSuggestions.test.tsx:1025`) is the in-flight else-branch. Edit 2 matches the *old* 25-row pin, not the current `NAMING_OPTIONS_LIMIT` pin — historical, not fabricated. Coverage Test 1 fails at `:1077` (empty-input `:1066` would still pass under `< 1`). Test 2 (`:1126`) matches the select-filter drop. Test 3’s recorded fail is `atRestTruncated` (`:1168`), which the `truncated` drop would break; it does not uniquely prove the Zenobia-unreachable claim (`:1169` stays green if Zenobia is merely past the 20-option slice). ORCH-10 (`ClusterEditForm.test.tsx:340`, 5 vs 49), ORCH-13 (`:375`, duplicate static id), and ORCH-11 (loader `:84`, 40 vs 20) all match.
2. No tautology found. `atRestPage.length - 1` (`useClusterSuggestions.test.tsx:1126`) is fixture-derived expected vs hook output. Hint interpolation (`ClusterEditForm.test.tsx:339-340`) compares two independent DOM queries. `namingOptions.length !== 40` (`useClusterSuggestionsLoader.test.tsx:85`) is weaker than `:84` but still compares production output to fixture size.
3. New tests mock `recognition` + `useRosterEntries` only. `buildNamingOptions` / loader / form are real. Not theatre.
4. Old `toHaveLength(25)` pinned fixture cardinality (Tory + 24), a proxy for `limit: null`. After ORCH-11 the contract is the builder default; retargeting to `NAMING_OPTIONS_LIMIT` (`useClusterSuggestions.test.tsx:814-816`) is that contract, not a cheat to hide a slice.
5. Loader test drives at-rest: `labelInput: ''`, `debounceMs: 0` (`useClusterSuggestionsLoader.test.tsx:76-77`) so `debouncedValue` is the empty input (`useClusterSuggestionsLoader.ts:87-88`); `:83` pins `isAtRestMode`; `:82` `atRestShown===40` cannot come from the disabled search query. Length 20 is the builder slice, not a different route.
6. Highest-value miss is Finding 1 (item wiring). Next-best: Test 3’s mock ignores `params.limit`, so it does not uniquely pin `AT_REST_LABELED_LIMIT`; the one-character test’s hardcoded `limit: 50` (`useClusterSuggestions.test.tsx:1078-1082`) is the actual lock.
