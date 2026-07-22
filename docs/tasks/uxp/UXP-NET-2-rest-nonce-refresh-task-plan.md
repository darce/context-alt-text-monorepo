# Task Plan

> **Metadata**
>
> - **Date**: 2026-07-22 19:30 EST
> - **Author**: claude-fable-5 medium
> - **Project**: apps/prototype-wp-alt-context
> - **Task ID**: `UXP-NET-2`
> - **Target Branch**: `feature/uxp-net-2`
> - **Review Coverage Target**: 2

---

## UXP-NET-2. Plugin-wide REST nonce refresh + auth-vs-network distinction

## Objective

Long-open admin SPA and post.php attachment-edit tabs recover transparently from
WP REST nonce expiry (single-flight refresh + one safe retry), and auth-expiry
is rendered as a distinct, actionable recovery state instead of the generic
"unavailable" error. Origin: UXP5-BRV-03 (deferred on UXP-5 archive).

## Problem Statement

Both JS surfaces localize `wp_create_nonce('wp_rest')` exactly once at enqueue
(`src/admin/class-admin.php` — `localize_spa_config` :361, and
`localize_attachment_edit_config` :434). WP nonces expire (12–24h window). A
long-open tab then receives `403 rest_cookie_invalid_nonce` on every request and
collapses into the generic unavailable state with no recovery signal; error
handling does not distinguish auth-403 from network failure.

Canon triggers: [WP-02]/[WEB-06] (the nonce is the CSRF mechanism — keep it,
refresh it, never bypass it), [SECD-03] (complete mediation: the server keeps
checking every call; the client must keep *supplying* fresh authority),
[FORM-05]/[INT-11] (actionable error + recovery that preserves in-progress work
over full restart).

## Constraints

- **Refresh wire contract (verified against WP core in the LocalWP checkout)**:
  the core `rest-nonce` action is registered **GET-only** — it lives in
  `$core_actions_get` (`wp-admin/admin-ajax.php:56`) and the hook registration
  is gated on `$_GET['action']` (admin-ajax.php:161-163); a POST with the
  action only in the body dies `'0'`/400. The handler
  (`wp_ajax_rest_nonce()`, `wp-admin/includes/ajax-actions.php:5545`) is
  `exit( wp_create_nonce( 'wp_rest' ) )` — the response body is the **raw
  nonce string**, not a JSON envelope. Logged-out requests (no nopriv handler)
  die `'0'`/400. Plugin requires WP ≥ 6.0; action exists since 5.3.
- No new plugin auth surface; `BlobsController::maybe_bypass_nonce_for_blob_route`
  unchanged; service-side API-key auth out of scope; no proactive
  timer/heartbeat refresh (retry-on-403 only, this task).
- Retry safety: `rest_cookie_check_errors` rejects in the authentication phase
  (`wp-includes/rest-api.php:1154-1158`) before any route handler runs — a
  nonce-403 guarantees non-execution, so one retry cannot double-apply
  ([RES-01]/[API-02]); the retry carries a *new* nonce header, so it is a
  modified request, not a blind 4xx retry ([API-08]). Exactly one retry; no
  retry for any other 4xx. Single-flight refresh with the in-flight slot
  cleared in `finally` — a rejected refresh must not poison later attempts
  ([RES-06]).
- **Accepted risk (documented)**: `rest-nonce` returns a nonce for whichever
  user's cookie is *currently* authenticated. If the browser's WP session was
  switched to a different account between the original request and the retry,
  the retried mutation executes as the new user. Accepted for this admin
  plugin (same-browser account switching mid-mutation is out of threat model;
  WP core's own `wp-api-request.js` auto-refresh has identical semantics).
  No identity guard this task.
- UXP-NET-1 429/`Retry-After` seam in `js/admin/utils/http.ts` and
  `js/admin/utils/retryPolicy.ts` must be behaviorally unchanged for non-403
  paths (concretely test-pinned, see Slice 2); never a gated `refetchInterval`
  returning `false`.
- sr-005: boundary data (`ajaxUrl`, refresh response) validated explicitly.
  Copy single-sourced per surface (UXP-4 discipline). Disk floor: no local
  venv builds; python/full gate via `make check-remote`.

## Design

1. **Refresh source (PHP)** — `localize_spa_config` and
   `localize_attachment_edit_config` (`src/admin/class-admin.php`) both add
   `ajaxUrl => admin_url('admin-ajax.php')`. TS types
   (`ApiConfig`/`NormalizedConfig` in `js/admin/api/config.ts`, and the
   attachment-edit localized-config type consumed by
   `js/attachment-edit/main.tsx`) gain `ajaxUrl`; `normalizeConfig`/
   `registerConfig` validate non-empty string; `main.tsx` threads
   `payload.ajaxUrl` through `registerConfig`.
2. **Nonce store (TS)** — `js/admin/api/config.ts`: `getNonce()` reads and
   `setNonce()` **mutates `cachedConfig.nonce` in place** (and the
   window-derived cached object on the SPA path), so the ~70 existing
   call-time `restNonce: getConfig().nonce` sites remain live-correct with
   zero rewrites. `refreshRestNonce()`: dedicated same-origin
   `fetch(`${ajaxUrl}?action=rest-nonce`, { method: 'GET', credentials:
   'same-origin' })` — NOT `fetchApi` (no JSON headers). Success = HTTP 2xx
   AND trimmed body matching `/^[a-f0-9]{8,20}$/i` (and not literal `'0'` /
   `'-1'` / empty) → `setNonce(body)`. Anything else → typed refresh failure.
   Single-flight: concurrent callers share one promise; slot cleared in
   `finally`.
3. **Retry seam** — `js/admin/utils/http.ts` `fetchApi`: resolve `X-WP-Nonce`
   **per attempt** from `options.restNonce ?? getNonce()` on the first send and
   from `getNonce()` on the retry (never reuse a stale option across the
   refresh). On 403, attempt `JSON.parse` of the already-read error text
   inside try/catch — non-JSON body (WAF/proxy page) → ordinary `HTTPError`,
   no refresh. If `code === 'rest_cookie_invalid_nonce'`: if
   `options.signal?.aborted`, bail with the abort; else refresh once, re-check
   abort, retry once. Second nonce-403 or refresh failure →
   `AuthExpiredError`. HTTP 401 responses whose body `code` is
   `rest_not_logged_in` also map to `AuthExpiredError` (no refresh attempt —
   the session is gone).
4. **Error classification** — `js/admin/utils/retryPolicy.ts` and
   `js/admin/hooks/clusterAutoRetry.ts` already treat unknown errors as
   terminal (verified: `shouldRetryRequest` retries only cooldown signals /
   `TypeError`; `isRetryableClusterError` only 429) — add explicit
   `instanceof AuthExpiredError → false` **regression pins + tests only**, no
   new logic. `js/admin/pages/workbench/identity-clusters/useLiveReviewTarget.ts`
   is different: its inline `retry` predicate (:84-90) retries any non-404
   once and its status model absorbs non-404 errors into `'live'` — exclude
   `AuthExpiredError` there and let the error surface through the SPA's
   general error presentation instead of reporting `'live'`.
5. **SSE path** — `js/admin/hooks/useJobProgressStream.ts` bakes `_wpnonce`
   into the `EventSource` URL at connect (:146-149), bypassing `fetchApi`.
   In-task: every (re)connect builds the URL from `getNonce()` at connect
   time, so post-recovery reconnects carry the fresh nonce. Accepted risk
   (documented): an EventSource nonce-403 is statusless and surfaces as a
   stall; stall-to-auth classification is out of scope this task (the next
   user *action* still recovers via the fetch seam).
6. **Recovery copy** — session-expired state with explicit reload/re-login
   action, distinct from generic error ([FORM-05]; [INT-11]: do not wipe
   in-progress UI state to display it). Attachment-edit copy in
   `js/attachment-edit/copy.ts`; SPA copy in the SPA's error-presentation
   module chosen in Slice 3 (single-sourced, no inline literals).

## Slices

### Slice 1 — refresh plumbing (PHP + config seam)

- [ ] `ajaxUrl` localized in both payloads; TS types + `normalizeConfig`/
      `registerConfig` validation + `main.tsx` threading (sr-005).
- [ ] `config.ts`: `getNonce()`/`setNonce()` (in-place mutation of the cached
      config) + `refreshRestNonce()` per Design §2 (GET, raw-string contract,
      charset validation, single-flight, finally-cleared slot).
- [ ] Vitest: N concurrent refresh callers → exactly 1 network call; request
      shape asserted (GET, `?action=rest-nonce`, same-origin credentials);
      raw-string success → `setNonce` visible via `getNonce()`; logged-out
      `'0'`/400 fixture → typed failure; empty/HTML body → typed failure;
      **reject-then-retry → second network call** (no poisoned slot).
- [ ] PHP test: both localize payloads carry `ajaxUrl` + `nonce` keys.

### Slice 2 — 403/401 seam in `http.ts`

- [ ] Per-attempt nonce resolution (`options.restNonce ?? getNonce()` first
      attempt, `getNonce()` on retry); nonce-403 detection with try/catch
      body parse; abort short-circuit before refresh and before retry;
      single retry; `AuthExpiredError` on second 403 / refresh failure /
      401 `rest_not_logged_in`.
- [ ] Vitest discrimination proofs ([TEST-15]/[TEST-06], each red-provable):
      nonce-403 → refresh → retry succeeds (exactly 2 REST requests + 1 ajax
      GET, retry carries the NEW header value); non-nonce 403 → no refresh,
      no retry, ordinary `HTTPError`; non-JSON 403 body → ordinary
      `HTTPError`, no refresh; 401 `rest_not_logged_in` → `AuthExpiredError`,
      no refresh call; second 403 → `AuthExpiredError`; aborted signal
      mid-refresh → abort surfaced, no retry; concurrent 403s → one refresh.
- [ ] UXP-NET-1 regression pins: 429 and 503+Retry-After cases assert fetch
      called exactly once, zero ajaxUrl calls, and thrown `HTTPError`
      `status`/`retryAfterSeconds`/`message` equal to the existing
      `http.test.ts` expectations.

### Slice 3 — surface recovery states + copy

- [ ] `retryPolicy.ts` + `clusterAutoRetry.ts`: `instanceof AuthExpiredError
      → false` regression pins + terminal-fallthrough tests (no new logic).
- [ ] `useLiveReviewTarget.ts`: inline retry predicate excludes
      `AuthExpiredError`; auth-expiry surfaces through the SPA error path,
      never absorbed into `'live'` (test pins both).
- [ ] `useJobProgressStream.ts`: (re)connect URL reads `getNonce()` at
      connect time (test: nonce refreshed between connects → new param).
- [ ] Attachment-edit: `AuthExpiredError` → session-expired copy + reload
      action (distinct from `faceDataUnavailable`), copy in `copy.ts`.
- [ ] SPA: error mapping renders auth-expired distinctly; component/module
      named in the slice-complete decision.
- [ ] Vitest/RTL: each surface renders auth-expired vs generic error as a
      discriminating assertion pair.

### Slice 4 — sweep + gate

- [ ] Nonce-read verification sweep: `grep -rn "\.nonce"` inventory recorded;
      confirm every request path reads the live value (in-place `setNonce`
      makes existing `getConfig().nonce` sites correct — verify none copy the
      nonce into module-level/closure state at import time; fix any that do).
- [ ] `make check-remote` green (typecheck compared against 5-error main
      baseline, not raw exit); scoped vitest green locally.
- [ ] Manual LocalWP walkthrough: shorten `nonce_life` to ~30s via filter,
      confirm SPA + post.php recover on next action without reload; logged-out
      case shows session-expired copy. Recorded as `test_result`.

## Review Readiness

- Every slice lands with its tests in the same commit; findings recorded in
  MCP (never in this file); /review-parallel (≥1 remote grok + local claude)
  before merge; reviewer claims code-verified before recording.
- Heuristics cited in briefs and findings: [WP-02] [WEB-06] [SECD-03] [RES-01]
  [RES-06] [API-02] [API-08] [FORM-05] [INT-11] [TEST-15] [TEST-06].

## Success Criteria

- A tab whose nonce expired recovers transparently on the next user action
  (one GET refresh + one retry, no reload) while the cookie session is alive.
- A tab whose cookie session is gone (logged out) shows the session-expired
  recovery state — never the generic unavailable state — on both surfaces,
  via refresh-failure or 401 classification.
- 429/5xx/network behavior is provably unchanged (pinned assertions);
  `handoff_close_check(enforce=True)` passes.

## Consolidated Checklist

- [ ] S1: ajaxUrl threaded + validated on both surfaces; GET raw-string refresh with single-flight + finally-clear; PHP + vitest green.
- [ ] S2: per-attempt nonce resolution; nonce-403 refresh + single retry; 401 classification; abort + non-JSON-body handling; discrimination tests red-provable; 429/5xx pins green.
- [ ] S3: regression pins (retryPolicy, clusterAutoRetry); useLiveReviewTarget auth-expiry surfaced; SSE reconnect fresh-nonce; both surfaces render distinct recovery state; copy single-sourced.
- [ ] S4: nonce-capture verification sweep; `make check-remote` green; manual LocalWP walkthrough recorded as test_result.
- [ ] Findings recorded/closed in MCP; close_check(enforce=True) passes.
