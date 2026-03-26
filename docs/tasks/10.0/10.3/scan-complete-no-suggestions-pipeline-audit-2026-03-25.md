# Scan Complete But No Suggestions: Pipeline Audit

**Date:** 2026-03-25
**Scope:** Scan-complete -> job polling -> projection sync -> sovereign local projection -> workbench suggestion surfaces
**Context:** User-reported runtime symptom after a completed scan:

- Workbench shows `Scan complete` and `Phase: Complete`
- Media rows still render `No identities detected yet.`
- Suggestion panel shows `No suggestions to review yet.`
- Browser console shows repeated `404` and `502` responses from `GET /wp-json/acx/v1/recognition/jobs/{job_id}` plus a `502` from `admin-ajax.php`

This audit focuses on the WordPress sovereign plugin path because the current workbench UI relies on the plugin as the local authority for cluster, identity, and top-unlabeled reads once projection exists.

---

## Executive Summary

The strongest explanation is not "the backend found nothing." The more likely failure mode is:

1. The backend analyze/clustering pipeline reached a terminal state for the scan job.
2. The follow-on projection or status-read path became unavailable or slow enough to trip the WordPress proxy layer.
3. The sovereign plugin then normalized those failures into empty success payloads for identities, suggestions, and top-unlabeled reads.
4. The workbench rendered those empty payloads as benign "nothing here" empty states instead of surfacing projection/backend failure.

That matches the reported symptoms much better than an all-singleton explanation:

- `MediaIdentitiesController` can return `200 { identities_by_media: {} }` when the proxy is unavailable.
- `SuggestionsController` can return `200 { suggestions: [], total: 0 }` when the proxy is unavailable.
- `ClustersController::list_top_unlabeled_clusters()` returns `200 { clusters: [], singleton_count: 0 }` whenever local projection is unavailable, without attempting a backend fallback read.

The current UI therefore cannot distinguish:

- no identities were actually found
- identities exist remotely but projection never landed locally
- the backend is temporarily unavailable
- the proxy timed out and opened its circuit breaker

---

## Findings

### F1. Proxy and projection failures are silently converted into empty success payloads

**Severity:** High

**Why it matters:** This is the closest code-level match to the user-visible behavior.

**Evidence:**

- `MediaIdentitiesController::get_media_identities()` returns a `200` response with empty `identities_by_media` whenever `is_proxy_unavailable()` is true.
- `SuggestionsController::get_pending_suggestions()` and `SuggestionsController::get_pending_merge_suggestions()` return `empty_pending_suggestions_response()` on proxy unavailability.
- `ClustersController::list_top_unlabeled_clusters()` returns an empty envelope when local projection is unavailable.

**Observed effect in UI:**

- `IdentityClusterList` sees an empty identities array and renders `No identities detected yet.`
- `SuggestionReviewPanel` sees empty suggestion arrays and renders `No suggestions to review yet.`
- `TopClustersSection` never appears because `clusters: []` and `singleton_count: 0` are treated as a genuine empty state.

**Assessment:**

The plugin currently favors uptime-shaped read responses over truthful diagnostics. That keeps the UI from crashing, but in this failure mode it actively hides the root cause.

---

### F2. The top-unlabeled naming queue is hard-gated on successful sovereign projection

**Severity:** High

**Why it matters:** This problem is directly linked to the sovereign plugin work.

**Evidence:**

- `ClustersController::list_top_unlabeled_clusters()` does not proxy to the backend when local projection is missing.
- Instead, it schedules `BOOTSTRAP_SYNC_HOOK` and immediately returns an empty `clusters/singleton_count` envelope.
- `ClustersControllerTest::testTopUnlabeledClustersReturnsEmptyArrayAndSchedulesBootstrapWhenProjectionUnavailable()` locks this behavior in as the expected contract.

**Implication:**

Even if the backend has valid unlabeled clusters after clustering completes, the workbench naming queue remains empty until projection succeeds locally.

**Assessment:**

This is a sensible local-authority design for steady state, but it creates a sharp failure edge:

- if projection succeeds, the naming queue works
- if projection fails or is delayed, the UI looks identical to "there are no clusters to label"

This is the clearest sovereign-plugin-specific linkage to the reported issue.

---

### F3. The proxy read policy is aggressive enough to manufacture post-scan failures under load

**Severity:** Medium-High

**Evidence:**

- `AbstractRecognitionProxyController::resolve_request_policy()` assigns all GET requests to `ui_read`.
- `ui_read` uses:
  - `timeout_seconds = 2`
  - `max_retries = 1`
  - `circuit_enabled = true`
- `record_proxy_failure()` opens the circuit after two failures for sixty seconds by default.
- The frontend also uses a `2_000ms` timeout in `fetchScanStatus()`.

**Why this matters here:**

Immediately after a 937-image scan, the system performs several read-heavy operations:

- poll `/recognition/jobs/{job_id}`
- optionally stream `/recognition/jobs/{job_id}/stream`
- load media identities
- load suggestions
- trigger sync/projection reads

If the backend is merely slow rather than down, the WordPress proxy can still convert that transient slowness into:

- `502` responses
- an open circuit
- follow-on empty payload fallbacks from Finding F1

**Inference from the browser trace:**

The reported repeated `502` responses on the current job endpoint are consistent with this timeout/circuit policy. I cannot prove timeout was the exact runtime cause from code alone, but the policy is aggressive enough that it is a credible contributor.

---

### F4. The workbench UI does not thread projection failure into the suggestion and identity empty states

**Severity:** Medium

**Evidence:**

- `useJobStateMachineEffects()` tracks `projectionSyncState` and `projectionError`.
- `SyncStatusIndicator` is the only major workbench surface that renders that error explicitly.
- `SuggestionReviewPanel` does not read projection state at all.
- `IdentityClusterList` only distinguishes `clusters.length === 0`.
- `TopClustersSection` only distinguishes `clusters.length` and `singleton_count`.

**Result:**

Three materially different states collapse into the same empty copy:

- genuinely no identities/suggestions
- projection still pending
- projection sync failed / backend unavailable

**Assessment:**

This is not the root cause of the missing suggestions, but it is a major debugging blocker because the UI erases the distinction operators need most.

---

### F5. Job history and job polling add noise that can obscure the real failure

**Severity:** Low

**Evidence:**

- `useRecognitionJobHistory()` eagerly re-fetches all stored job IDs from localStorage on mount.
- Stale history entries generate `404` requests until the hook prunes them.
- The browser trace includes a `404` for a different job ID before the `502`s for the current job.

**Assessment:**

This is probably not the primary cause of the missing suggestions, but it makes browser traces noisier and can mislead debugging toward "old job not found" instead of the live projection/sync problem.

---

## Probable Failure Chain

The most likely code-path sequence is:

1. The backend scan/clustering work finished or at least reported a terminal state.
2. The plugin tried to read or sync projection state through `/recognition/jobs/{job_id}` and/or `/recognition/sync/trigger`.
3. Those reads failed with `502` or timed out.
4. Local projection never became authoritative, so `ClustersController::list_top_unlabeled_clusters()` returned the empty sovereign bootstrap envelope.
5. The identities and suggestion controllers also degraded failure into empty `200` payloads.
6. The workbench displayed "no identities" and "no suggestions" instead of "projection/backend failure."

This explanation is consistent with both the browser console and the UI screenshot.

---

## Refactor Crosswalk

### Changes from `refactoring-typescript-evaluation.md` that would help

**TS-H1: `SyncStatusIndicator` god component**

- Helpful for debugging and reasoning.
- Today, sync health, projection state, retry actions, and presentation are tangled in one component.
- Extracting `useSyncStatusPresentation()` would make it easier to feed the same projection failure state into the suggestion panel and media empty states.

**TS-H4: `jobStateMachineUtils` mixed concerns**

- Helpful for debugging and reasoning.
- Phase derivation, status text, and progress shaping are mixed together.
- Splitting this into selectors, derivation, and formatting would make it easier to reason about when the UI should say `projecting`, `complete`, or `failed`.

**TS-M3: `useJobProgressStream` long hook**

- Helpful for debugging.
- The SSE/broadcast/online-state behavior is packed into one hook, which makes it harder to see whether the UI is trusting SSE, polling, or stale state after failures.
- Extracting smaller hooks would improve observability but would not by itself fix the missing suggestions.

**TS-M4: scattered magic status strings**

- Moderately helpful.
- Centralized enums for job/projection states would reduce accidental mismatches and make error-specific UI states easier to add.

### Changes from `refactoring-ui-evaluation.md` that would help

**UI-L2: Inconsistent Empty State Treatment**

- Helpful for diagnosis only.
- The current empty state design work would make it easier to present distinct states for:
  - no data yet
  - waiting for projection
  - service unavailable
  - retry required
- This would not fix the pipeline, but it would stop the UI from lying by omission.

### Changes from `refactoring-evaluation.md` that would help

**Fowler-M5: `AbstractRecognitionProxyController` as a Middle Man**

- Highly relevant.
- The failure masking and request policy logic are centralized in the inherited proxy layer, which makes controller behavior uniform but also hides dangerous defaults.
- Refactoring proxy policy into a dedicated service would make per-endpoint read behavior explicit and easier to tune.

**Fowler-H1: `cluster_repository.py` large class**

- Helpful for debugging backend top-unlabeled behavior.
- The backend query path is dense and hard to reason about quickly.
- This would improve maintainability of cluster reads, but it does not explain the empty UI as directly as the plugin fallback behavior does.

**Fowler-H5: `tenant_id` threading**

- Potentially helpful if tenant mismatches are suspected.
- I did not find direct evidence of tenant mismatch in this audit, so this is not my leading explanation.

---

## What Would Most Likely Help Fix This Issue

### Immediate diagnostic changes

1. Stop returning empty success payloads for proxy/projection failures on the workbench-critical read paths.
2. Teach the suggestion panel and media identity empty state to render a projection/backend failure state when sync or proxy reads fail.
3. Split "projection unavailable" from "no data exists" in the top-unlabeled controller contract.

### Targeted pipeline checks

1. Inspect whether `/recognition/jobs/{current_job_id}` is timing out in the proxy layer versus returning a real backend error.
2. Inspect whether `trigger_sync()` is returning `sync_failed`, `sync_unavailable`, or `no_remote_data` for the tenant after scan completion.
3. Inspect local sovereign sync state for the tenant:
   - snapshot version
   - last updated
   - last sync result
4. Inspect whether local `wp_acx_clusters` and `wp_acx_identity_members` were populated for the tenant at all.

### Refactors that are worth doing soon

1. Apply the `AbstractRecognitionProxyController` policy extraction before further debugging-by-patching.
2. Split the workbench job state derivation utilities so projection state can be consumed by more than `SyncStatusIndicator`.
3. Rework workbench empty states so "empty" is never used as a fallback for transport failure.

---

## Bottom Line

The current code strongly suggests a sovereign-plugin-side failure-masking problem, not simply an absence of cluster suggestions. The UI is currently capable of showing:

- "no identities"
- "no suggestions"

even when the real state is:

- "the backend job read failed"
- "projection did not land locally"
- "the proxy circuit opened after repeated slow reads"

That is the main conclusion of this audit, and it is exactly the part of the stack most tightly coupled to the recent sovereign plugin work.
