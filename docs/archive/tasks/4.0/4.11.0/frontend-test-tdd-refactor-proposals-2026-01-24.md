# Frontend + WP Test Refactor Proposals (TDD Focus)

Date: 2026-01-24

## Goals
- Increase behavior-level coverage for UI flows.
- Reduce brittle timer-driven tests.
- Add missing coverage for new pagination controls and suggestion actions.

## JavaScript/React Tests

### 1) Add per-page selector + persistence coverage (new feature)
**Why:** The new 10/50/100 images per page selector and localStorage persistence are currently untested.

**Files to update/add:**
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx`
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/SuggestionReviewPanel.test.tsx` (optional for shared query invalidation)

**Proposed tests:**
- Render WorkbenchPage, select 50 per page, verify:
  - `useWorkbenchMedia` is called with `perPage=50`.
  - `localStorage['acx-media-page-size']` is set to `50`.
  - Changing perPage resets page to 1.
- Re-render with stored value, ensure initial perPage uses stored preference.

### 2) Add success-path coverage for SuggestionReviewPanel
**Why:** Only the error/hide path is tested; the main success flow isn’t.

**File:**
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/SuggestionReviewPanel.test.tsx`

**Proposed tests:**
- When `fetchPendingSuggestions` resolves, panel renders items.
- Clicking Accept/Reject calls `acceptSuggestion`/`rejectSuggestion` and invalidates queries.
- Verify optimistic UI changes or post-action refetch behavior.

### 3) Reduce timer coupling in IdentityClusterList tests
**Why:** Tests depend on `SAVE_SUCCESS_DELAY_MS` and fake timers; brittle when UI timing changes.

**File:**
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/IdentityClusterList.test.tsx`

**Proposed refactor:**
- Replace time-advance waits with `waitFor` on UI states (e.g., button label, toast presence).
- If a delay is required, centralize it in a helper so UI timing changes are applied in one place.

### 4) Add light integration coverage for WorkbenchPage + hooks
**Why:** The current WorkbenchPage tests mock almost every hook; behavior regressions can slip through.

**File:**
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx`

**Proposed approach:**
- Keep hook-level tests, but add a light integration test using real hooks with mocked network calls.
- Validate that scan action triggers query invalidation and updates status text.

## PHP (WordPress) Tests

### Where PHP tests run
- `composer test` runs PHPUnit with `phpunit.xml.dist`.
- Suite includes `tests/Unit/*` only.
- Script is defined in `apps/prototype-wp-alt-context/composer.json`.

### PHP tests currently covered (unit-level)
- Admin tier normalization and fallback (`AdminTest`).
- Batch limit behavior (`BatchLimitsTest`).
- Proxy retry behavior (`ProxyRequestTest`).
- Controller validation (`RecognitionControllerTest`).
- Lifecycle options on activate/deactivate/uninstall (`LifecycleManagerTest`).
- Example scaffolding test (`ExampleTest`).

### Suggested new PHP tests
**1) Suggestions endpoints via RecognitionController**
**Why:** The WP proxy path for suggestions (pending + accept/reject) is core but untested.

**Add tests in:**
- `apps/prototype-wp-alt-context/tests/Unit/RecognitionControllerTest.php`

**Proposed tests:**
- `get_pending_suggestions` sends limit/offset, includes tenant_id.
- `accept_suggestion` and `reject_suggestion` validate suggestion_id and include tenant_id payload.
- Ensure `include_details` is not forwarded anymore (regression guard).

**2) Suggestion proxy request headers**
**Why:** Ensure API key header and tenant header usage are correct for suggestions endpoints.

**Add tests in:**
- `apps/prototype-wp-alt-context/tests/Unit/ProxyRequestTest.php`

**Proposed tests:**
- For pending suggestions request, verify `X-API-Key` is included when configured.

### JS tests that should be added
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection` tests for per-page selector and persistence.
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/SuggestionReviewPanel` success path.

## Notes
- The refactors above focus on behavior validation (user-visible outcomes) rather than internal hook mocks.
- The goal is to keep fast unit tests, but add one or two higher-signal integration-style tests.
