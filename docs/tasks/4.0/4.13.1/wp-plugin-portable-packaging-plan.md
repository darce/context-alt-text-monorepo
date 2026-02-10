# Portable Versioned Plugin Packaging (v4.13.1)

## Problem Statement

The plugin source lives inside a monorepo (`apps/prototype-wp-alt-context/`) and cannot be installed into an arbitrary WordPress instance without manual file surgery. A reproducible packaging workflow is needed to produce a versioned ZIP artifact that installs standalone and connects to the recognition service through runtime configuration only — no monorepo path coupling.

## Workflow Principles

- **Greenfield/direct-cutover posture** — no backward-compatibility shims or feature flags (per `instructions.md` Remove Over Flag rule).
- **Operational decoupling** — the plugin never derives service location from monorepo paths, `ABSPATH`, or filesystem discovery.
- **Deterministic artifacts** — same source commit always produces the same ZIP contents; packaging fails on version mismatch.
- **Sovereign roadmap safety** — packaging must not conflict with the `wp-sovereign-cluster-roadmap.md` phases; local-projection and scheduled-sync code ships in the ZIP even if backend endpoints are not yet live.

## Terminology

- **Recognition service**: the Python FastAPI backend in `apps/prototype-description-service/`.
- **Tenant ID**: `md5(get_site_url())` — 32-char hex string identifying a WordPress site to the backend.
- **Snapshot endpoint**: planned `GET /tenants/{tenant_id}/clusters/snapshot` (sovereign roadmap v0.1.0 — **does not yet exist** in contracts or backend).
- **Packaging script**: a shell script that assembles a staging directory and produces a versioned ZIP.

## Current State Analysis

What works:

- Plugin header declares version `0.0.1`, text domain `alt-context`, Domain Path `/public/languages`.
- Built assets exist at `public/assets/dist/` (Vite-produced `admin-*.css` and `admin-*.js`).
- Composer `vendor/` and `vendor/autoload.php` exist (but currently include dev-only packages — phpunit, squizlabs, wp-coding-standards — that must be excluded from a production ZIP).
- Lifecycle hooks (`register_activation_hook`, `register_deactivation_hook`, `register_uninstall_hook`) are wired in `alt-context.php` and delegate to `LifecycleManager`.
- Service URL and API key are read at request time via `get_option()` in `AbstractRecognitionProxyController` (confirmed lazy — no constructor caching).
- All six automated gates pass (55 PHP tests / 161 assertions, 153 JS tests, cs-check, typecheck, lint, arch).

What's missing or incorrect:

- **No packaging script** — no `scripts/release/package-plugin.sh` or equivalent exists.
- **No `composer install --no-dev` step** — current `vendor/` bundles test tooling.
- **No constant-based endpoint override** — the Runtime Service Configuration Contract claims deployment constants have highest priority, but `AbstractRecognitionProxyController::get_recognition_base_url()` only calls `get_option('alt_context_recognition_url', 'http://localhost:8000')`. No `defined('ALT_CONTEXT_RECOGNITION_URL')` check exists, nor does a filter hook path.
- **No `load_plugin_textdomain` call** — text domain `alt-context` is used in `__()` calls but the textdomain loading function is never invoked (auto-loading from translate.wordpress.org covers hosted translations; bundled `.mo` files under Domain Path `/public/languages` would not load).
- **No WP-Cron registration** — sovereign roadmap Phase 3 requires `wp_schedule_event` for snapshot pulls; zero cron-related calls exist in `src/`.
- **Snapshot endpoint does not exist** — `GET /tenants/{tenant_id}/clusters/snapshot` is specified in the sovereign roadmap as a backend workstream but has no contract doc and no backend route.
- **Option key prefix inconsistency** — lifecycle/config options use `alt_context_*` while roster options use `acx_*`.
- **Plugin header metadata is stale** — `Tested up to: 6.3` is outdated.

## Proposed Solution

Create a shell-based packaging pipeline that:

1. Reads the canonical version from the `alt-context.php` plugin header.
2. Runs `composer install --no-dev --optimize-autoloader` into a staging directory.
3. Runs `npm run build` (Vite production build) if dist assets are stale.
4. Assembles only runtime files (`alt-context.php`, `src/`, `public/assets/dist/`, `vendor/`) into a staging directory.
5. Validates version consistency, asset presence, and autoloader integrity.
6. Produces `alt-context-<version>.zip` with `sha256` checksum.

Before packaging, harden the endpoint/auth resolution path so it respects the documented precedence (constant → option → filter → fallback) and add admin diagnostics for misconfigured environments.

## Sources Ingested

Architecture and contracts:

1. `docs/agentic/BOOTSTRAP.md`
2. `docs/agentic/instructions.md`
3. `docs/agentic/contracts/README.md`
4. `docs/agentic/diagrams/system-overview.mmd`
5. `docs/roadmaps/v0.1.0/wp-sovereign-cluster-roadmap.md`

Plugin development literature:

6. `docs/literature/extracted/wp_plugin_dev/OPS/navigation.xhtml` (Professional WordPress Plugin Development, 2nd ed.)
7. `docs/literature/wp-plugin-literature-digest.md`

## Sovereign Roadmap Alignment (v0.1.0)

This packaging plan is a delivery workstream that must not conflict with the sovereign architecture roadmap.

Roadmap constraints carried forward:

1. Greenfield/direct-cutover posture; avoid long-lived compatibility shims.
2. Plugin remains operationally decoupled from backend filesystem location.
3. v0.1.0 scheduling baseline is WP-Cron (Action Scheduler deferred to v0.2+).
4. Snapshot pull dependency on backend endpoint `GET /tenants/{tenant_id}/clusters/snapshot` is explicit — **endpoint does not yet exist** and must be built as a parallel backend workstream.

### Phase Mapping

| Sovereign Phase | Required Capability | Packaging Alignment in 4.13.1 |
|---|---|---|
| Phase 1: Scaffolding/local projection foundation | `dbDelta` schema + repository/projector primitives can ship safely | ZIP must include migration/lifecycle code, repository classes, and deterministic asset/vendor bundle integrity checks |
| Phase 2: Read-path flip | Local-first reads survive backend outage | Standalone install verification includes backend-disconnected read behavior check |
| Phase 3: Local-first writes + pull sync | Dual-write behavior and scheduled snapshot pull | Release runbook must include WP-Cron registration verification and manual sync troubleshooting |
| Phase 4: Remove hard runtime dependency | Cluster UX remains usable when backend is down | Exit criteria include non-empty local cluster UX during backend outage |

Deferred roadmap scope that is not part of this packaging slice:

1. Outbox table and bidirectional idempotent sync workflow.
2. Action Scheduler migration.
3. Drift reconciliation queue/dashboards.

## Patterns to Follow

### Constant → Option → Filter resolution (Ch.3 / Ch.12 literature)

```php
// In AbstractRecognitionProxyController or a dedicated ConfigResolver
protected function get_recognition_base_url(): string {
    // 1. Deployment constant (wp-config.php level)
    if ( defined( 'ALT_CONTEXT_RECOGNITION_URL' ) && is_string( ALT_CONTEXT_RECOGNITION_URL ) ) {
        return trim( ALT_CONTEXT_RECOGNITION_URL );
    }

    // 2. Saved plugin option (admin-managed)
    $option = trim( (string) get_option( 'alt_context_recognition_url', '' ) );
    if ( '' !== $option ) {
        return $option;
    }

    // 3. Filter hook (host-specific injection)
    $filtered = apply_filters( 'acx_recognition_base_url', '' );
    if ( is_string( $filtered ) && '' !== $filtered ) {
        return trim( $filtered );
    }

    // 4. Local-development fallback
    return 'http://localhost:8000';
}
```

### Plugin header version extraction (packaging script)

```bash
#!/usr/bin/env bash
set -euo pipefail

PLUGIN_FILE="alt-context.php"
VERSION=$(grep -m1 '^ \* Version:' "$PLUGIN_FILE" | sed 's/.*Version: *//')

if [[ -z "$VERSION" ]]; then
    echo "ERROR: Could not extract version from $PLUGIN_FILE" >&2
    exit 1
fi

echo "Packaging alt-context v${VERSION}"
```

### Vendor production install

```bash
# Staging directory gets production-only autoloader
composer install --no-dev --optimize-autoloader --working-dir="$STAGING_DIR"
```

## Delivery Gaps

| Gap ID | Gap | Why It Matters | Status |
|---|---|---|---|
| G1 | Snapshot endpoint not in contracts or backend | Sovereign Phase 1/3 depends on `GET /tenants/{tenant_id}/clusters/snapshot` | **Open** — backend workstream required; packaging can gate on contract definition |
| G2 | No backend-outage acceptance test | Phase 2/4 require local UX continuity when backend is down | Open — add offline scenario to smoke matrix |
| G3 | WP-Cron guidance under-specified | v0.1.0 sync relies on scheduled pulls; currently zero cron calls in `src/` | Open — add runbook section |
| G4 | Lifecycle policy exists but needs idempotence audit | `LifecycleManager` wires activate/deactivate/uninstall but `dbDelta` and event unscheduling are not yet implemented | Open |
| G5 | Multisite/network activation not validated | Plugin header declares `Network: false`; no `switch_to_blog` or network-activation logic | Open — add validation row |
| G6 | `load_plugin_textdomain` never called | Text domain `alt-context` is used but not explicitly loaded; Domain Path `/public/languages` is declared but loading path is absent | Open — add call + verification |
| G7 | Rollback strategy not documented | No rollback runbook or data compatibility statement | Open |
| G8 | `vendor/` includes dev dependencies | `composer install` currently bundles phpunit, squizlabs, etc. | Open — packaging must run `--no-dev` |
| G9 | Constant-based endpoint override missing | Plan claims constants have highest priority but `get_recognition_base_url()` only reads `get_option()` | Open — implement resolution precedence |

## Functions to Change

| File | Line | Change |
|---|---|---|
| `src/api/class-abstract-recognition-proxy-controller.php` | 94 | Implement constant → option → filter → fallback resolution for `get_recognition_base_url()` |
| `src/api/class-abstract-recognition-proxy-controller.php` | 98 | Same pattern for `get_recognition_api_key()` |
| `src/admin/class-admin.php` | new | Add admin notice for unconfigured/invalid endpoint (diagnostic UX) |
| `alt-context.php` | new | Add `load_plugin_textdomain( 'alt-context', false, dirname( plugin_basename( __FILE__ ) ) . '/public/languages' )` on `init` hook |
| `alt-context.php` | 8 | Update `Tested up to` header to current WP version |

## Related Files

| File | Note |
|---|---|
| `alt-context.php` | Plugin entry point; version source of truth; lifecycle hook registration |
| `src/support/class-life-cycle-manager.php` | Activation/deactivation/uninstall logic; stores `alt_context_version` and `alt_context_installed` |
| `src/api/class-abstract-recognition-proxy-controller.php` | Shared proxy base; endpoint/auth resolution lives here |
| `src/admin/class-admin.php` | Admin bootstrap; Vite asset enqueuing; tier option read |
| `public/assets/dist/` | Built Vite assets (CSS + JS) |
| `vendor/autoload.php` | Composer autoloader |
| `composer.json` | Dependency manifest; `--no-dev` controls what ships |
| `package.json` | NPM scripts; `build` produces dist assets |
| `docs/roadmaps/v0.1.0/wp-sovereign-cluster-roadmap.md` | Sovereign architecture constraints; snapshot endpoint dependency |
| `docs/agentic/contracts/clustering-api.md` | WP REST → FastAPI proxy contract |

## Risks and Mitigations

1. **Version drift** between plugin header and ZIP artifact naming.
   Mitigation: packaging script hard-fails on mismatch.
2. **Missing runtime assets** in artifact.
   Mitigation: preflight checks + staging directory assembly with required-file validation.
3. **Endpoint/auth config ambiguity** across environments.
   Mitigation: single resolution path with documented precedence + admin diagnostics.
4. **Roadmap drift** between packaging and sovereign architecture phases.
   Mitigation: keep phase-mapping table and gap register updated per milestone.
5. **Dev dependencies in ZIP** bloat artifact and expose internal tooling.
   Mitigation: `composer install --no-dev` in isolated staging directory.

## Correctness Evaluation

Findings from verifying plan claims against codebase state as of commit `5b92720`:

| Claim | Verdict | Detail |
|---|---|---|
| Plugin header is version source of truth | **Correct** | `alt-context.php` L7: `Version: 0.0.1`. `ALT_CONTEXT_VERSION` constant parsed from header at L62. |
| ZIP should include `public/assets/dist/` | **Correct** | Directory exists with Vite-built `admin-*.css` and `admin-*.js` under `.vite/` manifest. |
| ZIP should include `vendor/` | **Partially correct** | `vendor/` exists but currently includes dev packages. Must use `--no-dev`. |
| Deployment constants have highest resolution priority | **Not implemented** | `get_recognition_base_url()` only calls `get_option()`. No `defined()` check, no filter hook. The resolution precedence documented in the plan is aspirational, not actual. |
| Lifecycle hooks are wired | **Correct** | `register_activation_hook`, `register_deactivation_hook`, `register_uninstall_hook` at L142-144, delegating to `LifecycleManager`. |
| WP-Cron is available for sovereign sync | **Not implemented** | Zero cron calls in `src/`. Sovereign roadmap Phase 3 deferred — this is expected but should be explicit. |
| Snapshot endpoint exists | **Incorrect** | `GET /tenants/{tenant_id}/clusters/snapshot` is in the sovereign roadmap as a backend workstream but has no contract doc and no backend route. Plan must not gate on it; should track as an external dependency. |
| i18n packaging is handled | **Incomplete** | Text domain `alt-context` declared in header and used in `__()` calls. `load_plugin_textdomain` is never called. Domain Path `/public/languages` declared but no `.pot`/`.mo` files exist there. |
| Options use consistent prefix | **Incorrect** | Lifecycle/config options use `alt_context_*` (e.g., `alt_context_recognition_url`). Roster options use `acx_*` (e.g., `acx_roster_entries`). This is a pre-existing inconsistency outside packaging scope but worth documenting. |
| `AbstractRecognitionProxyController` reads options at constructor time | **Incorrect (non-issue)** | The P6-L2 finding was inaccurate. There is no constructor; `get_recognition_base_url()` and `get_recognition_api_key()` call `get_option()` lazily per-request. No stale-value risk exists. |

---

# Consolidated Checklist

## Phase 0: Scaffolding

- [ ] Create `scripts/release/` directory.
- [ ] Add empty `scripts/release/package-plugin.sh` with usage comment and `set -euo pipefail`.
- [ ] Add `release:package` script entry to `package.json`.
- [ ] Verify scaffold runs: `bash scripts/release/package-plugin.sh` exits cleanly with usage message.

## Phase 1: Release Artifact Definition

- [ ] Implement version extraction from `alt-context.php` plugin header in packaging script.
- [ ] Add staging directory assembly: copy `alt-context.php`, `src/`, `public/assets/dist/`.
- [ ] Add `composer install --no-dev --optimize-autoloader` step targeting staging directory.
- [ ] Add preflight validation: fail if `public/assets/dist/` is empty or `vendor/autoload.php` is missing.
- [ ] Add version consistency check: fail if extracted version is empty or mismatches artifact name.
- [ ] Add exclusion enforcement: verify `node_modules/`, `tests/`, `.env*`, dev configs are absent from staging.
- [ ] Produce `alt-context-<version>.zip` from staging directory.
- [ ] Emit `sha256` checksum alongside ZIP.

## Phase 2: Endpoint/Auth Decoupling Hardening

- [ ] Implement constant → option → filter → fallback resolution in `get_recognition_base_url()`.
- [ ] Implement same resolution pattern in `get_recognition_api_key()`.
- [ ] Add URL validation (reject non-HTTP/HTTPS values) in resolution path.
- [ ] Add admin notice when recognition URL is unconfigured or falls through to localhost fallback.
- [ ] Add unit tests for resolution precedence (constant wins over option, option wins over filter, etc.).

## Phase 3: Lifecycle + i18n Hardening

- [ ] Audit `LifecycleManager` activation for idempotence (re-activation must not overwrite existing data).
- [ ] Ensure deactivation unschedules any WP-Cron events (forward-compatible with sovereign Phase 3).
- [ ] Document uninstall data policy (which options are deleted, which are retained).
- [ ] Add `load_plugin_textdomain` call on `init` hook in `alt-context.php`.
- [ ] Update `Tested up to` header to current WordPress version.

## Phase 4: Packaging Verification

- [ ] ZIP install smoke test in non-monorepo WordPress instance.
- [ ] Endpoint reconfiguration test (change option → plugin uses new URL without code changes).
- [ ] Backend-connected recognition round trip via `/acx/v1/recognition/*`.
- [ ] Verify `composer test`, `composer cs-check`, `npm run typecheck`, `npm run lint`, `npm run arch`, `npm run test -- --run` all pass.

## Phase 5: Release Ops and Documentation

- [ ] Add rollback runbook (reinstall previous ZIP + data compatibility statement).
- [ ] Add standalone installation documentation.
- [ ] Document WP-Cron operational guidance (health checks, manual trigger, true-cron recommendation) — forward-compatible placeholder for sovereign Phase 3.
- [ ] Add multisite validation row to test matrix (network activation, per-site option scoping).

## Sovereign Dependency Tracking (Not Gated)

These items depend on work outside this packaging plan. Track but do not gate release on them:

- [ ] Backend workstream: implement `GET /tenants/{tenant_id}/clusters/snapshot` and add contract to `docs/agentic/contracts/`.
- [ ] WP-Cron registration for scheduled snapshot pull (`acx_sync_pull_snapshot`) — sovereign Phase 3 scope.
- [ ] Backend-disconnected local-read behavior test — requires local projection tables (sovereign Phase 1/2).

## Success Criteria

- [ ] `bash scripts/release/package-plugin.sh` produces `alt-context-0.0.1.zip` with correct contents and no dev dependencies.
- [ ] ZIP installs and activates in a WordPress instance outside this monorepo.
- [ ] Recognition service URL is reconfigurable via constant, option, or filter without code changes.
- [ ] Admin notice appears when endpoint is unconfigured.
- [ ] No code path in the packaged plugin references monorepo-relative backend paths.
- [ ] All six automated gates pass after changes.
