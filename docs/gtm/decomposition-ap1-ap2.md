# Decomposition — AP-1 (Business Schema) + AP-2 (Business API)

> Both are **Epic** slices from the launch plan §14 — too large for one `/offload` pass (one end-state + one `TEST_CMD`). Below, each is broken into **atomic** sub-slices, each with a self-contained end-state and a scoped verification, ready to offload one at a time.
> **Canon anchors:** `[DATA-14]` system-of-record, `[DOM-04]` reference-by-ID, `[ARCH-02]` single-writer, `[API-02]/[RES-01]` idempotent webhooks, `[API-10]` translate-at-boundary, `[ARCH-07]` ADR. Field ownership map = launch plan §6.3.
> **Ordering:** AP-1 before AP-2. Within AP-2, 2a → (2b, 2c, 2d) → 2e → 2f.

---

## AP-1 — `acx_business` Postgres schema

Single business DB on the OCI VM; `tenant_id` (UUID) is the universal key. All external systems referenced by ID only. No PII beyond email+consent (§6.3).

| Sub-slice | End-state | Scoped `TEST_CMD` / verify | Deps |
|---|---|---|---|
| **AP-1a** `tenants` | Table: `id uuid pk`, `plan text not null default 'free'`, `clerk_user_id text unique null`, `polar_customer_id text unique null`, `email citext`, `created_at/updated_at`. Migration up/down. | migration applies + reverts; insert/select round-trips; duplicate `clerk_user_id` rejected | — |
| **AP-1b** `api_keys` | Table: `id uuid pk`, `tenant_id uuid fk→tenants`, `key_hash text unique`, `scope text`, `label text`, `created_at`, `rotated_at null`, `revoked_at null`. | FK enforced (orphan insert fails); lookup by `key_hash` returns tenant; revoke sets `revoked_at` | AP-1a |
| **AP-1c** `usage_daily` | Table: PK `(tenant_id, day date)`, `count int not null default 0`. Upsert-increment helper. | 3 increments → count=3; cross-tenant isolation holds | AP-1a |
| **AP-1d** `consent` | Table: `tenant_id fk`, `scope text` (e.g. `marketing_email`), `granted_at`, `revoked_at null`. | grant→revoke round-trip; current-consent query correct | AP-1a |
| **AP-1e** `leads` + `billing_events` | `leads` (crm-lite: id, email, source, tenant_id null, stage, notes). `billing_events` audit: `event_id text unique`, `provider text`, `payload jsonb`, `received_at`, `processed bool`. | duplicate `event_id` insert rejected (**idempotency invariant** `[API-02]`); lead insert round-trips | AP-1a |
| **AP-1f** ownership-map ADR + indexes | ADR `docs/adr/business-data-ownership.md` recording the §6.3 map (SoR per datum, by-ID rule, no-dual-write). Indexes on all FKs + `email`. Assert **no schema column stores vendor-owned truth** (no password, no card, no session). | ADR exists with alternatives+consequences `[ARCH-07]`; a grep/test finds no forbidden columns; `explain` uses the FK indexes | AP-1a..e |

> **Optional AP-1g** (defer unless needed): RLS policies on business tables scoped by `tenant_id` session context — the recognition DB already does this; business API is a trusted server, so RLS here is defense-in-depth, not a launch blocker.

---

## AP-2 — Business API service (FastAPI on OCI)

The **single authority** for tenant lifecycle `[ARCH-02]`. Vendors notify it via idempotent webhooks; recognition trusts tenant context after key validation. Same stack as recognition for deploy simplicity.

| Sub-slice | End-state | Scoped `TEST_CMD` / verify | Deps |
|---|---|---|---|
| **AP-2a** service scaffold | FastAPI app + `/health` `/ready`, config, DB session to `acx_business`, added as a compose service + systemd unit alongside recognition (bulkhead-limited). | `/health` 200 inside the stack; connects to `acx_business`; deploy is reproducible from repo | AP-1a |
| **AP-2b** tenant CRUD | Admin-guarded endpoints: create tenant (returns `tenant_id`, plan=free), get, update plan. Internal auth (admin token), not public. | create→get→update-plan round-trips over HTTP; unauthorized caller 401 | AP-2a |
| **AP-2c** key lifecycle (wraps existing minter) | Endpoints create/rotate/revoke API keys — **reuse the recognition `/admin` `manage_api_keys` mechanism**, keys hashed, scoped, tenant-bound. Business API owns *policy*; minter is *mechanism* (§7). | create key → recognition `require_auth` accepts it; revoke → recognition returns 401; **no second key SoR introduced** `[ARCH-02]` | AP-2a, AP-1b |
| **AP-2d** usage metering | Record-call ingest + daily rollup (job or endpoint) writing `usage_daily`. | N recorded calls → `usage_daily.count == N` for that tenant/day; other tenants unaffected | AP-2a, AP-1c |
| **AP-2e** recognition auth bridge | Update recognition auth middleware to validate keys against business DB (direct query or short-TTL cache) and set tenant context for RLS. **Contract/boundary change — follow `docs/workbay/contracts/`.** | valid business-DB key authorizes a recognition call; unknown key 401; tenant context scopes RLS; latency within SLO (cache if needed) | AP-2c |
| **AP-2f** idempotent webhook receiver (generic) | Skeleton that verifies provider signature, dedupes on `event_id` into `billing_events`, dispatches to a handler, marks processed. Provider-agnostic (Clerk/Polar plug in at AP-3/AP-5). | same `event_id` delivered twice → handler runs **once** `[API-02][RES-01]`; bad signature rejected; unknown event stored+ignored | AP-2a, AP-1e |

> **Boundary note (AP-2e):** this is the one sub-slice that edits the recognition service, not just the new business service. It crosses a service contract — do it under the repo's cross-service integration rules (contracts + review coverage), not as a blind offload. Consider keeping AP-2e operator/Claude-supervised even if 2a–2d/2f are offloaded.

---

## Offload guidance for these sub-slices

- **Straight-to-offload (atomic, clean `TEST_CMD`):** AP-1a, 1b, 1c, 1d, 1e, AP-2a, 2b, 2d, 2f.
- **Offload with care (touches existing systems / contracts):** AP-1f (ADR needs judgment), AP-2c (reuses the minter — must not fork key SoR), AP-2e (recognition contract change — supervise).
- Suggested first offload wave (parallel, independent): **AP-1a → then AP-1b/1c/1d/1e in parallel**. Then AP-2a, then 2b/2c/2d/2f. AP-2e last, supervised.
- Each offload brief = that row's End-state (as the objective) + its `TEST_CMD` + a known-red baseline ("table/endpoint does not exist; test fails to import/connect").
