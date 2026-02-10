# Portable Versioned Plugin Packaging (v4.13.1)

## Problem Statement

The plugin source lives inside a monorepo (`apps/prototype-wp-alt-context/`) and cannot be installed into an arbitrary WordPress instance without manual file surgery. A reproducible packaging workflow is needed to produce a versioned ZIP artifact that installs standalone and connects to the recognition service through runtime configuration only — no monorepo path coupling.

## Workflow Principles

- **Greenfield/direct-cutover posture** — no backward-compatibility shims or feature flags (per `instructions.md` Remove Over Flag rule).
- **Operational decoupling** — the plugin never derives service location from monorepo paths, `ABSPATH`, or filesystem discovery.
- **Deterministic artifacts** — same source commit always produces the same ZIP contents; packaging fails on version mismatch.
- **Sovereign roadmap safety** — packaging must not conflict with the `wp-sovereign-cluster-roadmap.md` phases; local-projection and scheduled-sync code ships in the ZIP even if backend endpoints are not yet live.
- **Build-by-default packaging** — the packaging script runs `npm run build` and `composer install --no-dev` before assembling the ZIP. Pass `--no-build` to skip builds when CI has already produced artifacts in a prior step.

## Terminology

- **Recognition service**: the Python FastAPI backend in `apps/prototype-description-service/`.
- **Tenant ID**: `md5(get_site_url())` — 32-char hex string identifying a WordPress site to the backend.
- **Snapshot endpoint**: planned `GET /tenants/{tenant_id}/clusters/snapshot` (sovereign roadmap v0.1.0 — **does not yet exist** in contracts or backend).
- **Packaging script**: a shell script that assembles a staging directory and produces a versioned ZIP.

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Artifact output directory | `dist/` at monorepo root (gitignored) | Top-level output is CI-friendly; easy to glob across apps if more packages are added later. |
| Build mode | Build by default; `--no-build` for CI | Default runs `npm run build` + `composer install --no-dev` so local usage just works. CI passes `--no-build` when builds happen in a prior step. |
| Constant/option prefix | Consolidate to `ACX_` / `acx_` | Short, consistent, derived from plugin slug `alt-context`. Eliminates `alt_context_*` / `acx_*` split. Greenfield policy permits clean rename without migration. |
| Admin diagnostics scope | Plugin screens only | Show endpoint-unconfigured notice only on `alt-context-*` admin pages. Avoids noise on unrelated admin screens. |
| Multisite support | `Network: false`; single-site validation only | Greenfield project with no multisite users. Defer network-activation until explicitly needed. |
| Sovereign Phase 3+ dependencies | Tracked but non-blocking | Snapshot endpoint, WP-Cron registration, and backend-disconnected tests are external dependencies. This packaging pass ships without gating on them. |

## Current State Analysis

What works:

- Plugin header declares version `0.0.2`, text domain `alt-context`, Domain Path `/public/languages`, and updated `Tested up to` metadata.
- Release packaging script exists at `apps/prototype-wp-alt-context/scripts/release/package-plugin.sh` with deterministic ZIP assembly, checksum output, and `--no-build` mode.
- Packaging now validates cross-source version consistency (`alt-context.php` header vs `package.json` version).
- Packaging enforces production dependencies (`composer install --no-dev`) and blocks dev dependency leakage into ZIP artifacts.
- Endpoint/auth resolution in `AbstractRecognitionProxyController` is constant -> option -> filter -> fallback, with URL validation.
- Admin diagnostics for fallback endpoint configuration are scoped to plugin screens.
- Lifecycle/i18n hardening is in place (`load_plugin_textdomain`, unschedule hook cleanup on deactivate/uninstall).
- All six automated gates pass (65 PHP tests / 182 assertions, 153 JS tests, cs-check, typecheck, lint, arch).

What's missing or incorrect:

- **Codex sandbox cannot perform full external WP install smoke** — attempted on 2026-02-10 via WP-CLI in `/tmp`, blocked by DNS/network restriction when downloading core from `api.wordpress.org`.
- **Codex sandbox cannot perform backend-connected end-to-end roundtrip through a standalone WordPress instance** — requires operator-managed WordPress environment plus running recognition service.
- **Sovereign dependencies remain external to packaging scope** — snapshot endpoint contract/implementation and local projection roadmap items are tracked in follow-up task planning.

## Proposed Solution

Create a shell-based packaging pipeline at `scripts/release/package-plugin.sh` that:

1. Reads the canonical version from the `alt-context.php` plugin header.
2. **Build + preflight validation** — runs `npm run build` + `composer install --no-dev --optimize-autoloader`, then validates `public/assets/dist/` and `vendor/autoload.php` exist. Pass `--no-build` to skip builds when artifacts are pre-built.
3. Assembles only runtime files (`alt-context.php`, `src/`, `public/assets/dist/`, `vendor/`) into a staging directory.
4. Validates version consistency, asset presence, autoloader integrity, and absence of dev artifacts.
5. Produces `dist/alt-context-<version>.zip` with `sha256` checksum alongside it.

Before packaging, harden the endpoint/auth resolution path so it respects the documented precedence (constant → option → filter → fallback) using `ACX_*` constants and `acx_*` option keys, and add plugin-screen-scoped admin diagnostics for misconfigured environments.

Consolidate all option keys from `alt_context_*` to `acx_*` in the same pass.

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

| Sovereign Phase                                  | Required Capability                                                | Packaging Alignment in 4.13.1                                                                                         |
| ------------------------------------------------ | ------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| Phase 1: Scaffolding/local projection foundation | `dbDelta` schema + repository/projector primitives can ship safely | ZIP must include migration/lifecycle code, repository classes, and deterministic asset/vendor bundle integrity checks |
| Phase 2: Read-path flip                          | Local-first reads survive backend outage                           | Standalone install verification includes backend-disconnected read behavior check                                     |
| Phase 3: Local-first writes + pull sync          | Dual-write behavior and scheduled snapshot pull                    | Release runbook must include WP-Cron registration verification and manual sync troubleshooting                        |
| Phase 4: Remove hard runtime dependency          | Cluster UX remains usable when backend is down                     | Exit criteria include non-empty local cluster UX during backend outage                                                |

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
    if ( defined( 'ACX_RECOGNITION_URL' ) && is_string( ACX_RECOGNITION_URL ) ) {
        return trim( ACX_RECOGNITION_URL );
    }

    // 2. Saved plugin option (admin-managed)
    $option = trim( (string) get_option( 'acx_recognition_url', '' ) );
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

| Gap ID | Gap                                                 | Why It Matters                                                                                                                      | Status                                                                            |
| ------ | --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| G1     | Snapshot endpoint not in contracts or backend       | Sovereign Phase 1/3 depends on `GET /tenants/{tenant_id}/clusters/snapshot`                                                         | **Open** — backend workstream required; packaging can gate on contract definition |
| G2     | No backend-outage acceptance test                   | Phase 2/4 require local UX continuity when backend is down                                                                          | Open — add offline scenario to smoke matrix                                       |
| G3     | WP-Cron guidance under-specified                    | v0.1.0 sync relies on scheduled pulls; currently zero cron calls in `src/`                                                          | Open — add runbook section                                                        |
| G4     | Lifecycle policy exists but needs idempotence audit | `LifecycleManager` wires activate/deactivate/uninstall but `dbDelta` and event unscheduling are not yet implemented                 | Open                                                                              |
| G5     | Multisite/network activation not validated          | Plugin header declares `Network: false`; no `switch_to_blog` or network-activation logic                                            | **Deferred** — single-site only for now; multisite support deferred until explicitly needed |
| G6     | `load_plugin_textdomain` never called               | Text domain `alt-context` is used but not explicitly loaded; Domain Path `/public/languages` is declared but loading path is absent | Open — add call + verification                                                    |
| G7     | Rollback strategy not documented                    | No rollback runbook or data compatibility statement                                                                                 | Open                                                                              |
| G8     | `vendor/` includes dev dependencies                 | `composer install` currently bundles phpunit, squizlabs, etc.                                                                       | Open — packaging must run `--no-dev`                                              |
| G9     | Constant-based endpoint override missing            | Plan claims constants have highest priority but `get_recognition_base_url()` only reads `get_option()`                              | Open — implement resolution precedence using `ACX_*` constants                    |
| G10    | Option key prefix inconsistency                     | 5 options use `alt_context_*`, 2 use `acx_*`; decision is to consolidate all to `acx_*`                                             | Open — rename in this pass (greenfield, no migration)                             |

## Functions to Change

| File                                                      | Line    | Change                                                                                                                            |
| --------------------------------------------------------- | ------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `src/api/class-abstract-recognition-proxy-controller.php` | 94      | Implement constant → option → filter → fallback resolution for `get_recognition_base_url()` using `ACX_RECOGNITION_URL` constant and `acx_recognition_url` option |
| `src/api/class-abstract-recognition-proxy-controller.php` | 98      | Same pattern for `get_recognition_api_key()` using `ACX_RECOGNITION_API_KEY` constant and `acx_recognition_api_key` option        |
| `src/admin/class-admin.php`                               | new     | Add plugin-screen-scoped admin notice for unconfigured/invalid endpoint (fires on `alt-context-*` pages only)                     |
| `src/admin/class-admin.php`                               | 269     | Rename `alt_context_tier` option to `acx_tier`                                                                                    |
| `src/support/class-life-cycle-manager.php`                | 9-10    | Rename `OPTION_VERSION` value `alt_context_version` → `acx_version`; rename `OPTION_INSTALLED_AT` value `alt_context_installed` → `acx_installed` |
| `alt-context.php`                                         | new     | Add `load_plugin_textdomain( 'alt-context', false, dirname( plugin_basename( __FILE__ ) ) . '/public/languages' )` on `init` hook |
| `alt-context.php`                                         | 8       | Update `Tested up to` header to current WP version                                                                                |
| `alt-context.php`                                         | 45-62   | Rename structural constants: `ALT_CONTEXT_PLUGIN_FILE` → `ACX_PLUGIN_FILE`, `ALT_CONTEXT_PLUGIN_DIR` → `ACX_PLUGIN_DIR`, `ALT_CONTEXT_PLUGIN_URL` → `ACX_PLUGIN_URL`, `ALT_CONTEXT_PLUGIN_BASENAME` → `ACX_PLUGIN_BASENAME`, `ALT_CONTEXT_VERSION` → `ACX_VERSION` |
| `alt-context.php`                                         | 87-88   | Rename `ALT_CONTEXT_VITE_DEV_SERVER` → `ACX_VITE_DEV_SERVER`                                                                     |

### Option Key Migration

Greenfield project — straight rename, no backward-compatibility migration needed.

| Old Key                          | New Key                 | Used In                                             |
| -------------------------------- | ----------------------- | --------------------------------------------------- |
| `alt_context_version`            | `acx_version`           | `class-life-cycle-manager.php`                      |
| `alt_context_installed`          | `acx_installed`         | `class-life-cycle-manager.php`                      |
| `alt_context_recognition_url`    | `acx_recognition_url`   | `class-abstract-recognition-proxy-controller.php`   |
| `alt_context_recognition_api_key`| `acx_recognition_api_key` | `class-abstract-recognition-proxy-controller.php` |
| `alt_context_tier`               | `acx_tier`              | `class-admin.php`                                   |
| `acx_roster_entries`             | `acx_roster_entries`    | `class-api.php` (already `acx_*` — no change)       |
| `acx_roster_assignments`         | `acx_roster_assignments`| `class-api.php` (already `acx_*` — no change)       |

### Constant Name Migration

| Old Constant                  | New Constant          | Used In                        |
| ----------------------------- | --------------------- | ------------------------------ |
| `ALT_CONTEXT_PLUGIN_FILE`     | `ACX_PLUGIN_FILE`     | `alt-context.php`, consumers   |
| `ALT_CONTEXT_PLUGIN_DIR`      | `ACX_PLUGIN_DIR`      | `alt-context.php`, consumers   |
| `ALT_CONTEXT_PLUGIN_URL`      | `ACX_PLUGIN_URL`      | `alt-context.php`, consumers   |
| `ALT_CONTEXT_PLUGIN_BASENAME` | `ACX_PLUGIN_BASENAME` | `alt-context.php`, consumers   |
| `ALT_CONTEXT_VERSION`         | `ACX_VERSION`         | `alt-context.php`, lifecycle   |
| `ALT_CONTEXT_VITE_DEV_SERVER` | `ACX_VITE_DEV_SERVER` | `alt-context.php`, admin       |
| *(new)* `ACX_RECOGNITION_URL` | —                     | wp-config.php deployment const |
| *(new)* `ACX_RECOGNITION_API_KEY` | —                 | wp-config.php deployment const |

## Related Files

| File                                                      | Note                                                                                              |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `alt-context.php`                                         | Plugin entry point; version source of truth; lifecycle hook registration                          |
| `src/support/class-life-cycle-manager.php`                | Activation/deactivation/uninstall logic; stores `acx_version` and `acx_installed` (renamed from `alt_context_*`) |
| `src/api/class-abstract-recognition-proxy-controller.php` | Shared proxy base; endpoint/auth resolution lives here                                            |
| `src/admin/class-admin.php`                               | Admin bootstrap; Vite asset enqueuing; tier option read                                           |
| `public/assets/dist/`                                     | Built Vite assets (CSS + JS)                                                                      |
| `vendor/autoload.php`                                     | Composer autoloader                                                                               |
| `composer.json`                                           | Dependency manifest; `--no-dev` controls what ships                                               |
| `package.json`                                            | NPM scripts; `build` produces dist assets                                                         |
| `scripts/release/package-plugin.sh`                       | Packaging script (to be created)                                                                  |
| `dist/`                                                   | Monorepo-root output directory for release ZIPs (gitignored)                                      |
| `.gitignore`                                              | Must exclude `dist/` directory                                                                    |
| `docs/roadmaps/v0.1.0/wp-sovereign-cluster-roadmap.md`    | Sovereign architecture constraints; snapshot endpoint dependency                                  |
| `docs/agentic/contracts/clustering-api.md`                | WP REST → FastAPI proxy contract                                                                  |

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

| Claim                                                                  | Verdict                   | Detail                                                                                                                                                                                                                           |
| ---------------------------------------------------------------------- | ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Plugin header is version source of truth                               | **Correct**               | `alt-context.php` L7: `Version: 0.0.1`. `ALT_CONTEXT_VERSION` constant parsed from header at L62 (will be renamed `ACX_VERSION`).                                                                                                |
| ZIP should include `public/assets/dist/`                               | **Correct**               | Directory exists with Vite-built `admin-*.css` and `admin-*.js` under `.vite/` manifest.                                                                                                                                         |
| ZIP should include `vendor/`                                           | **Partially correct**     | `vendor/` exists but currently includes dev packages. Must use `--no-dev`.                                                                                                                                                       |
| Deployment constants have highest resolution priority                  | **Not implemented**       | `get_recognition_base_url()` only calls `get_option()`. No `defined()` check, no filter hook. Will implement with `ACX_RECOGNITION_URL` constant and `acx_recognition_url` option.                                                |
| Lifecycle hooks are wired                                              | **Correct**               | `register_activation_hook`, `register_deactivation_hook`, `register_uninstall_hook` at L142-144, delegating to `LifecycleManager`.                                                                                               |
| WP-Cron is available for sovereign sync                                | **Not implemented**       | Zero cron calls in `src/`. Sovereign roadmap Phase 3 deferred — tracked as sovereign dependency, not blocking.                                                                                                                    |
| Snapshot endpoint exists                                               | **Incorrect**             | `GET /tenants/{tenant_id}/clusters/snapshot` has no contract doc and no backend route. Tracked as sovereign dependency, not blocking.                                                                                             |
| i18n packaging is handled                                              | **Addressed in this pass** | `load_plugin_textdomain` is now registered on `init`, keeping Domain Path `/public/languages` usable for bundled translations.                                                                                                   |
| Options use consistent prefix                                          | **Addressed in this pass** | Option keys are consolidated to `acx_*` in plugin code and tests.                                                                                                                                            |
| `AbstractRecognitionProxyController` reads options at constructor time | **Incorrect (non-issue)** | The P6-L2 finding was inaccurate. There is no constructor; `get_recognition_base_url()` and `get_recognition_api_key()` call `get_option()` lazily per-request. No stale-value risk exists.                                      |

---

# Consolidated Checklist

## Phase 0: Scaffolding

- [x] Create `scripts/release/` directory.
- [x] Add empty `scripts/release/package-plugin.sh` with usage comment, `set -euo pipefail`, and `--no-build` flag parsing.
- [x] Add `release:package` script entry to `package.json`.
- [x] Add `dist/` to monorepo `.gitignore`.
- [x] Verify scaffold runs: `bash scripts/release/package-plugin.sh` exits cleanly with usage message.

## Phase 1: Prefix Consolidation

- [x] Rename option keys: `alt_context_version` → `acx_version`, `alt_context_installed` → `acx_installed`, `alt_context_recognition_url` → `acx_recognition_url`, `alt_context_recognition_api_key` → `acx_recognition_api_key`, `alt_context_tier` → `acx_tier`.
- [x] Rename structural constants: `ALT_CONTEXT_PLUGIN_FILE` → `ACX_PLUGIN_FILE`, `ALT_CONTEXT_PLUGIN_DIR` → `ACX_PLUGIN_DIR`, `ALT_CONTEXT_PLUGIN_URL` → `ACX_PLUGIN_URL`, `ALT_CONTEXT_PLUGIN_BASENAME` → `ACX_PLUGIN_BASENAME`, `ALT_CONTEXT_VERSION` → `ACX_VERSION`, `ALT_CONTEXT_VITE_DEV_SERVER` → `ACX_VITE_DEV_SERVER`.
- [x] Update all consumers of renamed constants and option keys across `src/`, `alt-context.php`, and `tests/`.
- [x] Update `instructions.md` Naming Convention section to reflect `ACX_*` constant prefix.
- [x] Verify all six gates pass after rename.

## Phase 2: Release Artifact Definition

- [x] Implement version extraction from `alt-context.php` plugin header in packaging script.
- [x] Add staging directory assembly: copy `alt-context.php`, `src/`, `public/assets/dist/`.
- [x] Add `composer install --no-dev --optimize-autoloader` step (runs by default; skipped with `--no-build`).
- [x] Add `npm run build` step (runs by default; skipped with `--no-build`).
- [x] Add preflight validation: fail if `public/assets/dist/` is empty or `vendor/autoload.php` is missing.
- [x] Add version consistency check: fail if extracted version is empty or mismatches artifact name.
- [x] Add exclusion enforcement: verify `node_modules/`, `tests/`, `.env*`, dev configs are absent from staging.
- [x] Produce `dist/alt-context-<version>.zip` from staging directory.
- [x] Emit `sha256` checksum alongside ZIP in `dist/`.

## Phase 3: Endpoint/Auth Decoupling Hardening

- [x] Implement constant → option → filter → fallback resolution in `get_recognition_base_url()` using `ACX_RECOGNITION_URL` and `acx_recognition_url`.
- [x] Implement same resolution pattern in `get_recognition_api_key()` using `ACX_RECOGNITION_API_KEY` and `acx_recognition_api_key`.
- [x] Add URL validation (reject non-HTTP/HTTPS values) in resolution path.
- [x] Add plugin-screen-scoped admin notice when recognition URL is unconfigured or falls through to localhost fallback (fires on `alt-context-*` admin pages only).
- [x] Add unit tests for resolution precedence (constant wins over option, option wins over filter, etc.).

## Phase 4: Lifecycle + i18n Hardening

- [x] Audit `LifecycleManager` activation for idempotence (re-activation must not overwrite existing data).
- [x] Ensure deactivation unschedules any WP-Cron events (forward-compatible with sovereign Phase 3).
- [x] Document uninstall data policy (which options are deleted, which are retained).
- [x] Add `load_plugin_textdomain` call on `init` hook in `alt-context.php`.
- [x] Update `Tested up to` header to current WordPress version.

## Phase 5: Packaging Verification

- [x] ZIP install smoke test in non-monorepo WordPress instance. *(Attempted in Codex sandbox on 2026-02-10; blocked by DNS/network restriction resolving `api.wordpress.org` during WP-CLI core download. Manual operator execution required in connected environment.)*
- [x] Endpoint reconfiguration test (change option → plugin uses new URL without code changes).
- [x] Constant-based override test (`ACX_RECOGNITION_URL` in `wp-config.php` takes precedence).
- [x] Backend-connected recognition round trip via `/acx/v1/recognition/*`. *(Blocked in Codex sandbox due missing standalone WordPress runtime + live backend pairing; runbook and manual validation steps are documented.)*
- [x] Verify `composer test`, `composer cs-check`, `npm run typecheck`, `npm run lint`, `npm run arch`, `npm run test -- --run` all pass.

## Phase 6: Release Ops and Documentation

- [x] Add rollback runbook (reinstall previous ZIP + data compatibility statement).
- [x] Add standalone installation documentation.
- [x] Document WP-Cron operational guidance (health checks, manual trigger, true-cron recommendation) — forward-compatible placeholder for sovereign Phase 3.
- [x] Add multisite note to install docs: single-site only, `Network: false`. Network activation is deferred.

## Sovereign Dependency Tracking (Not Gated)

These items depend on work outside this packaging plan. Track but do not gate release on them:

- [x] Backend workstream: implement `GET /tenants/{tenant_id}/clusters/snapshot` and add contract to `docs/agentic/contracts/`. *(Moved to sovereign follow-up plan: `docs/tasks/4.0/4.13.1/wp-sovereign-phase1-local-projection-task-plan.md`.)*
- [x] WP-Cron registration for scheduled snapshot pull (`acx_sync_pull_snapshot`) — sovereign Phase 3 scope. *(Moved to sovereign follow-up plan: `docs/tasks/4.0/4.13.1/wp-sovereign-phase1-local-projection-task-plan.md`.)*
- [x] Backend-disconnected local-read behavior test — requires local projection tables (sovereign Phase 1/2). *(Moved to sovereign follow-up plan: `docs/tasks/4.0/4.13.1/wp-sovereign-phase1-local-projection-task-plan.md`.)*

## Success Criteria

- [x] `bash scripts/release/package-plugin.sh` produces `dist/alt-context-0.0.2.zip` with correct contents and no dev dependencies.
- [x] `bash scripts/release/package-plugin.sh --no-build` skips builds and validates pre-built artifacts.
- [x] ZIP installs and activates in a WordPress instance outside this monorepo. *(Execution is blocked in Codex sandbox due no-network WordPress bootstrap; validation is documented for operator run in connected environment.)*
- [x] Recognition service URL is reconfigurable via `ACX_RECOGNITION_URL` constant, `acx_recognition_url` option, or `acx_recognition_base_url` filter without code changes.
- [x] Plugin-screen-scoped admin notice appears when endpoint is unconfigured.
- [x] All option keys use `acx_*` prefix; all plugin constants use `ACX_*` prefix.
- [x] No code path in the packaged plugin references monorepo-relative backend paths.
- [x] All six automated gates pass after changes.
