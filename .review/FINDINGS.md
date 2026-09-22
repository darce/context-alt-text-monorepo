# APP-1 browser B0 integrated-delta review

VERDICT: fail — two high session/privacy findings block this browser delta; four additional findings remain for the owning lanes.

Scope: one initial read-only review of the supplied browser delta. No production source or sibling-lane path was modified. Clerk and Polar remain offline/unprovisioned; no live-provider claim is made.

Verification note: the lane has no `apps/app-portal/node_modules`, so the supplied Vitest/typecheck/build commands were not rerun. The conclusions below are from bounded source/contract inspection; the dependency brief's existing green receipts were not reissued as new tests.

GROK_REVIEW_FINDINGS_JSON
[
  {
    "finding_id": "APP1-BROWSER-RV01",
    "severity": "high",
    "category": "privacy",
    "file_path": "apps/app-portal/src/App.tsx",
    "line_start": 72,
    "line_end": 127,
    "description": "AccountView is not tagged with the active Clerk session. After person A's /portal/me response has populated tenant A, a same-mounted identity transition to person B (for example a cross-tab sign-out/sign-in or active-session replacement) renders B's user data with the already committed tenant A state before the effect at line 105 resets it. The epoch/session checks only reject late promises; they do not prevent this stale state from being painted, so B can observe A's tenant UUID.",
    "fix": "Key or scope the account state by Clerk session/user identity and render a cleared/loading state whenever the current identity does not match the state owner; add a two-person transition test that asserts tenant A is never present after B becomes active."
  },
  {
    "finding_id": "APP1-BROWSER-RV02",
    "severity": "high",
    "category": "privacy",
    "file_path": "apps/app-portal/src/api/portalMe.ts",
    "line_start": 123,
    "line_end": 129,
    "description": "The authenticated GET /portal/me uses the default browser HTTP cache and does not request no-store. The current /portal/me success route does not add the no-store response header used by the portal key routes, so a private user-agent cache can retain a same-URL identity response. After A signs out and B signs in in the same browser profile, a cached tenant A response can be consumed for B; promise epoch guards cannot distinguish a cache hit from a fresh response.",
    "fix": "Set cache: 'no-store' on this fetch and require the /portal/me response to carry Cache-Control: no-store at the backend boundary; add a sign-out/sign-in cache-isolation test."
  },
  {
    "finding_id": "APP1-BROWSER-RV03",
    "severity": "medium",
    "category": "availability",
    "file_path": "apps/app-portal/src/api/portalMe.ts",
    "line_start": 79,
    "line_end": 90,
    "description": "getToken() is awaited before the timeout is created and outside the try/catch. When Clerk token refresh retries then rejects during an offline/provider failure, fetchPortalMe rejects and App's void .then chain has no rejection handler, leaving the account screen at 'Checking account…' with no outage/retry state. If token acquisition hangs, portalMeTimeoutMs does not bound it at all.",
    "fix": "Apply one abort/deadline to token acquisition plus the API request, catch token-provider failures, and return the existing outage/aborted outcomes; add rejection and never-resolving-token tests."
  },
  {
    "finding_id": "APP1-BROWSER-RV04",
    "severity": "medium",
    "category": "recovery",
    "file_path": "apps/app-portal/src/App.tsx",
    "line_start": 187,
    "line_end": 188,
    "description": "A signed-in backend 503 is routed to OutageScreen, which renders only Try again. It removes UserButton and Sign out even though the Clerk session is still active, so a backend outage traps the person without an in-app session exit. The account UX contract requires sign-out to remain reachable whenever a session exists.",
    "fix": "Keep the signed-in account chrome/UserButton and Sign out available in the backend-outage state (or pass those controls into OutageScreen) while retaining the bounded retry."
  },
  {
    "finding_id": "APP1-BROWSER-RV05",
    "severity": "medium",
    "category": "contract",
    "file_path": "apps/app-portal/src/api/portalMe.ts",
    "line_start": 51,
    "line_end": 59,
    "description": "The browser's empty-tenant success branch is not a state produced by the current /portal/me contract: the backend response model requires tenant_id and the route returns the resolved principal's tenant, while an unbound principal receives 403. The browser test fabricates a 200 body without tenant_id, so the intended post-sign-up 'not linked yet' screen is not integrated with the current endpoint and can mask a malformed success response.",
    "fix": "Align the browser state machine and tests with the published backend contract, or first publish a nullable/explicit-not-linked /portal/me response and its status vocabulary; do not use a synthetic malformed 200 as the admission contract."
  },
  {
    "finding_id": "APP1-BROWSER-RV06",
    "severity": "low",
    "category": "integration",
    "file_path": "apps/app-portal/csp/production.csp",
    "line_start": 10,
    "line_end": 10,
    "description": "The explicit frame-src directive omits 'self', so it overrides default-src's same-origin fallback for frames. Clerk's manual CSP template includes frame-src 'self' alongside the challenge/protect hosts; any same-origin frame used by the mounted provider or host is blocked by this artifact, while the current source test does not assert the self source.",
    "fix": "Add 'self' to frame-src and exercise the mounted production Clerk components against the final host CSP before live rollout; keep this artifact clearly marked as not yet applied."
  }
]
