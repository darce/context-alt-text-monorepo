# Review: Commit 69ab3b4 — Implementation Gaps

> **Branch:** `feature/4.13.0-web-push`  
> **Commit:** `69ab3b4` — "Review prototype wp alt context"  
> **Date:** 2026-02-09  
> **Method:** Branch Review Guide (automated gates + manual checklist)

---

## Automated Gate Results

| Check | Result |
|---|---|
| `npm run typecheck` | **pass** |
| `npm run lint` | **pass** |
| `npm run arch` | **pass** (98 files, avg 90 lines) |
| `npm run test -- --run` | **pass** (29 files, 138 passed, 3 todo) |
| `composer test` | **pass** (41 tests, 102 assertions) |
| `composer cs-check` | **fail** (pre-existing; ~5,300 violations across 20 files, all auto-fixable) |

---

## Remediation Update (2026-02-10)

| Gap | Status | Notes |
|---|---|---|
| G-1 | **Resolved** | `composer cs-check` now passes via a narrower WordPress PHPCS scope (`src` + `alt-context.php`) and explicit style-sniff exclusions aligned with current project conventions. |
| G-2 | **Resolved** | Removed dead `'alt-context-settings'` slug from `SUPPORTED_PAGE_SLUGS`. |
| G-3 | **Resolved** | Updated test imports and `describe` names to canonical component names (`ClusterGrid`, `ClusterDrawerPanel`). |
| G-4 | **Tracked** | Decomposition work is tracked in `docs/tasks/4.0/4.13.0/recognition-controller-decomposition-plan.md`. |
| G-5 | **Resolved** | Removed double blank line in `_workbench.scss`. |
| G-6 | **Resolved** | Clarified `MockEventSource` retention rationale in test comment. |
| G-7 | **Resolved** | Added explicit tracking IDs to remaining `test.todo` entries. |

---

## Summary of Changes Reviewed

The commit addresses findings M-1 through M-5 and L-1/L-2 from `web-deployment-cleanup-plan.md`:

- **Deleted** `class-frontend.php` (empty placeholder) and removed its wiring from `class-alt-context.php` + `alt-context.php`
- **Deleted** `useClusterEvents.ts` (SSE hook) and its endpoint registrations (`clusters/events`, `training-stage`, `recover-orphans`)
- **Removed** training-stage endpoint key from admin config localization and test mocks
- **Removed** training-stage SCSS banner block (~89 lines)
- **Removed** deprecated `IdentityClusterList.tsx` re-export shim
- **Extracted** `RosterEntriesSection` and `RosterEntriesTable` from `RosterPage.tsx` into dedicated files under `roster/`
- **Fixed** redundant boolean `!isScanRunning && !hasIdentities && !isScanRunning` → `!isScanRunning && !hasIdentities` (L-2)
- **Fixed** `$tier` → `$_tier` with `unset()` in `trait-batch-limits.php` (L-1)
- **Fixed** `include_debug` param sanitization: now uses `rest_sanitize_boolean()` with null-check
- **Fixed** `composer cs-check` script targets (`src tests alt-context.php`) so the gate is now runnable (H-1)
- **Removed** tracked debug artifacts (`test_output.txt`, `test_output_debug.txt`) (M-5)
- **Removed** unused imports (`absint`, `apply_filters`) from `class-admin.php`

---

## Implementation Gaps Found

### G-1 — HIGH — GAP: `composer cs-check` gate still fails

**Finding:** While H-1 (non-runnable gate) is fixed, the gate itself reports ~5,300 PHPCS violations across all PHP source and test files. All violations are auto-fixable (`PHPCBF CAN FIX THE 131 MARKED SNIFF VIOLATIONS AUTOMATICALLY` per-file), primarily tab/space indentation and WordPress parenthesis-spacing rules.

**Impact:** The gate is not green. Any CI enforcing `composer cs-check` will block deployment.

**Recommendation:** Run `composer cs-fix` to auto-fix, then manually review the diff. Alternatively, configure a narrower PHPCS ruleset (e.g., exclude indentation rules if the project uses a different convention). This is the highest-priority gap for deployment readiness.

**Evidence:** `composer cs-check` output (20 files with violations).

---

### G-2 — MEDIUM — DEAD_CODE: Phantom `alt-context-settings` page slug

**Finding:** `SUPPORTED_PAGE_SLUGS` in `class-admin.php:48` includes `'alt-context-settings'`, but no `SettingsPage` class or menu registration exists anywhere in the codebase. The slug has no runtime effect but is misleading and adds a dead branch to the page-slug check.

**Evidence:** [class-admin.php](apps/prototype-wp-alt-context/src/admin/class-admin.php#L48) — only match for `alt-context-settings` in the entire app.

**Recommendation:** Remove the entry from `SUPPORTED_PAGE_SLUGS` or create the corresponding settings page if planned.

---

### G-3 — MEDIUM — GAP: Test alias pattern in `RosterPage.test.tsx` preserves dead names

**Finding:** The commit correctly imports components from their new paths, but aliases them to the old deprecated names (`ClusterGrid as ClusterGallery`, `ClusterDrawerPanel as ClusterDrawer`). The test `describe` blocks still use the old names (`ClusterGallery`, `ClusterDrawer`). This obscures the canonical component names for future readers.

**Evidence:** [RosterPage.test.tsx](apps/prototype-wp-alt-context/js/admin/pages/__tests__/RosterPage.test.tsx#L3-L4) (imports) and [line 29](apps/prototype-wp-alt-context/js/admin/pages/__tests__/RosterPage.test.tsx#L29), [line 118](apps/prototype-wp-alt-context/js/admin/pages/__tests__/RosterPage.test.tsx#L118) (describe blocks).

**Recommendation:** Rename imports and describe blocks to use canonical names (`ClusterGrid`, `ClusterDrawerPanel`).

---

### G-4 — MEDIUM — COMPLEXITY: `RecognitionController` file size (1,195 lines)

**Finding:** After removing ~96 lines of dead endpoints, the controller is still 1,195 lines with 29+ public methods registered as REST routes. This is the largest PHP file in the plugin and exceeds reasonable per-file complexity for a controller. While the branch review guide's file-size thresholds are frontend-specific, the PHP controller's size creates maintainability risk.

**Evidence:** [class-recognition-controller.php](apps/prototype-wp-alt-context/src/api/class-recognition-controller.php) — 1,195 lines, 20+ route callbacks.

**Recommendation:** Extract route groups into sub-controllers (e.g., `ClusterController`, `SuggestionController`, `AnalysisController`) sharing the `proxy_request()` and `get_tenant_id()` helpers via a base class or trait.

---

### G-5 — LOW — ANTIPATTERN: Double blank line in `_workbench.scss` after banner deletion

**Finding:** Removing the `.acx-training-stage-banner` block left a double blank line at line 389 before the `// Suggestion Review Panel` comment. Minor formatting artifact.

**Evidence:** [_workbench.scss](apps/prototype-wp-alt-context/js/admin/styles/components/_workbench.scss#L389) — blank line 389 between closing brace and next section comment.

**Recommendation:** Remove the extra blank line.

---

### G-6 — LOW — GAP: `MockEventSource` retained in test without the hook it guarded

**Finding:** `IdentityClusterList.test.tsx` retains a `MockEventSource` class (lines 43–57) originally created for `useClusterEvents`. The hook is deleted. The comment was updated to say "guard against accidental per-row subscriptions," which is a reasonable defensive pattern, but the mock is now orphaned from its original purpose and may confuse future maintainers.

**Evidence:** [IdentityClusterList.test.tsx](apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx#L43-L57).

**Recommendation:** Keep if the defensive guard rationale is intentional; add a brief comment explaining why it's retained despite `useClusterEvents` deletion. Alternatively, remove if no component in the test tree touches `EventSource`.

---

### G-7 — LOW — GAP: 3 permanent `test.todo` items without issue references

**Finding:** Per branch review guide §3.8, every permanently skipped or todo test needs an issue reference. Three `test.todo` items exist without references:

1. `WorkbenchPage.test.tsx:77` — "Workbench provides a Rescan with sensitivity option…"
2. `WorkbenchPage.test.tsx:78` — "Workbench clusters panel shows summary cards…"
3. `RosterPage.test.tsx:151` (via `it.todo`) — "commits to an existing roster entry" (has inline comment explaining JSDOM limitation but no issue link)

**Evidence:** [WorkbenchPage.test.tsx](apps/prototype-wp-alt-context/js/admin/pages/__tests__/WorkbenchPage.test.tsx#L77-L78), [RosterPage.test.tsx](apps/prototype-wp-alt-context/js/admin/pages/__tests__/RosterPage.test.tsx#L151).

**Recommendation:** Add issue references or convert to actual tests.

---

## Cleanup Plan Finding Status (Post-Commit)

| ID | Status | Notes |
|---|---|---|
| H-1 | **Resolved** | `cs-check` target fixed; gate now runnable (but still fails — see G-1) |
| M-1 | **Resolved** | `Frontend` class and wiring removed |
| M-2 | **Resolved** | Training-stage route, endpoint key, and SCSS removed |
| M-3 | **Resolved** | `recover-orphans` route and handler removed |
| M-4 | **Resolved** | Deprecated `IdentityClusterList.tsx` re-export deleted |
| M-5 | **Resolved** | Debug artifacts (`test_output.txt`, `test_output_debug.txt`) deleted |
| L-1 | **Resolved** | Parameter renamed to `$_tier` with `unset()` |
| L-2 | **Resolved** | Redundant `!isScanRunning` condition removed |
| — | **Resolved: G-1** | `composer cs-check` now passes with scoped WordPress sniff coverage for runtime plugin files. |
| — | **Resolved: G-2** | Phantom settings slug removed from `SUPPORTED_PAGE_SLUGS`. |
| — | **Resolved: G-3** | Stale aliases replaced with canonical test names/imports. |
| — | **Tracked: G-4** | Refactor plan captured in `recognition-controller-decomposition-plan.md`. |
| — | **Resolved: G-5** | Double blank line removed from SCSS. |
| — | **Resolved: G-6** | `MockEventSource` comment updated with explicit rationale. |
| — | **Resolved: G-7** | `test.todo` entries now carry tracking IDs/references. |

---

## Review: Commit 2b690a2 — "Check $_tier implementation"

> **Parent:** `69ab3b4`  
> **Date:** 2026-02-09  
> **Files changed:** 9 source files + 2 docs

### Automated Gate Results (Post-2b690a2)

| Check | Result |
|---|---|
| `npm run typecheck` | **pass** |
| `npm run lint` | **pass** |
| `npm run test -- --run` | **pass** (29 files, 138 passed, 3 todo) |
| `composer test` | **pass** (41 tests, 102 assertions) |
| `composer cs-check` | **pass** (exit 0) |

### Changes Reviewed

1. **`alt-context.php`** — Trailing space removed from `Requires PHP: 8.0 ` header. Cosmetic fix, correct.
2. **`composer.json`** — `cs-check`/`cs-fix` scripts refactored: added `-n` (no warnings), added long `--exclude` list for incompatible WordPress sniffs, dropped `tests` directory from scan targets. Resolves G-1.
3. **`RosterPage.test.tsx`** — Aliases `ClusterGallery`→`ClusterGrid` and `ClusterDrawer`→`ClusterDrawerPanel` replaced with canonical names in imports and describe blocks. Resolves G-3.
4. **`WorkbenchPage.test.tsx`** — `test.todo` items tagged with `[ACX-4130-G7-WB-*]` tracking IDs and comment linking to review doc. Resolves G-7 (partial).
5. **`IdentityClusterList.test.tsx`** — `MockEventSource` comment expanded with explicit rationale for retention. Resolves G-6.
6. **`_workbench.scss`** — Double blank line removed. Resolves G-5.
7. **`class-admin.php`** — `'alt-context-settings'` removed from `SUPPORTED_PAGE_SLUGS`. Resolves G-2.
8. **`class-api.php`** — `$thumb ?: null` replaced with `false === $thumb ? null : $thumb`. Semantically more explicit.
9. **`trait-batch-limits.php`** — Comment on `unset($_tier)` expanded with design rationale.

### New Findings

#### G-8 — MEDIUM — ANTIPATTERN: `class-api.php` indentation broken on `thumbnailUrl` line

**Finding:** The replacement on [class-api.php](apps/prototype-wp-alt-context/src/api/class-api.php#L141) introduced a tab-alignment error. The `'thumbnailUrl'` key is indented with an extra tab compared to its siblings in the array:

```php
				'status'       => '' === trim( (string) $alt_text ) ? 'missing' : 'complete',
					'thumbnailUrl' => false === $thumb ? null : $thumb,   // ← extra tab
				'altText'      => '' === trim( (string) $alt_text ) ? null : $alt_text,
```

All other keys in the array use 4 tabs of indentation; `thumbnailUrl` uses 5. This is a formatting regression that breaks visual alignment.

**Severity:** MEDIUM — Not a runtime defect, but will confuse reviewers and may cause PHPCS violations if the `tests` directory or this file is scanned with stricter rules.

**Recommendation:** Align `'thumbnailUrl'` to 4 tabs, matching its siblings.

---

#### G-9 — MEDIUM — GAP: `tests` directory removed from `cs-check` scope

**Finding:** The `cs-check` script in [composer.json](apps/prototype-wp-alt-context/composer.json#L32) now targets `src alt-context.php` only. The `tests` directory was dropped entirely. While test files have heavy formatting incompatibilities with WordPress coding standards, excluding them means no code-style enforcement on test code at all.

**Severity:** MEDIUM — Test code may drift in style without any lint coverage. A narrower exclusion (e.g., keeping tests but adding test-specific exclusions) would be preferable.

**Recommendation:** Either restore `tests` to the targets with an additional `--exclude` for test-only incompatible sniffs, or document the exclusion rationale in the composer.json or a project-level config note.

---

#### G-10 — LOW — GAP: Massive `--exclude` list in `composer.json` is fragile

**Finding:** The `cs-check` and `cs-fix` scripts each contain a ~850-character `--exclude` flag with 28 individual sniff names. This is duplicated between both scripts and is difficult to maintain. Any change requires updating both lines in lockstep.

**Severity:** LOW — Works correctly today, but maintenance burden is high.

**Recommendation:** Extract the exclusion list to a `phpcs.xml` or `.phpcs.xml.dist` configuration file, which both scripts can reference via `--standard=./phpcs.xml`. This is the standard WordPress plugin approach and eliminates duplication.

---

### Updated Finding Status

| ID | Status | Notes |
|---|---|---|
| G-1 | **Resolved** | PHPCS gate passes with scoped exclusions |
| G-2 | **Resolved** | Phantom slug removed |
| G-3 | **Resolved** | Canonical names in tests |
| G-4 | **Tracked** | Decomposition plan in `recognition-controller-decomposition-plan.md` |
| G-5 | **Resolved** | SCSS blank line removed |
| G-6 | **Resolved** | MockEventSource comment clarified |
| G-7 | **Resolved** | Todo items tagged with tracking IDs |
| G-8 | **Open** | `thumbnailUrl` alignment fixed, but `return array(…)` block shifted to 5 tabs (should be 4); `dimensions` children at same level as parent key; closing elements each under-indented by one tab. Carried forward as G-11 in `review-87e6ea9-gaps.md`. |
| G-9 | **Closed** | Confirmed: `phpcs.xml.dist` includes `tests` directory; only `tests/stubs/wp.php` excluded. |
| G-10 | **Closed** | Confirmed: `composer.json` scripts reference `--standard=phpcs.xml.dist`; all exclusions in one file. |
