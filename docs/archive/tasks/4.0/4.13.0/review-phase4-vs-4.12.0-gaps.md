# Phase 4 vs 4.12.0 Branch Audit — Gap Analysis

> **Date:** 2026-02-09
> **Scope:** Confirm Phase 4 of `web-deployment-cleanup-plan.md` meets the requirements in `branch-audit-findings.md` (4.12.0). Flag untracked gaps.

---

## Phase 4 Verdict: **PASS**

All Phase 4 items are marked complete. The two 4.12.0 findings in WP plugin scope that are specifically test debt have been independently verified as resolved:

| 4.12.0 ID | Finding | Current State |
|---|---|---|
| M-24 | Minimal `ClusterReviewPanel` test coverage (2 tests) | **Resolved** — `ClusterReviewPanel.test.tsx` now has 6 tests (removes member, cropped face fallback, loading state, error state, cancel confirmation, close button). |
| L-19 | Test `QueryClient` uses `retry: 1` instead of `retry: false` | **Resolved** — both `ClusterReviewPanel.test.tsx:44` and `SuggestionReviewPanel.test.tsx:49` use `retry: false`. |

The cleanup plan's own Phase 4 items (`AFS-L2`, `HK-L2`, `RAP-L3`, `PAG-M3`, `PAG-L2`, plus `it.todo`/`test.todo` closures) are all checked off and were verified in `review-7661327-verification.md`.

---

## Cross-Audit: 4.12.0 Findings in WP Plugin Scope

Full reconciliation of all 4.12.0 findings that touch `apps/prototype-wp-alt-context` files, regardless of phase.

### Already Tracked in Cleanup Plan

| 4.12.0 ID | Severity | Cleanup Plan Reference | Status |
|---|---|---|---|
| H-8 | HIGH | Seeded finding; resolved by file deletion | **Resolved** |
| M-14 | MEDIUM | Carry-Forward `4.12-M14` | **Verify** (grep shows no `!` assertions) |
| M-15 | MEDIUM | Carry-Forward `4.12-M15` | **Resolved** |
| M-20 | MEDIUM | Phase 2 (checked off) | **Resolved** — `sanitize_key()` applied |
| M-21 | MEDIUM | Phase 2 (checked off) | **Resolved** — redundant `tenant_id` removed |

### Resolved Without Tracking (Cleanup Side-Effects)

These were never explicitly tracked in the cleanup plan but were resolved by related cleanup work (file deletions, component rewrites, or incidental fixes).

| 4.12.0 ID | Severity | Finding | Resolution |
|---|---|---|---|
| M-16 | MEDIUM | Ad-hoc query keys outside `queryKeys` factory in `ClusterLabelingPanel.tsx`, `ClusterReviewPanel.tsx` | **Resolved** — both files now import from centralized `queryKeys`. |
| M-17 | MEDIUM | Duplicate face-crop math in `TopClustersSection.tsx` | **Resolved** — delegates to `<FaceThumbnail>` component; no duplicate crop style math remains. |
| M-18 | MEDIUM | Sequential mutation loop for bulk accept in `SuggestionReviewPanel.tsx` | **Resolved** — uses `Promise.all(suggestions.map(...mutateAsync...))`. |
| M-19 | MEDIUM | `!important` overrides in `_workbench.scss` | **Resolved** — no `!important` usage found in current file. |
| M-24 | MEDIUM | Minimal `ClusterReviewPanel` test coverage | **Resolved** — 6 test cases now. |
| L-6 | LOW | `wp.i18n` runtime check is ineffective in `main.tsx` | **Resolved** — i18n-specific global check removed. |
| L-7 | LOW | Duplicate `import type { DebugMetrics }` in `types/cluster.ts` | **Resolved** — single import only. |
| L-11 | LOW | `useClusterEvents` type assertion on `event.data` | **Resolved** — `useClusterEvents.ts` deleted. |
| L-12 | LOW | Overlapping event-type lists in `useClusterEvents` | **Resolved** — `useClusterEvents.ts` deleted. |
| L-14 | LOW | Inline styles in `SuggestionReviewPanel.tsx` / `TopClustersSection.tsx` | **Resolved** — no inline `style={}` props remain. |
| L-17 | LOW | SSE endpoint is a heartbeat-only stub | **Resolved** — `stream_cluster_events` route removed. |
| L-19 | LOW | Test `QueryClient` uses `retry: 1` | **Resolved** — both test files use `retry: false`. |

### Untracked — Still Open

These 4.12.0 findings are in WP plugin scope, still present in the codebase, and **not tracked** anywhere in the cleanup plan.

| 4.12.0 ID | Severity | Category | Finding | Evidence | Recommended Phase |
|---|---|---|---|---|---|
| L-13 | LOW | ANTIPATTERN | `window.confirm()` used for destructive member-removal action. Not styleable, not accessible. Should use a dialog component. | `js/admin/pages/workbench/identity-clusters/ClusterReviewPanel.tsx:44` — `window.confirm(__(…))` | Phase 3 (low-risk antipattern) |
| L-15 | LOW | COMPLEXITY | Magic hex colors in SCSS without design tokens: `#fef2f2`, `#fecaca`, `#991b1b` hardcoded instead of CSS custom properties. | `js/admin/styles/components/_cluster-panels.scss:50-53` | Phase 3 (style token consistency — pairs with `CF-L1`) |
| L-16 | LOW | COMPLEXITY | Magic number `top: 46px` for sticky positioning. Should be a CSS custom property documenting the 32px admin-bar + 14px breathing room. | `js/admin/styles/components/_workbench.scss:401` | Phase 3 (low-risk cleanup) |

---

## Recommended Action

1. **Phase 4:** No gaps. All test-debt items from both the cleanup plan and 4.12.0 audit are satisfied.
2. **L-13, L-15, L-16:** Add to Phase 3 in the cleanup plan (or Carry-Forward) for tracking. All are LOW severity and non-blocking for deployment.
