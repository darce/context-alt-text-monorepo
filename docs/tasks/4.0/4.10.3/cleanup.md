# Cleanup Tasks (v4.10.3)

Code quality issues identified during audit of unstaged changes.

> **Status:** Closed — See [v4.11.0 Implementation Plan](../4.11.0/implementation-plan.md) for remaining work.
>
> **Completion Summary (2026-01-12):**
>
> - 30/39 issues addressed (77%)
> - 6 partially addressed (15%)
> - 3 deferred as not needed (8%)

## Legend

| Section             | Description                              |
| ------------------- | ---------------------------------------- |
| **Implementation**  | Step-by-step approach with code patterns |
| **Methodology**     | Testing and validation strategy          |
| **Success Metrics** | Measurable criteria for completion       |
| ✅                  | Completed in v4.11.0                     |

---

## 🔴 Critical

### ✅ 0. Infinite Request Loop on Suggestions Endpoint (500 Error)

**File**: `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/SuggestionReviewPanel.tsx`  
**Lines**: 72-76

**Problem**: When the `/recognition/suggestions` endpoint returns 500, React Query retries 3 times (default), then the `refetchInterval: 30000` continues polling. Combined with missing global retry/error configuration, this creates a request storm.

```typescript
const { data, isLoading } = useQuery({
  queryKey: ["pending-suggestions"],
  queryFn: () => fetchPendingSuggestions(10, 0),
  refetchInterval: 30000, // ← Keeps polling even on error
  // Missing: retry, retryDelay, refetchIntervalInBackground
});
```

**Impact**:

- 14+ rapid 500 requests visible in console
- Server load from retry storm
- Poor UX (no error state shown)

**Root Cause**: Two issues compounding:

1. **No global QueryClient config** in `App.tsx`:

   ```typescript
   const queryClient = new QueryClient(); // No defaultOptions
   ```

2. **No per-query error handling** — `refetchInterval` ignores error state

**Fix**:

1. Add global defaults to `QueryClient`:

```typescript
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
      refetchOnWindowFocus: false,
    },
  },
});
```

2. Stop polling on error in `SuggestionReviewPanel`:

```typescript
const { data, isLoading, isError } = useQuery({
  queryKey: ["pending-suggestions"],
  queryFn: () => fetchPendingSuggestions(10, 0),
  refetchInterval: (query) => (query.state.status === "error" ? false : 30000),
  retry: 1,
});
```

**Implementation**:

1. Update `App.tsx` with global QueryClient defaults
2. Update `SuggestionReviewPanel` to conditionally disable polling on error
3. Add error UI state to show "Failed to load suggestions" instead of silent retries

```typescript
// SuggestionReviewPanel.tsx
if (isError) {
  return (
    <div className="acx-suggestion-panel acx-suggestion-panel--error">
      <p>{__("Failed to load suggestions.", "alt-context")}</p>
      <button onClick={() => refetch()}>{__("Retry", "alt-context")}</button>
    </div>
  );
}
```

**Methodology**:

- Reproduce with backend down
- Verify no more than 2 requests (initial + 1 retry)
- Verify refetchInterval stops until manual retry
- Add integration test with MSW returning 500

**Success Metrics**:

| Metric                 | Before         | After                      |
| ---------------------- | -------------- | -------------------------- |
| Requests on 500 error  | 14+ (infinite) | 2 (initial + 1 retry)      |
| Polling on error state | Continues      | Stops                      |
| User feedback on error | None           | Error UI with retry button |

---

### ✅ 1. Stale Closure Bug in `useJobProgressStream.ts`

**File**: `apps/prototype-wp-alt-context/js/admin/hooks/useJobProgressStream.ts`  
**Line**: 213

**Problem**: The `useEffect` dependency array includes `startTime` and `progress`, causing the SSE effect to re-run every time progress updates. This closes and reopens the EventSource connection repeatedly.

```typescript
// Current (broken)
}, [jobId, isOnline, isPrimary, channel, startTime, progress]);
```

**Impact**:

- SSE connection recreated on every progress update
- Performance degradation
- Potential missed events during reconnection

**Fix**:

1. Remove `startTime` and `progress` from dependency array
2. Use `useRef` for `startTime` to avoid stale closure:

```typescript
const startTimeRef = useRef<number | null>(null);
// ... use startTimeRef.current instead of startTime state
}, [jobId, isOnline, isPrimary, channel]);
```

**Implementation**:

1. Create `startTimeRef` and `progressRef` using `useRef`
2. Sync refs in a separate `useEffect` that depends on the state values
3. Replace all reads of `startTime`/`progress` inside SSE handlers with `.current`
4. Remove state values from dependency array

```typescript
// Pattern: Ref sync effect
const progressRef = useRef(progress);
useEffect(() => {
  progressRef.current = progress;
}, [progress]);

// In handler:
const elapsed = Date.now() - (startTimeRef.current ?? Date.now());
```

**Methodology**:

- Write integration test that mocks SSE with 100 rapid progress events
- Assert EventSource constructor called exactly once
- Use React DevTools Profiler to verify no re-renders from SSE effect

**Success Metrics**:

| Metric                          | Before                     | After                    |
| ------------------------------- | -------------------------- | ------------------------ |
| EventSource connections per job | N (one per progress event) | 1                        |
| Effect re-runs during scan      | ~100+                      | 0 (only on jobId change) |
| Console warnings about cleanup  | Frequent                   | None                     |

---

## 🟡 Medium

### ✅ 2. Unused Imports in `test_cancel_labels.py`

**File**: `apps/prototype-description-service/recognition/tests/integration/test_cancel_labels.py`  
**Line**: 2

**Problem**: `UTC` and `datetime` are imported but never used.

```python
from datetime import UTC, datetime  # Neither used
```

**Fix**: Remove the unused import line.

**Implementation**:

```bash
# Automated via ruff
ruff check --fix recognition/tests/integration/test_cancel_labels.py
```

**Methodology**:

- Run `ruff check` in CI to catch future unused imports
- Add `F401` (unused import) to enforced rules

**Success Metrics**:

| Metric                 | Before | After |
| ---------------------- | ------ | ----- |
| Unused imports in file | 2      | 0     |
| `ruff check` exit code | 1      | 0     |

---

### ✅ 3. Accessing Private Members in Tests

**File**: `apps/prototype-description-service/recognition/tests/integration/test_cancel_labels.py`  
**Lines**: 22-23

**Problem**: Tests access underscore-prefixed private attributes, breaking encapsulation.

```python
cluster_repo = cluster_service.assignment_writer._clusters
member_repo = cluster_service.assignment_writer._members
```

**Impact**: Tests are brittle — will break if internal structure changes.

**Recommendation**: Either:

- Add public accessors to `ClusterService` for testing
- Use a test-specific factory that exposes these repos directly
- Add `@property` methods that expose these for testing

**Implementation**:

Option A — Test factory pattern (preferred):

```python
# recognition/tests/fixtures/services.py
def build_test_cluster_service(session) -> tuple[ClusterService, ClusterRepository, MemberRepository]:
    cluster_repo = SqlAlchemyClusterRepository(session)
    member_repo = SqlAlchemyMemberRepository(session)
    writer = AssignmentWriter(clusters=cluster_repo, members=member_repo)
    service = ClusterService(assignment_writer=writer, ...)
    return service, cluster_repo, member_repo
```

Option B — Property accessors:

```python
class ClusterService:
    @property
    def cluster_repository(self) -> ClusterRepository:
        """Exposed for testing only."""
        return self.assignment_writer._clusters
```

**Methodology**:

- Refactor one test file using new pattern
- Ensure tests still pass
- Update remaining tests incrementally

**Success Metrics**:

| Metric                                | Before | After |
| ------------------------------------- | ------ | ----- |
| Private member accesses in tests      | 2+     | 0     |
| Test brittleness (breaks on refactor) | High   | Low   |

---

### ✅ 4. Stale Progress in Done Handler

**File**: `apps/prototype-wp-alt-context/js/admin/hooks/useJobProgressStream.ts`  
**Lines**: 156-163

**Problem**: The `done` event handler broadcasts `progress` which may be stale due to closure.

```typescript
channel?.postMessage({
  type: "JOB_PROGRESS",
  payload: {
    progress: progress, // ← stale closure value
    status: data.status,
    etaSeconds: null,
  },
});
```

**Fix**: Use a ref for progress, or compute final progress from the done event data.

**Implementation**:

```typescript
// Option 1: Use ref (consistent with issue #1 fix)
progressRef.current;

// Option 2: Derive from event data (preferred)
channel?.postMessage({
  type: "JOB_PROGRESS",
  payload: {
    progress: { completed: data.total, total: data.total }, // 100%
    status: data.status,
    etaSeconds: null,
  },
});
```

**Methodology**:

- Add unit test: open two tabs, complete job in primary, verify observer receives correct final progress
- Log discrepancy if `progressRef.current !== data.total` at done time

**Success Metrics**:

| Metric                          | Before       | After       |
| ------------------------------- | ------------ | ----------- |
| Final progress value accuracy   | Stale (race) | Always 100% |
| Observer tab sync on completion | Unreliable   | Reliable    |

---

## 🟢 Low / Deferred

### ⏸️ 5. Race Condition in Primary Election (Deferred)

**File**: `apps/prototype-wp-alt-context/js/admin/hooks/useJobCoordination.ts`  
**Lines**: 56-58

**Problem**: If multiple observer tabs receive `PRIMARY_CLOSING` simultaneously, they all become primary with no election protocol.

**Impact**: Multiple tabs could open duplicate SSE connections.

**Mitigation**: Acceptable for prototype. Production would need proper leader election (random delay + re-ping).

**Implementation** (if escalated):

```typescript
// Randomized backoff election
const handlePrimaryClosing = () => {
  const delay = Math.random() * 200; // 0-200ms
  setTimeout(() => {
    channel.postMessage({ type: "ELECTION_BID", tabId });
  }, delay);
};

// First bid wins
const handleElectionBid = (bidTabId: string) => {
  if (!isPrimary && bidTabId === tabId) {
    setIsPrimary(true);
  }
};
```

**Methodology**:

- Simulate with 5+ tabs using Playwright
- Assert only one SSE connection open at any time

**Success Metrics**:

| Metric                              | Before     | After              |
| ----------------------------------- | ---------- | ------------------ |
| Concurrent SSE connections (5 tabs) | 1-5 (race) | 1                  |
| Election protocol                   | None       | Randomized backoff |

---

### ⏸️ 6. SSR Guard Missing (Deferred — Not Needed)

**File**: `apps/prototype-wp-alt-context/js/admin/hooks/useJobPersistence.ts`  
**Line**: 43

**Problem**: Direct `localStorage` access would throw in SSR environments.

```typescript
const stored = localStorage.getItem(STORAGE_KEY);
```

**Fix** (if SSR needed):

```typescript
const stored =
  typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
```

**Status**: Not needed for WordPress admin context (client-only).

**Implementation** (if needed for SSR/testing):

```typescript
// utils/storage.ts
export const safeLocalStorage = {
  getItem: (key: string): string | null =>
    typeof window !== "undefined" ? localStorage.getItem(key) : null,
  setItem: (key: string, value: string): void => {
    if (typeof window !== "undefined") localStorage.setItem(key, value);
  },
};
```

**Methodology**:

- Add Jest test with `window` undefined
- Verify no throws

**Success Metrics**:

| Metric            | Before         | After          |
| ----------------- | -------------- | -------------- |
| SSR compatibility | ❌             | ✅             |
| Test isolation    | Requires jsdom | Works headless |

---

### ⏸️ 7. Inline Helper Function (Deferred — Cosmetic)

**File**: `apps/prototype-description-service/recognition/tests/integration/test_cancel_labels.py`  
**Lines**: 163-165

**Problem**: `_coerce_uuid` helper is only used once — could be inlined.

**Status**: Trivial, no action needed.

**Implementation**: Inline if desired:

```python
# Before
cluster_id = _coerce_uuid(raw_id)

# After
cluster_id = UUID(raw_id) if isinstance(raw_id, str) else raw_id
```

**Success Metrics**: N/A — cosmetic only.

---

## 🔵 Architectural Issues

Type system analysis revealed structural issues in the frontend codebase.

### ✅ 8. Duplicate `JobProgress` Type Definition

**Files**:

- `apps/prototype-wp-alt-context/js/admin/api/recognition/types/scan.ts` (L16-19)
- `apps/prototype-wp-alt-context/js/admin/hooks/useJobProgressStream.ts` (L4-7)

**Problem**: Identical `JobProgress` interface (`{ completed: number; total: number }`) defined in two places.

**Fix**: Remove definition from hook, import from API types.

**Implementation**:

```typescript
// useJobProgressStream.ts
- interface JobProgress {
-   completed: number;
-   total: number;
- }
+ import { JobProgress } from '../api/recognition/types/scan';
```

**Methodology**:

- Search codebase for other `JobProgress` definitions: `grep -r "interface JobProgress"`
- Ensure single source of truth

**Success Metrics**:

| Metric                    | Before    | After         |
| ------------------------- | --------- | ------------- |
| `JobProgress` definitions | 2         | 1             |
| Import graph clarity      | Ambiguous | Single source |

---

### 9. Schema Drift: `shared-contracts` vs Frontend Types

**Files**:

- `packages/shared-contracts/schemas/roster-entry.schema.json`
- `packages/shared-contracts/schemas/recognition-job.schema.json`
- `packages/shared-contracts/schemas/workbench-media-item.schema.json`

**Problem**: Schemas don't match actual frontend types:

| Schema                                                        | Frontend                                                | Mismatch             |
| ------------------------------------------------------------- | ------------------------------------------------------- | -------------------- |
| `roster-entry` requires `remoteId`, `label`, `type`, `status` | `RosterEntry` has `id`, `name`, `tags`, `cluster_count` | Completely different |
| `recognition-job` uses `"processing"`, `"complete"`           | Frontend uses `"running"`, `"completed"`                | Enum values differ   |
| `workbench-media-item` has `id: string`                       | Frontend `WorkbenchMediaItem` has `id: number`          | Type mismatch        |

**Impact**: Schemas describe aspirational future state, not current contract.

**Fix**: Either regenerate types from schemas or update schemas to match reality.

**Implementation**:

Option A — Schema-first (recommended for API contracts):

```bash
# Generate types from schemas
npx json-schema-to-typescript packages/shared-contracts/schemas/*.json \
  -o apps/prototype-wp-alt-context/js/admin/api/generated/
```

Option B — Code-first (pragmatic for prototype):

1. Delete aspirational schemas or move to `docs/future/`
2. Document that types are source of truth
3. Add `zod` schemas in TypeScript for runtime validation

**Methodology**:

- Create mapping table of all schema ↔ type pairs
- Validate each field matches
- Add CI check: `npm run validate-schemas`

**Success Metrics**:

| Metric                       | Before   | After              |
| ---------------------------- | -------- | ------------------ |
| Schema/type field mismatches | 10+      | 0                  |
| Runtime type errors from API | Possible | Caught at boundary |
| Schema validation in CI      | ❌       | ✅                 |

---

### ✅ 10. Parallel Cluster Type Hierarchies

**Files**:

- `js/admin/api/recognition/types/cluster.ts` — API types (`ClusterSummary`, `ClusterIdentity`)
- `js/admin/pages/workbench/identity-clusters/types.ts` — UI types (`ClusterGroup`)

**Problem**: Two overlapping type hierarchies with transformation via `groupIdentitiesByClusters()`. Components mix raw `DetectedIdentity[]` (API) with `ClusterGroup` (UI) inconsistently.

**Recommendation**: Create explicit adapter layer or document transformation boundary.

**Implementation**:

```typescript
// js/admin/api/recognition/adapters/clusterAdapter.ts
import type { ClusterSummary } from "../types/cluster";
import type { ClusterGroup } from "../../pages/workbench/identity-clusters/types";

export function toClusterGroup(summary: ClusterSummary): ClusterGroup {
  return {
    clusterId: summary.id,
    label: summary.label ?? `Cluster ${summary.id.slice(0, 8)}`,
    identities: summary.identities.map(toGroupIdentity),
    representativeUrl: summary.representative_thumbnail_url,
  };
}

// Usage in component
const groups = useMemo(() => clusters.map(toClusterGroup), [clusters]);
```

**Methodology**:

- Document transformation in ADR or inline JSDoc
- Add type tests ensuring adapter output matches UI type

**Success Metrics**:

| Metric                       | Before    | After          |
| ---------------------------- | --------- | -------------- |
| Transformation locations     | Scattered | Single adapter |
| Type confusion in components | Common    | Eliminated     |
| Documented boundary          | ❌        | ✅             |

---

### 11. Config Coercion Leaks to Consumers

**File**: `apps/prototype-wp-alt-context/js/admin/api/config.ts`

**Problem**: `ApiConfig` admits PHP serialization quirks:

```typescript
max_media_per_batch?: number | string; // wp_localize_script coercion
devMode?: boolean | string | number;   // also coerced
```

Every consumer must handle these union types. `isDevMode()` exists but `max_media_per_batch` handling is repeated in `scanApi.ts`.

**Fix**: Normalize all config values in `getConfig()` to clean types.

**Implementation**:

```typescript
// config.ts
interface NormalizedConfig {
  maxMediaPerBatch: number;
  devMode: boolean;
  // ... all clean types
}

function normalizeConfig(raw: ApiConfig): NormalizedConfig {
  return {
    maxMediaPerBatch: Number(raw.max_media_per_batch ?? 50),
    devMode:
      raw.devMode === true || raw.devMode === "true" || raw.devMode === 1,
    // ...
  };
}

let cachedConfig: NormalizedConfig | null = null;

export function getConfig(): NormalizedConfig {
  if (!cachedConfig) {
    cachedConfig = normalizeConfig(window.altContextConfig ?? {});
  }
  return cachedConfig;
}
```

**Methodology**:

- Add unit tests for edge cases: `"50"`, `"true"`, `1`, `undefined`
- Remove all `Number()` coercions from consumers

**Success Metrics**:

| Metric                    | Before             | After         |
| ------------------------- | ------------------ | ------------- |
| Config coercion locations | 5+ files           | 1 (config.ts) |
| Consumer type complexity  | `number \| string` | `number`      |
| Edge case bugs            | Possible           | Tested        |

---

### ✅ 12. Inconsistent Query Key Patterns

**Files**: Multiple hooks in `js/admin/hooks/`

**Problem**: React Query keys lack consistency:

- `['media-identities']` — flat
- `['recognition-clusters', params]` — parameterized
- `['clusters', 'top-unlabeled', tenantId]` — nested
- `['pending-suggestions']` — flat

**Impact**: Cache invalidation is fragile; `invalidateQueries({ queryKey: ['clusters'] })` won't catch all cluster-related queries.

**Fix**: Create `queryKeys` factory object:

```typescript
export const queryKeys = {
  clusters: {
    all: ["clusters"] as const,
    list: (params) => [...queryKeys.clusters.all, "list", params] as const,
    detail: (id) => [...queryKeys.clusters.all, "detail", id] as const,
  },
  // ...
};
```

**Implementation**:

```typescript
// js/admin/api/queryKeys.ts
export const queryKeys = {
  clusters: {
    all: ["clusters"] as const,
    list: (tenantId: string) =>
      [...queryKeys.clusters.all, "list", tenantId] as const,
    detail: (id: string) => [...queryKeys.clusters.all, "detail", id] as const,
    topUnlabeled: (tenantId: string) =>
      [...queryKeys.clusters.all, "top-unlabeled", tenantId] as const,
  },
  media: {
    all: ["media"] as const,
    identities: (mediaId: number) =>
      [...queryKeys.media.all, "identities", mediaId] as const,
  },
  jobs: {
    all: ["jobs"] as const,
    scan: (jobId: string) => [...queryKeys.jobs.all, "scan", jobId] as const,
  },
  suggestions: {
    all: ["suggestions"] as const,
    pending: () => [...queryKeys.suggestions.all, "pending"] as const,
  },
} as const;
```

**Methodology**:

- Migrate one hook at a time
- Search for hardcoded arrays: `grep -r "queryKey:.*\['"`
- Add lint rule banning inline query keys

**Success Metrics**:

| Metric                                                    | Before      | After       |
| --------------------------------------------------------- | ----------- | ----------- |
| Inline query key definitions                              | 10+         | 0           |
| Cache invalidation reliability                            | Fragile     | Predictable |
| `invalidateQueries({ queryKey: queryKeys.clusters.all })` | Misses some | Catches all |

---

### ✅ 13. WorkbenchPage Violates Single Responsibility

**File**: `apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx` (534 lines)

**Problem**: Orchestrates 6+ hooks, 4 mutations, multiple effects for job state machine (scanning → clustering → complete), tab navigation, and rendering.

**Recommendation**: Extract job state machine to dedicated hook or reducer:

```typescript
const { phase, progress, actions } = useJobStateMachine();
// phase: 'idle' | 'scanning' | 'clustering' | 'complete'
```

**Implementation**:

```typescript
// hooks/useJobStateMachine.ts
type Phase = "idle" | "scanning" | "clustering" | "complete" | "error";

interface JobState {
  phase: Phase;
  scanJobId: string | null;
  clusterJobId: string | null;
  progress: { completed: number; total: number };
  error: string | null;
}

type JobAction =
  | { type: "START_SCAN"; jobId: string }
  | { type: "SCAN_PROGRESS"; completed: number; total: number }
  | { type: "SCAN_COMPLETE" }
  | { type: "START_CLUSTERING"; jobId: string }
  | { type: "CLUSTERING_COMPLETE" }
  | { type: "ERROR"; message: string };

function jobReducer(state: JobState, action: JobAction): JobState {
  switch (action.type) {
    case "START_SCAN":
      return { ...state, phase: "scanning", scanJobId: action.jobId };
    // ...
  }
}

export function useJobStateMachine() {
  const [state, dispatch] = useReducer(jobReducer, initialState);
  // Wire up SSE, mutations, etc.
  return { ...state, dispatch };
}
```

**Methodology**:

- Extract reducer first (pure function, easy to test)
- Write unit tests for all state transitions
- Gradually move effects into hook

**Success Metrics**:

| Metric                   | Before | After                    |
| ------------------------ | ------ | ------------------------ |
| WorkbenchPage lines      | 534    | <200                     |
| State transitions tested | 0      | 100%                     |
| Job flow bugs            | Ad-hoc | State machine guarantees |

---

### ✅ 14. Test Mocking Friction

**Files**: Test files in `js/admin/pages/workbench/__tests__/`

**Problem**: 18+ instances of `as unknown as ReturnType<typeof useHook>` pattern:

```typescript
} as unknown as ReturnType<typeof useScanIdentities>;
} as unknown as ReturnType<typeof useWorkbenchMedia>;
```

**Impact**: Tests are tightly coupled to TanStack Query internals; mock objects are incomplete and type-unsafe.

**Recommendation**: Create thin wrapper hooks or test utilities that expose only consumed properties.

**Implementation**:

```typescript
// test-utils/mockHooks.ts
import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";

export function createMockQuery<T>(data: T): UseQueryResult<T, Error> {
  return {
    data,
    isLoading: false,
    isError: false,
    error: null,
    isSuccess: true,
    status: "success",
    refetch: vi.fn(),
    // Only include properties actually used by components
  } as UseQueryResult<T, Error>;
}

export function createMockMutation<TData, TVariables>(options?: {
  onSuccess?: (data: TData) => void;
}): UseMutationResult<TData, Error, TVariables> {
  return {
    mutate: vi.fn(),
    mutateAsync: vi.fn().mockResolvedValue({} as TData),
    isPending: false,
    isSuccess: false,
    // ...
  } as UseMutationResult<TData, Error, TVariables>;
}
```

**Methodology**:

- Audit which properties each component actually uses
- Create minimal mock factories
- Replace `as unknown as` with typed factories

**Success Metrics**:

| Metric                  | Before | After |
| ----------------------- | ------ | ----- |
| `as unknown as` casts   | 18+    | 0     |
| Mock type safety        | None   | Full  |
| Test maintenance burden | High   | Low   |

---

## 🔵 Backend Architectural Issues

Python backend type and structural analysis.

### ✅ 15. Large Router Files Violate SRP

**Files**:

- `recognition/interface_adapters/http/routers/analyze.py` (558 lines)
- `recognition/interface_adapters/http/routers/clusters.py` (575 lines)

**Problem**: Router modules contain inline business logic, helper functions, and background task handlers mixed with route definitions.

**Recommendation**: Extract to:

- Route definitions only in routers
- Background task helpers → `tasks/` module
- Inline helpers → appropriate service layer

**Implementation**:

```
recognition/
  interface_adapters/
    http/
      routers/
        analyze.py          # Route definitions only (~100 lines)
        clusters.py         # Route definitions only (~150 lines)
      tasks/
        analyze_tasks.py    # BackgroundTask handlers
        cluster_tasks.py    # BackgroundTask handlers
```

```python
# routers/analyze.py (after refactor)
@router.post("/scan")
async def start_scan(
    request: ScanRequest,
    background_tasks: BackgroundTasks,
    scan_service: ScanService = Depends(get_scan_service),
) -> ScanResponse:
    job = await scan_service.create_job(request)
    background_tasks.add_task(run_scan_job, job.id)
    return ScanResponse(job_id=job.id)

# tasks/analyze_tasks.py
async def run_scan_job(job_id: UUID) -> None:
    """Background task for scan execution."""
    async with get_session() as session:
        # ... implementation
```

**Methodology**:

- Extract one helper at a time, keeping tests green
- Use `git diff --stat` to verify line reduction
- Router should only have route decorators and minimal glue

**Success Metrics**:

| Metric                | Before | After |
| --------------------- | ------ | ----- |
| `analyze.py` lines    | 558    | <150  |
| `clusters.py` lines   | 575    | <200  |
| Functions per router  | 15+    | <10   |
| Cyclomatic complexity | High   | Low   |

---

### 16. `incremental_clustering.py` is 754 Lines

**File**: `recognition/application/orchestration/incremental_clustering.py`

**Problem**: Single module handles too many responsibilities across 7 top-level definitions:

| Definition                         | Lines    | Responsibility                    |
| ---------------------------------- | -------- | --------------------------------- |
| `ClusterJobResult` dataclass       | L47-57   | Job result data structure         |
| `get_chunk_size()`                 | L59-67   | Adaptive chunk sizing logic       |
| `cluster_unclustered_identities()` | L70-513  | **443 lines** — main orchestrator |
| `_run_hac_refinement()`            | L515-571 | HAC post-processing               |
| `_log_and_report_decision()`       | L573-659 | Logging helper (86 lines)         |
| `_prepare_cluster_caches()`        | L661-695 | Cache preparation                 |
| `_run_discovery_pipeline()`        | L697-754 | Multi-stage discovery             |

**Root Cause**: The main function `cluster_unclustered_identities()` is 443 lines and handles:

- Tenant UUID format coercion (L112-128)
- Job creation/update (L130-152)
- Orphaned representative cleanup (L155-161)
- Unclustered identity query (L163-170)
- Recognition run context creation (L189-206)
- Domain object transformation (L208-222)
- Chunked processing loop (L240-410)
- Decision handling (accept/suggest/reject)
- New cluster creation
- Progress callbacks
- Job completion

**Recommendation**: Split into:

- `cluster_job.py` — Job lifecycle and result types
- `chunked_processor.py` — Chunk iteration logic
- `discovery_pipeline.py` — Multi-stage discovery coordination
- `decision_handler.py` — Accept/suggest/reject logic
- `orchestrator.py` — Thin coordinator

**Implementation**:

```
recognition/application/orchestration/
  clustering/
    __init__.py
    job_result.py           # ClusterJobResult dataclass
    tenant_utils.py         # Tenant UUID coercion
    chunked_processor.py    # ChunkedIdentityProcessor class
    discovery_pipeline.py   # _run_discovery_pipeline, _prepare_cluster_caches
    decision_handler.py     # Decision logging and persistence
    orchestrator.py         # cluster_unclustered_identities (thin)
```

```python
# tenant_utils.py
def coerce_tenant_uuid(tenant_id: str) -> uuid.UUID:
    """Convert tenant ID to UUID, handling MD5 hash format."""
    tenant_str = str(tenant_id).replace("-", "")
    if len(tenant_str) == 32:
        formatted = f"{tenant_str[:8]}-{tenant_str[8:12]}-{tenant_str[12:16]}-{tenant_str[16:20]}-{tenant_str[20:]}"
        return uuid.UUID(formatted)
    return uuid.UUID(str(tenant_id))

# chunked_processor.py
class ChunkedIdentityProcessor:
    def __init__(self, identities: list[MediaIdentity], gate: AssignmentGate):
        self._remaining = sorted(identities, key=lambda i: i.confidence, reverse=True)
        self._processed = 0
        self._gate = gate

    def __iter__(self) -> Iterator[list[MediaIdentity]]:
        while self._remaining:
            chunk_size = self._get_chunk_size()
            yield self._remaining[:chunk_size]
            self._remaining = self._remaining[chunk_size:]
            self._processed += chunk_size

    def _get_chunk_size(self) -> int:
        if self._processed < 20:
            return 5
        if self._processed < 50:
            return 10
        if self._processed < 200:
            return 25
        return 50

# decision_handler.py
class DecisionHandler:
    def __init__(
        self,
        assignment_writer: AssignmentWriter,
        suggestion_service: SuggestionServiceProtocol,
        clustering_logger: ClusteringLogger | None = None,
    ):
        self._writer = assignment_writer
        self._suggestions = suggestion_service
        self._logger = clustering_logger

    async def handle(
        self,
        candidate: AssignmentCandidate,
        decision: AssignmentDecision,
    ) -> Literal["accepted", "suggested", "rejected"]:
        if decision.outcome == AssignmentOutcome.ACCEPT:
            await self._writer.persist_assignment(decision, batch_mode=True)
            await self._suggestions.resolve_for_identity_exclusive(...)
            return "accepted"
        elif decision.outcome == AssignmentOutcome.SUGGEST:
            await self._suggestions.create(candidate, decision.suggestion_confidence)
            return "suggested"
        return "rejected"
```

**Methodology**:

- Extract dataclass first (no behavior change)
- Extract `coerce_tenant_uuid` — used in multiple places
- Extract `ChunkedIdentityProcessor` with unit tests
- Extract `DecisionHandler` class
- Refactor orchestrator to use new components
- Verify all tests pass at each step

**Success Metrics**:

| Metric                                   | Before                  | After                 |
| ---------------------------------------- | ----------------------- | --------------------- |
| `incremental_clustering.py` lines        | 754                     | <150                  |
| `cluster_unclustered_identities()` lines | 443                     | <80                   |
| Largest function                         | 443 lines               | <50 lines             |
| Unit test coverage for chunking          | 0%                      | 100%                  |
| Tenant UUID coercion locations           | 2+ files                | 1 (`tenant_utils.py`) |
| Decision handling testability            | Coupled to orchestrator | Isolated class        |

---

### 17. Protocol TODOs in Domain Layer

**File**: `recognition/domain/repositories.py`

**Problem**: 13+ `raise NotImplementedError("TODO: ...")` in protocol methods:

```python
raise NotImplementedError("TODO: get_labeled_with_representatives")
raise NotImplementedError("TODO: implement bulk_update_status")
raise NotImplementedError("TODO: implement upsert_by_identity_cluster")
raise NotImplementedError("TODO: Implement in SqlAlchemyConstraintRepository")
```

**Impact**: Protocol methods are declared but implementations missing — runtime errors if called.

**Recommendation**: Either implement or remove from protocol interface.

**Implementation**:

Step 1 — Audit each TODO:

```bash
grep -n "NotImplementedError.*TODO" recognition/domain/repositories.py
```

Step 2 — For each, decide:

- **Used by callers?** → Implement in SqlAlchemy repository
- **Not used?** → Remove from Protocol (YAGNI)
- **Future planned?** → Move to `@abstractmethod` in separate `FutureRepositoryProtocol`

Step 3 — Example implementation:

```python
# domain/repositories.py
class ClusterRepository(Protocol):
    async def get_labeled_with_representatives(self, tenant_id: str) -> list[Cluster]:
        """Get all labeled clusters with their representatives."""
        ...  # Protocol methods use ... not raise

# infrastructure/repositories/cluster_repository.py
async def get_labeled_with_representatives(self, tenant_id: str) -> list[Cluster]:
    stmt = (
        select(ClusterModel)
        .where(ClusterModel.tenant_id == tenant_id)
        .where(ClusterModel.label.isnot(None))
        .options(selectinload(ClusterModel.representatives))
    )
    result = await self._session.execute(stmt)
    return [self._to_domain(row) for row in result.scalars()]
```

**Methodology**:

- Search for callers of each protocol method
- Implement only what's called
- Add integration tests for new implementations

**Success Metrics**:

| Metric                                    | Before   | After   |
| ----------------------------------------- | -------- | ------- |
| TODO NotImplementedError                  | 13       | 0       |
| Runtime errors from unimplemented methods | Possible | None    |
| Dead protocol methods                     | Unknown  | Removed |

---

### ✅ 18. SQLAlchemy `rowcount` Type Suppression

**Files**:

- `recognition/infrastructure/repositories/cluster_repository.py` (L310, 324, 334)
- `recognition/infrastructure/repositories/member_repository.py` (L187)

**Problem**: Repeated `# type: ignore[attr-defined]` for `rowcount` access:

```python
return int(result.rowcount)  # type: ignore[attr-defined]
```

**Root Cause**: SQLAlchemy's `CursorResult.rowcount` typing is incomplete.

**Fix**: Create typed helper:

```python
def get_rowcount(result: CursorResult[Any]) -> int:
    """Type-safe rowcount accessor."""
    return int(getattr(result, "rowcount", 0))
```

**Implementation**:

```python
# recognition/infrastructure/db/utils.py
from typing import Any
from sqlalchemy.engine import CursorResult

def get_rowcount(result: CursorResult[Any]) -> int:
    """Type-safe accessor for CursorResult.rowcount.

    SQLAlchemy's typing doesn't expose rowcount on CursorResult,
    but it's always available at runtime for DML statements.
    """
    return int(getattr(result, "rowcount", 0))

# Usage in repositories:
from recognition.infrastructure.db.utils import get_rowcount

async def delete_cluster(self, cluster_id: UUID) -> int:
    stmt = delete(ClusterModel).where(ClusterModel.id == cluster_id)
    result = await self._session.execute(stmt)
    return get_rowcount(result)  # No type: ignore needed
```

**Methodology**:

- Create utility module
- Find/replace all `result.rowcount  # type: ignore`
- Add unit test for helper

**Success Metrics**:

| Metric                                      | Before | After |
| ------------------------------------------- | ------ | ----- |
| `# type: ignore[attr-defined]` for rowcount | 4      | 0     |
| Centralized accessor                        | ❌     | ✅    |
| mypy strict mode compatible                 | ❌     | ✅    |

---

### ✅ 19. `scan_worker.py` Has Multiple Responsibilities

**File**: `recognition/worker/scan_worker.py` (561 lines)

**Problem**: Worker handles:

- Scan queue polling
- Clustering job polling
- Split job handling
- Curation job handling
- Job progress refresh
- Auto-creation of clustering jobs after scan

**Recommendation**: Consider handler pattern:

```python
class ClusteringJobHandler:
    async def handle(self, job: IdentityClusteringJob) -> None: ...

class ScanJobHandler:
    async def handle(self, item: ScanQueueItem) -> None: ...
```

**Implementation**:

```python
# recognition/worker/handlers/__init__.py
from .base import JobHandler
from .scan import ScanJobHandler
from .clustering import ClusteringJobHandler
from .curation import CurationJobHandler
from .split import SplitJobHandler

# recognition/worker/handlers/base.py
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

T = TypeVar("T")

class JobHandler(ABC, Generic[T]):
    @abstractmethod
    async def handle(self, job: T, session: AsyncSession) -> None:
        ...

# recognition/worker/handlers/clustering.py
class ClusteringJobHandler(JobHandler[IdentityClusteringJob]):
    def __init__(self, cluster_service: ClusterService):
        self._cluster_service = cluster_service

    async def handle(self, job: IdentityClusteringJob, session: AsyncSession) -> None:
        await self._cluster_service.cluster_unclustered(
            tenant_id=job.tenant_id,
            job_id=job.id,
        )

# recognition/worker/scan_worker.py (refactored)
class ScanWorker:
    def __init__(self, handlers: dict[str, JobHandler]):
        self._handlers = handlers

    async def _dispatch_job(self, job: IdentityClusteringJob) -> None:
        handler = self._handlers.get(job.job_type)
        if handler:
            await handler.handle(job, self._session)
```

**Methodology**:

- Extract one handler at a time
- Keep worker as dispatcher only
- Add integration tests per handler

**Success Metrics**:

| Metric                     | Before | After        |
| -------------------------- | ------ | ------------ |
| `scan_worker.py` lines     | 561    | <150         |
| Responsibilities per class | 6      | 1 (dispatch) |
| Handler test isolation     | None   | Per-handler  |

---

### ✅ 20. Dialect-Specific SQL Scattered

**File**: `recognition/infrastructure/repositories/scan_queue_repository.py`

**Problem**: SQLite vs PostgreSQL branching logic inline:

```python
if is_sqlite(self._session):
    sa_cast(func.strftime("%s", ...), Integer) < int(stale_before_ts)
else:
    IdentityScanJobItem.started_at < stale_before
```

**Recommendation**: Centralize dialect handling in a query builder or use SQLAlchemy `type_coerce` consistently.

**Implementation**:

```python
# recognition/infrastructure/db/dialect.py
from sqlalchemy import Integer, func
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement
from datetime import datetime

def is_sqlite(session: Session) -> bool:
    return session.bind.dialect.name == "sqlite" if session.bind else False

def timestamp_column(col: ColumnElement[datetime], session: Session) -> ColumnElement[int]:
    """Convert datetime column to Unix timestamp, dialect-aware."""
    if is_sqlite(session):
        return func.cast(func.strftime("%s", col), Integer)
    return func.extract("epoch", col).cast(Integer)

def timestamp_lt(col: ColumnElement[datetime], threshold: datetime, session: Session):
    """Datetime < threshold comparison, dialect-aware."""
    if is_sqlite(session):
        return func.cast(func.strftime("%s", col), Integer) < int(threshold.timestamp())
    return col < threshold
```

**Methodology**:

- Grep for `is_sqlite` and `strftime` patterns
- Replace with centralized helpers
- Add tests for both SQLite and PostgreSQL dialects

**Success Metrics**:

| Metric                               | Before    | After       |
| ------------------------------------ | --------- | ----------- |
| Inline dialect checks                | 5+        | 0           |
| Dialect-specific SQL in repositories | Scattered | Centralized |
| Dialect test coverage                | Implicit  | Explicit    |

---

### ✅ 21. Heavy Use of `typing.cast` for CursorResult

**Files**: Multiple infrastructure repositories

**Problem**: 20+ instances of `cast(CursorResult[Any], result)` to satisfy type checker:

```python
cursor = typing_cast(CursorResult[Any], result)
```

**Root Cause**: SQLAlchemy async `execute()` returns union type.

**Recommendation**: Wrap in typed helper or use protocol with proper overloads.

**Implementation**:

```python
# recognition/infrastructure/db/utils.py
from typing import Any, TypeVar, overload
from sqlalchemy import Result
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")

async def execute_dml(session: AsyncSession, stmt) -> CursorResult[Any]:
    """Execute a DML statement and return typed CursorResult.

    Use for INSERT, UPDATE, DELETE where you need rowcount.
    """
    result = await session.execute(stmt)
    # Runtime: always CursorResult for DML
    return result  # type: ignore[return-value]

async def execute_select(session: AsyncSession, stmt) -> Result[T]:
    """Execute a SELECT statement and return typed Result."""
    return await session.execute(stmt)

# Usage:
result = await execute_dml(session, delete_stmt)
count = result.rowcount  # No cast needed
```

Alternative — SQLAlchemy 2.0 style with `Result.rowcount`:

```python
# If upgrading SQLAlchemy, rowcount is on Result directly
from sqlalchemy import Result
result: Result = await session.execute(stmt)
count = result.rowcount  # Typed correctly in SA 2.0
```

**Methodology**:

- Audit SQLAlchemy version and available typing
- Create wrapper for current version
- Plan migration to SA 2.0 typing if upgrading

**Success Metrics**:

| Metric                               | Before         | After       |
| ------------------------------------ | -------------- | ----------- |
| `typing.cast(CursorResult` instances | 20+            | 0           |
| Type safety for DML results          | Cast-dependent | Native      |
| SQLAlchemy typing workarounds        | Ad-hoc         | Centralized |

---

## 🔵 Orchestration Layer Issues

Audit of `recognition/application/orchestration/` directory (2,841 total lines).

| File                        | Lines | Description                |
| --------------------------- | ----- | -------------------------- |
| `incremental_clustering.py` | 753   | Documented in #16          |
| `cluster_curation.py`       | 562   | CRUD + curation operations |
| `cluster_split.py`          | 494   | Split operations           |
| `cluster_service.py`        | 330   | Façade class               |
| `cluster_merge.py`          | 313   | Merge operations           |
| `job_service.py`            | 206   | Job orchestration          |
| `curation_job.py`           | 126   | Post-curation recompute    |
| `protocols.py`              | 50    | Shared protocols           |

---

### ✅ 22. Private Member Access Pattern Throughout Orchestration

**Files**: All orchestration modules access `AssignmentWriter` internals

**Problem**: 20+ instances of accessing private `_clusters` and `_members` attributes:

```python
# cluster_merge.py L50-51
cluster_repo: ClusterRepository = assignment_writer._clusters
member_repo: MemberRepository = assignment_writer._members

# cluster_curation.py L113, L272-273, L353-354
cluster_repo: ClusterRepository = assignment_writer._clusters

# cluster_service.py L158, L183, L277, L298-299, L323
cluster_repo = self.assignment_writer._clusters
member_repo=self.assignment_writer._members

# incremental_clustering.py L155, L444, L666
await assignment_writer._clusters.cleanup_orphaned_provisional_reps(str(tenant_id))

# job_service.py L180
cluster_repo=self.cluster_service.assignment_writer._clusters
```

**Impact**:

- Breaks encapsulation
- Tests must access private members (see issue #3)
- Refactoring `AssignmentWriter` internals breaks all callers

**Root Cause**: `AssignmentWriter` doesn't expose repositories via public interface.

**Implementation**:

```python
# assignment_writer.py
class AssignmentWriter:
    def __init__(
        self,
        clusters: ClusterRepository,
        members: MemberRepository,
        ...
    ):
        self._clusters = clusters
        self._members = members

    @property
    def cluster_repository(self) -> ClusterRepository:
        """Public accessor for cluster repository."""
        return self._clusters

    @property
    def member_repository(self) -> MemberRepository:
        """Public accessor for member repository."""
        return self._members
```

Then find/replace:

```bash
sed -i 's/assignment_writer\._clusters/assignment_writer.cluster_repository/g' **/*.py
sed -i 's/assignment_writer\._members/assignment_writer.member_repository/g' **/*.py
```

**Methodology**:

- Add public properties to `AssignmentWriter`
- Global find/replace across orchestration layer
- Verify tests pass
- Consider deprecating private access with warning

**Success Metrics**:

| Metric                      | Before | After |
| --------------------------- | ------ | ----- |
| `._clusters` accesses       | 20+    | 0     |
| `._members` accesses        | 10+    | 0     |
| Public repository accessors | 0      | 2     |
| Encapsulation violations    | High   | None  |

---

### ✅ 23. Defensive `getattr()` Pattern Overuse

**Files**: Multiple orchestration modules

**Problem**: 20+ instances of `getattr()` to check for optional methods, often repeated:

```python
# Repeated pattern in cluster_curation.py, curation_job.py, cluster_split.py
recompute_reps = getattr(assignment_writer, "recompute_representatives", None)
if callable(recompute_reps):
    await recompute_reps(cluster_id)

recompute_centroid = getattr(assignment_writer, "recompute_centroid", None)
if callable(recompute_centroid):
    await recompute_centroid(cluster_id)

refresh_view = getattr(assignment_writer, "refresh_centroids_view", None)
if callable(refresh_view):
    await refresh_view()
```

**Locations**:

- `cluster_curation.py`: L212-220, L318, L427-430
- `curation_job.py`: L49-55
- `cluster_split.py`: L328-336
- `cluster_service.py`: L197, L283-284
- `incremental_clustering.py`: L201-206

**Impact**:

- Code duplication (same 6-line pattern repeated 5+ times)
- `AssignmentWriter` interface is unclear
- No type safety for optional methods

**Implementation**:

Option A — Add methods to protocol:

```python
# Make methods required on AssignmentWriter
class AssignmentWriter:
    async def recompute_representatives(self, cluster_id: str) -> None: ...
    async def recompute_centroid(self, cluster_id: str) -> None: ...
    async def refresh_centroids_view(self) -> None: ...
```

Option B — Create helper:

```python
# recognition/application/orchestration/helpers.py
async def recompute_cluster(assignment_writer: AssignmentWriter, cluster_id: str) -> None:
    """Recompute representatives and centroid for a cluster."""
    if hasattr(assignment_writer, "recompute_representatives"):
        await assignment_writer.recompute_representatives(cluster_id)
    if hasattr(assignment_writer, "recompute_centroid"):
        await assignment_writer.recompute_centroid(cluster_id)

async def refresh_views(assignment_writer: AssignmentWriter) -> None:
    """Refresh materialized views if available."""
    if hasattr(assignment_writer, "refresh_centroids_view"):
        await assignment_writer.refresh_centroids_view()
```

**Methodology**:

- Audit which methods are always present vs optional
- Make always-present methods explicit in protocol
- Create helper for optional refresh operations
- Replace scattered `getattr` patterns

**Success Metrics**:

| Metric                               | Before  | After      |
| ------------------------------------ | ------- | ---------- |
| Repeated `getattr` patterns          | 10+     | 0          |
| Lines of defensive code              | ~60     | ~10        |
| `AssignmentWriter` method visibility | Unclear | Documented |

---

### ✅ 24. Tenant UUID Coercion Scattered Across Modules

**Files**: Multiple orchestration modules

**Problem**: Tenant UUID parsing/coercion logic duplicated in 5+ locations:

```python
# incremental_clustering.py L112-128 (handles MD5 hash format)
tenant_str = str(tenant_id).replace("-", "")
if len(tenant_str) == 32:
    formatted = f"{tenant_str[:8]}-{tenant_str[8:12]}-..."
    tenant_uuid = uuid.UUID(formatted)
else:
    tenant_uuid = uuid.UUID(str(tenant_id))

# cluster_curation.py L51, L263, L360 (simple conversion)
tenant_uuid = uuid.UUID(str(tenant_id))

# cluster_merge.py L155
tenant_uuid = uuid.UUID(str(tenant_id))

# cluster_split.py L210
tenant_uuid = uuid.UUID(original_cluster.tenant_id)
```

**Impact**:

- `incremental_clustering.py` handles MD5 format, others don't
- Inconsistent error handling
- Violates DRY

**Implementation**:

```python
# recognition/shared/tenant.py
import uuid

class TenantIdError(ValueError):
    """Invalid tenant ID format."""
    pass

def coerce_tenant_uuid(tenant_id: str) -> uuid.UUID:
    """Convert tenant ID to UUID, handling MD5 hash format.

    Args:
        tenant_id: UUID string or 32-char MD5 hash (no dashes)

    Returns:
        Parsed UUID

    Raises:
        TenantIdError: If format is invalid
    """
    try:
        tenant_str = str(tenant_id).replace("-", "")
        if len(tenant_str) == 32:
            formatted = f"{tenant_str[:8]}-{tenant_str[8:12]}-{tenant_str[12:16]}-{tenant_str[16:20]}-{tenant_str[20:]}"
            return uuid.UUID(formatted)
        return uuid.UUID(str(tenant_id))
    except ValueError as exc:
        raise TenantIdError(f"Invalid tenant_id format: {tenant_id}") from exc
```

**Methodology**:

- Create `recognition/shared/tenant.py`
- Replace all inline UUID conversions
- Add unit tests for MD5 and standard UUID formats
- Consistent error type for callers

**Success Metrics**:

| Metric                         | Before          | After                   |
| ------------------------------ | --------------- | ----------------------- |
| Tenant UUID coercion locations | 8               | 1                       |
| MD5 format handling            | 1 location only | All locations           |
| Error handling consistency     | Varies          | Uniform `TenantIdError` |

---

### ✅ 25. `cluster_curation.py` is 562 Lines with 9 Functions

**File**: `recognition/application/orchestration/cluster_curation.py`

**Problem**: Single module handles too many distinct operations:

| Function                              | Lines    | Responsibility              |
| ------------------------------------- | -------- | --------------------------- |
| `is_outlier_cluster()`                | L38-42   | Outlier detection           |
| `build_outlier_cluster()`             | L45-75   | Pseudo-cluster construction |
| `list_clusters()`                     | L78-100  | Query clusters              |
| `update_cluster()`                    | L104-162 | Update metadata             |
| `get_identity_cluster_id()`           | L165-170 | Lookup helper               |
| `remove_identity_from_cluster()`      | L173-246 | Remove + cleanup            |
| `create_cluster_for_identity()`       | L249-338 | Create new cluster          |
| `assign_outlier_to_cluster()`         | L341-472 | Assign identity             |
| `compute_curation_similarity()`       | L475-511 | Similarity helper           |
| `check_and_refresh_representatives()` | L514-562 | Rep maintenance             |

**Root Cause**: File grew organically as curation features were added.

**Implementation**:

```
recognition/application/orchestration/
  curation/
    __init__.py
    outlier.py              # is_outlier_cluster, build_outlier_cluster
    cluster_queries.py      # list_clusters, get_identity_cluster_id
    cluster_mutations.py    # update_cluster, remove_identity, create_cluster, assign_outlier
    similarity.py           # compute_curation_similarity, check_and_refresh_representatives
```

**Methodology**:

- Group by read vs write operations
- Extract helpers to shared module
- Keep imports backward-compatible via `__init__.py`

**Success Metrics**:

| Metric                      | Before | After                        |
| --------------------------- | ------ | ---------------------------- |
| `cluster_curation.py` lines | 562    | Deleted (split into 4 files) |
| Largest module in curation/ | N/A    | <150 lines                   |
| Import compatibility        | N/A    | Preserved via re-exports     |

---

### ✅ 26. `cluster_split.py` is 494 Lines with Long Main Function

**File**: `recognition/application/orchestration/cluster_split.py`

**Problem**: `split_cluster()` function is 320 lines (L71-390) handling:

- Member fetching
- Embedding extraction
- Hierarchical clustering
- Label assignment
- Member movement
- Block creation
- Representative recompute
- Suggestion refresh
- Event broadcasting

**Implementation**:

```python
# Split into focused modules
recognition/application/orchestration/
  split/
    __init__.py
    plan.py                 # SplitPlan, SplitStrategy, SplitScope dataclasses
    hierarchical.py         # HAC-based splitting logic
    anchor.py               # _force_anchor_split, _determine_label_owner
    executor.py             # split_cluster (thin orchestrator)
```

**Methodology**:

- Extract `SplitPlan` dataclass and enums to dedicated module
- Extract HAC logic to `hierarchical.py`
- Keep `split_cluster()` as thin orchestrator

**Success Metrics**:

| Metric                   | Before | After                        |
| ------------------------ | ------ | ---------------------------- |
| `cluster_split.py` lines | 494    | Deleted (split into 4 files) |
| `split_cluster()` lines  | 320    | <80                          |
| Helper functions         | Inline | Separate modules             |

---

## 🔵 Clustering Layer Issues

Audit of `recognition/application/clustering/` directory (666 total lines).

| File                                | Lines | Description                     |
| ----------------------------------- | ----- | ------------------------------- |
| `representative_only_clustering.py` | 296   | Cold-start clustering algorithm |
| `hierarchical_clustering.py`        | 187   | HAC for cluster splitting       |
| `constrained_hac.py`                | 92    | HAC with pairwise constraints   |
| `centroid_utils.py`                 | 91    | Centroid computation helpers    |

---

### 27. `representative_only_clustering.py` Has 7 Levels of Nested Conditionals

**File**: `recognition/application/clustering/representative_only_clustering.py`  
**Lines**: 130-270 (main `cluster()` method)

**Problem**: The `cluster()` method is 170 lines with deeply nested conditionals:

```python
for identity in identities:                                              # Level 1
    # ... embedding prep ...
    for cluster_id, rep_embeddings in local_representatives.items():     # Level 2
        for rep_emb in rep_embeddings:                                   # Level 3
            if similarity > best_similarity:                             # Level 4
                # ...

    if best_cluster_id and best_similarity >= self.high_confidence_threshold:  # Level 2
        if best_cluster_id in batch_cluster_ids:                         # Level 3
            for cluster in created_clusters:                             # Level 4
                if cluster.id == best_cluster_id:                        # Level 5
                    if add_to_cluster:                                   # Level 6
                        # ...
                    else:
                        if self._create_suggestion:                      # Level 7
                            # ...
                        else:
                            # create singleton
```

**Impact**:

- Cognitive complexity exceeds 15 (recommended max: 10)
- Difficult to test individual decision branches
- Logic buried inside nested blocks
- 5+ branches handle edge cases with duplicated logging

**Root Cause**: Three concerns conflated in one method:

1. Finding best matching cluster (similarity search)
2. Deciding action based on confidence thresholds
3. Executing that action (add/suggest/singleton)

**Implementation**:

```python
# Option A: Extract helper methods

from dataclasses import dataclass
from enum import Enum, auto

class ClusterDecision(Enum):
    """Result of matching an identity against existing clusters."""
    HIGH_CONFIDENCE_MATCH = auto()
    SUGGESTION_MATCH = auto()
    NO_MATCH = auto()

@dataclass
class MatchResult:
    """Result of finding best matching cluster."""
    cluster_id: UUID | None
    similarity: float
    is_batch_cluster: bool

    def decision(self, high_conf: float, suggestion_thresh: float) -> ClusterDecision:
        """Determine action based on thresholds."""
        if self.cluster_id and self.similarity >= high_conf:
            return ClusterDecision.HIGH_CONFIDENCE_MATCH
        elif self.cluster_id and self.similarity >= suggestion_thresh:
            return ClusterDecision.SUGGESTION_MATCH
        return ClusterDecision.NO_MATCH


class RepresentativeOnlyClustering:
    def _find_best_match(
        self,
        embedding: np.ndarray,
        representatives: dict[UUID, list[np.ndarray]],
        batch_cluster_ids: set[UUID],
    ) -> MatchResult:
        """Find best matching cluster for an embedding."""
        best_id = None
        best_sim = 0.0
        for cluster_id, rep_embeddings in representatives.items():
            for rep_emb in rep_embeddings:
                sim = float(np.dot(embedding, rep_emb))
                if sim > best_sim:
                    best_sim = sim
                    best_id = cluster_id
        return MatchResult(best_id, best_sim, best_id in batch_cluster_ids if best_id else False)

    async def _execute_high_confidence(
        self,
        identity: MediaIdentity,
        match: MatchResult,
        add_to_cluster: AddToClusterFn | None,
        create_cluster: CreateClusterFn,
        local_representatives: dict[UUID, list[np.ndarray]],
        batch_cluster_ids: set[UUID],
        created_clusters: list[IdentityCluster],
        log_prefix: str,
    ) -> tuple[IdentityCluster | None, str]:
        """Handle high-confidence match. Returns (new_cluster, action_taken)."""
        if add_to_cluster:
            await add_to_cluster(match.cluster_id, [identity])
            return None, "matched"
        elif self._create_suggestion:
            await self._create_suggestion(identity.id, match.cluster_id, match.similarity, match.similarity)
            return None, "suggested"
        else:
            # Fallback: create singleton
            cluster, _ = await create_cluster([identity])
            return cluster, "singleton_fallback"

    async def _create_singleton_with_suggestion(
        self,
        identity: MediaIdentity,
        match: MatchResult,
        create_cluster: CreateClusterFn,
        batch_cluster_ids: set[UUID],
        log_prefix: str,
    ) -> IdentityCluster:
        """Create singleton and optionally suggest merge with matched cluster."""
        cluster, _ = await create_cluster([identity])

        if self._create_suggestion and match.cluster_id not in batch_cluster_ids:
            try:
                await self._create_suggestion(
                    identity.id, match.cluster_id, match.similarity, match.similarity
                )
            except Exception as e:
                logger.warning("%sFailed to create suggestion: %s", log_prefix, e)

        return cluster

    async def cluster(self, ...) -> list[IdentityCluster]:
        """Simplified main loop using extracted helpers."""
        # ... setup ...

        for identity in identities:
            embedding = self._normalize_embedding(identity)
            match = self._find_best_match(embedding, local_representatives, batch_cluster_ids)
            decision = match.decision(self.high_confidence_threshold, self.suggestion_threshold)

            match decision:
                case ClusterDecision.HIGH_CONFIDENCE_MATCH:
                    new_cluster, action = await self._execute_high_confidence(...)
                case ClusterDecision.SUGGESTION_MATCH:
                    new_cluster = await self._create_singleton_with_suggestion(...)
                case ClusterDecision.NO_MATCH:
                    new_cluster, _ = await create_cluster([identity])

            if new_cluster:
                created_clusters.append(new_cluster)
                batch_cluster_ids.add(new_cluster.id)
                local_representatives[new_cluster.id] = [embedding]

        return created_clusters
```

**Methodology**:

1. Extract `_find_best_match()` — pure function, easy to unit test
2. Extract `_execute_high_confidence()` — handles one decision branch
3. Extract `_create_singleton_with_suggestion()` — handles another branch
4. Use `match` statement for clarity (Python 3.10+)
5. Reduce main loop to 20-30 lines

**Success Metrics**:

| Metric                         | Before | After |
| ------------------------------ | ------ | ----- |
| Max nesting depth              | 7      | 3     |
| Cognitive complexity           | ~20    | <10   |
| `cluster()` method lines       | 170    | ~40   |
| Testable helper methods        | 0      | 3     |
| Decision branches in main loop | 5+     | 3     |

---

### 28. `constrained_hac.py` Inlines Constraint Penalty Logic

**File**: `recognition/application/clustering/constrained_hac.py`  
**Lines**: 63-75

**Problem**: Constraint penalty application is embedded in the main method:

```python
for c in constraints:
    i = id_to_idx.get(c.identity_a)
    j = id_to_idx.get(c.identity_b)

    if i is not None and j is not None:
        if c.constraint_type == ConstraintType.MUST_LINK:
            dist_matrix[i, j] = 0.0
            dist_matrix[j, i] = 0.0
        elif c.constraint_type == ConstraintType.CANNOT_LINK:
            pen = self.settings.constraint_penalty
            dist_matrix[i, j] = max(dist_matrix[i, j], pen)
            dist_matrix[j, i] = max(dist_matrix[j, i], pen)
```

**Impact**:

- Cannot test penalty logic in isolation
- Adding new constraint types requires modifying main method
- Symmetric matrix update duplicated

**Implementation**:

```python
def _apply_constraint_to_matrix(
    dist_matrix: np.ndarray,
    constraint: IdentityConstraint,
    id_to_idx: dict[UUID, int],
    penalty: float,
) -> None:
    """Apply a single constraint to the distance matrix (in-place)."""
    i = id_to_idx.get(constraint.identity_a)
    j = id_to_idx.get(constraint.identity_b)

    if i is None or j is None:
        return

    match constraint.constraint_type:
        case ConstraintType.MUST_LINK:
            dist_matrix[i, j] = dist_matrix[j, i] = 0.0
        case ConstraintType.CANNOT_LINK:
            max_val = max(dist_matrix[i, j], penalty)
            dist_matrix[i, j] = dist_matrix[j, i] = max_val
        case _:
            pass  # Unknown constraint type - ignore
```

**Methodology**:

- Extract to module-level function
- Use `match` statement for extensibility
- Add test for each constraint type

**Success Metrics**:

| Metric                            | Before   | After                |
| --------------------------------- | -------- | -------------------- |
| `refine_clusters()` lines         | 50       | 35                   |
| Constraint logic testable         | No       | Yes                  |
| Constraint type handler locations | 1 inline | 1 extracted function |

---

## 🔵 Discovery Layer Issues

Audit of `recognition/application/discovery/` directory (776 total lines).

| File                | Lines | Description                                |
| ------------------- | ----- | ------------------------------------------ |
| `graph.py`          | 482   | HDBSCAN-based discovery (anchor injection) |
| `representative.py` | 155   | Representative matching discovery          |
| `centroid.py`       | 88    | Centroid matching discovery                |
| `base.py`           | 35    | Abstract `DiscoveryAlgorithm` interface    |
| `__init__.py`       | 16    | Re-exports                                 |

---

### ✅ 29. Discovery and Clustering Modules Have Overlapping Responsibilities

**Files**:

- `recognition/application/discovery/` (776 lines)
- `recognition/application/clustering/` (666 lines)

**Problem**: Both modules implement **similarity search** with near-identical patterns:

| Pattern                        | Discovery                                       | Clustering                                               |
| ------------------------------ | ----------------------------------------------- | -------------------------------------------------------- |
| Find best representative match | `RepresentativeDiscovery._find_best_match()`    | `RepresentativeOnlyClustering` loop (L140-150)           |
| Find best centroid match       | `CentroidDiscovery._find_best_centroid_match()` | `centroid_utils.compute_similarity()`                    |
| Normalize + dot product        | 8+ locations in discovery                       | 5+ locations in clustering                               |
| Threshold-based decisions      | `settings.similarity_threshold`                 | `settings.similarity_threshold`                          |
| Handle labeled vs unlabeled    | `RepresentativeDiscovery` (L140-155)            | `RepresentativeOnlyClustering` (high_conf vs suggestion) |

**Code Duplication Examples**:

```python
# discovery/representative.py L120-134
for cluster_id, representatives in representatives_by_cluster.items():
    for rep in representatives:
        rep_vec = normalize_face_embedding(np.asarray(rep, dtype=np.float32))
        similarity = float(np.dot(face_vector, rep_vec))
        if similarity > best_similarity:
            best_similarity = similarity
            best_cluster = cluster_id

# clustering/representative_only_clustering.py L143-149
for cluster_id, rep_embeddings in local_representatives.items():
    for rep_emb in rep_embeddings:
        similarity = float(np.dot(identity_embedding, rep_emb))
        if similarity > best_similarity:
            best_similarity = similarity
            best_cluster_id = cluster_id
```

**Conceptual Overlap**:

- **Discovery** = "Find candidates for existing clusters" (returns `AssignmentCandidate`)
- **Clustering** = "Group new identities into clusters" (returns `IdentityCluster`)

But `RepresentativeOnlyClustering` actually does BOTH:

1. Matches new identities to existing clusters (discovery)
2. Creates new singleton clusters (clustering)

**Root Cause**: The two modules evolved independently for different use cases:

- Discovery: Incremental assignment to existing clusters
- Clustering: Cold-start batch clustering

**Impact**:

- 200+ lines of duplicated similarity search logic
- Two sets of thresholds to maintain (`similarity_threshold`, `high_confidence_threshold`, `suggestion_threshold`, `anchor_discovery_threshold`)
- Algorithm changes must be applied to both modules
- Confusing API: when to use discovery vs clustering?

**Implementation**:

**Option A — Unified Similarity Search Layer**

Create a shared `SimilaritySearch` service:

```python
# recognition/application/similarity/search.py
from dataclasses import dataclass
from uuid import UUID

import numpy as np

from recognition.shared.similarity import normalize_face_embedding


@dataclass
class MatchResult:
    """Result of similarity search."""
    cluster_id: str | None
    similarity: float
    match_type: str  # "representative", "centroid", "anchor"
    is_labeled: bool = False


class SimilaritySearch:
    """Unified similarity search across cluster representatives."""

    def __init__(self, threshold: float) -> None:
        self.threshold = threshold

    def find_best_representative_match(
        self,
        face_vector: np.ndarray,
        representatives_by_cluster: dict[str, list[np.ndarray]],
        labeled_cluster_ids: set[str] | None = None,
    ) -> MatchResult:
        """Find best matching cluster by representative similarity."""
        labeled_ids = labeled_cluster_ids or set()
        best = MatchResult(None, 0.0, "representative")
        best_labeled = MatchResult(None, 0.0, "representative", is_labeled=True)

        for cluster_id, reps in representatives_by_cluster.items():
            for rep in reps:
                rep_vec = normalize_face_embedding(np.asarray(rep, dtype=np.float32))
                sim = float(np.dot(face_vector, rep_vec))

                if sim > best.similarity:
                    best = MatchResult(cluster_id, sim, "representative", cluster_id in labeled_ids)

                if cluster_id in labeled_ids and sim > best_labeled.similarity:
                    best_labeled = MatchResult(cluster_id, sim, "representative", True)

        return best, best_labeled

    def find_best_centroid_match(
        self,
        face_vector: np.ndarray,
        centroids_by_cluster: dict[str, np.ndarray],
    ) -> MatchResult:
        """Find best matching cluster by centroid similarity."""
        best = MatchResult(None, 0.0, "centroid")

        for cluster_id, centroid in centroids_by_cluster.items():
            centroid_vec = normalize_face_embedding(np.asarray(centroid, dtype=np.float32))
            sim = float(np.dot(face_vector, centroid_vec))
            if sim > best.similarity:
                best = MatchResult(cluster_id, sim, "centroid")

        return best
```

Then refactor both modules to use it:

```python
# discovery/representative.py
class RepresentativeDiscovery(DiscoveryAlgorithm):
    def __init__(self, settings: ClusteringSettings, search: SimilaritySearch) -> None:
        self.settings = settings
        self.search = search

    async def discover(self, identities, representatives_by_cluster, labeled_cluster_ids=None):
        candidates = []
        for identity in identities:
            match, labeled_match = self.search.find_best_representative_match(
                identity.face_vector, representatives_by_cluster, labeled_cluster_ids
            )
            # Use labeled_match for suggestions, match for auto-assign
            ...
```

**Option B — Merge Modules**

Consolidate into a single `recognition/application/matching/` module:

```
recognition/application/matching/
  __init__.py
  search.py              # SimilaritySearch (shared)
  representative.py      # Representative matching (replaces discovery + cold-start)
  centroid.py            # Centroid matching
  graph.py               # Graph-based (HDBSCAN)
  decision.py            # Threshold decisions (auto-assign, suggest, create)
```

**Methodology**:

1. Audit all `np.dot()` calls across both modules
2. Extract shared similarity search to new module
3. Refactor discovery to use shared search
4. Refactor clustering to use shared search
5. Verify identical behavior via existing tests
6. Consolidate threshold settings

**Success Metrics**:

| Metric                               | Before       | After               |
| ------------------------------------ | ------------ | ------------------- |
| Duplicate similarity loops           | 6+           | 0                   |
| Total lines (discovery + clustering) | 1,442        | ~900                |
| Shared similarity search module      | 0            | 1                   |
| Threshold parameters                 | 4+ scattered | Unified in settings |

---

### 30. `graph.py` is 482 Lines with Multiple Responsibilities

**File**: `recognition/application/discovery/graph.py`

**Problem**: Single module handles too many concerns:

| Concern                   | Lines    | Description                     |
| ------------------------- | -------- | ------------------------------- |
| GraphAlgorithm interface  | L45-57   | Abstract base                   |
| AnchorIdentity dataclass  | L26-31   | Anchor wrapper                  |
| GraphDiscoveryResult      | L34-43   | Result container                |
| GraphDiscovery main class | L60-310  | Core logic                      |
| Algorithm selection       | L385-408 | HDBSCAN config                  |
| Similarity helpers        | L330-380 | `_compute_avg_similarity`, etc. |
| Embedding stats           | L310-328 | Diagnostic logging              |

**Impact**:

- 483 lines in single file
- `discover()` method is 130+ lines
- Helpers mixed with core logic
- Hard to test algorithm selection separately

**Implementation**:

```
recognition/application/discovery/
  graph/
    __init__.py              # Re-exports GraphDiscovery
    algorithm.py             # GraphAlgorithm ABC, AnchorIdentity, GraphDiscoveryResult
    discovery.py             # GraphDiscovery class (~200 lines)
    helpers.py               # _compute_avg_similarity, _compute_member_similarities, etc.
    selection.py             # _select_algorithm, _hdbscan_available
```

**Methodology**:

- Extract dataclasses and ABC to `algorithm.py`
- Extract static helpers to `helpers.py`
- Extract algorithm selection to `selection.py`
- Keep `GraphDiscovery` as thin orchestrator

**Success Metrics**:

| Metric                    | Before | After                        |
| ------------------------- | ------ | ---------------------------- |
| `graph.py` lines          | 482    | Deleted (split into 4 files) |
| `discover()` lines        | 130    | ~80                          |
| Testable helper functions | Mixed  | Isolated in `helpers.py`     |

---

### ✅ 31. Clustering Performance Improvements

**Current Issues**:

1. **O(n × m) brute-force search** in representative matching:

   ```python
   for cluster_id, rep_embeddings in local_representatives.items():  # m clusters
       for rep_emb in rep_embeddings:  # k reps per cluster
           similarity = float(np.dot(identity_embedding, rep_emb))  # n identities
   ```

   Complexity: O(n × m × k) for n identities, m clusters, k representatives

2. **Repeated normalization** — vectors normalized on every comparison instead of once at load

3. **No batch vectorization** — similarity computed one-at-a-time instead of matrix multiply

4. **HDBSCAN overhead** for small batches — graph algorithm invoked even for <10 identities

**Implementation**:

**A. Vectorized Batch Similarity**

```python
# recognition/application/similarity/batch.py
import numpy as np

def batch_similarity_matrix(
    query_vectors: np.ndarray,  # (n, d)
    reference_vectors: np.ndarray,  # (m, d)
) -> np.ndarray:
    """Compute all pairwise similarities in one matrix multiply.

    Args:
        query_vectors: (n, d) array of normalized query embeddings
        reference_vectors: (m, d) array of normalized reference embeddings

    Returns:
        (n, m) similarity matrix where result[i, j] = dot(query[i], ref[j])
    """
    # Single BLAS call instead of n*m Python loops
    return query_vectors @ reference_vectors.T


def find_best_matches(
    query_vectors: np.ndarray,
    reference_vectors: np.ndarray,
    reference_cluster_ids: list[str],
) -> list[tuple[str, float]]:
    """Find best matching cluster for each query vector.

    Returns:
        List of (cluster_id, similarity) for each query vector
    """
    similarities = batch_similarity_matrix(query_vectors, reference_vectors)
    best_indices = np.argmax(similarities, axis=1)
    best_sims = similarities[np.arange(len(query_vectors)), best_indices]

    return [(reference_cluster_ids[i], float(s)) for i, s in zip(best_indices, best_sims)]
```

**B. Pre-normalized Representative Cache**

```python
# recognition/application/similarity/cache.py
from dataclasses import dataclass
import numpy as np

@dataclass
class RepresentativeCache:
    """Pre-normalized representatives for fast similarity search."""

    cluster_ids: list[str]  # Cluster ID for each row
    vectors: np.ndarray     # (total_reps, 512) pre-normalized
    cluster_start_idx: dict[str, int]  # Start index for each cluster
    cluster_count: dict[str, int]      # Rep count per cluster

    @classmethod
    def from_dict(cls, reps_by_cluster: dict[str, list[np.ndarray]]) -> "RepresentativeCache":
        """Build cache from cluster -> representatives dict."""
        cluster_ids = []
        vectors = []
        cluster_start_idx = {}
        cluster_count = {}

        idx = 0
        for cluster_id, reps in reps_by_cluster.items():
            cluster_start_idx[cluster_id] = idx
            cluster_count[cluster_id] = len(reps)
            for rep in reps:
                cluster_ids.append(cluster_id)
                vec = np.asarray(rep, dtype=np.float32)
                vec = vec / (np.linalg.norm(vec) + 1e-8)  # Normalize once
                vectors.append(vec)
            idx += len(reps)

        return cls(
            cluster_ids=cluster_ids,
            vectors=np.stack(vectors) if vectors else np.empty((0, 512), dtype=np.float32),
            cluster_start_idx=cluster_start_idx,
            cluster_count=cluster_count,
        )
```

**C. Approximate Nearest Neighbor (ANN) for Large Scale — POST-MVP**

> ⚠️ **Deferred to post-MVP**: Brute-force `np.dot()` handles 10k vectors in ~2ms.
> FAISS adds C++ build complexity and index maintenance overhead.
> Revisit only when monitoring shows >10k representatives per tenant.

For >50k representatives, consider FAISS or Annoy:

```python
# recognition/application/similarity/ann.py
from typing import Protocol

class ANNIndex(Protocol):
    """Protocol for approximate nearest neighbor indices."""

    def add(self, vectors: np.ndarray, ids: list[str]) -> None: ...
    def search(self, query: np.ndarray, k: int) -> list[tuple[str, float]]: ...


class FaissANNIndex:
    """FAISS-based ANN index for large representative sets."""

    def __init__(self, dimension: int = 512, use_gpu: bool = False):
        import faiss
        self.index = faiss.IndexFlatIP(dimension)  # Inner product = cosine for normalized
        if use_gpu:
            self.index = faiss.index_cpu_to_gpu(faiss.StandardGpuResources(), 0, self.index)
        self.id_map: list[str] = []

    def add(self, vectors: np.ndarray, ids: list[str]) -> None:
        self.index.add(vectors.astype(np.float32))
        self.id_map.extend(ids)

    def search(self, query: np.ndarray, k: int = 5) -> list[tuple[str, float]]:
        distances, indices = self.index.search(query.reshape(1, -1).astype(np.float32), k)
        return [(self.id_map[i], float(d)) for i, d in zip(indices[0], distances[0]) if i >= 0]
```

**D. Algorithm Selection Based on Scale**

```python
# In GraphDiscovery or new matcher
def select_search_strategy(identity_count: int, cluster_count: int, total_reps: int) -> str:
    """Choose optimal search strategy based on scale."""
    if identity_count < 10 and total_reps < 100:
        return "brute_force"  # Small scale, avoid overhead
    elif total_reps < 5000:
        return "batch_vectorized"  # Medium scale, matrix multiply
    else:
        return "ann_index"  # Large scale, approximate search
```

**Methodology**:

1. Benchmark current brute-force on 100, 1000, 10000 identities
2. Implement `batch_similarity_matrix()` as drop-in replacement
3. Add `RepresentativeCache` for pre-normalization ✅ (done in Phase 4)
4. Benchmark improvement (expect 10-50x for batch vectorized)
5. Add monitoring hook when representative count exceeds threshold
6. ~~Add FAISS integration~~ — Deferred to post-MVP (premature optimization)

**Success Metrics**:

| Metric                             | Before | After                    |
| ---------------------------------- | ------ | ------------------------ |
| 1000 identities × 500 reps latency | ~2s    | <50ms (vectorized)       |
| Normalization calls per search     | n × m  | 0 (cached) ✅            |
| Memory for 10k reps                | Dicts  | Contiguous ndarray ✅    |
| Large-scale (100k reps) support    | No     | Post-MVP if metrics show |

---

### ✅ 32. Clustering Accuracy Improvements

**Current Accuracy Issues**:

1. **Transitive closure problem** — Graph algorithms can chain unrelated identities:

   - A matches B (0.85), B matches C (0.82), C matches D (0.78)
   - Result: A, B, C, D all in same cluster even though A-D similarity is 0.50

2. **Cold-start creates too many singletons** — `RepresentativeOnlyClustering` is conservative, creating suggestions instead of merging

3. **No online learning** — Thresholds are static, not learned from user feedback

4. **Missing complete-link verification** — Only best representative checked, not worst-case

**Implementation**:

**A. Complete-Link Verification (#32)**

Location: `recognition/application/discovery/graph/verification.py`

```python
# recognition/application/discovery/graph/verification.py
"""Complete-link verification for graph expansion stage."""

import numpy as np
from collections.abc import Sequence

from recognition.shared.similarity import normalize_face_embedding


def verify_complete_link(
    candidate_embedding: np.ndarray,
    cluster_member_embeddings: Sequence[np.ndarray],
    *,
    min_similarity: float,
    min_coverage: float = 1.0,  # 1.0 = must pass for ALL members (complete-link)
) -> tuple[bool, float, float]:
    """Verify candidate has sufficient similarity to ALL cluster members.

    This prevents transitive chaining where:
    A→B (0.85), B→C (0.82), C→D (0.78) chains A-D even though A-D = 0.50

    Args:
        candidate_embedding: The identity we want to add
        cluster_member_embeddings: All current members of target cluster
        min_similarity: Minimum required similarity to each member
        min_coverage: Fraction of members that must pass (1.0 = all)

    Returns:
        (passed, min_sim, coverage_ratio)
    """
    if not cluster_member_embeddings:
        return True, 1.0, 1.0

    candidate_vec = normalize_face_embedding(
        np.asarray(candidate_embedding, dtype=np.float32)
    )

    similarities: list[float] = []
    for member_emb in cluster_member_embeddings:
        member_vec = normalize_face_embedding(
            np.asarray(member_emb, dtype=np.float32)
        )
        sim = float(np.dot(candidate_vec, member_vec))
        similarities.append(sim)

    min_sim = min(similarities)
    passing = sum(1 for s in similarities if s >= min_similarity)
    coverage = passing / len(similarities)

    # Pass if coverage met AND minimum similarity is within 90% of threshold
    passed = coverage >= min_coverage and min_sim >= (min_similarity * 0.9)

    return passed, min_sim, coverage


def batch_verify_complete_link(
    candidate_embeddings: Sequence[np.ndarray],
    cluster_member_embeddings: Sequence[np.ndarray],
    *,
    min_similarity: float,
) -> np.ndarray:
    """Batch verification returning boolean mask.

    Returns:
        Boolean array of shape (n_candidates,) indicating pass/fail.
    """
    if not cluster_member_embeddings:
        return np.ones(len(candidate_embeddings), dtype=bool)

    # Normalize all vectors
    candidates = np.stack([
        normalize_face_embedding(np.asarray(c, dtype=np.float32))
        for c in candidate_embeddings
    ])
    members = np.stack([
        normalize_face_embedding(np.asarray(m, dtype=np.float32))
        for m in cluster_member_embeddings
    ])

    # Compute all pairwise similarities: (n_candidates, n_members)
    sim_matrix = candidates @ members.T

    # Complete-link: minimum similarity to any member must exceed threshold
    min_sims = np.min(sim_matrix, axis=1)

    return min_sims >= min_similarity
```

**Threshold Values** (add to `ClusteringSettings`):

```python
# recognition/application/settings.py
class ClusteringSettings(BaseSettings):
    # Existing
    similarity_threshold: float = 0.72
    anchor_discovery_threshold: float = 0.68

    # New for complete-link
    complete_link_threshold: float = 0.65  # Slightly lower than similarity_threshold
    complete_link_min_coverage: float = 0.85  # 85% of members must pass
    complete_link_enabled: bool = True  # Feature flag
```

**Integration in GraphDiscovery expansion stage**:

```python
# In graph/discovery.py - after candidate generation
if self.settings.complete_link_enabled and candidate.cluster_id:
    cluster_members = await self._get_cluster_embeddings(candidate.cluster_id)

    passed, min_sim, coverage = verify_complete_link(
        candidate.identity.face_vector,
        cluster_members,
        min_similarity=self.settings.complete_link_threshold,
        min_coverage=self.settings.complete_link_min_coverage,
    )

    if not passed:
        logger.info(
            "[GraphDiscovery] Complete-link REJECTED identity=%s cluster=%s "
            "min_sim=%.3f coverage=%.2f",
            candidate.identity.id, candidate.cluster_id, min_sim, coverage,
        )
        # Demote to suggestion instead of auto-accept
        candidate.discovery_similarity = min_sim
        continue
```

**Unit Tests** (add 2-3 focused tests):

```python
# tests/unit/test_complete_link_verification.py
import numpy as np
import pytest
from recognition.application.discovery.graph.verification import verify_complete_link

def test_empty_cluster_always_passes():
    passed, min_sim, coverage = verify_complete_link(
        np.array([1.0, 0.0]), [], min_similarity=0.8
    )
    assert passed is True
    assert min_sim == 1.0

def test_must_link_all_members():
    candidate = np.array([1.0, 0.0])
    members = [
        np.array([0.9, 0.1]),  # Similar
        np.array([0.5, 0.5]),  # Less similar
    ]
    passed, min_sim, _ = verify_complete_link(
        candidate, members, min_similarity=0.8
    )
    assert passed is False  # Second member fails

def test_cannot_link_blocked_pairs():
    candidate = np.array([1.0, 0.0])
    members = [np.array([0.95, 0.05])]  # Very similar
    passed, min_sim, _ = verify_complete_link(
        candidate, members, min_similarity=0.7
    )
    assert passed is True
```

---

**B. Adaptive Threshold from User Feedback (#32b)**

**Data Model for Feedback History**:

```python
# db/models.py - new table
class ClusteringFeedback(Base):
    """User feedback on clustering decisions for adaptive learning."""
    __tablename__ = "clustering_feedback"

    id = Column(UUID, primary_key=True)
    tenant_id = Column(UUID, ForeignKey("tenants.id"), nullable=False)
    identity_id = Column(UUID, nullable=False)
    cluster_id = Column(UUID, nullable=False)
    decision_type = Column(String)  # "accept", "suggest", "reject"
    similarity_at_decision = Column(Float)
    user_action = Column(String)  # "confirmed", "rejected", "moved", "split"
    created_at = Column(DateTime)

    # A/B test tracking
    experiment_id = Column(String, nullable=True)  # e.g., "threshold_v2"
    variant = Column(String, nullable=True)  # e.g., "control", "treatment_a"
```

**Adaptive Threshold Service**:

```python
# recognition/application/settings/adaptive.py
from dataclasses import dataclass
import numpy as np

@dataclass
class AdaptiveThresholdResult:
    threshold: float
    source: str  # "default", "tenant_learned", "experiment"
    confidence: float  # How confident we are in this threshold
    sample_size: int


class AdaptiveThresholdService:
    """Learn optimal thresholds from user feedback."""

    MINIMUM_SAMPLES = 50  # Require 50+ feedback events before learning

    def __init__(self, session: AsyncSession, default_threshold: float = 0.72):
        self._session = session
        self._default = default_threshold

    async def get_threshold(
        self,
        tenant_id: str,
        experiment_id: str | None = None,
    ) -> AdaptiveThresholdResult:
        """Get optimal threshold for tenant, possibly in an experiment."""

        # Check if tenant is in an active experiment
        if experiment_id:
            variant = await self._get_experiment_variant(tenant_id, experiment_id)
            if variant:
                return AdaptiveThresholdResult(
                    threshold=variant.threshold,
                    source=f"experiment:{experiment_id}:{variant.name}",
                    confidence=1.0,
                    sample_size=0,
                )

        # Try to learn from tenant's feedback history
        learned = await self._learn_from_feedback(tenant_id)
        if learned and learned.sample_size >= self.MINIMUM_SAMPLES:
            return learned

        return AdaptiveThresholdResult(
            threshold=self._default,
            source="default",
            confidence=0.5,
            sample_size=0,
        )

    async def _learn_from_feedback(self, tenant_id: str) -> AdaptiveThresholdResult | None:
        """Learn threshold from confirmed/rejected decisions."""

        # Query feedback where user confirmed suggestions
        confirmed = await self._session.execute(
            select(ClusteringFeedback.similarity_at_decision)
            .where(ClusteringFeedback.tenant_id == uuid.UUID(tenant_id))
            .where(ClusteringFeedback.user_action == "confirmed")
            .where(ClusteringFeedback.decision_type == "suggest")
        )
        confirmed_sims = [row[0] for row in confirmed.all()]

        # Query feedback where user rejected/moved
        rejected = await self._session.execute(
            select(ClusteringFeedback.similarity_at_decision)
            .where(ClusteringFeedback.tenant_id == uuid.UUID(tenant_id))
            .where(ClusteringFeedback.user_action.in_(["rejected", "moved", "split"]))
        )
        rejected_sims = [row[0] for row in rejected.all()]

        if len(confirmed_sims) < 20 or len(rejected_sims) < 10:
            return None

        # Find threshold that maximizes separation
        min_confirmed = min(confirmed_sims)
        max_rejected = max(rejected_sims)

        if min_confirmed > max_rejected:
            # Clean separation exists
            optimal = (min_confirmed + max_rejected) / 2
            confidence = (min_confirmed - max_rejected) / 0.3
        else:
            # Overlap exists, use conservative approach
            optimal = np.percentile(confirmed_sims, 10)
            confidence = 0.6

        return AdaptiveThresholdResult(
            threshold=float(np.clip(optimal, 0.60, 0.85)),  # Safety bounds
            source="tenant_learned",
            confidence=min(confidence, 1.0),
            sample_size=len(confirmed_sims) + len(rejected_sims),
        )
```

---

**C. A/B Testing Configuration**

```python
# recognition/application/settings/experiments.py
from dataclasses import dataclass
from datetime import datetime

@dataclass
class ExperimentVariant:
    name: str
    threshold: float
    weight: float  # Traffic allocation (0.0-1.0)

@dataclass
class Experiment:
    id: str
    variants: list[ExperimentVariant]
    start_date: datetime
    end_date: datetime | None

ACTIVE_EXPERIMENTS: dict[str, Experiment] = {
    "threshold_v2_jan2026": Experiment(
        id="threshold_v2_jan2026",
        variants=[
            ExperimentVariant("control", threshold=0.72, weight=0.5),
            ExperimentVariant("aggressive", threshold=0.68, weight=0.25),
            ExperimentVariant("conservative", threshold=0.78, weight=0.25),
        ],
        start_date=datetime(2026, 1, 15),
        end_date=datetime(2026, 2, 15),
    ),
}
```

---

**D. UI Indicator for Development**

During development, show which algorithm/threshold is being used:

```tsx
// js/admin/components/ExperimentBadge.tsx
interface ExperimentBadgeProps {
  source: string; // From AdaptiveThresholdResult.source
  threshold: number;
  showInDev?: boolean;
}

export function ExperimentBadge({
  source,
  threshold,
  showInDev = true,
}: ExperimentBadgeProps) {
  // Only show in development or when explicitly enabled
  if (!showInDev && process.env.NODE_ENV === "production") {
    return null;
  }

  const getBadgeStyle = () => {
    if (source.startsWith("experiment:")) {
      const variant = source.split(":")[2];
      return (
        {
          control: "bg-gray-100 text-gray-700",
          aggressive: "bg-orange-100 text-orange-700",
          conservative: "bg-blue-100 text-blue-700",
        }[variant] || "bg-purple-100 text-purple-700"
      );
    }
    if (source === "tenant_learned") return "bg-green-100 text-green-700";
    return "bg-gray-50 text-gray-500";
  };

  const getLabel = () => {
    if (source.startsWith("experiment:")) {
      const [, expId, variant] = source.split(":");
      return `🧪 ${variant} (${threshold.toFixed(2)})`;
    }
    if (source === "tenant_learned") {
      return `📊 Learned (${threshold.toFixed(2)})`;
    }
    return `Default (${threshold.toFixed(2)})`;
  };

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${getBadgeStyle()}`}
      title={`Threshold source: ${source}`}
    >
      {getLabel()}
    </span>
  );
}
```

**UI Integration in Cluster Views**:

```tsx
// In ClusterDetail.tsx header or SuggestionCard.tsx
function ClusterDetailHeader({ cluster, thresholdInfo }: Props) {
  return (
    <div className="flex items-center gap-2">
      <h2>{cluster.label}</h2>
      {/* Show experiment badge during development */}
      <ExperimentBadge
        source={thresholdInfo.source}
        threshold={thresholdInfo.threshold}
        showInDev={true}
      />
    </div>
  );
}
```

**API Response Enhancement**:

```python
# Include threshold metadata in clustering/suggestion responses
class ClusteringMetadata(BaseModel):
    threshold_used: float
    threshold_source: str  # "default" | "tenant_learned" | "experiment:..."
    algorithm: str

class SuggestionResponse(BaseModel):
    suggestion: Suggestion
    metadata: ClusteringMetadata  # For UI badge display
```

---

**E. #31 Integration: Batch Vectorized Search**

**Location Decision**: Wire into both `graph/` and `representative.py` via enhanced `SimilaritySearch`.

```python
# recognition/application/similarity/batch.py
"""Batch vectorized similarity search for high-throughput matching."""

import numpy as np
from recognition.shared.similarity import normalize_face_embedding


def batch_similarity_matrix(
    queries: np.ndarray,  # Shape: (n_queries, dim)
    representatives: np.ndarray,  # Shape: (n_reps, dim)
    *,
    normalize: bool = True,
) -> np.ndarray:
    """Compute similarity matrix between queries and representatives.

    Returns:
        Shape (n_queries, n_reps) with cosine similarities.
    """
    if queries.size == 0 or representatives.size == 0:
        return np.empty((len(queries), len(representatives)), dtype=np.float32)

    if normalize:
        queries = np.stack([normalize_face_embedding(q) for q in queries])
        representatives = np.stack([normalize_face_embedding(r) for r in representatives])

    # Single matrix multiply — O(n*m*d) but highly optimized
    return queries @ representatives.T
```

**Strategy Switch** (add to `SimilaritySearch`):

```python
# recognition/application/similarity/search.py - enhanced
class SimilaritySearch:
    """Find best matching clusters with automatic strategy selection."""

    BATCH_THRESHOLD = 10  # Use batch when >= 10 queries

    def find_best_matches(
        self,
        query_embeddings: list[np.ndarray],
        representatives_by_cluster: Mapping[str, Sequence[np.ndarray] | np.ndarray],
        *,
        min_similarity: float | None = None,
    ) -> list[MatchResult | None]:
        """Find best match for multiple queries, auto-selecting strategy."""

        threshold = min_similarity or self._settings.similarity_threshold

        if len(query_embeddings) < self.BATCH_THRESHOLD:
            # Brute force for small batches (avoid matrix setup overhead)
            return [
                self.find_best_match(q, representatives_by_cluster, min_similarity=threshold)
                for q in query_embeddings
            ]

        # Batch vectorized for larger sets
        return self._batch_search(query_embeddings, representatives_by_cluster, threshold)
```

**Integration Points**:

```python
# 1. graph/discovery.py - use for noise rescue
if noise_identities and anchor_embeddings:
    search = SimilaritySearch(self.settings)
    matches = search.find_best_matches(
        [identity.face_vector for identity, _ in noise_identities],
        anchor_embeddings,
        min_similarity=self.settings.anchor_discovery_threshold,
    )

# 2. representative.py - use for main discovery
search = SimilaritySearch(self.settings)
matches = search.find_best_matches(
    [identity.face_vector for identity in identities],
    representatives_by_cluster,
    min_similarity=self.settings.similarity_threshold,
)
```

---

**F. Two-Stage Clustering**

```python
# recognition/application/clustering/two_stage.py
"""
Two-stage clustering for better accuracy:

Stage 1 - High Confidence Core:
  - Use very high threshold (0.90+)
  - Creates small, pure clusters
  - These become "anchor" clusters

Stage 2 - Expansion with Verification:
  - Use lower threshold (0.75) for candidates
  - Verify each candidate against ALL members of target cluster
  - Reject if any pairwise similarity < complete_link_floor
"""

async def two_stage_cluster(
    identities: list[MediaIdentity],
    high_threshold: float = 0.90,
    expansion_threshold: float = 0.75,
    complete_link_floor: float = 0.65,
) -> list[IdentityCluster]:
    # Stage 1: Create core clusters at high threshold
    core_clusters = await representative_only_cluster(
        identities,
        threshold=high_threshold,
        create_suggestions=False,  # No suggestions, only confident matches
    )

    # Stage 2: Try to expand each unassigned identity
    unassigned = [i for i in identities if not i.cluster_id]

    for identity in unassigned:
        for cluster in core_clusters:
            # Check if identity matches representative
            rep_sim = best_representative_similarity(identity, cluster)
            if rep_sim < expansion_threshold:
                continue

            # Verify complete-link to ALL members
            passes, min_sim = verify_complete_link(
                identity.embedding,
                [m.embedding for m in cluster.members],
                complete_link_floor,
            )

            if passes:
                await add_to_cluster(cluster.id, identity)
                break
        else:
            # No cluster match - create singleton
            await create_singleton(identity)

    return core_clusters
```

**Methodology**:

1. Log all suggestion confirmations/rejections with similarity scores
2. Analyze false positive rate at current threshold
3. Implement complete-link verification for expansion stage
4. Implement adaptive threshold based on feedback history
5. A/B test two-stage vs current approach

**Success Metrics**:

| Metric                              | Before   | After                      |
| ----------------------------------- | -------- | -------------------------- |
| False positive rate (wrong cluster) | ~5%      | <1%                        |
| Singleton clusters created          | High     | Reduced 30%                |
| Transitive false merges             | Possible | Prevented by complete-link |
| Threshold tuning                    | Manual   | Adaptive from feedback     |

---

## 🔵 Suggestion Service Issues

Audit of `recognition/application/suggestions/service.py` (758 lines).

---

### ✅ 33. `SuggestionService` is 758 Lines with 16 Methods and 9 Constructor Dependencies

**File**: `recognition/application/suggestions/service.py`

**Problem**: Single class handles too many responsibilities:

| Method                              | Lines    | Responsibility                                     |
| ----------------------------------- | -------- | -------------------------------------------------- |
| `__init__`                          | L37-64   | 9 constructor parameters                           |
| `create`                            | L141-166 | Create suggestion from candidate                   |
| `update_scores`                     | L168-189 | Update similarity scores                           |
| `refresh_for_identity`              | L191-316 | **127 lines** — recompute suggestions for identity |
| `refresh_for_cluster`               | L318-444 | **126 lines** — refresh scores for cluster         |
| `surface_for_newly_labeled_cluster` | L446-577 | **131 lines** — scan unlabeled clusters            |
| `resolve_for_identity_exclusive`    | L579-643 | Accept one, reject others                          |
| `accept`                            | L653-676 | Accept single suggestion                           |
| `reject`                            | L678-721 | Reject + create constraints                        |
| `list_pending`                      | L723-725 | Simple delegate                                    |
| `resolve_for_identity`              | L727-756 | Resolve by cluster                                 |

**Constructor Dependencies** (9 total):

```python
def __init__(
    self,
    repository: SuggestionRepository,           # 1
    tenant_id: str,                              # 2
    cluster_repository: ClusterRepository,      # 3
    session: AsyncSession,                       # 4
    run_context: RecognitionRunContext,          # 5
    settings: ClusteringSettings,                # 6
    block_repository: IdentityClusterBlockRepository,  # 7
    constraint_repository: IdentityConstraintRepository,  # 8
    # Implicit: _member_repo via getattr hack    # 9
):
```

**Impact**:

- Class violates Single Responsibility Principle
- 3 methods over 120 lines each
- Constructor takes 9 dependencies (God object smell)
- Hard to test individual refresh logic
- Private member access: `getattr(self._cluster_repository, "_member_repo", None)` (same as #22)

---

### 34. SuggestionService Duplicates Similarity Search Logic (3rd Copy)

**File**: `recognition/application/suggestions/service.py`  
**Lines**: 272-278, 371-377, 532-538

**Problem**: Same similarity search loop appears THREE times in this file:

```python
# Pattern repeated at L272-278, L371-377, L532-538
best_similarity = 0.0
for rep in reps:
    rep_vec = np.asarray(getattr(rep, "embedding", rep), dtype=np.float32)
    similarity = compute_face_similarity(identity_embedding, rep_vec)
    best_similarity = max(best_similarity, similarity)
```

This is the THIRD location (after discovery and clustering) implementing the same pattern.

**Total duplicate similarity loops across codebase**:

| Module        | File                                         | Pattern Count |
| ------------- | -------------------------------------------- | ------------- |
| Discovery     | `representative.py` L120-134                 | 1             |
| Discovery     | `centroid.py` L75-84                         | 1             |
| Discovery     | `graph.py` L460-470                          | 2             |
| Clustering    | `representative_only_clustering.py` L143-149 | 1             |
| Suggestions   | `service.py` L272-278, L371-377, L532-538    | 3             |
| Orchestration | `cluster_merge.py` L112-113                  | 1             |
| **Total**     |                                              | **9**         |

**Impact**:

- 9 implementations of essentially identical code
- Bug fixes must be applied to all locations
- Performance optimizations (vectorization) blocked by scatter

---

### 35. SuggestionService Mixes Persistence, Similarity, and Orchestration

**File**: `recognition/application/suggestions/service.py`

**Problem**: Service conflates three distinct concerns:

| Concern               | Examples                                                                                 | Should Be                             |
| --------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------- |
| **Persistence**       | `create()`, `update_scores()`, `accept()`, `reject()`                                    | Keep in SuggestionService             |
| **Similarity Search** | L272-278, L371-377, L532-538                                                             | Extract to `SimilaritySearch`         |
| **Orchestration**     | `refresh_for_identity()`, `refresh_for_cluster()`, `surface_for_newly_labeled_cluster()` | Extract to `SuggestionRefreshService` |

**Root Cause**: Methods like `refresh_for_identity()` grew to include:

1. Identity embedding lookup
2. Cluster enumeration
3. Block/constraint checking
4. Similarity computation
5. Threshold decisions
6. Suggestion upsert
7. Logging

**Implementation**:

**Option A — Extract Refresh Orchestration**

```python
# recognition/application/suggestions/refresh.py
class SuggestionRefreshService:
    """Orchestrate suggestion refresh operations."""

    def __init__(
        self,
        suggestion_service: SuggestionService,  # Thin persistence layer
        similarity_search: SimilaritySearch,     # Shared search (Issue #29)
        cluster_repository: ClusterRepository,
        block_repository: IdentityClusterBlockRepository,
        constraint_repository: IdentityConstraintRepository,
        settings: ClusteringSettings,
    ) -> None:
        self._suggestions = suggestion_service
        self._search = similarity_search
        self._clusters = cluster_repository
        self._blocks = block_repository
        self._constraints = constraint_repository
        self._settings = settings

    async def refresh_for_identity(
        self,
        tenant_id: str,
        identity_id: str,
        reason: SuggestionRefreshReason,
    ) -> list[AssignmentSuggestion]:
        """Recompute suggestions for a single identity."""
        identity_embedding = await self._load_identity_embedding(identity_id)
        clusters = await self._clusters.get_labeled_with_representatives(tenant_id)

        suggestions = []
        for cluster, reps in clusters:
            if not self._is_eligible(cluster, identity_id):
                continue

            # Use shared similarity search
            match = self._search.find_best_representative_match(
                identity_embedding,
                {cluster.id: reps},
            )

            if self._settings.suggestion_floor <= match.similarity < self._settings.suggestion_ceiling:
                suggestion = await self._suggestions.upsert(
                    tenant_id, identity_id, cluster.id, match.similarity
                )
                suggestions.append(suggestion)

        return suggestions
```

**Option B — Thin SuggestionService + Query/Command Separation**

```python
# recognition/application/suggestions/
  service.py              # Thin: create, accept, reject, list (CRUD only)
  refresh.py              # Orchestration: refresh_for_identity, refresh_for_cluster
  queries.py              # Read operations: list_pending, get_by_cluster
  surface.py              # surface_for_newly_labeled_cluster (complex scan)
```

**Methodology**:

1. Extract similarity search to shared module (ties to Issue #29)
2. Extract refresh orchestration to `SuggestionRefreshService`
3. Keep `SuggestionService` as thin persistence facade
4. Reduce constructor dependencies from 9 to ~4

**Success Metrics**:

| Metric                                       | Before | After      |
| -------------------------------------------- | ------ | ---------- |
| `SuggestionService` lines                    | 758    | ~200       |
| Constructor dependencies                     | 9      | 4          |
| Methods over 100 lines                       | 3      | 0          |
| Duplicate similarity loops in this file      | 3      | 0          |
| Total duplicate similarity loops in codebase | 9      | 1 (shared) |

---

### 36. Private Member Access via `getattr` Hack

**File**: `recognition/application/suggestions/service.py`  
**Lines**: 248, 495

**Problem**: Service accesses cluster repository internals via `getattr`:

```python
# L248, L495
member_repo = getattr(self._cluster_repository, "_member_repo", None)
if member_repo is not None:
    members = await member_repo.get_by_cluster(cluster_id)
```

**Impact**:

- Same issue as #22 (private member access)
- `ClusterRepository` doesn't expose member access publicly
- Tight coupling to internal implementation
- Tests can't mock properly

**Root Cause**: `ClusterRepository` was designed for cluster-level operations but suggestions need member-level queries.

**Implementation**:

```python
# Option A: Add method to ClusterRepository
class ClusterRepository:
    async def get_members(self, cluster_id: str) -> list[ClusterMember]:
        """Public accessor for cluster members."""
        return await self._member_repo.get_by_cluster(cluster_id)

# Option B: Inject MemberRepository directly
class SuggestionService:
    def __init__(
        self,
        ...
        member_repository: MemberRepository,  # Direct dependency
    ):
        self._member_repo = member_repository
```

**Methodology**:

- Add public `get_members()` to `ClusterRepository`
- Replace `getattr` hacks with public method calls
- Update tests to use public interface

**Success Metrics**:

| Metric                                      | Before | After |
| ------------------------------------------- | ------ | ----- |
| `getattr(..., "_member_repo")` calls        | 2      | 0     |
| Private member access in suggestions        | Yes    | No    |
| Public member accessor on ClusterRepository | No     | Yes   |

---

## 🟢 Assignment Module — Architecture Validation

Audit of `recognition/application/assignment/` directory (627 total lines).

| File                   | Lines | Description              |
| ---------------------- | ----- | ------------------------ |
| `checks/confidence.py` | 162   | Adaptive threshold check |
| `gate.py`              | 115   | Check orchestration      |
| `quality.py`           | 93    | Identity quality scoring |
| `checks/constraint.py` | 52    | CANNOT_LINK enforcement  |
| `checks/base.py`       | 52    | ABC for checks           |
| `checks/block.py`      | 51    | User block enforcement   |
| `decision.py`          | 32    | Decision dataclass       |
| `candidate.py`         | 32    | Candidate dataclass      |

---

### Architecture Integration Assessment

**✅ CONFIRMED: Assignment module correctly integrates with clustering architecture**

The assignment module serves as the **validation layer** in the pipeline:

```
Discovery → AssignmentCandidate → AssignmentGate → AssignmentDecision → Persistence
    ↓              ↓                    ↓                  ↓
  (Issue #29)   (shared type)     (orchestrates      (ACCEPT/SUGGEST/REJECT)
                                   checks)
```

**Data Flow Verification**:

| Producer                             | Consumer                     | Shared Type                          |
| ------------------------------------ | ---------------------------- | ------------------------------------ |
| `RepresentativeDiscovery.discover()` | `AssignmentGate.evaluate()`  | `AssignmentCandidate`                |
| `CentroidDiscovery.discover()`       | `AssignmentGate.evaluate()`  | `AssignmentCandidate`                |
| `GraphDiscovery.discover()`          | `AssignmentGate.evaluate()`  | `AssignmentCandidate`                |
| `AssignmentGate.evaluate()`          | `incremental_clustering.py`  | `AssignmentDecision`                 |
| `AssignmentGate.evaluate()`          | `SuggestionService.create()` | `AssignmentCandidate` (via decision) |

**Integration Points Found**:

1. **Orchestration** (`incremental_clustering.py` L27-30, L75, L577-578):

   ```python
   from recognition.application.assignment import (
       AssignmentCandidate,
       AssignmentGate,
   )
   ```

2. **ClusterService** (`cluster_service.py` L22):

   ```python
   from recognition.application.assignment import AssignmentGate
   ```

3. **SuggestionService** (`service.py` L17):

   ```python
   from recognition.application.assignment import AssignmentCandidate
   ```

4. **All Discovery Algorithms** produce `AssignmentCandidate`:
   - `representative.py` L12, L74
   - `centroid.py` L11, L52
   - `graph.py` L17, L227, L271

---

### 37. Assignment Module is Well-Structured (No Major Issues)

**Assessment**: The assignment module is the **best-architected** module in the codebase:

| Quality               | Rating       | Evidence                              |
| --------------------- | ------------ | ------------------------------------- |
| Single Responsibility | ✅ Excellent | Each check handles one concern        |
| Open/Closed           | ✅ Excellent | New checks via `AssignmentCheck` ABC  |
| Interface Segregation | ✅ Good      | `CheckResult` is minimal              |
| Dependency Inversion  | ✅ Good      | Checks depend on repository protocols |
| File Size             | ✅ Excellent | Largest file is 162 lines             |
| Testability           | ✅ Excellent | Each check is independently testable  |

**Why It Works**:

1. **Strategy Pattern** — `AssignmentCheck` ABC with concrete implementations
2. **Chain of Responsibility** — `AssignmentGate` runs checks in order, stops on fatal
3. **Value Objects** — `AssignmentCandidate`, `CheckResult`, `AssignmentDecision` are immutable dataclasses
4. **Separation of Concerns**:
   - `candidate.py` — What to evaluate
   - `decision.py` — Result of evaluation
   - `gate.py` — Orchestration
   - `checks/*` — Individual validation rules
   - `quality.py` — Score computation (pure function)

**Minor Improvements** (Low Priority):

1. `ConfidenceCheck.evaluate()` at 80 lines could extract threshold computation
2. `quality.py` uses module-level `_default_settings` instead of DI

---

### 38. Opportunity: Use Assignment Gate in SuggestionService

**Files**:

- `recognition/application/suggestions/service.py` L272-298
- `recognition/application/assignment/gate.py`

**Problem**: `SuggestionService.refresh_for_identity()` duplicates gate logic:

```python
# service.py L272-298 (inside refresh_for_identity)
if self._block_repository is not None and await self._block_repository.is_blocked(...):
    continue

if self._constraint_repository is not None:
    violates = await self._constraint_repository.has_cannot_link(...)
    if violates:
        continue

if best_similarity < self._settings.suggestion_floor:
    continue
if best_similarity >= self._settings.suggestion_ceiling:
    continue
```

This is **manual re-implementation** of what `AssignmentGate` already does with:

- `BlockCheck`
- `ConstraintCheck`
- `ConfidenceCheck`

**Impact**:

- Duplicate validation logic
- Bug fixes to gate don't propagate to suggestion refresh
- Harder to add new checks (must update both places)

**Implementation**:

```python
# recognition/application/suggestions/refresh.py
class SuggestionRefreshService:
    def __init__(
        self,
        gate: AssignmentGate,  # Reuse existing gate
        suggestion_service: SuggestionService,
        cluster_repository: ClusterRepository,
        settings: ClusteringSettings,
    ) -> None:
        self._gate = gate
        self._suggestions = suggestion_service
        self._clusters = cluster_repository
        self._settings = settings

    async def refresh_for_identity(
        self,
        tenant_id: str,
        identity_id: str,
        reason: SuggestionRefreshReason,
    ) -> list[AssignmentSuggestion]:
        """Recompute suggestions using the assignment gate."""
        identity = await self._load_identity(identity_id)
        clusters = await self._clusters.get_labeled_with_representatives(tenant_id)

        suggestions = []
        for cluster, reps in clusters:
            # Build candidate (same as discovery does)
            candidate = AssignmentCandidate(
                identity=identity,
                identity_vector=identity.face_vector,
                cluster_id=cluster.id,
                discovery_method=DiscoveryMethod.REPRESENTATIVE,
                discovery_similarity=self._compute_best_similarity(identity, reps),
            )

            # Use gate for all validation
            decision = await self._gate.evaluate(candidate)

            if decision.outcome == AssignmentOutcome.SUGGEST:
                suggestion = await self._suggestions.upsert(
                    tenant_id, identity_id, cluster.id,
                    candidate.discovery_similarity
                )
                suggestions.append(suggestion)

        return suggestions
```

**Methodology**:

1. Inject `AssignmentGate` into refresh logic
2. Build `AssignmentCandidate` for each cluster
3. Use gate's `evaluate()` instead of manual checks
4. Handle `SUGGEST` outcome to create suggestions

**Success Metrics**:

| Metric                            | Before   | After         |
| --------------------------------- | -------- | ------------- |
| Duplicate validation logic        | 2 places | 1 (gate only) |
| Lines in `refresh_for_identity()` | 127      | ~50           |
| Check coverage consistency        | Manual   | Automatic     |
| New check propagation             | Manual   | Automatic     |

---

### 39. GraphDiscovery Has Deep Nesting in `discover()` Method

**File**: `recognition/application/discovery/graph/discovery.py`  
**Lines**: 73-221 (148 lines)

**Problem**: The `discover()` method has 4-5 levels of nested conditionals:

```python
for _label, items in grouped.items():                    # Level 1
    group_anchors = [...]
    if not new_members_with_vecs:                        # Level 2
        continue
    if group_anchors:                                    # Level 2
        target_cluster_id = resolve_anchor_conflict(...)
        ...
    else:
        if not inject_anchors and anchor_embeddings:     # Level 3
            target_cluster_id, similarity = ...
    if target_cluster_id and similarity >= threshold:    # Level 2
        for member, member_vec in new_members_with_vecs: # Level 3
            candidates.append(...)
    else:
        ...

if noise_identities and anchor_embeddings:               # Level 1
    for identity, face_vec in noise_identities:          # Level 2
        best_cluster, best_sim = ...
        if best_cluster and best_sim >= threshold:       # Level 3
            candidates.append(...)
        else:
            new_clusters.append(...)
elif noise_identities:                                   # Level 1
    for identity, _ in noise_identities:                 # Level 2
        new_clusters.append(...)
```

**Impact**:

- Cognitive complexity ~18 (recommended max: 10)
- Hard to test individual branches
- Logic interleaved with data transformation

**Implementation — Refactor with Early Returns and Extracted Helpers**:

```python
# graph/discovery.py — refactored approach

async def discover(self, identities, anchor_embeddings, inject_anchors=True) -> GraphDiscoveryResult:
    """Generate candidates and new-cluster groups via graph algorithms."""
    if not identities:
        return GraphDiscoveryResult([], [])

    # Phase 1: Prepare inputs
    anchors, anchor_vecs = self._build_anchor_set(anchor_embeddings, inject_anchors)
    combined_identities, combined_vectors = self._combine_inputs(identities, anchors, anchor_vecs)

    # Phase 2: Run clustering
    algorithm = select_algorithm(algorithm=self.algorithm, settings=self.settings)
    labels = algorithm.cluster(combined_vectors, cast(list[MediaIdentity], combined_identities))

    # Phase 3: Process grouped results
    grouped = group_by_label(combined_identities, combined_vectors, labels)
    candidates, new_clusters = self._process_groups(grouped, anchor_embeddings, inject_anchors)

    # Phase 4: Handle noise points
    noise = self._extract_noise(combined_identities, combined_vectors, labels)
    noise_candidates, noise_clusters = self._process_noise(noise, anchor_embeddings)
    candidates.extend(noise_candidates)
    new_clusters.extend(noise_clusters)

    self._log_results(algorithm, labels, candidates, new_clusters, identities, anchors)
    return GraphDiscoveryResult(candidates, new_clusters)


def _process_groups(
    self,
    grouped: dict[int, list[tuple[MediaIdentity | AnchorIdentity, np.ndarray]]],
    anchor_embeddings: dict[str, list[np.ndarray]],
    inject_anchors: bool,
) -> tuple[list[AssignmentCandidate], list[tuple[list[MediaIdentity], list[float]]]]:
    """Process clustered groups into candidates or new clusters."""
    candidates: list[AssignmentCandidate] = []
    new_clusters: list[tuple[list[MediaIdentity], list[float]]] = []

    for _label, items in grouped.items():
        result = self._process_single_group(items, anchor_embeddings, inject_anchors)
        if result is None:
            continue
        group_candidates, group_new_cluster = result
        candidates.extend(group_candidates)
        if group_new_cluster:
            new_clusters.append(group_new_cluster)

    return candidates, new_clusters


def _process_single_group(
    self,
    items: list[tuple[MediaIdentity | AnchorIdentity, np.ndarray]],
    anchor_embeddings: dict[str, list[np.ndarray]],
    inject_anchors: bool,
) -> tuple[list[AssignmentCandidate], tuple[list[MediaIdentity], list[float]] | None] | None:
    """Process a single cluster group. Returns None if empty."""
    group_anchors = [item for item, _ in items if isinstance(item, AnchorIdentity)]
    members_with_vecs = [(item, vec) for item, vec in items if isinstance(item, MediaIdentity)]

    if not members_with_vecs:
        return None

    target, similarity = self._resolve_target_cluster(
        group_anchors, members_with_vecs, items, anchor_embeddings, inject_anchors
    )

    threshold = (
        self.settings.anchor_discovery_threshold if group_anchors
        else self.settings.similarity_threshold
    )

    if target and similarity >= threshold:
        candidates = [
            self._build_candidate(member, vec, target, similarity, bool(group_anchors))
            for member, vec in members_with_vecs
        ]
        return candidates, None

    # No match — propose new cluster
    members = [m for m, _ in members_with_vecs]
    member_vecs = [v for _, v in members_with_vecs]
    similarities = compute_member_similarities(member_vecs)
    return [], (members, similarities)


def _process_noise(
    self,
    noise: list[tuple[MediaIdentity, np.ndarray]],
    anchor_embeddings: dict[str, list[np.ndarray]],
) -> tuple[list[AssignmentCandidate], list[tuple[list[MediaIdentity], list[float]]]]:
    """Process noise points — try anchor match or create singletons."""
    if not noise:
        return [], []

    candidates: list[AssignmentCandidate] = []
    new_clusters: list[tuple[list[MediaIdentity], list[float]]] = []

    for identity, face_vec in noise:
        if anchor_embeddings:
            best_cluster, best_sim = match_single_to_anchors(face_vec, anchor_embeddings)
            if best_cluster and best_sim >= self.settings.anchor_discovery_threshold:
                candidates.append(self._build_candidate(
                    identity, face_vec, best_cluster, best_sim, anchor_linked=True
                ))
                continue

        # No anchor match — singleton
        new_clusters.append(([identity], [1.0]))

    return candidates, new_clusters
```

**Key Refactoring Techniques**:

1. **Extract Phase Methods** — `_build_anchor_set()`, `_combine_inputs()`, `_process_groups()`, `_process_noise()`
2. **Early Continue** — Skip empty groups immediately
3. **Single-Responsibility Helpers** — `_resolve_target_cluster()`, `_build_candidate()`
4. **Flatten Noise Handling** — Unified path with early continue for matched noise

**Methodology**:

1. Extract pure helpers first (no behavior change)
2. Add unit tests for each helper
3. Refactor main method to use helpers
4. Verify integration tests pass

**Success Metrics**:

| Metric                  | Before | After |
| ----------------------- | ------ | ----- |
| Max nesting depth       | 5      | 2     |
| Cognitive complexity    | ~18    | ~8    |
| `discover()` lines      | 148    | ~40   |
| Testable helper methods | 0      | 5     |
| Branches in main method | 8+     | 3     |

---

## Architecture Summary

### Module Relationships (Validated)

```
┌─────────────────────────────────────────────────────────────────┐
│                        ORCHESTRATION LAYER                       │
│  (incremental_clustering.py, cluster_service.py, cluster_*.py) │
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│    DISCOVERY    │  │   ASSIGNMENT    │  │   SUGGESTIONS   │
│ (representative,│  │  (gate, checks) │  │   (service)     │
│  centroid,      │  │                 │  │                 │
│  graph)         │  │                 │  │                 │
└─────────────────┘  └─────────────────┘  └─────────────────┘
         │                    ▲                    │
         │                    │                    │
         └────────────────────┼────────────────────┘
                              │
                    AssignmentCandidate
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         CLUSTERING LAYER                         │
│    (representative_only_clustering.py, hierarchical_*.py)       │
└─────────────────────────────────────────────────────────────────┘
```

### Redundancy Analysis

| Issue         | Modules Affected                   | Shared Pattern                   | Fix                           |
| ------------- | ---------------------------------- | -------------------------------- | ----------------------------- |
| #29, #34      | Discovery, Clustering, Suggestions | Similarity search loop           | Extract to `SimilaritySearch` |
| #22, #23, #36 | Orchestration, Suggestions         | Private member access, `getattr` | Add public accessors          |
| #38           | Suggestions, Assignment            | Validation logic                 | Reuse `AssignmentGate`        |

### Priority Order for Refactoring

1. **High Impact, Low Risk**: Issue #29 — Shared `SimilaritySearch` (eliminates 9 duplicates)
2. **High Impact, Medium Risk**: Issue #38 — Use `AssignmentGate` in suggestions
3. **Medium Impact, Low Risk**: Issue #22 — Public accessors on `AssignmentWriter`
4. **Medium Impact, Medium Risk**: Issues #25, #26, #30 — Module splits

---

## Consolidated Checklist

Organized by **logical execution order** (dependencies first).

### Phase 1: 🔴 Critical Fixes (Do First)

| Done | #   | Task                                               | File(s)                                | Risk |
| ---- | --- | -------------------------------------------------- | -------------------------------------- | ---- |
| [x]  | 0   | Fix infinite request loop on suggestions 500 error | `SuggestionReviewPanel.tsx`, `App.tsx` | Low  |
| [x]  | 1   | Fix stale closure in `useJobProgressStream.ts`     | `useJobProgressStream.ts`              | Low  |
| [x]  | 4   | Fix stale progress in done handler                 | `useJobProgressStream.ts`              | Low  |
| [x]  | 2   | Remove unused imports in `test_cancel_labels.py`   | `test_cancel_labels.py`                | Low  |
| [x]  | 3   | Refactor private member access in tests            | Various test files                     | Low  |

### Phase 2: 🔧 Foundation (Shared Utilities)

Establish helpers used by later phases.

| Done | #   | Task                                           | File(s)                | Risk |
| ---- | --- | ---------------------------------------------- | ---------------------- | ---- |
| [x]  | 18  | Create typed `get_rowcount()` helper           | `shared/db/helpers.py` | Low  |
| [x]  | 21  | Create typed helper for `CursorResult` casting | `shared/db/helpers.py` | Low  |
| [x]  | 20  | Centralize dialect-specific SQL handling       | `shared/db/dialect.py` | Low  |
| [x]  | 24  | Centralize tenant UUID coercion                | `shared/tenant.py`     | Low  |

### Phase 3: 🔒 Encapsulation (Public Accessors)

Fix private member access before refactoring modules.

| Done | #   | Task                                              | File(s)                  | Risk |
| ---- | --- | ------------------------------------------------- | ------------------------ | ---- |
| [x]  | 22  | Add public accessors to `AssignmentWriter`        | `assignment_writer.py`   | Low  |
| [x]  | 36  | Add public `get_members()` to `ClusterRepository` | `cluster_repository.py`  | Low  |
| [x]  | 23  | Create helper functions for `getattr` patterns    | `shared/`                | Low  |
| [x]  | 35  | Replace `getattr` hacks with public method calls  | `suggestions/service.py` | Low  |

### Phase 4: 🔄 Shared Services (High-Impact Deduplication)

| Done | #   | Task                                                    | Impact                      | Risk   |
| ---- | --- | ------------------------------------------------------- | --------------------------- | ------ |
| [x]  | 29  | Create shared `SimilaritySearch` service                | **Eliminates 9 duplicates** | Medium |
| [x]  | 31  | Add `RepresentativeCache` for pre-normalized embeddings | Performance                 | Medium |
| [x]  | 38  | Reuse `AssignmentGate` in suggestion refresh logic      | Consistency                 | Medium |

### Phase 5: 📦 Module Splits (Backend)

| Done | #   | Task                                                      | Lines → Target              | Risk   |
| ---- | --- | --------------------------------------------------------- | --------------------------- | ------ |
| [x]  | 16  | Split `incremental_clustering.py` into focused modules    | 432 → <150 each             | Medium |
| [x]  | 25  | Split `cluster_curation.py` into focused modules          | 265 → <100 each             | Medium |
| [x]  | 26  | Split `cluster_split.py` into focused modules             | 178 → <80 each              | Medium |
| [x]  | 30  | Split `graph.py` into focused modules                     | 482 → <150 each             | Medium |
| [x]  | 33  | Split `SuggestionService` — extract refresh orchestration | 758 → <300                  | Medium |
| [x]  | 34  | Reduce `SuggestionService` to thin persistence facade     | —                           | Medium |
| [x]  | 15  | Extract router business logic to service/task modules     | `analyze.py`, `clusters.py` | Medium |
| [x]  | 19  | Extract job handlers from `scan_worker.py`                | 170 → <80                   | Medium |

### Phase 6: 🧩 Clustering Layer Refactoring

| Done | #   | Task                                                             | File(s)                             | Risk |
| ---- | --- | ---------------------------------------------------------------- | ----------------------------------- | ---- |
| [x]  | 27  | Extract `_find_best_match()` from `RepresentativeOnlyClustering` | `representative_only_clustering.py` | Low  |
| [x]  | 28  | Extract constraint penalty logic to standalone function          | `constrained_hac.py`                | Low  |

### Phase 7: 🎨 Frontend Architecture

| Done | #   | Task                                                          | File(s)                                | Risk   |
| ---- | --- | ------------------------------------------------------------- | -------------------------------------- | ------ |
| [x]  | 8   | Add global QueryClient defaults (retry, refetchOnWindowFocus) | `App.tsx`                              | Low    |
| [x]  | 9   | Remove duplicate `JobProgress` definition from hook           | `useJobProgressStream.ts`, `types/`    | Low    |
| [x]  | 10  | Reconcile `shared-contracts` schemas with frontend types      | `packages/shared-contracts/`, frontend | Medium |
| [x]  | 11  | Document cluster type transformation boundary                 | Docs + code comments                   | Low    |
| [x]  | 12  | Normalize config values in `getConfig()`                      | `config.ts`                            | Low    |
| [x]  | 13  | Create `queryKeys` factory for consistent cache invalidation  | `queryKeys.ts`                         | Low    |
| [x]  | 14  | Extract job state machine from WorkbenchPage                  | `WorkbenchPage.tsx`                    | Medium |

### Phase 8: 🔬 Discovery Performance & Accuracy

| Done | #   | Task                                                    | File(s)                 | Risk   |
| ---- | --- | ------------------------------------------------------- | ----------------------- | ------ |
| [x]  | 31  | Implement batch vectorized similarity search            | `similarity/batch.py`   | Medium |
| [x]  | 32  | Add complete-link verification for expansion stage      | `graph/verification.py` | Medium |
| [x]  | 32b | Implement adaptive threshold from user feedback         | `settings/adaptive.py`  | High   |
| [x]  | 39  | Reduce GraphDiscovery nesting with early-return/extract | `graph/discovery.py`    | Low    |

### Phase 9: 🟢 Deferred / Low Priority

| Done | #   | Task                                                    | Notes          |
| ---- | --- | ------------------------------------------------------- | -------------- |
| [x]  | 5   | Create test utilities to reduce `as unknown as` mocking | Nice-to-have   |
| [x]  | 6   | Add leader election for multi-tab coordination          | Complex, defer |
| [x]  | 17  | Implement or remove TODO protocol methods               | Cleanup        |

---

## Quick Reference: Issue Cross-Cutting Dependencies

| Dependency                          | Blocks             |
| ----------------------------------- | ------------------ |
| #18 (rowcount helper)               | #15, #16, #19      |
| #22 (AssignmentWriter accessors)    | #23, #35           |
| #29 (SimilaritySearch)              | #27, #30, #34, #38 |
| #36 (ClusterRepository.get_members) | #33, #35           |
