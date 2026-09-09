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
  - **Honest service status / heartbeat (UXA-02) → its own task.** The original UXP-2 carried UXA-01 and UXA-02; planning review produced six independent design blockers against the heartbeat alone. The successor plan is `docs/tasks/uxp/UXA-02-honest-service-status-task-plan.md`. It carries the write-gate, full `ProbeOutcome` (11 constants, not a boolean and not a six-way collapse), ordered-predicate, `/health/detailed` body-status, read-time freshness, LifeCycleManager cron, named-lock throttle, exhaustive banner/dashboard, `base_url` keying, pairing-exclusion, and rg-016 constraints as binding inputs (handoff IDs UXP-2-PR-01..06,12,13,14,16,17).
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
| `useExportJobStatus` | 2s (until `completed`/`failed`) | yes — `RetentionController::get_export_job_status` `proxy_request`s `/retention/export/{id}/status` upstream (not a local table) | **yes** — 7th gated poller; missed by the slice-2 six-poller roster, gated by the slice-2 review fix (mirrors `useDescribeRunProgress`) |
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
- Heuristics: `heuristics-canon` `engineering.md` ([RES-01], [RES-02], [RES-05], [RES-06], [RES-12], [RES-15], [API-01], [API-08], [API-09], [API-10], [OBS-05], [REF-05], [REF-09], [RLSE-04], [TEST-03], [TEST-06]) and `accessibility.md` ([A11Y-21], [A11Y-24]). Vendored at `docs/reviews/uxp-2/lexicons/` — every ID above was checked to exist there before citation ([AGT-02]: a missing anchor is a finding, not a license to improvise). The local `docs/workbay/rules/engineering-heuristics.md` is byte-identical to canon as of 2026-07-15, but it is gitignored, so that parity is incidental — treat canon-via-`gh` as the source of record.
- Handoff/MCP: task ref `UXP-2`; planning findings `UXP-2-PR-*`, `UXP-2-PR2-*`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `GET /identities/{id}/suggestions` `top_k` | recognition (Python) | param sent by client, **silently ignored** | honor as a clamped `Query`. Enforcing an ignored param is a **breaking change** ([API-09]: changed defaults count as breaking — Hyrum's Law), not a tightening — and the blast radius is **every caller of the route**, not just `useClusterSuggestionsLoader`: the PHP proxy *defaults* `top_k` to 5 when the client omits it. | no — greenfield, but the change must be *reasoned*, not waved through | API test pinning the new bound |
| `GET /identities/suggestions` (**new**) | recognition (Python) | does not exist | batch per-identity top-k, **keyed by identity_id**. `identity_ids` = comma-joined scalar, max **100** (URL-budget-derived, not `max_page_size`), over-limit **rejected**; `top_k` clamped. Row count `≤ len(ids) × top_k` **by construction**. | no — purely additive ([API-09]) | API tests: subset keyed by id; over-limit rejected; **60-id fixture exercising multi-suggestion, unlabeled-first, and auto-label identities** |
| `acx/v1/recognition/identities/suggestions` proxy (**new**) | proxy (PHP) | does not exist | new `SuggestionsController` route + method forwarding `identity_ids` **as an unchanged scalar** + `top_k`; route `args` declares a string param | no | PHP proxy test: 60 ids survive the hop intact |
| `GET /identities/{id}/suggestions` `threshold` | recognition (Python) | proxy sends `threshold` (default `0.6`); **the route has no such param — it accepts `min_confidence`** | **not fixed here.** A second ignored param, same defect class as `top_k`, found while verifying it. Honouring it would start hiding sub-0.6 suggestions that display today — a user-visible change, not network discipline. | n/a | recorded as a follow-up finding, deliberately out of scope |
| `fetchApi` thrown type | frontend (internal) | `Error` with status in the message | `HTTPError` with `status` | n/a — but **four call sites string-sniff the message** and must migrate in the same slice | unit tests on the 404 path |

## Proposed Solution

Four slices. Slice 1 makes the error honest and consolidates all four retry policies into one. Slice 2 adds the cooldown over an explicit membership set. Slice 3 splits server from client, because `top_k` and `identity_ids` are independently shippable contract changes and the component restructure is not.

**Retry budget, stated.** The proxy retries 5xx internally up to `max_retries`. The client therefore adds **no second 5xx retry layer**: by the time the browser sees a 5xx, the proxy has exhausted its budget, and retrying again is the [RES-06] amplification this task exists to stop. The client retries only on transport failure (no response at all) and on 429/503-with-`Retry-After` — explicit "ask again later" instructions, not failures.

**Cooldown trigger.** `fetchApi` throws `HTTPError`; the QueryClient error path opens the cooldown on 429 or 503-with-`Retry-After`. No URL predicate: WordPress does not rate-limit these admin routes, so such a response on an `acx` route originates upstream. A false positive (some intermediary emitting 429) costs one bounded cooldown window and is benign — stated here so the assumption is reviewable rather than implicit.

**Cooldown membership** is the explicit table above, keyed on whether the query reaches recognition. `useSyncHealth` is excluded because it provably does not.

**The cooldown is a second breaker — name it as one** ([RES-15]: circuit-break integration points; stop calling what's already failing). The proxy already owns a server-side breaker; `recognitionCooldown` is a *client-side* one that trips on an upstream signal, suspends calls, and half-opens on expiry. Two consequences follow and are not optional: its state must be **observable** (RES-15's "expose breaker state to operations", and [OBS-05]: a new breaker without metrics), and its interaction with the proxy's breaker must be bounded the same way the retry budget is — a proxy 503-with-`Retry-After` (breaker open) and a client cooldown are the same signal at two layers, so the client waits, it does not re-probe.

**The batch goes on a new per-identity endpoint, not on `/suggestions`. This is a corrected design; the earlier one was wrong.**

An earlier revision batched through `GET /suggestions` with an `identity_ids` filter, bounding the request by "`limit` ≥ the id count". **That bound is the wrong quantity, and the approach is unfixable by tuning.** `/suggestions` paginates over *suggestion rows*, not identities: `list_pending_with_details` does `select(SuggestionModel) … .offset(offset).limit(limit)` with no per-identity grouping, and an identity has **many** pending suggestions by design — `resolve_for_identity_exclusive` exists precisely to accept "one and reject the rest". So 60 cards × ~3 pending suggestions ≈ 180 rows; `limit=60` returns 60 rows ordered by *global* `confidence_score desc`, which might cover 20 identities and leave 40 cards silently prompt-less. The ceiling is structural, not a tuning error: `validate_paging` rejects `limit > max_page_size` and `max_page_size` is **500** — the same ceiling as the id list — so 500 ids can yield >500 rows and **no legal `limit` can fetch them all in one call**.

The root mistake was the seam, and [API-10] names it: *interface is its own artifact — translate internal models at the boundary so storage refactors never break clients*. `/suggestions` returns `SuggestionResponse`, a row shape that mirrors the suggestions table. The workbench's question is not "give me a page of suggestion rows"; it is **"what is the top suggestion for each of these identities?"** Batching on a row-paginated storage surface forced the identity/row mismatch, the shape mapping, and the filter divergence — all three dissolve once the endpoint expresses the domain question.

So: a **new `GET /identities/suggestions`** returning per-identity top-k keyed by identity id, in the existing `ClusterSuggestionMatch` element shape the prompt already consumes (a **new** envelope schema — the existing `IdentitySuggestionsResponse` is flat `{matches: [...]}` for a single identity and is not keyed). Row count is `≤ len(ids) × top_k` **by construction** ([API-01]/[RES-05]: bounded by the thing the caller actually asked for), so there is no global page cut to truncate against and no truncation-detection heuristic to get wrong. Purely additive ([API-09]).

**Filter parity — literally, not approximately.** The batch must apply the per-card route's filter *exactly*: pending suggestions whose cluster has a **truthy label** (`suggestions.py`: `if cluster and cluster.label`), plus `tenant_id` scoping. That is the whole filter. It is **not** `list_pending_with_details`'s stricter set (`user_confirmed IS TRUE` + `label NOT LIKE 'cluster-%'`) — that belongs to the abandoned `/suggestions` seam, and applying it here would silently drop any card whose top suggestion targets a labeled-but-unconfirmed cluster: PR4-01's failure mode wearing a different hat. This slice is network discipline; it must not change which prompts a user sees.

Consequence, stated so nobody "fixes" it mid-slice: auto-generated `cluster-1234` labels **pass** the per-card filter today, so they must pass the batch filter too. `_is_meaningful_label` exists in that same router but is not used by the per-card route, which arguably contradicts its own docstring ("unlabeled cluster suggestions are not actionable"). That is a real latent defect — and a **behavior change**, therefore out of scope here. Recorded as a follow-up, not smuggled in.

**Filter before rank, inside the window.** The per-card route filters to labeled clusters *first*, then sorts by similarity. The batch must do the same **inside** the windowed subquery. If `ROW_NUMBER` ranks the unfiltered set and the label filter sits in the outer query, an identity whose #1 suggestion targets an unlabeled cluster and whose #2 is labeled gets `rn=1` → filtered out → **no prompt at `top_k=1`**, while the per-card route happily shows #2. Same silent-drop symptom, third mechanism.

Per-identity ranking uses `ROW_NUMBER() OVER (PARTITION BY identity_id ORDER BY representative_similarity DESC, created_at DESC) <= top_k`. The `created_at DESC` tie-break is not decoration: the per-card route sorts with Python's **stable** `sort()` over a `created_at DESC` list, so ties there resolve by recency. Ranking on similarity alone would make the parity test flake on tied similarities.

**Not `DISTINCT ON`** — and the reason is worse than "not portable". SQLAlchemy does not error on SQLite; it **silently drops the `ON` clause** and emits plain `SELECT DISTINCT` (a deprecation warning only). So `DISTINCT ON` would go **green in tests while returning every row per identity**, and behave differently in production. Tests run `sqlite+aiosqlite:///:memory:` (`recognition/tests/conftest.py`); production is Postgres. `ROW_NUMBER` is portable to both and is verified to work under the repo's SQLite (3.50.4; window functions need ≥3.25).

Cluster details are loaded in the same query (`joinedload`), not per row — the per-card route's `cluster_repo.get_by_id`-in-a-loop is the [RES-12] defect this slice exists to remove, and reintroducing it inside the batch would defeat the point.

**`identity_ids` wire format: one comma-joined string, end to end.** This must be pinned, because every naive encoding is broken across the three hops (TS → WP proxy → FastAPI) and one fails *silently*:

- Repeated keys (`?identity_ids=a&identity_ids=b`, the FastAPI-idiomatic `Query(list[str])` form) — PHP's `$_GET` is **last-wins** and collapses them to a single id. 59 of 60 cards silently prompt-less. PR4-01's exact symptom, delivered by the query parser.
- PHP-array syntax (`?identity_ids[]=a&identity_ids[]=b`) — WordPress parses it, but `proxy_request` forwards via `add_query_arg($query, $url)`, whose `build_query` emits `identity_ids[0]=a&identity_ids[1]=b`, which FastAPI binds to nothing → 422 or empty.

So: the client sends **`identity_ids=<uuid>,<uuid>,…`** (a single scalar), the proxy forwards that scalar unchanged (`add_query_arg` handles scalars correctly), and the endpoint takes `identity_ids: str` and splits on `,`. UUIDs contain no commas, so the delimiter is safe. Each id is validated with `validate_entity_id` (→ 400 on garbage), **not** `_coerce_uuid`, which returns `None` and would match nothing silently.

**`identity_ids` bound is 100, derived from the URL budget — not `max_page_size`.** 500 comma-joined UUIDs is ~18 KB of query string; the **WordPress hop** typically fronts nginx (`large_client_header_buffers`, 8 KB) or Apache (`LimitRequestLine`, 8190), so a 500-id request would die as a 414 before FastAPI ever saw it — a bound that cannot be exercised is not a bound. (The recognition hop is Caddy, ~1 MB, and is not the constraint; the WP hop alone sets the ceiling.) 100 ids ≈ 3.7 KB fits with >2× headroom even if the commas percent-encode. Reusing `max_page_size` (a row-paging knob, `RECOGNITION_MAX_PAGE_SIZE`) for an id list would also couple two unrelated limits. The client chunks if a page ever exceeds 100 — `ceil(N/100)` requests is still a coarse interface ([RES-12]), not an N+1.

Over-limit is **rejected**, deliberately deviating from [API-01]'s "clamped client limits" guidance: clamping an id list silently drops identities, which is the same silent-loss failure in yet another costume. Stated so a reviewer can disagree.

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
| backend | `routers/suggestions.py` : `list_identities_suggestions` (**new**) | `GET /identities/suggestions`; clamp `top_k`, bound + reject over-limit `identity_ids`; returns per-identity matches keyed by id |
| backend | `application/suggestions/service.py` : `SuggestionService.list_for_identities` (**new**) | Batch counterpart to `list_for_identity` |
| backend | `infrastructure/repositories/suggestion_repository.py` : `SqlAlchemySuggestionRepository.list_for_identities` (**new**) | One `tenant_id`-scoped query: `ROW_NUMBER() OVER (PARTITION BY identity_id ORDER BY representative_similarity DESC, created_at DESC) <= top_k`, with the **per-card filter applied inside the windowed subquery** — pending + truthy `cluster.label` **only** (no `user_confirmed`, no `cluster-%` exclusion; that stricter set belongs to the abandoned `/suggestions` seam). `joinedload` cluster details, no per-row lookup. |
| backend | `interface_adapters/http/schemas/responses.py` | Response keyed by identity id, reusing `ClusterSuggestionMatch` |
| php | `src/api/class-suggestions-controller.php` : new batch route + method | Forward `identity_ids` as an **unchanged comma-joined scalar** + `top_k`. Route `args` must declare it **`'type' => 'string'`, never `'array'`** — `'array'` triggers `rest_sanitize_array` → `wp_parse_list`, which splits the scalar into a PHP array that `add_query_arg` then emits as `identity_ids%5B0%5D=`, binding nothing on the FastAPI side. Silent, and it is the very failure this format was chosen to avoid. |
| tests | TS/PHP/Python suites | Per slice, below |

## Related Files

| File : symbol | Note |
| --- | --- |
| `class-abstract-recognition-proxy-controller.php` : `backend_overloaded_response`, `normalize_response_headers` | The proxy's retry budget, the overload-503, `Retry-After` forwarding. Not modified. |
| `useClusterSuggestionsLoader.ts` | The `top_k=5` caller whose live behavior changes when `top_k` becomes real |
| `suggestion_repository.py` : `list_pending_with_details` | The row-paginated pending list. **Not the batch seam** (see Proposed Solution) and not modified. Its `user_confirmed` + non-`cluster-` label filter is stricter than the per-card path — the divergence that made it the wrong surface to batch on. |
| `class-suggestions-controller.php` : `get_identity_suggestions` | Forwards `top_k` for the **per-identity** route. Not the `identity_ids` site. |
| `js/admin/hooks/useSyncHealth.ts` | Deliberately untouched — reads local state only |

## Verification Strategy

- Deterministic tests:
  - `npm --prefix apps/prototype-wp-alt-context test`
  - `composer --working-dir=apps/prototype-wp-alt-context test`
  - `make test` (recognition suite, marker-filtered)
- Contract/fixture verification:
  - `top_k` bounds the returned match count (incl. the `top_k=5` caller's changed behavior)
  - batch returns the requested subset keyed by identity id; over-limit id list rejected
  - **60 ids against a fixture where several identities carry ≥2 pending suggestions → every id resolves** (the row-vs-identity regression guard; a one-suggestion-per-identity fixture would pass while broken)
  - batch and per-card routes agree on the same identity (filter parity)
  - the `ROW_NUMBER` query runs under SQLite (tests) and Postgres (prod)
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

### Slice 3a: Server — honor `top_k`, add the batch identity endpoint

**Goal**: The server honors the bound it advertises, and can answer "top suggestion for each of these identities" in one bounded call.

Changes:

- `top_k` becomes a real clamped `Query` on `list_suggestions`. This is a **breaking behavior change for an existing caller**, not a tightening: `useClusterSuggestionsLoader` sends `top_k=5` and today receives unbounded matches ([API-09]: changed defaults count as breaking — Hyrum's Law). Greenfield exempts us from a migration, not from the reasoning. Deliberate deviation from the "clamped" wording here and below: out-of-range `top_k` is **rejected** with 400, never silently clamped, matching `validate_paging`'s reject-not-clamp convention (`MAX_TOP_K` in `validation.py`).
- **New `GET /identities/suggestions`** (`list_identities_suggestions`): takes `identity_ids` (comma-joined scalar, ≤100, over-limit **rejected**, each id via `validate_entity_id`) + clamped `top_k`; returns matches **keyed by identity id**, elements in the existing `ClusterSuggestionMatch` shape under a **new** envelope schema. Response size `≤ len(ids) × top_k` by construction ([API-01]/[RES-05]).
- Repository `list_for_identities`: **one** query, `tenant_id`-scoped, using `ROW_NUMBER() OVER (PARTITION BY identity_id ORDER BY representative_similarity DESC, created_at DESC) <= top_k`, with the **per-card filter applied inside the windowed subquery** (pending + truthy `cluster.label` only — *not* `user_confirmed`, *not* the `cluster-%` exclusion), and `joinedload` for cluster details — no per-row `get_by_id` ([RES-12]).
  - **Verify window-function portability before building on it.** `ROW_NUMBER` under `sqlite+aiosqlite` (tests) and Postgres (prod). `DISTINCT ON` is forbidden: SQLAlchemy silently drops its `ON` clause on SQLite, so it would pass tests green while returning every row per identity.
- PHP proxy: new route + method forwarding `identity_ids` (scalar, unchanged) + `top_k`; route `args` declares a string param.
- **Filter parity is the requirement, and it is literal.** The batch applies the per-card filter exactly, so the two paths agree by construction and no card changes visibility. `cluster-*` labels pass today and must keep passing (see Proposed Solution).
- `/suggestions` and its `min_confidence` path are **untouched** — no `identity_ids`, so no `_collect_min_confidence_page` binding hazard.
- Also batch the per-card route's own `cluster_repo.get_by_id`-in-a-loop enrichment ([RES-12]) — it is the N+1 inside the N that this task named, and leaving it would mean the per-card route stays chatty for `useClusterSuggestionsLoader`.

Proof:

- API: `top_k` bounds count on the per-card route, incl. the changed behavior for every caller of that route.
- API: batch returns the requested subset keyed by id; over-limit id list (>100) rejected.
- **API: 60 ids against a fixture that actually exercises the failure modes** — a one-suggestion-per-identity fixture would green while the design was broken. The fixture must contain:
  - several identities carrying **≥2 pending suggestions** (guards the row-vs-identity bound), and
  - at least one identity whose **highest-similarity suggestion targets an unlabeled cluster and whose second targets a labeled one** (guards filter-before-rank: it must still resolve, matching the per-card route), and
  - at least one identity whose top suggestion targets a `cluster-1234`-style auto-label (guards the deliberate parity decision: it must resolve, not be filtered).
- API: batch and per-card routes return the **same** match for the same identity across that whole fixture (filter parity, pinned).
- API: tied similarities resolve identically on both routes (`created_at DESC` tie-break).
- Wire: a 60-id request survives TS → PHP proxy → FastAPI with all 60 ids arriving (guards the `$_GET` last-wins and `add_query_arg` array-syntax traps).
- Runtime: the `ROW_NUMBER` query executes under both SQLite and Postgres.

### Slice 3b: Client — one batched call

**Goal**: One suggestions request per workbench render, for exactly the cards that will render a prompt.

Changes:

- `IdentityClusterList` derives the batch id set using **the same predicate as the render gate** — `!cluster.label && anchorIdentityId && canMutate` (`IdentityClusterItem`), where `canMutate = !isLabelOnly` and `isLabelOnly = dataSource === DATA_SOURCE.BACKEND_PROXY`. Consequences the implementation must honor: in label-only mode **no prompt renders, so the batch fetches nothing**; and `anchorIdentityId` is `cluster.members[0]?.identity_id`, currently derived inside `IdentityClusterItem` — the list must derive it from the same grouped cluster data (`groupIdentitiesByClusters` produces those `members`) rather than duplicating the rule.
- `useInlineSuggestionBatch` issues the single call to `GET /identities/suggestions` with the id set and `top_k=1`. **No `limit` juggling and no truncation heuristic** — the endpoint is bounded per identity, so completeness is structural rather than something the client must detect.
- Mapping is thin by design: the endpoint already returns the `ClusterSuggestionMatch` shape (`label`, `similarity`, `identity_count`) that the TS `ClusterSuggestion` type (`js/admin/api/recognition/types/cluster.ts`) mirrors and `InlineSuggestionPrompt` already consumes. The client keys by identity id and takes the first match (server-ranked). Choosing the domain-shaped endpoint over the row-shaped one is what collapsed this from a field-by-field remap to an indexing step ([API-10]).
- **Two hats** ([REF-05]): this slice moves `InlineSuggestionPrompt` to presentational *and* introduces batched fetching. They land as two commits — the structural move first, behavior unchanged, then the batch — so a reviewer can see each independently.
- `InlineSuggestionPrompt` becomes presentational, match by prop; the per-card `useQuery` and the false `// Only fetch top 1` comment both go.

Proof:

- Component: N unlabeled cards → exactly one fetch; label-only mode → zero fetches.
- **Component: 60 unlabeled cards, several identities carrying ≥2 pending suggestions → every card resolves its prompt.**
- Unit: keying by identity id and empty-match handling (an identity with no labeled-cluster suggestion renders nothing, as today).
- Manual: network panel shows one suggestions request.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded frontend/PHP/backend rules and the proxy's retry/overload behavior before editing.
- [ ] Recorded boundary ownership for `top_k` and `identity_ids`.

### Checklist for Slice 1: Typed HTTPError + one retry policy

- [ ] `HTTPError` with `status` + delta-seconds `retryAfterSeconds`; `fetchApi` throws it.
- [ ] Single QueryClient predicate: transport + 429/503-with-`Retry-After`; no other 4xx; no second 5xx layer.
- [x] All four private policies deleted (three in `useRecognitionHooks.ts`, one in `useDescribeRunProgress.ts`); 404 guards migrated to `error.status === 404`.
- [ ] `useMediaIdentities`'s `retry: false` retained with its rationale recorded in code, not left as a silent divergence.
- [ ] Characterization tests for current 404 behavior green before the migration.
- [ ] Unit tests: 429 / 503+header / 503-bare / 403 / 404 / malformed header; each watched failing once.

### Checklist for Slice 2: Shared cooldown gate

- [ ] `recognitionCooldown` module; single-source state values; `isCoolingDown()` computes from `expiresAt`, never a cached flag ([REF-09]).
- [ ] Exactly the six gated pollers gate on it; `useSyncHealth` and `useSyncStatus` untouched.
- [ ] Cooldown state is observable ([RES-15]/[OBS-05]) and its frozen surfaces are designed + announced ([RLSE-04]/[A11Y-21]).
- [ ] Fake-timer tests: suspend, resume, sync-health unaffected, no timer leak.

### Checklist for Slice 3a: Server — `top_k` + batch identity endpoint

- [ ] Window-function portability proven under SQLite **and** Postgres before building on it (`ROW_NUMBER`, never `DISTINCT ON` — it silently drops `ON` under SQLite).
- [ ] `top_k` honored and clamped on `list_suggestions`; behavior change covered for every caller (proxy defaults it to 5).
- [ ] `GET /identities/suggestions` added: comma-joined `identity_ids` ≤100 (URL-budget bound), over-limit rejected, ids via `validate_entity_id`; `top_k` clamped; keyed by identity id; new envelope schema.
- [ ] Repository `list_for_identities`: one `tenant_id`-scoped query; `ROW_NUMBER` partitioned by identity, ordered `representative_similarity DESC, created_at DESC`; **per-card filter inside the windowed subquery** (truthy label only — no `user_confirmed`, no `cluster-%` exclusion); `joinedload` details.
- [ ] Per-card route's own `get_by_id`-in-a-loop enrichment batched.
- [ ] PHP proxy route + method forward `identity_ids` as an unchanged scalar + `top_k`; route `args` declares a string param.
- [ ] Tests: parity fixture (multi-suggestion, unlabeled-first, auto-label identities) → batch matches per-card exactly; over-limit rejected; 60 ids survive the wire hop; tie-break parity.

### Checklist for Slice 3b: Client — one batched call

- [ ] `IdentityClusterList` derives the id set with the render predicate; label-only mode fetches nothing.
- [ ] `useInlineSuggestionBatch` calls `GET /identities/suggestions` with `top_k=1`; keys by identity id.
- [ ] `InlineSuggestionPrompt` presentational by prop; stale comment removed. Structural move and batch land as separate commits ([REF-05]).
- [ ] Component tests: one request for N cards; label-only → zero; **60 cards with multi-suggestion identities all resolve**.

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
- [ ] **Every unlabeled card resolves its prompt regardless of how many cards are on screen or how many pending suggestions each identity carries** — the batch cannot silently drop a card, because its bound is per-identity by construction rather than a global page.
- [ ] `top_k` is honored and clamped by the server. (`threshold` on the same route is **also** silently ignored — the proxy sends `threshold`, the route accepts `min_confidence` — and is deliberately left alone here: fixing it would hide sub-0.6 suggestions users see today. Recorded as a follow-up, so the claim is "top_k is fixed", not "no ignored param remains".)
- [ ] No card changes visibility: the batch resolves a prompt for exactly the identities the per-card route would, across the parity fixture.
