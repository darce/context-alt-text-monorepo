# Task Plan

> **Metadata**
>
> - **Date**: 2026-07-22 19:20 EST
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

- No new plugin auth surface: refresh rides WP core's `rest-nonce` admin-ajax
  action (registered in `wp-admin/admin-ajax.php:56` core actions,
  `wp_ajax_rest_nonce()` in `wp-admin/includes/ajax-actions.php:5545`; plugin
  requires WP ≥ 6.0, action exists since 5.3). Verified in the LocalWP checkout.
- `BlobsController::maybe_bypass_nonce_for_blob_route` unchanged; service-side
  API-key auth out of scope; no proactive timer/heartbeat refresh (retry-on-403
  only, this task).
- Retry safety: `rest_cookie_check_errors` rejects in the authentication phase
  (`wp-includes/rest-api.php:1158`) before any route handler runs — a nonce-403
  guarantees non-execution, so one retry cannot double-apply
  ([RES-01]/[API-02]); the retry carries a *new* nonce header, so it is a
  modified request, not a blind 4xx retry ([API-08]). Exactly one retry;
  no retry for any other 4xx. Single-flight refresh — concurrent 403s share one
  refresh promise ([RES-06]).
- UXP-NET-1 429/`Retry-After` seam in `js/admin/utils/http.ts` and
  `js/admin/utils/retryPolicy.ts` must be behaviorally unchanged for non-403
  paths (regression-guarded); never a gated `refetchInterval` returning `false`.
- sr-005: boundary data (`ajaxUrl`, ajax envelope) validated explicitly, no
  assertion helpers on API data. Copy single-sourced per surface (UXP-4
  discipline). Disk floor: no local venv builds; python/full gate via
  `make check-remote`.

## Design

One shared seam, no per-callsite request changes:

1. **Refresh source (PHP)** — `localize_spa_config` and
   `localize_attachment_edit_config` (`src/admin/class-admin.php`) both add
   `ajaxUrl => admin_url('admin-ajax.php')`.
2. **Nonce store (TS)** — `js/admin/api/config.ts` gains `getNonce()` /
   `setNonce()` seeded from the localized payload on both paths
   (`window.AltContextAdmin` and `registerConfig`), plus single-flight
   `refreshRestNonce()` POSTing `action=rest-nonce` to `ajaxUrl` and parsing
   the WP ajax envelope (`{success: true, data: "<nonce>"}`).
3. **Retry seam** — `js/admin/utils/http.ts` `fetchApi`: on 403 whose JSON body
   `code === 'rest_cookie_invalid_nonce'` (parsed from the already-read error
   text, no double body read), refresh once, retry once with the fresh nonce.
   Second 403, or refresh failure → throw new `AuthExpiredError` (alongside
   `HTTPError`/`ResponseParseError`).
4. **Error classification** — `js/admin/utils/retryPolicy.ts` classifies
   `AuthExpiredError` non-retryable (react-query must not re-fire against an
   expired session); `hooks/clusterAutoRetry.ts` and
   `pages/workbench/identity-clusters/useLiveReviewTarget.ts` (the other
   `HTTPError` consumers) treat `AuthExpiredError` as terminal-auth, not
   transient.
5. **Recovery copy** — session-expired state with explicit reload/re-login
   action, distinct from generic error ([FORM-05]; [INT-11]: do not wipe
   in-progress UI state to display it). Attachment-edit copy in
   `js/attachment-edit/copy.ts`; SPA copy in the SPA's error-presentation
   module chosen in Slice 3 (single-sourced, no inline literals).

## Slices

### Slice 1 — refresh plumbing (PHP + config seam)

- [ ] `ajaxUrl` localized in both payloads (`localize_spa_config`,
      `localize_attachment_edit_config`); TS boundary validates non-empty
      string (explicit check, sr-005).
- [ ] `config.ts`: `getNonce()`/`setNonce()` accessor + single-flight
      `refreshRestNonce()`; envelope parse failure → typed failure.
- [ ] Vitest: N concurrent refresh callers → exactly 1 network call; malformed
      envelope → typed failure; `setNonce` visible to subsequent `getNonce()`.
- [ ] PHP test: both localize payloads carry `ajaxUrl` + `nonce` keys.

### Slice 2 — 403 retry seam in `http.ts`

- [ ] Nonce-403 detection by status + body `code`; refresh + single retry with
      new `X-WP-Nonce`; all other failures unchanged.
- [ ] `AuthExpiredError` thrown on refresh failure or repeat 403.
- [ ] Vitest discrimination proofs ([TEST-15]/[TEST-06], each red-provable):
      nonce-403 → refresh → retry succeeds (exactly 2 requests, new header);
      non-nonce 403 → no refresh, no retry; 429/5xx behavior byte-identical to
      pre-change (UXP-NET-1 guard); second 403 → `AuthExpiredError`; refresh
      rejection → `AuthExpiredError`; concurrent 403s → one refresh.

### Slice 3 — surface recovery states + copy

- [ ] `retryPolicy.ts`: `AuthExpiredError` classified non-retryable; existing
      429/`Retry-After` classification unchanged (test-pinned).
- [ ] `clusterAutoRetry.ts` + `useLiveReviewTarget.ts`: `AuthExpiredError`
      terminal-auth handling (no auto-retry loop).
- [ ] Attachment-edit: `AuthExpiredError` → session-expired copy + reload
      action (distinct from `faceDataUnavailable`), copy in `copy.ts`.
- [ ] SPA: error mapping renders auth-expired distinctly; component/module
      named in the slice-complete decision.
- [ ] Vitest/RTL: each surface renders auth-expired vs generic error as a
      discriminating assertion pair.

### Slice 4 — sweep + gate

- [ ] Nonce-read sweep: every request reads `getNonce()` at send time; **no
      captured/module-level nonce values** (e.g. `identityActionsApi.ts:75`
      captures `restNonce` into a payload at call time — audit all such sites);
      `grep -rn "\.nonce"` inventory recorded in the slice note.
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
  (one refresh + one retry, no reload) while the cookie session is alive.
- A logged-out tab shows the session-expired recovery state — never the
  generic unavailable state — on both surfaces.
- 429/5xx/network behavior is provably unchanged; `handoff_close_check(enforce=True)` passes.

## Consolidated Checklist

- [ ] S1: ajaxUrl in both payloads + boundary-validated; nonce accessor + single-flight refresh; PHP + vitest green.
- [ ] S2: nonce-403 → refresh → single retry; `AuthExpiredError`; discrimination tests red-provable; 429/5xx seam untouched.
- [ ] S3: retryPolicy/clusterAutoRetry/useLiveReviewTarget classify auth-expiry terminal; both surfaces render distinct recovery state; copy single-sourced.
- [ ] S4: nonce-capture sweep complete (call-time reads only); `make check-remote` green; manual LocalWP walkthrough recorded as test_result.
- [ ] Findings recorded/closed in MCP; close_check(enforce=True) passes.
