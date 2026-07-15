# UXP-2. Network Discipline: 429 Backoff + Suggestion Fan-out

> **Metadata**
>
> - **Date**: 2026-07-15 04:10 EST
> - **Author**: claude-opus-4-8
> - **Project**: prototype-wp-alt-context (admin SPA + PHP proxy) · prototype-description-service (recognition)
> - **Task ID**: `UXP-2`
> - **Target Branch**: `feature/uxp-2`
> - **Review Coverage Target**: 2

---

## Objective

Stop the 429 storm at one seam: `fetchApi` gains a typed error, one shared retry policy stops retrying 4xx and honors `Retry-After`, a shared cooldown quiets the hot pollers, and the per-card suggestion fan-out collapses into one bounded call.

## Intake

- **Scope one-pager**: `docs/scopes/uxp-ux-pass-decomposition.md` (§ UXP-2)
- **Source assessment**: `docs/assessments/current/ux-ui-pass-assessment-2026-07-15.md` (**UXA-01** only)
- **Key intake decisions**: UXP-1 `claude_uxp1_scope_intake_v1`; scope split recorded as `claude_planning_review_uxp2_fail_v1` (planning-review verdict) and the operator's decision to ship the storm fix first.
- **Not-Doing**:
  - **Honest service status / heartbeat (UXA-02) → moved to its own task.** The original UXP-2 carried both UXA-01 and UXA-02. Planning review produced six independent design blockers against the heartbeat alone (probe outcome modelling, `/health/detailed` 200-while-unhealthy, WP-cron cadence vs freshness TTL, cron ownership/registration, breaker-state write-gating consumers, probe throttling). That work needs its own scope pass; bundling it here would gate a self-contained storm fix behind an unresolved design.
  - Server-side rate-limit redesign (E20-7/E20-11), SSE migration of job polling, outbox/dispatcher retry changes.

## Problem Statement

Three defects compound into a 429 storm. Each was resolved against the tree this session.

**1. The fetch seam erases the error.** `fetchApi` (`js/admin/utils/http.ts:45-47`) throws a bare `Error` with the status interpolated into a message string. Status code and `Retry-After` survive only as prose. Downstream code already pays for this: three pollers sniff `error.message.includes('404')` to detect a 404 (`useRecognitionHooks.ts:58,82,96`).

**2. The retry policy retries everything — and three hot pollers ignore it anyway.** The QueryClient (`js/admin/App.tsx:15-23`) sets `retry: 1` with exponential `retryDelay` for all queries: every 4xx is retried once and `Retry-After` is ignored ([RES-06] / [API-08]). Meanwhile `useScanStatus` (`useRecognitionHooks.ts:52-64`), `useMultiScanStatus` (`:72-88`) and `useBatchRunStatus` (`:90-102`) each set a **local** `retry` that overrides the default entirely, retrying `failureCount < 3` on everything including 429 — and these are the 1.5s pollers.

**3. The suggestion fan-out is N+1 twice over.** `InlineSuggestionPrompt` (`InlineSuggestionPrompt.tsx:39-44`) runs its own `useQuery` per card, rendered once per unlabeled cluster in `IdentityClusterItem.tsx:332-339` — N unlabeled cards produce N parallel GETs. The server endpoint `list_suggestions` (`suggestions.py:103-141`) **has no `top_k` parameter at all**: the client's `top_k=1` ("Only fetch top 1", `InlineSuggestionPrompt.tsx:41`) is dropped by FastAPI, every match is returned, and each is enriched with a separate `cluster_repo.get_by_id` (`:126`). [RES-12] nested inside itself, plus a client comment documenting behavior the server never implemented.

**Poller inventory** (corrected — there are six queries, not four):

| Query | Cadence | Notes |
| --- | --- | --- |
| `useScanStatus` | 1.5s | `getJobRefetchInterval` (`:32-36`), only while running/pending; local `retry` override |
| `useMultiScanStatus` | 1.5s | same interval fn, one query per job id; local `retry` override |
| `useBatchRunStatus` | 1.5s | `getBatchRunRefetchInterval` (`:38-39`); local `retry` override |
| `useMediaIdentities` | 3s | **conditional** — only when `hasPendingClustering` (`useMediaIdentities.ts:31-36`); already `retry: false` (`:26`) and already stops on error |
| `useRecognitionClusters` | 30s | unconditional (`useRecognitionHooks.ts:134-139`) |
| `useSyncHealth` | 15s | unconditional (`useSyncHealth.ts:6-7`) |

## Constraints

- **Greenfield** (CLAUDE.md): no compatibility shims. Change the contract and its consumers in the same slice.
- **The proxy already retries.** `class-abstract-recognition-proxy-controller.php:175` retries 5xx internally up to `max_retries` before returning. Any client-side retry multiplies against that budget; the total attempt count across both layers must be stated, not discovered.
- **Overload arrives as 503, not 429.** `backend_overloaded_response` (`:292-305`) returns **503 + `Retry-After`**, and `normalize_response_headers` (`:374-380`) forwards `retry-after` from upstream. A client that only special-cases 429 will backoff-retry a 503 that means "the breaker is open, stop asking".
- **`Retry-After` is delta-seconds here.** PHP `parse_retry_after` (`class-settings-controller.php:505-521`) explicitly rejects HTTP-date, documenting that delta-seconds is what the recognition service's rate limiter emits.
- Status values centralize as `as const` / backed enums (sr-007).

## Workflow Principles

- **One seam per concern.** Error typing at `fetchApi`; retry policy at the QueryClient; cooldown in one shared gate. No per-hook retry special-casing — and this slice *removes* the three that exist rather than merely asserting the principle.
- **Bound every collection** ([API-01]). A batch call takes an explicit, clamped id list; it does not page-and-hope.
- **Name the layer that owns the budget.** Retry lives in the proxy or the client, with a stated total, never implicitly in both.

## Terminology

- **Cooldown**: a shared client-side window, opened by a 429 (or 503-with-`Retry-After`) from the recognition route prefix, during which hot pollers suspend refetching.
- **Recognition route prefix**: `acx/v1/recognition/*`. The browser never contacts the recognition host directly — every poller calls same-origin WordPress REST routes that proxy to it.

## Current State Analysis

**Works today:** `createRecognitionTimeoutSignal(2_000)` bounds recognition reads ([RES-02] satisfied at that seam); the proxy's breaker trips deterministically under a lock-guarded counter (`:443-503`); `useMediaIdentities` already declines to retry and already stops polling on error — it is the one poller that behaves.

**Broken or drifting:** `fetchApi` erases status; the QueryClient retries 4xx; three 1.5s pollers override the policy and sniff error strings; `top_k` is a no-op the client believes in.

**Misleading:** the comment `// Only fetch top 1` asserts a bound the server does not honor.

## Target Outcome

A 429 or an overload-503 from the recognition route prefix puts the hot pollers into a shared cooldown that respects the server's `Retry-After`; no 4xx is retried except 429; and no hook carries a private retry policy. The workbench asks for suggestions once per render, for exactly the identities on screen, and the server honors the bound it advertises.

## Context Loading

- Rules: `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/backend-php-guidelines.md`, `docs/workbay/rules/testing-typescript.md`, `docs/workbay/rules/testing-python.md`
- Heuristics: `heuristics-canon` `engineering.md` ([RES-01], [RES-02], [RES-06], [RES-12], [API-01], [API-08], [API-09], [TEST-06]). Vendored for the lane at `docs/reviews/uxp-2/lexicons/`.
- Handoff/MCP: task ref `UXP-2`; planning findings `UXP-2-PR-*`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `GET /identities/{id}/suggestions` `top_k` | recognition (Python) | param sent by client, **silently ignored** (`suggestions.py:103-141`) | honor `top_k` as a clamped `Query`. **Behavior change** for `useClusterSuggestionsLoader.ts:65` (`top_k=5`), which today receives unbounded matches. | no — greenfield | API test asserting the returned match count is bounded |
| `GET /suggestions` `identity_ids` | recognition (Python) | `limit`/`offset`/`min_confidence` (`suggestions.py:55-77`) | add `identity_ids` filter, max = `security_settings.max_page_size` (default 500), over-limit **rejected** not truncated | no — additive ([API-09]) | API test: ids in → subset out; over-limit → 4xx |
| `acx/v1/recognition/suggestions` proxy | proxy (PHP) | passthrough | forward `identity_ids` | no | PHP proxy test |
| `fetchApi` thrown type | frontend (internal) | `Error` with status in the message | `HTTPError` with `status` | n/a — internal, but **three call sites string-sniff the message** and must migrate in the same slice | unit tests on the 404 path |

## Proposed Solution

Four slices. Slice 1 makes the error honest and consolidates the retry policy — including deleting the three local overrides, because a shared policy that three of the hottest pollers ignore is not a policy. Slice 2 adds the cooldown. Slice 3 splits server from client, because `top_k` and `identity_ids` are independently shippable contract changes and the component restructure is not.

**Retry budget, stated.** The proxy retries 5xx up to `max_retries` internally (`:175`). The client therefore does **not** add a second 5xx retry layer for proxied recognition routes: by the time the browser sees a 5xx, the proxy has already exhausted its budget, and retrying again is the [RES-06] amplification this task exists to stop. The client retries only on transport-level failure (no response at all) and on 429/503-with-`Retry-After`, which are explicit "ask again later" instructions rather than failures.

**Cooldown scope: the recognition route prefix.** Every poller calls same-origin `acx/v1/recognition/*`; the browser never sees the recognition host, so "per-host" is not observable from the client and there is exactly one recognition host per site anyway (`RecognitionCircuitKeys::for_base_url`). The cooldown keys on the route prefix, which `HTTPError.endpoint` does carry. Rejected: per-endpoint-family scoping — a 429 from one recognition route is evidence about the shared upstream, and letting the other pollers keep hammering it is the storm.

**`Retry-After` parsing.** Delta-seconds is the contract (the PHP parser rejects HTTP-date by design, documenting that the service emits delta-seconds). The TS parser accepts delta-seconds; HTTP-date is handled defensively for intermediaries but is explicitly out-of-contract, and a malformed value falls back to bounded backoff rather than producing `NaN`.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| frontend | `js/admin/utils/http.ts` | Add `HTTPError {status, retryAfterSeconds, endpoint, bodyPreview}`; `fetchApi` throws it |
| frontend | `js/admin/App.tsx` | One `retry`/`retryDelay` predicate: transport + 429/503-with-`Retry-After` only; never other 4xx; no second 5xx layer |
| frontend | `js/admin/hooks/useRecognitionHooks.ts` | **Delete** local `retry` in `useScanStatus:57-62`, `useMultiScanStatus:81-86`, `useBatchRunStatus:95-100`; replace `error.message.includes('404')` with `error.status === 404`; gate `refetchInterval` on the cooldown |
| frontend | `js/admin/utils/recognitionCooldown.ts` (new) | Route-prefix-scoped cooldown gate + subscription |
| frontend | `js/admin/hooks/useMediaIdentities.ts` | Gate `refetchInterval` on the cooldown (already `retry: false` — leave it) |
| frontend | `js/admin/hooks/useSyncHealth.ts` | Cooldown **floor** (30s), never suspended |
| frontend | `identity-clusters/IdentityClusterList.tsx:35-72` | Owns the batch: collects visible unlabeled identity ids, one call |
| frontend | `identity-clusters/useInlineSuggestionBatch.ts` (new) | The single bounded list call + response mapping |
| frontend | `InlineSuggestionPrompt.tsx` | Presentational; match arrives **by prop**; per-card `useQuery` removed |
| frontend | `js/admin/api/recognition/identityQueriesApi.ts` | Batch fetch fn; `top_k` now a real bound |
| backend | `recognition/interface_adapters/http/routers/suggestions.py` | Honor `top_k` on `list_suggestions`; add `identity_ids` to `list_pending_suggestions`; batch cluster enrichment |
| backend | `recognition/application/suggestions/service.py:320` | `SuggestionService.list_pending` gains `identity_ids` |
| backend | `recognition/infrastructure/repositories/suggestion_repository.py:191` | `list_pending_with_details` gains `identity_ids`; SQL filter |
| php | `src/api/class-suggestions-controller.php:194` | Forward `identity_ids` |
| tests | TS/PHP/Python suites | Per slice, below |

## Related Files

| File | Note |
| --- | --- |
| `class-abstract-recognition-proxy-controller.php:175,292-305,374-380` | The proxy's own retry budget, the overload-503, and `Retry-After` forwarding. Not modified. |
| `useClusterSuggestionsLoader.ts:63-68` | The `top_k=5` caller whose live behavior changes when `top_k` becomes real |
| `suggestion_repository.py:223-226` | `/suggestions` filters to `user_confirmed` clusters with non-`cluster-` labels **at query time** — a stricter filter than the per-card path applies |
| `class-settings-controller.php:505-521` | `parse_retry_after`: delta-seconds only, by design |

## Verification Strategy

- Deterministic tests:
  - `npm --prefix apps/prototype-wp-alt-context test`
  - `composer --working-dir=apps/prototype-wp-alt-context test`
  - `make test` (recognition suite, marker-filtered)
- Contract/fixture verification:
  - API test: `top_k` bounds the returned match count (including the `top_k=5` caller's changed behavior)
  - API test: `identity_ids` returns the matching subset; over-limit list rejected
  - API test: the batch path's filter divergence is asserted, not assumed (below)
- Runtime-parity:
  - `make check-remote` for the committed HEAD
- Manual verification (**dev recognition only** — never the prod/demo host):
  - Dev service rate-limiting → console shows zero repeated-429 loops; pollers cool down and resume.
  - Workbench with N unlabeled cards → network panel shows one suggestions request.

## Slice Delivery

### Slice 1: Typed HTTPError + one retry policy

**Goal**: One retry policy, obeyed by every query, that never retries a 4xx except an explicit "ask again later".

Changes:

- `HTTPError` in `http.ts` carrying `status`, `retryAfterSeconds` (delta-seconds; HTTP-date defensive; malformed → `undefined`, never `NaN`), `endpoint`, `bodyPreview`.
- QueryClient predicate: retry on transport failure and on 429/503-with-`Retry-After` (honoring the header, bounded attempts); never retry other 4xx; **no second 5xx retry layer** — the proxy owns that budget.
- Delete the three local `retry` overrides; migrate their 404 guard from `error.message.includes('404')` to `error.status === 404` ([TEST-03] — this is a characterization-first change: the existing 404 behavior is the contract).
- Poll queries are GETs, so retry is idempotent by construction ([RES-01] — noted, not a risk).

Proof:

- Unit: 429 + `Retry-After: 5` → one retry at ~5s; 503 + `Retry-After` → same; 503 without the header → no retry; 403 → no retry; 404 via `error.status` → no retry (characterization test written against the *current* behavior first, then re-run against `HTTPError`); malformed `Retry-After` → bounded backoff, no `NaN`.
- Each test watched failing once ([TEST-06]).

### Slice 2: Shared cooldown gate

**Goal**: One "ask again later" from the recognition prefix quiets the hot pollers — without blinding the status surface.

Changes:

- `recognitionCooldown`: `openCooldown(seconds)`, `isCoolingDown()`, subscribe/notify; scoped to the `acx/v1/recognition/*` prefix via `HTTPError.endpoint`; single source of truth (sr-007).
- QueryClient error path opens the cooldown on 429/503-with-`Retry-After` from that prefix.
- The three job pollers (1.5s), media identities (3s), clusters (30s) suspend while cooling; resume on expiry.
- Sync health (15s) is **never suspended** — it drops to a 30s floor, so the surface an operator reads during a storm keeps updating.

Proof:

- Unit with fake timers: one 429 suspends the data pollers; sync health continues at the floor; expiry resumes; no timer leak on unmount.
- Manual: rate-limited dev service → no repeated-429 loop.

### Slice 3a: Server — honor `top_k`, add `identity_ids`

**Goal**: The server honors the bound it advertises and can answer for many identities in one call.

Changes:

- `top_k` becomes a real clamped `Query` on `list_suggestions`.
- `identity_ids` filter added down the stack — router (`suggestions.py:55-77`) → `SuggestionService.list_pending` (`service.py:320`) → `SqlAlchemySuggestionRepository.list_pending_with_details` (`suggestion_repository.py:191`), bounded by `security_settings.max_page_size`, over-limit rejected ([API-01]).
- Batch the per-suggestion `cluster_repo.get_by_id` enrichment (`suggestions.py:126`) into one lookup ([RES-12]).
- PHP proxy forwards `identity_ids` (`class-suggestions-controller.php:194`).
- **Filter divergence is decided here, not discovered in slice 3b.** `/suggestions` filters to `user_confirmed` clusters whose label is non-null and does not start with `cluster-` (`suggestion_repository.py:223-226`); `/identities/{id}/suggestions` only requires `cluster.label` truthy (`suggestions.py:128`). The batch path is therefore **stricter**: cards whose suggestion targets a labeled-but-unconfirmed cluster show a prompt today and would stop. Slice 3a adds a test pinning both endpoints' filters against the same fixture so the divergence is explicit, and the plan adopts the stricter `/suggestions` semantics as correct (an unconfirmed cluster is not a trustworthy thing to ask "Is this X?" about).

Proof:

- API tests: `top_k` bounds count; `identity_ids` returns subset; over-limit rejected.
- API test: both endpoints' cluster filters pinned against one fixture, documenting the divergence.

### Slice 3b: Client — one batched call

**Goal**: One suggestions request per workbench render.

Changes:

- `IdentityClusterList` (`IdentityClusterList.tsx:35-72`) collects the visible unlabeled identity ids and calls `useInlineSuggestionBatch` once.
- The hook maps `SuggestionResponse` (`responses.py:179` — `rep_similarity`, `cluster_label`, `cluster_identity_count`) onto what the prompt needs, which today arrives as `ClusterSuggestionMatch` (`responses.py:264-271` — `label`, `similarity`, `identity_count`). The mapping is explicit and tested; the shapes are **not** interchangeable.
- `InlineSuggestionPrompt` becomes presentational, receiving its match by prop; the per-card `useQuery` and the false `// Only fetch top 1` comment both go.

Proof:

- Component test: N unlabeled cards → exactly one fetch.
- Unit: the `SuggestionResponse` → prompt-props mapping, including the top-match-by-similarity selection.
- Manual: network panel shows one suggestions request.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded frontend/PHP/backend rules and the proxy's retry/overload behavior before editing.
- [ ] Recorded boundary ownership for `top_k` and `identity_ids`.

### Checklist for Slice 1: Typed HTTPError + one retry policy

- [ ] `HTTPError` with `status` + delta-seconds `retryAfterSeconds`; `fetchApi` throws it.
- [ ] Single QueryClient predicate: transport + 429/503-with-`Retry-After`; no other 4xx; no second 5xx layer.
- [ ] Three local `retry` overrides deleted; 404 guard migrated to `error.status === 404`.
- [ ] Characterization test for the current 404 behavior written and passing before the migration.
- [ ] Unit tests for 429 / 503+header / 503-bare / 403 / 404 / malformed header; each watched failing once.

### Checklist for Slice 2: Shared cooldown gate

- [ ] `recognitionCooldown` scoped to the `acx/v1/recognition/*` prefix; single-source state values.
- [ ] Job pollers, media identities, clusters suspend on cooldown; sync health floors at 30s and never suspends.
- [ ] Fake-timer tests: suspend, floor, resume, no timer leak.

### Checklist for Slice 3a: Server — `top_k` + `identity_ids`

- [ ] `top_k` honored and clamped on `list_suggestions`.
- [ ] `identity_ids` threaded router → service → repository, bounded by `max_page_size`, over-limit rejected.
- [ ] Cluster enrichment batched.
- [ ] PHP proxy forwards `identity_ids`.
- [ ] Test pinning both endpoints' cluster filters against one fixture.

### Checklist for Slice 3b: Client — one batched call

- [ ] `IdentityClusterList` owns the batch call.
- [ ] Response mapping implemented and unit-tested.
- [ ] `InlineSuggestionPrompt` presentational by prop; stale comment removed.
- [ ] Component test: one request for N cards.

## Review Readiness

- [ ] Every boundary change (`top_k`, `identity_ids`) has matching contract/type/test evidence.
- [ ] The retry budget across proxy and client is stated and tested, not implicit.
- [ ] Handoff decision records the change, verification, and contract implications.

## Stretch Goals

- [ ] Emit a lightweight client metric on cooldown entry/exit ([OBS-01]) if it costs no new transport.

## Success Criteria

- [ ] With the dev recognition service rate-limiting, the console shows zero repeated-429 loops; pollers cool down and resume.
- [ ] No query in the admin carries a private retry policy; one predicate governs all of them.
- [ ] A 503-with-`Retry-After` (breaker open) is waited out, not retried into.
- [ ] A workbench with N unlabeled cards issues one suggestions request.
- [ ] `top_k` is honored and clamped by the server — no ignored-param contract lie remains.
