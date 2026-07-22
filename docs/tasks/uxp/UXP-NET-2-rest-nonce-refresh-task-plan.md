# UXP-NET-2. Plugin-wide REST nonce refresh + auth-vs-network distinction

**Task ref**: `UXP-NET-2` · **Branch**: `feature/uxp-net-2` · **Origin**: UXP5-BRV-03 (deferred on UXP-5 archive)

## Problem

Both JS surfaces localize `wp_create_nonce('wp_rest')` exactly once at enqueue
(`src/admin/class-admin.php` — SPA `localize_spa_config`, attachment-edit
`localize_attachment_edit_config`). WP nonces expire (12–24h window). A
long-open admin SPA tab or post.php attachment-edit tab starts receiving
`403 rest_cookie_invalid_nonce` on every request and collapses into the generic
"unavailable" state with no recovery signal; error handling does not
distinguish auth-403 from network failure.

Canon triggers: [WP-02]/[WEB-06] (nonce is the CSRF mechanism — keep it, refresh
it, never bypass it), [SECD-03] (complete mediation: server keeps checking every
call; the client must keep *supplying* fresh authority), [FORM-05]/[INT-11]
(actionable error + recovery that preserves in-progress work over full restart).

## Design

One shared seam, no per-callsite changes:

1. **Refresh source (PHP)**: WP core ships the `rest-nonce` admin-ajax action
   (`wp_ajax_rest-nonce`, core since 5.3) returning a fresh `wp_rest` nonce for
   the logged-in cookie session. Localize `ajaxUrl => admin_url('admin-ajax.php')`
   into **both** config payloads. No new plugin endpoint, no capability surface
   change ([WP-02] preserved: verification stays server-side, we only re-mint).
2. **Nonce store (TS)**: `config.ts` gains a mutable current-nonce accessor
   (`getNonce()` / `setNonce()`), seeded from the localized payload for both the
   SPA path (`window.AltContextAdmin`) and the `registerConfig` post.php path.
   All existing `getConfig().nonce` reads migrate to the accessor (mechanical;
   callsites keep passing `restNonce` into `fetchApi`).
3. **Refresh + retry seam (`admin/utils/http.ts`)**: on HTTP 403 whose JSON body
   `code` is a WP nonce/cookie auth code (`rest_cookie_invalid_nonce`), call a
   **single-flight** `refreshRestNonce()` (concurrent 403s share one refresh
   promise — no thundering herd, [RES-06]), then retry the original request
   **once** with the new nonce.
   - Safety: `rest_cookie_check_errors` rejects in the authentication phase,
     before any route handler runs — a nonce-403 guarantees the operation did
     not execute, so one retry cannot double-apply ([RES-01]/[API-02]); the
     retried request carries a new nonce, so it is a *modified* request, not a
     blind 4xx retry ([API-08]). No retry for any other 4xx.
   - Retry once only; a second nonce-403 falls through to the auth-expired path.
4. **Error taxonomy**: refresh failure (ajax non-OK / user logged out) or
   post-refresh 403 throws `AuthExpiredError` (new, alongside `HTTPError` /
   `ResponseParseError`). Callers distinguish: network/5xx → existing paths;
   `AuthExpiredError` → session-expired state with an explicit reload/re-login
   action ([FORM-05]: which/why/how-to-fix; [INT-11]: do not wipe in-progress
   UI state to say it).
5. **Copy**: session-expired copy added to `attachment-edit/copy.ts` and the
   SPA's equivalent error surface; sync-vocabulary discipline from UXP-4 (single
   source per surface, no inline literals).

Out of scope: proactive timer-based refresh (heartbeat piggyback), non-`wp_rest`
nonces, `BlobsController::maybe_bypass_nonce_for_blob_route` (unchanged), the
service-side auth path (API-key, not nonce).

## Slices

### Slice 1 — refresh plumbing (PHP + config seam)
- `ajaxUrl` localized in both payloads; validated non-empty at TS boundary
  (explicit boundary validation, sr-005 — no assertion helpers on API data).
- `config.ts`: nonce accessor + `refreshRestNonce()` (single-flight, POSTs
  `action=rest-nonce` to `ajaxUrl`, parses WP ajax envelope, `setNonce`).
- Vitest: single-flight (N concurrent callers → 1 fetch), envelope parse
  failure → typed failure, store update visible to `getNonce()`.
- PHP test: both localize payloads carry `ajaxUrl` + `nonce` keys.

### Slice 2 — 403 retry seam in `http.ts`
- Detect nonce-403 by status + body `code` (parse the already-read error text;
  no double body read). Retry once with refreshed nonce; all other failures
  unchanged.
- `AuthExpiredError` class; thrown on refresh failure or repeat 403.
- Vitest ([TEST-15]/[TEST-06] discrimination proofs, each red-provable):
  nonce-403 → refresh → retry succeeds (1 retry, new header value);
  non-nonce 403 → no refresh, no retry; 429/5xx paths untouched (UXP-NET-1
  regression guard); second 403 → `AuthExpiredError`, exactly 2 requests;
  refresh rejection → `AuthExpiredError`; concurrent 403s → one refresh.

### Slice 3 — surface recovery states + copy
- Attachment-edit: `AuthExpiredError` → session-expired message + reload
  action (not `faceDataUnavailable`); copy in `copy.ts`.
- Admin SPA: query/mutation error mapping distinguishes `AuthExpiredError`
  (react-query: no silent permanent-freeze patterns — UXP-NET-1 lesson:
  never return `false` from a gated `refetchInterval`).
- Vitest/RTL: each surface renders auth-expired state distinctly from the
  generic error state (discriminating assertion pair).

### Slice 4 — sweep + gate
- Migrate remaining `getConfig().nonce` literal reads to the accessor
  (mechanical sweep; `grep -rn "\.nonce"` inventory recorded in slice note).
- `make check-remote` green (typecheck baseline compare, not exit-code),
  scoped vitest local; a11y unaffected (copy-only DOM changes announced via
  existing live regions).

## Verification
- Scoped vitest per slice locally (APFS-clone node_modules; **no local venv builds** — disk floor).
- Full gate via `make check-remote` at slice 4.
- Manual: LocalWP long-tab simulation — invalidate nonce server-side
  (`wp_set_current_user` re-login or filter `nonce_life` to 30s), confirm SPA +
  post.php recover on next action without reload; then logged-out case shows
  session-expired copy.

## Consolidated checklist
- [ ] S1: ajaxUrl in both payloads + boundary-validated; nonce accessor + single-flight refresh; PHP + vitest green.
- [ ] S2: nonce-403 → refresh → single retry; `AuthExpiredError`; discrimination tests red-provable; 429/5xx seam untouched.
- [ ] S3: both surfaces render distinct auth-expired recovery state; copy single-sourced.
- [ ] S4: nonce-read sweep complete; `make check-remote` green; manual LocalWP walkthrough recorded as test_result.
- [ ] Findings recorded/closed in MCP; close_check(enforce=True) passes.
