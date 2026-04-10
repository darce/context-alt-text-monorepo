# Review: Commit 87e6ea9 — Implementation Gaps

> **Branch:** `feature/4.13.0-web-push`  
> **Commit:** `87e6ea9` — "Fix $_tier implementation issues"  
> **Parent:** `2b690a2`  
> **Date:** 2026-02-10  
> **Scope:** 20 files changed, +94 / −197 lines  
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
| `composer cs-check` | **pass** (exit 0, via new `phpcs.xml.dist`) |

All six gates green. Manual review follows.

---

## Summary of Changes Reviewed

### PHP

1. **`composer.json`** — `cs-check` / `cs-fix` scripts simplified to `--standard=phpcs.xml.dist`. Removes duplicated inline `--exclude` lists (resolves prior G-10).
2. **`phpcs.xml.dist`** *(new)* — 50-line WordPress PHPCS config. Targets `src`, `tests`, `alt-context.php`; excludes `tests/stubs/wp.php` and 28 style-related sniffs. Restores test directory to CS scope (resolves prior G-9).
3. **`class-api.php`** — Indentation rework of `return array(…)` block in `list_media()` callback.
4. **`BatchLimitsTest.php`** — Anonymous class body reformatted from spaces to tabs.
5. **`ProxyRequestTest.php`** — Trailing whitespace removed (cosmetic).

### TypeScript — Dead Code Removal

6. **`clusterAdapter.ts`** *(deleted)* — 59-line dead adapter. Zero remaining imports.
7. **`types/constraint.ts`** *(deleted)* — Dead type file. Zero remaining imports or re-exports.
8. **`clusterApi.ts`** — Barrel re-exports removed: `reassignClusterFace`, `pinRepresentative`, `fetchClusterLabels`.
9. **`clusterApiMembers.ts`** — Removed `pinRepresentative` function.
10. **`clusterApiMutations.ts`** — Removed `reassignClusterFace` wrapper. Added `TODO(sovereign-phase-3)` on `undismissCluster`.
11. **`clusterApiQueries.ts`** — Removed `fetchClusterLabels` function.
12. **`types/cluster.ts`** — Removed `ReassignClusterFaceRequest`, `ClusterRepresentative`, `PinRepresentativeRequest` interfaces; removed unused `DebugMetrics` import.
13. **`types/index.ts`** — Removed `constraint` re-export.
14. **`index.ts` (recognition barrel)** — Removed dead re-exports.
15. **`useMediaSelectionState.ts`** — Removed unused `clearSelection` function.
16. **`WorkbenchPage.test.tsx`** — Removed `clearSelection: vi.fn()` from mock (matches hook change).

### TypeScript — Simplification & Bug Fix

17. **`scanApi.ts`** — Replaced `TenantLimits` interface / `getTenantLimits()` with `getMaxMediaPerBatch()`. Single-value accessor replaces object fetch; cleaner call sites.
18. **`useJobStateMachine.ts`** — Bug fix: `useCombinedScanStatus(jobId ?? null, [])` → `useCombinedScanStatus(jobId ?? null, activeJobIds)`. The empty array prevented active job IDs from being included in combined status polling, potentially missing in-flight scan updates.

---

## Dead Code Verification

All deleted symbols were grep-checked for residual references. Zero matches for:

| Symbol | Type | Result |
|---|---|---|
| `clusterAdapter` | module | 0 matches |
| `constraint` (types/) | module | 0 matches |
| `pinRepresentative` | function | 0 matches |
| `reassignClusterFace` | function | 0 matches |
| `fetchClusterLabels` | function | 0 matches |
| `clearSelection` | function | 0 matches |
| `ReassignClusterFaceRequest` | interface | 0 matches |
| `ClusterRepresentative` | interface | 0 matches |
| `PinRepresentativeRequest` | interface | 0 matches |
| `TenantLimits` | interface | 0 matches |
| `getTenantLimits` | function | 0 matches |

`DebugMetrics` import was removed only from `types/cluster.ts`; 11 legitimate references remain in `identity.ts`, `DebugMetricsPanel.tsx`, and `index.ts`.

---

## Manual Checklist Walk-Through

### §3.1 Correctness ✓

- **useJobStateMachine bug fix** is a genuine correctness improvement. Passing `activeJobIds` instead of `[]` ensures combined scan status reflects all in-flight jobs.
- No unreachable code introduced.
- No duplicate declarations.

### §3.2 Type Safety ✓

- All removed interfaces had zero remaining consumers.
- No new `as T` casts, non-null assertions, or `undefined as T` patterns.
- `getMaxMediaPerBatch()` returns `number` (typed via `getConfig()` return shape).

### §3.3 Architecture Boundaries ✓

- `scanApi.ts` simplified to a direct config accessor — still goes through `getConfig()`, not raw globals.
- No cross-layer violations.

### §3.4 Code Duplication ✓

- Inline `--exclude` duplication eliminated by `phpcs.xml.dist`.
- No new duplication introduced.

### §3.5 Error Handling ✓

- No error-handling changes in this commit.

### §3.6 Frontend Specific ✓

- No SCSS changes, no new inline styles, no `!important`.
- All API removals were in proper API barrel modules.

### §3.7 PHP / WordPress — Issues Found

- **`class-api.php`** — Indentation regression in `list_media()` callback. See G-11.
- **`BatchLimitsTest.php`** — Mixed indentation (tabs inside space-indented context). See G-12.
- No superglobal or nonce changes.

### §3.8 Tests ✓

- `WorkbenchPage.test.tsx` mock correctly updated to reflect `clearSelection` removal.
- No new permanently skipped tests.
- No empty test bodies.

### §3.9 Documentation & Cleanup ✓

- `TODO(sovereign-phase-3)` on `undismissCluster` has a structured tracking ID and actionable description. Compliant with review guide — not a stale or vague TODO.

---

## Implementation Gaps Found

### G-11 — MEDIUM — ANTIPATTERN: `class-api.php` indentation regression in `return array(…)` block

**Finding:** The original G-8 (`thumbnailUrl` extra-tab misalignment) was partially addressed — all sibling keys now align. However, the `return array(…)` block itself is at **5 tabs** while its surrounding closure body statements (`$alt_text`, `$thumb`, `$meta`, `$terms`) are at 4 tabs. Additionally, from the `dimensions` sub-array onward, indentation is off by one tab:

```
Actual tab counts (sed -n 'l' analysis):

Line   Content                          Tabs  Expected
----   -------                          ----  --------
136    (blank)                           0     —
137    return array(                     5     4
138    'id'           => …              6     5
139    'title'        => …              6     5
140    'status'       => …              6     5
141    'thumbnailUrl' => …              6     5
142    'altText'      => …              6     5
143    'mimeType'     => …              6     5
144    'editUrl'      => …              6     5
145    'updatedAt'    => …              6     5
146    'dimensions'   => array(         6     5
147    'width'  => …                    6     6  ← should be 6, IS 6 ✓*
148    'height' => …                    6     6  ← should be 6, IS 6 ✓*
149    ),                               5     5  ← closing dimensions ✓*
150    'tags'         => …              5     5  ← but should be same as siblings (6)
151    );                               4     4  ← closing return ✓*
```

*\* Marks lines that are correct relative to the over-indented `return array(`. The block is internally inconsistent: keys `'id'` through `'dimensions'` are at 6 tabs, but `'tags'` drops to 5 tabs (matching the closing bracket level, not the key level).*

The entire `return array(…)` should start at 4 tabs (matching sibling statements in the closure body), keys at 5 tabs, `dimensions` children at 6 tabs, closings one level out from their opener.

**Evidence:** [class-api.php](../../../../apps/prototype-wp-alt-context/src/api/class-api.php#L137-L151) — `sed -n 'l'` output confirms tab sequences.

**Impact:** Not a runtime defect. Passes `composer cs-check` because `WordPress.Arrays.ArrayIndentation` is excluded. Creates visual confusion for maintainers and will surface as a violation if array indentation sniffs are ever re-enabled.

**Recommendation:** Re-indent the block:

```php
				$terms    = wp_get_object_terms( $attachment_id, 'post_tag', array( 'fields' => 'names' ) );

				return array(
					'id'           => $attachment_id,
					'title'        => get_the_title( $attachment_id ),
					'status'       => '' === trim( (string) $alt_text ) ? 'missing' : 'complete',
					'thumbnailUrl' => false === $thumb ? null : $thumb,
					'altText'      => '' === trim( (string) $alt_text ) ? null : $alt_text,
					'mimeType'     => get_post_mime_type( $attachment_id ),
					'editUrl'      => get_edit_post_link( $attachment_id, '' ),
					'updatedAt'    => get_post_modified_time( 'c', true, $attachment_id ),
					'dimensions'   => array(
						'width'  => isset( $meta['width'] ) ? (int) $meta['width'] : null,
						'height' => isset( $meta['height'] ) ? (int) $meta['height'] : null,
					),
					'tags'         => is_wp_error( $terms ) || ! is_array( $terms ) ? array() : array_values( $terms ),
				);
```

**Continuity:** Superseded G-8 from `review-69ab3b4-gaps.md`; both carry-over indentation issues are now resolved in this branch.

---

### G-12 — LOW — ANTIPATTERN: `BatchLimitsTest.php` mixed tabs and spaces in `setUp()`

**Finding:** The anonymous class body (lines 24–37) was reformatted to use tab indentation in this commit, but the enclosing `setUp()` method and `BatchLimitsTest` class use **space indentation** (consistent with the rest of the PHPUnit test file). This creates a visual discontinuity:

```php
    protected function setUp(): void              // ← spaces (4)
    {                                              // ← spaces (4)
        parent::setUp();                           // ← spaces (8)

        // Create anonymous class that uses the trait
	        $this->subject = new class() {         // ← 1 tab + 8 spaces
				use BatchLimits;                   // ← 4 tabs
				public function getTier...         // ← 4 tabs
```

The anonymous class comment line has a leading tab mixed with spaces, and the class body uses pure tabs — contrasting with the surrounding pure-space indentation.

**Evidence:** [BatchLimitsTest.php](../../../../apps/prototype-wp-alt-context/tests/Unit/BatchLimitsTest.php#L24-L37).

**Impact:** Cosmetic. Passes `composer cs-check` because `Generic.WhiteSpace.DisallowSpaceIndent` is excluded in `phpcs.xml.dist`. Does not affect test execution.

**Recommendation:** Align the anonymous class body to match the surrounding file's space-based indentation (4 spaces per level, consistent with PHPUnit convention in this project). Alternatively, if the intent is to migrate test files to tabs, do so as a separate whole-file consistency pass.

---

## Finding Status

| ID | Severity | Category | Status | Summary |
|---|---|---|---|---|
| G-11 | **MEDIUM** | ANTIPATTERN | **Resolved** | `class-api.php` `return array(…)` block re-indented to closure-level alignment with consistent key nesting. |
| G-12 | **LOW** | ANTIPATTERN | **Resolved** | `BatchLimitsTest.php` anonymous class indentation normalized to the file's existing space-based style. |

---

## Prior Gap Verification (from review-69ab3b4-gaps.md)

| Prior ID | Verdict | Evidence |
|---|---|---|
| G-8 | **Resolved** | `return array(…)` block and nested keys were re-indented to consistent closure-level tab nesting. |
| G-9 | **Confirmed closed** | `phpcs.xml.dist` `<file>tests</file>` restores test directory to CS scope. Only `tests/stubs/wp.php` excluded. |
| G-10 | **Confirmed closed** | `composer.json` scripts reference `--standard=phpcs.xml.dist`. No inline `--exclude` duplication remains. |

---

## Positive Changes (No Gaps)

- **`useJobStateMachine.ts` bug fix** — Correctness improvement; combined scan status now includes active job IDs.
- **Dead code removal** — 11 symbols across 11 files deleted cleanly with zero orphaned references.
- **`scanApi.ts` simplification** — Clean reduction from object interface to single accessor.
- **`phpcs.xml.dist` extraction** — Proper WordPress-standard config file replaces fragile inline flags.
- **`TODO(sovereign-phase-3)`** — Structured tracking ID with clear description; compliant with §3.9.
