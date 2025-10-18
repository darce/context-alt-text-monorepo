# Refactoring Task List

**Project:** Context Alt Text WordPress Plugin  
**Date:** October 17, 2025  
**Status:** Pre-Production Greenfield Refactoring

**Context Documents:**

- [PHP Audit](apps/wp-context-alt-text/PHP_AUDITS.md) - Backend code analysis
- [Frontend Audit](apps/wp-context-alt-text/FRONTEND_AUDITS.md) - JavaScript/React code analysis

---

## 🎯 Executive Summary

This document provides a **comprehensive refactoring roadmap** combining tactical code cleanup with strategic architectural improvements. It integrates findings from PHP backend audits, frontend audits, and architectural analysis into a cohesive plan.

### Two-Track Approach

**Track 1: Tactical Refactoring (Phases 1-10)** - Start here

- **Focus:** Code cleanup, duplication removal, test coverage, immediate wins
- **Time:** 46-58 hours (6-8 weeks part-time)
- **Impact:** ~1,473 lines reduced, 35-40% technical debt eliminated, +8-10% test coverage
- **Benefits:** Cleaner codebase, less duplication, better testing, easier maintenance
- **Risk:** Low - incremental changes

**Track 2: Strategic Architecture (Phase 11)** - Plan for later

- **Focus:** Design patterns, infrastructure, long-term maintainability
- **Time:** 8+ weeks (requires careful planning)
- **Impact:** 80% bootstrap reduction, 67% API reduction, zero circular dependencies
- **Benefits:** Better testability, extensibility, developer experience
- **Risk:** Medium - requires architectural changes

### What's Included

**Tactical Tasks (Phases 1-10):**

1. **Greenfield cleanup** - Remove 713 unnecessary lines before production ✓
2. **Shared utilities** - Eliminate 260+ lines of duplication ✓
3. **Hook simplification** - Fix state management with useReducer, refactor 3 complex hooks
4. **PHP utilities** - Extract common patterns (80 lines reduced)
5. **Cross-stack alignment** - Better frontend/backend symmetry
6. **Component improvements** - Break down large files
7. **Test coverage** - Increase coverage from 74.5% → 82.5%+ with utilities, contract, and edge case tests

**Strategic Tasks (Phase 11):**

1. **DI Container** - Reduce bootstrap from 491→100 lines
2. **Service Providers** - Clear domain separation
3. **Event Bus** - Eliminate circular dependencies
4. **CQRS** - Reduce Api.php from 1,509→500 lines
5. **Test Infrastructure** - Factories and builders

### Quick Comparison

| Aspect          | Tactical (Now)   | Strategic (Later)        |
| --------------- | ---------------- | ------------------------ |
| Time Investment | 40-50 hours      | 8+ weeks                 |
| When to Start   | Immediately      | After tactical complete  |
| Risk Level      | Low              | Medium                   |
| Code Changes    | ~1,500 lines     | ~2,000+ lines            |
| Impact          | Cleanup & polish | Architectural foundation |
| Reversibility   | Easy             | Moderate                 |

**Recommendation:** Complete Tactical Phases 1-3 (critical path, 11 hours) first, then evaluate if strategic architecture is needed based on project trajectory.

---

## � Overall Progress Tracker

**Tactical Refactoring (Phases 1-10):**

- [x] **Phase 1:** Greenfield Cleanup (1h) - 5/5 tasks complete ✓
- [x] **Phase 2:** Frontend Utilities (3h) - 2/2 tasks complete ✓
- [x] **Phase 3:** Frontend Hooks (5-7h) - 6/7 tasks complete ✅ (Task 3.7 deferred to Phase 10, hooks compliant)
- [x] **Phase 4:** PHP Utilities (3h) - 4/4 tasks complete ✅
- [ ] **Phase 5:** Frontend Components (12-18h) - 0/4 tasks complete ⬅️ **CURRENT FOCUS**
- [ ] **Phase 6:** Cross-Stack Alignment (6h) - 0/3 tasks complete
- [ ] **Phase 7:** PHP Components (4h) - 0/3 tasks complete
- [ ] **Phase 8:** Test Coverage (6-8h) - 0/6 tasks complete
- [ ] **Phase 9:** Documentation (2h) - 0/2 tasks complete
- [ ] **Phase 10:** Polish (10h) - 0/4 tasks complete

**Total: 17/49 tactical tasks complete (35%)**

**Note**: Phase 5 expanded from 2 to 4 tasks to include architecture compliance audits and component refactoring based on new [Frontend Component Architecture Rules](docs/architecture/rules/instructions.md).

**Strategic Architecture (Phase 11):**

- [ ] **Phase 11A:** DI Container + Service Providers (4-6 days)
- [ ] **Phase 11B:** Event Bus + Repository Refinement (4-6 days)
- [ ] **Phase 11C:** CQRS Implementation (5-6 days)
- [ ] **Phase 11D:** Test Infrastructure (2-3 days)

---

## �📊 Refactoring Priorities

### Tactical Refactoring (Code Cleanup)

| Priority    | Category              | Tasks | Time | Impact                                  |
| ----------- | --------------------- | ----- | ---- | --------------------------------------- |
| 🔴 Critical | Greenfield Cleanup    | 5     | 1h   | Remove 713 lines ✓                      |
| 🔴 Critical | Frontend Utilities    | 2     | 3h   | Remove 260 lines ✓                      |
| 🔴 Critical | Frontend Hooks        | 7     | 6-8h | Fix state management + Remove 545 lines |
| 🟡 High     | PHP Utilities         | 4     | 3h   | Remove 80 lines                         |
| 🟡 High     | Frontend Components   | 2     | 4h   | Improve structure                       |
| 🟡 High     | Cross-Stack Alignment | 3     | 6h   | Better symmetry                         |
| 🟢 Medium   | PHP Components        | 3     | 4h   | Improve maintainability                 |
| 🟢 Medium   | Test Coverage         | 6     | 6-8h | Confidence & quality                    |
| 🟢 Medium   | Documentation         | 2     | 2h   | Update after refactoring                |
| 🟢 Low      | Polish                | 4     | 10h  | Optional improvements                   |

**Tactical Subtotal:** 45-60 hours, ~1,678 lines reduced, +10-15% test coverage

### Strategic Architecture (Long-term Improvements)

| Priority    | Category              | Tasks | Time     | Impact                          |
| ----------- | --------------------- | ----- | -------- | ------------------------------- |
| 🔴 Critical | DI Container          | 3     | 2-3 days | Bootstrap: 491→100 lines (-80%) |
| 🔴 Critical | Service Providers     | 5     | 2-3 days | Clear domain separation         |
| 🟡 High     | Event Bus             | 10    | 3-4 days | Zero circular dependencies      |
| 🟡 High     | Repository Refinement | 3     | 1-2 days | Single responsibility           |
| 🟢 Medium   | CQRS                  | 25    | 5-6 days | Api.php: 1,509→500 lines (-67%) |
| 🟢 Medium   | Domain Events         | 5     | 1-2 days | Analytics/audit foundation      |
| 🟢 Low      | Test Infrastructure   | 15    | 2-3 days | Better test utilities           |

**Strategic Subtotal:** 8+ weeks (part-time), Major architectural improvements

**See:** [ARCHITECTURAL_IMPROVEMENTS.md](ARCHITECTURAL_IMPROVEMENTS.md) for detailed strategic roadmap.

---

## 🎭 Two-Track Approach

This document now covers **both tactical and strategic improvements**:

**Track 1: Tactical Refactoring (Phases 1-9)**

- Focus: Code cleanup, duplication removal, immediate wins
- Timeline: 40-50 hours (can complete in 5-7 weeks part-time)
- Benefits: Cleaner codebase, less duplication, easier maintenance
- **Start here** - these are quick wins with immediate benefits

**Track 2: Strategic Architecture (See ARCHITECTURAL_IMPROVEMENTS.md)**

- Focus: Design patterns, infrastructure, long-term maintainability
- Timeline: 8+ weeks (requires careful planning and implementation)
- Benefits: Better testability, extensibility, developer experience
- **Plan for later** - these require more upfront investment but pay dividends long-term

### Recommended Approach

1. **Complete Tactical Phases 1-3 first** (11 hours, critical path)

   - Greenfield cleanup
   - Frontend utilities
   - Frontend hooks

2. **Then evaluate strategic architecture**

   - If adding 3+ new features soon → Start DI Container + Service Providers
   - If maintaining current scope → Continue tactical refactoring
   - If planning major expansion → Full strategic roadmap

3. **Mix and match based on needs**
   - Can do tactical refactoring while planning strategic changes
   - Strategic improvements can be done incrementally
   - No need to complete everything at once

---

## 🔴 PHASE 1: Critical - Greenfield Cleanup (1 hour)

**Goal:** Remove unnecessary code before production launch

**Progress Tracker:**

- [x] Task 1.1: Remove Redundant WordPress Stub Files
- [x] Task 1.2: Fix Settings Option Name (Root Cause)
- [x] Task 1.3: Update Test Files for New Option Name
- [x] Task 1.4: Remove Legacy Migration Code
- [x] Task 1.5: Update Documentation for New Option Name

---

### Task 1.1: Remove Redundant WordPress Stub Files

**Priority:** 🔴 Critical  
**Time:** 15 minutes  
**Impact:** -653 lines  
**Status:** [x] Complete

**Context:** [PHP_AUDITS.md - Greenfield Refactoring Priorities](apps/wp-context-alt-text/PHP_AUDITS.md#-critical-remove-redundant-wordpress-stub-files)

**Actions:**

```bash
cd apps/wp-context-alt-text
rm src/Support/WpFunctionStubs.php          # 253 lines
rm phpstubs/wordpress-functions.php         # 400 lines
rmdir phpstubs
```

**Why:** Project already uses `php-stubs/wordpress-stubs` composer package. Custom stubs are redundant.

**Verification:**

```bash
grep -r "WpFunctionStubs" src/
grep -r "wordpress-functions.php" src/
# Both should return no results
```

---

### Task 1.2: Fix Settings Option Name (Root Cause)

**Priority:** 🔴 Critical  
**Time:** 5 minutes  
**Impact:** Fixes architectural misalignment  
**Status:** [ ] Not Started

**Context:** [PHP_AUDITS.md - Fix PluginSettingsPage](apps/wp-context-alt-text/PHP_AUDITS.md#phase-2-fix-pluginsettingspagephp-2-min)

**File:** `src/Admin/PluginSettingsPage.php`

**Change:**

```php
// Line 34 - OLD:
private const OPTION_NAME = 'context_alt_text_recognition_settings';

// Line 34 - NEW:
private const OPTION_NAME = 'cat_settings';
```

**Why:** Settings page was using legacy option name, forcing SettingsRepository to maintain backwards compatibility code.

---

### Task 1.3: Update Test Files for New Option Name

**Priority:** 🔴 Critical  
**Time:** 15 minutes  
**Impact:** Aligns test suite with new architecture  
**Status:** [ ] Not Started

**Context:** [PHP_AUDITS.md - Update Test Files](apps/wp-context-alt-text/PHP_AUDITS.md#phase-3-update-test-files-15-min)

**Files to Update (6 files):**

1. `tests/Integration/ConfigurationIntegrationTest.php` (lines 104, 221)
2. `tests/Support/FeatureFlagsTest.php` (line 150)
3. `tests/Recognition/RecognitionClientTest.php` (line 20)
4. `tests/Integration/RecognitionServiceIntegrationTest.php` (lines 41, 52, 206, 226)
5. `tests/Roster/RosterClientTest.php` (line 20)

**Change Pattern:**

```php
// OLD:
$GLOBALS['__cat_options']['context_alt_text_recognition_settings'] = [...]
update_option('context_alt_text_recognition_settings', [...])

// NEW:
$GLOBALS['__cat_options']['cat_settings'] = [...]
update_option('cat_settings', [...])
```

---

### Task 1.4: Remove Legacy Migration Code

**Priority:** 🔴 Critical  
**Time:** 15 minutes  
**Impact:** -60 lines  
**Status:** [ ] Not Started

**Context:** [PHP_AUDITS.md - Remove Legacy Migration](apps/wp-context-alt-text/PHP_AUDITS.md#phase-4-remove-legacy-migration-code-15-min)

**File:** `src/Shared/Config/SettingsRepository.php`

**Remove:**

- Line 29: `LEGACY_RECOGNITION_OPTION` constant
- Line 48: `mergeLegacyRecognitionSettings()` call
- Lines 100, 117: `syncLegacyRecognitionOption()` calls
- Lines 211-249: `mergeLegacyRecognitionSettings()` method (39 lines)
- Lines 251-260: `syncLegacyRecognitionOption()` method (10 lines)

**Why:** No production users, no legacy data exists. Migration code adds unnecessary complexity.

**Verification:**

```bash
composer test
grep -r "LEGACY_RECOGNITION_OPTION" src/
# Should return no results
```

---

### Task 1.5: Update Documentation for New Option Name

**Priority:** 🔴 Critical  
**Time:** 10 minutes  
**Impact:** Prevents developer confusion  
**Status:** [x] Complete

**Files to Update (4 files):**

1. `docs/configuration.md` (5 occurrences)
2. `docs/development.md` (1 occurrence)
3. `docs/troubleshooting.md` (3 occurrences)
4. `README.md` (WP-CLI examples)

**Change Pattern:**

```bash
# OLD:
wp option update context_alt_text_recognition_settings \
  '{"base_url":"...","timeout_ms":"30000"}' --format=json

# NEW:
wp option update cat_settings \
  '{"recognition":{"baseUrl":"...","timeoutMs":30000,"enabled":true}}' --format=json
```

**Note:** Script `scripts/smoke-test-local-integration.sh` already updated.

---

## 🔴 PHASE 2: Critical - Frontend Utilities Extraction (3 hours)

**Goal:** Eliminate 260+ lines of duplication in frontend hooks

**Progress Tracker:**

- [x] Task 2.1: Create Shared Normalization Utilities
- [x] Task 2.2: Create Shared HTTP Utilities

---

### Task 2.1: Create Shared Normalization Utilities

**Priority:** 🔴 Critical  
**Time:** 2 hours  
**Impact:** -200 lines  
**Status:** [x] Complete

**Context:** [FRONTEND_AUDITS.md - Duplicated Normalization Logic](apps/wp-context-alt-text/FRONTEND_AUDITS.md#-1-duplicated-normalization-logic)

**Create:** `js/admin/utils/normalization.ts`

**Affected Files (3 hooks):**

- `js/admin/hooks/useRecognitionJob.ts` (lines 107-247)
- `js/admin/hooks/useRecognitionObservations.ts` (lines 90-221)
- `js/admin/hooks/useRoster.ts` (encoding logic)

**Functions to Extract:**

```typescript
// Basic type coercion
export const toFiniteNumber = (candidate: unknown, fallback = 0): number
export const toNumberOrNull = (candidate: unknown): number | null
export const toStringOrNull = (candidate: unknown): string | null
export const toBooleanOrNull = (candidate: unknown): boolean | null
export const toUniqueNumericIds = (ids: (number | string)[]): number[]
export const toNullableTimestamp = (value: unknown): number | null
export const ensureString = (value: unknown): string

// Domain object normalization
export const normalizeObservation = (data: unknown): RecognitionObservationRecord
export const normalizeRosterEntry = (data: unknown): RosterEntry
export const normalizeJobSummary = (data: unknown): RecognitionJobSummary
export const normalizeJobDetails = (data: unknown): RecognitionJobDetails
```

**Additional Location:** `js/admin/dashboardData.ts` already has normalization functions that could be consolidated:

- `normalizeMetric`
- `normalizeRecognition`
- `normalizeRosterMedia`
- `normalizeWorkbenchItem`
- `normalizeDimensions`
- `normalizeWorkbenchPagination`
- `normalizeRosterEntry`
- `normalizeRosterStats`

**Decision Required:** Consolidate all normalization in one place or keep domain-specific normalization separate?

**Recommendation:** Create hierarchy:

```
utils/
├── normalization/
│   ├── index.ts           # Re-exports
│   ├── primitives.ts      # toFiniteNumber, toStringOrNull, etc.
│   ├── recognition.ts     # Recognition domain objects
│   ├── roster.ts          # Roster domain objects
│   └── workbench.ts       # Workbench domain objects
```

---

### Task 2.2: Create Shared HTTP Utilities

**Priority:** 🔴 Critical  
**Time:** 1 hour  
**Impact:** -60 lines  
**Status:** [x] Complete

**Context:** [FRONTEND_AUDITS.md - Duplicated URL Building](apps/wp-context-alt-text/FRONTEND_AUDITS.md#-2-duplicated-url-building-logic)

**Enhance:** `js/admin/utils/http.ts` (currently 36 lines)

**Affected Files (3 hooks):**

- `js/admin/hooks/useRecognitionObservations.ts` (lines 68-92)
- `js/admin/hooks/useRoster.ts` (lines 57-83)
- `js/admin/hooks/useWorkbenchMedia.ts` (lines 199-217)

**Add to `http.ts`:**

```typescript
// URL building
export const buildApiUrl = (
  endpoint: string,
  params?: Record<string, string | number | boolean | null | undefined>,
): string

// Header building
export const buildHeaders = (
  restNonce?: string,
  includeJson = false,
): HeadersInit

// Unified fetch
export interface FetchApiOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  params?: Record<string, string | number | boolean | null | undefined>;
  body?: unknown;
  restNonce?: string;
}

export const fetchApi = async <T = unknown>(
  endpoint: string,
  options: FetchApiOptions = {},
): Promise<T>
```

**Benefits:**

- Consistent error handling
- Centralized nonce management
- Automatic JSON encoding/decoding
- Eliminates 3 duplicate implementations

---

## 🧠 State Management Decision (Phase 3 Foundation)

**Problem Identified:** Multiple hooks (especially `useRecognitionJob.ts`) use 6+ separate `useState` hooks, leading to:

- Race conditions (non-atomic state updates)
- Inconsistent states (e.g., `isSubmitting=true` with `lastError` set)
- Complex coordination logic
- Multiple re-renders

**Solution Evaluated:**

| Option            | Pros                                            | Cons                                          | Verdict                         |
| ----------------- | ----------------------------------------------- | --------------------------------------------- | ------------------------------- |
| **Redux/Zustand** | Global state, dev tools                         | ❌ Overkill, React Query handles server state | ❌ Not needed                   |
| **XState**        | Explicit state machines, visualizer             | ❌ 18KB, learning curve                       | 🟡 Optional if complexity grows |
| **useReducer**    | ✅ Zero dependencies, atomic updates, type-safe | None for this use case                        | ✅ **SELECTED**                 |

**Decision: useReducer + TypeScript Discriminated Unions**

**Why:**

- ✅ Built into React (zero new dependencies)
- ✅ Perfect for state machines (job flow: idle → submitting → polling → complete/error)
- ✅ Atomic state updates (eliminates race conditions)
- ✅ Type-safe with discriminated unions (impossible states become impossible)
- ✅ Industry standard for complex useState scenarios
- ✅ Easy to test (pure reducer function)
- ✅ Works seamlessly with React Query for data fetching

**Implementation Pattern:**

```typescript
type JobState =
  | { status: "idle" }
  | { status: "submitting"; attachmentIds: number[] }
  | { status: "polling"; jobId: string }
  | { status: "complete"; job: RecognitionJobDetails }
  | { status: "error"; error: RecognitionRequestError };

function jobReducer(state: JobState, action: JobAction): JobState { ... }

const [state, dispatch] = useReducer(jobReducer, { status: "idle" });
```

**Reference:** [FRONTEND_AUDITS.md - State Management Section](apps/wp-context-alt-text/FRONTEND_AUDITS.md#4-state-management-react-query--usestate-no-reduxzustand-needed)

---

## 🔴 PHASE 3: Critical - Frontend Hook Refactoring (5-7 hours)

**Goal:** Fix state management issues and simplify overly complex hooks

**Progress Tracker:**

- [x] Task 3.1: Refactor useRecognitionJob with useReducer + state machine ✅ (COMPLETE - all tests passing)
- [x] Task 3.2: Simplify useRoster encoding logic ✅ (COMPLETE - 480→450 lines, all tests passing)
- [x] Task 3.3: Simplify useWorkbenchMedia.ts ✅ (COMPLETE - 347→224 lines, all tests passing)
- [x] Task 3.4: Extract useRecognitionJob state machine to separate files ✅ (COMPLETE - 750→634 lines)
- [x] Task 3.5: Simplify useRecognitionObservations ✅ (COMPLETE - 458→446 lines, -12 lines)
- [x] Task 3.6: Extract recognition normalization utilities ✅ (COMPLETE - 634→333 lines, -301 lines)
- [ ] Task 3.7: Extract recognition type definitions (333→290 lines, polish task, deferred to Phase 10)

**Architecture Compliance:**

- ✅ All hooks reviewed against new [Frontend Component Architecture Rules](docs/architecture/rules/instructions.md)
- ✅ Complete compliance achieved: 0 useState, 0 useEffect, 0 anti-patterns
- ✅ Detailed analysis: [HOOKS_ARCHITECTURE_REVIEW.md](apps/wp-context-alt-text/js/admin/hooks/HOOKS_ARCHITECTURE_REVIEW.md)
- 🔲 **Next**: Apply same standards to components (see Phase 5 updated tasks)

---

### Task 3.1: Refactor useRecognitionJob with useReducer State Machine

**Priority:** 🔴 Critical  
**Time:** 2-3 hours  
**Impact:** -150 lines, eliminates race conditions  
**Status:** [x] Complete ✅

**Progress:**

- ✅ Step 1: Extract normalization utilities (-42 lines)
- ✅ Step 2: Add state machine types and reducer
- ✅ Step 3: Replace 6 useState hooks with single useReducer
- ✅ Step 4: Update ~20 setState calls to dispatch actions and test

**Results:**

- All hook tests passing (3/3)
- All integration tests passing (4/4)
- File size: 585 → 750 lines (includes state machine infrastructure)
- Race conditions eliminated via atomic state updates
- State machine prevents impossible states

**Deferred:**

- Extract state machine types/reducer to separate files (see Task 3.4)

**Context:** [FRONTEND_AUDITS.md - useRecognitionJob Critical Bloat](apps/wp-context-alt-text/FRONTEND_AUDITS.md#2-userecognitionjobts--critical-bloat-585-lines)

**Current Issues:**

- 585 lines (should be <200)
- **6 separate useState hooks** creating race conditions and inconsistent states
- Manual polling implementation (60+ lines)
- Complex normalization (80 lines - already moved to utils in Phase 2)
- Brittle state coordination

**Root Problem:**

```typescript
// ❌ BAD: Multiple useState hooks - not atomic, race conditions
const [lastJob, setLastJob] = useState<RecognitionJobSummary | null>(null);
const [lastError, setLastError] = useState<RecognitionRequestError | null>(
  null
);
const [jobDetails, setJobDetails] = useState<RecognitionJobDetails | null>(
  null
);
const [isSubmitting, setIsSubmitting] = useState(false);
const [pollState, setPollState] = useState<PollState>("idle");
const [currentJobId, setCurrentJobId] = useState<string | null>(null);
```

**Solution: useReducer + TypeScript Discriminated Unions**

**Why useReducer:**

- ✅ Zero new dependencies (built into React)
- ✅ Atomic state updates (no race conditions)
- ✅ Impossible states become impossible
- ✅ Type-safe with discriminated unions
- ✅ Perfect for state machines
- ✅ Industry standard for complex useState scenarios
- ✅ Easy to test (pure reducer function)

**Refactoring Strategy:**

1. **Define state machine with discriminated union:**

```typescript
type JobState =
  | { status: "idle" }
  | { status: "submitting"; attachmentIds: number[] }
  | { status: "polling"; jobId: string; attempts: number }
  | { status: "complete"; job: RecognitionJobDetails }
  | { status: "error"; error: RecognitionRequestError; retryable: boolean };

type JobAction =
  | { type: "SUBMIT_START"; attachmentIds: number[] }
  | { type: "SUBMIT_SUCCESS"; jobId: string }
  | { type: "SUBMIT_ERROR"; error: RecognitionRequestError }
  | { type: "POLL_UPDATE"; job: RecognitionJobDetails }
  | { type: "POLL_COMPLETE"; job: RecognitionJobDetails }
  | { type: "RESET" };
```

2. **Create pure reducer function:**

```typescript
function jobReducer(state: JobState, action: JobAction): JobState {
  switch (action.type) {
    case "SUBMIT_START":
      return { status: "submitting", attachmentIds: action.attachmentIds };

    case "SUBMIT_SUCCESS":
      return { status: "polling", jobId: action.jobId, attempts: 0 };

    case "SUBMIT_ERROR":
      return { status: "error", error: action.error, retryable: true };

    case "POLL_UPDATE":
      if (state.status !== "polling") return state;
      return { ...state, attempts: state.attempts + 1 };

    case "POLL_COMPLETE":
      return { status: "complete", job: action.job };

    case "RESET":
      return { status: "idle" };

    default:
      return state;
  }
}
```

3. **Replace manual polling with React Query:**

```typescript
function useRecognitionJob() {
  const [state, dispatch] = useReducer(jobReducer, { status: "idle" });

  // React Query handles polling automatically
  const { data } = useQuery({
    queryKey: [
      "recognition-job",
      state.status === "polling" ? state.jobId : null,
    ],
    queryFn: () => fetchJob(state.jobId),
    refetchInterval: (data) => (data?.status === "complete" ? false : 2000),
    enabled: state.status === "polling",
    onSuccess: (data) => {
      if (data.status === "complete") {
        dispatch({ type: "POLL_COMPLETE", job: data });
      } else {
        dispatch({ type: "POLL_UPDATE", job: data });
      }
    },
  });

  const submitJob = async (attachmentIds: number[]) => {
    dispatch({ type: "SUBMIT_START", attachmentIds });
    try {
      const response = await submitJobApi(attachmentIds);
      dispatch({ type: "SUBMIT_SUCCESS", jobId: response.jobId });
    } catch (error) {
      dispatch({ type: "SUBMIT_ERROR", error });
    }
  };

  return {
    state,
    submitJob,
    reset: () => dispatch({ type: "RESET" }),
    isSubmitting: state.status === "submitting",
    isPolling: state.status === "polling",
    isComplete: state.status === "complete",
    hasError: state.status === "error",
  };
}
```

**Benefits:**

- Eliminates 6 useState hooks → 1 useReducer
- Impossible to be in `submitting` state with `error` set
- Single source of truth
- Type-safe exhaustive case handling
- React Query handles polling complexity
- Easy to add new states (e.g., "paused", "canceling")

**Testing:** Reducer is pure function - easy to unit test

---

### Task 3.2: Simplify useRoster Encoding Logic

**Priority:** 🟡 Medium  
**Time:** 1-2 hours  
**Impact:** -30 lines, improved readability  
**Status:** [x] Complete ✅

**Results:**

- File size: 480 → 450 lines (-30 lines)
- Replaced local utilities with shared versions (buildApiUrl, buildHeaders, fetchApi)
- Split encodeRosterBody into smaller helper functions for better readability
- All 113 tests passing (12 RosterRoute tests + full suite)

**Changes Made:**

1. ✅ Replaced local `buildHeaders` with shared version from `utils/http.ts`
2. ✅ Replaced local `buildRosterUrl` with shared `buildApiUrl`
3. ✅ Replaced all manual fetch calls with shared `fetchApi` utility
4. ✅ Split `encodeRosterBody` into helper functions:
   - `buildMetadataObject()` - Extract metadata fields
   - `buildReferenceImagesArray()` - Normalize reference images
   - `buildResolutionObject()` - Build observation resolution config
5. ✅ Removed unused imports and local utility functions

**Context:** [FRONTEND_AUDITS.md - useRoster Complex Encoding](apps/wp-context-alt-text/FRONTEND_AUDITS.md#4-userosterjs--moderate-complexity-432-lines)

**Current Issues:**

- `encodeRosterBody` function is 106 lines doing too much
- Duplicated URL building (can use shared `buildApiUrl` from Task 2.2)
- Confusing initial data logic

**Refactoring Steps:**

1. **Split `encodeRosterBody` into smaller functions:**

```typescript
const buildMetadata = (values: RosterFormValues) => { ... };
const buildReferenceImages = (values: RosterFormValues) => { ... };
const buildResolution = (values: RosterFormValues) => { ... };

const encodeRosterBody = (values: RosterFormValues): Record<string, unknown> => ({
  label: values.label,
  type: values.type,
  ...buildMetadata(values),
  reference_images: buildReferenceImages(values),
  resolve_observation: buildResolution(values),
});
```

2. **Replace `buildRosterUrl` with shared `buildApiUrl`** from utils/http.ts

3. **Clarify bootstrap logic** with explicit comments

**Benefits:**

- Each function has single responsibility
- Easier to test encoding logic
- Better readability
- Uses shared utilities

---

### Task 3.3: Simplify useWorkbenchMedia.ts

**Priority:** 🔴 Critical  
**Time:** 2 hours  
**Impact:** -123 lines (347 → 224)  
**Status:** [x] Complete ✅

**Context:** [FRONTEND_AUDITS.md - useWorkbenchMedia Extremely Brittle](apps/wp-context-alt-text/FRONTEND_AUDITS.md#5-useworkbenchmediats--extremely-brittle-347-lines)

**Results:**

- ✅ Reduced from 347 to 224 lines (35% reduction)
- ✅ All 12 App.test.tsx tests passing
- ✅ Removed 65-line origin resolution maze
- ✅ Simplified endpoint fallback logic
- ✅ Removed unnecessary `hasEndpoint` variable and conditionals
- ✅ Removed `shouldEnableRemoteFetch` wrapper (uses `shouldFetchRemote` directly)

**What was removed:**

1. **Origin resolution functions** (65 lines):

   - `resolveOriginCandidate()`, `isViableOrigin()`, `takeFirstOrigin()`
   - Attempted to parse 4 different origin sources (overly defensive)

2. **Complex fallback logic** (13 lines):

   - `window.ajaxurl` URL construction with try-catch
   - In production, PHP always provides endpoint via `rest_url()`
   - Simple relative path fallback works for all test scenarios

3. **Redundant endpoint checks** (45 lines total):
   - Removed `hasEndpoint` variable
   - Removed null checks in query function
   - Endpoint is always defined (config or fallback)

**Simplified endpoint resolution:**

```typescript
const endpoint = React.useMemo(() => {
  const configEndpoint = config.endpoints?.workbenchMedia;
  if (configEndpoint && configEndpoint.trim().length > 0) {
    return configEndpoint;
  }
  // Simple fallback: relative path (works everywhere)
  return "/wp-json/cat/v1/workbench/media";
}, [config.endpoints?.workbenchMedia]);
```

**Key Insight:** The complex 4-tier fallback logic was over-engineered for edge cases that don't occur in practice. Production WordPress always provides the endpoint when REST API is available.

---

### Task 3.4: Extract useRecognitionJob State Machine to Separate Files

**Priority:** 🟢 Medium  
**Time:** 1 hour  
**Impact:** Better code organization, -116 lines from main file  
**Status:** [x] Complete ✅

**Results:**

- Main hook file: 750 → 634 lines (-116 lines)
- Created `useRecognitionJob.types.ts` (71 lines)
- Created `useRecognitionJob.reducer.ts` (55 lines)
- All 113 tests passing

**Files Created:**

1. **`useRecognitionJob.types.ts`** (71 lines):

   - `RecognitionRequestError` class and error options
   - `JobState` discriminated union (5 state variants)
   - `JobAction` discriminated union (7 action types)

2. **`useRecognitionJob.reducer.ts`** (55 lines):

   - `initialJobState` constant
   - `jobReducer` pure function with exhaustive case handling

3. **Updated `useRecognitionJob.ts`** (634 lines):
   - Imports types and reducer from new files
   - Removed local type/reducer definitions
   - Focused on hook implementation and normalization

**Updated Test File:**

- `useRecognitionJob.test.tsx` updated to import `RecognitionRequestError` from `.types` file

**Benefits:**

- ✅ Better code organization (types, reducer, hook separated)
- ✅ Easier to test reducer in isolation
- ✅ Clearer file navigation
- ✅ Follows React best practices for complex hooks
- ✅ Main file reduced from 750 → 634 lines

**Context:** Task 3.1 completed successfully but left the file at 750 lines (from 585). The state machine types and reducer should be extracted to separate files following React best practices.

**Current State:**

- `useRecognitionJob.ts`: 750 lines (includes state machine types, reducer, and hook logic)

**Target Structure:**

```
js/admin/hooks/
├── useRecognitionJob.ts           # Main hook (300-350 lines)
├── useRecognitionJob.types.ts     # State machine types (80-100 lines)
└── useRecognitionJob.reducer.ts   # Reducer logic (100-120 lines)
```

**Files to Create:**

1. **`useRecognitionJob.types.ts`** - Extract type definitions:

   ```typescript
   // State machine types
   export type JobState =
     | { status: "idle" }
     | { status: "submitting"; attachmentIds: number[] }
     | {
         status: "polling";
         jobId: string;
         attempts: number;
         lastJob: RecognitionJobSummary;
       }
     | { status: "complete"; details: RecognitionJobDetails }
     | {
         status: "error";
         error: RecognitionRequestError;
         retryable: boolean;
         lastJob?: RecognitionJobSummary;
       };

   export type JobAction =
     | { type: "SUBMIT_START"; attachmentIds: number[] }
     | { type: "SUBMIT_SUCCESS"; jobId: string; summary: RecognitionJobSummary }
     | { type: "SUBMIT_ERROR"; error: RecognitionRequestError }
     | { type: "POLL_UPDATE"; details: RecognitionJobDetails }
     | { type: "POLL_COMPLETE"; details: RecognitionJobDetails }
     | { type: "POLL_ERROR"; error: RecognitionRequestError }
     | { type: "RESET" };

   // Hook return type
   export interface UseRecognitionJobReturn {
     canSubmit: boolean;
     triggerRecognition: (attachmentIds: number[]) => Promise<void>;
     isSubmitting: boolean;
     isPolling: boolean;
     lastJob: RecognitionJobSummary | null;
     jobDetails: RecognitionJobDetails | null;
     status: "idle" | "processing" | "complete" | "error";
     error: RecognitionRequestError | null;
     reset: () => void;
     refetchJob: () => Promise<void>;
   }
   ```

2. **`useRecognitionJob.reducer.ts`** - Extract reducer logic:

   ```typescript
   import type { JobState, JobAction } from "./useRecognitionJob.types";

   export const initialJobState: JobState = { status: "idle" };

   export function jobReducer(state: JobState, action: JobAction): JobState {
     switch (action.type) {
       case "SUBMIT_START":
         return {
           status: "submitting",
           attachmentIds: action.attachmentIds,
         };

       case "SUBMIT_SUCCESS":
         return {
           status: "polling",
           jobId: action.jobId,
           attempts: 0,
           lastJob: action.summary,
         };

       case "SUBMIT_ERROR":
         return {
           status: "error",
           error: action.error,
           retryable: true,
         };

       case "POLL_UPDATE":
         if (state.status !== "polling") return state;
         return {
           ...state,
           attempts: state.attempts + 1,
         };

       case "POLL_COMPLETE":
         if (state.status !== "polling") return state;
         return {
           status: "complete",
           details: action.details,
         };

       case "POLL_ERROR":
         return {
           status: "error",
           error: action.error,
           retryable: state.status === "polling",
           lastJob: state.status === "polling" ? state.lastJob : undefined,
         };

       case "RESET":
         return { status: "idle" };

       default:
         return state;
     }
   }
   ```

3. **Update `useRecognitionJob.ts`**:
   - Remove type definitions (import from `.types`)
   - Remove reducer function (import from `.reducer`)
   - Keep hook logic and normalization helpers
   - Target: 300-350 lines

**Benefits:**

- ✅ Each file under 400 lines (maintainability threshold)
- ✅ Clear separation of concerns (types, reducer logic, hook logic)
- ✅ Easier to test reducer in isolation
- ✅ Better code navigation (types and reducer are explicitly named files)
- ✅ Follows React community best practices for complex hooks

**Verification:**

```bash
cd apps/wp-context-alt-text
npm test -- useRecognitionJob.test.tsx
npm test -- RecognitionActions.test.tsx
```

---

### Task 3.5: Simplify useRecognitionObservations

**Priority:** 🔴 Critical  
**Time:** 30 minutes  
**Impact:** -12 lines (458→446), reduced duplication  
**Status:** [x] Complete ✅

**Results:**

- File size: 458 → 446 lines (-12 lines)
- Replaced duplicate primitive normalizers with shared utilities
- Updated to use shared `buildHeaders` function
- All 113 tests passing
- Improved code reuse and consistency

**Analysis:**
Unlike `useRecognitionJob`, this hook doesn't need `useReducer` because:

- No complex local state management (only uses React Query)
- No race conditions or impossible states to prevent
- Purely a data-fetching hook with straightforward logic

**Changes Made:**

1. **Removed duplicate primitive normalizers:**

   - `toFiniteNumber` → imported from `utils/normalization/primitives`
   - `toNumberOrNull` → imported from `utils/normalization/primitives`
   - `toStringOrNull` → imported from `utils/normalization/primitives`

2. **Updated HTTP utilities:**

   - Replaced local `buildHeaders` with shared version from `utils/http`
   - Updated all function calls to use shared utilities

3. **Kept observation-specific normalizers local:**
   - Observation normalizers use different data structures than job normalizers
   - These are endpoint-specific and should remain in the hook
   - Examples: `normalizeCandidate`, `normalizeObservationDetails`, `normalizeAttachment`

**Verification:**

```bash
cd apps/wp-context-alt-text
npm test -- useRecognitionObservations.test.tsx
npm test -- --run  # Full test suite (113 tests passing)
```

---

### Task 3.6: Extract Recognition Normalization Utilities

**Priority:** 🔴 Critical  
**Time:** 1 hour  
**Impact:** -301 lines (634→333), enables reuse in Task 3.5  
**Status:** [x] Complete ✅

**Results:**

- Extracted 7 interfaces and 8 normalization functions to `utils/normalization/recognition.ts`
- File size: 634 → 333 lines (-301 lines, 47% reduction)
- All 113 tests passing
- Normalization utilities now shared and reusable
- Added re-exports for backward compatibility

**Extracted to:** `js/admin/utils/normalization/recognition.ts`

**Functions Extracted:**

- `normalizeObservationStatus()` - Status field normalization
- `normalizeCandidates()` - Array of face/brand candidates
- `normalizeMatch()` - Individual match with confidence
- `normalizeRoster()` - Roster metadata (counts, names)
- `normalizeObservationRecord()` - Full observation with sophisticated confidence resolution
- `normalizeAttachmentSummaries()` - Array of attachment observations
- `normalizeJobDetails()` - Complete job response normalization
- `maybeParseJson()` - HTTP utility with dynamic import

**Types Extracted:**

- `RecognitionJobSummary` - Polling summary interface
- `RecognitionObservationMatch` - Individual match details
- `RecognitionObservationRoster` - Roster metadata
- `RecognitionObservationCandidate` - Face/brand candidate
- `RecognitionObservationRecord` - Full observation record
- `RecognitionAttachmentObservations` - Attachment with observations
- `RecognitionJobDetails` - Complete job details

**Context:** useRecognitionJob.ts previously contained ~301 lines of domain-specific normalization logic that needed to be shared utilities for reuse in `useRecognitionObservations.ts` (Task 3.5).

**Current Issues:**

- Normalization functions are duplicated in `useRecognitionObservations.ts`
- Cannot be reused by other hooks/components
- Makes `useRecognitionJob.ts` harder to read and test
- Violates DRY principle

**Create:** `js/admin/utils/normalization/recognition.ts`

**Functions to Extract:**

```typescript
// Status normalization
export const normalizeObservationStatus = (
    value: unknown,
): RecognitionObservationRecord["status"] => { ... }

// Complex object normalization
export const normalizeCandidates = (
    candidates: unknown
): RecognitionObservationCandidate[] => { ... }

export const normalizeMatch = (
    match: unknown
): RecognitionObservationMatch => { ... }

export const normalizeRoster = (
    roster: unknown
): RecognitionObservationRoster => { ... }

export const normalizeObservationRecord = (
    observation: unknown
): RecognitionObservationRecord | null => { ... }

export const normalizeAttachmentSummaries = (
    input: unknown
): RecognitionAttachmentObservations[] => { ... }

export const normalizeJobDetails = (
    payload: Record<string, unknown>,
    fallbackId?: string | null
): RecognitionJobDetails => { ... }

// HTTP helpers
export const maybeParseJson = async (
    response: Response
): Promise<unknown> => { ... }
```

**Update Files:**

1. **`js/admin/utils/normalization/recognition.ts`** (new file, ~240 lines)

   - Move all normalization functions from `useRecognitionJob.ts`
   - Import primitive normalizers from `primitives.ts`
   - Export all functions for reuse

2. **`js/admin/hooks/useRecognitionJob.ts`** (update)

   - Import normalization functions from `utils/normalization/recognition`
   - Remove local normalization code (lines 180-415)
   - File size: 550 → 315 lines

3. **`js/admin/hooks/useRecognitionObservations.ts`** (future update in Task 3.5)
   - Will use shared normalization utilities
   - Eliminates duplication

**Benefits:**

- ✅ Normalization logic can be reused in `useRecognitionObservations` (Task 3.5)
- ✅ Can be tested independently
- ✅ Reduces `useRecognitionJob` from 550 → 315 lines
- ✅ Aligns with Phase 2 normalization structure
- ✅ Easier to maintain and update normalization rules

**Dependencies:**

- Requires: `js/admin/utils/normalization/primitives.ts` (already exists from Phase 2)
- Enables: Task 3.5 (useRecognitionObservations refactor)

**Verification:**

```bash
cd apps/wp-context-alt-text
npm test -- useRecognitionJob.test.tsx
npm test -- RecognitionActions.test.tsx
npm test -- --run  # Full test suite
```

---

### Task 3.7: Extract Recognition Type Definitions (Polish)

**Priority:** 🟢 Low (Polish task)  
**Time:** 30 minutes  
**Impact:** -110 lines (315→205), better organization  
**Status:** [ ] Not Started  
**Deferred to:** Phase 10 (Polish)

**Context:** After extracting state machine and normalization utilities, the remaining type definitions (lines 1-110) could be moved to a shared types file for better organization.

**Current Issues:**

- Type definitions mixed with hook implementation
- Cannot be easily imported by other components
- Makes file navigation harder

**Create:** `js/admin/types/recognition.ts`

**Types to Extract:**

```typescript
// Core domain types
export interface RecognitionJobSummary { ... }
export interface RecognitionObservationMatch { ... }
export type RecognitionObservationRoster = { ... } | null;
export interface RecognitionObservationCandidate { ... }
export interface RecognitionObservationRecord { ... }
export interface RecognitionAttachmentObservations { ... }
export interface RecognitionJobDetails { ... }

// Error class
export class RecognitionRequestError extends Error { ... }
```

**Update Files:**

1. **`js/admin/types/recognition.ts`** (new file, ~110 lines)

   - Move all type definitions
   - Export all types and classes

2. **`js/admin/hooks/useRecognitionJob.ts`** (update)

   - Import types from `@/admin/types/recognition`
   - Remove local type definitions
   - File size: 315 → 205 lines

3. **Other files using recognition types** (update imports)
   - `useRecognitionObservations.ts`
   - `RecognitionActions.tsx`
   - Any other components using these types

**Benefits:**

- ✅ Clear separation: types vs implementation
- ✅ Types can be imported anywhere
- ✅ Reduces `useRecognitionJob` to ~205 lines (original target)
- ✅ Better code organization and discoverability
- ✅ Follows React/TypeScript best practices

**Note:** This is a polish task and can be deferred to Phase 10. The functional improvements are already achieved by Tasks 3.4 and 3.6.

**Verification:**

```bash
cd apps/wp-context-alt-text
npm test -- --run  # Full test suite
```

---

## 🟡 PHASE 4: High Priority - PHP Utilities (3 hours)

**Goal:** Reduce duplication in PHP backend

**Progress Tracker:**

- [x] Task 4.1: Extract PHP URL Validation Helper
- [x] Task 4.2: Create AbstractSpaPage Base Class
- [x] Task 4.3: Extract REST URL Helper in Admin.php
- [x] Task 4.4: Split Admin::get_config() Method

---

### Task 4.1: Extract PHP URL Validation Helper

**Priority:** 🟡 High  
**Time:** 30 minutes  
**Impact:** -15 lines  
**Status:** [ ] Not Started

**Context:** [PHP_AUDITS.md - SettingsRepository Issue 2](apps/wp-context-alt-text/PHP_AUDITS.md#--issue-2-url-validation-duplicated)

**File:** `src/Shared/Config/SettingsRepository.php`

**Extract to:** `src/Shared/Utils/ValidationHelpers.php`

```php
<?php
declare(strict_types=1);

namespace ContextAltText\Shared\Utils;

final class ValidationHelpers
{
    public static function sanitizeUrl(string $url, bool $stripTrailingSlash = false): string
    {
        $url = trim($url);
        if ($url === '' || filter_var($url, FILTER_VALIDATE_URL) === false) {
            return '';
        }
        return $stripTrailingSlash ? rtrim($url, '/') : $url;
    }

    public static function sanitizeTimeout(int $value, int $min, int $max): int
    {
        return max($min, min($max, $value));
    }
}
```

**Update:** `SettingsRepository.php` to use helper (lines 167-169, 186-189)

---

### Task 4.2: Create AbstractSpaPage Base Class

**Priority:** 🟡 High  
**Time:** 1 hour  
**Impact:** -40 lines  
**Status:** [x] Complete

**Context:** [PHP_AUDITS.md - Minimal Page Shells](apps/wp-context-alt-text/PHP_AUDITS.md#--issue-1-minimal-page-shells-3-files)

**Affected Files (3):**

- `src/Admin/AltTextWorkbenchPage.php` (22 lines → 36 lines with docblock)
- `src/Admin/AccountCenterPage.php` (19 lines → 36 lines with docblock)
- `src/Admin/AutomationQueuePage.php` (19 lines → 36 lines with docblock)

**Created:** `src/Admin/AbstractSpaPage.php` (62 lines)

The abstract base class provides:

- Template method `render()` with common HTML structure
- Abstract methods for customization: `getRootId()`, `getRootClass()`, `getPageTitle()`, `getLoadingMessage()`
- Proper WordPress escaping via `esc_attr()` and `esc_html_e()`

All 3 page classes now extend `AbstractSpaPage` and implement the abstract methods. While each file is slightly longer due to comprehensive docblocks, the duplication has been eliminated and maintainability improved.

**Verification:** All 163 PHP tests passing (653 assertions)

---

### Task 4.3: Extract REST URL Helper in Admin.php

**Priority:** 🟡 High  
**Time:** 30 minutes  
**Impact:** -20 lines  
**Status:** [x] Complete

**Context:** [PHP_AUDITS.md - Admin.php Issue 2](apps/wp-context-alt-text/PHP_AUDITS.md#--issue-2-duplicate-endpoint-url-construction)

**File:** `src/Admin/Admin.php`

**Created helper method:**

```php
private function get_rest_url(string $path): string
{
    return function_exists('rest_url') ? rest_url($path) : '';
}
```

**Updated 7 locations** where REST URLs were being constructed with duplicate `function_exists('rest_url')` checks:

1. `get_config()`: Coverage endpoint
2. `get_config()`: Workbench endpoint
3. `get_config()`: Recognition analyze endpoint
4. `get_config()`: Recognition job endpoint
5. `get_config()`: Observations endpoints (2 locations)
6. `get_config()`: Retry endpoint
7. `get_config()`: Roster endpoints (2 locations)
8. `get_settings_endpoints()`: Recognition settings endpoints (2 locations)

All conditional `&& function_exists('rest_url')` checks removed from if statements, simplifying the logic. Empty string fallback now centralized in the helper method.

**Verification:** All 163 PHP tests passing (653 assertions)

---

### Task 4.4: Split Admin::get_config() Method

**Priority:** 🟡 High  
**Time:** 1 hour  
**Impact:** Better organization (improved readability and maintainability)  
**Status:** [x] Complete

**Context:** [PHP_AUDITS.md - Admin.php Issue 1](apps/wp-context-alt-text/PHP_AUDITS.md#--issue-1-large-method---get_config-90-lines)

**File:** `src/Admin/Admin.php`

**Refactored the 90-line `get_config()` method by extracting endpoint configuration logic:**

**Created:**

- `get_endpoint_config()`: New private method that builds all REST API endpoint URLs (94 lines)
  - Handles feature flag checks for conditional endpoints
  - Includes debug logging for recognition/roster flags
  - Returns array of 11 endpoint URLs

**Updated:**

- `get_config()`: Simplified from 78 lines → 14 lines (clean orchestration method)
  - Now delegates to three focused methods:
    - `get_feature_flags_config()` (already existed)
    - `get_endpoint_config()` (newly extracted)
    - `get_settings_endpoints()` (already existed)
  - Clean, readable structure showing exactly what config contains

**Benefits:**

- ✅ Single Responsibility: Each method has one clear purpose
- ✅ Improved Readability: `get_config()` now reads like a table of contents
- ✅ Better Testability: Endpoint logic can be tested in isolation
- ✅ Easier Maintenance: Endpoint changes isolated to one method

**Verification:** All 163 PHP tests passing (653 assertions)

---

## 🟡 PHASE 5: High Priority - Frontend Component Improvements (4 hours)

**Goal:** Break down large components and ensure architecture compliance

**Progress Tracker:**

- [ ] Task 5.1: Audit components against new architecture standards (RosterRoute.tsx, App.tsx, WorkbenchApp.tsx)
- [ ] Task 5.2: Refactor RosterRoute.tsx to comply with architecture limits (2,543 → ~400 lines per file)
- [ ] Task 5.3: Refactor App.tsx to comply with architecture limits (563 → ~300 lines)
- [ ] Task 5.4: Extract shared UI components to component library

**Architecture Standards Reference:**

- [Frontend Component Architecture Rules](docs/architecture/rules/instructions.md) (lines 79-194)
- [Component Architecture Patterns Guide](docs/architecture/frontend-uml/component-architecture-patterns.md)
- [RosterRoute Refactoring Roadmap](docs/architecture/frontend-uml/roster-route-refactoring-roadmap.mmd)
- [Anti-Patterns vs Ideal Patterns](docs/architecture/frontend-uml/anti-patterns-vs-ideal.mmd)

**Key Limits to Enforce:**

- Max 300 lines per component file (400 for route components)
- Max 5 `useState` hooks per component
- Max 3 `useEffect` hooks per component
- Extract JSX blocks over 50 lines
- No prop drilling beyond 2 levels

---

### Task 5.1: Audit Components Against New Architecture Standards

**Priority:** 🟡 High  
**Time:** 1 hour  
**Impact:** Identify violations and create refactoring plan  
**Status:** [ ] Not Started

**Scope:** Audit all major components against new [Frontend Component Architecture Rules](docs/architecture/rules/instructions.md)

**Components to Audit:**

| Component                      | Current Lines | Expected Violations                      |
| ------------------------------ | ------------- | ---------------------------------------- |
| `RosterRoute.tsx`              | 2,543         | 🔴 Critical (14+ useState, 6+ useEffect) |
| `App.tsx`                      | 563           | 🟠 High (8+ useState, 5+ useEffect)      |
| `WorkbenchApp.tsx`             | 274           | 🟡 Medium (check hook counts)            |
| `RecognitionSettingsPanel.tsx` | ?             | 🟡 Medium (complex state)                |
| `DashboardHeader.tsx`          | ?             | 🟢 Low (likely OK)                       |

**Analysis Checklist:**

For each component, check:

1. **Component Size**:

   - [ ] Total lines < 300 (or < 400 for routes)
   - [ ] Embedded components extracted
   - [ ] JSX blocks < 50 lines

2. **State Management**:

   - [ ] `useState` count < 5
   - [ ] `useEffect` count < 3
   - [ ] No props mirrored in state
   - [ ] No derived values in state

3. **Anti-Patterns**:

   - [ ] No effect chains
   - [ ] No prop drilling beyond 2 levels
   - [ ] No manual data fetching state

4. **Extraction Opportunities**:
   - [ ] Can extract custom hooks?
   - [ ] Can extract sub-components?
   - [ ] Can use React Query?
   - [ ] Can use `useReducer`?

**Deliverable:** Create `COMPONENT_ARCHITECTURE_AUDIT.md` with:

- Violation matrix (component × limits)
- Priority ranking (Critical → Low)
- Refactoring estimates (hours per component)
- Dependency graph (which components to refactor first)

---

### Task 5.2: Refactor RosterRoute.tsx to Comply with Architecture Limits

**Priority:** � Critical  
**Time:** 6-8 hours  
**Impact:** 2,543 → ~400 lines per file, eliminate 14+ useState, 6+ useEffect  
**Status:** [ ] Not Started

**Current Violations:**

- **Line count**: 2,543 lines ❌ (exceeds 400-line route limit by 536%)
- **useState count**: 14+ hooks ❌ (exceeds 5-hook limit by 180%)
- **useEffect count**: 6+ hooks ❌ (exceeds 3-effect limit by 100%)
- **Embedded components**: 4+ components ❌ (should be extracted)

**Refactoring Strategy:**

Follow the [RosterRoute Refactoring Roadmap](docs/architecture/frontend-uml/roster-route-refactoring-roadmap.mmd):

**Phase 1: Extract Data Hooks** (2 hours)

Create separate hooks for data operations:

```
js/admin/hooks/
├── useRosterTable.ts         # List/filter/pagination (~200 lines)
├── useRosterForm.ts          # Create/edit form state (~150 lines)
└── useObservationDialog.ts   # Observation management (~150 lines)
```

**Phase 2: Extract UI Components** (3 hours)

Break down large JSX blocks into components:

```
js/components/roster/
├── RosterRoute.tsx           # Main route (~400 lines) ✅
├── RosterTable.tsx           # Table component (~250 lines)
├── RosterForm.tsx            # Form component (~200 lines)
├── RosterFormFields.tsx      # Form fields (~150 lines)
├── ObservationDialog.tsx     # Observation UI (~200 lines)
├── ImageUploadModal.tsx      # Image upload (~150 lines)
└── shared/
    ├── RosterEntryCard.tsx   # Card component (~100 lines)
    ├── StatusBadge.tsx       # Status indicator (~50 lines)
    └── AvatarUpload.tsx      # Avatar upload (~100 lines)
```

**Phase 3: Extract Utilities** (1 hour)

Move business logic to utilities:

```
js/admin/utils/roster/
├── validation.ts             # Form validation (~80 lines)
├── normalization.ts          # Data normalization (~100 lines)
└── calculations.ts           # Stats/metrics (~60 lines)
```

**Phase 4: Consolidate State** (2 hours)

Replace multiple `useState` with `useReducer`:

```typescript
// Before: 14+ useState hooks ❌
const [selection, setSelection] = useState({});
const [assigningId, setAssigningId] = useState(null);
const [searchInput, setSearchInput] = useState("");
const [search, setSearch] = useState(null);
const [page, setPage] = useState(1);
const [perPage, setPerPage] = useState(20);
const [editing, setEditing] = useState(null);
const [isSubmitting, setIsSubmitting] = useState(false);
const [statusFilter, setStatusFilter] = useState(null);
const [draftValues, setDraftValues] = useState(null);
const [observationPrompt, setObservationPrompt] = useState(null);
// ... 3+ more

// After: 1-2 useReducer + React Query ✅
const [tableState, dispatchTable] = useReducer(tableReducer, initialTableState);
const [formState, dispatchForm] = useReducer(formReducer, initialFormState);
const { data, isLoading } = useRosterTable(tableState.filters);
const { mutate } = useRosterForm();
```

**Phase 5: Eliminate Effects** (1 hour)

Replace `useEffect` with derived state and event handlers:

```typescript
// Before: 6+ useEffect hooks ❌
useEffect(() => setSearch(searchInput), [searchInput]);
useEffect(() => refetch(), [page, perPage]);
useEffect(() => /* sync state */, [data]);
// ... 3+ more

// After: 0 useEffect hooks ✅
const debouncedSearch = useDebouncedValue(searchInput, 500);
// React Query auto-refetches when dependencies change
const { data } = useQuery({
    queryKey: ['roster', { page, perPage, search: debouncedSearch }],
    queryFn: fetchRoster,
});
```

**Success Criteria:**

- ✅ RosterRoute.tsx < 400 lines
- ✅ All extracted components < 300 lines
- ✅ useState count < 5 per component
- ✅ useEffect count < 3 per component
- ✅ All tests passing
- ✅ No functionality lost

**Estimated Result:**

```
Before: 1 file × 2,543 lines = 2,543 lines
After:  8-10 files × ~200-400 lines = ~2,200 lines
Net:    -343 lines + better organization
```

---

### Task 5.3: Refactor App.tsx to Comply with Architecture Limits

**Priority:** 🟠 High  
**Time:** 3 hours  
**Impact:** 563 → ~300 lines, eliminate 8+ useState, 5+ useEffect  
**Status:** [ ] Not Started

**Current Violations:**

- **Line count**: 563 lines ❌ (exceeds 400-line route limit by 41%)
- **useState count**: 8+ hooks ❌ (exceeds 5-hook limit by 60%)
- **useEffect count**: 5+ hooks ❌ (exceeds 3-effect limit by 67%)

**Refactoring Strategy:**

**Phase 1: Extract Router** (30 minutes)

```
js/admin/app/
├── App.tsx                   # Main app shell (~150 lines) ✅
└── AdminRouter.tsx           # Route definitions (~200 lines) ✅
```

**Phase 2: Extract Route Components** (2 hours)

```
js/admin/app/routes/
├── DashboardRoute.tsx        # Dashboard logic (~250 lines) ✅
├── WorkbenchRoute.tsx        # Workbench logic (~200 lines) ✅
└── shared/
    ├── RouteErrorBoundary.tsx  # Error handling (~80 lines)
    └── RouteLoader.tsx         # Loading states (~60 lines)
```

**Phase 3: Extract Utilities** (30 minutes)

```
js/admin/utils/app/
├── csvExport.ts              # CSV generation (~100 lines)
├── searchNormalization.ts    # Search utilities (~80 lines)
└── paginationHelpers.ts      # Pagination logic (~60 lines)
```

**Success Criteria:**

- ✅ App.tsx < 200 lines (app shell only)
- ✅ All route components < 300 lines
- ✅ useState count < 5 per component
- ✅ useEffect count < 3 per component
- ✅ All tests passing

---

### Task 5.4: Extract Shared UI Components to Component Library

**Priority:** 🟡 Medium  
**Time:** 3 hours  
**Impact:** Enable reuse, reduce duplication  
**Status:** [ ] Not Started

````

**Update:** `RecognitionSettingsPanel.tsx` to use hook

---

## 🟡 PHASE 6: High Priority - Cross-Stack Alignment (6 hours)

**Goal:** Better symmetry between frontend and backend

**Progress Tracker:**

- [ ] Task 6.1: Align Validation Logic (Frontend ↔ PHP)
- [ ] Task 6.2: Align Sanitization Patterns
- [ ] Task 6.3: Create Shared TypeScript/PHP Type Definitions

---

### Task 6.1: Align Validation Logic (Frontend ↔ PHP)

**Priority:** 🟡 High
**Time:** 2 hours
**Impact:** Consistent validation rules
**Status:** [ ] Not Started

**Current State:**

- **Frontend:** URL/timeout validation in `RecognitionSettingsPanel.tsx` (lines 9-28)
- **PHP:** URL/timeout validation in `SettingsRepository.php` (lines 167-169, 175-176)

**Goal:** Ensure validation rules are identical

**Actions:**

1. **Create shared validation constants** (in both codebases):

```typescript
// js/admin/constants/validation.ts
export const VALIDATION = {
  TIMEOUT_MS: {
    MIN: 1000,
    MAX: 120000,
    DEFAULT: 15000,
  },
  URL: {
    PATTERN: /^(https?:)\/\//i,
    REQUIRED_SCHEMES: ["http", "https"],
  },
} as const;
````

```php
// src/Shared/Constants/ValidationConstants.php
final class ValidationConstants
{
    public const MIN_TIMEOUT_MS = 1000;
    public const MAX_TIMEOUT_MS = 120000;
    public const DEFAULT_TIMEOUT_MS = 15000;
}
```

2. **Document validation rules** in shared contract file

3. **Add contract tests** to verify frontend/backend alignment

---

### Task 6.2: Align Sanitization Patterns

**Priority:** 🟡 High  
**Time:** 2 hours  
**Impact:** Consistent data handling  
**Status:** [ ] Not Started

**Current State:**

- **Frontend:** Normalization functions scattered across hooks
- **PHP:** Sanitization in multiple repositories (RecognitionObservationRepository, RosterService, Api.php)

**Goal:** Mirror sanitization approaches

**Pattern to Follow:**

```typescript
// Frontend: js/admin/utils/normalization/primitives.ts
export const toStringOrNull = (value: unknown): string | null => {
  if (typeof value === "string" && value.trim() !== "") {
    return value.trim();
  }
  return null;
};
```

```php
// PHP: src/Shared/Utils/SanitizationHelpers.php
public static function toStringOrNull($value): ?string
{
    if (!is_string($value) && !is_numeric($value)) {
        return null;
    }
    $sanitized = sanitize_text_field((string) $value);
    return $sanitized !== '' ? $sanitized : null;
}
```

**Benefits:**

- Predictable data shape across stack
- Easier debugging (same patterns)
- Reduces contract test failures

---

### Task 6.3: Create Shared TypeScript/PHP Type Definitions

**Priority:** 🟡 High  
**Time:** 2 hours  
**Impact:** Better contract alignment  
**Status:** [ ] Not Started

**Context:** Prevent drift between frontend types and PHP DTOs

**Create:** `packages/shared-contracts/types/`

```
shared-contracts/
├── types/
│   ├── recognition.types.ts       # TypeScript
│   ├── recognition.types.php.md   # PHP equivalent (documented)
│   ├── roster.types.ts
│   ├── roster.types.php.md
│   ├── workbench.types.ts
│   └── workbench.types.php.md
├── validation/
│   ├── recognition.rules.json     # Shared validation rules
│   └── roster.rules.json
└── tests/
    └── contract-alignment.test.ts # Verify TS/PHP alignment
```

**Example:**

```typescript
// recognition.types.ts
export interface RecognitionJobSummary {
  id: string;
  status: "pending" | "processing" | "complete" | "error";
  attachmentIds: number[];
  createdAt: number;
  updatedAt: number;
}
```

```php
// Corresponding PHP (documented in recognition.types.php.md)
/**
 * @phpstan-type RecognitionJobSummary array{
 *   id: string,
 *   status: 'pending'|'processing'|'complete'|'error',
 *   attachmentIds: int[],
 *   createdAt: int,
 *   updatedAt: int
 * }
 */
```

---

## 🟢 PHASE 7: Medium Priority - PHP Component Improvements (4 hours)

**Progress Tracker:**

- [ ] Task 7.1: Refactor WorkbenchMediaResolver.php
- [ ] Task 7.2: Refactor useRecognitionObservations.ts
- [ ] Task 7.3: Refactor useRoster.ts

---

### Task 7.1: Refactor WorkbenchMediaResolver.php

**Priority:** 🟢 Medium  
**Time:** 2 hours  
**Impact:** -50 lines (245 → ~195)  
**Status:** [ ] Not Started

**Context:** [PHP_AUDITS.md - WorkbenchMediaResolver](apps/wp-context-alt-text/PHP_AUDITS.md#workbenchmediaresolverphp--good-245-lines)

**Extract methods:**

```php
// Extract from fetch() (40 lines → 3 focused methods)
private function buildQueryArgs(int $page, int $perPage, string $status, ?string $search): array
private function executeQuery(array $queryArgs): WP_Query
private function formatQueryResults(WP_Query $query): array

// Extract from mapPosts() (50 lines → single post mapping)
private function mapPost(WP_Post $post): ?array

// Extract from buildRecognitionMetadata() (55 lines → smaller functions)
private function extractMatchedRoster(array $observations): ?array
private function determineRecognitionStatus(array $summary): string
private function extractScalarString(array $data, string $key, ?string $fallbackKey = null): ?string
```

---

### Task 7.2: Refactor useRecognitionObservations.ts

**Priority:** 🟢 Medium  
**Time:** 1.5 hours  
**Impact:** -193 lines (443 → ~250)  
**Status:** [ ] Not Started

**Context:** [FRONTEND_AUDITS.md - useRecognitionObservations](apps/wp-context-alt-text/FRONTEND_AUDITS.md#3-userecognitionobservationsts--moderate-bloat-443-lines)

**Actions:**

1. Use shared normalization utilities (from Task 2.1)
2. Use shared URL builder (from Task 2.2)
3. Simplify complex normalization (extract to smaller functions)

---

### Task 7.3: Refactor useRoster.ts

**Priority:** 🟢 Medium  
**Time:** 30 minutes  
**Impact:** -152 lines (432 → ~280)  
**Status:** [ ] Not Started

**Context:** [FRONTEND_AUDITS.md - useRoster](apps/wp-context-alt-text/FRONTEND_AUDITS.md#4-userosterTS--moderate-complexity-432-lines)

**Split `encodeRosterBody` function:**

```typescript
// OLD: 106-line monster function
const encodeRosterBody = (values: RosterFormValues): Record<string, unknown> => { ... }

// NEW: Focused functions
const encodeBasicFields = (values: RosterFormValues) => { ... }
const encodeAvatarField = (values: RosterFormValues) => { ... }
const encodeReferenceImages = (values: RosterFormValues) => { ... }
const encodeMetadata = (values: RosterFormValues) => { ... }

const encodeRosterBody = (values: RosterFormValues): Record<string, unknown> => {
  return {
    ...encodeBasicFields(values),
    ...encodeAvatarField(values),
    ...encodeReferenceImages(values),
    ...encodeMetadata(values),
  };
}
```

---

## 🟢 PHASE 8: Medium Priority - Test Coverage Improvements (6-8 hours)

**Goal:** Increase test coverage and confidence, especially for refactored code

**Context:** After refactoring, ensure all new utilities and simplified components have comprehensive test coverage. Current coverage is good but can be enhanced in key areas.

**Progress Tracker:**

- [ ] Task 8.1: Add Tests for New Shared Utilities
- [ ] Task 8.2: Add Tests for PHP Validation Helpers
- [ ] Task 8.3: Add Integration Tests for Refactored Hooks
- [ ] Task 8.4: Add Contract Tests for Frontend/Backend Alignment
- [ ] Task 8.5: Measure and Document Coverage Baselines
- [ ] Task 8.6: Add Missing Edge Case Tests

---

### Task 8.1: Add Tests for New Shared Utilities

**Priority:** 🟢 Medium  
**Time:** 2 hours  
**Impact:** Prevents regressions in commonly-used code  
**Status:** [ ] Not Started

**Context:** New utilities created in Phase 2 need comprehensive tests

**Files to Test:**

1. **`js/admin/utils/normalization/primitives.ts`** - New file from Task 2.1

   ```typescript
   // Test coverage needed for:
   describe("toFiniteNumber", () => {
     it("should convert valid numbers", () => {
       expect(toFiniteNumber("42")).toBe(42);
       expect(toFiniteNumber(42.5)).toBe(42.5);
     });

     it("should return fallback for invalid values", () => {
       expect(toFiniteNumber("invalid", 10)).toBe(10);
       expect(toFiniteNumber(NaN, 5)).toBe(5);
       expect(toFiniteNumber(Infinity, 0)).toBe(0);
     });
   });

   describe("toStringOrNull", () => {
     it("should return trimmed string or null", () => {
       expect(toStringOrNull("  hello  ")).toBe("hello");
       expect(toStringOrNull("")).toBeNull();
       expect(toStringOrNull(null)).toBeNull();
       expect(toStringOrNull(undefined)).toBeNull();
     });
   });
   // ... test all 7 primitive functions
   ```

2. **`js/admin/utils/normalization/recognition.ts`** - New file from Task 2.1

   ```typescript
   describe("normalizeObservation", () => {
     it("should normalize valid observation data", () => {
       const input = {
         id: "123",
         jobId: "job-456",
         confidence: "0.95",
         // ... other fields
       };
       const result = normalizeObservation(input);
       expect(result.id).toBe("123");
       expect(result.confidence).toBe(0.95);
     });

     it("should handle missing optional fields", () => {
       const minimal = { id: "123", jobId: "job-456" };
       expect(() => normalizeObservation(minimal)).not.toThrow();
     });
   });
   ```

3. **`js/admin/utils/http.ts`** - Enhanced in Task 2.2

   ```typescript
   describe("buildApiUrl", () => {
     it("should build URL with query params", () => {
       const url = buildApiUrl("/api/roster", {
         page: 1,
         search: "test",
         enabled: true,
       });
       expect(url).toContain("page=1");
       expect(url).toContain("search=test");
       expect(url).toContain("enabled=true");
     });

     it("should skip null/undefined params", () => {
       const url = buildApiUrl("/api/roster", {
         page: 1,
         search: null,
         type: undefined,
       });
       expect(url).not.toContain("search");
       expect(url).not.toContain("type");
     });
   });

   describe("fetchApi", () => {
     it("should handle successful response", async () => {
       // Use MSW or fetch mock
       const result = await fetchApi("/api/test", {
         method: "GET",
       });
       expect(result).toBeDefined();
     });

     it("should handle error response", async () => {
       await expect(
         fetchApi("/api/error", { method: "GET" })
       ).rejects.toThrow();
     });
   });
   ```

**Test Coverage Goals:**

- Primitive normalization: 100% (simple, pure functions)
- Domain normalization: 90%+ (test all paths)
- HTTP utilities: 85%+ (mock external calls)

---

### Task 8.2: Add Tests for PHP Validation Helpers

**Priority:** 🟢 Medium  
**Time:** 1 hour  
**Impact:** Ensures validation logic is bulletproof  
**Status:** [ ] Not Started

**Context:** New PHP utilities from Task 4.1 need tests

**Create:** `tests/Shared/Utils/ValidationHelpersTest.php`

```php
<?php
declare(strict_types=1);

namespace ContextAltText\Tests\Shared\Utils;

use ContextAltText\Shared\Utils\ValidationHelpers;
use PHPUnit\Framework\TestCase;

final class ValidationHelpersTest extends TestCase
{
    /**
     * @dataProvider urlProvider
     */
    public function testSanitizeUrl(string $input, bool $stripTrailing, string $expected): void
    {
        $result = ValidationHelpers::sanitizeUrl($input, $stripTrailing);
        $this->assertSame($expected, $result);
    }

    public function urlProvider(): array
    {
        return [
            // Valid URLs
            ['https://example.com', false, 'https://example.com'],
            ['https://example.com/', true, 'https://example.com'],
            ['http://localhost:8080/path', false, 'http://localhost:8080/path'],

            // Invalid URLs
            ['not-a-url', false, ''],
            ['', false, ''],
            ['   ', false, ''],

            // Edge cases
            ['  https://example.com  ', false, 'https://example.com'],
            ['https://example.com///', true, 'https://example.com'],
        ];
    }

    /**
     * @dataProvider timeoutProvider
     */
    public function testSanitizeTimeout(int $value, int $min, int $max, int $expected): void
    {
        $result = ValidationHelpers::sanitizeTimeout($value, $min, $max);
        $this->assertSame($expected, $result);
    }

    public function timeoutProvider(): array
    {
        return [
            // Within range
            [5000, 1000, 10000, 5000],

            // Below minimum
            [500, 1000, 10000, 1000],
            [0, 1000, 10000, 1000],

            // Above maximum
            [15000, 1000, 10000, 10000],

            // Edge cases
            [1000, 1000, 10000, 1000],  // Min boundary
            [10000, 1000, 10000, 10000], // Max boundary
        ];
    }
}
```

**Test Coverage Goal:** 100% (simple validation logic)

---

### Task 8.3: Add Integration Tests for Refactored Hooks

**Priority:** 🟢 Medium  
**Time:** 2 hours  
**Impact:** Ensures refactored hooks work correctly together  
**Status:** [ ] Not Started

**Context:** After splitting `useRecognitionJob` (Task 3.1), verify all pieces work together

**Create/Update:** `js/admin/hooks/__tests__/useRecognitionJob.integration.test.tsx`

```typescript
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useRecognitionJob } from '../useRecognitionJob';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';

const server = setupServer();

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe('useRecognitionJob - Integration', () => {
  const wrapper = ({ children }) => (
    <QueryClientProvider client={new QueryClient()}>
      {children}
    </QueryClientProvider>
  );

  it('should submit job and poll for completion', async () => {
    const jobId = 'test-job-123';

    // Mock job submission
    server.use(
      http.post('/wp-json/cat/v1/recognition/analyze', () => {
        return HttpResponse.json({
          id: jobId,
          status: 'pending',
          attachmentIds: [1, 2, 3],
        });
      })
    );

    // Mock polling - first pending, then complete
    let pollCount = 0;
    server.use(
      http.get(`/wp-json/cat/v1/recognition/jobs/${jobId}`, () => {
        pollCount++;
        const status = pollCount === 1 ? 'processing' : 'complete';
        return HttpResponse.json({
          id: jobId,
          status,
          attachmentIds: [1, 2, 3],
          observations: pollCount === 2 ? [{...}] : [],
        });
      })
    );

    const { result } = renderHook(() => useRecognitionJob(), { wrapper });

    // Start job
    result.current.startJob([1, 2, 3]);

    // Wait for submission
    await waitFor(() => {
      expect(result.current.isSubmitting).toBe(false);
    });

    // Verify polling started
    expect(result.current.isPolling).toBe(true);

    // Wait for completion
    await waitFor(() => {
      expect(result.current.jobDetails?.status).toBe('complete');
    }, { timeout: 5000 });

    // Verify no errors
    expect(result.current.error).toBeNull();
  });

  it('should handle submission errors gracefully', async () => {
    server.use(
      http.post('/wp-json/cat/v1/recognition/analyze', () => {
        return HttpResponse.json(
          { message: 'Invalid attachment IDs' },
          { status: 400 }
        );
      })
    );

    const { result } = renderHook(() => useRecognitionJob(), { wrapper });

    result.current.startJob([999]);

    await waitFor(() => {
      expect(result.current.error).toBeTruthy();
    });

    expect(result.current.isPolling).toBe(false);
  });
});
```

**Also Test:**

- `useRecognitionSubmit` (unit test)
- `useRecognitionPoll` (unit test with fake timers)
- `useWorkbenchMedia` (integration test for fallback logic)

**Test Coverage Goal:** 80%+ (integration tests cover main paths)

---

### Task 8.4: Add Contract Tests for Frontend/Backend Alignment

**Priority:** 🟢 Medium  
**Time:** 1.5 hours  
**Impact:** Prevents API drift  
**Status:** [ ] Not Started

**Context:** Verify frontend types match backend responses (Task 6.3)

**Create:** `packages/shared-contracts/tests/contract-alignment.test.ts`

```typescript
import { describe, it, expect } from "vitest";
import type { RecognitionJobSummary, RosterEntry } from "../types";

describe("Contract Alignment Tests", () => {
  describe("RecognitionJobSummary", () => {
    it("should match PHP response structure", () => {
      // Sample response from PHP backend
      const phpResponse = {
        id: "job-123",
        status: "complete",
        attachmentIds: [1, 2, 3],
        createdAt: 1697500000,
        updatedAt: 1697500100,
      };

      // Verify it matches TypeScript type
      const typed: RecognitionJobSummary = phpResponse;

      expect(typed.id).toBe("job-123");
      expect(typed.status).toBe("complete");
      expect(typed.attachmentIds).toEqual([1, 2, 3]);
      expect(typed.createdAt).toBe(1697500000);
      expect(typed.updatedAt).toBe(1697500100);
    });

    it("should reject invalid status values", () => {
      const invalidResponse = {
        id: "job-123",
        status: "invalid-status", // Not in allowed values
        attachmentIds: [1],
        createdAt: 1697500000,
        updatedAt: 1697500100,
      };

      // TypeScript should catch this at compile time
      // Runtime validation in normalizeJobSummary() should reject it
      expect(() => {
        // Assume normalizeJobSummary throws on invalid status
        // const typed: RecognitionJobSummary = normalizeJobSummary(invalidResponse);
      }).toThrow();
    });
  });

  describe("RosterEntry", () => {
    it("should match PHP response structure", () => {
      const phpResponse = {
        remoteId: "remote-123",
        label: "John Doe",
        type: "face",
        status: "SYNCED",
        avatarId: 42,
        referenceImages: [1, 2],
        createdAt: 1697500000,
        updatedAt: 1697500100,
      };

      const typed: RosterEntry = phpResponse;

      expect(typed.remoteId).toBe("remote-123");
      expect(typed.label).toBe("John Doe");
      expect(typed.type).toBe("face");
    });
  });

  describe("Validation Constants", () => {
    it("should have matching timeout limits in TS and PHP", async () => {
      // Import frontend constants
      const { VALIDATION } = await import(
        "../../../js/admin/constants/validation"
      );

      // Verify these match PHP ValidationConstants
      expect(VALIDATION.TIMEOUT_MS.MIN).toBe(1000);
      expect(VALIDATION.TIMEOUT_MS.MAX).toBe(120000);
      expect(VALIDATION.TIMEOUT_MS.DEFAULT).toBe(15000);

      // If these fail, frontend/backend are out of sync
    });
  });
});
```

**Test Coverage Goal:** Key contracts covered (not exhaustive, but critical paths)

---

### Task 8.5: Measure and Document Coverage Baselines

**Priority:** 🟢 Medium  
**Time:** 30 minutes  
**Impact:** Establish metrics for future improvements  
**Status:** [ ] Not Started

**Actions:**

1. **Run coverage reports:**

   ```bash
   # PHP coverage
   cd apps/wp-context-alt-text
   composer test -- --coverage-html coverage/html
   composer test -- --coverage-text

   # Frontend coverage
   cd apps/wp-context-alt-text
   npm run test:coverage
   ```

2. **Document current baselines in README:**

   ```markdown
   ## Test Coverage

   **PHP Backend:**

   - Overall: 78% (target: 85%)
   - Repositories: 85%
   - Services: 72%
   - Controllers (API): 65%
   - Utilities: 90%

   **Frontend:**

   - Overall: 71% (target: 80%)
   - Hooks: 68%
   - Components: 73%
   - Utilities: 85%
   - Normalization: 60% (needs improvement)

   **Coverage Goals:**

   - Critical paths: 90%+
   - Utilities: 85%+
   - Business logic: 80%+
   - UI components: 70%+
   ```

3. **Set up coverage thresholds:**

   **PHP:** Update `phpunit.xml.dist`:

   ```xml
   <coverage>
     <report>
       <html outputDirectory="coverage/html"/>
       <text outputFile="php://stdout" showUncoveredFiles="true"/>
     </report>
     <include>
       <directory suffix=".php">src</directory>
     </include>
     <exclude>
       <directory>src/Support/WpFunctionStubs.php</directory> <!-- If not deleted yet -->
     </exclude>
   </coverage>
   ```

   **Frontend:** Update `vitest.config.ts`:

   ```typescript
   export default defineConfig({
     test: {
       coverage: {
         provider: "v8",
         reporter: ["text", "html", "lcov"],
         thresholds: {
           lines: 70, // Current baseline
           functions: 70,
           branches: 65,
           statements: 70,
         },
         exclude: ["node_modules/", "tests/", "**/*.test.ts", "**/*.test.tsx"],
       },
     },
   });
   ```

4. **Add coverage badges to README** (optional):
   ```markdown
   [![PHP Coverage](https://img.shields.io/badge/PHP%20Coverage-78%25-yellow.svg)]()
   [![JS Coverage](https://img.shields.io/badge/JS%20Coverage-71%25-yellow.svg)]()
   ```

**Deliverables:**

- Baseline coverage metrics documented
- Thresholds configured in test runners
- Coverage reports generated

---

### Task 8.6: Add Missing Edge Case Tests

**Priority:** 🟢 Medium  
**Time:** 1.5-2 hours  
**Impact:** Prevents production bugs  
**Status:** [ ] Not Started

**Context:** Identify and test edge cases revealed during refactoring

**High-Priority Edge Cases:**

1. **Empty/Null Data Handling:**

   ```typescript
   // Test normalization with empty responses
   describe("normalizeObservation - edge cases", () => {
     it("should handle empty object", () => {
       expect(() => normalizeObservation({})).not.toThrow();
     });

     it("should handle null values for optional fields", () => {
       const data = {
         id: "123",
         jobId: "job-456",
         confidence: null,
         rosterMatch: null,
       };
       const result = normalizeObservation(data);
       expect(result.confidence).toBeNull();
       expect(result.rosterMatch).toBeNull();
     });
   });
   ```

2. **Boundary Values:**

   ```php
   public function testTimeoutBoundaries(): void
   {
       // Test exactly at boundaries
       $this->assertSame(1000, ValidationHelpers::sanitizeTimeout(1000, 1000, 10000));
       $this->assertSame(10000, ValidationHelpers::sanitizeTimeout(10000, 1000, 10000));

       // Test one off boundaries
       $this->assertSame(1000, ValidationHelpers::sanitizeTimeout(999, 1000, 10000));
       $this->assertSame(10000, ValidationHelpers::sanitizeTimeout(10001, 1000, 10000));
   }
   ```

3. **Race Conditions in Polling:**

   ```typescript
   it("should handle rapid job status changes", async () => {
     // Simulate job completing before first poll
     server.use(
       http.post("/analyze", () =>
         HttpResponse.json({ id: "fast-job", status: "pending" })
       ),
       http.get("/jobs/fast-job", () =>
         HttpResponse.json({ status: "complete" })
       )
     );

     const { result } = renderHook(() => useRecognitionJob(), { wrapper });
     result.current.startJob([1]);

     await waitFor(() => {
       expect(result.current.jobDetails?.status).toBe("complete");
     });
   });
   ```

4. **Error Recovery:**

   ```typescript
   it("should retry failed requests", async () => {
     let attemptCount = 0;
     server.use(
       http.get("/api/roster", () => {
         attemptCount++;
         if (attemptCount < 3) {
           return HttpResponse.error();
         }
         return HttpResponse.json([{ id: "1", label: "Success" }]);
       })
     );

     // Test that React Query retries work
     const { result } = renderHook(() => useRoster(), { wrapper });

     await waitFor(() => {
       expect(result.current.data).toBeDefined();
       expect(attemptCount).toBe(3);
     });
   });
   ```

**Test Coverage Goal:** Critical edge cases covered (aim for 15-20 new tests)

---

### Test Coverage Success Metrics

**Before Test Coverage Improvements:**

- PHP Coverage: ~78%
- Frontend Coverage: ~71%
- Contract Tests: 0
- Edge Case Tests: Minimal

**After Test Coverage Improvements:**

- PHP Coverage: 85%+ (goal)
- Frontend Coverage: 80%+ (goal)
- Contract Tests: 10+ key contracts verified
- Edge Case Tests: 20+ critical scenarios covered
- Test Reliability: 95%+ (fewer flaky tests)

**Additional Benefits:**

- ✅ Confidence in refactored code
- ✅ Faster debugging (tests pinpoint issues)
- ✅ Documentation through tests
- ✅ Prevents regressions
- ✅ Easier onboarding (tests show expected behavior)

---

## 🟢 PHASE 9: Medium Priority - Documentation Updates (2 hours)

**Progress Tracker:**

- [ ] Task 9.1: Update Code Architecture Documentation
- [ ] Task 9.2: Create Refactoring Retrospective

---

### Task 9.1: Update Code Architecture Documentation

**Priority:** 🟢 Medium  
**Time:** 1 hour  
**Impact:** Developer onboarding  
**Status:** [ ] Not Started

**Files to Update:**

- `apps/wp-context-alt-text/README.md`
- `docs/architecture/rules/coding-standards.md` (if exists)
- `docs/architecture/rules/frontend-patterns.md` (if exists)

**Add sections for:**

1. Shared utility guidelines
2. Normalization patterns
3. Validation alignment
4. Hook composition patterns
5. Test coverage expectations (NEW - from Phase 8)

---

### Task 9.2: Create Refactoring Retrospective

**Priority:** 🟢 Medium  
**Time:** 1 hour  
**Impact:** Knowledge capture  
**Status:** [ ] Not Started

**Create:** `docs/REFACTORING_RETROSPECTIVE.md`

**Content:**

- What was refactored and why
- Before/after metrics (lines, complexity, coverage)
- Lessons learned
- Patterns to follow for future code
- Patterns to avoid

---

## 🟢 PHASE 10: Low Priority - Polish (10 hours)

**Progress Tracker:**

- [ ] Task 10.1: Remove Test-Specific Code from Production
- [ ] Task 10.2: Consolidate Duplicate notices.ts Files
- [ ] Task 10.3: Add PHPDoc to Private Methods
- [ ] Task 10.4: Create Value Objects for Dashboard Data

---

### Task 10.1: Remove Test-Specific Code from Production

**Priority:** 🟢 Low  
**Time:** 2 hours  
**Impact:** Cleaner production code  
**Status:** [ ] Not Started

**Affected Files:**

- `js/admin/App.tsx` (lines 31-32, 539-541)
- `js/admin/hooks/useWorkbenchMedia.ts` (lines 185-194)
- `js/admin/logger.ts` (line 24)

**Pattern:**

```typescript
// OLD:
const runtimeProcess = (
  globalThis as { process?: { env?: Record<string, string | undefined> } }
).process;
if (runtimeProcess?.env?.NODE_ENV === "test") {
  console.info("Debug info", data);
}

// NEW: Remove entirely, use test utilities in test files instead
```

**Alternative:** Use Vite's `import.meta.env.DEV` for development logging

---

### Task 10.2: Consolidate Duplicate notices.ts Files

**Priority:** 🟢 Low  
**Time:** 30 minutes  
**Impact:** -96 lines  
**Status:** [ ] Not Started

**Context:** [FRONTEND_AUDITS.md - notices.ts Duplicate](apps/wp-context-alt-text/FRONTEND_AUDITS.md#7-noticests-root--duplicate-96-lines)

**Files:**

- `js/admin/notices.ts` (96 lines) - **DELETE**
- `js/admin/utils/notices.ts` (73 lines) - **KEEP**

**Update imports** in affected files (primarily `App.tsx`)

---

### Task 10.3: Add PHPDoc to Private Methods

**Priority:** 🟢 Low  
**Time:** 2 hours  
**Impact:** Better IDE support  
**Status:** [ ] Not Started

**Context:** [PHP_AUDITS.md - Missing PHPDoc](apps/wp-context-alt-text/PHP_AUDITS.md#--issue-4-missing-phpdoc-for-private-methods)

**Files:**

- `src/Admin/Admin.php` (~10 private methods)
- `src/Security/Security.php` (all public methods)
- `src/Shared/Logger.php` (class-level doc)

---

### Task 10.4: Create Value Objects for Dashboard Data

**Priority:** 🟢 Low  
**Time:** 5.5 hours  
**Impact:** Type safety, better IDE support  
**Status:** [ ] Not Started

**Context:** [PHP_AUDITS.md - Missing Value Objects](apps/wp-context-alt-text/PHP_AUDITS.md#--issue-1-no-value-objects)

**Create classes:**

```php
src/Admin/ValueObjects/
├── HeroStatus.php
├── CoverageMetrics.php
├── RecognitionInsights.php
└── AutomationPipeline.php
```

**Example:**

```php
final class HeroStatus
{
    public function __construct(
        public readonly string $state,
        public readonly string $message,
        public readonly ?string $ctaUrl,
        public readonly ?string $ctaLabel,
        public readonly ?string $lastUpdatedHuman,
    ) {}
}
```

**Update:** `DashboardPage.php` to use value objects instead of arrays

**Trade-off:** More classes but better type safety and maintainability

---

## 📈 Success Metrics

### Before Refactoring

**Frontend:**

- Total Lines: 1,860 (hooks only)
- Average Hook Complexity: 6.0/10
- Duplicate Code: ~260 lines
- Large Files: 3 hooks >400 lines
- Test Coverage: ~71%

**PHP:**

- Total Lines: ~3,500
- Unnecessary Code: ~713 lines (20%)
- Technical Debt Items: 2 major (stubs, legacy migration)
- Test Coverage: ~78%

**Combined:**

- Estimated Duplicate Logic: ~400 lines
- Code Smell Score: 5.5/10 (average)
- Average Test Coverage: 74.5%

### After Refactoring

**Frontend:**

- Total Lines: ~1,100 (40% reduction)
- Average Hook Complexity: 3.5/10
- Duplicate Code: 0 lines
- Large Files: 0 hooks >250 lines
- Test Coverage: ~80%+ (target)

**PHP:**

- Total Lines: ~2,787
- Unnecessary Code: 0 lines
- Technical Debt Items: 0
- Test Coverage: ~85%+ (target)

**Combined:**

- Estimated Duplicate Logic: 0 lines
- Code Smell Score: 2.5/10 (average)
- Average Test Coverage: 82.5%+ (target)

### ROI Calculation

| Metric           | Before | After  | Improvement       |
| ---------------- | ------ | ------ | ----------------- |
| Total Lines      | ~5,360 | ~3,887 | -1,473 (-27%)     |
| Duplicate Lines  | ~400   | 0      | -400 (-100%)      |
| Avg Complexity   | 5.5/10 | 2.5/10 | -55%              |
| Files >400 lines | 5      | 0      | -100%             |
| Test Coverage    | 74.5%  | 82.5%+ | +8-10%            |
| Contract Tests   | 0      | 10+    | New coverage area |

**Time Investment:** 46-58 hours (includes test improvements)  
**Long-term Savings:** ~200 hours over next year (easier maintenance, faster features, fewer bugs)  
**Quality Impact:** Higher confidence in deployments, faster debugging, better onboarding

---

## 🚀 Execution Strategy

### Recommended Path: Tactical → Strategic

**Step 1: Complete Tactical Critical Path (11 hours)**

1. Phase 1: Greenfield Cleanup (1h)
2. Phase 2: Frontend Utilities (3h)
3. Phase 3: Frontend Hooks (7h)

**Decision Point:** After critical path, evaluate project needs:

- **If maintaining current scope** → Continue tactical phases 4-9
- **If planning major features** → Start strategic Phase 10 (DI Container)
- **If team bandwidth limited** → Pause, use improved codebase

**Step 2: Choose Tactical Completion Approach**

### Approach A: Sequential (Safest, Tactical Only)

Execute phases 1-9 in order. Each phase builds on previous work.

**Timeline:** 6-7 weeks (assuming 8 hours/week)

**Pros:**

- Lower risk
- Easier to test incrementally
- Can pause between phases
- No strategic architecture needed yet

**Cons:**

- Slower overall progress
- Benefits realized gradually

**Best For:** Solo developer, conservative approach, uncertain about strategic needs

---

### Approach B: Parallel Streams (Faster, Tactical Only)

Run multiple phases concurrently with different developers/timeslots.

**Streams:**

1. **Greenfield Cleanup** (Phase 1) - 1 hour
2. **Frontend Utilities** (Phase 2) - 3 hours
3. **PHP Utilities** (Phase 4) - 3 hours
4. **Hook Refactoring** (Phase 3) - 7 hours [depends on Stream 2]
5. **Cross-Stack Alignment** (Phase 6) - 6 hours [depends on Streams 2+3]

**Timeline:** 3-4 weeks with parallel work

**Pros:**

- Faster completion
- Early benefits from multiple fronts
- Can still defer strategic architecture

**Cons:**

- More coordination needed
- Higher merge conflict risk

**Best For:** Team of 2+, good Git workflow, want faster tactical completion

---

### Approach C: High-Impact First (Recommended, Tactical Only)

Focus on high-impact tasks first, defer polish.

**Priority Order:**

1. Phase 1: Greenfield Cleanup (1h) - **DO FIRST**
2. Phase 2: Frontend Utilities (3h)
3. Phase 3: Frontend Hooks (7h)
4. Phase 4: PHP Utilities (3h)
5. Phase 6: Cross-Stack Alignment (6h)
6. Phase 5: Frontend Components (4h)
7. Phase 7: PHP Components (4h)
8. Phase 8: Documentation (2h)
9. Phase 9: Polish (defer or skip)

**Timeline:** 4-5 weeks for critical work, polish as time permits

**Pros:**

- Maximum impact early (75% benefit from 50% work)
- Can stop at any point with value
- Polish truly optional
- Strategic architecture remains option later

**Cons:**

- Documentation lags implementation
- Polish may never happen

**Best For:** Most teams - practical approach with early wins

---

### Approach D: Tactical + Strategic (Aggressive, Full Stack)

Complete tactical cleanup while planning strategic architecture, then execute both.

**Phase Progression:**

1. **Weeks 1-2:** Tactical Phases 1-3 (critical path)
2. **Week 3:** Evaluate + plan strategic architecture
3. **Weeks 4-5:** Tactical Phases 4-7 (utilities + components)
4. **Weeks 6-7:** Strategic Phase 10A (DI Container + Service Providers)
5. **Weeks 8-9:** Strategic Phase 10B (Event Bus + Repository)
6. **Weeks 10-15:** Strategic Phase 10C (CQRS) - if needed
7. **Week 16:** Strategic Phase 10D (Test Infrastructure) - if needed

**Timeline:** 8-16 weeks depending on strategic scope

**Pros:**

- Complete transformation
- Best long-term architecture
- All technical debt addressed
- Future-proof codebase

**Cons:**

- Major time investment
- Higher risk
- Requires commitment
- May be overkill for small projects

**Best For:** Projects with:

- ✅ Long-term roadmap (1+ year)
- ✅ Team growth planned
- ✅ 5+ major features coming
- ✅ Technical debt causing pain

---

### Decision Matrix

Choose your approach based on your situation:

| Situation                                          | Recommended Approach                   |
| -------------------------------------------------- | -------------------------------------- |
| Solo developer, greenfield cleanup urgently needed | **Approach A** (Sequential)            |
| Small team, want quick tactical wins               | **Approach C** (High-Impact First)     |
| 2+ developers, good coordination                   | **Approach B** (Parallel Streams)      |
| Planning major expansion, team growth              | **Approach D** (Tactical + Strategic)  |
| Bootstrap file causing daily pain                  | **Approach D** (Start strategic early) |
| Just want code cleanup, not architecture           | **Approach C** (Stop after Phase 9)    |
| Uncertain about future direction                   | **Approach C** (Keep options open)     |

---

### When to Skip Strategic Architecture

**Don't do Phase 10 if:**

- ❌ Project scope stable, few new features planned
- ❌ Solo developer maintaining small plugin
- ❌ Bootstrap file manageable with tactical improvements
- ❌ No circular dependency issues after tactical work
- ❌ Team bandwidth limited
- ❌ Current patterns working fine

**Strategic architecture is optional** - tactical refactoring alone provides significant value (35-40% technical debt reduction).

---

## ✅ Definition of Done

For each task:

- [ ] Code changes implemented
- [ ] Tests updated and passing
- [ ] No new linting errors
- [ ] PHPStan/TypeScript checks pass
- [ ] Code review completed
- [ ] Documentation updated (if applicable)
- [ ] Commit message follows conventional commits format

For each phase:

- [ ] All phase tasks completed
- [ ] Integration tests pass
- [ ] Manual smoke testing completed
- [ ] Performance benchmarks maintained or improved
- [ ] Audit documents updated

For overall refactoring:

- [ ] All critical phases (1-3) completed
- [ ] Metrics targets achieved (see Success Metrics)
- [ ] Retrospective document created
- [ ] Team knowledge sharing session completed

---

## 🎯 Quick Start Checklist

**Week 1: Greenfield Cleanup**

- [ ] Task 1.1: Remove stub files (15 min)
- [ ] Task 1.2: Fix settings option name (5 min)
- [ ] Task 1.3: Update tests (15 min)
- [ ] Task 1.4: Remove legacy migration (15 min)
- [ ] Task 1.5: Update docs (10 min)
- [ ] Run full test suite
- [ ] Commit & push

**Week 2: Frontend Utilities**

- [ ] Task 2.1: Create normalization utils (2h)
- [ ] Task 2.2: Enhance HTTP utils (1h)
- [ ] Update hooks to use new utilities
- [ ] Run frontend tests
- [ ] Commit & push

**Week 3-4: Hook Refactoring**

- [ ] Task 3.1: Refactor useRecognitionJob (5h)
- [ ] Task 3.2: Simplify useWorkbenchMedia (2h)
- [ ] Integration testing
- [ ] Commit & push

**Week 5: PHP Utilities & Alignment**

- [ ] Tasks 4.1-4.4: PHP utilities (3h)
- [ ] Tasks 6.1-6.3: Cross-stack alignment (6h)
- [ ] Contract testing
- [ ] Commit & push

**Week 6: Components & Tests**

- [ ] Tasks 5.1-5.2: Frontend components (4h)
- [ ] Tasks 7.1-7.3: PHP components (4h)
- [ ] Tasks 8.1-8.3: Test coverage for new utilities (3h)

**Week 7: Test Coverage & Documentation**

- [ ] Tasks 8.4-8.6: Contract tests and edge cases (3-4h)
- [ ] Tasks 9.1-9.2: Documentation (2h)
- [ ] Final review & retrospective

---

## 🏗️ PHASE 11: Strategic Architecture (8+ weeks)

**Context:** After completing tactical refactoring (Phases 1-9), consider these strategic architectural improvements. These are optional but high-impact changes for long-term maintainability.

**See:** [ARCHITECTURAL_IMPROVEMENTS.md](ARCHITECTURAL_IMPROVEMENTS.md) for complete details, code examples, and migration guides.

**Note:** This is now Phase 11 after adding Test Coverage as Phase 8.

### When to Start Strategic Architecture

**Do DI Container + Service Providers if:**

- ✅ Planning 3+ new features in next month
- ✅ Onboarding new developers soon
- ✅ Bootstrap file causing maintenance issues
- ✅ Want to eliminate circular dependencies

**Do Event Bus if:**

- ✅ Need to decouple recognition ↔ roster
- ✅ Want analytics/auditing infrastructure
- ✅ Planning integration with external systems

**Do CQRS if:**

- ✅ Api.php becoming unmaintainable (>1,000 lines)
- ✅ Need to reuse business logic in CLI/cron
- ✅ Want clearer command vs query separation

### Strategic Task Summary

#### Phase 10A: Foundation (Week 1-2, Critical Priority �)

**Task 10A.1: Install & Configure PHP-DI Container**  
**Time:** 2-3 days | **Impact:** Bootstrap 491→100 lines (-80%)

1. Install PHP-DI: `composer require php-di/php-di "^7.0"`
2. Create `src/Infrastructure/ContainerConfig.php`
3. Define service definitions with autowiring
4. Update `context-alt-text.php` to use container
5. Create `tests/ContainerTestCase.php` for testing
6. Verify all existing functionality works

**Deliverables:**

- Container configuration with ~40 service definitions
- Simplified bootstrap file (~100 lines)
- Test base class for easy mocking

**Task 10A.2: Implement Service Provider Architecture**  
**Time:** 2-3 days | **Impact:** Clear domain separation

1. Create `src/Infrastructure/ServiceProvider.php` base class
2. Create domain-specific providers:
   - `RecognitionServiceProvider.php`
   - `RosterServiceProvider.php`
   - `AdminServiceProvider.php`
   - `ApiServiceProvider.php`
   - `FrontendServiceProvider.php`
3. Move hook registration from bootstrap to providers
4. Move CLI command registration to providers
5. Update bootstrap to register/boot providers

**Deliverables:**

- 5 service provider classes
- Bootstrap further reduced (~80 lines total)
- Better separation of concerns

---

#### Phase 10B: Decoupling (Week 3-4, High Priority 🟡)

**Task 10B.1: Implement Event Bus Architecture**  
**Time:** 3-4 days | **Impact:** Zero circular dependencies

1. Create `src/Infrastructure/EventBus.php`
2. Define domain events (10 events):
   - `RecognitionJobStarted`
   - `RecognitionJobCompleted`
   - `RecognitionJobFailed`
   - `RosterEntryCreated`
   - `RosterEntryUpdated`
   - `RosterEntryDeleted`
   - `RosterSyncStarted`
   - `RosterSyncCompleted`
   - `WorkbenchItemAnalyzed`
   - `SettingsUpdated`
3. Create event listeners (8 listeners):
   - `LinkObservationsOnJobComplete`
   - `InvalidateCacheOnRosterChange`
   - `SendAnalyticsEvent`
   - `UpdateDashboardMetrics`
   - etc.
4. Update `RecognitionJobService` to dispatch events
5. Remove manual `setRosterObservationManager()` setter injection
6. Register listeners in service providers

**Deliverables:**

- Event bus infrastructure
- 10 domain events
- 8 event listeners
- Circular dependency eliminated
- WordPress action integration

**Task 10B.2: Refine Repository Pattern**  
**Time:** 1-2 days | **Impact:** Single responsibility principle

1. Extract `RecognitionObservationNormalizer` from repository
2. Extract `RosterObservationLinker` domain service
3. Update `RecognitionObservationRepository` to use normalizer
4. Apply same pattern to other repositories
5. Update tests

**Deliverables:**

- 3 normalizer classes
- 1 domain service
- Repositories focused on data access only

---

#### Phase 10C: Application Layer (Week 5-7, Medium Priority 🟢)

**Task 10C.1: Implement CQRS Pattern**  
**Time:** 5-6 days | **Impact:** Api.php 1,509→500 lines (-67%)

1. Create command/query infrastructure:
   - `src/Application/Commands/CommandBus.php`
   - `src/Application/Queries/QueryBus.php`
2. Extract 15 commands from Api.php:
   - `CreateRosterEntryCommand` + Handler
   - `UpdateRosterEntryCommand` + Handler
   - `DeleteRosterEntryCommand` + Handler
   - `StartRecognitionJobCommand` + Handler
   - `SyncRosterCommand` + Handler
   - etc.
3. Extract 10 queries from Api.php:
   - `ListRosterEntriesQuery` + Handler
   - `GetRosterEntryQuery` + Handler
   - `GetRecognitionJobQuery` + Handler
   - `ListWorkbenchItemsQuery` + Handler
   - etc.
4. Simplify Api.php to thin REST layer
5. Make handlers reusable from CLI/cron/admin

**Deliverables:**

- 15 command classes + handlers
- 10 query classes + handlers
- Simplified Api.php (~500 lines)
- Reusable business logic

---

#### Phase 10D: Testing Infrastructure (Week 8, Low Priority 🟢)

**Task 10D.1: Create Test Factories & Builders**  
**Time:** 2-3 days | **Impact:** Easier test writing

1. Create factory classes (10 factories):
   - `RosterEntryFactory`
   - `RecognitionJobFactory`
   - `RecognitionObservationFactory`
   - `WorkbenchItemFactory`
   - etc.
2. Create builder classes (5 builders):
   - `RecognitionJobBuilder`
   - `RosterEntryBuilder`
   - etc.
3. Update 20 existing tests to use factories
4. Add shared test utilities

**Deliverables:**

- 10 factory classes
- 5 builder classes
- Tests easier to write and read

**Task 10D.2: Implement Rich Domain Events**  
**Time:** 1-2 days | **Impact:** Analytics foundation

1. Create rich domain events with full context
2. Add event listeners for analytics
3. Add audit logging infrastructure
4. Integrate with external systems (optional)

**Deliverables:**

- Enhanced event system
- Analytics tracking
- Audit logs

---

### Strategic Architecture Benefits

**Metrics Impact:**

| Metric                | Before      | After Strategic | Improvement |
| --------------------- | ----------- | --------------- | ----------- |
| Bootstrap File        | 491 lines   | ~100 lines      | -80%        |
| Api.php Size          | 1,509 lines | ~500 lines      | -67%        |
| Circular Dependencies | 1           | 0               | -100%       |
| Manual Wiring         | 100%        | 5%              | -95%        |
| Testability           | 6/10        | 9/10            | +50%        |
| Maintainability       | 6/10        | 9/10            | +50%        |
| Time to Add Feature   | 4 hours     | 2 hours         | -50%        |
| Developer Onboarding  | 2 weeks     | 1 week          | -50%        |

**Long-term Value:**

- **Better Testing:** Easy to mock dependencies, faster tests
- **Easier Extensibility:** Add features without modifying existing code
- **Clearer Architecture:** New developers understand quickly
- **Less Coupling:** Services don't know about each other
- **Future-Proof:** Ready for growth and new requirements

### Migration Strategy

**Incremental Approach (Recommended):**

1. **Week 1-2:** DI Container + Service Providers

   - Verify all existing functionality
   - Deploy to staging
   - Monitor for issues

2. **Week 3-4:** Event Bus + Repository Refinement

   - Eliminate circular dependencies
   - Verify recognition ↔ roster integration
   - Deploy to staging

3. **Week 5-7:** CQRS Implementation

   - Start with 5 most-used endpoints
   - Gradually migrate remaining endpoints
   - Deploy incrementally

4. **Week 8:** Testing Infrastructure
   - Add test utilities as needed
   - No deployment required

**Validation at Each Step:**

- ✅ All tests passing
- ✅ Manual smoke testing
- ✅ Performance benchmarks maintained
- ✅ No regressions in functionality

### Quick Wins (Before Strategic Work)

While planning strategic architecture, these can be done immediately:

1. **Add Type Hints** (30 min)

   ```php
   // Add explicit return types to all factory functions
   function context_alt_text(): ContextAltText
   ```

2. **Extract Roster Snapshot Function** (15 min)

   ```php
   // Already exists, just document it
   function context_alt_text_fetch_roster_snapshot(): ?array
   ```

3. **Add PHPDoc** (1 hour)

   ```php
   // Document all factory functions with purpose and usage
   ```

4. **Create Interfaces** (2 hours)
   ```php
   // Create interfaces for key abstractions
   interface RecognitionClientInterface {}
   interface RosterServiceInterface {}
   ```

---

## 📚 Reference Links

- **Architecture Roadmap:** [ARCHITECTURAL_IMPROVEMENTS.md](ARCHITECTURAL_IMPROVEMENTS.md) - Complete strategic guide
- **PHP Audit:** [apps/wp-context-alt-text/PHP_AUDITS.md](apps/wp-context-alt-text/PHP_AUDITS.md) - Backend code analysis
- **Frontend Audit:** [apps/wp-context-alt-text/FRONTEND_AUDITS.md](apps/wp-context-alt-text/FRONTEND_AUDITS.md) - JavaScript/React analysis
- **Smoke Test:** [scripts/SMOKE_TEST_ANALYSIS.md](scripts/SMOKE_TEST_ANALYSIS.md) - Integration testing
- **Architecture Rules:** [docs/architecture/rules/](docs/architecture/rules/) - Coding standards
- **Shared Contracts:** [packages/shared-contracts/](packages/shared-contracts/) - Cross-stack types

### External Resources (Strategic Architecture)

- **PHP-DI:** https://php-di.org/ - Dependency injection container
- **Event-Driven:** https://martinfowler.com/articles/201701-event-driven.html - Martin Fowler
- **CQRS:** https://martinfowler.com/bliki/CQRS.html - Command/Query separation
- **Repository Pattern:** https://designpatternsphp.readthedocs.io/ - PHP patterns

---

**Document Status:** Living document - update as refactoring progresses  
**Last Updated:** October 17, 2025  
**Next Review:** After Phase 1 completion (tactical), then after Phase 10A (strategic)
