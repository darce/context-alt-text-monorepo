# E21-16 remote review — correctness and accessibility lens

Reviewed: `4444f753f6fd2e837511bd8e3f908421ad7e109a` against main

This sandbox is history-stripped (`main` is absent; `HEAD` is a single commit). Review is of the current identity-cluster tree at that SHA, not a `main...HEAD` patch.

## Verdict

pass_with_findings

## Findings

### 1. low — at-rest hint is both a live region and the combobox description

- File: `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterEditForm.tsx:207-209` (`aria-describedby`) and `:282-288` (`role="status"` + `aria-live="polite"` on the same node).
- What is wrong: one element is a polite live region and the input's `aria-describedby` target. The input also autofocuses on mount (`:112-115`). On open in at-rest truncated mode the hint text is therefore announced twice: once because the status region mounted, once because focus lands on the combobox and the description is read. A second `role="status"` already exists at `:299-301` (`N naming options`).
- Concrete input: open edit on a labelled cluster while `atRestTruncated && isAtRestMode` (empty / 1-character input, envelope truncated). Autofocus fires immediately.
- House style for the equivalent field-adjacent hint: `MediaAltSuggest.tsx:780-786` keeps the length advisory as a described-by `<p>` with neither `role="status"` nor `aria-live`; the live channel is a single existing status region. Tests pin that split (`MediaAltSuggest.test.tsx:1986-1990`). The roster truncation line (`NeedsAssignmentSection.tsx:179-186`) uses `role="status"` but is not an input description.
- Smallest fix: drop `role="status"` and `aria-live="polite"` from the hint `<p>`. Keep `id={atRestHintId}` and the describedby wiring. If the "type to search for more" cue must be live-announced, compose it into the existing result-count status at `:299` instead of adding a second live region.

## Checked and clean

1. Same `showAtRestTruncationHint` (`ClusterEditForm.tsx:130`) gates `aria-describedby` (`:207-209`) and the hint `<p>` (`:282`); they cannot disagree, and the later sibling is in the same commit.
2. Hint `%1$d` is `displayedOptions.length` (`:292`); the listbox maps that same array (`:215`). Idle path matches. `!isPending` at `:212` hides the listbox during Save while the hint still names the budgeted length — transient, not filed.
4. `React.useId()` is unconditional at the top of `ClusterEditForm` (`:131`). App + tests have no remaining literal `'acx-identity-cluster-at-rest-hint'` except this template prefix.
5. No caller passes `atRestShown`; no List/Item/Form type declares it (no `atRestShown=` in the tree). Loader/hook still return the field for tests only.
6. Loader `buildNamingOptions` (`useClusterSuggestionsLoader.ts:174-179`) omits `limit`. The overlay is the only rendered list and goes through `budgetOverlayOptions` (`ClusterEditForm.tsx:127,:215`). Save/match readers (`findPersonOptionLabel`, `resolveClusterMatchFromOptions`, `resolveMatchMemberCount`) are exact-match lookups; at-rest input is `< 2` chars so a sliced-off row is not a reachable typed match. `collisionsByLabel` is pre-slice. Not a user-visible regression.
