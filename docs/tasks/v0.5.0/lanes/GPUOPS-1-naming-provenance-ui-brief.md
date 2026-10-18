# GPUOPS-1 lane L8 — show naming provenance in the apply view

Branch `feature/gpuops-1-naming-provenance-ui`, worktree `context-alt-text-monorepo-gpuops-1-naming-provenance-ui`. Owns `apps/prototype-wp-alt-context/js/admin/pages/DescribeRunApplyView.tsx`, `js/admin/api/describeApi.ts`, their tests, `src/api/class-describe-run*.php` only if pass-through strips `provenance.naming`, and a new `tests/Unit/DescribeRunProvenancePassthroughTest.php`.

## Goal

An operator reviewing a describe run can see which people were named in each draft and how (contract C7), so an unwanted or wrong name is caught before apply (HAI-05, HAI-08, PROV-06).

## Current anchors

- `js/admin/api/describeApi.ts` :218 `DescribeResultTier`, :319 item `provenance` / `tier` fields.
- `js/admin/pages/DescribeRunApplyView.tsx`: per-item card showing tier (`provisional_cpu | final_gpu`) and the draft; add the naming badge beside the tier badge.
- Frozen field shape from L7 (C7): `provenance.naming = {status: "applied"|"disabled"|"skipped_budget"|"no_faces", realizer: "grounded"|"positional_fallback"|null, names_applied: string[]}`. Older items may lack `naming` entirely; treat as unknown, not as `disabled`.
- PHP: the describe-run controller forwards items from the service; confirm `provenance` is forwarded untouched (rg-015) with a unit test against a fixture that contains `naming`.

## Deliverables

1. `describeApi.ts`: `NamingProvenanceStatus` and `NamingRealizer` as `as const` objects (sr-007), `NamingProvenance` type, item `provenance.naming?: NamingProvenance`. Parse defensively at the boundary (validate shape; no non-null assertions, sr-005).
2. `DescribeRunApplyView.tsx`: badge text `Names: A, B · positional` (or `· grounded`), `No names (disabled)`, `Names skipped (time budget)`, `No faces`; absent → no badge. Icon paired with colour (sr-004); `title`/`aria-label` explains the realizer in one sentence. Tokens only.
3. PHP pass-through test; fix the controller only if the test fails.

## Tests

`cd apps/prototype-wp-alt-context && npx vitest run js/admin/pages/__tests__/DescribeRunApplyView* js/admin/api/__tests__ && npx tsc --noEmit` and `vendor/bin/phpunit --filter DescribeRunProvenancePassthrough`. The ux-map parity tests are owned by L5; ignore them if red.

## Non-goals

Worker or realizer changes (L7), settings toggle (L6), Burst GPU card (L5).
