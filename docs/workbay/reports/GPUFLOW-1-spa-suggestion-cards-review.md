# GPUFLOW-1 spa-suggestion-cards review

Verdict: pass_with_findings

| base | tip | files |
| --- | --- | --- |
| `58b3bf034` | `b6802b19e` | `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/SuggestionCards.tsx`; `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/SuggestionCards.test.tsx`; `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/fixtures/gpuflow-candidate-preview.json` |

## Review basis

- The inlined delta changes exactly the three owned paths; no sibling-lane path is part of this review.
- `SuggestionCards` now uses the shared `isCroppableBbox` predicate before constructing either `FaceThumbnail`. Missing representative media still reaches the existing `REPRESENTATIVE_VOCABULARY.imageUnavailable` `Avatar` placeholder, preserving the null-as-absence contract (rg-015) and an explicit accessible name ([A11Y-02]).
- The added tests cover the null-representative branch and zero/negative/non-finite geometry. This is the correct local proof point for the UI behavior ([TEST-03]); the backend normal/replay exclusion remains covered by the upstream repository lane's fixture/test.
- The required repository gate passed. The declared Vitest command was attempted but is not runnable here because the worktree has no `node_modules` or local Vitest; no pass claim is based on that unavailable run.

## FINDINGS

### GPUFLOW-1-SPASUGGESTIONCARDS-R-01 — low

- **File:line:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/SuggestionCards.test.tsx:59,89-90`
- **Evidence:** The three new assertion lines are 126, 126, and 139 characters, while the owned app's `.prettierrc` sets `printWidth` to 120.
- **Impact:** The lane's formatting gate can reject an otherwise correct SPA test delta.
- **Fix:** Run Prettier on the touched test file, or wrap the assertions to the configured width.
