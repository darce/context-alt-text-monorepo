# Phase 5 Post-Cleanup Findings Delta (v4.13.0)

> **Date:** 2026-02-10  
> **Scope:** `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context`  
> **Source of baseline findings:** `web-deployment-cleanup-plan.md` seeded findings + addenda + carry-forward table

---

## Gate Re-Run Results (Phase 5)

All baseline gates were re-run from `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context`.

| Check | Result |
| --- | --- |
| `npm run typecheck` | pass |
| `npm run lint` | pass |
| `npm run arch` | pass (`98` files checked, no violations) |
| `npm run test -- --run` | pass (`30` files, `153` tests passed) |
| `composer test` | pass (`46` tests, `121` assertions) |
| `npx tsc --noEmit --project tsconfig.type-check.json --noUnusedLocals --noUnusedParameters` | pass |
| `composer cs-check` | pass (`0` exit) |

---

## Findings Reclassification Summary

- Baseline tracked findings: `46`
- Resolved findings: `38`
- Open findings: `8`

### Severity Delta

| Severity | Baseline Count | Post-Cleanup Open Count | Delta |
| --- | --- | --- | --- |
| HIGH | 2 | 1 | -1 |
| MEDIUM | 26 | 2 | -24 |
| LOW | 18 | 5 | -13 |
| Total | 46 | 8 | -38 |

### Category Delta

| Category | Baseline Count | Post-Cleanup Open Count | Delta |
| --- | --- | --- | --- |
| DEAD_CODE | 18 | 0 | -18 |
| GAP | 17 | 3 | -14 |
| ANTIPATTERN | 8 | 2 | -6 |
| COMPLEXITY | 3 | 3 | 0 |
| Total | 46 | 8 | -38 |

---

## Open Findings (Post-Phase 5)

| ID | Severity | Category | Status | Notes |
| --- | --- | --- | --- | --- |
| `A-H1` | HIGH | GAP | Open | Admin SPA bootstrap still fails silently when manifest/build assets are missing; no explicit admin notice/log path. |
| `A-M2` | MEDIUM | GAP | Open | Admin asset/menu wiring regression coverage is still limited in `tests/Unit/AdminTest.php`. |
| `AFS-M4` | MEDIUM | COMPLEXITY | Open | `RecognitionController` monolith remains; tracked for decomposition in Phase 6 plan. |
| `4.12-L13` | LOW | ANTIPATTERN | Open | `window.confirm()` still used in cluster member removal flow. |
| `4.12-L15` | LOW | COMPLEXITY | Open | Magic hex colors remain in `_cluster-panels.scss`. |
| `4.12-L16` | LOW | COMPLEXITY | Open | Magic `top: 46px` remains in `_workbench.scss`. |
| `CF-L1` | LOW | ANTIPATTERN | Open | Divergent `--acx-color-danger` fallback hex values remain across SCSS files. |
| `CF-L2` | LOW | GAP | Open | Unstructured `TODO: Restore tier-based limits post-MVP` remains in `trait-batch-limits.php`. |

---

## Verification Update

`4.12-M14` (non-null assertions in `SuggestionReviewPanel.tsx`) moved from `Verify` -> `Resolved` after targeted grep validation found no postfix non-null assertions in the component.
