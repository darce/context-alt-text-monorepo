# Scope — UXP-NET-1: 429/backoff seam + suggestion fan-out (UXA-01)

**Intake decision:** `claude_scope_intake_uxp_net_429_fanout` (id 2433, task `workbench-502-triage`, 2026-07-15)
**Planning review:** round 1 `planrev-uxp-net-1-scope-20260715-r1` (conditional_pass, findings UXP-NET-1-PR-01..09) — this revision resolves all nine.
**Assessment anchor:** UXA-01 in `docs/assessments/current/ux-ui-pass-assessment-2026-07-15.md`¹
**Trigger incident:** 100-image batch on curation tenant :10018 — 502 storm (incl. `admin-ajax.php`) + post-batch `/cluster` 429.

¹ Assessment drift note (PR-09): UXA-01 describes the limiter as a "per-tenant token bucket, 60 rpm / burst 10" and credits `Retry-After` to the per-IP demo limiter. Actual mechanism: **per-api-key sliding window** that itself emits `Retry-After` + `X-RateLimit-*` (`recognition/interface_adapters/http/deps/rate_limit.py:66-82`; `docs/workbay/contracts/security.md:206-229`). This note's citations are authoritative.

All frontend paths relative to `apps/prototype-wp-alt-context/`.

## Root causes (verified, planrev round 1)

1. **502s** — per-identity `suggestions?top_k=1` fan-out (`InlineSuggestionPrompt.tsx:39-44`, one `useQuery` per unlabeled identity card rendered unpaginated by `IdentityClusterList.tsx:67`) + job polling saturates LocalWP php-fpm; nginx: `connect() to php-fpm.socket failed (61: Connection refused)` on those exact URLs → 502 on all PHP endpoints. Each aborted GET (2s timeout signal, `identityQueriesApi.ts:77`) is re-issued by `retry: 1` → up to 2N requests.
2. **429** — recognition per-key sliding-window limiter (60 rpm STANDARD; `recognition/interface_adapters/http/deps/rate_limit.py`) drained by polling + fan-out; post-batch `/cluster` lands on empty budget. Trigger chain: `useJobStateMachineEffects.ts:133-135` → `useClusterIdentities` (`useJobStateMachineMutations.ts:77-90`) → `clusterFaces` (`scanApi.ts:152-163`) → PHP `/recognition/cluster` (`class-cluster-mutations-controller.php:107`) → service `POST /recognition/clustering/jobs`. The same effect fires `invalidateQueries(suggestions.all + clusters.all)` (`useJobStateMachineEffects.ts:117-121,131-134`) — a refetch burst at the exact moment `cluster()` POSTs.
3. **Amplifier** — `js/admin/utils/http.ts:45-48` `fetchApi` throws a bare `Error` (status baked into the message string; headers discarded); QueryClient `retry: 1` status-blind (`App.tsx:15-23`, queries only — mutations do not retry today, so cluster auto-retry is net-new behavior).

**Verified plumbing (no PHP change needed):** the recognition 429 carries `Retry-After` (`rate_limit.py:77-81`) and the WP proxy forwards it through its header allowlist (`class-abstract-recognition-proxy-controller.php:374-393`); 429 < 500 passes through un-retried (`:169-178`). `X-RateLimit-*` is stripped by the allowlist — the client must rely on `Retry-After` only.

## MVP scope (frontend-only; zero server changes)

1. **Typed error seam** — `HTTPError extends Error` with `{ status, retryAfterSeconds }` in `js/admin/utils/http.ts`; `fetchApi` reads `response.status` + `Retry-After` header before throwing. Must stay `Error`-compatible (catch sites read `.message`, e.g. `useJobStateMachineMutations.ts:87-88`). `AbortError` from the 2s timeout signal is classified separately (timeout, not HTTP) and never enters 429 handling. 429 is a plain HTTPException — parse the **header**, not a body envelope.
2. **Retry policy** — QueryClient (`App.tsx`): never retry 4xx except 429; 429 delays honor `retryAfterSeconds`; 5xx keep bounded exponential backoff (RES-06/API-08).
3. **Shared 429 cooldown** — module-level cooldown singleton beside the QueryClient (`js/admin/App.tsx`), set on any 429, exposing `cooldownUntil`. Participating pollers gate via `refetchInterval`-as-function returning `false` during cooldown. Enumerated poller sites (all under `js/admin/hooks/`): `useSyncHealth.ts:14`, `useRetentionStatus.ts:67`, `useDescribeRunProgress.ts:53`, `useMediaIdentities.ts:31`, `useRecognitionHooks.ts:57,79,95,138`, `useRosterHooks.ts:17`, `useSyncStatus.ts:11`. The SSE stream (`useJobProgressStream.ts`) is explicitly **out** of cooldown scope (server-push, not request fan-out). The cooldown also gates the post-batch invalidation refetch burst (suggestions/clusters refetches wait out an active cooldown).
4. **Batch the suggestion fan-out** — replace N per-identity GETs with **one call to the existing `GET acx/v1/recognition/suggestions`** (PHP passthrough `class-suggestions-controller.php:36-56` → service `routers/suggestions.py:55`), passing explicit `limit=500` (service max page size). Client-side reduction replicating per-identity semantics (`suggestions.py:106-146`): group rows by `identity_id`, drop rows with null `cluster_label` (labeled-only), take top-1 by `similarity` per identity. Note: `top_k`/`threshold` were always ignored by the service — filtering is wholly client-side. New query key nests under `queryKeys.suggestions.all` so existing invalidations (`useJobStateMachineEffects.ts:120`, `useSyncTrigger.ts:29,86`) cover it; `InlineSuggestionPrompt` consumes a per-identity selector from the shared query.
5. **Post-batch cluster auto-retry** — wrap the trigger at `useJobStateMachineEffects.ts:133-135` / `useClusterIdentities` (`useJobStateMachineMutations.ts:77-90`): on 429, auto-retry after `retryAfterSeconds`, ceiling **exactly 3 attempts**, surfacing "Clustering queued — starting in Ns" through the job-pipeline status surface (`jobStateMachineProgress.ts` → `JobTimeline`); after the ceiling, show a manual "Retry clustering" affordance via the existing `onClusterError` path.

**Heuristics (canon `lexicons/engineering.md`):** RES-06 (backoff + ceiling), API-08 (bounded, never retry unmodified 4xx; 429+`Retry-After` is the sanctioned exception), RES-01/API-02 satisfied (limiter is a pre-handler dependency — 429 = request never executed → retry safe), AGT-10 (degrade loudly — honest queued status).

## Success criteria

1. **Incident replay:** 100-image batch on the curation tenant completes with clustering hands-off. Zero 502s; zero *unrecovered* 429s (a 429 that auto-recovers via the queued path is a pass; console noise from recovered 429s is acceptable).
2. **Bounded request budget (automated):** N unlabeled identities → exactly `ceil(P/500)` suggestion requests, where P = pending-suggestion rows (practically 1 request); no retry on 4xx≠429; 429 retry delay equals the `Retry-After` value. Tests: `js/admin/utils/__tests__/http.test.ts` (HTTPError seam), `js/admin/pages/workbench/identity-clusters/__tests__/suggestionBatching.test.tsx` (fan-out reduction), following the `vi.mock('../../utils/http')` pattern from `js/admin/api/__tests__/recognitionApi.test.ts`.
3. **Cluster 429 recovery (automated):** mocked 429 with `Retry-After: 2` → exactly 3 bounded attempts, queued-status copy rendered, manual-retry affordance after ceiling.
4. **Before/after evidence:** devtools request count for the workbench render with ~20 unlabeled identities drops from ~20+ suggestion GETs to 1.

## Follow-up (separate task, currently **unowned**)

Server-side relief: suggestions-endpoint hardening, php-fpm-facing load-shedding, proxy blocking-retry loop (`usleep` holds workers ~3.5s extra, `class-abstract-recognition-proxy-controller.php:155-190`), and the suggestions proxy masking terminal 5xx as HTTP 200 `{matches: []}` (`class-suggestions-controller.php:207-214` — the HTTPError seam never sees 5xx on that endpoint). E20-4/E20-7 do **not** own this (E20-7 = WP description-generation budgets; E20-4 = bulk generation ledger); candidate owner: new task or E15 recognition-service scope. Any new batch endpoint is a contract extension of `docs/workbay/contracts/suggestion-extensions-api.md`.

## Not-doing

- UXA-02 heartbeat / honest-status work (separate task).
- Rate-limit tier changes or per-endpoint limiter exemptions.
- php-fpm pool tuning (LocalWP config is out of plugin-boundary bounds).
- Server/PHP code changes of any kind (MVP verified implementable without them).
- Saturation-probe server hardening (moved to follow-up — untestable by frontend-only scope, PR-02).
