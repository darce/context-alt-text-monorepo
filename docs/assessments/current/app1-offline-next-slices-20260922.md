# APP-1 offline next-slices assessment — reconciliation R and browser B

Date: 2026-09-22 UTC. Status: context-gathering only; no source or product decision is made here.

This assessment is against the checked-out source at `HEAD=f623b2e9` (the supplied
`c6c080c7` is not resolvable in this history-stripped checkout). It covers only
offline-executable work for R and B. Clerk/Polar credentials were not accessed;
no live browser, authentication, vendor, or paid acceptance is claimed.

## Decision summary

R is not complete. The provider adapter already has a typed, bounded subscription
enumerator, but `BillingReconciliationWorker` only drains known webhook-inbox rows.
There is no durable reconciliation cursor, lease/fence, remote-orphan processing,
or audited retry path in the current model/migration.

B is not started. The backend portal routes and Clerk JWT verifier exist, but
`apps/app-portal/**`, a browser mount, browser tests, and a precise CSP policy are
absent. The approved host shape is a static SPA at `https://app.altcontext.com`
with `/portal/*` proxied to the API; the API host remains the webhook host.

Both lanes have offline work that is not blocked solely by vendor accounts:

- R can implement and fake-test the cursor/lease/remote-orphan processor once C
  publishes the shared persistence/protocol boundary.
- B can build the Clerk/account shell and mocked portal journey once the mount and
  CSP allowlist are frozen. The recovered UX inventory should be preserved and
  bounded-repaired, not redrawn.
- Live rehearsal remains a separate prerequisite: production Clerk provisioning,
  Polar sandbox account/catalog/webhook setup, DNS/SSL, and sanitized genuine
  fixtures.

## Verified current source facts

### R: provider, worker, repository, and schema

| Surface | Current fact | Consequence for remaining work |
| --- | --- | --- |
| Provider protocol | `recognition/domain/portal_contracts.py:194-279` currently defines `CheckoutSession`, `EnumerationPage`, and `BillingProvider.create_checkout_session(..., idempotency_key, attempt_id)`, `create_portal_session`, `retrieve_state`, `retrieve_checkout`, `enumerate_subscriptions(cursor, limit, request_timeout)`, `verify_webhook(raw_body, headers)`, and `parse_event`. | R must consume these signatures; it must not invent another vendor method or infer state from a redirect. |
| Polar checkout/state | `recognition/infrastructure/billing/polar_provider.py:188-328` sends an attempt-owned idempotency key, scopes customer/subscription ids by environment, retrieves known state, retrieves one checkout, and calls the list endpoint. `_assert_environment_matches_base_url` at `:417-423` rejects sandbox/live host mismatch. | Durable checkout-attempt work is existing prior art, but ambiguous attempts still need a reconciliation consumer. |
| Polar enumeration parser | `PolarBillingProvider.enumerate_subscriptions` at `:307-328` accepts a decimal page cursor, bounds `limit` to 1..100, sends `page`, `limit`, and optional `organization_id`, and returns `EnumerationPage`. `_enumeration_page_from_response` at `:858-888` requires `items` plus `pagination.max_page`, emits the next decimal cursor, and marks exhaustion. `_subscription_item_state` / `_tenant_id_from_enumeration` at `:891-942` discard malformed, seller-mismatched, or unparseable tenant identities. | Parser prior art exists, but silently dropping a bad remote item is not the required observable quarantine/audited-retry behavior. C/R must decide the typed quarantine result without accepting email or request context as a tenant. |
| Webhook verifier | `PolarBillingProvider.verify_webhook(raw_body, headers)` at `:330-366` receives the full header map, bounds the body to 1 MiB, checks delivery id/timestamp/signature, and tries Standard Webhooks plus the legacy key form at `:470-520`. | This is implementation prior art and synthetic-test coverage, not genuine Polar sandbox evidence. Do not present it as live vendor acceptance. |
| Worker seam | `scripts/billing_reconcile.py:161-205` has a repository protocol with only `list_pending_webhooks`, `get_projection`, `upsert_projection`, and `mark_webhook_processed`; `ReconcileConfig` at `:207-276` bounds provider timeout, retries, backoff, polling, and stall count. | The worker has no cursor or lease interface to call. C must publish that boundary before R can safely add remote enumeration. |
| Known-event processing | `BillingReconciliationWorker.run` at `scripts/billing_reconcile.py:341-451` lists a bounded inbox batch. `_process_row` at `:453-611` checks a row, releases the DB transaction before provider I/O, retrieves known state, compares tenant/customer ids, upserts the projection, applies entitlement state, then marks the inbox row. `_context_and_projection` at `:717-775` derives tenant/customer/subscription ids from event payload/projection; `_retrieve_state` at `:789-815` calls only a known-state method. | This is a usable known-projection path, not remote-orphan recovery. `enumerate_subscriptions` is not called anywhere in the worker. |
| Claim/lease behavior | `_claim_row` at `scripts/billing_reconcile.py:869-873` only checks `received`/`failed`; it does not acquire a durable lease. `_recheck_row` at `:817-867` compares status and attempt count, not an owner/fence. | Concurrent workers can inspect the same pending row; a durable owner token and stale-writer rejection are still required. |
| Retry/quarantine prior art | `BillingRepository.mark_webhook_processed` at `recognition/infrastructure/repositories/billing_repository.py:290-336` increments attempts, applies bounded backoff, and changes max-attempt failures to `discarded` with `quarantined_at`. `list_pending_webhooks` at `:338-358` returns only received/failed rows below the max attempt count. | This is inbox retry state, not an operator-audited retry command for remote-orphan/item quarantine. Preserve it and add a distinct, observable path rather than treating `discarded` as recoverable by magic. |
| Projection contract | `BillingRepository.upsert_projection` at `:147-249` is tenant-scoped, one row per tenant, rejects provider changes, ignores duplicate/stale event positions, and stores the event position in `BillingSubscriptionProjection.updated_at` because there is no separate event-position column. Model constraints are at `db/models/portal_billing.py:205-235`. | Do not overload `updated_at` as a global enumeration cursor. Remote item identity and provider/environment/seller namespace need an explicit C-owned contract. |
| Existing billing tables | `BillingWebhookInbox` is `db/models/portal_billing.py:318-338` with `(provider, provider_event_id)` uniqueness, payload, attempts, next-attempt, quarantine timestamp, and status. `BillingCheckoutAttempt` is already present at `:238-315`; its status/indexes are also emitted by `db/migrations/versions/001_identity_schema.py:838-912`. | Checkout persistence is useful prior art. The inbox key currently has no environment/seller-account columns, so C must adjudicate namespace compatibility before live multi-account use. |
| Cursor/lease/fence schema | There is no `billing_reconciliation_cursor`, `lease_owner`, `lease_until`, or `last_progress_at` in `portal_billing.py` or `001_identity_schema.py`. The only billing-side `fence_token` search hit is the usage reservation (`UsageReservation` at `portal_billing.py:131-165`), which is a different ledger and cannot serve as a billing-scan lease. | R cannot claim resumability, fencing, or healthy progress from the current schema. Migration/upgrade/RLS ownership belongs to C/G5, not this assessment lane. |

### B: current API/auth boundary and absent browser surface

| Surface | Current fact | Consequence for remaining work |
| --- | --- | --- |
| Portal HTTP routes | `recognition/interface_adapters/http/routers/portal.py:698-765` has `GET /portal/me` and `POST /portal/onboarding/claim`; `:796-869` has `POST /portal/billing/checkout` and `/portal/billing/manage`; keys are `:872-999`; usage is `:1050-1113`. Claim requires verified identity/email and Origin, forbids client tenant selection, and commits atomically. Checkout uses server-selected catalog/return URLs and durable checkout service; manage requires a mapped provider customer. | B can consume existing route contracts with mocked responses. It must not add a second claim/checkout router or infer tenant state in the browser. |
| Backend mount | `api/main.py:568-605` configures CORS and includes portal/webhook routers only when `RECOGNITION_PORTAL_ENABLED` is true. CORS allows configured origins, bearer/key/tenant/content/idempotency headers, and does not mount static browser assets. | The backend is not the browser app. B owns the SPA; H/U/D retain API, composition, and host ownership unless a later handoff says otherwise. |
| Clerk verifier | `portal_auth.py:133-192` requires `ACX_CLERK_ISSUER`, `ACX_CLERK_JWKS_URL`, `ACX_CLERK_AUDIENCE`, and `ACX_CLERK_AUTHORIZED_PARTIES`. `:515-554` verifies issuer, `aud`, `azp`, expiry/clock skew, RS256, and optional email claims; `:681-689` requires `email_verified` and non-empty email for portal access. `:728-779` separates pre-tenant verified identity from tenant-bound principal. | Frozen browser behavior is Clerk person session → backend admission; a Clerk organization, email local-part, or browser-supplied tenant id is never a tenant authority. |
| Frontend existence | No `apps/app-portal/**` files, `portal_ui.py`, browser package, static mount, or browser test exists in this checkout. | B is an implementation slice, not an integration/review of existing UI. |
| CSP | The source has no portal CSP header/directive implementation. Plan 0001 only says that precise CSP and `frame-ancestors` evidence is required (`docs/plans/0001-app-altcontext-beta-clerk-polar-task-plan.md:181`); it does not freeze a directive allowlist. | Exact CSP is an unresolved contract prerequisite. Do not claim the candidate UX patch or host runbook is CSP-complete. |

### Approved host and Clerk shape in current docs

The current operational docs establish the following offline planning boundary:

- `docs/runbooks/app-portal-deploy.md:19-30` reserves `https://app.altcontext.com`;
  `/portal` and `/portal/*` reverse-proxy to `prod-api:8000`; `/` is a static SPA
  with history fallback; admin, internal, unrelated API, and webhook paths are
  not exposed on this host. The Polar webhook remains on
  `https://api.altcontext.com/billing/webhooks/polar` (`:105-109`).
- `docs/runbooks/clerk-production-auth.md:17-33` names `app.altcontext.com` as the
  primary application and `clerk.altcontext.com` as the Clerk FAPI custom host;
  `:41-67` requires distinct `aud` and `azp`, with authorized party exactly
  `https://app.altcontext.com`.
- Only browser-safe `VITE_CLERK_PUBLISHABLE_KEY` and `VITE_CLERK_FAPI` are written
  for a future frontend (`clerk-production-auth.md:130-147`); `CLERK_SECRET_KEY`
  remains backend-only.

This verifies host, route split, mount shape, env names, and JWT claim inputs. It
does not verify a deployed host, a live Clerk instance, or an exact CSP allowlist.
The stale Plan 0002 `portal_ui.py`/server-side integration suggestion is not the
browser ownership contract for this lane; the reserved surface is the static
`apps/app-portal/**` SPA plus the existing portal API.

## Existing prior art and recovered UX disposition

Relevant planning/source prior art is already present in:

- `docs/specs/app-portal-account-billing-spec.md:331-427` — typed provider,
  bounded Polar enumeration, opaque cursor, no network while holding a DB lock,
  quarantine requirements, and the proposed cursor/lease shape. It is explicitly
  a proposed planning contract, not proof that the current source implements it.
- `docs/plans/0002-app-altcontext-launch-continuation-task-plan.md:136-158` — R
  recovery obligations and B journey obligations; use for ownership history, not
  as evidence of a shipped browser.
- `docs/assessments/current/app1-usage-schema-fix-groups-20260922.md:81-115` —
  G1/G2/G3 disjoint ownership and the G2 → G3 data edge. Current source shows
  scene ingress wiring in `describe.py:1779-1855` and `usage_admission.py:123-180`,
  while G3 remains pending: normal async `202` leaves the usage ticket reserved
  for the worker, but `_run_async_describe_job_and_release` at
  `describe.py:1863-1879` only releases the process-local image gate and does not
  call `commit_fenced`/`release_fenced`.
- `docs/runbooks/app-portal-deploy.md` and `docs/runbooks/clerk-production-auth.md`
  — host/auth prerequisites above.
- The recovered candidate UX patch supplied with this task (not present in the
  worktree): `docs/assessments/current/app1-account-ux-map.md` plus
  `docs/ux-maps/app-portal.uxmap.json`. It correctly preserves Clerk-as-person,
  backend tenant admission, no OrganizationSwitcher/fake tenant, one-time local
  key boundaries, signed-out/signed-in/not-admitted/outage states, and the
  `apps/app-portal/src/App.tsx` target.

Integration posture: preserve the candidate inventory after review; it does not
need a new screen map. It needs bounded repair before it becomes implementation
authority: mark every screen as proposed until source exists; resolve hosted
Account Portal versus embedded `@clerk/react` after the supported package path is
confirmed; map claim/`/portal/me`/checkout/manage response states exactly; define
the public portal flag and Clerk-outage distinction; add the exact CSP allowlist;
and remove any wording that implies live Clerk/vendor acceptance. No candidate
file is integrated by this context-only lane.

## Frozen contracts versus operator prerequisites

### Planning-frozen for offline implementation (not live-proven)

1. A verified Clerk `iss` + `sub` is identity only. A local tenant UUID is created
   or resolved by backend admission; no email local-part, Clerk organization, or
   browser tenant header may create a claim (`DOM-03`, `CARD-12`).
2. The current `BillingProvider` signatures above are the handoff boundary. R
   consumes typed `BillingState`/`EnumerationPage`; it does not derive a tenant
   from email or invent a Polar endpoint (`REF-15`, `CARD-06`).
3. Enumeration is bounded: provider page size 50 for this lane, at most 20 pages
   per `--once` run, opaque persisted cursor, per-item isolation, and no network
   I/O while a cursor row lock is held (`GRPH-09`, `GRPH-31`, `PERF-13`). A page
   timeout or wholly unprogressed run is failure, not healthy completion.
4. Known projections and remote orphans are separate recovery paths. Mismatched
   seller/environment/customer/tenant identity is quarantined and auditable; it
   is never silently mapped from request context. Ambiguous checkout attempts are
   retrieved before a new provider mutation.
5. Portal POSTs retain bearer auth, verified email, Origin/CSRF checks, no-store
   for secret-bearing responses, server-selected catalog and return origins. A
   redirect never grants paid entitlement. Existing local API keys remain backend
   authority.
6. G3 owns terminal usage settlement: HTTP `202` is pending; worker success
   commits, pre-pickup refusal/failure releases, restart reclaim is fenced, and
   stale callbacks cannot settle a newer reservation. Browser usage copy must
   remain honest until this dependency is green.

### Operator or live-evidence prerequisites (not blockers for all offline work)

- Provision Clerk production for `app.altcontext.com`, custom FAPI/DNS/SSL, the
  four backend auth settings, session-token `aud`/`email`/`email_verified`, and
  the exact authorized party. The runbook says credentials do not exist yet.
- Provision a Polar sandbox organization/OAT, seller account, product catalog,
  webhook secret, allowed origins, and sanitized genuine webhook fixtures. No
  live or sandbox credential is available to this worker.
- Supply `APP_PUBLIC_ORIGIN`, `APP_ALLOWED_ORIGINS`, catalog mapping, seller
  account, grace/stale-entitlement policy, and the final CSP directives. These
  are operator inputs; do not guess them from source or docs.
- Run later V evidence: two-tenant browser sign-in/claim/key/WordPress flow,
  sandbox checkout/webhook/cancel/refund/expiry, genuine signature fixtures,
  host-route denial, CSP/Clerk loading, restore/reconciliation, and no live
  charges. Offline mocks may establish contract behavior only.

## Minimal implementation groups and ownership

These are proposed disjoint groups for later dispatch; they are not claims that
the paths are currently free of other coordinator assignments.

| Group | Sole owned paths | Deliverable |
| --- | --- | --- |
| C0 — recovery contract/schema (dependency of R) | `recognition/domain/portal_contracts.py`; `recognition/infrastructure/billing/polar_provider.py`; `db/models/portal_billing.py`; `db/migrations/versions/001_identity_schema.py`; a new `recognition/infrastructure/repositories/billing_reconciliation_repository.py` | Freeze cursor key `(provider, environment, seller_account, kind)`, opaque cursor, lease owner/expiry/fence, progress timestamp, per-item quarantine/audit/retry shape, upgrade/RLS behavior, and the provider result semantics. Do not make R edit the existing shared billing repository or migration. |
| R1 — reconciliation processor | `apps/prototype-description-service/scripts/billing_reconcile.py`; if a separate operator command is needed, new `apps/prototype-description-service/scripts/billing_reconcile_retry.py` | Keep known-inbox recovery; add leased known-state, remote-subscription, and ambiguous-checkout loops; commit lease before network; bound pages/items/time; isolate/quarantine bad items; persist cursor only after progress; return non-zero on no progress; expose audited retry. |
| B0 — browser app/mount | `apps/app-portal/**` (one owner for `package.json`, `src/main.*`, `src/App.*`, API client, auth adapter, features, tests, and styles) | Build the static SPA against current `/portal/*` routes, Clerk publishable env only, mocked provider/backend seams, explicit loading/unavailable/not-admitted/outage states, and accessible keyboard/mobile flows. Do not split `App.tsx`/`main.tsx` ownership. |
| H/U/D — integration dependencies | Existing `recognition/interface_adapters/http/routers/portal.py`, `portal_auth.py`, `portal_composition.py`, `api/main.py`, host/Caddy/runbook paths, and scene/G3 paths remain with their current owners. | H/U/D publish stable response/CORS/flag/host/CSP contracts. B consumes them; B does not silently edit these shared paths. |

R1 must not add cursor columns to `billing_repository.py` while C0 owns the
shared schema/repository boundary. B0 must not edit `portal.py`, `portal_auth.py`,
`api/main.py`, Caddy, or Clerk/Polar credentials. The candidate UX docs are
preserved as evidence and are not regenerated by this lane.

## DAG: data dependencies versus path conflicts

```text
                    (data/interface edges)
 C0 recovery schema/protocol ───────► R1 reconciliation processor ──► V evidence
          │                                      │
          └──────────────► H billing/portal schemas ───────► B0 browser app ──► V
                                             ▲                 │
                                             │                 └──► D host deploy
                                  U + G3 usage/terminal truth ─────► B0
```

| Edge | Type | Exact reason |
| --- | --- | --- |
| C0 → R1 | Data dependency | R1 cannot lease/advance a cursor or persist quarantine until C0 publishes the row/repository/fence contract; R1 then consumes `enumerate_subscriptions` and `retrieve_checkout`. |
| H → B0 | Data dependency | Browser actions need current claim/key/usage/checkout/manage schemas, status/error vocabulary, and no-store/CORS behavior from existing portal HTTP ownership. |
| U + G3 → B0 | Data dependency | Usage states and async result/terminal truth must not show a paid/available count while reservations remain unsettled; G3 is currently pending. |
| B0 → D | Artifact dependency | D can host only a real SPA build; current deploy runbook explicitly refuses a missing/empty frontend. |
| R1 ↔ C0 | Path conflict only if R1 edits shared billing/model/migration files | Keep R1 to the worker/command paths and give schema/repository ownership to C0. This conflict must not be mistaken for a precedence edge. |
| B0 ↔ H/U/D | Path conflict only if B0 edits backend/composition/host files | Keep B0 in `apps/app-portal/**`; existing API, composition, `api/main.py`, and Caddy owners integrate at handoff. |
| R1 ↔ G3 | No path conflict | They use separate billing-script versus scene-worker paths; their result contracts meet only at V. |

## Behavioral acceptance tests

These are the minimum offline RED/GREEN cases for the named slices. They are
acceptance requirements, not test receipts from this context-only lane.

### R acceptance

- **R-01 provider contract:** fake `BillingProvider` records exact calls. Known
  projection recovery uses `retrieve_state` with bounded timeout; ambiguous or
  `provider_requested` checkout recovery uses `retrieve_checkout`; no new checkout
  mutation is attempted while the old attempt is unresolved.
- **R-02 orphan discovery:** a page containing a valid environment-scoped
  `customer.external_id` with no local projection is mapped/quarantined according
  to the frozen C0 result. An email-only, foreign environment, foreign seller,
  malformed UUID, missing local admission, or customer mismatch creates no tenant
  and is observable with a reason and retry identity. One bad item does not abort
  the other items on the page.
- **R-03 cursor bound/resume:** `--once` uses `limit=50`, processes no more than 20
  pages/1000 items, persists the opaque next cursor only after item progress, exits
  with the cursor for the next run, and resumes without skipping or reprocessing a
  committed page.
- **R-04 lease/fence:** concurrent workers cannot own the same cursor; an expired
  lease can be stolen with a newer fence; the old owner cannot advance the cursor,
  clear quarantine, or mark an item processed. The database lock is committed
  before any provider GET, and provider timeout cannot leave a row lock held.
- **R-05 health/stall:** leased-but-zero-page-progress, malformed page, timeout,
  or exhausted retry budget yields a non-zero `--once` report and an observable
  failure/quarantine. A healthy exit requires cursor/item progress or a verified
  exhausted cursor, never merely a successful lease acquisition.
- **R-06 audit/retry:** quarantine stores provider/environment/seller/item identity,
  reason, attempt, fence, and timestamps without secrets or unnecessary PII. An
  explicit audited retry requeues only the selected item/cursor and is idempotent;
  retry cannot invent a tenant or bypass seller/environment checks.
- **R-07 known-event isolation:** duplicate/stale inbox events remain harmless;
  tenant/customer mismatches remain pending or quarantined per the frozen contract;
  entitlement is applied only after authoritative state and a durable projection,
  then the inbox row is acknowledged.

Existing unit anchors are `recognition/tests/unit/test_app1_billing_provider.py`,
`test_app1_billing_reconcile.py`, and `test_app1_billing_repository.py`.
They cover adapter/inbox behavior, not the missing cursor/lease/orphan receipt.
Add focused fake-provider tests and a real PostgreSQL transaction/concurrency
receipt owned by the C0/G5 implementation group before claiming R complete.

### B acceptance

- **B-01 build/secrets:** a local mocked build loads only
  `VITE_CLERK_PUBLISHABLE_KEY`/`VITE_CLERK_FAPI`; no `CLERK_SECRET_KEY`, OAT,
  webhook secret, raw API key, or invitation token appears in source, bundle,
  server-rendered HTML, local storage, logs, or analytics.
- **B-02 unavailable/loading:** missing publishable key, disabled public portal
  flag, Clerk loading, and bounded Clerk failure each render an explicit designed
  state. Sign-in/create-account are disabled until Clerk is ready; outage copy
  does not claim API-key or backend failure. No homemade password field is used.
- **B-03 account transitions:** mocked Clerk session transitions signed-out →
  sign-in/sign-up → signed-in → sign-out. User identity is shown, but tenant/
  workspace remains empty until `/portal/me` or claim returns backend authority;
  no organization switcher or email-derived tenant appears.
- **B-04 claim/admission:** claim sends bearer JWT, verified-email state, Origin,
  and invitation token to `/portal/onboarding/claim`; missing/mismatched Origin,
  tenant selection, unverified email, replay, not-admitted, and identity outage
  map to the current backend vocabulary without exposing another tenant.
- **B-05 keys/usage:** mocked key list/create/rotate/revoke preserves one-time
  secret display and no-store behavior; keys remain local backend authority.
  Usage renders unknown/expired/capped/outage states honestly and never fabricates
  paid allowance or treats polling as billable.
- **B-06 checkout/manage:** checkout sends server-selected `plan_code`,
  Idempotency-Key, Origin, and no tenant selection; pending/ambiguous/succeeded,
  expired, already-subscribed, disabled, and provider-unavailable responses are
  distinct. Manage is unavailable without a customer mapping. A return URL alone
  never changes entitlement.
- **B-07 browser/host security:** static history fallback serves only the app
  routes; `/admin`, internal API, unrelated service routes, and webhook paths are
  denied on the app host; `/portal/*` reaches the API host. Once D freezes the
  CSP, test Clerk FAPI/script/connect/frame directives, `frame-ancestors`, and
  absence of unsafe wildcard/secret exposure. This case cannot be green before
  the exact CSP is published.
- **B-08 accessibility/responsiveness:** keyboard-only sign-in/sign-up/back/
  sign-out/retry/key-copy/checkout flows, focus return, status live regions,
  mobile layout, and unavailable/error states are covered in the mocked browser
  suite.
- **B-09 live gate (later V, not offline):** two tenants complete the real Clerk
  browser flow against the deployed host, then sandbox Polar checkout/webhook and
  WordPress first-caption flow with genuine sanitized fixtures. No live charge is
  permitted; mocked/offline results cannot satisfy this case.

## Concrete blockers and next ready slices

Ready after a bounded C0 contract handoff:

1. **R1 offline recovery slice:** add cursor/lease/fence repository consumption,
   remote-orphan and ambiguous-checkout loops, per-item quarantine/audited retry,
   and no-progress exit behavior in the worker-owned paths; exercise fake provider
   cases R-01..R-07.
2. **B0 offline browser slice:** scaffold the reserved static SPA, preserve the
   recovered UX inventory, implement Clerk adapter and API seams with offline
   mocks, and cover B-01..B-08. This does not need a live Clerk account.

Concrete blockers for completion, not for all offline implementation:

- C0 has not published the durable reconciliation cursor/lease/fence/quarantine
  schema and upgrade/RLS contract. Current source cannot support R claims by
  scanning local projections alone.
- G3 worker settlement is pending; B can implement honest pending states, but the
  end-to-end usage/scene acceptance cannot pass until worker terminal settlement
  and restart fencing land.
- `apps/app-portal/**` and the precise CSP directive allowlist are absent. Host
  route/mount documentation is present; CSP acceptance remains unresolved.
- Clerk production and Polar sandbox accounts/catalog/fixtures are unprovisioned.
  This blocks live evidence only; it does not justify marking the offline R/B
  slices wholly blocked.
