# APP-1 browser-integration I1 postlanding review

Review range: `a331a10bd3e5b5e0c2f6ea40f2d6dccf5b45524d..a9c1081bb1071a330e0ada1ed93c29494f12e3ba`

Scope was limited to the supplied inline delta, actual App routing, the shared bearer boundary, session ownership, public payment configuration, and their direct route/API contracts. B0/N1/C0 and the existing K/U module implementation were treated as constraints, not re-reviewed. The local checkout is history-stripped, so the supplied inline diff and exact current source paths were used for line verification.

## Summary

Verdict: conditional. Four medium integration findings remain; no high-severity finding was established in this scoped pass. The supplied VM self-verification was accepted as provided and was not rerun.

## Findings

### APP1-INTEGRATION-RV01 — `/portal/me` bypasses the shared redirect/URL containment boundary

- Severity: medium
- Category: auth-transport
- Location: `apps/app-portal/src/App.tsx:217-222`; direct fetch contract at `apps/app-portal/src/api/portalMe.ts:134-141`
- Failure scenario: The mounted shell obtains its authoritative tenant through `fetchPortalMe`, not `createPortalRequest`. That fetch follows redirects by default and accepts the final response when it contains any UUID tenant ID. A proxy/open-redirect or accidental same-origin redirect from `/portal/me` can therefore turn an unintended final response into an `ok` account and mount private routes; a same-origin redirect can also carry the bearer to the redirected endpoint. The shared module transport already rejects redirects and non-allowlisted paths, so the identity gate has weaker containment than the private subtree it authorizes.
- Minimal fix: Send `/portal/me` through the same bounded request helper, or add the identical relative-path allowlist and `redirect: 'error'` to `fetchPortalMe`; fail closed on any redirect or identity/source mismatch before producing `PortalMeOutcome.Ok`.

### APP1-INTEGRATION-RV02 — the shared deadline ends before response-body consumption

- Severity: medium
- Category: resilience
- Location: `apps/app-portal/src/api/portalRequest.ts:132-155`
- Failure scenario: The helper races only the fetch promise, then clears its timer as soon as response headers arrive. The mounted claim, key, usage, and billing clients call `response.json()` after the helper returns. If an endpoint sends headers and stalls its body, the timer is gone and the screen can remain busy indefinitely, violating the total bounded-wait contract even though the supplied hanging-fetch test passes.
- Minimal fix: Keep the controller/deadline alive through body reads—prefer a bounded JSON/read operation in the transport—or expose a response reader that races body consumption against the same abort gate and clears the timer only after the body is settled.

### APP1-INTEGRATION-RV03 — private route matching is a broad prefix, not a disjoint segment

- Severity: medium
- Category: routing
- Location: `apps/app-portal/src/App.tsx:327-342` and `apps/app-portal/src/App.tsx:373-425`
- Failure scenario: A signed-in user opening a typo or crafted path such as `/keys-old`, `/usage-preview`, `/billing-malformed`, or `/claim-anything` is routed into a real private module (and `/claim-anything` exposes the invitation claim UI). `/billing/returnevil` is caught by the return branch before the normal billing branch. This violates disjoint route boundaries and makes deep-link recovery/action semantics depend on arbitrary suffixes.
- Minimal fix: Match canonical paths plus a slash-delimited child only, e.g. `path === '/keys' || path.startsWith('/keys/')`, with the same segment-safe rule for claim, usage, billing, and billing return; use a stricter nested route for `/billing/return`.

### APP1-INTEGRATION-RV04 — checkout handoff races external navigation and loses the attempt on return

- Severity: medium
- Category: billing-recovery
- Location: `apps/app-portal/src/screens/BillingScreen.tsx:234-240`; return mounting/state at `apps/app-portal/src/App.tsx:402-411`
- Failure scenario: For a pending/provider-requested checkout, the handler calls `window.location.assign(checkout_url)` and immediately performs SPA navigation to `/billing/return`. The second navigation can win or race the hosted checkout. If the hosted page does win, the full-page unload destroys `returnAttemptId`, so a provider return to `/billing/return` renders generic pending copy with no preserved opaque attempt ID and no usable recovery context. The return screen correctly grants nothing, but it does not preserve the contract's checkout attempt for recovery.
- Minimal fix: Do not SPA-navigate to the return screen when a hosted URL exists; persist the validated opaque attempt ID in a short-lived session handoff before `assign` (or have the server build it into the allowlisted return target), read and clear it on return, and keep raw invitation/key material out of that handoff.

## Verification

- Supplied VM selfverify: `apps/app-portal/node_modules/.bin/vitest run --root apps/app-portal src/__tests__/account-navigation.test.tsx src/__tests__/portal-request.test.ts` — exit code 0, passed; not rerun in this review.
- No app execution, live request, provider access, secret use, or whole-suite run was performed.

GROK_REVIEW_FINDINGS_JSON
[
  {"finding_id":"APP1-INTEGRATION-RV01","severity":"medium","category":"auth-transport","file_path":"apps/app-portal/src/App.tsx","line_start":217,"line_end":222,"description":"The authoritative /portal/me call bypasses createPortalRequest, so it follows redirects and lacks the shared URL/redirect containment before a final UUID tenant response authorizes the private subtree.","fix":"Route /portal/me through the shared bounded request helper, or add the same relative-path allowlist and redirect:error behavior and fail closed on redirect or identity/source mismatch."},
  {"finding_id":"APP1-INTEGRATION-RV02","severity":"medium","category":"resilience","file_path":"apps/app-portal/src/api/portalRequest.ts","line_start":132,"line_end":155,"description":"The deadline is cleared after fetch headers resolve, while mounted clients parse response bodies afterward; a stalled body can leave a screen busy indefinitely.","fix":"Keep the abort/deadline through body consumption by bounding JSON/read operations in the transport or an equivalent shared reader, clearing the timer only after the body settles."},
  {"finding_id":"APP1-INTEGRATION-RV03","severity":"medium","category":"routing","file_path":"apps/app-portal/src/App.tsx","line_start":327,"line_end":425,"description":"Claim, keys, usage, billing, and billing-return dispatch uses startsWith prefixes, so arbitrary suffix paths mount real private modules and can expose claim/action semantics on noncanonical URLs.","fix":"Use exact canonical paths plus slash-delimited child matching, with a strict nested match for /billing/return."},
  {"finding_id":"APP1-INTEGRATION-RV04","severity":"medium","category":"billing-recovery","file_path":"apps/app-portal/src/screens/BillingScreen.tsx","line_start":234,"line_end":240,"description":"The checkout handler assigns the hosted URL and immediately SPA-navigates; the navigation can race checkout, and a full-page return destroys the in-memory attempt ID so recovery context is lost.","fix":"Avoid the immediate SPA navigation when a hosted URL exists and persist a validated opaque attempt handoff before assign, then read and clear it on the return route without storing secrets."}
]
