# E15-1b. Plugin Settings UX: Authenticated Probe and Rich Auth Error Taxonomy

> **Metadata**
>
> - **Date**: 2026-04-19
> - **Author**: Claude Opus 4.7
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Target Branch**: `feature/e15-1b`
> - **Target Worktree**: `/Users/daniel/Development/context-alt-text-monorepo-e15-1b`
> - **Prerequisite Tasks**: [E15-1 Security Baseline](./E15-1-security-baseline-task-plan.md) (all slices merged to `main`)
> - **Scope Decisions**: `MAINT-scope-e15-1b-20260419` decisions 2086–2090
> - **Review Coverage Target**: 2

---

## Objective

Make the plugin Settings page tell an operator the truth about their connection. Today the "Test Connection" button probes an unauthenticated liveness endpoint and reports "Connection successful!" even when the configured API key is blank, wrong, expired, revoked, or scoped to a different tenant. After this task, the probe hits an authenticated endpoint and the UI surfaces nine distinct outcomes — each mapped to the exact auth decision emitted by `require_auth` in E15-1 Slice 3 — with a concrete remediation hint for every failure case.

## Problem Statement

E15-1 landed three auth decisions in the backend (`success`, `invalid_key`, `expired`, `revoked`, `tenant_mismatch`, plus 429 `rate_limited`), each emitted by [`_require_auth_impl`](../../../apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py) on every protected request. The plugin's Settings page cannot consume any of this:

1. **Probe target is unauthenticated.** [`SettingsController::test_connection`](../../../apps/prototype-wp-alt-context/src/api/class-settings-controller.php) (line 127) builds `$url . '/recognition/health'`. That router has no `require_auth` dependency ([`health.py:26-53`](../../../apps/prototype-description-service/recognition/interface_adapters/http/routers/health.py)) — it returns 200 for anyone. A tester can paste a revoked key, hit "Test Connection", and see "Connection successful!"
2. **No tenant header.** The probe only forwards `X-API-Key`; `X-Tenant-ID` is never sent. The plugin already derives a canonical tenant UUID from `get_site_url()` in [`class-abstract-recognition-proxy-controller::get_tenant_id()`](../../../apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php) and forwards it on every recognition call (line 66). The probe does not reuse that derivation, so its result diverges from real request behavior.
3. **Binary UI state.** [`SettingsPage.tsx:191-202`](../../../apps/prototype-wp-alt-context/js/admin/pages/SettingsPage.tsx) only renders `connected ? "Connection successful!" : "Connection failed. <error>"`. Upstream 401/403/429/5xx payloads collapse into the same red banner with no remediation hint.
4. **No test coverage.** [`SettingsPage.test.tsx`](../../../apps/prototype-wp-alt-context/js/admin/pages/__tests__/SettingsPage.test.tsx) exercises form interaction but does not assert any mapping from a backend auth outcome to a UI banner.

The net effect: the Settings page is a misleading smoke test. An operator cannot tell the plugin is silently unauthenticated until a real recognition request fails in production use.

## Constraints

- **Scope is the plugin only** (`apps/prototype-wp-alt-context/`). No changes to the Python recognition service — E15-1 already supplies the auth decisions this task consumes. If the probe needs a server-side signal the backend does not already emit, raise it as an open question, not a scope expansion.
- **No two-key rotation overlap UI.** Rotation ceremony stays on the operator CLI (E15-1 Slice 3). The Settings page remains a single-key swap-in-place form. Adding pending/primary/secondary key state is explicitly out of scope.
- **`/recognition/health` stays unauthenticated.** It is the liveness probe for external monitors and the docker-compose healthcheck. This task swaps the plugin's probe target, not the endpoint's auth policy.
- **No Playwright E2E, no manual screenshot gallery.** Vitest + PHPUnit carry the completion signal.
- **Greenfield policy.** No migrations, no back-compat shims. If the existing `test_connection` shape needs to change, change it.
- **TS error-state values come from a single canonical source** ([sr-007]). A `TestConnectionOutcome` `as const` object in `settingsApi.ts` is the enum surface; SettingsPage renders from that mapping only, no scattered string literals.
- Branch isolation: all edits on `feature/e15-1b`, not `main`.

## Workflow Principles

- Align the controller probe with the backend auth contract in Slice 1 before adding UI taxonomy in Slice 2. If the probe cannot discriminate outcomes, UI work is premature.
- Tests first in each slice: Vitest for the React layer, PHPUnit for the controller probe dispatch.
- The nine outcome codes below are the contract between controller (PHP) and page (TS). Both ends import/declare them from one source-of-truth manifest per language, not duplicated string literals.

## Terminology

- **Probe**: the HTTP request `SettingsController::test_connection` makes to the recognition service when an operator clicks "Test Connection". Before this task it hits `/recognition/health`; after, it hits `/recognition/health/pool`.
- **Outcome code**: one of nine canonical strings emitted by the plugin's controller to the React layer — `connected`, `invalid_key`, `expired`, `revoked`, `tenant_mismatch`, `rate_limited`, `server_error`, `network_error`, `tls_error`. Each maps 1:1 to the auth decision or transport failure the probe observed.
- **Remediation hint**: the short second-line sentence under each error banner that tells the operator what to do next (e.g. "revoked — rotate via CLI", "tenant mismatch — confirm `X-Tenant-ID` matches the key's tenant").
- **Single-key swap-in-place**: the Settings form has one API-key input; saving a new value overwrites the previous value. No dual-key overlap UI.

## Current State Analysis

### What works

- [`SettingsController`](../../../apps/prototype-wp-alt-context/src/api/class-settings-controller.php) already resolves the key from the constant/option/filter chain and masks it on read.
- [`SettingsPage`](../../../apps/prototype-wp-alt-context/js/admin/pages/SettingsPage.tsx) renders source-chain labels (constant/option/filter/default) and disables fields when an override is active.
- The recognition service's authenticated endpoints (including `/recognition/health/pool`) already emit the five auth-decision codes via E15-1's `emit_auth_event` and return deterministic status codes (401/403/429) with stable `detail` strings.

### What is broken or missing

- `test_connection` probes `/recognition/health` (unauthenticated), so any key — including a blank, revoked, or wrong-tenant key — returns 200.
- `test_connection` does not forward `X-Tenant-ID`. Tenant-mismatch outcomes cannot be reproduced by the probe.
- `TestConnectionResponse` is a three-field bag (`connected`, `status_code?`, `body?`, `error?`) with no outcome code. The TS layer has nothing to switch on.
- `SettingsPage.tsx:191-202` renders only two states (success / failure).
- `SettingsPage.test.tsx` has no coverage of error-state mapping.
- No PHPUnit coverage of `test_connection` probe dispatch (no assertion of endpoint path or header forwarding).

## Target Outcome

When an operator saves a new API key and clicks "Test Connection":

- A valid key for the configured tenant → "Connected." green banner with recognition service version from the response body.
- A blank / malformed / unknown key → "Invalid API key — check the value in your operator CLI output."
- A key past its `expires_at` → "API key expired — rotate via the operator CLI."
- A key with `revoked_at` set → "API key revoked — rotate via the operator CLI."
- A key that exists but the tenant claim does not match `X-Tenant-ID` → "Tenant mismatch — the key is scoped to a different tenant."
- A key hitting its rate limit (429) → "Rate limited — wait `<Retry-After>s` and retry."
- Recognition service 5xx → "Recognition service error — check the service logs."
- cURL-level network failure (no HTTP response) → "Network error — verify the URL and that the service is reachable."
- TLS/cert failure → "TLS error — verify the recognition URL certificate is valid."

The nine states are fully covered by `SettingsPage.test.tsx` and `SettingsControllerTest::test_probe_dispatch`.

## Context Loading

- Rules: [docs/agentic/rules/frontend-guidelines.md](../../agentic/rules/frontend-guidelines.md), [docs/agentic/rules/backend-php-guidelines.md](../../agentic/rules/backend-php-guidelines.md)
- Rules: [docs/agentic/rules/testing-typescript.md](../../agentic/rules/testing-typescript.md), [docs/agentic/rules/testing-php.md](../../agentic/rules/testing-php.md)
- Context map: [docs/agentic/maps/frontend.md](../../agentic/maps/frontend.md), [docs/agentic/maps/php-plugin.md](../../agentic/maps/php-plugin.md)
- Contract: [docs/agentic/contracts/security.md](../../agentic/contracts/security.md) (E15-1 auth-decision outcomes and response shapes)
- External docs via `ctx7` only if WordPress `wp_remote_get` error-code surface (`is_wp_error` classifications) needs verification.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
|----------|-------|-----------------|----------------|----------------------|--------------|
| `POST /acx/v1/settings/test` response shape | PHP Plugin | `{connected: bool, status_code?: int, body?: unknown, error?: string}` | Add `outcome: OutcomeCode`, `retry_after_seconds?: int`, `detail?: string` | No (greenfield) | PHPUnit + Vitest |
| Recognition auth decisions | Backend | `emit_auth_event` outcomes in E15-1 Slice 3 | None (consumer only) | N/A | N/A |
| Plugin Settings UI | PHP Plugin | SettingsPage.tsx binary success/failure | Nine-state render + remediation hints | No (greenfield) | Vitest |

## Proposed Solution

1. **Swap the probe endpoint.** `SettingsController::test_connection` builds `$url . '/recognition/health/pool'` (authenticated) and forwards both `X-API-Key` and `X-Tenant-ID`. The tenant value comes from the **same derivation the proxy controller already uses** (`sha1('acx-site-tenant:' . lowercased site URL)` formatted as a UUID), promoted out of `class-abstract-recognition-proxy-controller::get_tenant_id()` into a shared helper so both call sites stay bit-identical. No new WP option is introduced — the plugin already treats `get_site_url()` as the canonical tenant source.
2. **Add an outcome-code layer in PHP.** A new private method `SettingsController::classify_probe_response(WP_Error|array $response)` returns one of the nine outcome codes. Classification rules:
   - `is_wp_error()` with a TLS/cert error string → `tls_error`.
   - Other `is_wp_error()` → `network_error`.
   - HTTP 200 → `connected`.
   - HTTP 401 with `detail="api key expired"` → `expired`.
   - HTTP 401 with `detail="api key revoked"` → `revoked`.
   - HTTP 401 (any other detail) → `invalid_key`.
   - HTTP 403 with `detail="tenant mismatch"` → `tenant_mismatch`.
   - HTTP 429 → `rate_limited` (surface `Retry-After` header as `retry_after_seconds`).
   - HTTP ≥ 500 → `server_error`.
   The `detail` strings are the exact literal values emitted by [`_require_auth_impl`](../../../apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py). The nine outcome codes live in one place: a PHP enum/class constant under `AltContext\Api\ProbeOutcome`.
3. **Thread the outcome through the response.** `test_connection` returns `{connected, outcome, status_code?, retry_after_seconds?, detail?, body?}`. The existing `connected` bool is kept for back-compat with any consumer (there is none today besides the plugin itself, but keeping it costs nothing and makes the response self-describing). `outcome` is the new source-of-truth discriminator.
4. **Mirror the outcome in TS and render nine banners.** `TestConnectionResponse` grows an `outcome: TestConnectionOutcome` field where `TestConnectionOutcome` is an `as const` object in `settingsApi.ts`. `SettingsPage.tsx` switches on `outcome` to render one of nine `<div className="notice ..." role="status|alert">` banners. Each banner has a localized primary line and a remediation hint line. The `rate_limited` banner interpolates `retry_after_seconds` when present.
5. **Test the mapping end to end.** Vitest drives `SettingsPage` nine times with a mocked `testConnection` response for each outcome and asserts the rendered strings. PHPUnit tests `test_connection` dispatch by stubbing `wp_remote_get` (via the existing test seam in `SettingsControllerTest`) for each of the nine response shapes and asserts the returned outcome plus the probe URL is `/recognition/health/pool`, not `/recognition/health`.

## Files and Surfaces to Change

| Surface | File | Change |
|---------|------|--------|
| Probe target + classification | `apps/prototype-wp-alt-context/src/api/class-settings-controller.php` | Swap probe URL to `/recognition/health/pool`; forward `X-Tenant-ID`; add `classify_probe_response`; extend response shape |
| Outcome-code constants (PHP) | `apps/prototype-wp-alt-context/src/api/class-probe-outcome.php` | New: PHP class constants (or backed enum per [sr-007]) for the nine outcome codes |
| Controller probe unit test | `apps/prototype-wp-alt-context/tests/Unit/SettingsControllerTest.php` | Add `test_probe_dispatch` covering probe URL, header forwarding, and all nine outcome classifications |
| Tenant-id shared helper | `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php` | Promote `get_tenant_id()` from `protected` to a shared helper (trait or `public static` on a new `AltContext\Api\TenantIdentity` class) so `SettingsController` can reuse the exact derivation without subclassing the proxy controller |
| TS outcome enum + response type | `apps/prototype-wp-alt-context/js/admin/api/settingsApi.ts` | Add `TestConnectionOutcome` `as const`; extend `TestConnectionResponse` with `outcome`, `retry_after_seconds`, `detail` |
| SettingsPage renderer | `apps/prototype-wp-alt-context/js/admin/pages/SettingsPage.tsx` | Replace binary banner with a nine-state switch on `outcome`; render primary + remediation lines; interpolate `retry_after_seconds` for `rate_limited` |
| SettingsPage Vitest | `apps/prototype-wp-alt-context/js/admin/pages/__tests__/SettingsPage.test.tsx` | Add one test per outcome asserting the rendered primary line and remediation hint |
| Contract docs | `docs/agentic/contracts/security.md` | Append a short "Plugin probe contract" section describing the nine outcome codes and which `_require_auth_impl` detail string each one maps to |

## Related Files

| File | Note |
|------|------|
| `apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py` | Source of canonical `detail` strings — do not change |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/health.py` | `/health/pool` handler — already auth-gated, no change |
| `apps/prototype-wp-alt-context/js/admin/utils/http.ts` | Existing `fetchRequiredApi` wrapper — no change |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-wp-alt-context && npm run test -- SettingsPage`
  - `cd apps/prototype-wp-alt-context && composer test -- --filter=SettingsControllerTest`
- Runtime-parity:
  - With a valid key for tenant A and `X-Tenant-ID: A` → UI shows "Connected."
  - With the same key and `X-Tenant-ID: B` → UI shows "Tenant mismatch".
  - After `manage_api_keys.py revoke --key-id <id>` → UI shows "API key revoked".
  - With the URL set to `https://expired.badssl.com` → UI shows "TLS error".
- Contract verification:
  - Security contract has a "Plugin probe contract" subsection listing the nine outcomes and their `_require_auth_impl` `detail` anchors.

## Slice Delivery

### Slice 1: Authenticated Probe and Outcome Classification (Controller)

**Goal**: Make `SettingsController::test_connection` hit the authenticated endpoint, forward the tenant header, and return a canonical outcome code for every response shape.

Changes:

- Add `apps/prototype-wp-alt-context/src/api/class-probe-outcome.php` with nine constants (`CONNECTED`, `INVALID_KEY`, `EXPIRED`, `REVOKED`, `TENANT_MISMATCH`, `RATE_LIMITED`, `SERVER_ERROR`, `NETWORK_ERROR`, `TLS_ERROR`). Use a `final class` with `public const` per the plugin's existing PHP conventions; add `require_once` wiring from the plugin bootstrap if PSR-4 autoloading does not resolve the `class-*.php` filename ([rg-016]).
- Promote `get_tenant_id()` from `class-abstract-recognition-proxy-controller.php` (currently `protected`, lines 138–151) into a shared surface so `SettingsController` can reuse the exact derivation. Options (pick one in implementation): (a) extract into a `TenantIdentity` trait included by both controllers, or (b) extract into a `final class AltContext\Api\TenantIdentity { public static function derive_from_site_url(): string { ... } }` helper. The abstract proxy controller's method becomes a thin delegator so behavior for existing recognition calls is unchanged. Add `TenantIdentityTest` PHPUnit covering the SHA-1/UUID derivation against known site URLs.
- In `SettingsController::test_connection`:
  - Replace `'/recognition/health'` with `'/recognition/health/pool'` at line 127.
  - Forward `X-Tenant-ID` using the shared `TenantIdentity::derive_from_site_url()` helper (never empty; `get_site_url()` is always available in a WP runtime).
  - Forward `X-API-Key` (existing behavior).
  - Add `classify_probe_response(WP_Error|array $response): string` using the mapping in §Proposed Solution.
  - Extend the return shape: `{connected: bool, outcome: string, status_code?: int, retry_after_seconds?: int, detail?: string, body?: unknown}`. `connected` stays as a convenience bool (`outcome === CONNECTED`).
- **Contract co-change (same slice)**: append the "Plugin probe contract" subsection to `docs/agentic/contracts/security.md` in this slice, alongside the payload and classification change. The contract documents the nine outcome codes and their mapping to `_require_auth_impl` detail strings. Deferring the contract update leaves a known-stale security contract in place during implementation.
- Add `tests/Unit/SettingsControllerTest::test_probe_dispatch`:
  - Stub `wp_remote_get` (existing harness pattern) to return each of the nine shapes.
  - Assert the probe URL is `/recognition/health/pool`, not `/recognition/health`.
  - Assert `X-API-Key` and `X-Tenant-ID` headers are both present; assert `X-Tenant-ID` value matches `TenantIdentity::derive_from_site_url()` output for the test site URL.
  - Assert each stubbed response produces the expected `outcome` and (where applicable) `retry_after_seconds`.

Proof:
- `composer test -- --filter=SettingsControllerTest` passes with all nine outcomes covered.
- `composer test -- --filter=TenantIdentityTest` passes (SHA-1/UUID derivation regression test).
- PHPUnit output shows the probe URL assertion is green (guards against regression to `/recognition/health`).
- `contracts/security.md` contains the "Plugin probe contract" subsection with the nine outcome codes.

### Slice 2: Nine-State Settings Page Renderer (React)

**Goal**: Render one remediation-aware banner per outcome; hold the `TestConnectionOutcome` enum in a single source-of-truth location.

Changes:

- In `settingsApi.ts`: add
  ```ts
  export const TestConnectionOutcome = {
    CONNECTED: 'connected',
    INVALID_KEY: 'invalid_key',
    EXPIRED: 'expired',
    REVOKED: 'revoked',
    TENANT_MISMATCH: 'tenant_mismatch',
    RATE_LIMITED: 'rate_limited',
    SERVER_ERROR: 'server_error',
    NETWORK_ERROR: 'network_error',
    TLS_ERROR: 'tls_error',
  } as const;
  export type TestConnectionOutcomeValue = typeof TestConnectionOutcome[keyof typeof TestConnectionOutcome];
  ```
  Extend `TestConnectionResponse` with `outcome: TestConnectionOutcomeValue`, `retry_after_seconds?: number`, `detail?: string`.
- In `SettingsPage.tsx`: replace the binary banner at lines 191-202 with a switch on `testResult.outcome`. Each case renders `<div className="notice notice-success|warning|error inline" role="status|alert">` with:
  - a localized primary string (`__('…', 'alt-context')`)
  - a second `<p>` with a remediation hint
  - for `rate_limited`, interpolate `testResult.retry_after_seconds` into the hint (fallback: "a few seconds" when absent)
- Exhaustive switch: use a `const never: never = outcome` assertion in the `default` branch so adding a new outcome without updating the UI is a TypeScript error ([sr-005]).
- In `SettingsPage.test.tsx`: add one test per outcome that mocks `testConnection` to resolve with the appropriate response shape, clicks "Test Connection", and asserts the rendered primary + remediation lines.

Proof:
- `npm run test -- SettingsPage` passes with nine new cases.
- `npm run typecheck` fails if a new outcome is added to the enum but not to the switch (exhaustiveness check).

### Slice 3: Staging Demo Smoke

**Goal**: Exercise the end-to-end surface against the staging recognition service and record runtime-parity evidence, now that the controller + renderer are wired and the contract is documented.

Changes:

- Manual smoke pass against the staging recognition service (documented, not automated):
  1. Save a valid key for the staging tenant → expect `connected`.
  2. Revoke that key via `manage_api_keys.py revoke` on the staging VM, click "Test Connection" → expect `revoked`.
  3. Save a key scoped to a different tenant, keep the plugin tenant setting as-is → expect `tenant_mismatch`.
  4. Flood the probe endpoint from the browser console to breach the rate limit → expect `rate_limited` with `retry_after_seconds` shown.
- Record smoke outcomes as a `test_result` event so the close check has runtime-parity evidence.

Proof:
- One `test_result` event per smoke scenario, all `passed=true`.

---

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded security contract (`docs/agentic/contracts/security.md`) before editing
- [ ] Confirmed `/recognition/health/pool` is auth-gated in `health.py`
- [ ] Confirmed `_require_auth_impl` detail strings (`"api key expired"`, `"api key revoked"`, `"tenant mismatch"`) are literal constants, not variable interpolations
- [ ] Branch created: `feature/e15-1b`
- [ ] Worktree: `/Users/daniel/Development/context-alt-text-monorepo-e15-1b`

### Checklist for Slice 1: Authenticated Probe and Outcome Classification

- [ ] Failing PHPUnit test written first (`tests/Unit/SettingsControllerTest::test_probe_dispatch`)
- [ ] `class-probe-outcome.php` added with nine constants; autoload verified via runtime `class_exists` check ([rg-016])
- [ ] `get_tenant_id()` derivation extracted into a shared helper (trait or `TenantIdentity` class); abstract proxy controller delegates to it; `TenantIdentityTest` PHPUnit added
- [ ] `test_connection` probes `/recognition/health/pool` (assertion in test guards regression)
- [ ] `X-Tenant-ID` forwarded using the shared tenant helper (matches the value sent by existing recognition proxy calls)
- [ ] All nine response shapes map to the correct outcome code
- [ ] `retry_after_seconds` parsed from `Retry-After` header on 429
- [ ] Security contract updated in the same slice with the Plugin probe contract subsection
- [ ] PHPUnit passes

### Checklist for Slice 2: Nine-State Settings Page Renderer

- [ ] Failing Vitest cases written first (`SettingsPage.test.tsx`)
- [ ] `TestConnectionOutcome` `as const` + type alias in `settingsApi.ts` ([sr-007])
- [ ] `SettingsPage.tsx` switches on `outcome` with exhaustive `never` check ([sr-005])
- [ ] Each banner renders primary line + remediation hint; `rate_limited` interpolates `retry_after_seconds`
- [ ] All nine Vitest cases pass
- [ ] `npm run typecheck` green

### Checklist for Slice 3: Staging Demo Smoke

- [ ] Four staging smoke scenarios run and recorded as `test_result` events
- [ ] Full `make check` pass from repo root (or per-app equivalent)

## Review Readiness

- [ ] Security contract documents the probe outcome taxonomy
- [ ] No raw API keys in logs, responses, or test fixtures
- [ ] `connected` bool stays consistent with `outcome === 'connected'`
- [ ] Handoff decision recorded per slice; final `close_slice` per slice

## Success Criteria

- [ ] "Test Connection" with a revoked key shows the `revoked` banner, not "Connection successful!"
- [ ] "Test Connection" with a wrong-tenant key shows the `tenant_mismatch` banner
- [ ] `rate_limited` banner shows a concrete `Retry-After` seconds value
- [ ] Adding a tenth outcome to `TestConnectionOutcome` without updating `SettingsPage.tsx` fails `npm run typecheck`
- [ ] PHPUnit assertion guards against the probe URL regressing to `/recognition/health`
- [ ] Security contract's Plugin probe contract section maps each of the nine outcomes to an `_require_auth_impl` anchor

## Open Questions

1. **TLS vs network error discrimination.** `is_wp_error()` returns a `WP_Error` with an error code like `http_request_failed` and a message string. Distinguishing cert failures from generic network failures requires string-matching on the message (e.g. `stripos($msg, 'certificate')`). Acceptable for MVP? Or fold `tls_error` into `network_error` and defer the split?
2. **Should the save form block saving an obviously invalid key before probing?** Out of scope for MVP per scope decision; flag as a follow-on if beta testers ask.
3. **Trait vs static helper for tenant-id extraction.** Both achieve the same bit-identical derivation. Trait preserves the existing `$this->get_tenant_id()` call site shape in the proxy controller; static helper is easier for `SettingsController` to consume without touching inheritance. Decide at implementation time — the test (`TenantIdentityTest`) is the contract either way.
