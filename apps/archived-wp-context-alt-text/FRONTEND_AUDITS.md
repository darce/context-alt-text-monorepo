# JavaScript Hooks Audit Report

**Date:** October 17, 2025  
**Location:** `apps/wp-context-alt-text/js/admin/hooks/`  
**Files Audited:** 5 hooks (8 files total including tests)

---

## Executive Summary

**Overall Assessment:** 🟡 **MODERATE CONCERNS**

The hooks directory contains **well-structured React hooks** but suffers from:

1. **Massive complexity** in `useRecognitionJob.ts` (500+ lines)
2. **Duplicated normalization logic** across multiple hooks
3. **Over-engineering** with excessive defensive programming
4. **Brittle URL construction** in `useWorkbenchMedia.ts`

**Recommendation:** Refactor to extract shared utilities and simplify complex hooks.

---

## File-by-File Analysis

### 1. `useCoverageMetrics.ts` ✅ GOOD (53 lines)

**Purpose:** Fetch dashboard coverage metrics

**Strengths:**

- ✅ Clean, focused hook (~50 lines)
- ✅ Proper React Query usage
- ✅ Good error handling
- ✅ Sensible defaults

**Issues:**

- ⚠️ **Minor:** `hasEndpoint` boolean could be derived from query state

**Code Smell Score:** 2/10 (minimal issues)

**Recommendation:** Keep as-is

---

### 2. `useRecognitionJob.ts` 🔴 **CRITICAL BLOAT** (585 lines!)

**Purpose:** Manage recognition job submission and polling

**MAJOR ISSUES:**

#### 🔴 **Issue 1: Massive File Size**

- **Lines:** 585 (should be <200)
- **Complexity:** ~30 functions/types
- **Problem:** Violates Single Responsibility Principle

#### 🔴 **Issue 2: Duplicated Normalization Logic**

```typescript
// Lines 107-137: Utility functions duplicated in useRecognitionObservations.ts
const toUniqueNumericIds = (ids: (number | string)[]): number[] => { ... }
const toFiniteNumber = (value: unknown, fallback = 0): number => { ... }
const toNullableTimestamp = (value: unknown): number | null => { ... }
const ensureString = (value: unknown): string => { ... }
```

**Impact:** ~100 lines of duplicated code across hooks

#### 🔴 **Issue 3: Complex Normalization Functions**

```typescript
// Lines 168-247: 80 lines of nested normalization
const normalizeObservationRecord = (observation: unknown): RecognitionObservationRecord | null => {
    // 80 lines of deeply nested logic
    // Parsing candidates, matches, confidence scores
    // Should be extracted to shared utility
};
```

**Problem:** Business logic mixed with hook logic

#### 🔴 **Issue 4: Manual Polling Implementation**

```typescript
// Lines 395-458: 60+ lines of manual polling logic
const pollJob = React.useCallback(
    async (jobId: string) => {
        // Manual setTimeout management
        // Complex ref management
        // Recursive async calls
    },
    [clearPendingPoll, jobEndpoint, restNonce],
);
```

**Better Approach:** Use React Query's `refetchInterval` or `refetchOnInterval`

#### 🔴 **Issue 5: Brittle State Management**

```typescript
const [lastJob, setLastJob] = React.useState<RecognitionJobSummary | null>(null);
const [lastError, setLastError] = React.useState<RecognitionRequestError | null>(null);
const [jobDetails, setJobDetails] = React.useState<RecognitionJobDetails | null>(null);
const [isSubmitting, setIsSubmitting] = React.useState(false);
const [pollState, setPollState] = React.useState<PollState>("idle");
const [currentJobId, setCurrentJobId] = React.useState<string | null>(null);
```

**Problem:** 6 separate state hooks that should be a single state machine

#### ⚠️ **Issue 6: Over-Defensive Type Parsing**

```typescript
// Every field has 3+ fallback checks
const idCandidate = ensureString(payload.id ?? payload.jobId ?? fallbackId ?? "");
```

**Problem:** If backend contract is reliable, this is unnecessary complexity

**Code Smell Score:** 9/10 (critical refactor needed)

**Recommendations:**

1. **Extract normalization utilities** to `@/admin/utils/normalization.ts`:

    ```typescript
    // shared-utils/normalization.ts
    export const toUniqueNumericIds = ...
    export const toFiniteNumber = ...
    export const normalizeObservationRecord = ...
    ```

2. **Use React Query for polling**:

    ```typescript
    useQuery({
        queryKey: ["recognition-job", jobId],
        queryFn: () => fetchJobStatus(jobId),
        refetchInterval: (data) => (data?.status === "complete" ? false : 3000),
        enabled: Boolean(jobId),
    });
    ```

3. **State Machine for job flow**:

    ```typescript
    type JobState =
        | { status: "idle" }
        | { status: "submitting" }
        | { status: "polling"; jobId: string; details: JobDetails }
        | { status: "complete"; details: JobDetails }
        | { status: "error"; error: RecognitionRequestError };

    const [jobState, setJobState] = useState<JobState>({ status: "idle" });
    ```

4. **Split into multiple hooks**:
    - `useRecognitionSubmit.ts` - Submit jobs (100 lines)
    - `useRecognitionPoll.ts` - Poll status (80 lines)
    - `useRecognitionJob.ts` - Compose both (50 lines)

---

### 3. `useRecognitionObservations.ts` 🟡 **MODERATE BLOAT** (443 lines)

**Purpose:** Fetch and update recognition observations

**Issues:**

#### 🟡 **Issue 1: Duplicated Normalization**

```typescript
// Lines 90-120: Same utilities as useRecognitionJob.ts
const toFiniteNumber = (candidate: unknown, fallback = 0): number => { ... }
const toNumberOrNull = (candidate: unknown): number | null => { ... }
const toStringOrNull = (candidate: unknown): string | null => { ... }
```

**Impact:** ~100 lines duplicated

#### 🟡 **Issue 2: Overly Complex Normalization**

```typescript
// Lines 166-221: 55 lines of observation normalization
const normalizeObservationRecord = (candidate: Record<string, unknown>): RecognitionObservationRecord => {
    // Deeply nested parsing logic
    // Should be extracted to shared utility
};
```

#### ⚠️ **Issue 3: Unnecessary URL Building**

```typescript
// Lines 68-92: 25 lines to build URL with query params
const buildObservationsUrl = (endpoint: string, filters: RecognitionObservationFilters): string => {
    try {
        const url = new URL(endpoint, typeof window !== "undefined" ? window.location.origin : undefined);
        // ... complex logic
    } catch {
        return endpoint;
    }
};
```

**Better Approach:** Use `URLSearchParams` helper or library

**Code Smell Score:** 6/10 (needs refactoring)

**Recommendations:**

1. **Extract shared normalization** to `@/admin/utils/normalization.ts`
2. **Simplify URL building** with helper:

    ```typescript
    import { buildApiUrl } from "@/admin/utils/http";
    const url = buildApiUrl(endpoint, filters);
    ```

3. **Split complex normalization** into smaller functions:
    ```typescript
    const parseConfidence = (observation: unknown) => { ... };
    const parseMatch = (observation: unknown) => { ... };
    const parseCandidates = (observation: unknown) => { ... };
    ```

---

### 4. `useRoster.ts` 🟡 **MODERATE COMPLEXITY** (432 lines)

**Purpose:** Manage roster CRUD operations

**Issues:**

#### 🟡 **Issue 1: Complex Encoding Logic**

```typescript
// Lines 100-206: 106 lines of roster body encoding
const encodeRosterBody = (values: RosterFormValues): Record<string, unknown> => {
    // Massive function handling all edge cases
    // Should be split into smaller functions
};
```

**Problem:** Single function doing too much

#### ⚠️ **Issue 2: Duplicated URL Building**

```typescript
// Lines 57-83: Similar to useRecognitionObservations.ts
const buildRosterUrl = (endpoint: string, filters: RosterFilters): string => {
    try {
        const url = new URL(endpoint, typeof window !== "undefined" ? window.location.origin : undefined);
        // ... same pattern as other hooks
    } catch {
        return endpoint;
    }
};
```

#### ⚠️ **Issue 3: Confusing Initial Data Logic**

```typescript
// Lines 238-247: Complex conditional initial data
initialData: hasEndpoint && isInitialFilters(filters)
    ? rosterResultFromBootstrap(initialData, filters)
    : undefined,
```

**Problem:** Implicit behavior based on filter state

**Code Smell Score:** 5/10 (moderate issues)

**Recommendations:**

1. **Split `encodeRosterBody`** into logical chunks:

    ```typescript
    const buildMetadata = (values: RosterFormValues) => { ... };
    const buildReferenceImages = (values: RosterFormValues) => { ... };
    const buildResolution = (values: RosterFormValues) => { ... };
    const encodeRosterBody = (values) => ({
      ...buildMetadata(values),
      referenceImages: buildReferenceImages(values),
      resolveObservation: buildResolution(values),
    });
    ```

2. **Extract URL building** to shared utility

3. **Clarify bootstrap logic** with explicit conditions

---

### 5. `useWorkbenchMedia.ts` 🔴 **EXTREMELY BRITTLE** (347 lines)

**Purpose:** Fetch workbench media items

**CRITICAL ISSUES:**

#### 🔴 **Issue 1: Over-Engineered Origin Resolution**

```typescript
// Lines 40-75: 35 lines trying to resolve origin from multiple sources
const resolveOriginCandidate = (candidate: unknown, sourceLabel: string): string | null => { ... }
const isViableOrigin = (candidate: string | null | undefined): candidate is string => { ... }
const takeFirstOrigin = (candidates: (string | null | undefined)[]): string | null => { ... }
```

**Problem:** Extremely defensive code that shouldn't be necessary

#### 🔴 **Issue 2: Brittle Fallback Logic**

```typescript
// Lines 99-144: 45 lines of fallback endpoint resolution
const fallbackEndpoint = React.useMemo(() => {
    if (typeof window === "undefined") return null;

    try {
        const { location } = window;
        const originCandidate = (() => {
            // Nested function inside useMemo inside try/catch
            // 30+ lines of complex logic
        })();

        const fallbackOrigin = takeFirstOrigin([
            originCandidate,
            resolveOriginCandidate(document.baseURI, "document.baseURI"),
            resolveOriginCandidate(wpApiSettings?.root, "wpApiSettings.root"),
            resolveOriginCandidate(window.ajaxurl, "window.ajaxurl"),
        ]);
        // ... more complex logic
    } catch (error) {
        console.warn("Unable to resolve fallback Workbench endpoint", error);
        return null;
    }
}, []);
```

**Problem:** This is a MASSIVE code smell. If the endpoint isn't configured, it should fail early, not try 5 different fallback strategies.

#### 🔴 **Issue 3: Overly Complex shouldFetchRemote Logic**

```typescript
// Lines 159-183: 24 lines to determine if remote fetch is needed
const shouldFetchRemote = React.useMemo(
    () => {
        if (!hasResolvedEndpoint) return false;
        if (normalizedSearch !== null) return true;
        if (bootstrapItems.length === 0) return true;
        if (page !== bootstrapPage) return true;
        if (perPage !== bootstrapPerPage) return true;
        if (hasBootstrapPaginationGap) return true;
        return false;
    },
    [
        /* 7 dependencies */
    ],
);
```

**Problem:** Too many conditions. Should use simpler heuristic.

#### ⚠️ **Issue 4: Duplicated URL Building**

```typescript
// Lines 199-217: Another URL builder (3rd one across hooks!)
const buildRequestUrl = React.useCallback((endpoint: string) => {
    try {
        return new URL(endpoint);
    } catch {
        // Fallback logic...
    }
}, []);
```

#### ⚠️ **Issue 5: Test-Specific Console Logs**

```typescript
// Lines 185-194: Test environment checks littered in production code
const runtimeProcess = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process;
if (runtimeProcess?.env?.NODE_ENV === "test") {
    console.info("useWorkbenchMedia", { ... });
}
```

**Problem:** Test instrumentation should be in test files, not production code

**Code Smell Score:** 8/10 (critical refactor needed)

**Recommendations:**

1. **Remove brittle fallback logic**:

    ```typescript
    // SIMPLE VERSION:
    const endpoint = config.endpoints?.workbenchMedia;
    if (!endpoint) {
        throw new Error("Workbench media endpoint not configured");
    }
    ```

2. **Simplify fetch logic**:

    ```typescript
    const shouldFetchRemote = hasEndpoint && (hasSearch || page > 1 || perPage !== DEFAULT_PER_PAGE);
    ```

3. **Remove test-specific code** - use test utilities instead

4. **Extract URL building** to shared utility

---

## Cross-Cutting Issues

### 🔴 **1. Duplicated Normalization Logic**

**Affected Files:** 3 hooks (useRecognitionJob, useRecognitionObservations, useRoster)

**Duplicate Code:**

- `toFiniteNumber()` - Appears 3x
- `toNumberOrNull()` - Appears 2x
- `toStringOrNull()` - Appears 2x
- `normalizeObservationRecord()` - Similar logic in 2 hooks
- `normalizeRoster()` - Similar logic in 2 hooks

**Impact:** ~200 lines of duplicated code

**Recommendation:**

Create `@/admin/utils/normalization.ts`:

```typescript
// utils/normalization.ts
export const toFiniteNumber = (candidate: unknown, fallback = 0): number => {
    if (typeof candidate === "number" && Number.isFinite(candidate)) {
        return candidate;
    }

    if (typeof candidate === "string") {
        const parsed = Number(candidate);
        if (Number.isFinite(parsed)) return parsed;
    }

    return fallback;
};

export const toNumberOrNull = (candidate: unknown): number | null => {
    const num = toFiniteNumber(candidate, NaN);
    return Number.isFinite(num) ? num : null;
};

export const toStringOrNull = (candidate: unknown): string | null => {
    if (typeof candidate === "string") {
        const trimmed = candidate.trim();
        return trimmed !== "" ? trimmed : null;
    }

    if (typeof candidate === "number" && Number.isFinite(candidate)) {
        return String(candidate);
    }

    return null;
};

export const normalizeObservation = (data: unknown): ObservationRecord => {
    // Centralized normalization logic
};

export const normalizeRoster = (data: unknown): RosterEntry => {
    // Centralized roster normalization
};
```

**Lines Saved:** ~200 lines

---

### 🔴 **2. Duplicated URL Building Logic**

**Affected Files:** 3 hooks (useRecognitionObservations, useRoster, useWorkbenchMedia)

**Pattern:**

```typescript
const buildUrl = (endpoint: string, params: object): string => {
    try {
        const url = new URL(endpoint, window.location.origin);
        // ... set params
        return url.toString();
    } catch {
        return endpoint;
    }
};
```

**Recommendation:**

Create `@/admin/utils/http.ts`:

```typescript
// utils/http.ts
export const buildApiUrl = (
    endpoint: string,
    params?: Record<string, string | number | boolean | null | undefined>,
): string => {
    try {
        const url = new URL(endpoint, typeof window !== "undefined" ? window.location.origin : undefined);

        if (params) {
            Object.entries(params).forEach(([key, value]) => {
                if (value != null) {
                    url.searchParams.set(key, String(value));
                }
            });
        }

        return url.toString();
    } catch {
        return endpoint;
    }
};
```

**Usage:**

```typescript
const url = buildApiUrl(endpoint, {
    page,
    per_page: perPage,
    status,
    search,
});
```

**Lines Saved:** ~60 lines

---

### 🟡 **3. Duplicated Header Building**

**Affected Files:** 3 hooks

**Pattern:**

```typescript
const buildHeaders = (config: AdminConfig, includeJson = false): HeadersInit => {
    const headers: Record<string, string> = {};
    if (includeJson) headers["Content-Type"] = "application/json";
    if (config.restNonce) headers["X-WP-Nonce"] = config.restNonce;
    return headers;
};
```

**Recommendation:** Extract to `@/admin/utils/http.ts`

---

### ⚠️ **4. Over-Defensive Programming**

**Problem:** Every hook has 3-5 fallback checks for every field

**Example:**

```typescript
const id = toFiniteNumber(candidate.id ?? candidate.attachmentId ?? candidate.attachment_id ?? 0, 0);
```

**Impact:**

- Makes code harder to read
- Hides actual bugs (silent failures)
- Bloats file size

**Recommendation:**

- Trust backend contracts (you control both ends!)
- Add runtime validation at API boundaries instead
- Use TypeScript strict mode to catch issues at build time

---

## Summary Statistics

| File                            | Lines     | Complexity | Code Smell | Priority    |
| ------------------------------- | --------- | ---------- | ---------- | ----------- |
| `useCoverageMetrics.ts`         | 53        | Low        | 2/10       | ✅ Low      |
| `useRecognitionJob.ts`          | 585       | Very High  | 9/10       | 🔴 Critical |
| `useRecognitionObservations.ts` | 443       | High       | 6/10       | 🟡 High     |
| `useRoster.ts`                  | 432       | Moderate   | 5/10       | 🟡 Medium   |
| `useWorkbenchMedia.ts`          | 347       | High       | 8/10       | 🔴 High     |
| **Total**                       | **1,860** |            | **6.0/10** |             |

**Average Lines per Hook:** 372 lines (industry standard: 100-200 lines)

---

## Refactoring Plan

### Phase 1: Extract Shared Utilities (High Priority) 🔴

**Time:** 2-3 hours  
**Impact:** Reduce 260+ lines of duplication

1. Create `@/admin/utils/normalization.ts`:
    - `toFiniteNumber()`
    - `toNumberOrNull()`
    - `toStringOrNull()`
    - `toUniqueNumericIds()`
    - `normalizeObservation()`
    - `normalizeRoster()`

2. Create `@/admin/utils/http.ts`:
    - `buildApiUrl()`
    - `buildHeaders()`
    - `handleJsonResponse()` (already exists, good!)
    - `ensureOk()` (already exists, good!)

3. Update all hooks to use shared utilities

**Lines Reduced:** ~260 lines  
**Files Affected:** 5 hooks

---

### Phase 2: Refactor useRecognitionJob.ts (Critical) 🔴

**Time:** 4-5 hours  
**Impact:** Reduce 585 → ~200 lines

1. **Extract polling logic** to use React Query:

    ```typescript
    // hooks/useRecognitionPoll.ts (80 lines)
    export const useRecognitionPoll = (jobId: string | null) => {
        return useQuery({
            queryKey: ["recognition-job", jobId],
            queryFn: () => fetchJobStatus(jobId),
            refetchInterval: (data) => (data?.status === "complete" ? false : 3000),
            enabled: Boolean(jobId),
        });
    };
    ```

2. **Extract submission logic**:

    ```typescript
    // hooks/useRecognitionSubmit.ts (100 lines)
    export const useRecognitionSubmit = () => {
        return useMutation({
            mutationFn: (ids: number[]) => submitRecognitionJob(ids),
        });
    };
    ```

3. **Compose in main hook**:
    ```typescript
    // hooks/useRecognitionJob.ts (50 lines)
    export const useRecognitionJob = () => {
        const { mutate: submit, data: jobId } = useRecognitionSubmit();
        const poll = useRecognitionPoll(jobId);

        return {
            triggerRecognition: submit,
            jobDetails: poll.data,
            isSubmitting: submit.isPending,
            isPolling: poll.isFetching,
        };
    };
    ```

**Lines Reduced:** 585 → ~230 lines total (across 3 files)

---

### Phase 3: Simplify useWorkbenchMedia.ts (High Priority) 🔴

**Time:** 2-3 hours  
**Impact:** Reduce 347 → ~150 lines

1. **Remove brittle fallback logic** (save ~80 lines):

    ```typescript
    // BEFORE: 45 lines of fallback logic
    // AFTER: 5 lines
    const endpoint = config.endpoints?.workbenchMedia;
    if (!endpoint) {
      console.error("Workbench media endpoint not configured");
      return { data: [], total: 0, ... };
    }
    ```

2. **Simplify shouldFetchRemote** (save ~20 lines):

    ```typescript
    const shouldFetchRemote = hasEndpoint && (hasSearch || page > 1 || perPage !== DEFAULT_PER_PAGE);
    ```

3. **Remove test-specific code** (save ~10 lines)

4. **Use shared URL builder** (save ~20 lines)

**Lines Reduced:** 347 → ~150 lines

---

### Phase 4: Polish Other Hooks (Medium Priority) 🟡

**Time:** 2-3 hours per hook  
**Impact:** Improve maintainability

1. **useRecognitionObservations.ts:**
    - Use shared normalization utilities
    - Simplify observation parsing
    - 443 → ~250 lines

2. **useRoster.ts:**
    - Split `encodeRosterBody` into smaller functions
    - Use shared URL builder
    - 432 → ~280 lines

---

## Final Recommendations

### Critical Actions (Do Now) 🔴

1. **Extract shared utilities** - Eliminate 260+ lines of duplication
2. **Refactor useRecognitionJob.ts** - Split into 3 focused hooks
3. **Simplify useWorkbenchMedia.ts** - Remove brittle fallback logic

### High Priority (Do Soon) 🟡

4. **Refactor useRecognitionObservations.ts** - Use shared utilities
5. **Refactor useRoster.ts** - Split complex encoding logic

### Medium Priority (Do Eventually) 🟢

6. **Add integration tests** - Ensure refactors don't break functionality
7. **Document hook patterns** - Create style guide for future hooks
8. **Add runtime validation** - Replace defensive programming with explicit validation

---

## Estimated Impact

**Before Refactoring:**

- Total Lines: 1,860
- Average Complexity: 6.0/10
- Maintainability: Poor

**After Refactoring:**

- Total Lines: ~1,110 (40% reduction)
- Average Complexity: 3.5/10
- Maintainability: Good

**Time Investment:** ~15-20 hours  
**ROI:** Significant - Easier maintenance, fewer bugs, faster feature development

---

## Conclusion

The hooks directory has **solid foundations** but suffers from:

- **Excessive duplication** (260+ lines)
- **Over-engineering** (especially useWorkbenchMedia)
- **Massive complexity** (useRecognitionJob at 585 lines)

**Priority:** Address critical issues (Phase 1-3) to reduce technical debt by ~40%.

---

# Settings Directory Audit

**Location:** `apps/wp-context-alt-text/js/admin/settings/`  
**Files:** 1 component

---

## `RecognitionSettingsPanel.tsx` ✅ **WELL-STRUCTURED** (420 lines)

**Purpose:** Settings form for recognition service configuration

### Strengths

- ✅ **Single Responsibility:** Focused settings panel component
- ✅ **Good Validation:** URL and timeout validation with user feedback
- ✅ **Controlled Form:** Proper React form state management
- ✅ **Accessibility:** Labels, ARIA roles, screen reader support
- ✅ **Error Handling:** Clear error states with inline messages
- ✅ **TypeScript:** Well-typed props and state
- ✅ **i18n:** Proper internationalization with `__()` and `sprintf()`

### Minor Issues

#### ⚠️ **Issue 1: Inline Validation Functions**

```typescript
// Lines 9-28: Could be extracted to utils
const URL_PATTERN = /^(https?:)\/\//i;
const sanitizeUrl = (value: string): string => value.trim();
const isValidUrl = (value: string): boolean => { ... }
const clampTimeout = (value: number): number => { ... }
```

**Recommendation:** Move to `@/admin/utils/validation.ts`

#### ⚠️ **Issue 2: Duplicated Fetch Logic**

```typescript
// Lines 151-180: Similar to hook fetch patterns
const response = await fetch(saveEndpoint, {
    method: "POST",
    credentials: "same-origin",
    headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...(restNonce ? { "X-WP-Nonce": restNonce } : {}),
    },
    body: JSON.stringify({ ... }),
});
```

**Recommendation:** Use shared `fetchApi()` utility from `@/admin/utils/http.ts`

#### ⚠️ **Issue 3: Complex State Management**

```typescript
// 7 separate state hooks
const [form, setForm] = useState<RecognitionSettingsPayload>(...);
const [errors, setErrors] = useState<FieldErrors>(...);
const [isSaving, setIsSaving] = useState(false);
const [isTesting, setIsTesting] = useState(false);
const [lastTestResult, setLastTestResult] = useState<TestResultState>(null);
const [flags, setFlags] = useState<FeatureFlags>(...);
```

**Recommendation:** Consider `useReducer` for complex form state

### Code Smell Score: 3/10 (good with minor improvements)

### Recommendations

1. **Extract validation utilities** to `@/admin/utils/validation.ts`
2. **Create settings hook** (`useRecognitionSettings.ts`) to move API logic out of component
3. **Use shared fetch utilities** from `@/admin/utils/http.ts`

---

# Testing Directory Audit

**Location:** `apps/wp-context-alt-text/js/admin/testing/`  
**Files:** 3 files + fixtures

---

## ✅ **EXCELLENT ORGANIZATION**

### File Structure

```
testing/
├── fixtures/
│   └── adminPayloads.ts   # Test fixtures (~400 lines)
├── mswServer.ts           # MSW server setup (16 lines)
└── renderDashboard.tsx    # Test render utility (52 lines)
```

### Verdict: **Should testing/ directory exist?**

**Answer: YES** ✅

**Reasons:**

1. **Shared Test Utilities:** `renderDashboard()` and MSW server used across multiple test files
2. **Fixtures Management:** Centralized test data prevents duplication
3. **Industry Standard:** Jest/Vitest projects commonly have `__tests__`, `__mocks__`, or `testing/` directories
4. **Clean Separation:** Keeps test infrastructure separate from production code

### Comparison to Industry Standards

| Project              | Test Utilities Location           |
| -------------------- | --------------------------------- |
| **React**            | `packages/shared/__tests__/`      |
| **Vue**              | `packages/vue/__tests__/`         |
| **Next.js**          | `test/lib/`                       |
| **Remix**            | `packages/remix-react/__tests__/` |
| **Context Alt Text** | `js/admin/testing/` ✅            |

---

## File Analysis

### 1. `mswServer.ts` ✅ **PERFECT** (16 lines)

**Purpose:** MSW (Mock Service Worker) server for testing

**Strengths:**

- ✅ Clean setup with beforeAll/afterEach/afterAll
- ✅ Proper server lifecycle management
- ✅ Export `useDashboardHandlers` for custom handlers
- ✅ Minimal and focused

**Code Smell Score:** 0/10 (perfect)

---

### 2. `renderDashboard.tsx` ✅ **EXCELLENT** (52 lines)

**Purpose:** Test rendering utility with React Query and Router

**Strengths:**

- ✅ Proper QueryClient setup with test-friendly defaults
- ✅ Optional router support with MemoryRouter
- ✅ Returns extended result with `queryClient` and `user` (userEvent)
- ✅ Clean provider wrapper pattern
- ✅ Good TypeScript types

**Minor Suggestion:**

```typescript
// Consider adding @testing-library/react-hooks support
import { renderHook } from "@testing-library/react";

export const renderDashboardHook = <T>(hook: () => T, options?: RenderDashboardOptions) =>
    renderHook(hook, { wrapper: Provider });
```

**Code Smell Score:** 1/10 (nearly perfect)

---

### 3. `fixtures/adminPayloads.ts` ✅ **WELL-ORGANIZED** (400+ lines)

**Purpose:** Centralized test fixtures for dashboard, workbench, roster, observations

**Strengths:**

- ✅ Comprehensive test data covering all major features
- ✅ Well-structured with TypeScript types
- ✅ Realistic data (dates, IDs, relationships)
- ✅ Multiple scenarios (matched/unmatched observations, synced/local roster)
- ✅ Includes both payload and expectation fixtures

**Minor Issues:**

#### ⚠️ **Issue 1: Large File Size**

- **Lines:** 400+
- **Problem:** Single file with all fixtures
- **Recommendation:** Split by domain:
    ```
    fixtures/
    ├── dashboard.ts      # Dashboard fixtures
    ├── workbench.ts      # Workbench fixtures
    ├── roster.ts         # Roster fixtures
    └── observations.ts   # Observation fixtures
    ```

#### ⚠️ **Issue 2: Hardcoded Timestamps**

```typescript
timestamp: 1_704_000_000_000,  // Brittle, will become stale
```

**Recommendation:** Use relative dates

```typescript
// fixtures/utils.ts
export const daysAgo = (days: number) =>
  Date.now() - (days * 24 * 60 * 60 * 1000);

// Usage
timestamp: daysAgo(7),  // 7 days ago
```

**Code Smell Score:** 2/10 (very good with minor improvements)

---

# Utils Directory Audit

**Location:** `apps/wp-context-alt-text/js/admin/utils/`  
**Files:** 2 utilities

---

## 1. `http.ts` ✅ **GOOD** (36 lines)

**Purpose:** HTTP response handling utilities

### Strengths

- ✅ Clean error handling with `ensureOk()`
- ✅ Flexible JSON parsing with `handleJsonResponse()`
- ✅ Handles 204 No Content correctly
- ✅ Extracts error messages from response data
- ✅ Already used by hooks (good!)

### Issues

#### 🟡 **Issue 1: Missing buildApiUrl**

**Problem:** Hooks implement URL building 3x (identified in hooks audit)

**Recommendation:** Add to this file:

```typescript
export const buildApiUrl = (
    endpoint: string,
    params?: Record<string, string | number | boolean | null | undefined>,
): string => {
    try {
        const url = new URL(endpoint, typeof window !== "undefined" ? window.location.origin : undefined);

        if (params) {
            Object.entries(params).forEach(([key, value]) => {
                if (value != null) {
                    url.searchParams.set(key, String(value));
                }
            });
        }

        return url.toString();
    } catch {
        return endpoint;
    }
};
```

#### 🟡 **Issue 2: Missing buildHeaders**

**Problem:** Header building duplicated in 3 hooks

**Recommendation:** Add to this file:

```typescript
export const buildHeaders = (restNonce?: string, includeJson = false): HeadersInit => {
    const headers: Record<string, string> = {
        Accept: "application/json",
    };

    if (includeJson) {
        headers["Content-Type"] = "application/json";
    }

    if (restNonce) {
        headers["X-WP-Nonce"] = restNonce;
    }

    return headers;
};
```

#### 🟡 **Issue 3: Missing fetchApi**

**Problem:** Fetch patterns duplicated across hooks and components

**Recommendation:** Add to this file:

```typescript
interface FetchApiOptions {
    method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
    params?: Record<string, unknown>;
    body?: unknown;
    restNonce?: string;
}

export const fetchApi = async <T = unknown>(endpoint: string, options: FetchApiOptions = {}): Promise<T> => {
    const url = options.params ? buildApiUrl(endpoint, options.params) : endpoint;

    const response = await fetch(url, {
        method: options.method ?? "GET",
        credentials: "same-origin",
        headers: buildHeaders(options.restNonce, Boolean(options.body)),
        ...(options.body ? { body: JSON.stringify(options.body) } : {}),
    });

    return handleJsonResponse(await ensureOk(response)) as T;
};
```

**Code Smell Score:** 4/10 (good but incomplete)

---

## 2. `notices.ts` ✅ **EXCELLENT** (73 lines)

**Purpose:** WordPress notice system integration

### Strengths

- ✅ Clean abstraction over WordPress notice API
- ✅ Proper fallback when WordPress API unavailable
- ✅ Type guards (`isNoticeDispatcher`)
- ✅ Error logging
- ✅ Custom event fallback for non-WP contexts
- ✅ Helper functions (`notifySuccess`, `notifyError`, etc.)

### Minor Issue

#### ⚠️ **Duplicate with `/js/admin/notices.ts`**

**Problem:** There are TWO notice files:

- `/js/admin/notices.ts` (root level)
- `/js/admin/utils/notices.ts` (utils directory)

**Investigation Needed:**

- Are these the same file?
- Are they duplicates?
- Which one is canonical?

**Recommendation:** Consolidate into utils directory and update imports

**Code Smell Score:** 2/10 (excellent with duplicate concern)

---

# Root Admin Directory Audit

**Location:** `apps/wp-context-alt-text/js/admin/` (root files)  
**Files Audited:** 10 core files + WordPress shims

---

## Core Application Files

### 1. `App.tsx` ✅ **EXCELLENT** (606 lines)

**Purpose:** Main application router and route components

**Strengths:**

- ✅ Clean component composition (App → AdminRouter → Route components)
- ✅ Proper React Router v6 patterns with MemoryRouter
- ✅ React Query integration with sensible defaults
- ✅ Good separation of concerns (Dashboard, Workbench, Roster routes)
- ✅ Feature flag guards for conditional routes
- ✅ Proper internationalization throughout
- ✅ Custom hooks for debounced search (`useDebouncedValue`)
- ✅ Analytics event tracking at appropriate boundaries
- ✅ Accessibility features (ARIA labels, roles, live regions)
- ✅ CSV export functionality with proper escaping
- ✅ Comprehensive error handling with user feedback

**Minor Issues:**

#### ⚠️ **Issue 1: Duplicated Search Normalization**

```typescript
// Line 34
const normalizeSearchQuery = (value: string): string | null => {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
};
```

**Recommendation:** Move to `@/admin/utils/validation.ts` (already suggested for other validation utilities)

#### ⚠️ **Issue 2: Test Environment Checks in Production Code**

```typescript
// Lines 31-32
const runtimeProcess = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process;
const SEARCH_INPUT_DEBOUNCE_MS = runtimeProcess?.env?.NODE_ENV === "test" ? 0 : 400;

// Lines 539-541 (handlePerPageChange)
if (runtimeProcess?.env?.NODE_ENV === "test") {
    console.info("handlePerPageChange", { current: perPage, next: nextPerPage });
}
```

**Problem:** Test instrumentation scattered in production code (same issue found in hooks)

**Recommendation:** Remove test-specific code, use test utilities for debugging

#### ⚠️ **Issue 3: Large File Size**

- **Lines:** 606
- **Components:** 4 major components (App, AdminRouter, DashboardRoute, WorkbenchRoute)

**Problem:** Not critical, but could be split

**Recommendation:** Split into separate files:

```
app/
├── index.tsx              # Main App component
├── AdminRouter.tsx        # Router setup
├── DashboardRoute.tsx     # Dashboard route
└── WorkbenchRoute.tsx     # Workbench route
```

#### ⚠️ **Issue 4: Inline CSV Export Logic**

```typescript
// Lines 198-266: 68 lines of CSV generation
const handleCoverageExport = React.useCallback(() => {
    // CSV row building
    // Cell escaping
    // Blob creation
    // Download trigger
}, [coverage]);
```

**Recommendation:** Extract to `@/admin/utils/export.ts`:

```typescript
export const exportCoverageToCSV = (coverage: CoverageCard): void => {
    // Centralized export logic
};
```

**Code Smell Score:** 3/10 (very good with minor improvements)

---

### 2. `main.tsx` ✅ **GOOD** (77 lines)

**Purpose:** Application entry point and mount logic

**Strengths:**

- ✅ Clean mount point resolution
- ✅ Fallback for missing `window.wp.svgPainter` (prevents WordPress crashes)
- ✅ Separate settings vs dashboard app mounting
- ✅ Proper React StrictMode usage
- ✅ Good error handling for missing mount elements

**Minor Issues:**

#### ⚠️ **Issue 1: Mutation of Global State**

```typescript
// Lines 13-24: Direct mutation of window.wp
if (typeof window !== "undefined") {
    const existingWp = (window as { wp?: unknown }).wp;
    if (existingWp && typeof existingWp === "object") {
        const wpGlobal = existingWp as Record<string, unknown>;
        if (!("svgPainter" in wpGlobal)) {
            Object.assign(wpGlobal, {
                svgPainter: { init: () => {} },
            });
        }
    }
}
```

**Problem:** Side effect at module load time

**Recommendation:** Move to initialization function or accept WordPress might not always have svgPainter

#### ⚠️ **Issue 2: Implicit Fallthrough Logic**

```typescript
// Lines 50-76: if/else with nested logic
if (!tryRenderSettings()) {
    // Complex mount point selection logic
}
```

**Problem:** Not obvious that settings takes precedence over dashboard

**Recommendation:** Add explanatory comment or restructure for clarity

**Code Smell Score:** 2/10 (good with minor concerns)

---

### 3. `globals.ts` ✅ **PERFECT** (26 lines)

**Purpose:** Bootstrap data access from WordPress global

**Strengths:**

- ✅ Clean abstraction over global state
- ✅ Type-safe with proper guards
- ✅ Getter/setter pattern
- ✅ Handles missing data gracefully
- ✅ Export for testing (setAdminBootstrap)

**Code Smell Score:** 0/10 (perfect)

---

### 4. `logger.ts` ✅ **EXCELLENT** (34 lines)

**Purpose:** Timestamped logging utility

**Strengths:**

- ✅ Clean logger factory pattern
- ✅ Timestamp formatting with milliseconds
- ✅ All console methods covered (log, info, warn, error, debug)
- ✅ Debug mode respects NODE_ENV
- ✅ Consistent prefix formatting

**Minor Issue:**

#### ⚠️ **Issue 1: process.env.NODE_ENV Check**

```typescript
// Line 24
if (process.env.NODE_ENV === 'development') {
```

**Problem:** Assumes bundler will replace `process.env.NODE_ENV` (works with Vite, but brittle)

**Recommendation:** Use `import.meta.env.DEV` for Vite:

```typescript
if (import.meta.env.DEV) {
    console.debug(`[${formatTimestamp()}] [${prefix}]`, ...args);
}
```

**Code Smell Score:** 1/10 (excellent)

---

### 5. `types.ts` ✅ **EXCELLENT** (297 lines)

**Purpose:** Central TypeScript type definitions

**Strengths:**

- ✅ Comprehensive type coverage for all data structures
- ✅ Well-organized by domain (Dashboard, Workbench, Roster, Settings, etc.)
- ✅ Proper interface composition
- ✅ Good naming conventions
- ✅ Optional fields clearly marked
- ✅ Discriminated unions where appropriate

**Minor Issues:**

#### ⚠️ **Issue 1: Large File**

- **Lines:** 297
- **Problem:** Single file with all types

**Recommendation:** Split by domain (optional - not critical):

```
types/
├── index.ts               # Re-exports
├── dashboard.ts           # Dashboard types
├── workbench.ts           # Workbench types
├── roster.ts              # Roster types
├── recognition.ts         # Recognition types
└── settings.ts            # Settings types
```

**Benefits:** Easier navigation, clearer dependencies

**Trade-off:** More files to manage, possible circular import risks

**Verdict:** Current structure is fine, split only if file grows beyond 500 lines

**Code Smell Score:** 1/10 (excellent)

---

### 6. `analytics.ts` ✅ **GOOD** (29 lines)

**Purpose:** Analytics event tracking

**Strengths:**

- ✅ Simple wrapper around analytics client
- ✅ Fallback to CustomEvents when analytics unavailable
- ✅ Clean API
- ✅ Type-safe event data

**Code Smell Score:** 1/10 (good)

---

### 7. `notices.ts` (root) 🔴 **DUPLICATE** (96 lines)

**Purpose:** WordPress notices integration

**CRITICAL ISSUE:** This file duplicates `utils/notices.ts` (73 lines)

**Comparison:**

| Feature            | `notices.ts` (root)     | `utils/notices.ts`      |
| ------------------ | ----------------------- | ----------------------- |
| Lines              | 96                      | 73                      |
| Type Guards        | ✅ `isNoticeDispatcher` | ✅ `isNoticeDispatcher` |
| Helper Functions   | ✅ 5 helpers            | ✅ 5 helpers            |
| Fallback Mechanism | ✅ CustomEvent          | ✅ CustomEvent          |
| Error Logging      | ✅ console.error        | ✅ console.error        |
| Implementation     | More verbose            | More concise            |

**Differences:**

- Root version has slightly different type annotations
- Root version has more verbose implementation
- **Both are functionally equivalent**

**Recommendation:**

1. **Keep `utils/notices.ts`** (cleaner, more concise)
2. **Delete `notices.ts` (root)**
3. **Update all imports:**

    ```typescript
    // OLD
    import { dispatchNotice } from "@/admin/notices";

    // NEW
    import { dispatchNotice } from "@/admin/utils/notices";
    ```

**Files Affected:**

- `App.tsx` (imports from root)
- Any other files importing from root notices

**Code Smell Score:** 9/10 (duplicate code - HIGH PRIORITY)

---

### 8. `dashboardData.ts` 🟡 **LARGE BUT NECESSARY** (620 lines)

**Purpose:** Bootstrap data normalization and fallbacks

**Strengths:**

- ✅ Centralized fallback constants
- ✅ Normalization functions for all data types
- ✅ Type-safe with comprehensive TypeScript types
- ✅ Handles missing/malformed data gracefully
- ✅ Used consistently across application

**Issues:**

#### 🟡 **Issue 1: Large File**

- **Lines:** 620
- **Problem:** Single file handling all data types

**Recommendation:** Split by domain:

```
data/
├── index.ts               # Re-exports
├── config.ts              # getDashboardConfig
├── dashboard.ts           # getDashboardData
├── workbench.ts           # getWorkbenchData
├── roster.ts              # getRosterData
├── settings.ts            # getSettingsData
└── normalization.ts       # Shared utilities
```

#### 🟡 **Issue 2: Duplicated Normalization**

```typescript
// Similar to hooks normalization
const normalizeMetric = (value: unknown, fallback: number): number => {
    const numeric = Number(value);
    if (Number.isFinite(numeric) && numeric >= 0) {
        return numeric;
    }
    return fallback;
};
```

**Recommendation:** Extract to shared `@/admin/utils/normalization.ts` (already suggested in hooks audit)

#### 🟡 **Issue 3: Complex Nested Functions**

```typescript
// Many functions like this throughout the file
const normalizeWorkbenchItem = (candidate: unknown): WorkbenchMediaItem => {
    // 50+ lines of nested normalization
    // Multiple fallback checks
    // Recursive object building
};
```

**Problem:** Hard to test individual normalization steps

**Recommendation:** Split into smaller, testable functions:

```typescript
const normalizeWorkbenchStatus = (candidate: unknown): WorkbenchMediaItem["status"] => {
    // Focused normalization
};

const normalizeWorkbenchRecognition = (candidate: unknown): WorkbenchMediaRecognition | null => {
    // Focused normalization
};

const normalizeWorkbenchItem = (candidate: unknown): WorkbenchMediaItem => {
    return {
        id: normalizeId(candidate),
        status: normalizeWorkbenchStatus(candidate),
        recognition: normalizeWorkbenchRecognition(candidate),
        // ...
    };
};
```

**Code Smell Score:** 5/10 (functional but needs refactoring)

---

# Cross-Directory Issues

## 🔴 **1. Duplicated Notice Implementations**

**Files:**

- `/js/admin/notices.ts` (110 lines)
- `/js/admin/utils/notices.ts` (73 lines)

**Impact:** Confusion about which to use, potential bugs

**Priority:** HIGH - Consolidate immediately

---

## 🔴 **2. Missing Shared Normalization Utilities**

**Duplicated Across:**

- `hooks/useRecognitionJob.ts`
- `hooks/useRecognitionObservations.ts`
- `hooks/useRoster.ts`
- `dashboardData.ts`

**Functions:**

- `toFiniteNumber()`
- `toNumberOrNull()`
- `toStringOrNull()`
- `normalizeMetric()`

**Recommendation:** Create `@/admin/utils/normalization.ts`

---

## 🟡 **3. Incomplete HTTP Utilities**

**Missing from `utils/http.ts`:**

- `buildApiUrl()` - Duplicated 3x in hooks
- `buildHeaders()` - Duplicated 3x in hooks
- `fetchApi()` - Pattern duplicated everywhere

**Recommendation:** Expand `utils/http.ts` with these utilities

---

## 🟡 **4. Settings Component Should Be Hook-Based**

**Problem:** `RecognitionSettingsPanel.tsx` contains API logic

**Recommendation:** Extract to hook:

```typescript
// hooks/useRecognitionSettings.ts
export const useRecognitionSettings = () => {
  const saveSettings = useMutation(...);
  const testConnection = useMutation(...);
  return { saveSettings, testConnection };
};
```

---

# Directory Structure Recommendations

## Current Structure Issues

```
js/admin/
├── hooks/              ✅ Good
├── settings/           ✅ Good (but only 1 file - could be in components/)
├── testing/            ✅ Excellent
├── utils/              ⚠️  Incomplete (missing functions)
├── notices.ts          🔴 DUPLICATE of utils/notices.ts
├── dashboardData.ts    🟡 Large (620 lines)
└── analytics.ts        ✅ Good
```

## Recommended Structure

```
js/admin/
├── components/         # NEW: UI components
│   └── settings/
│       └── RecognitionSettingsPanel.tsx
├── hooks/              # ✅ Keep as-is (will refactor in Phase 1-3)
├── testing/            # ✅ Keep as-is (excellent)
├── utils/              # 🔄 EXPAND with shared utilities
│   ├── http.ts         # Expand: add buildApiUrl, buildHeaders, fetchApi
│   ├── normalization.ts # NEW: Shared normalization utilities
│   ├── validation.ts   # NEW: Form validation utilities
│   └── notices.ts      # ✅ Keep (consolidate root notices.ts here)
├── data/               # NEW: Data layer
│   ├── dashboard.ts    # Split from dashboardData.ts
│   ├── workbench.ts
│   ├── roster.ts
│   └── settings.ts
├── analytics.ts        # ✅ Keep
└── types.ts            # ✅ Keep
```

---

# Summary Statistics

| Directory   | Files  | Total Lines | Issues        | Priority  |
| ----------- | ------ | ----------- | ------------- | --------- |
| `hooks/`    | 5      | 1,860       | 🔴 Critical   | Phase 1-3 |
| `settings/` | 1      | 420         | 🟡 Minor      | Low       |
| `testing/`  | 3      | ~470        | ✅ Excellent  | None      |
| `utils/`    | 2      | 109         | 🟡 Incomplete | Medium    |
| `root`      | 3      | 754         | 🟡 Moderate   | Medium    |
| **Total**   | **14** | **3,613**   | **6.2/10**    |           |

---

# Updated Refactoring Plan

## Phase 0: Critical Duplicates (NEW - HIGH PRIORITY) 🔴

**Time:** 1-2 hours  
**Impact:** Remove confusion, prevent bugs

1. **Consolidate notice implementations:**
    - Compare `/js/admin/notices.ts` and `/js/admin/utils/notices.ts`
    - Keep better implementation in `utils/notices.ts`
    - Update all imports
    - Delete duplicate

2. **Verify no other duplicates** across directories

**Files Affected:** All files importing notices

---

## Phase 1: Extract Shared Utilities (HIGH PRIORITY) 🔴

**Time:** 3-4 hours (updated from 2-3)  
**Impact:** Reduce 300+ lines of duplication

1. **Create `@/admin/utils/normalization.ts`:**
    - `toFiniteNumber()`
    - `toNumberOrNull()`
    - `toStringOrNull()`
    - `toUniqueNumericIds()`
    - `normalizeObservation()`
    - `normalizeRoster()`

2. **Expand `@/admin/utils/http.ts`:**
    - `buildApiUrl()`
    - `buildHeaders()`
    - `fetchApi()`

3. **Create `@/admin/utils/validation.ts`:**
    - `isValidUrl()`
    - `sanitizeUrl()`
    - `clampTimeout()`

4. **Update all hooks and components** to use shared utilities

**Lines Reduced:** ~300 lines  
**Files Affected:** 8 files (5 hooks, dashboardData.ts, RecognitionSettingsPanel.tsx, etc.)

---

## Phase 2-4: (Same as before)

[Previous Phase 2-4 plans remain unchanged]

---

## Final Recommendations Summary

### Critical Actions (Do Now) 🔴

1. **Consolidate duplicate notice files** - HIGH RISK
2. **Extract shared utilities** - Eliminate 300+ lines of duplication
3. **Refactor useRecognitionJob.ts** - Split into 3 focused hooks
4. **Simplify useWorkbenchMedia.ts** - Remove brittle fallback logic

### High Priority (Do Soon) 🟡

5. **Split dashboardData.ts** - 620 lines → multiple focused files
6. **Extract settings hook** - Move API logic out of component
7. **Refactor remaining hooks** - Use shared utilities

### Medium Priority (Do Eventually) 🟢

8. **Reorganize directory structure** - Move settings to components/
9. **Split test fixtures** - One file per domain
10. **Add integration tests** - Ensure refactors don't break functionality

---

## Overall Assessment

**Before Refactoring:**

- Total Lines: ~3,600
- Duplication: ~300 lines
- Average Complexity: 6.2/10
- Maintainability: Moderate

**After Refactoring:**

- Total Lines: ~2,500 (30% reduction)
- Duplication: ~50 lines (83% reduction)
- Average Complexity: 3.8/10
- Maintainability: Good

**Time Investment:** ~25-30 hours  
**ROI:** Significant - Easier maintenance, fewer bugs, faster development

---

## Architectural Observations for Higher-Level Review

**Patterns Identified:**

1. **Data Flow:**

    ```
    PHP Backend → AdminBootstrap → dashboardData.ts → hooks → components
    ```

2. **Testing Infrastructure:** ✅ Excellent (MSW + React Query + Testing Library)

3. **Type Safety:** ✅ Strong TypeScript usage throughout

4. **State Management:** React Query + useState (no Redux/Zustand needed)

5. **Code Organization:** 🟡 Good foundation, needs refactoring for scale

**Strengths:**

- ✅ Modern React patterns (hooks, functional components)
- ✅ Comprehensive testing infrastructure
- ✅ Good separation of concerns (mostly)
- ✅ Strong TypeScript typing

**Weaknesses:**

- 🔴 Excessive duplication (421 lines across 15 files)
- 🔴 Missing shared utilities layer
- 🔴 Duplicate notice implementations (2 files)
- 🟡 Some components too large (useRecognitionJob: 585 lines)
- 🟡 Directory structure could be clearer
- 🟡 Test instrumentation in production code

---

# Complete Refactoring Roadmap

## Phase 0: Critical Fixes (IMMEDIATE) 🔴

**Time:** 1-2 hours  
**Impact:** Remove duplicate notices file

1. Delete `notices.ts` (root - 96 lines)
2. Update imports in `App.tsx` to use `@/admin/utils/notices`
3. Run tests to verify
4. **Lines Saved:** 96 lines

---

## Phase 1: Extract Shared Utilities (HIGH PRIORITY) 🔴

**Time:** 4-5 hours  
**Impact:** Reduce 320+ lines of duplication

**New Files to Create:**

1. `@/admin/utils/normalization.ts` (200 lines - consolidates from 4 files)
2. `@/admin/utils/validation.ts` (50 lines - consolidates from 2 files)
3. `@/admin/utils/export.ts` (40 lines - extracts from App.tsx)
4. `@/admin/utils/formatting.ts` (30 lines - extracts from App.tsx)
5. Expand `@/admin/utils/http.ts` (add 80 lines - buildApiUrl, buildHeaders, fetchApi)

**Files Changed:** 9 files (5 hooks + dashboardData.ts + RecognitionSettingsPanel.tsx + App.tsx + http.ts)

**Lines Saved:** ~320 lines

---

## Phase 2: Refactor useRecognitionJob.ts (CRITICAL) 🔴

**Time:** 5-6 hours  
**Impact:** 585 → ~230 lines

**New Files:**

1. `hooks/useRecognitionSubmit.ts` (~100 lines)
2. `hooks/useRecognitionPoll.ts` (~80 lines)

**Refactored:** 3. `hooks/useRecognitionJob.ts` (~50 lines - composition)

**Lines Saved:** 355 lines

---

## Phase 3: Simplify useWorkbenchMedia.ts (HIGH PRIORITY) 🔴

**Time:** 3-4 hours  
**Impact:** 347 → ~150 lines

**Changes:**

- Remove brittle fallback logic (80 lines)
- Simplify shouldFetchRemote (20 lines)
- Remove test instrumentation (10 lines)
- Use shared buildApiUrl (20 lines)

**Lines Saved:** 197 lines

---

## Phase 4: Split Large Files (MEDIUM PRIORITY) 🟡

**Time:** 4-5 hours  
**Impact:** Improve maintainability

**Split App.tsx (606 lines):**

1. `app/index.tsx` (80 lines)
2. `app/AdminRouter.tsx` (60 lines)
3. `app/DashboardRoute.tsx` (220 lines)
4. `app/WorkbenchRoute.tsx` (246 lines)

**Split dashboardData.ts (620 lines):**

1. `data/index.ts` (exports only)
2. `data/config.ts` (~80 lines)
3. `data/dashboard.ts` (~150 lines)
4. `data/workbench.ts` (~150 lines)
5. `data/roster.ts` (~120 lines)
6. `data/settings.ts` (~40 lines)

**Split testing fixtures:**

1. `testing/fixtures/dashboard.ts`
2. `testing/fixtures/workbench.ts`
3. `testing/fixtures/roster.ts`
4. `testing/fixtures/observations.ts`

---

## Phase 5: Refactor Remaining Hooks (MEDIUM) 🟡

**Time:** 8-10 hours  
**Impact:** Use shared utilities

1. Refactor `useRecognitionObservations.ts` (443 → ~250 lines)
2. Refactor `useRoster.ts` (432 → ~280 lines)
3. Create `useRecognitionSettings.ts` (~100 lines)

**Lines Saved:** ~300 lines

---

## Phase 6: Polish & Documentation (LOW) 🟢

**Time:** 3-4 hours

1. Add JSDoc comments
2. Create architecture diagram
3. Write contribution guide
4. Remove all test instrumentation

---

## Final Expected Outcomes

| Metric            | Before    | After      | Improvement    |
| ----------------- | --------- | ---------- | -------------- |
| **Total Lines**   | 4,784     | ~3,200     | -33%           |
| **Duplication**   | 421 lines | ~50 lines  | -88%           |
| **Avg File Size** | 217 lines | ~90 lines  | -58%           |
| **Largest File**  | 620 lines | ~250 lines | -60%           |
| **Code Smell**    | 4.4/10    | 2.0/10     | -55%           |
| **Files**         | 22        | ~35        | +59% (smaller) |

**Total Time Investment:** 28-36 hours  
**ROI:** Massive - 88% reduction in duplication, 33% smaller codebase, better maintainability

---

**Ready for higher-level architectural review and implementation planning.**

---

---

# Components Directory Audit

**Location:** `apps/wp-context-alt-text/js/components/`  
**Subdirectories:** dashboard/, ui/, workbench/, roster/

---

## Dashboard Components Audit

**Location:** `apps/wp-context-alt-text/js/components/dashboard/`  
**Files:** 10 components

---

### 1. `Card.tsx` ✅ **PERFECT** (23 lines)

**Purpose:** Reusable card container component

**Strengths:**

- ✅ Clean, focused component
- ✅ Proper semantic HTML (`<article>`, `<header>`)
- ✅ `forwardRef` for ref forwarding
- ✅ `displayName` for debugging
- ✅ Optional className prop
- ✅ No logic, pure presentation

**Code Smell Score:** 0/10 (perfect)

---

### 2. `HeroStatus.tsx` ✅ **EXCELLENT** (34 lines)

**Purpose:** Hero banner with status message and CTA

**Strengths:**

- ✅ Clean presentation component
- ✅ Proper i18n with `sprintf()`
- ✅ Accessibility: `aria-live="polite"`, `role="status"`
- ✅ Dynamic state-based styling
- ✅ Uses UI component (`Button`)
- ✅ Handles optional timestamp

**Code Smell Score:** 0/10 (perfect)

---

### 3. `CoverageCard.tsx` ✅ **EXCELLENT** (285 lines)

**Purpose:** Coverage metrics card with donut chart, trend, and actions

**Strengths:**

- ✅ Comprehensive feature-rich component
- ✅ Excellent accessibility (ARIA labels, live regions, screen reader text)
- ✅ Analytics tracking with IntersectionObserver
- ✅ Error handling with retry mechanism
- ✅ Loading states (skeleton, refetching indicator)
- ✅ Feature flag support (workbench, trend)
- ✅ Clean separation with child components (CoverageDonut, CoverageTrend)
- ✅ Proper i18n with pluralization
- ✅ React Query integration

**Minor Issues:**

#### ⚠️ **Issue 1: Duplicated Utility Functions**

```typescript
// Lines 28-36
const clampPercent = (value: number): number => {
    if (Number.isNaN(value)) return 0;
    return Math.min(100, Math.max(0, value));
};

const formatPercent = (value: number): string => {
    if (Number.isNaN(value)) return "0";
    if (value % 1 === 0) return value.toFixed(0);
    return value.toFixed(1);
};
```

**Problem:** Similar to normalization in other files

**Recommendation:** Move to `@/admin/utils/formatting.ts`:

```typescript
export const clampPercent = (value: number): number => { ... };
export const formatPercent = (value: number): string => { ... };
```

#### ⚠️ **Issue 2: Complex State Management**

```typescript
// Lines 56-58
const hasEmittedSeen = React.useRef(false);
const hasLoggedTrend = React.useRef(false);
```

**Problem:** Multiple refs for tracking events

**Not Critical:** This is acceptable for analytics tracking, but could be consolidated

**Code Smell Score:** 2/10 (excellent with minor improvements)

---

### 4. `CoverageDonut.tsx` ✅ **EXCELLENT** (58 lines)

**Purpose:** SVG donut chart for coverage visualization

**Strengths:**

- ✅ Pure presentation component
- ✅ Math-based rendering (circumference, dashOffset)
- ✅ Accessibility (`role="img"`, `aria-label`, `aria-describedby`)
- ✅ Configurable (size, strokeWidth)
- ✅ Value clamping with dedicated function

**Minor Issue:**

#### ⚠️ **Issue 1: Duplicated clampValue**

```typescript
// Lines 10-16
const clampValue = (value: number): number => {
    if (Number.isNaN(value)) return 0;
    return Math.min(100, Math.max(0, value));
};
```

**Problem:** Same as `clampPercent` in CoverageCard

**Recommendation:** Use shared `clampPercent()` from utils

**Code Smell Score:** 1/10 (excellent)

---

### 5. `CoverageTrend.tsx` ✅ **EXCELLENT** (33 lines)

**Purpose:** Sparkline chart for coverage trend

**Strengths:**

- ✅ Clean SVG polyline rendering
- ✅ Handles empty data gracefully
- ✅ Mathematical coordinate mapping
- ✅ Decorative (`aria-hidden="true"`)
- ✅ Responsive (viewBox, preserveAspectRatio)

**Minor Issue:**

#### ⚠️ **Issue 1: Inline clamp Function**

```typescript
// Line 10
const clamp = (value: number) => Math.max(0, Math.min(100, value));
```

**Problem:** Third clamp implementation in dashboard components

**Recommendation:** Use shared utility

**Code Smell Score:** 1/10 (excellent)

---

### 6. `ActivityCard.tsx` ✅ **EXCELLENT** (98 lines)

**Purpose:** Display latest activity timestamps

**Strengths:**

- ✅ Clean component composition (ActivityRow)
- ✅ Tooltip integration for full timestamps
- ✅ Smart time formatting (minutes, hours)
- ✅ Proper i18n with pluralization
- ✅ Handles null/empty values gracefully
- ✅ Uses UI components (Tooltip)

**Minor Issue:**

#### ⚠️ **Issue 1: Complex formatActivity Function**

```typescript
// Lines 20-53: 33 lines of formatting logic
const formatActivity = (value: ...) => {
    // Null checks
    // Number/timestamp conversion
    // Relative time formatting
    // String fallback
};
```

**Recommendation:** Extract to `@/admin/utils/formatting.ts`:

```typescript
export const formatRelativeTime = (timestamp: number | string | null): string => {
    // Centralized time formatting
};
```

**Code Smell Score:** 2/10 (very good)

---

### 7. `RecognitionCard.tsx` ✅ **EXCELLENT** (107 lines)

**Purpose:** Recognition insights metrics card

**Strengths:**

- ✅ Feature flag-based routing (roster links)
- ✅ Dynamic link generation with helper function
- ✅ Warning styling for high values
- ✅ Clean helper functions (`formatRosterSyncMessage`, `renderMetricValue`)
- ✅ Conditional rendering based on roster feature
- ✅ React Router integration

**Minor Issue:**

#### ⚠️ **Issue 1: Inline formatRosterSyncMessage**

```typescript
// Lines 15-27: Helper function in component file
const formatRosterSyncMessage = (value: string | null, total: number): string => {
    // Conditional message logic
};
```

**Recommendation:** Could move to utils if reused elsewhere, but acceptable as component-specific helper

**Code Smell Score:** 1/10 (excellent)

---

### 8. `AutomationCard.tsx` ✅ **EXCELLENT** (33 lines)

**Purpose:** Automation pipeline status card

**Strengths:**

- ✅ Simple, focused component
- ✅ Proper i18n
- ✅ Conditional next run display
- ✅ Clean structure

**Code Smell Score:** 0/10 (perfect)

---

### 9. `ActionFooter.tsx` ✅ **EXCELLENT** (20 lines)

**Purpose:** Footer with action buttons and status

**Strengths:**

- ✅ Clean map over actions
- ✅ Uses Button UI component
- ✅ Semantic HTML (`<footer>`)
- ✅ Simple and focused

**Code Smell Score:** 0/10 (perfect)

---

## Dashboard Components Summary

| Component       | Lines   | Complexity | Issues              | Score         |
| --------------- | ------- | ---------- | ------------------- | ------------- |
| Card            | 23      | Low        | None                | 0/10 ✅       |
| HeroStatus      | 34      | Low        | None                | 0/10 ✅       |
| CoverageCard    | 285     | High       | Duplicated utils    | 2/10 ✅       |
| CoverageDonut   | 58      | Low        | Duplicated clamp    | 1/10 ✅       |
| CoverageTrend   | 33      | Low        | Duplicated clamp    | 1/10 ✅       |
| ActivityCard    | 98      | Medium     | Formatting function | 2/10 ✅       |
| RecognitionCard | 107     | Medium     | None (minor)        | 1/10 ✅       |
| AutomationCard  | 33      | Low        | None                | 0/10 ✅       |
| ActionFooter    | 20      | Low        | None                | 0/10 ✅       |
| **Total**       | **691** |            |                     | **0.8/10** ✅ |

**Overall Assessment:** ✅ **EXCELLENT**

**Strengths:**

- Clean, focused components
- Excellent accessibility
- Proper i18n throughout
- Good composition patterns
- Strong separation of concerns

**Minor Issues:**

- 3x clamp implementations (clampPercent, clampValue, clamp)
- formatActivity could be extracted
- formatPercent duplicated

**Recommendation:** Extract shared utilities to reduce ~30 lines of duplication

---

## UI Components Audit

**Location:** `apps/wp-context-alt-text/js/components/ui/`  
**Files:** 3 base components

---

### 10. `button.tsx` ✅ **EXCELLENT** (57 lines)

**Purpose:** Reusable button component with variants

**Strengths:**

- ✅ Uses Radix UI Slot for polymorphism
- ✅ Variant system (default, primary, subtle)
- ✅ Size system (sm, md, lg)
- ✅ `asChild` pattern for composition
- ✅ Proper forwardRef
- ✅ Type-safe with TypeScript
- ✅ Class name composition

**Code Smell Score:** 0/10 (perfect)

---

### 11. `tooltip.tsx` ✅ **EXCELLENT** (26 lines)

**Purpose:** Tooltip wrapper around Radix UI

**Strengths:**

- ✅ Clean Radix UI wrapper
- ✅ Exports primitive components
- ✅ Custom styled TooltipContent
- ✅ Arrow support
- ✅ Simple and focused

**Code Smell Score:** 0/10 (perfect)

---

### 12. `progress.tsx` ✅ **EXCELLENT** (37 lines)

**Purpose:** Progress bar component

**Strengths:**

- ✅ Radix UI wrapper
- ✅ Value clamping (0-100)
- ✅ Accessibility (ARIA attributes)
- ✅ CSS custom property for styling
- ✅ Proper forwardRef
- ✅ Type-safe

**Minor Issue:**

#### ⚠️ **Issue 1: Inline Clamping**

```typescript
// Line 16
const clamped = Math.max(0, Math.min(100, Number(value) || 0));
```

**Problem:** Fourth clamping implementation

**Recommendation:** Use shared `clampPercent()` utility

**Code Smell Score:** 1/10 (excellent)

---

## UI Components Summary

| Component | Lines   | Purpose         | Score         |
| --------- | ------- | --------------- | ------------- |
| button    | 57      | Button variants | 0/10 ✅       |
| tooltip   | 26      | Tooltip wrapper | 0/10 ✅       |
| progress  | 37      | Progress bar    | 1/10 ✅       |
| **Total** | **120** |                 | **0.3/10** ✅ |

**Overall Assessment:** ✅ **EXCELLENT**

UI components follow best practices:

- Radix UI primitives for accessibility
- Clean wrapper pattern
- Proper TypeScript types
- Consistent class naming

---

## Cross-Component Issues (Dashboard + UI)

### 🟡 **1. Duplicated Clamping Functions**

**Affected Files:** 4 components

**Implementations:**

- `CoverageCard.tsx` - `clampPercent()`
- `CoverageDonut.tsx` - `clampValue()`
- `CoverageTrend.tsx` - `clamp()`
- `progress.tsx` - inline `Math.max(0, Math.min(100, ...))`

**Impact:** ~15 lines duplicated

**Recommendation:** Create shared utility in `@/admin/utils/formatting.ts`:

```typescript
export const clampPercent = (value: number): number => {
    if (Number.isNaN(value)) return 0;
    return Math.min(100, Math.max(0, value));
};
```

**Priority:** 🟡 MEDIUM

---

### 🟡 **2. Formatting Functions in Components**

**Functions:**

- `formatPercent()` - CoverageCard
- `formatActivity()` - ActivityCard

**Recommendation:** Extract to `@/admin/utils/formatting.ts`:

```typescript
export const formatPercent = (value: number): string => { ... };
export const formatRelativeTime = (timestamp: number | string | null): string => { ... };
```

**Priority:** 🟡 LOW-MEDIUM

---

## Dashboard + UI Components: Final Assessment

**Total Files:** 12 components  
**Total Lines:** 811 lines  
**Average Complexity:** 0.7/10  
**Code Quality:** ✅ **EXCELLENT**

**Duplication Found:**

- Clamping functions: ~15 lines (4 implementations)
- Formatting functions: ~40 lines (could be shared)
- **Total:** ~55 lines (7% of codebase)

**Strengths:**

- ✅ Excellent component design
- ✅ Strong accessibility
- ✅ Proper i18n
- ✅ Clean composition
- ✅ Good separation of concerns
- ✅ Consistent patterns

**Minor Issues:**

- 🟡 Utility function duplication (low impact)
- 🟡 Could extract formatting helpers

**Recommendation:** Extract ~55 lines to shared utilities (optional, not critical)

---

**Next:** Continue audit with `workbench/` and `roster/` components...

---

## Workbench Components Audit

**Location:** `apps/wp-context-alt-text/js/components/workbench/`  
**Files:** 10 components

---

### 13. `WorkbenchApp.tsx` 🟡 **MODERATE COMPLEXITY** (265 lines)

**Purpose:** Main workbench application container

**Strengths:**

- ✅ Good state management with controlled selection
- ✅ Analytics tracking at appropriate points
- ✅ Error handling with useEffect hooks
- ✅ Proper cleanup of refs
- ✅ Integration with useRecognitionJob hook

**Issues:**

#### 🟡 **Issue 1: Multiple Ref-Based State Tracking**

```typescript
// Lines 42-47: 6 refs for error tracking
const requestErrorNoticeRef = React.useRef<string | null>(null);
const jobErrorNoticeRef = React.useRef<string | null>(null);
const requestErrorEventRef = React.useRef<string | null>(null);
const jobErrorEventRef = React.useRef<string | null>(null);
const completedJobEventRef = React.useRef<string | null>(null);
const lastAttemptedIdsRef = React.useRef<string[]>([]);
```

**Problem:** Complex ref-based de-duplication logic

**Recommendation:** Consider using `usePrevious` hook or simpler state machine

#### 🟡 **Issue 2: Test Instrumentation**

Uses `pushSnackbarNotice` instead of consolidated `dispatchNotice`

**Code Smell Score:** 5/10 (good but complex)

---

### 14. `MediaList.tsx` ✅ **EXCELLENT** (206 lines)

**Purpose:** Table view of media items with selection

**Strengths:**

- ✅ Accessible table with proper ARIA attributes
- ✅ Keyboard navigation support
- ✅ Clean helper functions (getStatusCopy, truncateAltText, getRecognitionMeta)
- ✅ Proper i18n with pluralization
- ✅ Row click handlers with event delegation

**Minor Issue:**

#### ⚠️ **Issue 1: Inline Helper Functions**

```typescript
// Lines 163-191: Helper functions in component file
const getStatusCopy = (status: ...) => { ... };
const truncateAltText = (value: string): string => { ... };
const getRecognitionMeta = (item: WorkbenchMediaItem): string | null => { ... };
```

**Recommendation:** Move to `utils.ts` in workbench directory

**Code Smell Score:** 2/10 (excellent)

---

### 15. `MediaPreview.tsx` ✅ **GOOD** (83 lines)

**Purpose:** Preview panel for selected media item

**Strengths:**

- ✅ Clean presentation component
- ✅ Proper use of formatWorkbenchDate utility
- ✅ Handles empty selection gracefully
- ✅ Semantic HTML

**Minor Issue:**

#### ⚠️ **Issue 1: Inline getStatusLabel**

```typescript
// Lines 68-78: Duplicates getStatusCopy from MediaList
const getStatusLabel = (status: ...) => { ... };
```

**Problem:** Same function as in MediaList.tsx

**Recommendation:** Move to shared utils.ts

**Code Smell Score:** 2/10 (very good)

---

### 16. `SelectionToolbar.tsx` ✅ **PERFECT** (43 lines)

**Purpose:** Toolbar for bulk actions on selected items

**Strengths:**

- ✅ Simple, focused component
- ✅ Clean button group
- ✅ Proper i18n with pluralization
- ✅ ARIA live region for selection count

**Code Smell Score:** 0/10 (perfect)

---

### 17. `SearchBar.tsx` ✅ **EXCELLENT** (118 lines)

**Purpose:** Search input with loading and error states

**Strengths:**

- ✅ Comprehensive accessibility (ARIA attributes, live regions)
- ✅ Clear button with focus management
- ✅ Error display with retry button
- ✅ Loading spinner
- ✅ Status message support
- ✅ Proper useId for unique IDs

**Code Smell Score:** 0/10 (excellent)

---

### 18. `PaginationControls.tsx` 🟡 **MODERATE COMPLEXITY** (209 lines)

**Purpose:** Pagination controls with page jump and per-page selector

**Strengths:**

- ✅ Comprehensive pagination features
- ✅ Proper accessibility
- ✅ Input validation and clamping
- ✅ Clean state management

**Issues:**

#### 🟡 **Issue 1: Test Instrumentation**

```typescript
// Lines 51-58: Test-specific console.info
if (runtimeProcess?.env?.NODE_ENV === "test") {
    console.info("PaginationControls::handlePerPageChange", {...});
}
```

**Problem:** Test code in production component (same as admin files)

**Recommendation:** Remove test instrumentation

**Code Smell Score:** 3/10 (good)

---

### 19. `RecognitionActions.tsx` 🔴 **VERY LARGE** (580 lines)

**Purpose:** Recognition job triggering and results display

**Issues:**

#### 🔴 **Issue 1: Massive File Size**

- **Lines:** 580
- **Problem:** Should be split into multiple components

**Recommendation:** Split into:

- `RecognitionActions.tsx` (main component - 150 lines)
- `RecognitionResultRow.tsx` (results display - 200 lines)
- `RecognitionObservationRow.tsx` (observation row - 150 lines)
- `RecognitionProgress.tsx` (progress UI - 80 lines)

#### 🟡 **Issue 2: Complex State Logic**

```typescript
// Lines 72-106: Complex progressPhase calculation
const progressPhase = React.useMemo(() => {
    if (isSubmitting) return "submitting";
    if (isPolling || jobStatus === "processing") return "processing";
    if (shouldRenderProgress) return "pending";
    return "idle";
}, [isSubmitting, isPolling, jobStatus, shouldRenderProgress]);
```

#### 🟡 **Issue 3: Inline Formatting Functions**

```typescript
// Line 449: formatStatusLabel
const formatStatusLabel = (status: string): string => {
    // Switch statement for status labels
};
```

**Problem:** Should be in utils

**Code Smell Score:** 7/10 (needs refactoring)

---

### 20. `BulkAltTextPanel.tsx` ✅ **GOOD** (50 lines)

**Purpose:** Bulk alt-text generation panel (stub)

**Strengths:**

- ✅ Clean component structure
- ✅ Feature flag support
- ✅ Disabled state with helpful messages
- ✅ Prepared for future implementation

**Code Smell Score:** 1/10 (good)

---

### 21. `utils.ts` ✅ **GOOD** (24 lines)

**Purpose:** Workbench utility functions

**Strengths:**

- ✅ Clean date formatting with Intl API
- ✅ Error handling with fallback
- ✅ Logger integration

**Recommendation:** Add more shared utilities here:

- `getStatusCopy()` from MediaList
- `truncateAltText()` from MediaList
- `getRecognitionMeta()` from MediaList
- `formatStatusLabel()` from RecognitionActions

**Code Smell Score:** 1/10 (good)

---

## Workbench Components Summary

| Component          | Lines     | Complexity | Issues         | Score         |
| ------------------ | --------- | ---------- | -------------- | ------------- |
| WorkbenchApp       | 265       | High       | Ref complexity | 5/10 🟡       |
| MediaList          | 206       | Medium     | Inline helpers | 2/10 ✅       |
| MediaPreview       | 83        | Low        | Inline helper  | 2/10 ✅       |
| SelectionToolbar   | 43        | Low        | None           | 0/10 ✅       |
| SearchBar          | 118       | Medium     | None           | 0/10 ✅       |
| PaginationControls | 209       | Medium     | Test code      | 3/10 ✅       |
| RecognitionActions | 580       | Very High  | Massive file   | 7/10 🔴       |
| BulkAltTextPanel   | 50        | Low        | None           | 1/10 ✅       |
| utils.ts           | 24        | Low        | Incomplete     | 1/10 ✅       |
| **Total**          | **1,578** |            |                | **2.3/10** ✅ |

**Overall Assessment:** ✅ **GOOD** with one large file

**Strengths:**

- Excellent accessibility throughout
- Clean component composition
- Good separation of concerns (mostly)
- Strong i18n support

**Issues:**

- RecognitionActions.tsx is too large (580 lines - should be 4 components)
- Some inline helper functions should move to utils.ts
- Test instrumentation in production code

**Recommendation:** Split RecognitionActions.tsx and extract shared utilities (~80 lines saved)

---

## Roster Component Audit

**Location:** `apps/wp-context-alt-text/js/components/roster/`  
**Files:** 1 massive file

---

### 22. `RosterRoute.tsx` 🔴 **EXTREMELY LARGE** (2,503 lines!)

**Purpose:** Complete roster management route with observations panel, table, editor, and pagination

**CRITICAL ISSUES:**

#### 🔴 **Issue 1: Massive Monolithic Component**

- **Lines:** 2,503 lines in a single file
- **Components:** 10+ components defined in one file
- **Functions:** 20+ utility functions inline
- **Problem:** Unmaintainable, violates Single Responsibility Principle

**File Breakdown:**

- Utility functions (lines 1-200): 200 lines
- RosterObservationsPanel (lines 201-700): 500 lines
- RosterRoute (main component, lines 701-1500): 800 lines
- RosterStats (lines 1501-1550): 50 lines
- RosterTable (lines 1551-1700): 150 lines
- RosterEditor (lines 1701-2200): 500 lines
- RosterPagination (lines 2201-2300): 100 lines
- ObservationPreview (lines 2301-2400): 100 lines
- RosterObservationPrompt (lines 2401-2503): 103 lines

#### 🔴 **Issue 2: Duplicated Normalization Functions**

```typescript
// Lines 30-70: Similar to hooks normalization
const isFiniteNumber = (value: unknown): value is number => { ... };
const normalizeConfidence = (value: unknown): number | null => { ... };
const formatPercentage = (value: number | null | undefined): string | null => { ... };
```

**Problem:** Should use shared utils from Phase 1

#### 🔴 **Issue 3: Complex Nested Logic**

```typescript
// Lines 100-200: 100+ lines of candidate sorting/matching logic
const getTopCandidate = (record: ...) => { ... };
const resolveSuggestedMatchLabel = (record: ..., lookup: ..., top: ...) => { ... };
const getRosterConfidenceValue = (record: ..., top: ...) => { ... };
const resolveSuggestedRemoteId = (record: ..., lookup: ..., top: ...) => { ... };
```

**Problem:** Business logic should be in hooks or utilities

#### 🔴 **Issue 4: Deep Component Nesting**

```typescript
RosterRoute
  ├── RosterStats
  ├── RosterObservationsPanel
  │   ├── ObservationPreview (per observation)
  │   └── Multiple nested lists
  ├── RosterTable
  │   └── StatusBadge (per row)
  ├── RosterEditor
  │   ├── StatusBadge
  │   ├── MediaAttachmentUploader (referenced but not shown)
  │   └── Complex form logic
  ├── RosterObservationPrompt
  └── RosterPagination
```

**Problem:** All components in single file makes navigation impossible

#### 🟡 **Issue 5: State Management Complexity**

```typescript
// Lines 700-750: 15+ useState hooks
const [searchInput, setSearchInput] = React.useState<string>("");
const [search, setSearch] = React.useState<string | null>(null);
const [page, setPage] = React.useState<number>(1);
const [perPage, setPerPage] = React.useState<number>(20);
const [editing, setEditing] = React.useState<RosterEntry | null>(null);
const [isSubmitting, setIsSubmitting] = React.useState<boolean>(false);
const [statusFilter, setStatusFilter] = React.useState<...>(null);
const [draftValues, setDraftValues] = React.useState<...>(null);
const [observationPrompt, setObservationPrompt] = React.useState<...>(null);
// ... more state
```

**Problem:** Could benefit from useReducer or state machine

#### 🟡 **Issue 6: URL Parameter Management**

```typescript
// Lines 800-950: 150 lines of URL param parsing
React.useEffect(() => {
    const params = new URLSearchParams(location.search ?? "");
    const filterParam = params.get("filter");
    const remoteIdParam = params.get("remoteId");
    // ... 140 more lines of param parsing
}, [location.search, ...]);
```

**Problem:** Should be extracted to custom hook or utility

**Code Smell Score:** 9.5/10 (critical refactoring needed)

---

### Recommended Structure for RosterRoute

**Current:** 1 file, 2,503 lines

**Recommended:**

```
roster/
├── RosterRoute.tsx                    # Main route (200 lines)
├── RosterObservationsPanel.tsx        # Observations panel (300 lines)
├── RosterTable.tsx                    # Entry table (150 lines)
├── RosterEditor.tsx                   # Entry editor form (400 lines)
├── RosterPagination.tsx               # Pagination controls (100 lines)
├── RosterStats.tsx                    # Stats summary (50 lines)
├── ObservationPreview.tsx             # Observation preview (100 lines)
├── RecognitionObservationRow.tsx      # Observation row (150 lines)
├── RosterObservationPrompt.tsx        # Observation prompt modal (100 lines)
├── StatusBadge.tsx                    # Status badge (30 lines)
├── hooks/
│   ├── useRosterUrlParams.ts          # URL parameter management (150 lines)
│   └── useObservationMatching.ts      # Observation matching logic (200 lines)
└── utils/
    ├── rosterFormatting.ts            # Formatting utilities (80 lines)
    ├── observationMatching.ts         # Matching logic (150 lines)
    └── confidenceCalculation.ts       # Confidence calc (80 lines)
```

**Total:** 15 files averaging ~160 lines each

**Lines Saved:** ~500 lines through deduplication

---

## Roster Component Summary

| Component       | Lines | Should Be | Complexity | Score     |
| --------------- | ----- | --------- | ---------- | --------- |
| RosterRoute.tsx | 2,503 | 15 files  | Extreme    | 9.5/10 🔴 |

**Overall Assessment:** 🔴 **CRITICAL - Immediate Refactoring Required**

**This is the worst code smell in the entire codebase.**

**Priority Actions:**

1. 🔴 Split into 15 separate files
2. 🔴 Extract shared utilities
3. 🔴 Create custom hooks for URL management
4. 🔴 Move business logic out of component

**Estimated Refactoring Time:** 12-15 hours

---

## Complete Components Audit Summary

### Statistics by Directory

| Directory  | Files  | Lines     | Avg Complexity | Score      |
| ---------- | ------ | --------- | -------------- | ---------- |
| dashboard/ | 9      | 691       | Low            | 0.8/10 ✅  |
| ui/        | 3      | 120       | Low            | 0.3/10 ✅  |
| workbench/ | 9      | 1,578     | Medium         | 2.3/10 ✅  |
| roster/    | 1      | 2,503     | Extreme        | 9.5/10 🔴  |
| **Total**  | **22** | **4,892** |                | **3.2/10** |

### Issues Found

| Issue Type              | Count  | Lines Affected | Priority    |
| ----------------------- | ------ | -------------- | ----------- |
| Massive files           | 2      | 3,083          | 🔴 Critical |
| Duplicated utilities    | ~15    | ~150           | 🟡 Medium   |
| Test instrumentation    | 2      | ~20            | 🟡 Medium   |
| Inline helper functions | ~8     | ~200           | 🟢 Low      |
| **Total**               | **27** | **~3,453**     |             |

---

## Components Refactoring Plan

### Phase A: Split Massive Files (CRITICAL) 🔴

**Time:** 12-16 hours  
**Impact:** Make code maintainable

**Tasks:**

1. **Split RosterRoute.tsx** (2,503 → 15 files):
    - Extract 9 components to separate files
    - Create 2 custom hooks
    - Move utilities to 3 utility files
    - **Lines reduced:** 2,503 → ~2,000 (split across 15 files)

2. **Split RecognitionActions.tsx** (580 → 4 files):
    - RecognitionActions.tsx (main - 150 lines)
    - RecognitionResultRow.tsx (200 lines)
    - RecognitionObservationRow.tsx (150 lines)
    - RecognitionProgress.tsx (80 lines)
    - **Lines reduced:** 580 → ~500 (split across 4 files)

**Files Created:** 18 new files  
**Maintainability:** Dramatic improvement

---

### Phase B: Extract Shared Utilities (MEDIUM) 🟡

**Time:** 2-3 hours  
**Impact:** Reduce 150+ lines of duplication

**Tasks:**

1. **Expand `workbench/utils.ts`:**
    - Add `getStatusCopy()`
    - Add `truncateAltText()`
    - Add `getRecognitionMeta()`
    - Add `formatStatusLabel()`

2. **Create `roster/utils/rosterFormatting.ts`:**
    - Extract `formatPercentage()`
    - Extract `normalizeConfidence()`

3. **Create `components/utils/formatting.ts`:**
    - Shared `clampPercent()`
    - Shared `formatPercent()`
    - Shared `formatRelativeTime()`

**Lines Saved:** ~150 lines

---

### Phase C: Remove Test Instrumentation (LOW) 🟢

**Time:** 30 minutes  
**Impact:** Clean production code

**Files:**

- `PaginationControls.tsx`
- `WorkbenchApp.tsx`

**Lines Removed:** ~20 lines

---

## Final Components Assessment

**Overall Quality:** ✅ **GOOD** except for 1 critical file

**Strengths:**

- ✅ Excellent dashboard components (0.8/10)
- ✅ Clean UI primitives (0.3/10)
- ✅ Good workbench components (2.3/10)
- ✅ Strong accessibility throughout
- ✅ Comprehensive i18n
- ✅ Good component composition

**Critical Weakness:**

- 🔴 RosterRoute.tsx is 2,503 lines (should be 15 files)
- 🔴 RecognitionActions.tsx is 580 lines (should be 4 files)

**After Refactoring:**

- Split 2 massive files into 19 components
- Extract ~150 lines of shared utilities
- Remove ~20 lines of test code
- **Result:** 4,892 → ~4,700 lines across 39 well-organized files
- **Avg file size:** 122 lines (down from 222)
- **Maintainability:** Excellent

---

**Components audit complete! Ready to continue with final recommendations...**

---

## Types Directory Audit

**Location:** `apps/wp-context-alt-text/js/types/`  
**Files:** 1 type declaration file

---

### 23. `wp-element.d.ts` ✅ **PERFECT** (30 lines)

**Purpose:** TypeScript type declarations for WordPress element package module paths

**Content:**

```typescript
declare module "@wordpress/element/build-module/react" {
  import * as ReactNamespace from "react";

  export const concatChildren: (...) => ReactNode[];
  export const switchChildrenNodeName: (...) => ReactNode;
  export * from "react";
  const ReactDefault: typeof ReactNamespace;
  export default ReactDefault;
}

declare module "@wordpress/element/build-module/react-platform" {
  import type * as ReactDOMNamespace from "react-dom";
  import type * as ReactDOMClientNamespace from "react-dom/client";

  export * from "react-dom";
  export * from "react-dom/client";

  const ReactPlatform: typeof ReactDOMNamespace & typeof ReactDOMClientNamespace;
  export default ReactPlatform;
}
```

**Strengths:**

- ✅ Clean module declarations for WordPress internal paths
- ✅ Proper TypeScript type re-exports
- ✅ Documents WordPress element helper functions (concatChildren, switchChildrenNodeName)
- ✅ Required for proper type checking with WordPress-provided React

**Code Smell Score:** 0/10 (perfect)

---

## React Version Strategy Analysis

### Current Setup

**Package Configuration:**

- `@wordpress/element@6.32.0` - installed
- `react` / `react-dom` - **NOT installed** (intentional)
- `@types/react@^18.3.1` - installed (devDependency)
- `@types/react-dom@^18.3.1` - installed (devDependency)

**WordPress Element Dependencies:**

```
@wordpress/element@6.32.0 depends on:
  - react: ^18.3.0
  - react-dom: ^18.3.0
  - @types/react: ^18.2.79
  - @types/react-dom: ^18.2.25
```

**Actual React in node_modules:**

- React 19.1.1 (from Radix UI, Storybook, React Router dependencies)
- React 18.3.1 (from @wordpress/element transitive dependencies)

**Build Configuration (vite.config.ts):**

```typescript
resolve: {
    alias: [
        { find: /^react$/, replacement: "js/admin/wp-react.ts" },
        { find: /^react-dom$/, replacement: "js/admin/wp-react-dom.ts" },
        { find: /^react-dom\/client$/, replacement: "js/admin/wp-react-dom-client.ts" },
        { find: /^react\/jsx-runtime$/, replacement: "js/admin/wp-react-jsx-runtime.ts" },
        { find: "@wordpress/element", replacement: "js/admin/wp-wordpress-element.ts" },
    ];
}
```

**Result:** All React imports are redirected to use WordPress-provided React via `window.wp.element`

---

### Analysis: Using WordPress React vs Bundling Separate React

#### ✅ **RECOMMENDED: Current Approach (WordPress React)**

**Benefits:**

1. **🟢 Bundle Size Reduction**
    - React + React-DOM: ~140KB minified + gzipped
    - Your plugin: Saves 140KB per page load
    - **Impact:** Faster load times, better performance

2. **🟢 No Version Conflicts**
    - WordPress Core uses React 18.3.x
    - Your plugin uses same React instance
    - **Impact:** No "multiple React copies" runtime errors
    - No hydration mismatches or hook violations

3. **🟢 WordPress Ecosystem Compatibility**
    - All WordPress plugins share same React instance
    - Interoperability with other plugins (Gutenberg, etc.)
    - **Impact:** Plugin plays nice with WordPress ecosystem

4. **🟢 WordPress Updates Handle React Updates**
    - When WordPress updates React, your plugin automatically benefits
    - No manual React upgrade work needed
    - **Impact:** Less maintenance burden

5. **🟢 Standard WordPress Plugin Pattern**
    - Matches WordPress best practices
    - Expected by WordPress plugin review team
    - **Impact:** Easier approval, better reputation

**Current Implementation Score:** 10/10 ✅ **EXCELLENT**

---

#### ❌ **NOT RECOMMENDED: Bundling Separate React**

**Drawbacks:**

1. **🔴 Massive Bundle Size Increase**
    - Would add ~140KB to your plugin bundle
    - **Impact:** Slower page loads, poor performance scores

2. **🔴 Multiple React Instances**
    - Two React copies on same page (WordPress + yours)
    - **Impact:** Runtime errors, context issues, hook violations

3. **🔴 Version Conflicts**
    - WordPress uses React 18.3.x
    - If you bundle React 19.x, incompatibility issues arise
    - **Impact:** Bugs, crashes, unpredictable behavior

4. **🔴 Plugin Ecosystem Fragmentation**
    - Your plugin can't share state/context with other WordPress plugins
    - **Impact:** Isolated from WordPress React ecosystem

5. **🔴 Manual React Maintenance**
    - You must manually update React when security patches released
    - **Impact:** Security risk, maintenance burden

---

### React 18 vs React 19 Consideration

**WordPress Core Status (October 2025):**

- WordPress 6.7 (latest): Ships React 18.3.x
- WordPress 6.8 (beta): Still React 18.3.x
- No official React 19 migration timeline announced

**Your Dependencies:**

- `@wordpress/element@6.32.0` → requires React 18.3.x
- Radix UI, React Router → compatible with React 18.3.x
- `@types/react@^18.3.1` → matches WordPress version

**Recommendation:** ✅ **Stay on React 18 via WordPress**

**Reasoning:**

1. WordPress will migrate to React 19 when stable
2. Your plugin automatically benefits from WordPress upgrade
3. No compatibility issues with WordPress ecosystem
4. Radix UI and React Router work fine with React 18

**If you bundled React 19 separately:**

- ❌ Incompatible with WordPress React 18
- ❌ Context/state can't be shared between instances
- ❌ Would need to monitor WordPress React version changes
- ❌ Risk of breaking when WordPress updates React

---

### Vite Alias Configuration Review

**Current Aliases:** ✅ **EXCELLENT**

```typescript
alias: [
    { find: /^react$/, replacement: "js/admin/wp-react.ts" },
    { find: /^react-dom$/, replacement: "js/admin/wp-react-dom.ts" },
    { find: /^react-dom\/client$/, replacement: "js/admin/wp-react-dom-client.ts" },
    { find: /^react\/jsx-runtime$/, replacement: "js/admin/wp-react-jsx-runtime.ts" },
    { find: /^react\/jsx-dev-runtime$/, replacement: "js/admin/wp-react-jsx-dev-runtime.ts" },
    { find: "@wordpress/element", replacement: "js/admin/wp-wordpress-element.ts" },
    { find: "@wordpress/i18n", replacement: "js/admin/wp-wordpress-i18n.ts" },
];
```

**Strengths:**

- ✅ Comprehensive coverage (all React entry points)
- ✅ JSX runtime aliased (React 17+ JSX transform)
- ✅ Both dev and prod JSX runtimes covered
- ✅ React-DOM client APIs aliased (createRoot)
- ✅ WordPress globals properly mapped

**Score:** 10/10 (perfect implementation)

---

### Shim Files Quality Check

**Already audited in Admin Root Files section:**

- `wp-react.ts` - ✅ Score: 0/10 (perfect)
- `wp-react-dom.ts` - ✅ Score: 0/10 (perfect)
- `wp-react-dom-client.ts` - ✅ Score: 0/10 (perfect)
- `wp-react-jsx-runtime.ts` - ✅ Score: 0/10 (perfect)
- `wp-react-jsx-dev-runtime.ts` - ✅ Score: 0/10 (perfect)
- `wp-wordpress-element.ts` - ✅ Score: 0/10 (perfect)
- `wp-wordpress-i18n.ts` - ✅ Score: 0/10 (perfect)

All shim files are correctly implemented.

---

## Types & React Strategy Summary

| Aspect                   | Status           | Score    |
| ------------------------ | ---------------- | -------- |
| Type declarations        | ✅ Perfect       | 0/10     |
| React version strategy   | ✅ Optimal       | 0/10     |
| Vite alias configuration | ✅ Comprehensive | 0/10     |
| Shim file implementation | ✅ Correct       | 0/10     |
| **Overall**              | ✅ **EXCELLENT** | **0/10** |

---

## Final React Version Recommendation

### ✅ **KEEP CURRENT APPROACH**

**Your current setup is OPTIMAL for WordPress plugin development.**

**Summary:**

1. ✅ Use WordPress-provided React 18.3.x via `@wordpress/element`
2. ✅ Do NOT install react/react-dom directly
3. ✅ Maintain Vite aliases to redirect to WordPress globals
4. ✅ Let WordPress handle React version updates
5. ✅ Keep `@types/react@^18.x` for TypeScript

**Benefits:**

- 140KB smaller bundle
- No version conflicts
- WordPress ecosystem compatibility
- Automatic React updates via WordPress
- Standard WordPress plugin pattern

**When to Reconsider:**

- ❌ Never for WordPress plugin context
- ✅ Only if building standalone web app (not WordPress plugin)

**Current Implementation Quality:** 10/10 ✅ **PERFECT**

---

**Types audit and React strategy analysis complete!**

---

## Configuration Files Audit

### TypeScript Configuration (`tsconfig.json`)

**Location:** `apps/wp-context-alt-text/tsconfig.json`  
**Lines:** 20

**Current Configuration:**

```json
{
    "compilerOptions": {
        "target": "ES2020",
        "module": "ESNext",
        "moduleResolution": "bundler",
        "jsx": "react",
        "esModuleInterop": true,
        "strict": true,
        "noUncheckedIndexedAccess": true,
        "lib": ["DOM", "DOM.Iterable", "ES2020"],
        "baseUrl": "./",
        "paths": {
            "@/*": ["js/*"],
            "react/jsx-runtime": ["js/admin/wp-react-jsx-runtime.ts"],
            "react/jsx-dev-runtime": ["js/admin/wp-react-jsx-dev-runtime.ts"]
        },
        "types": ["node"]
    },
    "include": ["js/**/*", ".storybook/**/*"],
    "exclude": ["node_modules", "public"]
}
```

---

#### ✅ **Strengths:**

1. **Strict Mode Enabled** ✅
    - `"strict": true` enables all strict type checking
    - `"noUncheckedIndexedAccess": true` catches array/object access bugs
    - **Impact:** Excellent type safety

2. **Modern ECMAScript Target** ✅
    - `"target": "ES2020"` - Modern JavaScript features
    - `"lib": ["DOM", "DOM.Iterable", "ES2020"]` - Browser + modern JS APIs
    - **Impact:** Good balance of features and browser support

3. **Bundler Module Resolution** ✅
    - `"moduleResolution": "bundler"` - Optimized for Vite
    - `"module": "ESNext"` - Modern ESM modules
    - **Impact:** Works perfectly with Vite

4. **Path Aliases** ✅
    - `"@/*": ["js/*"]` - Clean imports (`@/components/Button`)
    - JSX runtime aliased to WordPress shims
    - **Impact:** Better DX, matches Vite config

5. **WordPress Integration** ✅
    - `"jsx": "react"` - Classic JSX transform (WordPress compatible)
    - JSX runtime paths redirect to WordPress shims
    - **Impact:** Proper WordPress React integration

---

#### 🔴 **Critical Issues:**

##### Issue 1: Missing `skipLibCheck` Causes Type Declaration Errors

**Problem:**

```bash
js/types/wp-element.d.ts(13,17): error TS2498: Module 'react' uses 'export ='
and cannot be used with 'export *'.

js/types/wp-element.d.ts(23,3): error TS2308: Module "react-dom" has already
exported a member named 'Container'.

node_modules/@tanstack/react-query/build/modern/QueryErrorResetBoundary.d.ts(17,107):
error TS2724: Has no exported member named 'JSX'.
```

**Root Cause:**

- TypeScript is checking ALL `.d.ts` files in `node_modules`
- React types use `export =` (CommonJS style)
- Your `wp-element.d.ts` tries to re-export with `export *` (ESM style)
- This causes type system conflicts

**Solution:**

```json
"compilerOptions": {
  "skipLibCheck": true,  // Add this
  // ... rest
}
```

**Why This Works:**

- Skips type checking third-party `.d.ts` files
- Only checks YOUR code's type safety
- Standard practice for all modern TypeScript projects
- **Used by Next.js, Create React App, Vite templates, etc.**

**Impact:** Eliminates ~85 type errors from third-party libraries

---

##### Issue 2: `jsx: "react"` Causes UMD Global Errors in Tests

**Problem:**

```bash
js/admin/App.test.tsx(154,39): error TS2686: 'React' refers to a UMD global,
but the current file is a module. Consider adding an import instead.
```

**Root Cause:**

- `"jsx": "react"` expects global `React` variable
- Test files are ES modules with explicit imports
- TypeScript sees JSX but no imported `React` variable
- Suggests adding `import React from "react"`

**Current Workaround:**

- You're using classic JSX transform for WordPress compatibility
- At runtime, JSX transforms are redirected to WordPress globals
- TypeScript doesn't understand this

**Better Solution:**

```json
"compilerOptions": {
  "jsx": "react-jsx",  // Modern automatic JSX transform
  // ... rest
}
```

**Why This Works:**

- `react-jsx` uses automatic JSX runtime (React 17+)
- No need for `React` variable in scope
- Your path aliases already redirect to WordPress shims
- **Compatible with your Vite config**

**Alternative (Keep Current):**

- Add `/* @jsxImportSource react */` to test files
- Or add `import React from "react"` to all test files
- **Less clean, more verbose**

**Impact:** Eliminates ~60 UMD global errors in test files

---

##### Issue 3: Type Mismatches in Test Files

**Problems:**

```bash
js/admin/dashboardContracts.test.ts(34,27): error TS2345:
Type 'WorkbenchContractItem' is not assignable to type 'WorkbenchMediaItem'.
Types of property 'id' are incompatible.
Type 'string | number' is not assignable to type 'string'.

js/admin/dashboardData.test.ts(104,29): error TS2322:
Type 'number' is not assignable to type 'string'.

js/admin/dashboardData.test.ts(151,29): error TS2322:
Type '"unknown"' is not assignable to type 'AdminRouteKey | undefined'.
```

**Root Cause:**

- Contract types allow `id: string | number`
- Application types require `id: string`
- Test fixtures using wrong types

**Solution:** Fix test fixtures to match strict types

**Impact:** 4 test type errors to fix

---

##### Issue 4: WordPress Media Type Issue

**Problem:**

```bash
js/components/roster/RosterRoute.tsx(257,49): error TS2322:
Type 'Function' is not assignable to type '(options: Record<string, unknown>) => MediaFrame'.
```

**Root Cause:**

- `wp.media()` is typed as generic `Function`
- Should be `(options: Record<string, unknown>) => MediaFrame`

**Solution:** Add proper type declaration or type assertion

**Impact:** 1 type error in RosterRoute.tsx

---

#### 🟡 **Recommendations:**

##### Recommendation 1: Add Missing Compiler Options

**Add for Better Type Safety:**

```json
"compilerOptions": {
  // ... existing options
  "skipLibCheck": true,                    // Fix library type conflicts
  "jsx": "react-jsx",                      // Modern JSX transform
  "isolatedModules": true,                 // Vite requirement
  "allowImportingTsExtensions": true,      // Allow .ts in imports (Vite bundler)
  "noEmit": true,                          // Don't emit (Vite handles bundling)
  "forceConsistentCasingInFileNames": true // Prevent case-sensitivity issues
}
```

**Why These Matter:**

- `isolatedModules`: Required for Vite (each file compiled independently)
- `allowImportingTsExtensions`: Allows `import { X } from "./file.ts"` with bundler
- `noEmit`: TypeScript only for type checking, Vite handles transpilation
- `forceConsistentCasingInFileNames`: Prevents cross-platform issues

---

##### Recommendation 2: Fix Type Declaration File

**Current `wp-element.d.ts`:**

```typescript
declare module "@wordpress/element/build-module/react" {
    export * from "react"; // ❌ Conflicts with React's export =
    // ...
}
```

**Fixed:**

```typescript
declare module "@wordpress/element/build-module/react" {
  import type * as React from "react";

  export const concatChildren: (...) => React.ReactNode[];
  export const switchChildrenNodeName: (...) => React.ReactNode;

  // Don't re-export everything, just what's needed
  export type {
    ReactNode,
    ReactElement,
    ComponentType,
    // ... specific exports
  } from "react";

  export default React;
}
```

**Why:** Avoids `export *` with CommonJS modules

---

##### Recommendation 3: Add `types/` Directory to Paths

**Current Issue:** Types in `js/types/` but not in `paths`

**Add:**

```json
"paths": {
  "@/*": ["js/*"],
  "@types/*": ["js/types/*"],  // Explicit types path
  "react/jsx-runtime": ["js/admin/wp-react-jsx-runtime.ts"],
  "react/jsx-dev-runtime": ["js/admin/wp-react-jsx-dev-runtime.ts"]
}
```

---

#### 📊 **TypeScript Config Score:**

| Aspect                     | Status         | Score    |
| -------------------------- | -------------- | -------- |
| Strict mode                | ✅ Enabled     | 0/10     |
| Module resolution          | ✅ Bundler     | 0/10     |
| Path aliases               | ✅ Configured  | 0/10     |
| WordPress integration      | ✅ Correct     | 0/10     |
| Missing skipLibCheck       | 🔴 Critical    | 9/10     |
| JSX config                 | 🟡 Suboptimal  | 5/10     |
| Missing isolatedModules    | 🟡 Recommended | 3/10     |
| Type declaration conflicts | 🔴 Has errors  | 7/10     |
| **Overall**                | 🟡 **GOOD**    | **6/10** |

**Summary:** Strong foundation, but 85+ type errors from missing `skipLibCheck` and JSX config

---

### Vite Configuration (`vite.config.ts`)

**Location:** `apps/wp-context-alt-text/vite.config.ts`  
**Lines:** 41

**Current Configuration:**

```typescript
export default defineConfig(({ mode }) => ({
  plugins: [react({ jsxRuntime: "classic" })],
  publicDir: false,
  optimizeDeps: { exclude: ["@wordpress/data"] },
  build: {
    outDir: "public/assets/dist",
    emptyOutDir: true,
    sourcemap: mode === "development",
    manifest: true,
    rollupOptions: {
      input: { admin: "js/admin/main.tsx" },
      external: ["@wordpress/data"],
      output: {
        entryFileNames: `js/[name].js`,
        chunkFileNames: `js/[name]-[hash].js`,
        assetFileNames: (assetInfo) => { ... },
        globals: { "@wordpress/data": "wp.data" }
      }
    }
  },
  resolve: {
    alias: [
      { find: "@wordpress/element", replacement: "js/admin/wp-wordpress-element.ts" },
      { find: "@wordpress/i18n", replacement: "js/admin/wp-wordpress-i18n.ts" },
      { find: "@", replacement: "js" },
      { find: /^react\/jsx-runtime$/, replacement: "js/admin/wp-react-jsx-runtime.ts" },
      { find: /^react\/jsx-dev-runtime$/, replacement: "js/admin/wp-react-jsx-dev-runtime.ts" },
      { find: /^react-dom\/client$/, replacement: "js/admin/wp-react-dom-client.ts" },
      { find: /^react-dom$/, replacement: "js/admin/wp-react-dom.ts" },
      { find: /^react$/, replacement: "js/admin/wp-react.ts" }
    ]
  }
}));
```

---

#### ✅ **Strengths:**

1. **WordPress External Dependencies** ✅
    - `external: ["@wordpress/data"]` - Don't bundle WordPress globals
    - `globals: { "@wordpress/data": "wp.data" }` - Map to window globals
    - **Impact:** Smaller bundle, WordPress compatibility

2. **Comprehensive React Aliasing** ✅
    - All React entry points aliased (react, react-dom, jsx-runtime)
    - **Impact:** Perfect WordPress integration

3. **Source Maps** ✅
    - `sourcemap: mode === "development"` - Dev maps only
    - **Impact:** Debuggable in dev, optimized in prod

4. **Build Manifest** ✅
    - `manifest: true` - Generates manifest.json
    - **Impact:** PHP can discover hashed asset filenames

5. **Asset Organization** ✅
    - JS in `js/`, CSS in `css/`, other in `assets/`
    - **Impact:** Clean output structure

---

#### 🟡 **Issues & Recommendations:**

##### Issue 1: JSX Runtime Mismatch with TypeScript

**Problem:**

```typescript
plugins: [react({ jsxRuntime: "classic" })];
```

- Vite configured for classic JSX transform
- But can use automatic transform with your shims
- TypeScript config should match

**Recommendation:**

```typescript
plugins: [react({ jsxRuntime: "automatic" })];
```

**Why:**

- Modern automatic JSX transform (React 17+)
- No need for `React` variable in scope
- Smaller bundle (imports only needed functions)
- **Your shims already support this**

**Requires:**

- Update `tsconfig.json` to `"jsx": "react-jsx"`
- Your `wp-react-jsx-runtime.ts` already exports correct functions

---

##### Issue 2: Alias Order Matters

**Current Order:**

```typescript
alias: [
  { find: "@wordpress/element", ... },
  { find: "@wordpress/i18n", ... },
  { find: "@", ... },  // ⚠️ This is very broad
  { find: /^react\/jsx-runtime$/, ... },
  // ...
]
```

**Problem:**

- `{ find: "@", ... }` matches ANY import starting with `@`
- Should be LAST so it doesn't override `@wordpress/*` packages

**Recommendation:**

```typescript
alias: [
    // WordPress packages first (most specific)
    { find: "@wordpress/element", replacement: path.resolve(__dirname, "js/admin/wp-wordpress-element.ts") },
    { find: "@wordpress/i18n", replacement: path.resolve(__dirname, "js/admin/wp-wordpress-i18n.ts") },

    // React packages (regex patterns)
    { find: /^react\/jsx-runtime$/, replacement: path.resolve(__dirname, "js/admin/wp-react-jsx-runtime.ts") },
    { find: /^react\/jsx-dev-runtime$/, replacement: path.resolve(__dirname, "js/admin/wp-react-jsx-dev-runtime.ts") },
    { find: /^react-dom\/client$/, replacement: path.resolve(__dirname, "js/admin/wp-react-dom-client.ts") },
    { find: /^react-dom$/, replacement: path.resolve(__dirname, "js/admin/wp-react-dom.ts") },
    { find: /^react$/, replacement: path.resolve(__dirname, "js/admin/wp-react.ts") },

    // Project alias last (least specific)
    { find: "@", replacement: path.resolve(__dirname, "js") },
];
```

**Why:** Prevents `@wordpress/*` imports from matching `@` alias

---

##### Issue 3: Missing Path Resolution

**Current:**

```typescript
alias: [
    { find: "@", replacement: "js" }, // ❌ Relative path
];
```

**Problem:**

- `"js"` is relative, could break in some contexts
- Other aliases use `path.resolve(__dirname, ...)`

**Recommendation:**

```typescript
alias: [{ find: "@", replacement: path.resolve(__dirname, "js") }];
```

**Why:** Absolute paths are more reliable

---

##### Issue 4: Missing Optimization Options

**Recommended Additions:**

```typescript
build: {
  // ... existing options
  minify: "esbuild",           // Fast minification
  target: "es2020",            // Match tsconfig target
  cssCodeSplit: true,          // Split CSS per chunk
  rollupOptions: {
    output: {
      manualChunks: {
        "react-vendor": ["react", "react-dom"],
        "query-vendor": ["@tanstack/react-query"],
        "router-vendor": ["react-router-dom"]
      }
    }
  }
}
```

**Why:**

- Better caching (vendors rarely change)
- Faster subsequent page loads
- **Only useful if multiple entry points**

---

##### Issue 5: Development Server Config Missing

**Recommended Addition:**

```typescript
export default defineConfig(({ mode }) => ({
    // ... existing config

    server: {
        port: 3000,
        strictPort: false, // Use another port if 3000 taken
        open: false, // Don't auto-open browser
        cors: true, // Enable CORS for WordPress dev
        hmr: {
            protocol: "ws", // WebSocket HMR
            host: "localhost",
        },
    },

    preview: {
        port: 4000,
        strictPort: false,
    },
}));
```

**Why:** Better dev experience when running `npm run dev`

---

#### 📊 **Vite Config Score:**

| Aspect              | Status             | Score      |
| ------------------- | ------------------ | ---------- |
| React aliasing      | ✅ Comprehensive   | 0/10       |
| WordPress externals | ✅ Correct         | 0/10       |
| Build manifest      | ✅ Enabled         | 0/10       |
| Asset organization  | ✅ Clean           | 1/10       |
| JSX runtime         | 🟡 Classic vs auto | 3/10       |
| Alias order         | 🟡 Risky           | 4/10       |
| Path resolution     | 🟡 Inconsistent    | 2/10       |
| Missing dev server  | 🟢 Optional        | 1/10       |
| **Overall**         | ✅ **GOOD**        | **1.4/10** |

**Summary:** Excellent WordPress integration, minor config improvements needed

---

### Vitest Configuration (`vitest.config.ts`)

**Location:** `apps/wp-context-alt-text/vitest.config.ts`  
**Lines:** 15

**Current Configuration:**

```typescript
export default defineConfig({
    plugins: [react()],
    resolve: {
        alias: {
            "@": path.resolve(__dirname, "js"),
        },
    },
    test: {
        globals: true,
        environment: "jsdom",
        setupFiles: "./js/admin/test.setup.ts",
    },
});
```

---

#### ✅ **Strengths:**

1. **JSDOM Environment** ✅
    - `environment: "jsdom"` - Browser-like test environment
    - **Impact:** Can test React components with DOM

2. **Test Setup File** ✅
    - `setupFiles: "./js/admin/test.setup.ts"`
    - **Impact:** Consistent test environment

3. **Global Test APIs** ✅
    - `globals: true` - No need to import `describe`, `it`, `expect`
    - **Impact:** Cleaner test files

4. **Path Alias** ✅
    - `"@": "js"` matches tsconfig and Vite
    - **Impact:** Same imports work everywhere

---

#### 🔴 **Critical Issues:**

##### Issue 1: Missing React/WordPress Aliases

**Problem:**

```typescript
resolve: {
  alias: {
    "@": path.resolve(__dirname, "js")  // ✅ Has this
    // ❌ Missing all React/WordPress aliases!
  }
}
```

**Impact:**

- Tests import from real `react` package (React 19.1.1 from node_modules)
- Production uses WordPress-provided React (React 18.3.x)
- **Tests run against DIFFERENT React version than production!**
- Test results may not reflect production behavior

**Solution:**

```typescript
resolve: {
  alias: {
    "@": path.resolve(__dirname, "js"),

    // Add WordPress/React aliases (same as vite.config.ts)
    "@wordpress/element": path.resolve(__dirname, "js/admin/wp-wordpress-element.ts"),
    "@wordpress/i18n": path.resolve(__dirname, "js/admin/wp-wordpress-i18n.ts"),
    "react/jsx-runtime": path.resolve(__dirname, "js/admin/wp-react-jsx-runtime.ts"),
    "react/jsx-dev-runtime": path.resolve(__dirname, "js/admin/wp-react-jsx-dev-runtime.ts"),
    "react-dom/client": path.resolve(__dirname, "js/admin/wp-react-dom-client.ts"),
    "react-dom": path.resolve(__dirname, "js/admin/wp-react-dom.ts"),
    "react": path.resolve(__dirname, "js/admin/wp-react.ts")
  }
}
```

**Why This Matters:**

- Tests use same React version as production
- Tests use same WordPress globals setup
- More accurate test results
- **CRITICAL for WordPress plugin testing**

---

##### Issue 2: Missing Test Coverage Configuration

**Recommendation:**

```typescript
test: {
  globals: true,
  environment: "jsdom",
  setupFiles: "./js/admin/test.setup.ts",

  // Add coverage
  coverage: {
    provider: "v8",              // Fast coverage provider
    reporter: ["text", "json", "html"],
    exclude: [
      "node_modules/**",
      "js/**/*.test.{ts,tsx}",
      "js/**/*.stories.{ts,tsx}",
      "js/admin/test.setup.ts",
      ".storybook/**",
      "public/**"
    ],
    thresholds: {
      lines: 70,
      functions: 70,
      branches: 70,
      statements: 70
    }
  }
}
```

**Why:**

- Track test coverage over time
- Set minimum coverage thresholds
- Generate HTML coverage reports

---

##### Issue 3: Missing Global Type Augmentation

**Problem:**

- `globals: true` enables global test APIs
- TypeScript doesn't know about `describe`, `it`, `expect`
- **Already solved in tsconfig.json**: `"types": ["node"]`
- But should also include `"vitest/globals"`

**Solution in tsconfig.json:**

```json
"types": ["node", "vitest/globals"]
```

**Why:** TypeScript recognizes global test APIs

---

##### Issue 4: Missing Test Optimization

**Recommended Additions:**

```typescript
test: {
  globals: true,
  environment: "jsdom",
  setupFiles: "./js/admin/test.setup.ts",

  // Performance optimizations
  pool: "threads",              // Use worker threads (faster)
  poolOptions: {
    threads: {
      singleThread: false,      // Run tests in parallel
      isolate: true             // Isolate test context
    }
  },

  // Timeouts
  testTimeout: 10000,           // 10s max per test
  hookTimeout: 10000,           // 10s max for before/after hooks

  // Reporter
  reporters: ["default"],

  // Mock reset
  mockReset: true,              // Reset mocks after each test
  restoreMocks: true            // Restore original implementations
}
```

**Why:**

- Faster test execution
- Prevent test flakiness
- Better isolation

---

#### 📊 **Vitest Config Score:**

| Aspect                    | Status            | Score      |
| ------------------------- | ----------------- | ---------- |
| JSDOM environment         | ✅ Correct        | 0/10       |
| Setup file                | ✅ Configured     | 0/10       |
| Global APIs               | ✅ Enabled        | 0/10       |
| Path alias                | ✅ Matches others | 0/10       |
| **Missing React aliases** | 🔴 **CRITICAL**   | **9/10**   |
| Missing coverage          | 🟡 Recommended    | 3/10       |
| Missing optimizations     | 🟢 Optional       | 1/10       |
| **Overall**               | 🔴 **NEEDS FIX**  | **3.3/10** |

**Summary:** Good foundation, but CRITICAL missing React/WordPress aliases mean tests run against wrong React version!

---

## Configuration Files Summary

| Config File      | Overall Score | Status    | Priority               |
| ---------------- | ------------- | --------- | ---------------------- |
| tsconfig.json    | 6/10 🟡       | GOOD      | Fix skipLibCheck + JSX |
| vite.config.ts   | 1.4/10 ✅     | EXCELLENT | Minor improvements     |
| vitest.config.ts | 3.3/10 🔴     | NEEDS FIX | Add React aliases      |

---

## Configuration Refactoring Plan

### Phase 1: Critical Fixes (IMMEDIATE) 🔴

**Time:** 30 minutes  
**Impact:** Eliminate 85+ type errors, fix test environment

#### Task 1: Fix TypeScript Config

```json
// tsconfig.json
{
    "compilerOptions": {
        // Add these:
        "skipLibCheck": true, // Eliminate library type errors
        "jsx": "react-jsx", // Modern JSX transform
        "isolatedModules": true, // Vite requirement
        "noEmit": true, // Type check only
        "forceConsistentCasingInFileNames": true

        // Keep existing options...
    }
}
```

**Eliminates:** ~85 type errors

---

#### Task 2: Fix Vitest Config

```typescript
// vitest.config.ts
resolve: {
  alias: {
    "@": path.resolve(__dirname, "js"),

    // Add all React/WordPress aliases from vite.config.ts
    "@wordpress/element": path.resolve(__dirname, "js/admin/wp-wordpress-element.ts"),
    "@wordpress/i18n": path.resolve(__dirname, "js/admin/wp-wordpress-i18n.ts"),
    "react/jsx-runtime": path.resolve(__dirname, "js/admin/wp-react-jsx-runtime.ts"),
    "react/jsx-dev-runtime": path.resolve(__dirname, "js/admin/wp-react-jsx-dev-runtime.ts"),
    "react-dom/client": path.resolve(__dirname, "js/admin/wp-react-dom-client.ts"),
    "react-dom": path.resolve(__dirname, "js/admin/wp-react-dom.ts"),
    "react": path.resolve(__dirname, "js/admin/wp-react.ts")
  }
}
```

**Impact:** Tests use correct React version (18.3.x via WordPress)

---

#### Task 3: Update Vite JSX Runtime

```typescript
// vite.config.ts
plugins: [react({ jsxRuntime: "automatic" })]; // Change from "classic"
```

**Impact:** Matches tsconfig, smaller bundle

---

### Phase 2: Recommended Improvements (MEDIUM) 🟡

**Time:** 1-2 hours

#### Task 1: Fix Test Type Errors

- Fix `WorkbenchContractItem` vs `WorkbenchMediaItem` type mismatch
- Fix test fixtures to use correct types
- Fix `wp.media()` type in RosterRoute

**Eliminates:** 5 remaining type errors

---

#### Task 2: Fix Type Declaration

```typescript
// js/types/wp-element.d.ts
declare module "@wordpress/element/build-module/react" {
  import type * as React from "react";

  // Don't use export *, use specific exports
  export type {
    ReactNode,
    ReactElement,
    // ... specific types
  } from "react";

  export const concatChildren: (...) => React.ReactNode[];
  export default React;
}
```

---

#### Task 3: Reorder Vite Aliases

Move `@` alias to end of array (after WordPress/React aliases)

---

#### Task 4: Add Test Coverage

Configure Vitest coverage with thresholds

---

### Phase 3: Optional Enhancements (LOW) 🟢

**Time:** 1 hour

- Add Vite dev server config
- Add manual chunk splitting for vendors
- Add test performance optimizations
- Add more TypeScript strict flags

---

## Configuration Audit Complete

**Key Findings:**

1. 🔴 **CRITICAL:** `skipLibCheck: true` missing → 85+ type errors
2. 🔴 **CRITICAL:** Vitest missing React aliases → tests use wrong React version
3. 🟡 **MEDIUM:** JSX transform should be automatic, not classic
4. 🟡 **MEDIUM:** 5 test type errors need fixing
5. 🟢 **LOW:** Various config optimizations available

**After Fixes:**

- Zero type errors from libraries
- Tests use correct React version
- Modern JSX transform
- All configs aligned
- **Result:** Production-ready configuration

---

**All audits complete! Ready for final summary and implementation plan...**
