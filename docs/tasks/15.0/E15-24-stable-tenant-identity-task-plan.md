# E15-24. Stable Tenant Identity and Provisioning Seam

> **Metadata**
>
> - **Date**: 2026-06-10
> - **Author**: Claude Fable 5 (claude-fable-5)
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Target Branch**: `feature/e15-24`
> - **Review Coverage Target**: 2
> - **Companion assessment**: [E15-24-architecture-coherence-assessment.md](E15-24-architecture-coherence-assessment.md)
> - **Literature citation convention**: short form `designing-data-intensive-applications.md §Partition Key Stability` refers to `literature/extracted/refactoring/distilled/designing-data-intensive-applications.md`. **The `literature/` directory is gitignored and exists only in the root checkout** (`~/Development/context-alt-text-monorepo/literature/...`) — read it from there, not from your task worktree.

## Objective

Tenant identity becomes an explicit, persisted, overridable value instead of a per-request hash of the site URL. After this task, changing a site's URL/port/scheme never orphans recognition data, local dev can reuse a canonical tenant regardless of LocalWP port, and the API key's tenant claim is the single service-side authority the plugin adopts.

## Problem Statement

`TenantIdentity::derive_from_site_url()` (`apps/prototype-wp-alt-context/src/api/class-tenant-identity.php:26-40`) computes `sha1('acx-site-tenant:' + siteurl)` on every request. The partition key for all tenant data is welded to a mutable, environment-specific value. Routing (URL, key, source) is overridable via constant → filter → option chains; identity is not — the asymmetry is the defect. Consequences observed: a LocalWP site on `localhost:10010` pointed at prod attempted to mint a throwaway tenant in the prod database; any URL change silently "becomes" a new tenant. Service-side, `ensure_tenant_exists()` (`db/tenant_context.py:22-45`) JIT-provisions placeholder tenants, masking identity drift instead of failing fast.

## Constraints

- Greenfield policy: no production users; no data migration machinery — schema changes go in `001_identity_schema.py` directly.
- The service-side authority model (API key → `tenant_claim`, 403 on `X-Tenant-ID` mismatch, `auth.py:133-226`) is correct and must not weaken.
- Sovereign model: plugin must still resolve a tenant id with zero network calls (local mode has no key).
- Plugin Boundary Rule: monorepo files only.

## Workflow Principles

- Identity resolution mirrors the existing URL/key precedence chain exactly — one idiom for all config-like resolution (Fowler: replace derived-on-the-fly with stored value + explicit seam).
- Fail fast over silent provisioning: an authenticated request for an unknown/mismatched tenant is an error, not a provisioning trigger (Release It: fail fast).
- Expand → rollout → cleanup: introduce the persisted option alongside derivation, then make derivation the one-time fallback, then delete per-request derivation (Release It: zero-downtime migration shape).

## Terminology

- **Derived tenant id**: legacy `sha1(siteurl)` UUID-shaped value.
- **Persisted tenant id**: value stored in `acx_recognition_tenant_id` option after first resolution or pairing.
- **Pairing**: plugin adopting the canonical tenant id bound to its configured API key, via an authenticated service endpoint.

## Current State Analysis

- Plugin sends `X-Tenant-ID` derived per request (`class-abstract-recognition-proxy-controller.php:79-97`); nothing persisted.
- Service: `api_keys.tenant_claim` is authoritative when present; admin keys may override tenant; auth rejects mismatches. JIT provisioning fills gaps with `auto-provisioned-<prefix>` placeholder site URLs.
- No plugin surface shows the tenant id or its provenance; settings GET response has `url_source`/`key_source` but no tenant fields.

## Target Outcome

One resolution chain: `ACX_RECOGNITION_TENANT_ID` constant → `acx_recognition_tenant_id` filter → option → derive-from-URL once and persist to the option. In service mode with a configured key, a pairing call (`GET /tenant/whoami`-style endpoint returning the key's tenant claim) adopts the canonical id and persists it; subsequent URL changes are irrelevant to identity. The service stops JIT-provisioning on authenticated tenant-scoped routes and returns a structured error naming the mismatch. Settings UI displays tenant id + source (consumed by E15-25 redesign).

## Context Loading

- Rules: `docs/workbay/rules/backend-php-guidelines.md`, `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-php.md`, `docs/workbay/rules/testing-python.md`
- Contracts: settings REST response shape (`class-settings-controller.php` GET), auth spec `docs/specs/auth-transaction-isolation-spec.md`
- Handoff/MCP: this task ref E15-24; related deferred plans E15-8/E15-10 (auth follow-ons, v0.4.1) — do not absorb their scope.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `X-Tenant-ID` request header | plugin → service | Derived sha1(siteurl) UUID | Same header, persisted/paired value | No (greenfield; service already validates against key claim) | PHPUnit on resolver; service auth tests unchanged |
| `GET /acx/v1/settings` response | plugin REST | url/key/source fields | + `tenant_id`, `tenant_id_source`, `tenant_paired` | No — additive | PHPUnit response-shape test + TS type update |
| Tenant pairing endpoint | service | none | New authenticated read-only endpoint returning `{tenant_id, site_url}` for the presented key | n/a (new) | pytest router test |
| JIT provisioning | service | `ensure_tenant_exists()` on analyze paths | Restricted: explicit-provision or admin-key only; authed mismatch → 4xx with structured detail | No (greenfield) | pytest: unknown tenant + valid key → 403/409 not silent create |

## Proposed Solution

PHP: add `TenantIdentity::resolve()` implementing the four-level chain with one-time persistence; replace all `derive_from_site_url()` call sites; expose tenant fields in settings GET; add pairing into the existing `/settings/test` service-mode probe (it already calls authenticated `/health/detailed` — extend to fetch and persist the key's tenant claim on success). Python: add the whoami/pairing read endpoint; gate `ensure_tenant_exists()` behind explicit provisioning (CLI `manage_api_keys` already creates tenants when minting keys — that remains the provisioning path); return structured 409 for placeholder-tenant collisions. Delete `derive_from_site_url()` after call sites migrate (delete-over-flag).

## Junior Implementer Guide

> Read this before touching code. **Rule zero: never trust a line number in this plan without re-verifying it** — run the grep given with each anchor; if it misses, search the symbol name and continue from what you find (rg-010: editor file models go stale; terminal grep is truth). If reality contradicts a slice's design, STOP and record a blocker via `record_event(event_kind='blocker')` instead of improvising.

### Why this task exists (didactic)

The partition key for ALL of a site's recognition data is currently recomputed per request from a mutable environment value. `designing-data-intensive-applications.md §Partition Key Stability` is the core lesson: keys that partition tenant data must be invariant across deployments; deriving them from a URL means a port change silently "creates" a new tenant and orphans everything. The fix shape — keep a derived value only as a one-time bootstrap, then persist and treat the stored value as authoritative — follows §Systems of Record vs Derived Data (one authority; everything else is a cached derivation). Service-side, refusing to silently provision unknown tenants is `release-it.md §Fail Fast (5.5)`: check identity validity at the transaction boundary instead of letting placeholder rows mask drift.

### Assumed setup

1. `make task-start TASK=E15-24 OBJECTIVE="..."` → worktree `../context-alt-text-monorepo-e15-24-impl` style path on `feature/e15-24` (if this branch already hosts the planning docs, coordinate: implementation continues on the same branch). Work ONLY in the worktree; `make context` each session.
2. Per slice: implement → run the named test commands → `record_event(event_kind='test_result')` → `close_slice` → `render_handoff(kind='dashboard')`.

### Verified code anchors (as of commit `81de3127`; re-verify each)

| What | Where | Verified content | Re-verify with |
| --- | --- | --- | --- |
| Derivation | `apps/prototype-wp-alt-context/src/api/class-tenant-identity.php:26-40` | `sha1('acx-site-tenant:' . untrailingslashit(strtolower(get_site_url())))` reformatted into a UUIDv5-shaped string (version nibble forced to 5, variant bits forced) | `grep -n "acx-site-tenant" src/api/class-tenant-identity.php` |
| Call site 1 | `class-abstract-recognition-proxy-controller.php:192-194` | `get_tenant_id()` is a one-line wrapper returning `TenantIdentity::derive_from_site_url()`; used to build the `X-Tenant-ID` header at ~line 80 | `grep -n "derive_from_site_url" src/api/*.php` |
| Call site 2 | `class-settings-controller.php:197` | service-mode `/settings/test` probe sends the derived header | same grep |
| Model for the resolution chain | `class-recognition-endpoint-resolver.php:24-41` | constant → filter → option → default, each level returning `{value, source}` | read the file |
| Key resolution (4-level idiom incl. comment about code-managed sources) | `class-settings-controller.php:357-382` (`resolve_key_source()`) | constant `ACX_RECOGNITION_API_KEY` → filter → option → '' | `grep -n "resolve_key_source" -A 8 src/api/class-settings-controller.php` |
| Service auth authority | `apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py:198-208` | if key has `tenant_claim` AND `X-Tenant-ID` present → must match or 403 `tenant mismatch` (with `emit_auth_event('tenant_mismatch', ...)`) | `grep -n "tenant mismatch" recognition/interface_adapters/http/deps/auth.py` |
| JIT provisioning | `db/tenant_context.py:22-45` + live call sites `analyze.py:201`, `analyze.py:554`, `analyze_multipart.py:294`, `deps/services.py:342` | creates `Tenant(id=..., site_url='auto-provisioned-<8 chars>')` when missing | `grep -rn "ensure_tenant_exists" --include="*.py" \| grep -v test` |

### Slice 1 notes — PHP resolution chain

- Copy the `RecognitionEndpointResolver` idiom EXACTLY (constant → filter → option, each returning `{value, source}`): new `TenantIdentity::resolve(): array{value: string, source: string}` with constant `ACX_RECOGNITION_TENANT_ID`, filter `acx_recognition_tenant_id`, option `acx_recognition_tenant_id`, then one-time derivation. Naming per the table in CLAUDE.md §Naming Conventions (`acx_*` options, `ACX_*` constants).
- One-time persistence rule: only when the chain falls through to derivation AND the option is empty, `update_option('acx_recognition_tenant_id', $derived)` and return `source: 'derived'`; subsequent calls hit the option level. Never overwrite a non-empty option from `resolve()` — overwriting is exclusively the pairing flow's job (Slice 3). This guard is what makes identity *sticky* across URL changes.
- Validate any constant/filter/option value as UUID-shaped (lowercase, 8-4-4-4-12 hex); a malformed override returns to the next level and logs a warning. Do not invent a new UUID lib — `wp_is_uuid()` exists in WP core.
- Both call sites switch to `resolve()['value']`. The settings GET adds `tenant_id`, `tenant_id_source`, `tenant_paired` (bool; false until Slice 3) — mirror the existing `url`/`url_source` response idiom at `get_settings()` (`class-settings-controller.php:83-103`) and extend `SettingsResponse` in `js/admin/api/settingsApi.ts`.
- Tests: model them on whatever covers `RecognitionEndpointResolver` today (`grep -rln "RecognitionEndpointResolver" tests/`). Matrix: constant wins / filter wins / option wins / derivation persists once / option survives simulated `get_site_url()` change / malformed override falls through.

### Slice 2 notes — service whoami + provisioning discipline

- Whoami endpoint: thin authenticated GET (suggested `/recognition/tenant/whoami`) returning `{tenant_id, site_url}` from `AuthContext.tenant_claim`. Put it in a new or existing router under `recognition/interface_adapters/http/routers/` — copy the dependency-injection style of a small existing router. For an admin key (`tenant_claim is None, is_admin=True`) return 404 with detail `no tenant claim` — an admin key has no canonical tenant; do NOT guess one (rg-015: never fabricate contract metadata).
- Do NOT modify `_require_auth_impl` — the auth seam is reviewed and spec-bound (`docs/specs/auth-transaction-isolation-spec.md`). You are a consumer of `AuthContext` only.
- JIT gating: the 4 live `ensure_tenant_exists` call sites currently provision placeholders. Replace the silent-create behavior on authenticated tenant-scoped routes with a structured failure: unknown tenant + non-admin key → 403 with detail naming the expected provisioning path. Keep explicit provisioning working: the `manage_api_keys` CLI mints tenants when creating keys — that remains THE provisioning path. Check each call site's surrounding transaction before editing (read 20 lines of context around each; some run inside a session whose rollback semantics you must preserve).
- Why fail-fast here: `release-it.md §Fail Fast` — reject at the boundary with a precise error rather than letting a placeholder row (`auto-provisioned-…`) mask identity drift that surfaces months later as "orphaned" data.

### Slice 3 notes — pairing + local re-key + deletion

- Pairing lives in `test_connection()` service-mode branch (`class-settings-controller.php:195-217`): on a successful authenticated `/health/detailed` probe, also call whoami; apply the conflict policy from this plan's Slice 3 section verbatim (adopt only when option unset/equal; mismatch → structured conflict response, no write).
- Local re-key: enumerate tenant-scoped local tables by grepping the installer/schema for `tenant_id` columns (`grep -rn "tenant_id" src/ --include="*.php" | grep -i "create table\|schema"`) rather than trusting this plan's table list. Wrap the multi-table UPDATE in the shared `run_transactional` wrapper (sr-009; `grep -rn "run_transactional" src/` to find it). The bounded-threshold fallback to forced re-sync exists because a 50k-row UPDATE inside one request is its own outage (`latency-reduce-delay-in-software-systems.md §Deferred Task Scheduling` — defer non-interactive bulk work instead of blocking a request on it).
- Deleting `derive_from_site_url()` is the point of the slice, not housekeeping: a surviving second derivation path is exactly the dual-write hazard `designing-data-intensive-applications.md §Log-Based Derivation vs Dual Writes` warns about — two writers of one identity guarantee eventual divergence. `grep -rn "derive_from_site_url"` must return zero before slice close.

### Pitfalls / stop conditions

- The derived UUID format must stay byte-identical until Slice 3 deletes derivation — golden-value test FIRST (assert a known site URL → known UUID) so refactors can't silently shift every existing tenant id.
- Local mode has no API key → pairing is service-mode only; in local mode identity stays `derived`-then-persisted. Never block local mode on pairing.
- `X-Tenant-ID` must remain a normalized UUID string — the service runs `normalize_tenant_id()` on it before claim comparison (auth.py:199).
- If you find an additional derivation or header-construction site this plan doesn't list, stop and record a blocker — do not migrate it ad hoc.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| PHP identity | `apps/prototype-wp-alt-context/src/api/class-tenant-identity.php` | `resolve()` chain + persistence; deprecate then delete `derive_from_site_url()` |
| PHP proxy | `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php` | use `resolve()` |
| PHP settings | `apps/prototype-wp-alt-context/src/api/class-settings-controller.php` | tenant fields in GET; pairing on successful service test |
| TS types | `apps/prototype-wp-alt-context/js/admin/api/settingsApi.ts` | extend `SettingsResponse` |
| Service router | `apps/prototype-description-service/recognition/interface_adapters/http/routers/` | whoami/pairing endpoint |
| Service tenancy | `apps/prototype-description-service/db/tenant_context.py` | restrict JIT provisioning; structured errors |
| Schema | `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py` | only if pairing needs a column (expect none) |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-wp-alt-context && composer test` (resolver chain: constant wins, filter wins, option sticky, derivation persists once)
  - `cd apps/prototype-description-service && make test` (whoami endpoint; JIT-provision rejection; admin-key override unchanged)
- Runtime-parity:
  - LocalWP: change site port after pairing → `X-Tenant-ID` unchanged (assert via request log / settings GET)
- Manual:
  - Settings page shows tenant id + source after `make serve` + service test.

## Slice Delivery

### Slice 1: PHP resolution chain + persistence

**Goal**: `TenantIdentity::resolve()` exists with constant→filter→option→derive-once chain; proxy + settings use it.

Changes: new resolver + persistence; call-site migration; settings GET tenant fields; TS type.
Proof: PHPUnit covering all four levels + stickiness across simulated URL change.

### Slice 2: Service whoami + provisioning discipline

**Goal**: authenticated callers can read their canonical tenant; unknown-tenant authed writes fail structurally instead of provisioning placeholders.

Changes: whoami route; `ensure_tenant_exists()` call sites gated; structured 403/409 details; tests.
Proof: pytest — valid key returns claim; analyze with mismatched tenant fails 403 with no new tenant row.

### Slice 3: Pairing flow + local re-key + derivation removal

**Goal**: successful service-mode connection test adopts the key's tenant claim under an explicit conflict policy, local data follows the identity, and legacy derivation is deleted.

**Pairing conflict policy**: pairing adopts the key's `tenant_claim` only when the persisted option is unset or already equal. On mismatch, pairing does NOT silently re-key: the test endpoint returns a structured conflict (`{persisted_tenant_id, key_tenant_id}`) and the UI requires explicit operator confirmation before adoption.

**Local re-key reconciliation**: local tenant-scoped tables (`wp_acx_clusters`, `wp_acx_identity_members`, `wp_acx_sync_outbox`, `wp_acx_sync_conflicts`, `wp_acx_topology_commands`) carry `tenant_id`. Any identity change (confirmed pairing adoption, or first persistence differing from rows written under a legacy derived id) re-keys those rows in a single transaction via `run_transactional` (sr-009); if row counts exceed a bounded threshold, fall back to a forced snapshot re-sync instead of in-place re-key.

Changes: `/settings/test` pairing write with conflict policy; local re-key transaction (or re-sync fallback); delete `derive_from_site_url()`; docs note in epic.
Proof: PHPUnit pairing tests covering adopt/conflict/confirm paths; re-key test asserting no orphaned local rows after identity change; `grep -r derive_from_site_url` returns nothing; full plugin + service suites green.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded PHP/Python guidelines, auth spec, and this assessment before editing.
- [ ] Confirmed no `ctx7` need (WP options + FastAPI surfaces are in-repo idioms).
- [ ] Recorded boundary rows above in handoff decision at slice close.

### Checklist for Slice 1: PHP resolution chain

- [ ] `resolve()` chain implemented with one-time persistence
- [ ] All call sites migrated; settings GET + TS types extended
- [ ] PHPUnit evidence recorded via `record_event(event_kind='test_result')`

### Checklist for Slice 2: Service whoami + provisioning discipline

- [ ] Whoami endpoint authenticated and tested
- [ ] JIT provisioning restricted; structured errors asserted
- [ ] pytest evidence recorded

### Checklist for Slice 3: Pairing + cleanup

- [ ] Pairing persists canonical tenant id on successful test, with mismatch-confirmation path tested
- [ ] Local re-key transaction (or re-sync fallback) leaves zero orphaned tenant-scoped local rows
- [ ] `derive_from_site_url()` deleted; no references remain
- [ ] Slice-complete decision + dashboard render

## Review Readiness

- [ ] Boundary table changes carry matching tests/fixtures.
- [ ] Runtime-parity port-change check captured.
- [ ] Handoff decisions recorded per slice.

## Success Criteria

- [ ] Changing LocalWP port/scheme/domain does not change `X-Tenant-ID` once paired/persisted.
- [ ] Local dev against staging reuses one canonical tenant; prod holds only the real production-domain tenant.
- [ ] No code path silently creates placeholder tenants on authenticated requests.
