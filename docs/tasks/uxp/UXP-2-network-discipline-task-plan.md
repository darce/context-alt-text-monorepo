# UXP-2. Network Discipline: 429 Backoff + Honest Service Status

> **Metadata**
>
> - **Date**: 2026-07-15 03:30 EST
> - **Author**: claude-opus-4-8
> - **Project**: prototype-wp-alt-context (admin SPA + PHP proxy) · prototype-description-service (recognition)
> - **Task ID**: `UXP-2`
> - **Target Branch**: `feature/uxp-2`
> - **Review Coverage Target**: 2

---

## Objective

Stop the 429 storm at one seam: `fetchApi` gains a typed error, the QueryClient stops retrying 4xx and honors `Retry-After`, a shared cooldown pauses hot pollers, and the per-card suggestion fan-out collapses into one bounded call. Make the offline banner reflect *measured* service health via a scheduled authenticated probe, so the banner is honest when the admin is idle.

## Intake

- **Scope one-pager**: `docs/scopes/uxp-ux-pass-decomposition.md` (§ UXP-2)
- **Source assessment**: `docs/assessments/current/ux-ui-pass-assessment-2026-07-15.md` (UXA-01, UXA-02)
- **Key intake decisions**: recorded on UXP-1 as `claude_uxp1_scope_intake_v1` — UXP-net ships first; amend existing epics rather than duplicate.
- **Not-Doing**: server-side rate-limit redesign (E20-7/E20-11), SSE migration of job polling, outbox/dispatcher retry changes.

## Problem Statement

Four defects compound into a 429 storm and a dishonest status banner. Each was resolved against the tree this session.

**1. The fetch seam erases the error.** `fetchApi` (`js/admin/utils/http.ts:45-48`) throws a bare `Error` with the status interpolated into a message string. Status code and `Retry-After` survive only as prose, so no caller can make a structured retry decision without parsing English.

**2. The retry policy retries everything.** The QueryClient (`js/admin/App.tsx:15-23`) sets `retry: 1` with exponential `retryDelay` for *all* queries. Every 4xx is retried once, `Retry-After` is ignored, and a rate-limited service is answered with more traffic. This is the [RES-06] / [API-08] failure exactly: retry without 5xx-gating amplifies the outage.

**3. Four hot pollers have no shared brake.** Job status 1.5s (`js/admin/hooks/useRecognitionHooks.ts:95`), media identities 3s (`js/admin/hooks/useMediaIdentities.ts:31`), clusters 30s (`useRecognitionHooks.ts:138`), sync health 15s (`js/admin/hooks/useSyncHealth.ts:6-7`). All four hit the same recognition host. When it starts rate-limiting, each poller independently keeps its cadence; a 429 on one conveys nothing to the others.

**4. The suggestion fan-out is N+1 twice over.** `InlineSuggestionPrompt` (`InlineSuggestionPrompt.tsx:39-44`) runs its own `useQuery` per card, rendered once per unlabeled cluster in `IdentityClusterItem.tsx:332-339` — N unlabeled cards produce N parallel GETs. Worse, the server endpoint `list_suggestions` (`recognition/interface_adapters/http/routers/suggestions.py:106-147`) **has no `top_k` parameter at all**: the client's `top_k=1` ("Only fetch top 1") is silently dropped by FastAPI, the server returns every match, and enriches each one with a separate `cluster_repo.get_by_id` call. This is [RES-12] (chatty remote interface) nested inside itself, and a client comment that documents behavior the server never implemented.

**5. The banner cannot tell "healthy" from "unknown".** `isSyncOffline` is `health.breaker.state === 'open'` (`degradedModeBannerLogic.ts:15-16`). The breaker transient is only written by `record_proxy_failure` on real proxy traffic (`src/api/class-abstract-recognition-proxy-controller.php:421-436`; 2-failure threshold, 60s TTL), and `SyncHealthController::get_sync_health` reports `closed` whenever that transient is absent (`class-sync-health-controller.php:58-66`). An idle admin makes no proxy calls, so the breaker stays closed and the banner silently claims health while the service is down. [OBS-08] names this precisely: silence is not success — a quiet probe must break loudly, not read as healthy.

## Constraints

- **Greenfield** (CLAUDE.md): no compatibility shims, no dual-shape support. Change the contract and its consumers in the same slice.
- The heartbeat costs **≤1 request per 60s per site**, regardless of how many admins are open or how fast the pollers run.
- `sync/health` is a **read-only handler**: it performs no outbound I/O, so a hung upstream can never delay admin render ([RES-03]).
- The recognition proxy breaker (2 failures / 60s TTL) is the existing circuit for *real traffic*. UXP-2 does not modify, re-tune, or write to it.
- Banner status must not rely on color alone ([UI-02], [A11Y-06]); the existing `!` icon + `role`/`aria-live` pairing in `DegradedModeBanner.tsx:31-41` is load-bearing and must survive.
- `top_k` semantics are a published-API question; a param the server ignores is a contract defect, not a client bug.

## Workflow Principles

- **One seam per concern.** Retry policy lives at the QueryClient; error typing lives at `fetchApi`; cooldown lives in one shared gate. No per-hook retry special-casing.
- **Reuse the probe that exists.** `SettingsController::test_connection` already performs the authenticated `/health/detailed` probe with `Retry-After` parsing (`class-settings-controller.php:193-230`, `440-521`). The heartbeat extracts and reuses that path rather than growing a second probe implementation.
- **Distinct states need distinct signals.** A status the UI cannot independently observe is not a state; it is a synonym.
- **Bound every collection** ([API-01]). A batch call takes an explicit, clamped id list; it does not page-and-hope.
- Status values centralize as `as const` / backed enums (sr-007), not scattered string comparisons.

## Terminology

- **Heartbeat**: a WP-cron scheduled, authenticated probe from WordPress to the recognition service, at most once per 60s per site, writing its result to a transient.
- **Probe state**: the transient the heartbeat writes — `{at, ok, source}`. Independent of the proxy breaker.
- **Idle-unknown**: no probe result fresh enough to make a health claim. Distinct from "healthy" and from "offline".
- **Cooldown**: a shared client-side window, opened by a 429 from the recognition host, during which hot pollers suspend or slow refetching.

## Current State Analysis

**Works today:** the proxy breaker trips deterministically under real traffic (lock-guarded failure counter, `class-abstract-recognition-proxy-controller.php:443-503`); `createRecognitionTimeoutSignal(2_000)` already bounds recognition reads ([RES-02] satisfied at that seam); the banner's a11y pairing (icon + `alert`/`status` role) is correct and deliberate; `degradedModeBannerLogic.ts:5-13` documents why `last_pull.ok` was rejected as an offline signal — that reasoning stays.

**Broken or drifting:** `fetchApi` erases status; the QueryClient retries 4xx; four pollers freewheel; `top_k` is a no-op the client believes in; `breaker.state === 'closed'` conflates "reachable" with "never asked".

**Misleading:** the comment `// Only fetch top 1` (`InlineSuggestionPrompt.tsx:41`) asserts a bound the server does not honor. Any reader budgeting request cost from that line is wrong.

## Target Outcome

A 429 from the recognition host puts every hot poller into a shared cooldown that respects the server's `Retry-After`, and no 4xx is ever retried except 429. The workbench asks for suggestions once per render, for exactly the identities on screen, and the server honors the bound it advertises. The banner distinguishes three honest states — offline (the probe measured a failure), degraded (real proxy traffic is failing), idle-unknown (no fresh probe) — and stopping the dev recognition service flips it offline within ~one heartbeat interval with no job running.

## Context Loading

- Rules: `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/backend-php-guidelines.md`, `docs/workbay/rules/testing-typescript.md`, `docs/workbay/rules/testing-php.md`
- Heuristics: `heuristics-canon` lexicons `engineering.md` ([RES-02], [RES-03], [RES-06], [RES-12], [RES-15], [API-01], [API-08], [API-09], [OBS-01], [OBS-05], [OBS-08], [UI-02], [TEST-04], [TEST-06], [TEST-10]) and `accessibility.md` ([A11Y-06]). Vendored for the lane at `docs/reviews/uxp-2/lexicons/`.
- Contracts: `docs/workbay/contracts/` — sync-health response shape; recognition proxy surface.
- Handoff/MCP: task ref `UXP-2`; UXP-1 intake decision `claude_uxp1_scope_intake_v1`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `acx/v1/recognition/sync/health` | proxy (PHP) → frontend | `breaker: {state: 'open'\|'closed', base_url, opened_at}` (`class-sync-health-controller.php:58-66`) | **additive**: new `probe: {at, ok, source}` block. `breaker` shape unchanged. | no — additive ([API-09]) | PHP controller test + TS type + banner unit tests |
| `GET /identities/{id}/suggestions` `top_k` | recognition (Python) | param sent by client, **silently ignored** by server | honor `top_k` as a clamped `Query` (**behavior change** for the `top_k=5` caller, which today receives unbounded matches) | no — greenfield | API test asserting returned match count is bounded |
| `GET /suggestions` batch filter | recognition (Python) | `limit`/`offset`/`min_confidence` only | add `identity_ids` filter, max = `security_settings.max_page_size`, over-limit **rejected** not truncated | no — additive ([API-09]) | API test: ids in → matching subset out; over-limit → 4xx |
| `acx/v1/recognition/suggestions` proxy | proxy (PHP) | passthrough | forward `identity_ids` | no | PHP proxy test |

## Proposed Solution

Four slices, each landing behavior plus proof, ordered so the client seam is honest before anything leans on it.

**Heartbeat transport — WP-cron, not an inline probe.** A scheduled `acx_recognition_heartbeat` event (custom 60s interval) performs the authenticated probe and writes the probe transient; `sync/health` only *reads* that transient. The rejected alternative was probing inline inside the `sync/health` handler: PHP has no native async, so a cache-miss probe against a *hung* (not refused) upstream would block the handler for the full timeout on a 15s poll — the [RES-03] failure this plan is supposed to prevent. Cron keeps the handler pure-read and bounds cost by construction (one probe per 60s per site regardless of poller count or open admins).

Cron's known weakness — it fires on traffic — is acceptable here precisely because the banner is only *read* when an admin is open, and an open admin polling every 15s is traffic. If cron is disabled or broken entirely, the probe simply goes stale and the banner reports **idle-unknown** rather than inventing health. That failure mode is the [OBS-08] property stated positively: dead instrumentation reads as "unknown", never as "healthy".

**Probe state is independent of the proxy breaker.** The probe writes its own transient rather than the breaker's circuit key. Two reasons, both load-bearing:

1. *The breaker's thresholds are wrong for a probe.* `record_proxy_failure` needs **2** failures to open (`:428`) and its transient TTL is **60s** (`:434`) — equal to the probe cadence. Feeding it a once-per-60s probe would take ~120s to flip offline (not "one heartbeat interval") and would let the transient expire between probes, flapping the banner while the service stayed down.
2. *Collapsing them destroys the distinction.* If the probe writes the breaker, `breaker.state` becomes a delayed echo of `probe.ok` and "offline" and "degraded" stop being independently observable.

Instead the probe declares failure on its own evidence: **2 attempts within one probe run** (short timeout each, [RES-02]) before writing `ok:false`, with a transient TTL of 180s — three times the cadence, so a single missed cron tick cannot flap the state. Worst-case detection is therefore one cadence plus one probe run (~65s), and the Success Criteria say exactly that instead of an unreachable number.

**Banner state × signal.** Each state has exactly one exclusive trigger:

| State | Trigger | Source | Role |
| --- | --- | --- | --- |
| **offline** | `probe.ok === false` | deliberate scheduled probe | `alert` / `assertive` |
| **degraded** | `breaker.state === 'open'` **and** `probe.ok !== false` | incidental real proxy traffic | `status` / `polite` |
| **idle-unknown** | no probe within the freshness window | absence of measurement | `status` / `polite` |
| healthy / advisory | `probe.ok === true`, breaker closed | — | existing warnings path only |

This inverts today's meaning of `isSyncOffline` (currently `breaker.state === 'open'`, `degradedModeBannerLogic.ts:15-16`): breaker-open becomes *degraded*, and *offline* is reserved for measured probe failure. The two remain independently observable because their sources differ — the probe is deliberate and runs when idle; the breaker only ever sees traffic the user's own actions generated. `last_pull.ok` remains a non-signal ([`degradedModeBannerLogic.ts:5-13`](#)).

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| frontend | `js/admin/utils/http.ts` | Add `HTTPError {status, retryAfterSeconds, endpoint, bodyPreview}`; throw it from `fetchApi` |
| frontend | `js/admin/App.tsx` | QueryClient `retry`/`retryDelay` predicate: never retry 4xx except 429; honor `Retry-After`; bounded backoff |
| frontend | `js/admin/utils/recognitionCooldown.ts` (new) | Per-recognition-host 429 cooldown gate + subscription |
| frontend | `useRecognitionHooks.ts`, `useMediaIdentities.ts` | Gate `refetchInterval` on the cooldown (suspend) |
| frontend | `js/admin/hooks/useSyncHealth.ts` | Cooldown **floor** (30s), never suspended |
| frontend | `identity-clusters/IdentityClusterList.tsx` | Owns the batch: collects visible unlabeled identity ids, issues one call |
| frontend | `identity-clusters/useInlineSuggestionBatch.ts` (new) | The single bounded list call |
| frontend | `InlineSuggestionPrompt.tsx` | Presentational; receives its match **by prop**; per-card `useQuery` removed |
| frontend | `js/admin/api/recognition/identityQueriesApi.ts` | Batch fetch fn; `top_k` now a real bound |
| frontend | `degradedModeBannerLogic.ts`, `DegradedModeBanner.tsx` | Three states per the state × signal table |
| frontend | `js/admin/api/recognition/types/sync.ts` | Add `probe` block + `ProbeSource` union |
| php | `src/api/services/class-recognition-probe.php` (new) | Extracted authenticated probe; 2 attempts; writes probe transient |
| php | `src/api/class-recognition-heartbeat.php` (new) | `acx_recognition_heartbeat` cron event + 60s `cron_schedules` interval; (de)registration on activate/deactivate |
| php | `src/api/class-sync-health-controller.php` | Read probe transient; emit `probe` block. No outbound I/O. |
| php | `src/api/class-settings-controller.php` | Delegate probe to the extracted service |
| backend | `recognition/interface_adapters/http/routers/suggestions.py` | Honor `top_k`; add clamped `identity_ids` filter; batch cluster enrichment |
| tests | TS/PHP/Python suites | Per slice, below |

## Related Files

| File | Note |
| --- | --- |
| `class-abstract-recognition-proxy-controller.php:421-503` | The proxy breaker. UXP-2 reads its state; it must not write it. |
| `degradedModeBannerLogic.ts:5-13` | Documents why `last_pull.ok` is not an offline signal — preserve |
| `useClusterSuggestionsLoader.ts:63-68` | The `top_k=5` caller whose live behavior changes when `top_k` becomes real |
| `api/main.py:291-345` | `/health` (liveness, keyless) and `/health/detailed` (auth-gated) probe targets |

## Verification Strategy

- Deterministic tests:
  - `npm --prefix apps/prototype-wp-alt-context test`
  - `composer --working-dir=apps/prototype-wp-alt-context test`
  - `make test` (recognition suite, marker-filtered)
- Contract/fixture verification:
  - API test: `top_k` bounds the returned match count
  - API test: `identity_ids` returns the matching subset; over-limit list rejected
  - PHP test: `sync/health` emits `probe.source='none'` → idle-unknown with no transient; `ok:false` → offline; `ok:true` → healthy
  - PHP test: `sync/health` performs **no** outbound HTTP (assert via HTTP mock never called) — the render-blocking guard
- Runtime-parity / environment checks:
  - `make check-remote` for the committed HEAD (full suite belongs on the remote gate)
- Manual verification (**dev/staging recognition only** — never stop the prod/demo host, which serves the public demo):
  - With the dev recognition service rate-limiting: console shows zero repeated-429 loops; pollers cool down and resume.
  - Stop the **dev** recognition service (or point the effective target at a dead local URL) with **no job running**: banner flips offline within ~65s; restart flips it back.
  - Workbench with N unlabeled cards: network panel shows **one** suggestions request, not N.

## Slice Delivery

### Slice 1: Typed HTTPError + retry policy

**Goal**: A 4xx is never retried except 429, and 429 waits exactly as long as the server asked.

Changes:

- `HTTPError` class in `http.ts` carrying `status`, `retryAfterSeconds` (parsed from the header — delta-seconds or HTTP-date), `endpoint`, `bodyPreview`; `fetchApi` throws it instead of a string-formatted `Error`.
- QueryClient `retry` predicate: 5xx and network errors retry with bounded exponential backoff ([API-08]: backoff, bounded, 5xx-only); 4xx never retries; 429 retries once after `Retry-After`.
- Poll queries are GETs, so retry is idempotent by construction ([RES-01] — noted, not a risk here).

Proof:

- Unit: 429 with `Retry-After: 5` → one retry at ~5s; 429 with an HTTP-date → same; 403 → zero retries; 503 → backoff retry; malformed `Retry-After` → falls back to backoff, never `NaN`.
- Each test watched failing once before implementation ([TEST-06]).

### Slice 2: Shared 429 cooldown gate

**Goal**: One 429 from the recognition host quiets every hot poller until the server's window expires — without blinding the status surface.

Changes:

- `recognitionCooldown` module: `openCooldown(seconds)`, `isCoolingDown()`, subscribe/notify; single source of truth (sr-007 for state values).
- **Scope: per recognition host.** All four pollers hit one upstream, so a 429 from it is evidence about that host, not one endpoint. The rejected alternative (per-endpoint-family) would let three pollers keep hammering a host that just asked for quiet.
- QueryClient error path opens the cooldown on any 429 from that host.
- Job status (1.5s), media identities (3s), clusters (30s) **suspend** while cooling; resume on expiry.
- Sync health (15s) is **never suspended** — it drops to a 30s floor. A cooldown must not blind the surface the operator reads to understand the cooldown ([OBS-08]).

Proof:

- Unit with fake timers: one 429 suspends the three data pollers; sync health continues at the floor; expiry resumes all; no timer leak on unmount.
- Manual: rate-limited dev service → console shows no repeated-429 loop, banner still updates.

### Slice 3: Batch the suggestion fan-out

**Goal**: One bounded suggestions request per workbench render, and a server that honors the bound it advertises.

Changes:

- Server: `top_k` becomes a real clamped `Query` param on `/identities/{id}/suggestions`; add `identity_ids` filter to `/suggestions` bounded by `security_settings.max_page_size` (over-limit **rejected**, not truncated — [API-01]); batch the per-suggestion `cluster_repo.get_by_id` enrichment into one lookup ([RES-12]).
- PHP proxy forwards `identity_ids`.
- Client: `IdentityClusterList` (`IdentityClusterList.tsx:35-72`, the component that maps clusters → `IdentityClusterItem`) collects the visible unlabeled identity ids and calls `useInlineSuggestionBatch` once; the match reaches `InlineSuggestionPrompt` **by prop**, which becomes presentational. The false `// Only fetch top 1` comment goes with the code it misdescribed.
- `useClusterSuggestionsLoader`'s `top_k=5` call is covered by a test asserting the new bound, since it currently receives unbounded matches.

Proof:

- API tests: `top_k` bounds count (including the `top_k=5` behavior change); `identity_ids` returns the subset; over-limit id list rejected.
- Component test: N unlabeled cards → exactly one fetch.
- Manual: network panel shows one suggestions request.

### Slice 4: Heartbeat + honest banner states

**Goal**: The banner reports measured health, says "unknown" when it has not measured, and never blocks render to find out.

Changes:

- Extract the authenticated probe from `SettingsController` into `RecognitionProbe` ([TEST-04]: create the seam): 2 attempts per run, short timeout each ([RES-02]), writes `{at, ok, source}` to its own transient with a 180s TTL (3× cadence, so one missed tick cannot flap).
- `acx_recognition_heartbeat` cron event on a 60s custom interval runs the probe; registered/unregistered with plugin activation.
- `sync/health` reads the transient only and emits the `probe` block; **no outbound I/O in the handler**. Missing/stale transient → `probe.source='none'` → idle-unknown.
- `ProbeSource` as a backed enum / `as const` union (sr-007): `'cron' | 'settings_test' | 'none'`.
- Banner implements the state × signal table. Every state keeps icon + text, never color alone ([UI-02], [A11Y-06]); `alert`/`assertive` stays reserved for measured offline, `status`/`polite` for degraded and idle-unknown (rg-004).
- Copy uses UXP-4 vocabulary where it exists; new strings stay operator-language and are flagged for the UXP-4 pass.

Proof:

- PHP: no transient → `unknown`; failed probe → `probe.ok=false`; passing → healthy; probe runs at most once per 60s across repeated cron ticks; `sync/health` makes zero outbound requests even with no cached probe.
- TS: four banner outcomes render distinct title/message/role per the table; `breaker.state==='open'` with a passing probe reads **degraded**, not offline; `last_pull.ok=false` alone still reads healthy (guards the documented false-positive regression).
- Manual: stop dev recognition with no job running → offline within ~65s; restart → recovers.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded frontend/PHP/backend rules, sync-health contract, and UXP-1 intake decision before editing.
- [ ] Recorded boundary ownership for the `probe` block, `top_k`, and `identity_ids` changes.

### Checklist for Slice 1: Typed HTTPError + retry policy

- [ ] `HTTPError` with `status` + parsed `retryAfterSeconds` (delta-seconds and HTTP-date); `fetchApi` throws it.
- [ ] QueryClient predicate: 5xx-only backoff, 429 honors `Retry-After`, other 4xx never retry.
- [ ] Unit tests for 429 / 429-date / 403 / 503 / malformed `Retry-After`; each watched failing once.

### Checklist for Slice 2: Shared 429 cooldown gate

- [ ] `recognitionCooldown` module, per-host scope, single-source state values.
- [ ] Job status, media identities, clusters suspend on cooldown; sync health floors at 30s and never suspends.
- [ ] Fake-timer tests: suspend, floor, resume, no timer leak.

### Checklist for Slice 3: Batch the suggestion fan-out

- [ ] `top_k` honored and clamped server-side; `identity_ids` filter bounded by `max_page_size` with over-limit rejection; cluster enrichment batched.
- [ ] PHP proxy forwards `identity_ids`.
- [ ] `IdentityClusterList` owns the batch call; `InlineSuggestionPrompt` presentational by prop; stale comment removed.
- [ ] API + component tests; one request for N cards; `top_k=5` caller's behavior change covered.

### Checklist for Slice 4: Heartbeat + honest banner states

- [ ] `RecognitionProbe` extracted (2 attempts, short timeout, 180s TTL); `SettingsController` delegates.
- [ ] `acx_recognition_heartbeat` cron event + 60s interval, registered on activation.
- [ ] `sync/health` emits `probe`, performs no outbound I/O; test asserts the HTTP mock is never called.
- [ ] Banner implements the state × signal table with icon + text and correct roles; `last_pull.ok` regression guard kept.
- [ ] Manual dev-environment stop/restart evidence captured.

## Review Readiness

- [ ] Every boundary change (`probe` block, `top_k`, `identity_ids`) has matching contract/type/test evidence.
- [ ] Manual dev-environment stop/restart evidence captured — the idle-offline claim cannot be proven by unit tests alone ([TEST-10]).
- [ ] Handoff decision records the change, verification, and contract implications.

## Stretch Goals

- [ ] Emit a lightweight client metric on cooldown entry/exit ([OBS-01]) if it costs no new transport.

## Success Criteria

- [ ] With the dev recognition service rate-limiting, the console shows zero repeated-429 loops; pollers cool down and resume, and the banner keeps updating throughout.
- [ ] Stopping the **dev** recognition service flips the banner offline within **~65s** (one 60s cadence + one probe run) **with no job running**; restart flips it back.
- [ ] Heartbeat costs ≤1 request/60s per site; `sync/health` issues zero outbound requests and never blocks admin render.
- [ ] A workbench with N unlabeled cards issues one suggestions request.
- [ ] `top_k` is honored and clamped by the server — no ignored-param contract lie remains.
- [ ] Offline, degraded, and idle-unknown are each reachable from a distinct signal, and no two can be produced by the same one.
