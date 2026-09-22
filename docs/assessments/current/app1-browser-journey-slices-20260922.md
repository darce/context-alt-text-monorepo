# APP-1 browser journey slices — source-backed planning contract

Date: 2026-09-22. Status: COMPLETED journey-slices contract and map handoff.
B0 account chrome and the N1 backend contract fix are landed and remain the
observed/source-backed foundation. The journeys below are PLANNED-UI contracts
for later browser work. Clerk production and the Polar sandbox are not
provisioned, and no provider login, secret, or environment value was read for
this packet.

The single source of UX truth is
[`docs/ux-maps/app-portal.uxmap.json`](../../ux-maps/app-portal.uxmap.json).
This document extends that map; it does not create a second map. Existing B0
screen, action, and flow IDs remain unchanged.

## Boundary and source authority

`OBSERVED-UI` means behavior already present in `apps/app-portal`. `PLANNED-UI`
means a bounded journey derived from the current backend contract and Plan
0002, not an implementation or acceptance result. Current source wins over old
offline assessments.

| Surface | Current source anchor | What this packet freezes |
| --- | --- | --- |
| B0 shell and route gate | `apps/app-portal/src/App.tsx:1-259` | Preserve `@clerk/react`, routed `/sign-in` and `/sign-up`, allowed redirect origin, session/user stale-response guards, and visible sign-out. Do not redesign auth. |
| B0 private identity client | `apps/app-portal/src/api/portalMe.ts:1-148` | `/portal/me`, bearer token, bounded 8s request, 401/403/503 mapping. The browser-fix wave additionally freezes no-store, bounded token refresh, and invalid-200 handling. |
| B0 account rendering | `apps/app-portal/src/screens/AccountScreen.tsx:4-56`; `NotAdmittedScreen.tsx:4-34`; `OutageScreen.tsx:3-20` | Person identity is Clerk-owned; tenant UUID is backend-owned; an unadmitted 403 is non-enumerating; signed-in outage keeps UserButton and Sign out. |
| Offline Clerk harness | `apps/app-portal/src/__tests__/clerkDouble.tsx:3-87`; `renderPortal.tsx:6-31`; existing B0 tests | Keep doubles test-only. They prove offline state transitions, not production Clerk. |
| Identity and claim | `apps/prototype-description-service/recognition/interface_adapters/http/routers/portal.py:87-109, 698-765`; `.../deps/portal_auth.py:681-779` | `/me` is tenant-bound; claim accepts a verified pre-tenant identity and a hashed, single-use invitation token without client tenant selection. |
| Key lifecycle | `portal.py:110-181, 881-1006`; `recognition/application/services/tenant_key_service.py:64-75, 327-548` | Metadata-only reads, one-time raw secret, idempotent create/rotate, immediate revoke, finite expiry and last-usable-key warning. |
| Usage | `portal.py:183-208, 1009-1123`; `recognition/domain/portal_contracts.py:18-24, 106-115`; `tenant_entitlement_service.py:195-245` | Nullable counts and explicit period/data source are displayed honestly; the client never calculates entitlement. |
| Billing | `portal.py:210-243, 358-453, 768-878`; `docs/specs/app-portal-account-billing-spec.md:184-237, 276-297` | Origin and idempotency boundaries, server-selected catalog, payments-disabled default, durable attempt states, manage recovery, and no redirect grant. |

### Accepted B0 invariants before B1 coding

These constraints were accepted in the B0 browser-fix wave and are recorded
here even where the current B0 source still exposes the repair seam:

| Invariant | UI contract |
| --- | --- |
| Account state ownership | Key `/portal/me` state, cancellation, and stale-response checks by Clerk `userId`/session epoch. A response from a prior person cannot populate the current session. |
| Private read policy | Account reads are `no-store`; token acquisition/refresh and API calls are bounded. Do not use cached tenant identity or an unbounded retry loop. |
| Invalid 200 | A successful response without a valid UUID `tenant_id` is invalid account data, not “not linked.” Never fill it from email, organization, or a guessed workspace. |
| Unadmitted | A tenant-bound `/portal/me` refusal is backend 403 and gets non-enumerating account-not-ready copy. Claim has its own typed `email_unverified` and `not_admitted` outcomes. |
| Signed-in outage | A 503/timeout leaves UserButton and Sign out available. Retry only the backend identity read; do not silently sign out or fabricate a tenant. |

Canon used at the point of application: `RLSE-04` for designed recovery and
no blank/half-cleared states, `NAV-11` for return/focus continuity, `HAI-01`
for honest system authority and non-invented data, `DOM-03` for person versus
tenant vocabulary, `CARD-15` for key/billing consequences, and `REF-15` for
keeping Clerk behind the existing browser adapter.

## Coordinator status and completion decision

The coordinator recorded B0 repair checkpoint `bbe099978` as landed with its
30 UI tests plus `tsc`/build, and N1 checkpoint `afa532e2` as landed with its
97 backend tests. There is no remaining F0 repair prerequisite for this
documentation contract. The coordinator's actual WorkBay critique of map WIP
SHA `85416ba8` reported a schema-valid map with 16 screens and UI-06 flags on
`submit-claim`, `confirm-revoke-key`, and `start-checkout`; the JSON map in this
handoff corrects those action semantics while retaining claim/revoke
preview-confirmation.

## Vocabulary and expiry rules

| Term | Source-backed meaning | UI consequence |
| --- | --- | --- |
| Verified identity | A signed, issuer/audience/expiry-checked portal JWT with `email_verified=true` and a non-empty email. It has no tenant yet. | May open claim. Do not show keys, usage, or billing as tenant-owned until claim or `/portal/me` binds one. |
| Tenant-bound principal | `PortalPrincipal(tenant_id, issuer, subject, email)` returned after exact identity lookup. | Every tenant route derives scope from this principal; no tenant selector or client `tenant_id`. |
| Unadmitted | Verified Clerk identity with no eligible local identity, or a claim that is unknown, expired, email-mismatched, or otherwise not admitted. Current claim UI receives 403 `not_admitted`; `/me` receives 403 `portal access denied`. | Non-enumerating copy, retry only when useful, sign out remains. |
| Invitation token | Single-use raw input sent in `invitation_token`; repository hashes it, matches normalized verified email and checks `expires_at`, then accepts it atomically. | Hold only in memory for the request. Never URL, storage, log, analytics, or support copy. |
| API-key metadata | `id`, `tenant_id`, `created_at`, `expires_at`, `revoked_at`, `rate_limit_tier`, `lifetime_seconds`. | Safe to list; hashes and raw secret are never returned by reads. |
| Raw API secret | `raw_key` on a non-replayed create/rotate issue response only. Replayed issue responses have `raw_key: null`. | One-time dialog; copy/close; close clears memory and restores focus. No refetch can recover a missing secret. |
| Expired key | `expires_at` exists and is at or before backend now; it is not usable. `expires_at: null` is no configured expiry. | Show expired metadata; do not call it revoked or silently renew it. |
| Rotated key | The predecessor remains bounded by the service's seven-day rotation grace, capped by its existing expiry, then is no longer the current primary. | Show predecessor/cutoff state; rotate only the current primary usable key. |
| Revoked key | `revoked_at` is set immediately by revoke. | No undo control; require confirmation when it is the last usable key. |
| Usage evidence | `data_source` plus nullable `used`, `reserved`, `remaining`, `allowance`, period bounds, optional `as_of`, and `status`. | Display what the backend knows; `null` is unknown, not zero. Do not compute remaining. |
| Entitlement status | `beta_active`, `paid_active`, `past_due`, `expired`, or `revoked` (`EntitlementStatus`). | `past_due` may retain only backend-provided grace; `expired`/`revoked` are closed. |
| Checkout attempt | `created → provider_requested → pending → ambiguous → succeeded/expired/canceled/failed`. `succeeded` comes from authoritative billing state, never a return URL. | Preserve `attempt_id`; an ambiguous/open attempt is recovered or replayed, not duplicated. A completed/expired/canceled attempt needs a new attempt and idempotency key. |

## HTTP contract table

All mutating portal routes return `Cache-Control: no-store` in the approved
contract. All tenant routes use bearer auth and the backend principal; browser
headers/body never select a tenant. Detail may be a string on existing auth
errors or `{ "code": ... }` on typed route errors.

| Route | Request and headers | Success response | Idempotency / expiry | Exact failures and planned UI |
| --- | --- | --- | --- | --- |
| `GET /portal/me` | `Authorization: Bearer <Clerk JWT>`; no client tenant selector. | `200 {tenant_id, issuer, subject, email}`. | Private no-store, bounded token refresh/read. 200 without a valid UUID `tenant_id` is invalid account data. | `401 invalid_portal_authorization` or auth-required detail → session verification error; `403 portal access denied` → unadmitted; `503 portal identity unavailable`/auth outage → retry while retaining sign-out. |
| `POST /portal/onboarding/claim` | `Authorization`; required matching `Origin`; `Content-Type: application/json`; no `X-Tenant-ID`, query `tenant_id`, or body `tenant_id`; body `{ "invitation_token": "..." }`. | `201 {tenant_id, issuer, subject, email, replayed:false}` first claim; `200` same bound identity replay with `replayed:true`. | No client idempotency header. Invitation row lock/uniqueness and same identity determine replay. Raw token is hashed; `expires_at` and normalized verified email are checked in the transaction. Claim → tenant link → beta grant → audit is one commit or rollback. | `401 invalid_portal_authorization`; `403 email_unverified`, `not_admitted`, `tenant_header_forbidden`, `csrf_origin_denied`; `409 invitation_consumed`, `identity_already_bound`; `422 invalid_claim_request`; `503 portal_identity_unavailable`. Unknown/expired/email-mismatch remains non-enumerating `not_admitted`. |
| `GET /portal/keys` | Tenant-bound bearer. Query `limit` (default 25, effective max 100) and opaque `cursor`; include revoked metadata is server-selected. | `{data:[metadata], next_cursor, cursor, limit, total}`; no hashes/raw secrets. | Read is bounded/cursor based. Expiry is metadata (`expires_at`); revoked rows remain visible for history. | Common key service mapping: `404 "portal key not found"`; `422 "invalid portal key request"`; `503` lifecycle-unavailable detail; unexpected service failure is `500 "portal key service unavailable"`. Retry/list refresh preserves tenant scope. |
| `GET /portal/keys/{api_key_id}` | Tenant-bound bearer and UUID path. | One metadata object: `id, tenant_id, created_at, expires_at, revoked_at, rate_limit_tier, lifetime_seconds`. | Foreign/missing key is indistinguishable from not found. | `404 "portal key not found"`; `503` lifecycle corruption/unavailable; no secret recovery action. |
| `POST /portal/keys` | Tenant-bound bearer; required `Idempotency-Key`; body `{lifetime_seconds?: positive integer, rate_limit_tier?: non-empty string}`; no tenant field. | `200 {metadata..., raw_key, replayed:false}` for first issue; replay is metadata with `raw_key:null, replayed:true`. | Service fingerprints normalized request by tenant + operation + request fields. Same key/request replays; same idempotency key with a different fingerprint is `422`. `lifetime_seconds` maps to `expires_at`; `null` means no configured expiry. | `422 invalid portal key request` or idempotency reuse; `409 tenant key limit reached` / key state conflict; `503` lifecycle unavailable. First response opens one-time secret dialog only. |
| `POST /portal/keys/{api_key_id}/rotate` | Tenant-bound bearer; required `Idempotency-Key`; body `{reason?: non-empty string}`; UUID path. | Same issue envelope. Replacement raw secret is present only on first non-replayed success. | Fingerprint includes operation, target key, reason. Old current key cutoff is `min(old expiry, now + 7 days)`; expired, revoked, already rotated, or non-primary targets refuse. | `404 portal key not found`; `409 portal key is revoked`, `api key is expired`, `api key was already rotated`, or `portal key state conflict`; `422` invalid request/idempotency reuse; `503` lifecycle unavailable. |
| `POST /portal/keys/{api_key_id}/revoke` | Tenant-bound bearer; body `{reason?: string, confirm_last_usable?: bool, emergency?: bool}`. Normal UI sends confirmation only after warning; it does not expose emergency bypass. | `200 {id, tenant_id, revoked:true}`. | No `Idempotency-Key` on this current route. If transport outcome is uncertain, refresh/list before another destructive request. `revoked_at` is immediate and irreversible in this UI. | `404 portal key not found`; `409 {code:last_usable_key_confirmation_required, confirmation_field:confirm_last_usable}` before last usable revoke; `409 portal key is already revoked`/state conflict; `422 invalid portal key request`; `503` lifecycle unavailable. |
| `GET /portal/usage` | Tenant-bound bearer. No plan/price/client allowance input. | `{tenant_id, used, reserved, remaining, allowance, period_start, period_end, period:{start,end}, as_of, status, data_source}`; count fields and `as_of` may be `null`. | Backend chooses projection/entitlement source and period. The client renders `remaining` as returned and never computes it from other fields. | `503` detail `portal usage unavailable` → outage/retry. Shape gaps remain unknown/pending; `expired`/`revoked` are closed, `past_due` only has backend grace. |
| `POST /portal/billing/checkout` | Tenant-bound bearer; required matching `Origin`; required `Idempotency-Key` matching `[A-Za-z0-9._:-]{64,128}`; body `{plan_code:string, return_path?: relative path}`. Optional `X-Tenant-ID` must match principal; query/body tenant selection is forbidden. | `200 {attempt_id, checkout_url, status, replayed}`. `checkout_url:null` when status is `succeeded`; in-progress status may be `pending` or `provider_requested`. | Server maps `plan_code` through configured `billing_product_ids`; client cannot choose price/product. Server builds allowlisted success/cancel URLs. Equivalent key+fingerprint replays the durable attempt; ambiguous/open attempts are recovered, not duplicated. Return never grants entitlement. | `403 payments_disabled` (default) or `csrf_origin_denied`; `409 checkout_ambiguous` with optional `attempt_id`, or `already_subscribed`; `422 invalid_checkout_request`, `unknown_plan_code`, `invalid_return_path`, `invalid_idempotency_key`, `idempotency_key_reuse`; `503 checkout_ambiguous` with `Retry-After: 1` or `checkout_unavailable`. |
| `POST /portal/billing/manage` | Tenant-bound bearer; matching `Origin`; body `{return_path?: relative path}`; optional matching `X-Tenant-ID`; no absolute URL. | `200 {portal_url}` for an existing mapped billing customer. | Hosted customer portal only; return URL is server-origin-selected. It cannot create a tenant or grant entitlement. | `403 payments_disabled` / `csrf_origin_denied`; `409 billing_customer_missing`; `422 invalid_return_path`; `503 billing_portal_unavailable`. |

### Header and catalog decisions

- Claim uses `require_verified_portal_identity`, so a verified identity can be
  admitted before a tenant exists. Checkout/manage and all reads use
  `require_portal_principal`. `Origin` is required on all three mutating
  claim/checkout/manage routes; `Referer` is not a substitute.
- No client request includes a tenant selector. `X-Tenant-ID` is forbidden on
  claim and only an optional matching check on checkout/manage; body/query
  `tenant_id` is rejected. This is the HAI-01/DOM-03 boundary.
- Current `portal.py` has no public plan-catalog read route. The only safe
  browser input is a configured public `plan_code` known to the coordinator and
  accepted by the server's `billing_product_ids` map. Do not invent a price,
  product ID, currency, allowance, or “free/paid” entitlement in the browser.
  With `billing_payments_enabled=false` (the current safe default), checkout
  and manage display disabled recovery and make no provider call.
- Current `portal.py` has no checkout-attempt status route. `/billing/return`
  is a client landing state only; it can retain an in-memory attempt snapshot
  and read existing usage/entitlement evidence, but it must not invent a poll
  endpoint or treat a redirect as `paid_active`.

## Usage shape and state treatment

The API response is a shape, not a permission calculation for the browser:

| Field | Type from `PortalUsageResponse` | Rendering rule |
| --- | --- | --- |
| `tenant_id` | UUID | Display only as backend identity context; never use it to select a tenant. |
| `used`, `reserved`, `remaining`, `allowance` | integer or `null` | Show each only when present. `null` is unknown; do not replace it with zero. `remaining` is authoritative only as returned. |
| `period_start`, `period_end`, `period` | required datetimes | State the represented window. Do not infer a billing plan from dates. |
| `as_of` | datetime or `null` | Show freshness when present; no promise of real-time usage. |
| `status` | `beta_active`, `paid_active`, `past_due`, `expired`, `revoked`, or `null` | Explain status exactly; `past_due` grace is backend policy. |
| `data_source` | string | `authoritative` or `pending` are current source vocabulary; unknown/unrecognized values remain labeled as source-provided, not converted to a plan. |

UI states are the map schema's closed state vocabulary (`default`, `loading`,
`empty`, `error`, `offline`, `first_time`, `edge_input`, `degraded`). Domain
status appears in copy, zones, and flow branches rather than inventing new map
state enum values:

- `loading`: request in flight; no stale count is presented as current.
- `default`: required fields are present; show backend `data_source` and
  `as_of`.
- `empty`: nullable counts or pending evidence; say “Usage is not available
  yet,” not “0 used.”
- `degraded`: `status=expired`, `revoked`, or a backend cap (`remaining=0`) is
  shown as closed/at-cap, never as a client-calculated entitlement.
- `error`/`offline`: 503 or transport failure; Retry repeats the bounded read
  and preserves focus.

## ASCII screens and state changes

These frames are planning inventory, not source. Primary actions are bracketed
and state changes are listed below each frame.

### Verified identity claim — `/onboarding/claim`

```text
+-- AltContext onboarding -----------------------------------------------+
| Claim your invited account                                             |
| Signed in as <verified email>                                          |
|                                                                        |
| Invitation token [ paste once; held in memory only                 ]   |
|                                                                        |
| [ Claim access ]       Cancel / Sign out                               |
| status: Ready to claim                                                |
+------------------------------------------------------------------------+
```

`loading`: disable Claim access, keep the token field and status focus, send
`Origin` plus bearer token, and never include a tenant selector. `201` moves to
the account/key shell; `200 replayed:true` does the same without another beta
grant. `403 email_unverified` becomes verification guidance; `403 not_admitted`
is generic; `409 invitation_consumed` or `identity_already_bound` stops retry
and offers support/account recovery; `422 invalid_claim_request` keeps field
focus; `503 portal_identity_unavailable` offers bounded retry. `csrf_origin_denied`
and `tenant_header_forbidden` are configuration/request errors, not invitation
diagnostics.

### API keys — `/keys`

```text
+-- Developer access: API keys ------------------------------------------+
| API keys                                                               |
| [ Create API key ]     [ Usage ]     [ Billing ]                       |
|                                                                        |
| key …7f31   created …   expires …   status: usable                    |
|                         [ Rotate ]  [ Revoke ]                         |
| key …1a90   created …   revoked …  status: revoked                     |
|                                                                        |
| Need WordPress? [ Test Connection guidance ]                          |
| status: Metadata only; raw secrets appear once after issue             |
+------------------------------------------------------------------------+
```

`loading`: list skeleton and disabled mutations. `empty`: Create is primary.
Create/Rotate success opens the secret dialog; replay success refreshes
metadata but cannot reopen a raw secret. `409 tenant key limit reached` keeps
Create unavailable until the usable key changes; `404`, `422`, `409` lifecycle,
and `503` states keep row context and offer list/retry. Revoke opens a preview
first; `last_usable_key_confirmation_required` adds the explicit consequence,
Cancel-first focus, and `confirm_last_usable` only after confirmation.

### One-time secret — dialog after create/rotate

```text
+-- Copy this API secret once -------------------------------------------+
| This secret will not be shown again.                                  |
|                                                                        |
| <raw secret in memory>                                                 |
|                                                                        |
| [ Copy secret ]                    [ Close ]                           |
| status: Not copied                                                      |
+------------------------------------------------------------------------+
```

Copy success changes status to Copied and leaves the dialog available. Clipboard
failure changes status to Copy failed with retry/instruction and no API retry.
Close clears the value and returns focus to the initiating Create/Rotate
button. A replayed response or missing `raw_key` renders a safe error/empty
dialog; it never calls a “show secret” endpoint. `NAV-11`, `RLSE-04`, and
`CARD-15` govern the return/focus and irreversibility.

### WordPress handoff — guidance overlay

```text
+-- WordPress Test Connection guidance ----------------------------------+
| 1. Copy the secret once.                                                |
| 2. Paste it into the WordPress plugin's API-key field.                  |
| 3. Run the plugin's Test Connection control.                            |
| 4. Return here to inspect, rotate, or revoke the key.                   |
|                                                                        |
| Never send the secret in a URL, screenshot, log, or support ticket.     |
| [ Back to API keys ]                                                    |
+------------------------------------------------------------------------+
```

This is guidance only. Targeted current WordPress source did not expose a
matching Test Connection anchor, so the exact menu label, plugin version, and
success/error copy require later WordPress evidence. A WordPress failure is not
automatically a Clerk, usage, or billing outage.

### Honest usage — `/usage`

```text
+-- Account › Usage ------------------------------------------------------+
| Usage period: <period_start> — <period_end>                            |
| Used: <value or unknown>     Reserved: <value or unknown>               |
| Remaining: <backend value or unknown>   Allowance: <value or unknown>   |
| Source: <data_source>  As of: <as_of or unavailable>                   |
|                                                                        |
| status: <active / pending / expired / at cap / unavailable>            |
| [ Try again ]                                                           |
+------------------------------------------------------------------------+
```

`loading` hides stale numbers; `empty` says unknown/pending; `degraded` says
expired/revoked or backend-reported cap; `error`/`offline` says temporarily
unavailable. No client arithmetic and no invented plan catalog.

### Billing and return — `/billing`, `/billing/return`

```text
+-- Account › Billing ----------------------------------------------------+
| Billing                                                                 |
| Plan: <configured public plan_code only; no guessed price>              |
| status: Payments are disabled / Ready / Checkout pending               |
|                                                                        |
| [ Continue to checkout ]     [ Manage billing ]                         |
| recovery: <attempt_id / retry / customer mapping guidance>             |
+------------------------------------------------------------------------+

+-- Billing return -------------------------------------------------------+
| We received the return. Access changes only after backend confirmation. |
| status: Pending reconciliation / canceled / expired / confirmed        |
|                                                                        |
| [ Return to billing ]                                                   |
+------------------------------------------------------------------------+
```

`payments_disabled` removes checkout/manage mutation and explains the beta
state. `pending`/`provider_requested` keeps the same attempt; `checkout_ambiguous`
shows the attempt ID and tells the user not to create another. `unknown_plan_code`,
`invalid_return_path`, `invalid_idempotency_key`, and
`idempotency_key_reuse` keep the form/error focus. `already_subscribed` moves
to authoritative billing/usage explanation. `billing_customer_missing` and
`billing_portal_unavailable` recover on the billing panel. A provider success
redirect is never `paid_active`; only backend billing state/usage evidence can
change that copy.

## Actions, flows, and focus rules

The JSON map carries the complete action and flow inventory. The non-negotiable
interaction rules are:

| Interaction | State change | Focus / destructive rule |
| --- | --- | --- |
| Claim | default → loading → account or typed recovery | Claim is a single-use mutation with preview/confirmation; field/status focus survives validation and retry. |
| Create/rotate | keys → loading → one-time secret → keys | Idempotency replay is safe; no duplicate submit. Close secret clears memory and returns focus to initiating action. |
| Revoke | row → warning → confirm or cancel → metadata/error | `Revoke` is irreversible; preview is required; last usable key warning is not dismissible by accidental Enter. Cancel is safe and focus-restoring. |
| Usage retry | loading/empty/error → bounded GET → evidence/error | Retry does not compute or mutate entitlement. Announce source/period changes. |
| Checkout | billing → durable attempt → external provider → return pending/recovery | Confirm before costly external navigation. Return focus to billing status. Redirect cannot grant. |
| Manage | billing → hosted portal → return | Hosted portal cannot select tenant or change entitlement locally; return restores billing focus. |

## Frozen browser interfaces

These are the exact per-file exports for parallel feature work. They are a
documentation contract, not source edits in this lane. Each API file declares
its own structural transport alias and its own error type; none imports a
runtime or type from a hypothetical shared module. UUIDs and datetimes are
transport strings in browser DTOs. The DTO fields below are the current
backend response models (`PortalClaimResponse`, `PortalKey*Response`,
`PortalUsageResponse`, `PortalCheckout*`, and `PortalManage*`), not new routes.

The published error shape is a compatibility shape only:

```ts
type PortalApiError = {
  status: number;
  code: string | null;
  detail: string | null;
  attemptId: string | null;
  retryAfterSeconds: number | null;
};
```

### K/U API files and component props

`src/api/portalKeys.ts` owns all names in this block; the `PortalRequest` line
is local to that file and is not exported or shared:

```ts
type PortalRequest = (path: string, init?: RequestInit) => Promise<Response>;

export type PortalKeyMetadataResponse = {
  id: string;
  tenant_id: string;
  created_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  rate_limit_tier: string | null;
  lifetime_seconds: number | null;
};
export type PortalKeyIssueResponse = PortalKeyMetadataResponse & {
  raw_key: string | null;
  replayed: boolean;
};
export type PortalKeyPageResponse = {
  data: PortalKeyMetadataResponse[];
  next_cursor: string | null;
  cursor: string | null;
  limit: number;
  total: number;
};
export type CreateKeyRequest = {
  lifetime_seconds?: number | null;
  rate_limit_tier?: string | null;
};
export type RotateKeyRequest = { reason?: string };
export type RevokeKeyRequest = {
  reason?: string;
  confirm_last_usable?: boolean;
  emergency?: boolean;
};
export type RevokeKeyResponse = {
  id: string;
  tenant_id: string;
  revoked: boolean;
};
export type PortalKeyApiError = {
  status: number;
  code: string | null;
  detail: string | null;
  attemptId: string | null;
  retryAfterSeconds: number | null;
};
export type PortalKeyClient = {
  list(input?: { cursor?: string; limit?: number }): Promise<PortalKeyPageResponse>;
  create(input: CreateKeyRequest, idempotencyKey: string): Promise<PortalKeyIssueResponse>;
  rotate(id: string, input: RotateKeyRequest, idempotencyKey: string): Promise<PortalKeyIssueResponse>;
  revoke(id: string, input: RevokeKeyRequest): Promise<RevokeKeyResponse>;
};
export function createPortalKeyClient(request: PortalRequest): PortalKeyClient;
```

`src/api/portalUsage.ts` owns these names and repeats the same structural
alias locally:

```ts
type PortalRequest = (path: string, init?: RequestInit) => Promise<Response>;

export type PortalUsagePeriodResponse = { start: string; end: string };
export type PortalUsageResponse = {
  tenant_id: string;
  used: number | null;
  reserved: number | null;
  remaining: number | null;
  allowance: number | null;
  period_start: string;
  period_end: string;
  period: PortalUsagePeriodResponse;
  as_of: string | null;
  status: 'beta_active' | 'paid_active' | 'past_due' | 'expired' | 'revoked' | null;
  data_source: string;
};
export type PortalUsageApiError = {
  status: number;
  code: string | null;
  detail: string | null;
  attemptId: string | null;
  retryAfterSeconds: number | null;
};
export type PortalUsageClient = { read(): Promise<PortalUsageResponse> };
export function createPortalUsageClient(request: PortalRequest): PortalUsageClient;
```

K/U components own and export these props locally. `sessionKey` is stable for
one Clerk session/user and is used for scope/reset; callbacks are navigation
only and carry no auth or tenant authority:

```ts
export type KeysScreenProps = {
  client: PortalKeyClient;
  sessionKey: string;
  onNavigateToUsage: () => void;
  onNavigateToBilling: () => void;
  onOpenWordPressGuidance: (keyId: string) => void;
};
export type UsageScreenProps = {
  client: PortalUsageClient;
  sessionKey: string;
  onNavigateToKeys: () => void;
  onNavigateToBilling: () => void;
};
export type OneTimeSecretDialogProps = {
  rawKey: string | null;
  replayed: boolean;
  onCopy: () => Promise<void>;
  onClose: () => void;
  returnFocusId: string;
};
```

### C/B API files and component props

`src/api/portalClaim.ts` owns the claim DTO, client, and local error shape:

```ts
type PortalRequest = (path: string, init?: RequestInit) => Promise<Response>;

export type PortalClaimResponse = {
  tenant_id: string;
  issuer: string;
  subject: string;
  email: string | null;
  replayed: boolean;
};
export type PortalClaimApiError = {
  status: number;
  code: string | null;
  detail: string | null;
  attemptId: string | null;
  retryAfterSeconds: number | null;
};
export type PortalClaimClient = {
  claim(invitationToken: string): Promise<PortalClaimResponse>;
};
export function createPortalClaimClient(request: PortalRequest): PortalClaimClient;
```

`src/api/portalBilling.ts` owns the billing DTOs, client, and local error
shape. `status` remains the backend's current string because no checkout-status
route or new enum is being introduced:

```ts
type PortalRequest = (path: string, init?: RequestInit) => Promise<Response>;

export type PortalCheckoutRequest = {
  plan_code: string;
  return_path?: string | null;
};
export type PortalCheckoutResponse = {
  attempt_id: string;
  checkout_url: string | null;
  status: string;
  replayed: boolean;
};
export type PortalManageRequest = { return_path?: string | null };
export type PortalManageResponse = { portal_url: string };
export type PortalBillingApiError = {
  status: number;
  code: string | null;
  detail: string | null;
  attemptId: string | null;
  retryAfterSeconds: number | null;
};
export type PortalBillingClient = {
  checkout(input: PortalCheckoutRequest, idempotencyKey: string): Promise<PortalCheckoutResponse>;
  manage(input?: PortalManageRequest): Promise<PortalManageResponse>;
};
export function createPortalBillingClient(request: PortalRequest): PortalBillingClient;
```

C/B components own and export these props locally. The public plan and payment
flag are configuration inputs, never client-selected prices or entitlements:

```ts
export type ClaimScreenProps = {
  client: PortalClaimClient;
  onClaimed: (response: PortalClaimResponse) => void;
};
export type BillingScreenProps = {
  client: PortalBillingClient;
  publicPlanCode: string | null;
  paymentsEnabled: boolean;
  onNavigateToReturn: (attemptId: string) => void;
  onNavigateToUsage: () => void;
};
export type BillingReturnScreenProps = {
  client: PortalBillingClient;
  publicPlanCode: string | null;
  paymentsEnabled: boolean;
  attemptId: string | null;
  onNavigateToBilling: () => void;
  onNavigateToUsage: () => void;
};
```

Every local `*ApiError` above is structurally compatible with `PortalApiError`;
feature code must not use `instanceof` against a cross-lane error class. The
factories parse only the current public DTOs and return typed clients. Feature
unit tests inject typed clients or request stubs at these boundaries; no
production auth mock or bypass is part of the contract.

`PortalMeOutcome`, `PortalMeResult`, and `fetchPortalMe` remain the existing
client contract from `src/api/portalMe.ts` for I1 integration. I1 alone creates
the real session-scoped authenticated `PortalRequest`: it adds the current
bearer token, `Origin`, `Cache-Control: no-store`, bounded timeout, and bounded
token refresh/retry, then passes that request to
`createPortalKeyClient`, `createPortalUsageClient`, `createPortalClaimClient`,
and `createPortalBillingClient`. It must not make Clerk account state a tenant
selector.

## Disjoint implementation DAG and ownership

No implementation is performed here. Later dispatch should use at most four
trees. `GRPH09` is applied as conflict coloring: red paths are shared and have
one owner; amber rows are frozen interface edges; green paths are disjoint
feature modules. `GRPH31` is applied as critical-path-first: freeze the shared
interfaces, finish the two feature branches, then integrate the shell before
the offline gate.

```text
I0  this contract + map/schema validation
 ├──► K/U keys + usage modules (green feature paths)
 └──► C/B claim + billing modules (green feature paths)

K/U ───────────────┐
C/B ───────────────┼──► I1  one app-integration owner after both groups land
                    │       App.tsx/routes/styles/config/client composition only
                    │
                    └──► V0  offline browser tests + scoped protocol smoke
```

The critical path is `I0 → feature interface freeze → K/U and C/B → I1 → V0`.
K/U and C/B do not wait on each other: each uses its local frozen clients,
DTOs, errors, and props. I1 is the only owner of the red shell paths after
both green branches land. Never open two trees that edit `App.tsx`,
`styles.css`, or client composition concurrently.

| Group | Exact owned paths | Frozen boundary / disjointness |
| --- | --- | --- |
| K/U — keys, secret, WordPress guidance, usage | `apps/app-portal/src/api/portalKeys.ts`; `apps/app-portal/src/api/portalUsage.ts`; `apps/app-portal/src/screens/KeysScreen.tsx`; `apps/app-portal/src/screens/UsageScreen.tsx`; `apps/app-portal/src/components/OneTimeSecretDialog.tsx`; `apps/app-portal/src/components/WordPressTestConnectionGuidance.tsx`; `apps/app-portal/src/__tests__/keys-journey.test.tsx`; `apps/app-portal/src/__tests__/usage-journey.test.tsx` | Owns the local key/usage DTOs, injected factories, local error shapes, and component props frozen above. `sessionKey` scopes/reset state and navigation callbacks are props; no shared-module import, App/styles edit, claim/billing client, or raw-secret persistence. |
| C/B — claim, checkout, manage, return | `apps/app-portal/src/api/portalClaim.ts`; `apps/app-portal/src/api/portalBilling.ts`; `apps/app-portal/src/screens/ClaimScreen.tsx`; `apps/app-portal/src/screens/BillingScreen.tsx`; `apps/app-portal/src/screens/BillingReturnScreen.tsx`; `apps/app-portal/src/__tests__/claim-journey.test.tsx`; `apps/app-portal/src/__tests__/billing-journey.test.tsx` | Owns the local claim/billing DTOs, injected factories, local error shapes, and component props frozen above. No shared-module import, Clerk widget rewrite, price/catalog guess, provider SDK, App/styles edit, or production auth bypass. |
| I1 — integration handoff after both groups | `apps/app-portal/src/App.tsx`; `apps/app-portal/src/main.tsx`; `apps/app-portal/src/styles.css`; `apps/app-portal/src/api/portalMe.ts`; `apps/app-portal/src/screens/AccountScreen.tsx`; `apps/app-portal/src/screens/NotAdmittedScreen.tsx`; `apps/app-portal/src/screens/OutageScreen.tsx`; config and the actual route/client registry | Single owner activated only after K/U and C/B land. Create the real authenticated no-store bounded `PortalRequest`, pass it to the four factories, key the keys subtree to session/user, wire routes/config/styles, preserve focus/sign-out, and compose feature exports. This is composition, not a feature implementation or F0 repair prerequisite. |

Backend `portal.py`, models, provider adapters, WordPress plugin source, and
production configuration are not owned by this docs lane. Backend contract
authority remains the current `portal.py`; any API change requires a new
contract decision before browser work.

## Evidence boundary and later provider criteria

| Criterion | Offline evidence allowed now | Later evidence required |
| --- | --- | --- |
| Clerk shell/account | Existing 18 B0 UI tests, Clerk double, bounded fake fetch, `tsc`/build receipts. | Real production Clerk app/origin: sign-in, sign-up, refresh, user/session swap, verified email, sign-out, and provider outage while preserving sign-out. |
| Claim | Fake verified claims plus backend contract/unit/transaction tests can check headers, statuses, replay, rollback, and non-enumerating errors. | Real Clerk-issued verified JWT against the provisioned environment and a real invitation lifecycle; no live claim is asserted here. |
| Keys/secret | Fake fetch tests can assert metadata-only reads, raw-key one-time rendering, copy/close/error focus, idempotency replay, expiry, rotation grace, revoke warning, and no storage/log/analytics. | Real WordPress plugin Test Connection with a short-lived key, expiry/revocation/rotation, plugin/network failure copy, and evidence that the secret is not echoed or retained. |
| Usage | Fake JSON can cover null/authoritative/pending/expired/cap/503 shapes; backend protocol smoke can cover response contracts. | PostgreSQL/admission/worker evidence for actual usage freshness, reservations, period/grace transitions, and outage/recovery. |
| Billing | Payments-off fake provider can cover disabled copy, configured `plan_code`, idempotency, return-path validation, pending/ambiguous/recovery, manage mapping errors, and redirect-no-grant. | Polar sandbox provisioning, configured public catalog, real hosted checkout/manage, webhook/reconciliation, expired/canceled/new-attempt, and return-before-webhook evidence. No live charge/canary is claimed. |
| UX map | JSON parse, ID/reference checks, diff review, and the coordinator's recorded WorkBay critique. | Coordinator reruns the final map validation/critique after this commit; no live UX or vendor acceptance is claimed. |

No live acceptance claim is made. The required scoped command is a protocol
smoke only, not UX proof:

```bash
uv run --directory apps/prototype-description-service --extra dev \
  python -m pytest recognition/tests/unit/test_app1_portal_contracts.py \
  -q -p no:randomly --timeout=60
```

The WorkBay UX map CLI is unavailable in this lane's PATH and no CLI package
was installed. The coordinator already ran the actual critique on map WIP SHA
`85416ba8` and recorded schema-valid 16-screen output plus the UI-06 findings
addressed in the JSON map. The coordinator should rerun the final map
validation/critique after this commit; this lane reports no live UX or vendor
acceptance evidence.

## Not doing in this lane

- No TSX, CSS, API client, backend, WordPress, provider, or environment-file
  edits.
- No Clerk or Polar login/provisioning, secret reads, live checkout, live
  WordPress test, release, or deployment.
- No client-computed entitlement, fabricated price/catalog, tenant selector,
  secret storage/logging/analytics, or redirect-based grant.
- No implementation review or fix loop; coordinator performs the separate
  post-landing review. This packet is the bounded docs/map handoff.
