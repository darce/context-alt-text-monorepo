# ADR-011: Retire On-Device Recognition — Single Shared Remote Backend, Key-Driven Tenanting, Offline Plugin Sovereignty for Display

## Status

Proposed

## Date

2026-07-09

## Context

The product shape is settled: media lives in the local WordPress plugin; **new** recognition and alt-text inference is sent over the wire to a **single shared hosted recognition service** (`altcontext.com`) running on one GPU box, with per-customer isolation enforced by **Postgres RLS** at the database level. Customers do not run their own recognition hardware.

The recognition service (`apps/prototype-description-service`) was built **local-first**: it can run on-device (dev/host machine, CPU InsightFace models) *and* against a hosted service, selected by a plugin-side `local` / `service` mode. That dual mode, combined with a tenant identity **derived from the WordPress site URL**, produces recurring operational confusion — most visibly the "tenant mismatch → Unreachable" trap where a valid key is rejected because the plugin's *claimed* (URL-derived) tenant does not match the key's *bound* tenant.

As inference moves to GPU (remote only), on-device CPU recognition has no remaining value: it is slower, lower quality, and doubles the code paths. The E14 self-hosting epic already targets a **GPU inference server + WordPress frontend**, and the OCI backend is live at `api.altcontext.com`.

This ADR resolves the design question: **retire on-device recognition, collapse to a single remote path, and make tenanting key-driven** — while preserving the one thing local sovereignty must guarantee: offline **display**.

### Constraints from prior review

> Established by product-owner clarification (2026-07-09). Non-negotiable.

- **Single shared backend.** One GPU box (`altcontext.com`) serves all customers; isolation is Postgres RLS, not per-customer servers or hardware. There is no customer-run recognition server.
- **No local recognition models.** On-device inference is retired entirely.
- **Plugin sovereignty = offline display.** Users MUST always be able to view their media, already-computed identity clusters, and already-inferred alt-text captions **with no remote connection**. Only *new* recognition/inference requires the remote service. Remote-unreachable must degrade to "cannot compute new," never "cannot view existing."

## Current State Inventory

> Grounded in the live codebase (commit `9551d929`).

- **Plugin recognition mode** — `Admin::get_recognition_source()` returns `local` | `service` (`apps/prototype-wp-alt-context/src/admin/class-admin.php:380`); an endpoint resolver picks the local vs hosted URL.
- **Dual-mode health probe** — `class-settings-controller.php:238-296`: `local` mode probes `/health` (liveness only); `service` mode probes `/health/detailed` with `X-Tenant-ID` + `X-API-Key` headers.
- **URL-derived tenant** — `TenantIdentity::resolve()` precedence is constant → filter → option → **derived-from-site-URL** (`class-tenant-identity.php:105`, `derive_site_url_tenant_id()` = a UUIDv5-style `sha1('acx-site-tenant:' + site_url)`).
- **Server tenant enforcement** — `recognition/.../deps/auth.py:198-208`: when both a key tenant claim and an `X-Tenant-ID` header are present and differ, the server raises `403 "tenant mismatch"`.
- **Misleading UI label** — `js/admin/pages/settings/healthStatus.ts:25` maps **every** non-`connected` outcome (`invalid_key`, `tenant_mismatch`, `expired`, `revoked`, `rate_limited`, `server_error`) to `Unreachable`.
- **Pairing deadlock** — `attempt_tenant_pairing()` (`whoami` → adopt the key's tenant) only runs *after* the probe returns `CONNECTED` (`class-settings-controller.php:275`). On a tenant mismatch the probe returns `403` (not `CONNECTED`), so auto-adoption can never run — the plugin is stuck behind the very mismatch pairing was meant to resolve.
- **WP sovereign mirror tables** — local WordPress DB tables (roster/clusters/identity members, cached captions) that render media, clusters, and captions in the admin UI. This is a **display cache**, independent of where inference runs.
- **Recognition Postgres (pgvector)** — the recognition service's own store; today provisioned per deployment (local dev vs OCI).

### Downstream surfaces that must migrate together

- `apps/prototype-wp-alt-context/src/admin/class-admin.php` — recognition-source resolution, localized `recognitionSource`/`effectiveTargetUrl`.
- `apps/prototype-wp-alt-context/src/api/class-settings-controller.php` — dual-mode health probe, tenant pairing, `X-Tenant-ID` header emission.
- `apps/prototype-wp-alt-context/src/api/class-tenant-identity.php` — derive-from-URL bootstrap and override precedence.
- `apps/prototype-wp-alt-context/js/admin/pages/settings/*` — local/hosted toggle, `healthStatus` mapping, test-connection banner.
- `apps/prototype-wp-alt-context/js/admin/api/settingsApi.ts` — settings response contract (`tenant_id`, `tenant_id_source`, `tenant_paired`).
- Any local-recognition deployment path (local Postgres, on-device model provisioning) in `apps/prototype-description-service`.

## Decision

Retire on-device recognition. Collapse the plugin to a **single remote path** against the shared hosted service, make tenanting **key-driven**, and guarantee **offline display** from the sovereign mirror.

### Chosen design rules

1. **Remote-only recognition.** All new recognition/inference targets the single shared hosted service (`altcontext.com`). Remove the on-device recognition runtime, local model provisioning, and the local recognition-Postgres product path. Delete-over-flag (greenfield policy) — no `local`/`service` mode branches remain.
2. **Single shared, RLS-isolated backend.** The service endpoint is the hosted service; it is **not** a customer-facing "choose your server" control. Isolation is Postgres RLS per tenant. Internal dev/staging/eval endpoints may remain as **advanced/constant** overrides (`ACX_RECOGNITION_BASE_URL`), never as a user-facing mode.
3. **Key-driven tenant adoption.** The plugin adopts the tenant **bound to its API key** (via `GET /recognition/tenant/whoami`) at key-save time, and persists it. Derive-from-site-URL is dropped as the tenant *source of truth*. This eliminates the tenant-mismatch class: paste key → plugin reads the key's tenant → done. The plugin must not send a stale, self-derived `X-Tenant-ID` that can 403 the probe before adoption.
4. **Offline sovereignty for display.** Rendering media, computed clusters, and inferred captions reads **only** from the WP sovereign mirror and MUST NOT depend on remote reachability. Remote calls are required solely to compute *new* recognition/inference. A down remote surface disables "analyze new," never "view existing."
5. **Remote-only settings UI + identity display.** Remove the local/hosted service toggle; show a single hosted-service view. Add **Key ID** and **Tenant ID** (read-only, copyable, sourced from `/tenant/whoami`) to the settings page so clients can self-identify for support.

### Target outcome

- One recognition code path (remote). Zero `local`-mode branches.
- Zero "tenant mismatch → Unreachable" occurrences: tenant is always the key's tenant.
- Media/clusters/captions render with the network fully offline.
- Settings page shows: hosted service status, Key ID, Tenant ID — no mode toggle.

## Why This Decision

### GPU-remote dominates on-device

CPU InsightFace/VLM inference on the WordPress host is slower and lower quality than the shared GPU backend. Post-GPU there is no scenario where on-device inference is the right choice, so the second code path is pure liability.

### One path deletes three defects at once

The dual `local`/`service` mode, the derive-then-reconcile tenant bootstrap, and the pairing deadlock are all artifacts of local-first design. Collapsing to remote-only + key-driven tenanting removes the dual-mode probe, the URL-derived tenant reconciliation, and the deadlock in a single move — not three separate patches.

### Support becomes possible

Surfacing Key ID + Tenant ID gives clients a stable, non-secret identifier to quote. Today the tenant is only visible transiently inside a conflict banner.

### Sovereignty kept where it matters

Offline **display** is the real sovereignty guarantee (users own and can always see their data). Offline **inference** was never a requirement and is dead weight. This decision preserves the former and drops the latter.

## Alternatives Considered

### 1. Keep the dual local/service mode

Rejected. On-device inference has no value after the GPU move, and the dual mode is the direct cause of the tenant-mismatch confusion and the two UI/flow bugs. Maintaining it means carrying two probe paths, two deployment stories, and the derive-from-URL bootstrap indefinitely.

### 2. Customer-run self-hosted recognition servers (configurable endpoint as a product feature)

Rejected. Hardware is shared and isolation is RLS at the DB level — there is no per-customer box. Exposing "point at your own server" would contradict the single-backend model, multiply the operations surface, and invite unsupported deployments. (An internal-only constant override for dev/staging/eval is retained, but it is not a customer feature.)

### 3. Keep derive-from-URL tenanting with auto-reconciliation

Rejected. The derive→reconcile handshake is precisely what deadlocks: the plugin sends its URL-derived `X-Tenant-ID`, the server 403s on mismatch, and the pairing/adopt step that would fix it never runs because it is gated behind a `CONNECTED` probe. Key-driven adoption is both simpler and correct — the key already unambiguously identifies its tenant.

### 4. Retire the WP sovereign mirror too (thin client, always fetch from remote)

Rejected. It violates the hard offline-display constraint: users must always see their media, clusters, and captions with no network. The mirror is the sovereignty guarantee and stays.

## Consequences

### Positive

- Single recognition path; the `local`/`service` split, dual-mode probe, and pairing deadlock are deleted.
- The entire "tenant mismatch → Unreachable" failure class disappears (tenant = the key's tenant).
- Simpler settings UI; clearer support via visible Key ID + Tenant ID.
- Offline display sovereignty preserved and made explicit/testable.

### Negative

- No offline **inference** — new recognition/captioning hard-depends on the hosted service. (Accepted; not a requirement.)
- Removal work touches the plugin endpoint resolver, health controller, tenant identity, and settings UI plus their tests.
- Hard dependency on a single shared backend's availability for new analysis; sovereign display must be proven to hold when that backend is down.

### Guardrails for the follow-on implementation task

- **Never gate display on remote reachability.** Media/cluster/caption reads come from the sovereign mirror only; those code paths must make no network call. Add a test that renders the roster/clusters/captions with the remote endpoint stubbed unreachable.
- **Tenant source of truth = the key's tenant via `/tenant/whoami`.** Remove derive-from-URL as authority. Do not send a self-derived `X-Tenant-ID` that can 403 a probe; send only the adopted tenant, or omit the header and let the key's claim stand.
- **Delete-over-flag.** Remove `local`-mode branches wholesale, not behind a feature flag (greenfield policy — no production users/data to preserve).
- **Settings UI:** single hosted-service view; no local/hosted toggle; Key ID + Tenant ID read-only + copyable, sourced from `/tenant/whoami`.
- **Fix or moot the label:** surface the real probe outcome (`invalid_key`, `tenant_mismatch`, `rate_limited`, …) instead of collapsing to `Unreachable`. Key-driven adoption should make `tenant_mismatch` unreachable in practice, but the label must still be honest for the remaining outcomes.

## Implementation Plan (follow-on task, derived from this ADR)

> Sliced for the derived task plan; not tracked here.

1. **Key-driven tenant adoption.** Adopt the key's tenant via `/tenant/whoami` on key save; drop derive-from-URL authority; stop sending the stale `X-Tenant-ID`; remove the pairing deadlock.
2. **Settings UI → remote-only + identity.** Remove the local/hosted toggle; single hosted-service view; add read-only, copyable **Key ID** + **Tenant ID**; fix the `Unreachable` label to reflect the real outcome.
3. **Remove on-device recognition.** Delete local-mode code paths in the plugin and the local recognition runtime / local-Postgres product path in the service.
4. **Offline-display proof.** Add tests asserting media/clusters/captions render with the remote surface unreachable.

## References

- Epic: [E14 Self-Hosting & Multi-Server Connectivity](../epics/v0.3.1/self-hosting-epic.md) — OCI backend live at `api.altcontext.com`; GPU inference server target.
- Epic: [E15 Public Demo Launch Readiness](../epics/v0.4.0/public-demo-launch-readiness-epic.md).
- Prior art: [ADR-003 WordPress Local Authority and Durable Outbox Replay](./ADR-003-wordpress-local-authority-and-durable-outbox-replay.md); [ADR-002 Person as First-Class Local Entity](./ADR-002-person-as-first-class-local-entity.md).
- Code: `recognition/interface_adapters/http/deps/auth.py:198-208` (tenant enforcement); `apps/prototype-wp-alt-context/src/api/class-tenant-identity.php` (derive-from-URL); `apps/prototype-wp-alt-context/src/api/class-settings-controller.php:238-296` (dual-mode probe + pairing); `apps/prototype-wp-alt-context/js/admin/pages/settings/healthStatus.ts:25` (label mapping).
- Implementation task plan: _to be created from this ADR after planning review._
