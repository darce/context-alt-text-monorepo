# UXP-2. Network Discipline: 429 Backoff + Suggestion Fan-out

> **Metadata**
>
> - **Date**: 2026-07-15 04:35 EST
> - **Author**: claude-opus-4-8
> - **Project**: prototype-wp-alt-context (admin SPA + PHP proxy) · prototype-description-service (recognition)
> - **Task ID**: `UXP-2`
> - **Target Branch**: `feature/uxp-2`
> - **Review Coverage Target**: 2

---

## Objective

Stop the 429 storm at one seam: `fetchApi` gains a typed error, one shared retry policy replaces four private ones, a shared cooldown quiets the pollers that reach the recognition service, and the per-card suggestion fan-out collapses into one bounded call.

## Intake

- **Scope one-pager**: `docs/scopes/uxp-ux-pass-decomposition.md` (§ UXP-2)
- **Source assessment**: `docs/assessments/current/ux-ui-pass-assessment-2026-07-15.md` (**UXA-01** only)
- **Key decisions**: UXP-1 `claude_uxp1_scope_intake_v1`; `claude_planning_review_uxp2_fail_v1` (planning-review fail + operator's scope-split decision).
- **Not-Doing**:
  - **Honest service status / heartbeat (UXA-02) → its own task.** The original UXP-2 carried UXA-01 and UXA-02; planning review produced six independent design blockers against the heartbeat alone. Deferred findings `UXP-2-PR-01..06,12,13,14,16,17` are its inputs.
  - Server-side rate-limit redesign (E20-7/E20-11), SSE migration of job polling, outbox/dispatcher retry changes.
  - **`useSyncHealth` is deliberately untouched** — see *Cooldown membership* below.

## Problem Statement

Three defects compound into a 429 storm. Each was resolved against the tree this session.

**1. The fetch seam erases the error.** `fetchApi` (`js/admin/utils/http.ts`, the `!response.ok` branch) throws a bare `Error` with the status interpolated into a message string. Status and `Retry-After` survive only as prose. Downstream code already pays for this: three pollers sniff `error.message.includes('404')` to detect a 404.

**2. Four private retry policies, none of which is the shared one.** The QueryClient (`js/admin/App.tsx` : `queryClient`) sets `retry: 1` with exponential `retryDelay` for all queries — every 4xx retried once, `Retry-After` ignored ([RES-06] / [API-08]). But four hooks override it entirely:

| Hook | Local policy | Cadence |
| --- | --- | --- |
| `useScanStatus` (`useRecognitionHooks.ts`) | `retry: failureCount < 3`, `message.includes('404')` guard | 1.5s |
| `useMultiScanStatus` (`useRecognitionHooks.ts`) | same | 1.5s |
| `useBatchRunStatus` (`useRecognitionHooks.ts`) | same | 1.5s |
| `useDescribeRunProgress` (`useDescribeRunProgress.ts`) | `retry: DESCRIBE_RUN_POLL_RETRIES` (3) **plus its own `retryDelay`** (backoff cap 8s) | 2s |

All four retry a 429 up to three times. These are the hottest queries in the admin.

A fifth query, `useMediaIdentities`, sets `retry: false`. It is a private policy too, but a *conservative* one, and it stays — see slice 1.

**3. The suggestion fan-out is N+1 twice over.** `InlineSuggestionPrompt` runs its own `useQuery` per card, rendered once per unlabeled cluster in `IdentityClusterItem` (the `!cluster.label && anchorIdentityId && canMutate` gate) — N unlabeled cards produce N parallel GETs. The server's `list_suggestions` (`suggestions.py`) **has no `top_k` parameter at all**: the client's `top_k=1` ("Only fetch top 1") is dropped by FastAPI, every match is returned, and each is enriched with a separate `cluster_repo.get_by_id`. [RES-12] nested inside itself, plus a client comment documenting behavior the server never implemented.

### Query inventory — cooldown membership

Not every `acx/v1/recognition/*` route reaches the recognition service; membership is decided per query, by what it actually calls, not by URL shape.

| Query | Cadence | Reaches recognition? | Gated? |
| --- | --- | --- | --- |
| `useScanStatus` | 1.5s (while running/pending) | yes — proxied job status | **yes** |
| `useMultiScanStatus` | 1.5s, one query per job id | yes | **yes** |
| `useBatchRunStatus` | 1.5s (until terminal) | yes | **yes** |
| `useDescribeRunProgress` | 2s (until terminal) | yes — `describe/runs/{id}` | **yes** |
| `useMediaIdentities` | 3s, **conditional** on `hasPendingClustering`; already `retry: false`, already stops on error | yes | **yes** |
| `useRecognitionClusters` | 30s | sometimes — `ClusterReadService` serves the local projection mirror when `should_use_local_projection()` | **yes** (gating a local read costs nothing; not gating an upstream read costs a storm) |
| `useSyncHealth` | 15s | **no** — `SyncHealthController::get_sync_health` reads a transient plus local `SyncStateRepository` / `OutboxQueryRepository` counts and makes zero upstream calls | **no** — see below |
| `useSyncStatus` | 120s | **no** — `SyncStatusController::get_sync_status` reads local `SyncStateRepository` state only; no `wp_remote_*` call | **no** — local; there is nothing to gate |

**The two sync hooks are excluded deliberately, and for the same reason:** neither calls recognition, so neither can produce a recognition 429 and neither contributes to a storm. Gating `useSyncHealth` would additionally halve the operator's status freshness (15s → 30s) exactly when they are trying to understand the storm, while saving zero upstream requests. Both stay unmodified.

Both are nonetheless under the `acx/v1/recognition/*` route prefix — which is why membership is decided by what a query *calls*, not by what its URL *looks like*.

## Constraints

- **Greenfield** (CLAUDE.md): no compatibility shims. Change the contract and its consumers in the same slice.
- **The proxy already retries.** `AbstractRecognitionProxyController` retries 5xx internally up to `max_retries` before returning. Client-side 5xx retry multiplies against that budget; the total must be stated, not discovered.
- **Overload arrives as 503, not 429.** `backend_overloaded_response` returns **503 + `Retry-After`**, and `normalize_response_headers` forwards `retry-after` from upstream. A client that only special-cases 429 will backoff-retry a 503 that means "the breaker is open, stop asking".
- **`Retry-After` is delta-seconds here.** PHP `parse_retry_after` (`class-settings-controller.php`) explicitly rejects HTTP-date, documenting that delta-seconds is what the recognition rate limiter emits.
- Status values centralize as `as const` / backed enums (sr-007).
- Prefer symbol names over line numbers in change sites — line anchors drift.

## Workflow Principles

- **One seam per concern.** Error typing at `fetchApi`; retry policy at the QueryClient; cooldown in one shared gate. This slice *deletes* the four private policies rather than merely asserting the principle.
- **Membership by behavior, not by URL.** A query is gated because it calls recognition, not because its path matches a prefix.
- **Bound every collection** ([API-01]). A batch call takes an explicit, clamped id list.
- **Name the layer that owns the budget.** Retry lives in the proxy or the client, with a stated total, never implicitly in both.

## Terminology

- **Cooldown**: a shared client-side window, opened when any recognition-backed request returns 429 or 503-with-`Retry-After`, during which the gated pollers suspend refetching.
- **Gated pollers**: the explicit set in the membership table above. Not a URL predicate — the admin's endpoints are absolute `rest_url()` values whose shape varies with permalink structure (`/wp-json/acx/v1/…` vs `?rest_route=/acx/v1/…`), so a path-prefix test is both brittle and wrong (it would catch `sync/health`, which never calls recognition).

## Current State Analysis

**Works today:** `createRecognitionTimeoutSignal(2_000)` bounds recognition reads ([RES-02] satisfied at that seam); the proxy's breaker trips deterministically under a lock-guarded counter; `useMediaIdentities` already declines to retry and already stops polling on error — the one poller that behaves.

**Broken or drifting:** `fetchApi` erases status; the QueryClient's policy is overridden by the four hottest queries; those four sniff error strings for 404; `top_k` is a no-op the client believes in.

**Misleading:** the comment `// Only fetch top 1` asserts a bound the server does not honor.

## Target Outcome

A 429 or overload-503 from a recognition-backed request puts the gated pollers into a shared cooldown honoring the server's `Retry-After`; no 4xx is retried except an explicit "ask again later"; and no query carries a private retry policy. The workbench asks for suggestions once per render, for exactly the identities that will render a prompt, and the server honors the bound it advertises.

## Context Loading

- Rules: `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/backend-php-guidelines.md`, `docs/workbay/rules/testing-typescript.md`, `docs/workbay/rules/testing-python.md`
- Heuristics: `heuristics-canon` `engineering.md` ([RES-01], [RES-02], [RES-06], [RES-12], [RES-15], [API-01], [API-08], [API-09], [OBS-05], [REF-05], [REF-09], [RLSE-04], [TEST-03], [TEST-06]) and `accessibility.md` ([A11Y-21], [A11Y-24]). Vendored at `docs/reviews/uxp-2/lexicons/` — every ID above was checked to exist there before citation ([AGT-02]: a missing anchor is a finding, not a license to improvise). The local `docs/workbay/rules/engineering-heuristics.md` is byte-identical to canon as of 2026-07-15, but it is gitignored, so that parity is incidental — treat canon-via-`gh` as the source of record.
- Handoff/MCP: task ref `UXP-2`; planning findings `UXP-2-PR-*`, `UXP-2-PR2-*`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `GET /identities/{id}/suggestions` `top_k` | recognition (Python) | param sent by client, **silently ignored** | honor as a clamped `Query`. **Behavior change** for `useClusterSuggestionsLoader`'s `top_k=5`, which today receives unbounded matches. | no — greenfield | API test bounding the returned match count |
| `GET /suggestions` result completeness | recognition (Python) → client | caller must page; no truncation signal in the body | client sends `limit` ≥ id count; **a full page is treated as suspected truncation, not success** ([API-01]: could a client tell it was truncated?) | no | test: 60 unlabeled cards → every card resolves |
| `GET /suggestions` `identity_ids` | recognition (Python) | `limit`/`offset`/`min_confidence`; **`limit` defaults to 50** | add `identity_ids`, max = `security_settings.max_page_size` (default 500), over-limit **rejected** not truncated. Must apply on **both** the plain and `min_confidence` paths. Client must send an explicit `limit` — see *Truncation* below. | no — additive | API tests incl. `min_confidence` **and** `identity_ids` together; **>50-card truncation test** |
| `GET /identities/{id}/suggestions` behavior | recognition (Python) | `top_k` ignored → unbounded matches | enforcing it is a **breaking change for an existing caller** ([API-09]: changed defaults count as breaking — Hyrum's Law), not a mere tightening | no — greenfield, but the change must be *reasoned*, not waved through | test pinning the `top_k=5` caller's new bound |
| `acx/v1/recognition/suggestions` proxy | proxy (PHP) | `limit`/`offset` in route `args` | `SuggestionsController::get_pending_suggestions` forwards `identity_ids`; route `args` gains an array entry | no | PHP proxy test |
| `fetchApi` thrown type | frontend (internal) | `Error` with status in the message | `HTTPError` with `status` | n/a — but **four call sites string-sniff the message** and must migrate in the same slice | unit tests on the 404 path |

## Proposed Solution

Four slices. Slice 1 makes the error honest and consolidates all four retry policies into one. Slice 2 adds the cooldown over an explicit membership set. Slice 3 splits server from client, because `top_k` and `identity_ids` are independently shippable contract changes and the component restructure is not.

**Retry budget, stated.** The proxy retries 5xx internally up to `max_retries`. The client therefore adds **no second 5xx retry layer**: by the time the browser sees a 5xx, the proxy has exhausted its budget, and retrying again is the [RES-06] amplification this task exists to stop. The client retries only on transport failure (no response at all) and on 429/503-with-`Retry-After` — explicit "ask again later" instructions, not failures.

**Cooldown trigger.** `fetchApi` throws `HTTPError`; the QueryClient error path opens the cooldown on 429 or 503-with-`Retry-After`. No URL predicate: WordPress does not rate-limit these admin routes, so such a response on an `acx` route originates upstream. A false positive (some intermediary emitting 429) costs one bounded cooldown window and is benign — stated here so the assumption is reviewable rather than implicit.

**Cooldown membership** is the explicit table above, keyed on whether the query reaches recognition. `useSyncHealth` is excluded because it provably does not.

**The cooldown is a second breaker — name it as one** ([RES-15]: circuit-break integration points; stop calling what's already failing). The proxy already owns a server-side breaker; `recognitionCooldown` is a *client-side* one that trips on an upstream signal, suspends calls, and half-opens on expiry. Two consequences follow and are not optional: its state must be **observable** (RES-15's "expose breaker state to operations", and [OBS-05]: a new breaker without metrics), and its interaction with the proxy's breaker must be bounded the same way the retry budget is — a proxy 503-with-`Retry-After` (breaker open) and a client cooldown are the same signal at two layers, so the client waits, it does not re-probe.

**Truncation — the batch must not silently lose cards.** `list_pending_suggestions` declares `limit: int = Query(default=50)`. A workbench with more than 50 unlabeled cards would send one request for up to 500 ids and receive **the first 50 rows**; every card past the cut renders no prompt, and the naive success criterion ("N cards → one request") passes while the feature is broken. This is [API-01]'s second, easily-skipped clause: *could a client tell it was truncated?* Therefore: the client sends an explicit `limit` ≥ the id count it asked for, and a response whose row count equals the requested `limit` is treated as **suspected truncation** — logged and surfaced, never silently accepted. The plan also deliberately deviates from [API-01]'s "clamp" guidance for `identity_ids` itself: clamping an id list silently drops identities, so over-limit is **rejected**. Both choices are stated here so a reviewer can disagree with them.

**`Retry-After` parsing.** Delta-seconds is the contract. The TS parser accepts delta-seconds; HTTP-date is handled defensively for intermediaries but is explicitly out-of-contract; malformed values fall back to bounded backoff, never `NaN`.

**The frozen state is a designed state, not a side effect** ([RLSE-04]: undesigned state is a bug — offline is one of the states that must be intentionally designed). A cooldown suspends six pollers for a server-dictated window, one of which (`useDescribeRunProgress`) drives a **progress bar**. A progress bar that stops advancing for 30s with no explanation reads as a hang, and the user's repair instinct — reload, re-run — is exactly the traffic the cooldown exists to prevent. So the cooldown is surfaced: affected surfaces show a brief "waiting for the service" state with the remaining window, and it is announced ([A11Y-21]: async updates without focus need a live region / `role="status"`, cross-referenced by [A11Y-24]'s state-matrix join). This is the one seam where the accessibility lexicon touches this plan.

**Cooldown state is derived, not mirrored** ([REF-09]: a stored value computable from other data can desync). `isCoolingDown()` computes `Date.now() < expiresAt` on read; it does **not** cache a boolean flipped by a `setTimeout` callback. Background-tab timer throttling would leave such a flag stale and the pollers frozen past expiry — and fake-timer tests would not catch it.

## Files and Surfaces to Change

| Surface | File : symbol | Change |
| --- | --- | --- |
| frontend | `js/admin/utils/http.ts` : `HTTPError` (new), `fetchApi` | Throw `HTTPError {status, retryAfterSeconds, endpoint, bodyPreview}` |
| frontend | `js/admin/App.tsx` : `queryClient` | One `retry`/`retryDelay` predicate: transport + 429/503-with-`Retry-After` only; never other 4xx; no second 5xx layer |
| frontend | `js/admin/hooks/useRecognitionHooks.ts` : `useScanStatus`, `useMultiScanStatus`, `useBatchRunStatus` | **Delete** local `retry`; replace `error.message.includes('404')` with `error.status === 404`; gate `refetchInterval` on the cooldown |
| frontend | `js/admin/hooks/useDescribeRunProgress.ts` : `useDescribeRunProgress` | **Delete** local `retry` + `retryDelay` (and the now-unused `DESCRIBE_RUN_POLL_RETRIES`); gate `refetchInterval` on the cooldown |
| frontend | `js/admin/utils/recognitionCooldown.ts` (new) : `openCooldown`, `isCoolingDown`, `subscribe` | The shared gate |
| frontend | `js/admin/hooks/useMediaIdentities.ts` : `useMediaIdentities` | Gate `refetchInterval` on the cooldown (keep `retry: false`) |
| frontend | `js/admin/hooks/useRecognitionHooks.ts` : `useRecognitionClusters` | Gate `refetchInterval` on the cooldown |
| frontend | `identity-clusters/IdentityClusterList.tsx` : `IdentityClusterList` | Derive the batch id set; one call |
| frontend | `identity-clusters/useInlineSuggestionBatch.ts` (new) | The single bounded list call + response mapping |
| frontend | `identity-clusters/InlineSuggestionPrompt.tsx` : `InlineSuggestionPrompt` | Presentational; match by prop; per-card `useQuery` removed |
| frontend | `js/admin/api/recognition/identityQueriesApi.ts` : `fetchIdentitySuggestions` (+ batch fn) | `top_k` becomes a real bound |
| backend | `routers/suggestions.py` : `list_suggestions` | Honor clamped `top_k`; batch the `cluster_repo.get_by_id` enrichment |
| backend | `routers/suggestions.py` : `list_pending_suggestions` | Add `identity_ids`; **bind it into the `_collect_min_confidence_page` callable** (lambda/`partial`, mirroring the merge route) |
| backend | `application/suggestions/service.py` : `SuggestionService.list_pending` | Gains `identity_ids` |
| backend | `infrastructure/repositories/suggestion_repository.py` : `SqlAlchemySuggestionRepository.list_pending_with_details` | Gains `identity_ids`; SQL filter |
| php | `src/api/class-suggestions-controller.php` : `get_pending_suggestions` + route `args` | Forward `identity_ids`; declare the array param |
| tests | TS/PHP/Python suites | Per slice, below |

## Related Files

| File : symbol | Note |
| --- | --- |
| `class-abstract-recognition-proxy-controller.php` : `backend_overloaded_response`, `normalize_response_headers` | The proxy's retry budget, the overload-503, `Retry-After` forwarding. Not modified. |
| `useClusterSuggestionsLoader.ts` | The `top_k=5` caller whose live behavior changes when `top_k` becomes real |
| `suggestion_repository.py` : `list_pending_with_details` | Filters to `user_confirmed` clusters with non-`cluster-` labels **at query time** — stricter than the per-card path |
| `class-suggestions-controller.php` : `get_identity_suggestions` | Forwards `top_k` for the **per-identity** route. Not the `identity_ids` site. |
| `js/admin/hooks/useSyncHealth.ts` | Deliberately untouched — reads local state only |

## Verification Strategy

- Deterministic tests:
  - `npm --prefix apps/prototype-wp-alt-context test`
  - `composer --working-dir=apps/prototype-wp-alt-context test`
  - `make test` (recognition suite, marker-filtered)
- Contract/fixture verification:
  - `top_k` bounds the returned match count (incl. the `top_k=5` caller's changed behavior)
  - `identity_ids` returns the subset; over-limit rejected; **`min_confidence` + `identity_ids` together** still filters by identity
  - both endpoints' cluster filters pinned against one fixture
- Runtime-parity: `make check-remote` for the committed HEAD
- Manual (**dev recognition only** — never the prod/demo host):
  - Dev service rate-limiting → zero repeated-429 loops; gated pollers cool down and resume; sync-health banner keeps updating at 15s.
  - Workbench with N unlabeled cards → one suggestions request.

## Slice Delivery

### Slice 1: Typed HTTPError + one retry policy

**Goal**: One retry policy, obeyed by every query, that never retries a 4xx except an explicit "ask again later".

Changes:

- `HTTPError` in `http.ts`: `status`, `retryAfterSeconds` (delta-seconds; HTTP-date defensive; malformed → `undefined`, never `NaN`), `endpoint`, `bodyPreview`.
- QueryClient predicate: retry on transport failure and on 429/503-with-`Retry-After` (honoring the header, bounded attempts); never other 4xx; **no second 5xx layer**.
- Delete all four private policies — the three in `useRecognitionHooks.ts` plus `useDescribeRunProgress`'s `retry` + `retryDelay` — and migrate their 404 guards from `error.message.includes('404')` to `error.status === 404` ([TEST-03]: characterize the current 404 behavior first; actual, not intended, is the contract).
- **`useMediaIdentities` keeps `retry: false` — the one documented exception.** It genuinely diverges from the shared predicate (it declines even the transport-failure and 429/503-with-`Retry-After` retries). That is acceptable because the query is conditional, already stops polling on error, and is gated by the cooldown — its next scheduled poll *is* the retry. Retained deliberately, not by omission; the success criterion names it rather than pretending it does not exist.
- Poll queries are GETs, so retry is idempotent by construction ([RES-01] — noted, not a risk).

Proof:

- Characterization tests pinning today's 404 behavior for all four hooks, written and green **before** the migration.
- Unit: 429 + `Retry-After: 5` → one retry at ~5s; 503 + `Retry-After` → same; 503 bare → no retry; 403 → no retry; 404 via `error.status` → no retry; malformed header → bounded backoff, no `NaN`.
- Each watched failing once ([TEST-06]).

### Slice 2: Shared cooldown gate

**Goal**: One "ask again later" quiets every recognition-backed poller — and nothing else.

Changes:

- `recognitionCooldown`: `openCooldown(seconds)`, `isCoolingDown()`, subscribe/notify; single source of truth (sr-007).
- QueryClient error path opens the cooldown on 429/503-with-`Retry-After`.
- Gate `refetchInterval` on the cooldown for exactly the membership set: `useScanStatus`, `useMultiScanStatus`, `useBatchRunStatus`, `useDescribeRunProgress`, `useMediaIdentities`, `useRecognitionClusters`. Resume on expiry.
- `useSyncHealth` and `useSyncStatus` are **not** gated — both read local state only (membership table).

Proof:

- Unit with fake timers: one 429 suspends all six gated pollers; `useSyncHealth` keeps its 15s cadence untouched; expiry resumes; no timer leak on unmount.
- Manual: rate-limited dev service → no repeated-429 loop.

### Slice 3a: Server — honor `top_k`, add `identity_ids`

**Goal**: The server honors the bound it advertises and can answer for many identities in one call — on every code path.

Changes:

- `top_k` becomes a real clamped `Query` on `list_suggestions`. This is a **breaking behavior change for an existing caller**, not a tightening: `useClusterSuggestionsLoader` sends `top_k=5` and today receives unbounded matches ([API-09]: changed defaults count as breaking — Hyrum's Law). Greenfield exempts us from a migration, not from the reasoning.
- `identity_ids` threaded router → `SuggestionService.list_pending` → `SqlAlchemySuggestionRepository.list_pending_with_details`, bounded by `security_settings.max_page_size`, over-limit rejected ([API-01]).
- **The `min_confidence` branch must bind it too.** `list_pending_suggestions` currently passes `suggestion_service.list_pending` to `_collect_min_confidence_page` as a bare two-arg callable invoked as `fn(batch_limit, batch_offset)`; an unbound `identity_ids` would be silently dropped there — this task's own headline bug, reintroduced. Bind via lambda/`partial`, mirroring the merge route's existing shape.
- Batch the per-suggestion `cluster_repo.get_by_id` enrichment into one lookup ([RES-12]).
- PHP proxy: `get_pending_suggestions` forwards `identity_ids`; the route `args` array declares it.
- **Filter divergence decided here.** `/suggestions` filters to `user_confirmed` clusters whose label is non-null and does not start with `cluster-`; `/identities/{id}/suggestions` only requires `cluster.label` truthy. The batch path is therefore **stricter**: cards targeting a labeled-but-unconfirmed cluster show a prompt today and would stop. The plan adopts the stricter semantics deliberately — an unconfirmed cluster is not a trustworthy thing to ask "Is this X?" about — and pins both filters with a test.

Proof:

- API: `top_k` bounds count; `identity_ids` returns subset; over-limit rejected.
- API: `min_confidence` **and** `identity_ids` together — the regression guard for the callable-binding path.
- API: both endpoints' cluster filters pinned against one fixture.

### Slice 3b: Client — one batched call

**Goal**: One suggestions request per workbench render, for exactly the cards that will render a prompt.

Changes:

- `IdentityClusterList` derives the batch id set using **the same predicate as the render gate** — `!cluster.label && anchorIdentityId && canMutate` (`IdentityClusterItem`), where `canMutate = !isLabelOnly` and `isLabelOnly = dataSource === DATA_SOURCE.BACKEND_PROXY`. Consequences the implementation must honor: in label-only mode **no prompt renders, so the batch fetches nothing**; and `anchorIdentityId` is `representative?.identity_id`, currently derived inside `IdentityClusterItem` — the list must derive it from the same grouped cluster data (`groupIdentitiesByClusters`) rather than duplicating the rule.
- `useInlineSuggestionBatch` issues the single call, sending an explicit **`limit` ≥ the id count** (never relying on the server's `default=50`), and treats `rows.length === limit` as **suspected truncation** — surfaced, not silently accepted ([API-01]).
- It maps the Python `SuggestionResponse` (`rep_similarity`, `cluster_label`, `cluster_identity_count`) onto the prompt's props, which today arrive as the TS `ClusterSuggestion` type (`js/admin/api/recognition/types/cluster.ts` — `label`, `similarity`, `identity_count`; the Python-side model is `ClusterSuggestionMatch`). The shapes are **not** interchangeable. Null rule: `cluster_label`/`cluster_identity_count` are nullable on `SuggestionResponse` but required on the prompt — drop rows with a null label (defence in depth behind the server filter) and default the count to 0, mirroring the per-card path.
- **Two hats** ([REF-05]): this slice moves `InlineSuggestionPrompt` to presentational *and* introduces batched fetching. They land as two commits — the structural move first, behavior unchanged, then the batch — so a reviewer can see each independently.
- Top match per identity selected by `rep_similarity` descending.
- `InlineSuggestionPrompt` becomes presentational, match by prop; the per-card `useQuery` and the false `// Only fetch top 1` comment both go.

Proof:

- Component: N unlabeled cards → exactly one fetch; label-only mode → zero fetches.
- **Component: 60 unlabeled cards → every card resolves its prompt** — the guard against the `limit=50` truncation that "one request for N cards" would otherwise hide.
- Unit: the `SuggestionResponse` → prompt-props mapping, incl. null handling and top-match selection.
- Manual: network panel shows one suggestions request.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded frontend/PHP/backend rules and the proxy's retry/overload behavior before editing.
- [ ] Recorded boundary ownership for `top_k` and `identity_ids`.

### Checklist for Slice 1: Typed HTTPError + one retry policy

- [ ] `HTTPError` with `status` + delta-seconds `retryAfterSeconds`; `fetchApi` throws it.
- [ ] Single QueryClient predicate: transport + 429/503-with-`Retry-After`; no other 4xx; no second 5xx layer.
- [ ] All four private policies deleted (three in `useRecognitionHooks.ts`, one in `useDescribeRunProgress.ts`); 404 guards migrated to `error.status === 404`.
- [ ] `useMediaIdentities`'s `retry: false` retained with its rationale recorded in code, not left as a silent divergence.
- [ ] Characterization tests for current 404 behavior green before the migration.
- [ ] Unit tests: 429 / 503+header / 503-bare / 403 / 404 / malformed header; each watched failing once.

### Checklist for Slice 2: Shared cooldown gate

- [ ] `recognitionCooldown` module; single-source state values; `isCoolingDown()` computes from `expiresAt`, never a cached flag ([REF-09]).
- [ ] Exactly the six gated pollers gate on it; `useSyncHealth` and `useSyncStatus` untouched.
- [ ] Cooldown state is observable ([RES-15]/[OBS-05]) and its frozen surfaces are designed + announced ([RLSE-04]/[A11Y-21]).
- [ ] Fake-timer tests: suspend, resume, sync-health unaffected, no timer leak.

### Checklist for Slice 3a: Server — `top_k` + `identity_ids`

- [ ] `top_k` honored and clamped on `list_suggestions`.
- [ ] `identity_ids` threaded router → service → repository, bounded by `max_page_size`, over-limit rejected.
- [ ] `identity_ids` bound into the `_collect_min_confidence_page` callable.
- [ ] Cluster enrichment batched.
- [ ] `get_pending_suggestions` forwards `identity_ids`; route `args` declares it.
- [ ] Tests: `min_confidence` + `identity_ids` together; both endpoints' cluster filters pinned.

### Checklist for Slice 3b: Client — one batched call

- [ ] `IdentityClusterList` derives the id set with the render predicate; label-only mode fetches nothing.
- [ ] Batch sends an explicit `limit` ≥ id count; a full page is treated as suspected truncation.
- [ ] Response mapping implemented and unit-tested, incl. null rule and top-match selection.
- [ ] `InlineSuggestionPrompt` presentational by prop; stale comment removed. Structural move and batch land as separate commits ([REF-05]).
- [ ] Component tests: one request for N cards; **60 cards all resolve**.

## Review Readiness

- [ ] Every boundary change (`top_k`, `identity_ids`) has matching contract/type/test evidence.
- [ ] The retry budget across proxy and client is stated and tested, not implicit.
- [ ] Cooldown membership is justified per query, not assumed from URL shape.
- [ ] Handoff decision records the change, verification, and contract implications.

## Stretch Goals

- [ ] Emit a lightweight client metric on cooldown entry/exit ([OBS-01]) if it costs no new transport.

## Success Criteria

- [ ] With the dev recognition service rate-limiting, the console shows zero repeated-429 loops; gated pollers cool down and resume.
- [ ] One predicate governs every query's retry behavior, with exactly one documented exception: `useMediaIdentities`'s deliberate `retry: false`.
- [ ] A 503-with-`Retry-After` (breaker open) is waited out, not retried into.
- [ ] The sync-health banner keeps updating at 15s throughout a cooldown.
- [ ] A cooldown is visible and announced wherever it freezes a progress surface — no silent hang.
- [ ] A workbench with N unlabeled cards issues one suggestions request; label-only mode issues none.
- [ ] **A workbench with more than 50 unlabeled cards resolves a prompt for every card** — the batch never silently truncates.
- [ ] `top_k` is honored and clamped by the server, and `identity_ids` filters on every code path including `min_confidence` — no ignored-param contract lie remains.
