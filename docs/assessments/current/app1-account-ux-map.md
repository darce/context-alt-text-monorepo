# APP-1 account UX map — inventory and ASCII screens

Date: 2026-09-22. Status: COMPLETED docs/map contract — OBSERVED-UI B0 account chrome plus PLANNED-UI B1 browser journeys in the same SSOT map. Coordinator decisions record the B0 browser fix and N1 backend fix as landed; no F0 repair prerequisite remains. Clerk production, Polar sandbox, and WordPress live evidence remain unavailable; this is an offline inventory and contract, not an acceptance claim. SSOT: [`docs/ux-maps/app-portal.uxmap.json`](../../ux-maps/app-portal.uxmap.json). Detailed B1 contracts and ownership live in [`app1-browser-journey-slices-20260922.md`](app1-browser-journey-slices-20260922.md). Plugin map precedent: `apps/prototype-wp-alt-context/docs/ux-maps/*.uxmap.json`.

Canon (stable IDs, latest, never pin): [heuristics-canon](https://github.com/darce/heuristics-canon) `REF-15`, `CARD-06`, `CARD-15`, `DOM-03`. Also `NAV-08`, `NAV-07`, `RLSE-04`, `FORM-09`, `CARD-12`, `CARD-16`.

## Decision

Author the account screen contract before browser code (`CARD-06`). Visible **Sign in**, **Create account**, **User**, and **Sign out**. Unavailable configuration is a designed screen with those controls disabled or absent. Clerk authenticates a person. Tenant UUID and API keys stay existing backend authority. No fake tenant claims (`DOM-03`). Wrap Clerk so a later identity swap is an adapter change (`REF-15`, `CARD-16`). Sign-out is cheap and reversible at session scope; key revoke is not this surface (`CARD-15`).

Account screens and flows below are **OBSERVED-UI** in `apps/app-portal`. Production Clerk and the Polar sandbox remain unprovisioned; this document does not claim live-provider evidence. The same JSON map now extends into **PLANNED-UI** claim, keys, usage, WordPress guidance, and billing journeys using current backend contracts; no B1 source implementation is included in this docs lane.

## B0 browser-fix invariants before B1

These are accepted integration constraints for the app-owned browser-fix wave, recorded here before any B1 source work. They are not a claim that production Clerk or a live backend has been exercised.

| Invariant | Contract for the shell | Source anchor |
| --- | --- | --- |
| Session ownership | Key account state and stale-response guards by Clerk `userId`/session epoch; a late response from a previous person cannot populate the current screen. | `apps/app-portal/src/App.tsx:71-127` |
| Private fetch | `/portal/me` reads use `Cache-Control: no-store` intent, bounded timeout, and Clerk token refresh/retry within the API client boundary; never use a cached tenant binding. | `apps/app-portal/src/api/portalMe.ts:79-147` plus accepted B0-fix constraint |
| Invalid 200 | A 200 response missing or carrying an invalid `tenant_id` is invalid account data, not “not linked”; do not substitute email, Clerk org, or a guessed tenant. | `portalMe.ts:51-59`; `App.tsx:46-54`; `backend-authority.test.tsx:77-94` |
| Unadmitted 403 | `/portal/me` 403 remains a non-enumerating account-not-ready state; claim-specific `email_unverified` is the only typed verified-email exception. | `portalMe.ts:62-76`; `portal_auth.py:681-712, 728-779` |
| Signed-in outage | A 503/timeout preserves UserButton and Sign out; retry refreshes the backend identity read and does not turn an outage into signed-out or tenant-ready UI. | `App.tsx:181-209`; `OutageScreen.tsx:3-18`; accepted B0-fix constraint |

The B1 feature modules consume these boundaries. They do not redesign the existing Clerk account integration (`REF-15`, `CARD-16`, `RLSE-04`, `NAV-11`, `HAI-01`).

## B1 completion and parallel implementation boundary

The coordinator's frozen decision is that K/U (keys and usage) and C/B (claim
and billing) implement in parallel after this contract freeze. Each feature
group owns its API DTOs, client interface, local error shape, and component
props. Components receive typed clients and test doubles through props; they
do not import runtime or type definitions from a hypothetical shared browser
module. A structural `PortalRequest` alias is repeated in each owned API file.

B0 and N1 are already landed. I1 is a single app owner activated only after
both feature groups land: it creates the real session-scoped authenticated
no-store bounded transport, passes it to the four feature factories, keys the
keys subtree to the Clerk session/user, and wires `App.tsx`, routes, styles,
and config. No feature group edits those shell paths or waits for an unwritten
F0 source module.

## Vocabulary (`DOM-03`)

| Term | Meaning here | Not this |
| --- | --- | --- |
| Clerk user | Person session from `@clerk/react` | Tenant, workspace, org |
| Tenant | Backend UUID from identity link | Clerk org, email local-part |
| Admitted | Backend accepted the Clerk subject | Signed-in at Clerk |
| API key | Existing local hashed credential | Clerk secret, publishable key |
| Unavailable | Portal cannot run (config or flag) | Clerk outage after config exists |

## Jobs

| Job | Entry | Success |
| --- | --- | --- |
| Authenticate session | Signed-out chrome | Clerk session on origin; return to account |
| Manage session | Signed-in chrome | User visible; sign-out returns to signed-out |
| Recover unavailable | Missing key, flag off, Clerk down, not admitted | Honest copy; no invented tenant; sign-out if a session exists |

## Screen index

| Screen | Kind | Route | Primary |
| --- | --- | --- | --- |
| Signed out | screen | `/` | Sign in |
| Sign in | overlay | `/sign-in` | Continue (account sign-in) |
| Create account | overlay | `/sign-up` | Create account (account setup) |
| Signed in | screen | `/` | User menu |
| Unavailable | screen | `/` | none |
| Not admitted | screen | `/` | Sign out |
| Sign-in unavailable | screen | `/` | Try again |
| Sign out | exit | `/` | Sign out |

`code_ref` is `apps/app-portal/src/App.tsx` for B0. The B1 extension anchors its planned screens to current `portal.py` handlers and keeps Clerk integration as the existing adapter; no provider CLI setup or application ID is required for this offline slice.

## ASCII screens and states

### Signed out — `default` / `first_time`

```text
+-- AltContext account -----------------------------------------------------+
| AltContext                                                                |
| Account                                                                   |
| Sign in to manage your account.                                           |
|                                                                            |
| status: Ready to sign in                                                   |
|                                                                            |
| [ Sign in ]     [ Create account ]                                         |
+----------------------------------------------------------------------------+
```

`loading`: same chrome; both buttons disabled; status “Checking sign-in…”. `FORM-09`: do not enable Sign in or Create account before the provider is ready.

### Sign in overlay — `default`

```text
+-- Sign in ---------------------------------------------------------------+
| Sign in                                                                   |
| (Secure account sign-in)                                                  |
| [email / SSO / MFA]                                                        |
|                                                                            |
| [ Continue ]                                                               |
| Create account · Back to account                                           |
+----------------------------------------------------------------------------+
```

`error`: the account sign-in surface failed to load; Back to account still works (`NAV-07`). The app never collects a password field of its own.

### Create account overlay — `default`

```text
+-- Create account --------------------------------------------------------+
| Create an account                                                         |
| Set up your account to continue.                                          |
| (Secure account setup)                                                     |
|                                                                            |
| [ Create account ]                                                         |
| Sign in · Back to account                                                  |
+----------------------------------------------------------------------------+
```

Creating a person session does not grant tenant access; that backend invariant remains in the JSON purpose and zone prose.

### Signed in — `default`

```text
+-- AltContext account -----------------------------------------------------+
| AltContext                                            [Account] [Sign out] |
| Account                                                                   |
| You are signed in as <name or email>.                                     |
| Account access: Checking                                                  |
|                                                                            |
| status: Session ready                                                      |
+----------------------------------------------------------------------------+
```

`loading`: Account may be present; account access strip “Checking account…”. The B0-fix contract treats a 200 `/portal/me` response without a valid `tenant_id` as invalid backend account data, not as a “not linked” tenant; it must not be filled from the email local-part or a Clerk organization (`CARD-12`). No `OrganizationSwitcher`. The account menu and Sign out remain reachable while identity is loading, ready, or the signed-in backend is unavailable (`RLSE-04`, `NAV-11`, `HAI-01`).

### Unavailable — missing publishable key (`error`)

```text
+-- AltContext account -----------------------------------------------------+
| AltContext                                                                |
| Account                                                                   |
| status: Account access is not configured.                                  |
| Sign in and Create account are not available.                              |
+----------------------------------------------------------------------------+
```

No provider wrapper. No secret key in the client. `CLERK_SECRET_KEY` must never appear in browser bundles.

### Unavailable — portal flag off (`degraded`)

```text
+-- AltContext account -----------------------------------------------------+
| AltContext                                                                |
| Account                                                                   |
| status: Account access is turned off.                                     |
| Contact support. Sign in is disabled.                                     |
+----------------------------------------------------------------------------+
```

Distinct from missing config and from sign-in outage (`NAV-13` / `DOM-03`).

### Not admitted — `error`

```text
+-- AltContext account -----------------------------------------------------+
| AltContext                                            [Account] [Sign out] |
| Account                                                                   |
| status: Your account is not ready for access yet.                         |
|                                                                            |
+----------------------------------------------------------------------------+
```

Backend `/portal/me` uses 403 `portal access denied` for an unadmitted tenant-bound principal; claim uses typed `email_unverified` or `not_admitted` outcomes. UI keeps non-enumerating “account access not ready” copy unless verified-email guidance is explicitly required. Sign out remains (`NAV-07`). No tenant, keys, or billing are shown before backend admission.

### Sign-in unavailable (provider outage) — `error`

```text
+-- AltContext account -----------------------------------------------------+
| AltContext                                                                |
| Account                                                                   |
| status: Sign-in is temporarily unavailable.                               |
| [ Try again ]                                                              |
+----------------------------------------------------------------------------+
```

Bounded wait before this state (`INT-08`). A signed-in backend outage is a separate planned state that retains UserButton and Sign out; WordPress API-key recognition is a different failure domain and is not claimed broken here (`REF-15`).

### Sign out exit

`default`:

```text
+-- Signed out again ------------------------------------------------------+
| You are signed out.                                                       |
| → signed-out chrome                                                        |
+----------------------------------------------------------------------------+
```

`loading`: Signing out… Existing API keys are unchanged. Tenant/account fetch data already cleared. `error`: Sign out failed. Your account data on this page is cleared. Try again. Sign in doors are not restored until sign-out succeeds (`RLSE-04`).

Ending the person session does not revoke backend API keys (`CARD-15`); that engineering invariant is not customer-facing copy.

## Interaction coverage

| Trigger | Result | Controls |
| --- | --- | --- |
| First paint, key missing | `portal-unavailable` error | none |
| Portal disabled | `portal-unavailable` degraded | none |
| Key present, Clerk loading | signed-out `loading` | Sign in / Create account disabled |
| Clerk ready, signed out | signed-out `default` | Sign in primary, Create account secondary |
| Sign in success | `portal-account` | User + Sign out |
| Sign up success | `portal-account` empty tenant strip | User + Sign out |
| Backend 403 not admitted | `portal-not-admitted` | User + Sign out |
| Clerk.js/session fail | `portal-clerk-outage` | Try again |
| Sign out | `logout-complete` loading → default → signed-out | Sign in restored only after success |
| Sign out fails | `logout-complete` error | Try again retries sign-out; data stays cleared; Sign in not restored (`RLSE-04`) |
| User | account profile surface | account-owned; no tenant editor |

Primary actions stay reachable from zero selection (`rg-003`). Status uses icon plus color (`sr-004` when CSS lands).

## Interaction state assessment

The recovered action conditions are represented in supported screen states rather than extra schema fields:

| Screen | State | Interaction meaning |
| --- | --- | --- |
| `portal-signed-out` | `loading` | The session provider is resolving; `open-sign-in` and `open-sign-up` are present but disabled. |
| `portal-signed-out` | `default` / `first_time` | The session is ready and signed out; `open-sign-in` is primary and `open-sign-up` is secondary, both enabled. |
| `portal-account` | `loading` | Signed-in chrome remains available while `/portal/me` is checked; the account menu and Sign out remain reachable. |
| `portal-account` | `default` | The signed-in person can open the account menu or sign out. |
| `portal-account` | `empty` | The source B0 state is retained for schema compatibility, but the accepted B0-fix meaning is invalid `/portal/me` binding (for example 200 without a valid tenant_id); no “not linked” label, tenant substitute, or key/billing control is enabled. |
| `portal-account` | `error` | Backend `GET /portal/me` returned 401; retry refetches. Sign out remains. |
| `portal-backend-outage` | `error` / `degraded` | Backend 503/timeout; retry is bounded to the account read while UserButton and Sign out remain reachable. |
| `portal-not-admitted` | `degraded` | Clerk email is unverified; Sign out remains; no tenant UUID. |
| `logout-complete` | `loading` | Sign-out in flight; account/tenant data already cleared. |
| `logout-complete` | `error` | Sign-out failed; Try again retries sign-out; tenant data stays cleared. |

## Critique (advisory)

| ID | Finding | Fix in this map |
| --- | --- | --- |
| `NAV-08` | First screen needs obvious doors | Sign in + Create account |
| `NAV-07` | Overlay/error traps | Back / Sign out always present when a session exists |
| `RLSE-04` | Empty config must not be a blank crash | `portal-unavailable` |
| `RLSE-04` | Logout success-only; fail/retry undesigned | `logout-complete` `loading` + `error` with Try again |
| `FORM-09` | Auth CTAs before provider ready | disabled in `loading` |
| `DOM-03` | “Account” vs tenant | vocabulary table; empty account-access strip |
| `CARD-12` | Surface implying a workspace the server does not bind | no org switcher, no guessed name |
| `REF-15` | Hard-wired Clerk in domain chrome | `@clerk/react` only in SPA auth shell |
| `CARD-16` | Clerk outage must not kill API keys | outage copy is portal-only |
| `CARD-15` | Sign-out vs key revoke | logout does not revoke keys |
| `CARD-06` | Screen code before inventory | this document + JSON before `apps/app-portal` |
| `UI-06` | Irreversible primary actions were mapped on non-overlays | Single-use claim and last-key revoke retain preview/confirmation with secondary/destructive final actions; hosted checkout is marked reversible because it opens navigation without charging |

No high finding blocks this planning extension. The JSON keeps every B0 screen/action/flow id and adds B1 planned journeys. B1 remains offline and source-backed; it does not turn provider-dependent criteria into completed evidence.

## Implementation notes (this slice, offline)

- Package: `@clerk/react` in `apps/app-portal` (not `@clerk/clerk-react`, not `@clerk/nextjs`).
- Env in browser: `VITE_CLERK_PUBLISHABLE_KEY`, optional `VITE_CLERK_FAPI`, public `VITE_PORTAL_ENABLED`.
- Routed `<SignIn />` / `<SignUp />` plus `ClerkProvider` / `UserButton` / `useAuth`.
- Test doubles live only under `src/__tests__/`. Production has no auth bypass.
- Production Clerk and Polar sandbox provisioning remain outside this lane. K/U and C/B use injected typed clients; I1 owns authenticated transport and shell wiring after both branches land.

## Remaining limitations

- No live Clerk, Polar, or WordPress evidence. CSP file is an artifact, not a deployed header.
- B1 claim, key, usage, WordPress guidance, and billing screens are mapped as PLANNED-UI only; no source implementation is claimed here.
- Backend `portal_auth` / `PortalIdentityService` were not edited.

## Not doing

See JSON `not_doing`. This assessment does not commit env/login material, read provider credentials, or edit backend `portal_auth` / `PortalIdentityService`. The B1 extension is in the same map and the companion slice document; it preserves Clerk account integration and does not redesign auth. The coordinator ran the actual WorkBay critique on preserved map WIP SHA `85416ba8` (schema-valid, 16 screens); the local lane CLI is unavailable, so the coordinator should rerun final map validation/critique after this commit. This is not live UX or vendor acceptance evidence.
