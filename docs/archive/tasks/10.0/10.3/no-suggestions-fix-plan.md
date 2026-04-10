# Fix Scan-Complete Empty Suggestions: Truthful Failure States and Proxy Policy Extraction

## Problem Statement

After a completed scan, the workbench renders "No identities detected yet" and "No suggestions to review yet" even when identities exist on the backend. The root cause is that three PHP controllers silently convert proxy/projection failures into empty `200` success payloads, and the frontend has no mechanism to distinguish "genuinely empty" from "transport failure" or "projection not landed."

## Workflow Principles

- Failures must be visible: never return an empty success payload as a stand-in for a transport or projection failure.
- The proxy policy should be an explicit, composable service; not an inherited middle-man base class.
- Projection state must be consumable by any workbench surface, not only `SyncStatusIndicator`.
- Status strings must come from centralized enums, not scattered magic literals.

## Terminology

- **Projection**: the sovereign local copy of backend cluster/identity data in `wp_acx_clusters` and `wp_acx_identity_members`.
- **Proxy policy**: the timeout, retry, and circuit-breaker configuration that governs HTTP calls from the WordPress plugin to the recognition backend.
- **Empty success payload**: a `200` REST response with `{ clusters: [], suggestions: [], identities_by_media: {} }` that the UI cannot distinguish from "genuinely no data."
- **Circuit breaker**: a transient-based mechanism that stops proxying after N consecutive failures for a cooldown period.

## Current State Analysis

- `AbstractRecognitionProxyController` is a 311-line middle-man base class inherited by the workbench-critical proxy controllers (`ClustersController`, `SuggestionsController`, `MediaIdentitiesController`, `AnalysisJobsController`, `SyncStatusController`). `RecognitionController` is a composition root and does not extend it; `XmpEmbedController` is a standalone controller unrelated to the proxy chain. It owns config resolution, circuit breaking, tenant context, and request dispatch in one inheritance chain. Controllers cannot opt into different policies per endpoint.
- `ClustersController::list_top_unlabeled_clusters()` returns `{ clusters: [], singleton_count: 0 }` when local projection is unavailable; schedules a bootstrap sync but gives the UI no signal that data is missing due to failure.
- `SuggestionsController::get_pending_suggestions()` returns `{ suggestions: [], total: 0 }` on proxy unavailability.
- `MediaIdentitiesController::get_media_identities()` returns `{ identities_by_media: [] }` on proxy unavailability.
- `SyncStatusIndicator` (354 lines) is the only component that renders projection error state. It calls 3 API hooks, derives 15+ intermediate variables, and renders 5+ conditional panels inline.
- `jobStateMachineUtils.ts` (206 lines) mixes job filtering, phase derivation, and UI text generation in one module.
- `useJobProgressStream.ts` (202 lines) packs SSE connection, broadcast subscriber, online detection, and progress state into one hook body with 5 chained effects.
- `SuggestionReviewPanel`, `IdentityClusterList`, and `TopClustersSection` do not consume projection/sync failure state; they render identical empty-state copy for both "no data" and "backend unavailable."
- `ui_read` proxy policy uses a 2s timeout with circuit enabled; two consecutive failures open the circuit for 60s, during which all subsequent reads on that controller degrade to empty payloads.

## Proposed Solution

### Phase 1: PHP proxy policy extraction (Optional; tech-debt follow-up)

Extract `AbstractRecognitionProxyController` responsibilities into a composable `ProxyPolicyService`:

- Owns config resolution (URL, API key, tenant ID).
- Owns circuit-breaker state (record failures, check availability, reset).
- Owns request dispatch with policy-driven timeout/retry/backoff.
- Controllers compose `ProxyPolicyService` via constructor injection instead of inheriting.
- Controllers can specify per-endpoint policy overrides (e.g., `post_scan_read` with a longer timeout for the projection-critical window).

### Phase 2: PHP controller truthful responses

Stop returning empty success payloads when the real state is "unavailable":

- Add a response envelope field (`data_source: 'local_projection' | 'backend_proxy' | 'unavailable'`) to workbench-critical read endpoints.
- When proxy is unavailable or projection is missing, return `data_source: 'unavailable'` alongside the empty arrays so the frontend can distinguish failure from emptiness.
- Add a `projection_status` field to the top-unlabeled response: `'available' | 'bootstrapping' | 'unavailable'`.

### Phase 3: TypeScript state extraction (Optional; tech-debt follow-up)

Decompose the frontend state management so projection/sync failure is consumable by all workbench surfaces:

1. Split `jobStateMachineUtils.ts` into `jobSelectors.ts`, `pipelineDerivation.ts`, and `statusFormatters.ts`.
2. Extract `useSyncStatusPresentation()` from `SyncStatusIndicator`; a hook that owns API calls + derivation and exposes projection health as a typed object.
3. Decompose `useJobProgressStream` into `useSSEConnection()`, `useBroadcastSubscriber()`, and `useOnlineStatus()`.
4. Centralize `JobStatus` and `ProjectionSyncState` as `as const` enum objects with exhaustive helpers.

### Phase 4: Frontend empty-state truthfulness

Thread projection/sync failure into `SuggestionReviewPanel`, `IdentityClusterList`, and `TopClustersSection`:

- Consume the `data_source` envelope field from API responses.
- When `data_source === 'unavailable'`, render a distinct failure state (warning banner + retry action) instead of "No X yet."
- _(If Phase 3 is pursued)_ Consume the extracted `useSyncStatusPresentation()` hook to show projection status inline when relevant. Otherwise, read projection state directly from `useSyncStatus()` or the existing sync status query.

## Patterns to Follow

### ProxyPolicyService composition (PHP)

```php
final class ProxyPolicyService {
    public function resolve_policy(string $request_class): ProxyPolicy { /* ... */ }
    public function is_circuit_open(string $circuit_key): bool { /* ... */ }
    public function record_failure(string $circuit_key): void { /* ... */ }
    public function dispatch(string $method, string $path, ProxyPolicy $policy, array $body = [], array $query = []): WP_REST_Response|WP_Error { /* ... */ }
    public function get_tenant_id(): string { /* ... */ }
}

// Controller composition:
final class ClustersController extends WP_REST_Controller {
    public function __construct(
        private readonly ProxyPolicyService $proxy,
        private readonly ClustersRepository $clusters_repository,
        // ...
    ) {}
}
```

### Truthful response envelope (PHP)

```php
return new WP_REST_Response([
    'clusters'          => [],
    'singleton_count'   => 0,
    'data_source'       => 'unavailable',
    'projection_status' => 'bootstrapping',
], 200);
```

### Extracted presentation hook (TypeScript)

```tsx
interface SyncPresentation {
  syncHealth: SyncHealth;
  projectionState: ProjectionSyncState;
  isProjectionFailed: boolean;
  isProxyUnavailable: boolean;
  retryProjection: () => void;
  counts: { pending: number; failed: number; conflicts: number };
}

export function useSyncStatusPresentation(
  pipelinePhase?: PipelinePhase,
  projectionState?: ProjectionSyncState,
): SyncPresentation {
  /* ... */
}
```

### Data-source-aware empty state (TypeScript)

```tsx
if (dataSource === "unavailable") {
  return (
    <EmptyStateWarning
      message={__("Results are temporarily unavailable.", "alt-context")}
      onRetry={onRetryProjection}
    />
  );
}
if (items.length === 0) {
  return (
    <EmptyState message={__("No suggestions to review yet.", "alt-context")} />
  );
}
```

### Split jobStateMachineUtils (TypeScript)

```typescript
// jobSelectors.ts
export function getLatestJobByType(
  jobs: PersistedJob[],
  type: string,
): PersistedJob | null;
export function isScanRunning(params: ScanRunningParams): boolean;

// pipelineDerivation.ts
export function derivePipelinePhase(
  scanJob,
  clusterJob,
  scanStatus,
): PipelinePhase;
export function deriveLatestJobId(
  phase,
  scanJob,
  clusterJob,
  scanStatus,
): string | null;

// statusFormatters.ts
export function buildStatusText(params: StatusTextParams): string | undefined;
export function buildScanProgress(
  params: ScanProgressParams,
): JobProgress | null;
export function buildClusterProgress(phase, sseProgress): JobProgress | null;
```

## Functions to Change

| File                                                                     | Function / Target                              | Change                                                                                        |
| ------------------------------------------------------------------------ | ---------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `src/api/class-abstract-recognition-proxy-controller.php`                | `resolve_request_policy`                       | Extract into `ProxyPolicyService::resolve_policy()`. Remove from base class.                  |
| `src/api/class-abstract-recognition-proxy-controller.php`                | `proxy_request`                                | Extract into `ProxyPolicyService::dispatch()`. Remove from base class.                        |
| `src/api/class-abstract-recognition-proxy-controller.php`                | `record_proxy_failure`, `is_proxy_unavailable` | Move to `ProxyPolicyService`.                                                                 |
| `src/api/class-abstract-recognition-proxy-controller.php`                | entire class                                   | Delete after extraction; subclasses compose `ProxyPolicyService` instead.                     |
| `src/api/class-clusters-controller.php`                                  | `list_top_unlabeled_clusters`                  | Add `data_source` and `projection_status` to response envelope. Compose `ProxyPolicyService`. |
| `src/api/class-suggestions-controller.php`                               | `get_pending_suggestions`                      | Add `data_source` to response envelope. Stop silently returning empty on unavailability.      |
| `src/api/class-suggestions-controller.php`                               | `get_pending_merge_suggestions`                | Same as above.                                                                                |
| `src/api/class-suggestions-controller.php`                               | `empty_pending_suggestions_response`           | Add `data_source: 'unavailable'` to the payload.                                              |
| `src/api/class-media-identities-controller.php`                          | `get_media_identities`                         | Add `data_source` to response envelope.                                                       |
| `js/admin/hooks/jobStateMachineUtils.ts`                                 | all exports                                    | Split into `jobSelectors.ts`, `pipelineDerivation.ts`, `statusFormatters.ts`.                 |
| `js/admin/hooks/useJobProgressStream.ts`                                 | hook body                                      | Extract `useSSEConnection()`, `useBroadcastSubscriber()`, `useOnlineStatus()`.                |
| `js/admin/pages/workbench/SyncStatusIndicator.tsx`                       | component body + inline derivations            | Extract `useSyncStatusPresentation()` hook. Slim component to presentation-only.              |
| `js/admin/pages/workbench/identity-clusters/SuggestionReviewPanel.tsx`   | empty state branch                             | Check `data_source` from API response; render failure state when unavailable.                 |
| `js/admin/pages/workbench/identity-clusters/IdentityClusterList.tsx`     | `clusters.length === 0` branch                 | Check projection/sync state; render failure state when unavailable.                           |
| `js/admin/pages/workbench/identity-clusters/TopClustersSection.tsx`      | null-return branch                             | Check `data_source` / `projection_status`; render failure state when unavailable.             |
| `js/admin/api/recognition/types/cluster.ts` or new `types/dataSource.ts` | `TopUnlabeledClustersResponse`                 | Add `data_source` and `projection_status` fields.                                             |
| `js/admin/api/recognition/clusterApiQueries.ts`                          | `fetchTopUnlabeledClusters`                    | Preserve and expose `data_source` from response.                                              |

## Related Files

| File                                                                             | Note                                                                                                                                       |
| -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `src/api/class-analysis-jobs-controller.php`                                     | Inherits `AbstractRecognitionProxyController`; must switch to `ProxyPolicyService` composition.                                            |
| `src/api/class-sync-status-controller.php`                                       | Same; inherits base class.                                                                                                                 |
| `src/api/class-recognition-controller.php`                                       | Composition root; does not extend `AbstractRecognitionProxyController`. Routes to child controllers; no proxy extraction migration needed. |
| `src/sovereign/sync/class-snapshot-projector.php`                                | Projection logic; related context for understanding "projection unavailable" semantics.                                                    |
| `js/admin/hooks/useJobStateMachineEffects.ts`                                    | Tracks `projectionSyncState`; will consume split modules from Phase 3.                                                                     |
| `js/admin/hooks/useSyncStatus.ts`                                                | Thin query hook; consumed by the new `useSyncStatusPresentation()`.                                                                        |
| `js/admin/hooks/useJobCoordination.ts`                                           | 220-line hook with BroadcastChannel logic; related to `useJobProgressStream` decomposition.                                                |
| `js/admin/api/recognition/identityQueriesApi.ts`                                 | Frontend adapter for media-identity queries; affected by `data_source` envelope changes.                                                   |
| `js/admin/api/recognition/types/suggestion.ts`                                   | Suggestion response types; affected by `data_source` envelope changes.                                                                     |
| `js/admin/api/recognition/types/identity.ts`                                     | Identity response types; affected by `data_source` envelope changes.                                                                       |
| `docs/tasks/tech-debt/refactoring-evaluation.md`                                 | Proxy policy extraction rationale (tech-debt evaluation).                                                                                  |
| `docs/tasks/tech-debt/refactoring-typescript-evaluation.md`                      | TypeScript decomposition rationale (tech-debt evaluation).                                                                                 |
| `docs/tasks/tech-debt/refactoring-ui-evaluation.md`                              | Empty-state truthfulness guidance.                                                                                                         |
| `docs/tasks/10.0/10.3/scan-complete-no-suggestions-pipeline-audit-2026-03-25.md` | Root audit motivating this plan.                                                                                                           |

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID    | Owned Paths                                | Upstream Dependencies                            | Required Tests                                                                                          |
| ---------- | ------------------------------------------ | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| `wp-proxy` | `apps/prototype-wp-alt-context/src/api/**` | None                                             | `cd apps/prototype-wp-alt-context && vendor/bin/phpunit tests/Unit/ 2>&1 \| tee /tmp/phpunit_proxy.txt` |
| `frontend` | `apps/prototype-wp-alt-context/js/**`      | `wp-proxy` (contract: `data_source` field shape) | `cd apps/prototype-wp-alt-context && npx vitest run 2>&1 \| tee /tmp/vitest_frontend.txt`               |

### Merge Order

1. `wp-proxy` (truthful response envelopes)
2. `frontend` (data-source-aware empty states)

### Manifest

```bash
make lane-manifest-init TASK=scan-complete-no-suggestions-fix LANE_IDS='wp-proxy frontend' TASK_PLAN=docs/tasks/10.0/10.3/scan-complete-no-suggestions-fix-plan.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: Use MCP worker lifecycle tools (`worker_start_all`, `worker_status`, `worker_stop`) with `backend="codex-subagent"`. The orchestrator daemon dispatches work, intakes merge-ready lanes, and refreshes downstream dependents automatically.
- **Shell fallback**: Use `make lane-open`, `make lane-run`, `make lane-handoff`, and `make lane-intake` from the orchestrator root.

---

# Consolidated Checklist

## Completed

- [x] Pipeline audit: see `scan-complete-no-suggestions-pipeline-audit-2026-03-25.md`
- [x] Refactoring evaluations: see `docs/tasks/tech-debt/refactoring-evaluation.md` and `refactoring-typescript-evaluation.md` (review findings tracked in MCP)

## Phase 0: Scaffolding

- [ ] Add `data_source` field to existing response types in TypeScript (`cluster.ts`, `suggestion.ts`, `identity.ts`).
- [ ] Verify scaffolds compile: `npm run typecheck`.

_(Optional, only if pursuing Phase 1):_ Create `ProxyPolicyService` class with interface stubs, `ProxyPolicy` value object, and verify with `composer phpstan`.
_(Optional, only if pursuing Phase 3):_ Create placeholder files: `jobSelectors.ts`, `pipelineDerivation.ts`, `statusFormatters.ts`, `useSyncStatusPresentation.ts`, `useSSEConnection.ts`, `useBroadcastSubscriber.ts`, `useOnlineStatus.ts`.

## Phase 1: PHP Proxy Policy Extraction (Optional; tech-debt follow-up)

- [ ] Implement `ProxyPolicyService::resolve_policy()` (move logic from `AbstractRecognitionProxyController::resolve_request_policy()`).
- [ ] Implement `ProxyPolicyService::dispatch()` (move logic from `AbstractRecognitionProxyController::proxy_request()`).
- [ ] Implement circuit-breaker methods (`is_circuit_open`, `record_failure`, `record_success`).
- [ ] Implement config resolution (`get_recognition_url`, `get_api_key`, `get_tenant_id`).
- [ ] Convert `ClustersController` to compose `ProxyPolicyService` (remove `extends AbstractRecognitionProxyController`).
- [ ] Convert `SuggestionsController` to compose `ProxyPolicyService`.
- [ ] Convert `MediaIdentitiesController` to compose `ProxyPolicyService`.
- [ ] Convert `AnalysisJobsController` to compose `ProxyPolicyService`.
- [ ] Convert `SyncStatusController` to compose `ProxyPolicyService`.
- [ ] _(Follow-up debt)_ Delete `AbstractRecognitionProxyController` once all subclasses are migrated.
- [ ] Update PHPUnit tests for each converted controller.

## Phase 2: PHP Truthful Response Envelopes

- [ ] Add `data_source` field to `ClustersController::list_top_unlabeled_clusters()` response.
- [ ] Add `projection_status` field to the same response.
- [ ] Add `data_source` field to `SuggestionsController::get_pending_suggestions()` response.
- [ ] Add `data_source` field to `SuggestionsController::get_pending_merge_suggestions()` response.
- [ ] Add `data_source` field to `MediaIdentitiesController::get_media_identities()` response.
- [ ] Update `empty_pending_suggestions_response()` to include `data_source: 'unavailable'`.
- [ ] Add PHPUnit tests asserting `data_source` values for success, proxy-unavailable, and projection-missing cases.
- [ ] Update WP REST contract docs (`docs/agentic/contracts/clustering-api.md`) with new `data_source` envelope fields.
- [ ] Update affected frontend adapters/types: `js/admin/api/recognition/identityQueriesApi.ts`, `types/suggestion.ts`, `types/identity.ts`.

## Phase 3: TypeScript State Decomposition (Optional; tech-debt follow-up)

- [ ] Split `jobStateMachineUtils.ts` into `jobSelectors.ts`, `pipelineDerivation.ts`, `statusFormatters.ts`.
- [ ] Update all import sites to reference new module paths.
- [ ] Extract `useSSEConnection()` from `useJobProgressStream.ts`.
- [ ] Extract `useBroadcastSubscriber()` from `useJobProgressStream.ts`.
- [ ] Extract `useOnlineStatus()` from `useJobProgressStream.ts`.
- [ ] Rewrite `useJobProgressStream` as thin composition of extracted hooks.
- [ ] Extract `useSyncStatusPresentation()` from `SyncStatusIndicator.tsx`.
- [ ] Slim `SyncStatusIndicator` to presentation-only component consuming the hook.
- [ ] Centralize `JobStatus` and `ProjectionSyncState` as `as const` enum objects in `types/`.
- [ ] Replace scattered magic-string comparisons with centralized enum imports.
- [ ] Vitest tests for each extracted module.

## Phase 4: Frontend Empty-State Truthfulness

- [ ] Add `data_source` to TypeScript response types (`TopUnlabeledClustersResponse`, suggestions response, media identities response).
- [ ] Update `fetchTopUnlabeledClusters` and other API fetchers to preserve `data_source`.
- [ ] Create `EmptyStateWarning` component for unavailable/failure states.
- [ ] Update `SuggestionReviewPanel` to render failure state when `data_source === 'unavailable'`.
- [ ] Update `IdentityClusterList` to render failure state when data source indicates unavailability.
- [ ] Update `TopClustersSection` to render failure/bootstrapping states using `data_source` and `projection_status`.
- [ ] Add Vitest tests for each component covering unavailable vs. genuinely-empty scenarios.

## Stretch Goals

- [ ] Add a `post_scan_read` proxy policy with a longer timeout (e.g., 10s) for the projection-critical window after scan completion.
- [ ] Add a workbench-level `ProjectionHealthBanner` that appears across all tabs when projection state is `error` or `bootstrapping`.
- [ ] Add structured logging to `ProxyPolicyService` for circuit-open events and timeout counts.

## Success Criteria

- [ ] After a completed scan where the backend has cluster data, the workbench never shows "No identities detected yet" or "No suggestions to review yet" when the real cause is proxy/projection failure.
- [ ] `data_source` field is present on all workbench-critical read endpoints and accurately reflects whether data came from local projection, backend proxy, or was unavailable.
- [ ] _(Follow-up debt)_ `AbstractRecognitionProxyController` is deleted; all controllers compose `ProxyPolicyService`.
- [ ] _(Follow-up debt)_ `SyncStatusIndicator` is under 100 lines; `useSyncStatusPresentation()` owns all derivation.
- [ ] _(Follow-up debt)_ `jobStateMachineUtils.ts` is deleted; functionality lives in 3 focused modules.
- [ ] All existing PHPUnit and Vitest tests pass after the refactoring.
