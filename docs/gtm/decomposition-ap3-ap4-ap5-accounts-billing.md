# Decomposition — AP-3 (Clerk Auth) + AP-4 (Dashboard) + AP-5 (Polar Billing)

> The three **Epic** slices from the launch plan §14 that form the self-serve accounts + money path (Phases 1–2). Each is broken into **atomic** sub-slices with a self-contained end-state and a scoped `TEST_CMD`, ready to offload one at a time.
> **Engineering heuristics v2** (stable IDs, cite in every slice): [`docs/strategy/engineering-heuristics.md`](../strategy/engineering-heuristics.md). Business rules: [`docs/strategy/business-marketing-heuristics.md`](../strategy/business-marketing-heuristics.md).
> **Depends on:** AP-1 (`acx_business` schema) + AP-2 (business API), decomposed in [`decomposition-ap1-ap2.md`](decomposition-ap1-ap2.md). Ownership map = launch-plan §6.3.
> **Ordering:** AP-1/AP-2 → AP-3 → AP-4 → AP-5. AP-3f and AP-5b share the idempotent-webhook pattern; build AP-3b first, reuse it.

---

## Cross-cutting invariants (apply to every sub-slice below)

- **Vendor is the system of record; you project, never dual-write** `[DATA-14]`. Clerk owns identity, Polar owns subscription truth; the business DB derives its copy from their webhook stream and references them by id `[DOM-04]`.
- **Single writer owns `plan`/`tenant`** `[ARCH-02]` — the business API writes tenant/plan; Clerk/Polar only notify it.
- **Every inbound webhook: verify signature, then dedupe** `[SEC-01]` (validate at the trust boundary) + `[API-02]`/`[RES-01]` (idempotent — a lost response plus redelivery must not double-apply).
- **Every outbound vendor call: bounded timeout + backoff + breaker** `[RES-02]`, `[API-08]`, `[RES-15]` — a hung Clerk/Polar call must not tie up a request thread.
- **The UI/API shape is its own artifact** `[API-10]` — do not leak DB column names or vendor field names into dashboard responses.

---

## AP-3 — Clerk auth + `user.*` webhooks → tenant lifecycle

| Sub-slice | End-state | Scoped `TEST_CMD` / verify | Heuristics | Deps |
|---|---|---|---|---|
| **AP-3a** Clerk app + SDK | Clerk project (dev + prod instances); SDK wired into the dashboard app for login/signup/session. | signup + login complete; a session cookie/JWT is issued and validated | `[SEC-01]` | — |
| **AP-3b** webhook receiver | Endpoint verifying the Clerk (Svix) signature and deduping on event id into an `auth_events` audit row before dispatch. | valid signed event processed **once**; redelivery of same id is a no-op; bad signature → 401 | `[SEC-01][API-02][RES-01]` | AP-1e |
| **AP-3c** `user.created` → tenant | On `user.created`: create a `plan='free'` tenant, store `clerk_user_id`, and cache `email` + marketing consent (the owned contact path). On `user.deleted`: mark tenant closed. | new Clerk signup auto-creates exactly one free tenant carrying its `clerk_user_id` + email; re-fired event does not duplicate | `[DATA-14][DOM-04]`, biz `[BOOT-01]` | AP-3b, AP-2b |
| **AP-3d** first-key provisioning | After tenant creation, mint one API key via the business API (which wraps the `/admin` minter) so the dashboard can show it immediately. | post-signup, the tenant has exactly one active key; it authorizes a recognition call | `[ARCH-02]` | AP-3c, AP-2c |
| **AP-3e** outbound-call hardening | Any dashboard/business→Clerk API call (profile fetch, etc.) is timeout-bounded with bounded retry and a breaker. | simulated Clerk latency/outage does not hang a request; breaker opens after N failures | `[RES-02][API-08][RES-15]` | AP-3a |

## AP-4 — Customer dashboard (`app.altcontext.com`)

| Sub-slice | End-state | Scoped `TEST_CMD` / verify | Heuristics | Deps |
|---|---|---|---|---|
| **AP-4a** scaffold + auth gate | Dashboard app (SvelteKit/Next per launch-plan §6.1), Clerk-gated; unauthenticated routes redirect to login. | unauth → login redirect; authed → dashboard shell renders | `[SEC-01]` | AP-3a |
| **AP-4b** API-key panel | View / create / rotate / revoke keys via the business API; raw key shown **once** on create, never re-fetchable. | each action round-trips; created key displayed once and not persisted in the client | `[SEC-01][API-10]`, `[SEC-06]` (never echo the raw key back into storage/logs) | AP-2c |
| **AP-4c** usage chart | Usage view backed by a **bounded** query (date-ranged, `LIMIT`), rendered from a translated API shape. | usage renders; the backing query is bounded, not fetch-all | `[RES-05][API-10]` | AP-2d |
| **AP-4d** install steps + upgrade | Copy-paste WP install snippet (API URL + key) on the same screen as the key (highest-drop onboarding step), plus a Polar upgrade/portal link. | snippet present next to the key; upgrade link resolves to Polar checkout/portal | biz `[PROD-01]` (activation) | AP-4b, AP-5a |

## AP-5 — Polar billing (`subscription.*` → plan enforcement)

| Sub-slice | End-state | Scoped `TEST_CMD` / verify | Heuristics | Deps |
|---|---|---|---|---|
| **AP-5a** products + checkout | Polar products for Free/Pro/Business; a checkout-link generator keyed by `tenant_id`. | a checkout URL is produced for a plan and carries the tenant reference | `[DOM-04]` | AP-1a |
| **AP-5b** `subscription.*` webhook | Signature-verified, idempotent receiver that **projects** subscription status (`active`/`canceled`/`past_due` + `current_period_end`) into the business DB. | `subscription.active` flips the tenant projection to `pro`; duplicate delivery applies once; bad signature rejected | `[SEC-01][API-02][RES-01][DATA-14]` | AP-1e, AP-3b (reuse pattern) |
| **AP-5c** plan/quota enforcement | Recognition auth path reads the tenant's plan/quota (from the business DB projection) and enforces the rate tier + monthly cap. | free tenant over cap → deterministic 429/cap message; pro tenant gets the raised limit | `[ARCH-02][RES-05]`, biz `[BOOT-06]` (the cap is the conversion trigger) | AP-5b, AP-2e |
| **AP-5d** audit + reconciliation | Every processed Polar event is recorded in `billing_events`; a reconcile job compares DB projection vs Polar as the source of truth and flags drift. | processed events all recorded; a deliberately dropped event is caught by reconcile | `[API-02][DATA-14]` | AP-5b |

---

## Offload guidance

- **Straight-to-offload (atomic):** AP-3a, AP-3b, AP-3c, AP-3d, AP-3e, AP-4a, AP-4b, AP-4c, AP-4d, AP-5a, AP-5b, AP-5d.
- **Offload with care (crosses the recognition service / contract):** **AP-5c** (touches the recognition auth path like AP-2e — supervise; it's a boundary change under `docs/workbay/contracts/`).
- **First wave (after AP-1/AP-2 land):** AP-3b (webhook pattern) → AP-3c/AP-3d in parallel → AP-4a → AP-4b/AP-4c/AP-4d in parallel. AP-5 after AP-4d exposes the upgrade path.
- Each offload brief = the row's End-state (objective) + its `TEST_CMD` + a known-red baseline ("endpoint/webhook/panel does not exist; test fails to connect") + the cited heuristic IDs so the lane inlines the rule.

**Reasoning owner (Claude/operator):** the SoR/projection model (§ cross-cutting), enforcement placement (AP-5c), the conversion-trigger tie (`[BOOT-06]`). **Junior/offload owner:** the atomic rows above.
