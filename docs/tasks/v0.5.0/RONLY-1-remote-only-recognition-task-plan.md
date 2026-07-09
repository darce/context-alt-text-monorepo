# Task Plan — RONLY-1

> - **Date**: 2026-07-09
> - **Author**: Claude Opus 4.8 (operator session)
> - **Project**: context-alt-text-monorepo (plugin + description-service)
> - **Task ID**: `RONLY-1`
> - **Target Branch**: `feature/ronly-1`
> - **Review Coverage Target**: 2
> - **Derived from**: [ADR-011](../../adrs/ADR-011-retire-on-device-recognition-remote-only.md)

---

## RONLY-1. Remote-Only Recognition & Key-Driven Tenanting

## Objective

Collapse the plugin to a single remote recognition path against the shared hosted service, make tenanting key-driven (adopt the key's tenant via `/recognition/tenant/whoami`), retire on-device recognition, and prove media/clusters/captions still render offline. When complete, there is no `local`/`service` mode split, no URL-derived tenant, and no "tenant mismatch → Unreachable" failure.

## Problem Statement

The plugin is local-first: it selects a `local` or `service` recognition endpoint, derives a tenant from the site URL, and reconciles that against a server-provisioned tenant. This produces a `403 "tenant mismatch"` when the derived tenant differs from the key's tenant (`auth.py:198-208`), which the UI mislabels as "Unreachable" (`healthStatus.ts:25`), and the auto-pairing that would fix it is gated behind a `CONNECTED` probe it can never reach (`class-settings-controller.php:275`) — a deadlock. On-device CPU recognition has no value once the backend is GPU-bound (E14 target). ADR-011 accepted retiring on-device recognition, going remote-only, and key-driven tenanting.

## Constraints

- **Greenfield** (CLAUDE.md): no production data; schema changes go directly in `001_identity_schema.py`; **delete-over-flag** — remove `local` mode, do not flag it off.
- **Offline display is mandatory** (ADR-011): rendering media, clusters, and captions must make **no** network call; only new recognition/inference may hit remote.
- **Single shared backend** (`altcontext.com`), RLS-isolated; no customer-run servers; internal endpoint override stays only as `ACX_RECOGNITION_URL` constant / `acx_recognition_base_url` filter (`class-recognition-endpoint-resolver.php:25,30`).
- **Plugin Boundary Rule**: only modify `apps/prototype-wp-alt-context/**` and `apps/prototype-description-service/**`.
- Branch isolation; TypeScript uses `as const`/StrEnum for status values (sr-007); no `console.assert` on API data (sr-005).

## Workflow Principles

- One recognition path; no dual-mode branches survive.
- Tenant source of truth = the key's tenant (server-authoritative via whoami), not a client derivation.
- Display reads never touch the network; only "compute new" does.

## Terminology

- **Key-driven tenanting**: the plugin persists and uses the tenant bound to its API key (read from `/recognition/tenant/whoami`), rather than one derived from the site URL.
- **Sovereign mirror**: the WP-local tables (`{prefix}acx_persons`, `{prefix}acx_clusters`, alt-text meta) that back offline display.

## Current State Analysis

- `Admin::get_recognition_source()` returns `local`|`service` (`apps/prototype-wp-alt-context/src/admin/class-admin.php:380`); `RecognitionEndpointResolver` resolves the URL (`src/api/class-recognition-endpoint-resolver.php`).
- Health probe is dual-mode: `local` → `/health` liveness; `service` → `/health/detailed` with `X-Tenant-ID` + `X-API-Key`, then `attempt_tenant_pairing()` via `/recognition/tenant/whoami` gated behind `CONNECTED` (`src/api/class-settings-controller.php:238-296`).
- Tenant derived from site URL unless overridden (`src/api/class-tenant-identity.php:105 derive_site_url_tenant_id`); server enforces `X-Tenant-ID == key tenant` else 403 (`recognition/interface_adapters/http/deps/auth.py:198-208`).
- UI maps every non-`connected` outcome to `Unreachable` (`js/admin/pages/settings/healthStatus.ts:25`); settings contract carries `tenant_id`, `tenant_id_source`, `tenant_paired` (`js/admin/api/settingsApi.ts:18-20`).
- Roster/cluster reads are `$wpdb`-local, no `wp_remote` (`src/sovereign/repositories/class-roster-entry-projection-repository.php:24-135`) — offline display already holds and must be preserved.

## Target Outcome

Pasting a valid key resolves the tenant automatically (whoami), the settings page shows a single hosted service plus Key ID + Tenant ID, health reports the true outcome, on-device recognition code is gone, and a test proves the roster/clusters/captions render with the remote endpoint stubbed unreachable.

## Context Loading

- ADR: `docs/adrs/ADR-011-retire-on-device-recognition-remote-only.md`
- Rules: `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/backend-php-guidelines.md`, `docs/workbay/rules/testing-typescript.md`, `docs/workbay/rules/testing-php.md`
- Handoff: task `RONLY-1`; ADR-011 verdict decision `operator_planning_review_verdict_adr011_adr012`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Settings REST (`acx/v1/settings*`) | proxy (PHP) → frontend (TS) | `js/admin/api/settingsApi.ts` response shape | Remove mode fields; add `key_id`, resolved `tenant_id` from whoami, honest `outcome`; drop `tenant_id_source`/derive | no (greenfield) | `settingsResponseContract.test.ts` updated |
| `X-Tenant-ID` on recognition calls | PHP client → recognition service | header sent = derived tenant | Send adopted (whoami) tenant, or omit; never a stale derived value | no | integration test: mismatch no longer 403s |
| `/recognition/tenant/whoami` | recognition service | `{tenant_id, site_url}` (`routers/tenant.py:20`) | consumed at key-save; no server change | no | live probe already verified |

## Proposed Solution

Four slices: (1) adopt the key's tenant on save and remove the derive/pairing deadlock; (2) collapse the settings UI to remote-only and surface Key ID + Tenant ID + honest outcome; (3) delete on-device recognition (plugin `local` branches + service local-run surfaces); (4) add an offline-display regression test. Each slice ships behavior + proof.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| PHP client | `src/api/class-settings-controller.php` | Single-mode probe; adopt whoami tenant on save; stop sending stale `X-Tenant-ID`; remove `CONNECTED`-gated pairing deadlock |
| PHP identity | `src/api/class-tenant-identity.php` | Demote derive-from-URL from authority; adopted tenant (option) wins; keep derive only as last-resort display label |
| PHP resolver | `src/api/class-recognition-endpoint-resolver.php` | Remove `local` branch; keep `ACX_RECOGNITION_URL`/filter override; default to hosted service |
| PHP admin | `src/admin/class-admin.php` | Remove `get_recognition_source()` local case + `recognitionSource` localize |
| TS settings | `js/admin/api/settingsApi.ts` | Response contract: add `key_id`, resolved `tenant_id`; remove `tenant_id_source`, mode |
| TS health | `js/admin/pages/settings/healthStatus.ts` | Map real outcomes (invalid_key/expired/revoked/rate_limited/server_error) instead of collapsing to `Unreachable` |
| TS settings UI | `js/admin/pages/settings/*` | Remove local/hosted toggle; single hosted view; render Key ID + Tenant ID (read-only, copyable) |
| Service | `apps/prototype-description-service/docker-compose.db.yml`, `scripts/admin_dev.sh`, `Makefile` (`admin-dev`/`dev-ready`), InsightFace local provisioning, local worker path | Remove local-run product surfaces (inventory first — Slice 3) |

## Related Files

| File | Note |
| --- | --- |
| `recognition/interface_adapters/http/deps/auth.py:198-208` | Tenant enforcement stays; slice 1 must ensure the plugin sends the matching (or no) tenant |
| `src/sovereign/repositories/class-roster-entry-projection-repository.php` | Offline-display read path — must remain network-free (slice 4 test) |
| `js/admin/pages/settings/TestConnectionBannerView.tsx`, `testConnectionBanner.ts`, `settingsConstants.ts` | Banner/label surfaces to update |

## Verification Strategy

- Deterministic tests:
  - PHP: `cd apps/prototype-wp-alt-context && composer test` (settings-controller adoption + single-mode probe; tenant-identity precedence)
  - TS: `cd apps/prototype-wp-alt-context && npm test` (`settingsResponseContract.test.ts`, `healthStatus` outcome mapping)
- Contract/fixture verification:
  - `settingsResponseContract.test.ts` asserts new shape (`key_id`, `tenant_id`, no `tenant_id_source`).
- Runtime-parity / manual:
  - Paste a key minted under a non-derived tenant → health `connected`, tenant adopted (no 403).
  - Roster/clusters/captions render with remote stubbed unreachable (slice 4 automated).

## Slice Delivery

### Slice 1: Key-driven tenant adoption; remove the deadlock

**Goal**: Saving a valid key adopts the key's tenant and clears the mismatch class.

Changes:
- On key save, call `/recognition/tenant/whoami`; persist returned `tenant_id` via `TenantIdentity::adopt_paired_tenant()`; make the adopted option the authority in `TenantIdentity::resolve()`.
- Stop sending a stale derived `X-Tenant-ID` on the probe (send adopted tenant or omit); remove the `CONNECTED`-gated pairing branch so adoption runs on save, not after a probe.

Proof:
- PHP test: saving a key whose tenant ≠ derived tenant results in adoption + `connected`, not `tenant_mismatch`.

### Slice 2: Remote-only settings UI + identity display + honest outcome

**Goal**: One hosted-service view; Key ID + Tenant ID visible; real health outcome.

Changes:
- Remove the local/hosted toggle; render Key ID + resolved Tenant ID (read-only, copyable).
- `healthStatus.ts` maps each `outcome` to its own status; `Unreachable` only for network/TLS.

Proof:
- TS tests: `healthStatus` returns `invalid_key`/`rate_limited`/… distinctly; contract test asserts `key_id`/`tenant_id` present.

### Slice 3: Remove on-device recognition

**Goal**: No `local` recognition path in plugin or service.

Changes:
- Delete plugin `local` branches (`class-recognition-endpoint-resolver.php`, `get_recognition_source()`, `local` probe branch).
- Inventory then remove service local-run surfaces (`docker-compose.db.yml` local Postgres bring-up, `make admin-dev`/`dev-ready` local flow, local InsightFace provisioning, local worker daemon). Keep OCI deployability.

Proof:
- `grep` shows no `local` recognition-mode branch; `composer test` + service test suite green.

### Slice 4: Offline-display regression proof

**Goal**: Prove display never depends on remote.

Changes:
- Add a test that renders roster/clusters/captions with the recognition endpoint stubbed unreachable and asserts full display.

Proof:
- New PHP/TS test passes with remote stubbed to fail.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded ADR-011, frontend/PHP guidelines, and task `RONLY-1` handoff state before editing.
- [ ] Recorded settings-contract boundary ownership (PHP↔TS) and greenfield no-compat expectation.

### Checklist for Slice 1: Key-driven tenant adoption

- [ ] whoami-on-save adoption implemented in `class-settings-controller.php`; adopted option wins in `TenantIdentity::resolve()`.
- [ ] Stale `X-Tenant-ID` no longer sent; `CONNECTED`-gated pairing deadlock removed.
- [ ] PHP test proves adoption clears the mismatch; captured as evidence.

### Checklist for Slice 2: Remote-only UI + identity display

- [ ] Local/hosted toggle removed; Key ID + Tenant ID rendered read-only/copyable.
- [ ] `healthStatus.ts` surfaces real outcomes; `settingsResponseContract.test.ts` updated.
- [ ] TS tests captured as evidence.

### Checklist for Slice 3: Remove on-device recognition

- [ ] Plugin `local` branches deleted; service local-run surfaces inventoried and removed.
- [ ] OCI deployability preserved; suites green.

### Checklist for Slice 4: Offline-display proof

- [ ] Test renders media/clusters/captions with remote unreachable and passes.

## Review Readiness

- [ ] No boundary-touching change (settings contract) without matching TS/PHP test evidence.
- [ ] Offline-display test included (runtime behavior tests could otherwise mask a network coupling).
- [ ] Handoff decision records change + verification + contract implications.

## Success Criteria

- [ ] Pasting a valid key adopts its tenant and yields `connected` with no `tenant_mismatch`.
- [ ] Settings page shows one hosted service + Key ID + Tenant ID; no mode toggle; honest outcome labels.
- [ ] No `local` recognition-mode code remains in plugin or service; suites green.
- [ ] Automated proof that media/clusters/captions render with the remote endpoint unreachable.
