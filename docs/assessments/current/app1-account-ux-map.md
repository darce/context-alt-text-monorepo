# APP-1 account UX map — inventory and ASCII screens

Date: 2026-09-22. Status: PROPOSED inventory for `portal-uxmap`; no browser screen is implemented. SSOT: [`docs/ux-maps/app-portal.uxmap.json`](../../ux-maps/app-portal.uxmap.json). Plugin map precedent: `apps/prototype-wp-alt-context/docs/ux-maps/*.uxmap.json`.

Canon (stable IDs, latest, never pin): [heuristics-canon](https://github.com/darce/heuristics-canon) `REF-15`, `CARD-06`, `CARD-15`, `DOM-03`. Also `NAV-08`, `NAV-07`, `RLSE-04`, `FORM-09`, `CARD-12`, `CARD-16`.

## Decision

Author the account screen contract before browser code (`CARD-06`). Visible **Sign in**, **Create account**, **User**, and **Sign out**. Unavailable configuration is a designed screen with those controls disabled or absent. Clerk authenticates a person. Tenant UUID and API keys stay existing backend authority. No fake tenant claims (`DOM-03`). Wrap Clerk so a later identity swap is an adapter change (`REF-15`, `CARD-16`). Sign-out is cheap and reversible at session scope; key revoke is not this surface (`CARD-15`).

All screens and flows below remain **PROPOSED** until browser code exists. Production Clerk and the Polar sandbox are unprovisioned for this offline slice; this document records the contract and does not claim live-provider evidence.

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

`code_ref` targets `apps/app-portal/src/App.tsx` when browser code is implemented; no provider CLI setup or application ID is required for this offline inventory.

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

`loading`: Account may be present; account access strip “Checking account…”. `empty`: signed in, no tenant UUID — **do not** fill with email local-part or a Clerk organization (`CARD-12`). No `OrganizationSwitcher`. The account menu and Sign out remain reachable while identity is loading or ready.

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

Backend may distinguish `tenant_not_eligible` / `email_unverified` / `claim_missing`; UI uses one non-enumerating “account access not ready” family unless a verified-email retry is explicitly required. Sign out remains (`NAV-07`). No tenant, keys, or billing are shown.

### Sign-in unavailable (provider outage) — `error`

```text
+-- AltContext account -----------------------------------------------------+
| AltContext                                                                |
| Account                                                                   |
| status: Sign-in is temporarily unavailable.                               |
| [ Try again ]                                                              |
+----------------------------------------------------------------------------+
```

Bounded wait before this state (`INT-08`). WordPress API-key recognition is a different failure domain and is not claimed broken here (`REF-15`).

### Sign out exit

```text
+-- Signed out again ------------------------------------------------------+
| You are signed out.                                                       |
| → signed-out chrome                                                        |
+----------------------------------------------------------------------------+
```

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
| Sign out | `logout-complete` → signed-out | Sign in restored |
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
| `portal-account` | `empty` | The session exists but backend account access is not linked; no tenant substitute or key/billing control is enabled. |

## Critique (advisory)

| ID | Finding | Fix in this map |
| --- | --- | --- |
| `NAV-08` | First screen needs obvious doors | Sign in + Create account |
| `NAV-07` | Overlay/error traps | Back / Sign out always present when a session exists |
| `RLSE-04` | Empty config must not be a blank crash | `portal-unavailable` |
| `FORM-09` | Auth CTAs before provider ready | disabled in `loading` |
| `DOM-03` | “Account” vs tenant | vocabulary table; empty account-access strip |
| `CARD-12` | Surface implying a workspace the server does not bind | no org switcher, no guessed name |
| `REF-15` | Hard-wired Clerk in domain chrome | `@clerk/react` only in SPA auth shell |
| `CARD-16` | Clerk outage must not kill API keys | outage copy is portal-only |
| `CARD-15` | Sign-out vs key revoke | logout does not revoke keys |
| `CARD-06` | Screen code before inventory | this document + JSON before `apps/app-portal` |

No high finding that blocks planning the account chrome slice. Keys, Polar, and invitation field remain out of this map (`not_doing` in the JSON); B1 later extends this same SSOT.

## Implementation notes (next slice, offline-capable)

- Package: `@clerk/react` (not `@clerk/clerk-react`, not `@clerk/nextjs`).
- Env in browser: `VITE_CLERK_PUBLISHABLE_KEY` only.
- Official React/Vite path: wrap `ClerkProvider`, then `Show` / `SignInButton` / `SignUpButton` / `UserButton` (or routed `<SignIn />` `<SignUp />`).
- Manual integration and offline test doubles are supported. Production Clerk and Polar sandbox provisioning are outside this lane; do not run account setup commands or read credential files.
- No accountless replacement and no hardcoded rescued application ID.

## Not doing

See JSON `not_doing`. This assessment does not implement screens, does not commit env/login material, and does not edit backend `portal_auth` / `PortalIdentityService`. Claim/invitation, keys, usage, and billing journeys remain explicitly out of map until the later B1 extension.
