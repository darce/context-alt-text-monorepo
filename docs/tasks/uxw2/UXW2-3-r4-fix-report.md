# UXW2-3-r4 fix report

Commits by subject. ClusterActions copy not reverted.

## Items

| Item | Finding | Commit subject | Tests | TEST-15 mutant RED | After |
| --- | --- | --- | --- | --- | --- |
| 1 | UXW2-3-R4-01 | `fix(fe): UXW2-3-R4-01 retarget IdentityClusterList queries to group copy` | `allows unlinking an identity (wrong person) only for singletons`; `allows splitting a cluster`; `issues exactly one batched suggestions fetch at projection depth for N unlabeled cards`; `resolves an inline prompt on every one of 60 unlabeled cards from a single batch`; `renders nothing for an identity absent from the keyed envelope (empty-match)`; `keeps backend-fallback clusters labelable while hiding local-only corrective actions` | See mutants below | IdentityClusterList 24/24. ClusterActions copy still `Remove from group` / `Split group`. |
| 2 | UXW2-3-R4-02 | `fix(fe): UXW2-3-R4-02 pass string literals into __() at eight sites` | `does not pass CONST identifiers into __() across identity-clusters` | See mutant below | gettext-literals 3/3. Guard (`GETTEXT_NON_LITERAL`, `collectTsFiles`) untouched. |

### Item 1 mutants (ClusterActions labels reverted to old copy)

Positive repaired queries (`getByText('Remove from group')`, `getByRole(..., /split group/i)`):

```
TestingLibraryElementError: Unable to find an element with the text: Remove from group, which matches selector 'button'. This could be because the text is broken up by multiple elements. In this case, you can provide a function for your text matcher to make your matcher more flexible.
```

```
TestingLibraryElementError: Unable to find an accessible element with the role "button" and name `/split group/i`
```

Same mutant against the real waitFor tests (`--testTimeout=2500`):

```
Error: Test timed out in 2500ms.
If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".
 ❯ js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx:975:3
```

```
Error: Test timed out in 2500ms.
If this is a long-running test, pass a timeout value as the last argument or configure it globally with "testTimeout".
 ❯ js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx:1027:3
```

Negative repaired assertions (forced `canReject`/`canSplit` buttons visible, new copy kept):

```
Error: expect(element).not.toBeInTheDocument()

expected document not to contain element, found <button
  class="acx-identity-cluster__action"
  type="button"
>
  Remove from group
</button> instead
```

```
Error: expect(element).not.toBeInTheDocument()

expected document not to contain element, found <button
  class="acx-identity-cluster__action"
  type="button"
>
  Split group
</button> instead
```

Mutants reverted. ClusterActions not in any r4 commit.

### Item 2 mutant (`queryRetry.tsx:61` re-wrapped `__(QUERY_RETRY_COPY.RETRY, ...)`)

```
AssertionError: expected [ Array(1) ] to deeply equal []

- Expected
+ Received

- []
+ [
+   "queryRetry.tsx:61 QUERY_RETRY_COPY.RETRY",
+ ]
```

Mutant reverted.

Pre-fix baseline (same test, 8 offenders):

```
AssertionError: expected [ …(8) ] to deeply equal []

- Expected
+ Received

- []
+ [
+   "ReviewQueue.tsx:888 QUERY_RETRY_COPY.RETRY_FAILED_SUGGESTIONS",
+   "ReviewQueue.tsx:889 QUERY_RETRY_COPY.LOAD_FAILED_SUGGESTIONS",
+   "ReviewQueue.tsx:897 QUERY_RETRY_COPY.RETRYING_SUGGESTIONS",
+   "ReviewQueue.tsx:1556 holdMessage",
+   "WorkbenchFindingsPanel.tsx:138 QUERY_RETRY_COPY.RETRYING_FINDINGS",
+   "WorkbenchFindingsPanel.tsx:319 QUERY_RETRY_COPY.RETRY_FAILED_FINDINGS",
+   "WorkbenchFindingsPanel.tsx:320 QUERY_RETRY_COPY.LOAD_FAILED_FINDINGS",
+   "queryRetry.tsx:61 QUERY_RETRY_COPY.RETRY",
+ ]
```

## Gate

Run on this tree after both code commits:

```
cd apps/prototype-wp-alt-context
npx vitest run
```

```
 Test Files  211 passed (211)
      Tests  2420 passed (2420)
```

```
npm run typecheck
```

`tsc --noEmit --project tsconfig.type-check.json` — exit 0, no diagnostics.

```
composer test
```

```
OK (1765 tests, 8518 assertions)
```

## Undone

- No UX-map edit: no operator-facing copy or zone change (test queries + `__()` lift only).
- No contract edit (`docs/workbay/contracts/` gitignored here).
- Handoff MCP tools unavailable; `workbay_handoff_mcp` Python import failed (`ModuleNotFoundError`). No handoff write.

