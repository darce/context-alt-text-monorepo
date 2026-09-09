# UXA-02. Honest Service Status / Heartbeat

> **Metadata**
>
> - **Date**: 2026-09-09
> - **Author**: grok-4.6
> - **Project**: prototype-wp-alt-context (admin SPA + PHP proxy) · prototype-description-service (recognition)
> - **Task ID**: `UXA-02`
> - **Target Branch**: `feature/uxa-02`
> - **Review Coverage Target**: 2
> - **Split from**: `UXP-2` at `c7587ce2` (operator scope-split). Binding inputs are the UXP-2 planning-review blockers against the heartbeat design.

---

## Objective

Make the admin's service-status banner and write-gating reflect **measured** recognition-service health when idle, without unblocking mutations against a tripped breaker, without collapsing `ProbeOutcome`'s 11 constants into a boolean, and without a cron heartbeat that flaps, races, or auto-pairs.

## Intake

- **Scope one-pager**: `docs/scopes/uxp-ux-pass-decomposition.md` (§ UXP-2 originally bundled UXA-01 + UXA-02)
- **Source assessment**: `docs/assessments/current/ux-ui-pass-assessment-2026-07-15.md` (**UXA-02** only)
- **Predecessor**: `docs/tasks/uxp/UXP-2-network-discipline-task-plan.md` (429 backoff + suggestion fan-out; heartbeat explicitly Not-Doing)
- **Binding inputs**: UXP-2 planning-review blockers against the heartbeat (write-gating, probe classification, exclusive-trigger table, `/health/detailed` semantics, TTL vs WP-cron, cron ownership, per-interval lock, banner/dashboard exhaustiveness, `base_url` keying, pairing side-effect, autoload). Reference those IDs in handoff; do not paste their bodies here.
- **Not-Doing**:
  - UXP-2's typed `HTTPError`, QueryClient retry predicate, cooldown, or suggestion batch (already its own task).
  - Server-side rate-limit redesign (E20-7/E20-11).
  - Redefining `isSyncOffline` as a drive-by of banner copy.

## Problem Statement

There is no health ping. `useSyncHealth` polls WP-local `sync/health`, which only reads the proxy circuit-breaker transient. The breaker opens after two failed proxied requests and auto-expires in 60s. With no traffic, state reverts to closed regardless of actual service health. Settings → Test connection is the only real probe (`GET {base}/health/detailed`), and it is operator-initiated.

The original UXP-2 heartbeat design tried to close that gap and independently failed planning review on six high and three medium design errors. Those errors are **this task's starting constraints**, not optional polish.

## Constraints

### Write-gating must not silently relax (binding)

Today a tripped breaker **disables** mutations via `useSyncOffline()`. Production callers (freeze this roster; do not treat tests as the list):

- `js/admin/pages/roster/hooks/useClusterActions.ts`
- `js/admin/pages/dashboard/DescribePanel.tsx`
- `js/admin/pages/workbench/MediaSelection.tsx`
- `js/admin/pages/workbench/ConfirmTabContent.tsx`
- `js/admin/pages/workbench/identity-clusters/useClusterActionMutations.ts`

Banner/summary consumers of `resolveEffectiveSyncHealth` (`degradedModeBannerLogic.ts`) — not write-gates, but must stay exhaustive:

- `js/admin/pages/workbench/syncPresentation.ts`
- `js/admin/pages/DashboardPage.tsx`

If breaker-open is reassigned from `offline` to `degraded` for banner copy, **`isSyncOffline` must keep returning true for breaker-open**, or a new dedicated write-gate must land in the same slice and be wired into **every** `useSyncOffline()` production caller above. Naming only `degradedModeBannerLogic.ts` / `DegradedModeBanner.tsx`, or only the roster+describe pair, is a behavior regression: workbench describe/cluster mutations would issue at a host that just failed twice.

### Probe outcome is the full `ProbeOutcome` set, not a boolean (binding)

`ProbeOutcome` (`src/api/class-probe-outcome.php`; mirrored by `TestConnectionOutcome` in `settingsApi.ts`) has **11** constants:

`CONNECTED`, `NOT_CONFIGURED`, `INVALID_KEY`, `EXPIRED`, `REVOKED`, `TENANT_MISMATCH`, `RATE_LIMITED`, `SERVER_ERROR`, `NETWORK_ERROR`, `TLS_ERROR`, `TENANT_PAIRING_CONFLICT`.

`SettingsController::classify_http_status` covers only the HTTP subset (`CONNECTED` / `INVALID_KEY` / `EXPIRED` / `REVOKED` / `TENANT_MISMATCH` / `RATE_LIMITED` / `SERVER_ERROR`). The other four are local or transport: `NOT_CONFIGURED` (pre-HTTP), `NETWORK_ERROR`, `TLS_ERROR`, `TENANT_PAIRING_CONFLICT`. A probe payload of `{at, ok, source}` discards all of that. Do **not** call this "six-way". Do not design against the HTTP subset alone.

Consequences that the design must prevent:

- A 429 on the probe (the condition UXP-2 exists to handle) must **not** yield `ok:false` → `offline` with `alert`/`assertive` while every real request succeeds. `RATE_LIMITED` is not offline.
- An expired key must **not** render "The recognition backend is currently unreachable" for a service that is up.
- `NETWORK_ERROR` / `TLS_ERROR` are transport failures, not credential failures; `NOT_CONFIGURED` is a local precondition (no request); `TENANT_PAIRING_CONFLICT` is a pairing state the heartbeat must not produce (pairing is excluded) but the banner/write-gate machine must still handle because Settings Test can emit it.
- There must be an explicit 429-storm / rate-limited state in the state machine, not a boolean collapse.

Reuse the existing `ProbeOutcome` set. Exhaustive switch (sr-007). Do not invent a second taxonomy.

### States are an ordered predicate chain (binding)

Do **not** publish a table that claims "exactly one exclusive trigger" per row. The failed design had `degraded = breaker.state==='open' && probe.ok !== false`. With no probe, `probe.ok` is `undefined`, and `undefined !== false` is `true`, so breaker-open + no-probe matched both `degraded` and `idle-unknown`.

Required:

- Discriminate **probe absence first**.
- Then breaker state.
- Then classified probe outcome.
- Then freshness.
- One ordered function; exhaustive switch (sr-007). Slice proofs must include the breaker-open + no-probe cell.

### `/health/detailed` is the wrong 2xx oracle (binding)

`api/main.py` aggregates `check_database` + `check_breaker` + `check_model_cache` into a **body** status and returns HTTP 200 regardless (`/ready` is the 503 flip). Deriving `ok` from the HTTP code reads healthy when the recognition DB is down. The endpoint comment says it is an operator diagnostic "never hit by load-balancer probes".

Required:

- Derive health from the **body status**, not the HTTP code.
- Do not make `/health/detailed` a per-60s-per-site monitor as-is: each call costs a DB roundtrip plus `bundle.glob('*.onnx')`. Prefer a cheaper authenticated ping, or cache the expensive checks server-side, and state the cost bound.

### Freshness is computed at read time against the configured interval (binding)

WP-cron cannot deliver a 60s cadence. `WP_CRON_LOCK_TIMEOUT` defaults to 60s, so a 60s recurrence realistically fires every 60–120s. Under `DISABLE_WP_CRON` + system cron (standard production, typically 1–5 min) the period reaches 300s. A 180s TTL then expires between ticks and the banner permanently oscillates healthy ↔ idle-unknown on a fully working site.

"Cron disabled entirely" is not the common case; "cron slower than my TTL" is. A ~65s detection claim is unsupportable on those hosts.

Required: freshness = `now - probe.at` compared to `max(configured_interval * N, minimum_floor)` at **read** time, not a baked TTL that assumes a 60s tick.

### LifeCycleManager owns cron (binding)

`src/support/class-life-cycle-manager.php` is the plugin's cron owner. It clears `SNAPSHOT_SYNC_HOOK`, curation-outbox drain, and split-topology drain in **both** `deactivate()` and `uninstall()`, and prefers Action Scheduler (`as_enqueue_async_action`) when available.

Activation hooks are skipped by this project's forced-install deploy path (`class-life-cycle-manager.php` documents that WP-admin plugin updates and `wp plugin install --force` skip activation hooks). The in-repo pattern (`class-outbox-drain.php`) schedules under a runtime `wp_next_scheduled()` guard.

Required:

- Register / reschedule under a runtime `wp_next_scheduled()` (or Action Scheduler equivalent) guard, not an activation hook.
- Clear the event on both deactivate and uninstall. A removed plugin must not leave a 60s event whose `cron_schedules` recurrence no longer exists.
- Do not duplicate LifeCycleManager with a second cron owner.

### Per-interval bound is a lock, not a wish (binding)

`<=1 request / interval / site` is not inherited from `wp_schedule_event`. `doing_cron` is best-effort and races under the multi-admin case the breaker already had to solve with a MySQL named lock (`class-abstract-recognition-proxy-controller.php`). The probe has no such guard, and `source='settings_test'` writing the same key unthrottled defeats the bound.

Required: self-throttle on the transient's `at` **under the existing named-lock helper**. A Slice proof "probe runs at most once per interval across repeated cron ticks" is only possible if that mechanism exists.

### Every new state has exhaustive consumers (binding)

`shouldShowDegradedBanner` today renders only when `isSyncOffline || hasSyncHealthWarnings`, so `idle-unknown` would never render. `getDashboardSyncHealthSummary`'s switch defaults to "Machine state is stale" for any new state.

`idle-unknown` is the **steady state** on the verification environments: fresh activation, loopback-blocked hosts (LocalWP / dev / firewalled staging), and `DISABLE_WP_CRON` sites. Shipping a state that never renders, with no diagnostic and no repair affordance, is not honest status.

Required: `shouldShowDegradedBanner`, `resolveEffectiveSyncHealth`, `getDashboardSyncHealthSummary`, and `syncPresentation` all get exhaustive handling of every new state (sr-007). `idle-unknown` needs copy, a live-region policy, and a repair action (open Settings / Test connection / enable cron).

### Probe state is keyed by `base_url` (binding)

`RecognitionCircuitKeys::for_base_url` keys the circuit per host so a target change does not inherit stale state. Probe state must use the same helper. Cron runs with **no** admin request context; `resolve_settings_snapshot()['effective_target_url']` and `TenantIdentity::resolve()` can vary with the `acx_recognition_base_url` filter and the dev hatch. The plan must state which context resolves the probe target under cron, and that it matches the target sync/health reports on.

### Extracted probe excludes pairing (binding)

`SettingsController::test_connection` uses `timeout => 10` on a single attempt and, on `CONNECTED` / `TENANT_MISMATCH`, attempts tenant pairing. A cron heartbeat that inherits that side effect auto-pairs every interval.

Required:

- The heartbeat probe **must not** pair.
- State the actual timeout (2×10s is not "short"); pick a short single-attempt timeout and name it.
- A manual Settings "Test" must **not** write the same freshness transient as the cron heartbeat, or a site where cron never runs reads healthy for the full window and defeats OBS-08.

### Autoload (rg-016)

Any new WordPress-style `class-*.php` (e.g. `class-recognition-probe.php`, `class-recognition-heartbeat.php`) is not PSR-4 autoloadable. Name the `require_once` entrypoint and add an rg-016 runtime `class_exists` check. Follow `class-sync-health-controller.php`.

## Workflow Principles

- Honest status is measured, not inferred from traffic.
- Banner copy and write-gating are **separate seams**. Copy may distinguish degraded vs offline; write-gating may not silently follow.
- One classification function, one freshness function, one lock. No second taxonomy, no second cron owner.
- Fail closed on probe absence: do not treat "we have not pinged" as healthy.

## Terminology

- **Probe**: authenticated request that classifies recognition-service reachability using the full `ProbeOutcome` set (11 constants; HTTP subset via `classify_http_status` plus `NOT_CONFIGURED` / `NETWORK_ERROR` / `TLS_ERROR` / `TENANT_PAIRING_CONFLICT`), body status for `/health/detailed` if that endpoint is used, never HTTP 2xx alone.
- **Heartbeat**: scheduled probe that writes a `base_url`-keyed transient under a named lock.
- **Freshness**: read-time age of the last successful-or-classified probe versus the configured interval, not a fixed TTL.
- **Idle-unknown**: no fresh probe and breaker closed — the honest state on LocalWP / cron-slow / freshly activated sites.
- **Write-gate**: the predicate that disables cluster mutations and describe. Independent of banner visibility.

## Current State Analysis

**Works today:** proxy breaker trips deterministically under a lock-guarded counter; Settings Test connection already classifies the full `ProbeOutcome` set; `LifeCycleManager` already owns cron lifecycle; `RecognitionCircuitKeys::for_base_url` already keys per host.

**Broken:** idle banner is traffic-derived; no heartbeat; `isSyncOffline` is the write-gate and the banner input at once.

**Misleading:** `/health/detailed` HTTP 200; any design that treats WP-cron 60s as a real SLA.

## Target Outcome

Stopping the OCI service flips the banner to a measured offline (or classified failure) state within one configured interval **without any job running**; restart flips it back. A tripped breaker still blocks mutations. A 429 on the probe is rate-limited, not offline. Slow cron does not flap a healthy site. Cron registration survives forced install and is cleared on uninstall.

## Context Loading

- Rules: `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/backend-php-guidelines.md`, `docs/workbay/rules/testing-typescript.md`
- Heuristics: honest-status / OBS-08, RES-15, sr-007, rg-016, A11Y-21/A11Y-24
- Code: `class-settings-controller.php` (`classify_http_status`, `test_connection`), `class-abstract-recognition-proxy-controller.php` (named lock, breaker), `class-life-cycle-manager.php`, `class-outbox-drain.php` (runtime schedule guard), `degradedModeBannerLogic.ts`, `useSyncOffline.ts`, `syncPresentation.ts`, recognition `api/main.py` `/health/detailed` vs `/ready`

## Contract and Boundary Impact

| Boundary | Owner | Current | Expected change | Verification |
| --- | --- | --- | --- | --- |
| Probe transient | PHP | none (breaker only) | `base_url`-keyed, lock-guarded, classified outcome + `at` + `source` | unit: keying, lock, throttle, no pairing |
| `GET /health/detailed` | recognition | HTTP 200 + body status | consumed by body status if used; or replaced by cheaper ping | unit: unhealthy body → not CONNECTED |
| Banner + dashboard | TS | `isSyncOffline` / 6-arm summary | exhaustive new states; write-gate unchanged unless explicitly replaced | matrix tests including no-probe + breaker-open |
| Cron | PHP LifeCycleManager | N/A | runtime schedule + deactivate/uninstall clear | tests for skip-activation and uninstall |

## Proposed Solution

Four slices. Slice 1 pins the state machine and write-gate **before** any probe exists, so the no-probe cells are designed rather than discovered. Slice 2 extracts a pairing-free classified probe. Slice 3 installs the heartbeat under LifeCycleManager + named lock. Slice 4 wires banner/dashboard exhaustively.

### Slice 1 — Ordered state function + write-gate freeze

One TS function, ordered predicates:

1. Probe missing → if breaker open: keep write-gate closed; banner `degraded` (breaker) **or** a named `idle-unknown-with-breaker` — pick one and test it; never both.
2. Probe missing → breaker closed → `idle-unknown`.
3. Probe present, stale by read-time freshness → treat as missing (step 1/2).
4. Probe present, fresh → exhaustive switch on **all 11** `ProbeOutcome` constants:
   - `CONNECTED` — healthy (if `/health/detailed` is the target, body status must also be healthy).
   - `RATE_LIMITED` — rate-limited, **not** offline; writes stay allowed unless the breaker is open.
   - `EXPIRED` / `INVALID_KEY` / `REVOKED` — credential states; not "unreachable".
   - `TENANT_MISMATCH` / `TENANT_PAIRING_CONFLICT` — tenant/pairing states; heartbeat must not emit the latter (no pairing), but the function still handles it.
   - `SERVER_ERROR` / `NETWORK_ERROR` — service/transport unreachable → offline-class.
   - `TLS_ERROR` — TLS/transport failure, distinct copy from generic unreachable.
   - `NOT_CONFIGURED` — local precondition; no backend configured; not a failed ping.

Freeze: `isSyncOffline` continues to mean "writes are unsafe" and **includes breaker-open** unless Slice 1 introduces `isSyncWriteBlocked` and migrates **every production `useSyncOffline()` caller** in the same commit (`useClusterActions.ts`, `DescribePanel.tsx`, `MediaSelection.tsx`, `ConfirmTabContent.tsx`, `useClusterActionMutations.ts`). Tests that mock the hook are not the freeze list.

Proof: TS matrix covering every cell, including breaker-open + no-probe, RATE_LIMITED + breaker-closed, and dedicated cells for `NETWORK_ERROR`, `TLS_ERROR`, and `NOT_CONFIGURED` (plus `TENANT_PAIRING_CONFLICT` even though the heartbeat must not pair). Each new assertion watched failing once.

### Slice 2 — Pairing-free classified probe

Extract probe from `test_connection` **without** the pairing branch. Timeout: one short attempt (name the seconds; do not silently inherit 10s×2). If `/health/detailed` is the target, parse body status; document cost or switch to `/ready` / a dedicated cheap ping.

Manual Settings Test keeps pairing (that is the operator action) and does **not** stamp the heartbeat freshness key.

Proof: PHP unit — pairing not invoked; RATE_LIMITED classified; HTTP 200 + unhealthy body ≠ CONNECTED; settings-test source does not refresh heartbeat `at`.

### Slice 3 — Heartbeat schedule + lock + keying

- Key via `RecognitionCircuitKeys::for_base_url`.
- Named lock around read-modify-write of `at`.
- Self-throttle: if `now - at < interval`, no request.
- Schedule from a runtime `wp_next_scheduled()` / Action Scheduler path owned by LifeCycleManager; clear on deactivate and uninstall.
- Cron-resolved target = `effective_target_url` from the same snapshot sync/health uses, with no admin request. State that in code comments.

Proof: two overlapping ticks issue one request; uninstall removes the event; forced-install path still schedules on first runtime request.

### Slice 4 — Banner, dashboard, idle-unknown repair

Exhaustive handling in `shouldShowDegradedBanner`, `resolveEffectiveSyncHealth`, `getDashboardSyncHealthSummary`, `syncPresentation`. `idle-unknown` renders with consequence + action (open Settings, run Test, enable cron). Announce via `role="status"` / live region (A11Y-21).

Proof: component tests for each state; LocalWP-shaped fixture (no probe, breaker closed) shows idle-unknown, not healthy and not silent.

## Files and Surfaces to Change

| Surface | File : symbol | Change |
| --- | --- | --- |
| TS | `degradedModeBannerLogic.ts` | ordered state function; do not claim exclusive table triggers |
| TS | `useSyncOffline.ts` and every production caller: `useClusterActions.ts`, `DescribePanel.tsx`, `MediaSelection.tsx`, `ConfirmTabContent.tsx`, `useClusterActionMutations.ts` | freeze or replace **all five** in-slice |
| TS | `syncPresentation.ts`, `DashboardPage.tsx`, `DegradedModeBanner.tsx` | exhaustive states |
| PHP | new probe + heartbeat classes | pairing-free; rg-016 require_once named |
| PHP | `class-life-cycle-manager.php` | schedule + clear |
| PHP | Settings test_connection | do not share heartbeat freshness key |
| tests | TS + PHP | matrix, lock, uninstall, body-status |

## Slice Delivery

See Proposed Solution. Do not start Slice 3 until Slice 1's no-probe cells and Slice 2's classification are green — a heartbeat that writes a boolean into an exclusive-trigger table re-introduces the failed design.

## Success Criteria

- [ ] Stopping recognition with no jobs running moves the banner to a measured/classified failure within one configured interval on a host whose cron actually fires at that interval; the claim is not "~65s on WP-cron".
- [ ] Breaker-open still blocks every production `useSyncOffline()` caller (roster cluster actions, dashboard describe, workbench MediaSelection, ConfirmTabContent, identity-cluster mutations) — or the replacement write-gate does, with all five migrated in the same slice.
- [ ] `RATE_LIMITED` is not rendered as offline.
- [ ] Breaker-open + no-probe produces exactly one state, tested.
- [ ] Unhealthy `/health/detailed` body is not treated as CONNECTED.
- [ ] Slow cron (interval > previous 180s TTL) does not flap a healthy site.
- [ ] Heartbeat does not pair; Settings Test does not stamp heartbeat freshness.
- [ ] Event is cleared on deactivate and uninstall; registration does not depend on activation hooks.
- [ ] `idle-unknown` is visible and actionable on LocalWP-shaped hosts.

## Review Readiness

- [ ] Write-gate consumers listed above are named in the diff, not only banner files: `useClusterActions.ts`, `DescribePanel.tsx`, `MediaSelection.tsx`, `ConfirmTabContent.tsx`, `useClusterActionMutations.ts`. A freeze that names only roster+describe is a fail.
- [ ] Classification reuses the full `ProbeOutcome` set (11 constants), not a boolean and not the HTTP-only `classify_http_status` subset.
- [ ] rg-016 check recorded for any new `class-*.php`.
