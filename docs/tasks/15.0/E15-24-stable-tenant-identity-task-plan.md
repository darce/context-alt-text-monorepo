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

- Rules: `docs/workstate/rules/backend-php-guidelines.md`, `docs/workstate/rules/backend-python-guidelines.md`, `docs/workstate/rules/testing-php.md`, `docs/workstate/rules/testing-python.md`
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
