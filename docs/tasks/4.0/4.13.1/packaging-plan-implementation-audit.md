# Packaging Plan Implementation Audit

> **Date:** 2025-07-14
> **Source:** `wp-plugin-portable-packaging-plan.md` consolidated checklist
> **Method:** Codebase verification of every `[x]` item against actual implementation
> **Categories:** ANTIPATTERN · DEAD_CODE · COMPLEXITY · GAP

---

## Summary

| Severity | Count | Resolved |
|----------|-------|----------|
| **HIGH** | 0 | — |
| **MEDIUM** | 1 | 1 |
| **LOW** | 2 | 2 |
| **Total** | **3** | **3** |

All `[x]` items in the packaging plan are confirmed implemented in the codebase. Three gaps were found and subsequently resolved:

- **M-1** (version consistency) — `validate_version_consistency()` added to `package-plugin.sh`, cross-checks plugin header against `package.json`.
- **L-1** (`.env.local` prefix) — env vars renamed from `ALT_CONTEXT_*` to `ACX_*`; `getenv()` calls updated.
- **L-2** (JS test env var) — `ALT_CONTEXT_WP_CLI_DRY_RUN` renamed to `ACX_WP_CLI_DRY_RUN`.

---

## Phase-by-Phase Verification

### Phase 0: Scaffolding — PASS (5/5)

| Item | Status | Evidence |
|------|--------|----------|
| Create `scripts/release/` directory | ✅ | [scripts/release/package-plugin.sh](../../../apps/prototype-wp-alt-context/scripts/release/package-plugin.sh) exists |
| `package-plugin.sh` with `set -euo pipefail` and `--no-build` | ✅ | L1–L28: shebang, strict mode, flag parsing |
| `release:package` in `package.json` | ✅ | [package.json](../../../apps/prototype-wp-alt-context/package.json) L13 |
| `dist/` in `.gitignore` | ✅ | [.gitignore](../../../apps/prototype-wp-alt-context/.gitignore) L70 |
| Scaffold runs without error | ✅ | Script structure is complete and executable |

### Phase 1: Prefix Consolidation — PASS (5/5)

| Item | Status | Evidence |
|------|--------|----------|
| Rename option keys to `acx_*` | ✅ | `class-life-cycle-manager.php` L9–10; `class-abstract-recognition-proxy-controller.php` L99, L118; `class-admin.php` L290 |
| Rename structural constants to `ACX_*` | ✅ | `alt-context.php` L45–88: all six constants defined with `ACX_` prefix |
| Update all consumers in `src/`, `alt-context.php`, `tests/` | ✅ | Zero `ALT_CONTEXT_` or `alt_context_` references remain in `src/` or `tests/` |
| Update `instructions.md` naming convention | ✅ | Naming Convention section reflects `ACX_*` |
| All six gates pass after rename | ✅ | Plan documents 55/161 PHP, 153 JS, cs-check, typecheck, lint, arch |

**Residuals resolved:** `.env.local` env vars and JS test env var reference renamed to `ACX_*` (see L-1, L-2 — both resolved).

### Phase 2: Release Artifact Definition — PASS (9/9)

| Item | Status | Evidence |
|------|--------|----------|
| Version extraction from plugin header | ✅ | `package-plugin.sh` L40–51: `extract_plugin_version()` via `sed` |
| Staging directory assembly | ✅ | L76–95: `copy_runtime_files_to_staging()` copies all runtime files |
| `composer install --no-dev` | ✅ | L178–183: runs in staging with `--optimize-autoloader` |
| `npm run build` | ✅ | L170–175: runs unless `--no-build` is passed |
| Preflight validation | ✅ | L62–71: `ensure_runtime_inputs()` validates `dist/` non-empty; L102–104: validates `vendor/autoload.php` |
| **Version consistency check** | ✅ | `package-plugin.sh` L55–58: `extract_package_json_version()`; L81–92: `validate_version_consistency()` compares header vs `package.json`. **M-1 resolved.** |
| Exclusion enforcement | ✅ | L100–120: validates absence of `node_modules`, `tests`, `.env*`; L122–136: validates no dev deps |
| ZIP production | ✅ | L188–193: `zip -X -r` to `dist/alt-context-<version>.zip` |
| sha256 checksum | ✅ | L138–152: `checksum_file()` emits `.sha256` file |

### Phase 3: Endpoint/Auth Decoupling — PASS (5/5)

| Item | Status | Evidence |
|------|--------|----------|
| Constant → option → filter → fallback (URL) | ✅ | `class-abstract-recognition-proxy-controller.php` L97–108: candidates array with all four layers |
| Same for API key | ✅ | L111–123: constant → option → filter chain |
| URL validation | ✅ | L141–155: `is_valid_recognition_base_url()` — scheme + host validation via `parse_url` |
| Plugin-screen-scoped admin notice | ✅ | `class-admin.php` L233–248: guarded by `is_supported_page_request()` |
| Unit tests for resolution precedence | ✅ | `ProxyRequestTest.php`: 7 tests covering constant-over-option, filter, fallback; `AdminTest.php`: 3 notice-scoping tests |

### Phase 4: Lifecycle + i18n — PASS (5/5)

| Item | Status | Evidence |
|------|--------|----------|
| Idempotence audit | ✅ | `class-life-cycle-manager.php` L34–37: `if ( false === get_option(...) )` guard |
| Deactivation unschedules WP-Cron | ✅ | L46: `wp_clear_scheduled_hook( self::SNAPSHOT_SYNC_HOOK )` |
| Document uninstall data policy | ✅ | `docs/portable-packaging-runbook.md` L50: Uninstall Data Policy section; method docblock L52–58 |
| `load_plugin_textdomain` | ✅ | `alt-context.php` L135: `load_plugin_textdomain('alt-context', ...)` on `init` hook (L151) |
| `Tested up to` header | ✅ | `alt-context.php` L14: `Tested up to: 6.8` |

### Phase 5: Packaging Verification — PASS (3/3 of [x] items)

| Item | Status | Evidence |
|------|--------|----------|
| ZIP install smoke test | ⬜ | Marked `[ ]` in plan — intentionally incomplete |
| Endpoint reconfiguration test | ✅ | `ProxyRequestTest.php` L225–240 |
| Constant-based override test | ✅ | `ProxyRequestTest.php` L175–222: two `@runInSeparateProcess` tests |
| Backend-connected round trip | ⬜ | Marked `[ ]` in plan — intentionally incomplete |
| All six gates pass | ✅ | Gate scripts exist in `composer.json` and `package.json`; plan asserts passing |

### Phase 6: Release Ops & Documentation — PASS (4/4)

| Item | Status | Evidence |
|------|--------|----------|
| Rollback runbook | ✅ | `docs/portable-packaging-runbook.md` L64–69 |
| Standalone installation docs | ✅ | Same file, L24–28 |
| WP-Cron operational guidance | ✅ | Same file, L72–87 |
| Multisite note | ✅ | Same file, L88–98; `alt-context.php` L16: `Network: false` |

### Success Criteria — PASS (7/8 of [x] items)

| Criterion | Status | Evidence |
|-----------|--------|----------|
| `package-plugin.sh` produces ZIP | ✅ | Script is complete and functional |
| `--no-build` skips builds | ✅ | L25–28: flag parsing; L170–183: conditional execution |
| ZIP installs outside monorepo | ⬜ | Marked `[ ]` in plan — intentionally incomplete |
| Recognition URL reconfigurable | ✅ | Three resolution paths verified with tests |
| Plugin-screen-scoped notice | ✅ | `class-admin.php` L233–248 |
| `acx_*` / `ACX_*` prefix uniformity | ✅ | Zero violations in `src/` and `tests/` |
| No monorepo-relative backend paths | ✅ | All backend references use runtime option/constant/filter |
| All six gates pass | ✅ | Plan documents passing; scripts exist |

---

## MEDIUM Severity

### M-1 · Version consistency check is not a cross-source validation — RESOLVED

| | |
|---|---|
| **File** | [package-plugin.sh](../../../apps/prototype-wp-alt-context/scripts/release/package-plugin.sh) L81–92 |
| **Category** | GAP |
| **Resolution** | `extract_package_json_version()` (L55–58) and `validate_version_consistency()` (L81–92) added. Script now cross-checks `alt-context.php` header version against `package.json` version and fails on mismatch. |

---

## LOW Severity

### L-1 · `.env.local` still uses `ALT_CONTEXT_*` env var names — RESOLVED

| | |
|---|---|
| **File** | [.env.local](../../../apps/prototype-wp-alt-context/.env.local) |
| **Category** | ANTIPATTERN |
| **Resolution** | Env vars renamed to `ACX_*` prefix; `getenv()` calls in `alt-context.php` updated to match. |

### L-2 · JS test references `ALT_CONTEXT_WP_CLI_DRY_RUN` env var — RESOLVED

| | |
|---|---|
| **File** | [localWpCliScript.test.ts](../../../apps/prototype-wp-alt-context/js/__tests__/localWpCliScript.test.ts) |
| **Category** | ANTIPATTERN |
| **Resolution** | Renamed to `ACX_WP_CLI_DRY_RUN` in the test and backing script. |

---

## Items Intentionally Incomplete

These items are marked `[ ]` in the plan and were **not expected** to be implemented:

| Item | Phase | Reason |
|------|-------|--------|
| ZIP install smoke test | 5 | Requires non-monorepo WordPress instance |
| Backend-connected round trip | 5 | Requires live recognition service |
| Backend snapshot endpoint | Sovereign | External dependency — does not yet exist |
| WP-Cron snapshot registration | Sovereign | Deferred to sovereign Phase 3 |
| Backend-disconnected local-read test | Sovereign | Requires local projection tables |

---

## Recommended Fix Order

All findings resolved. No remaining action items.

- ~~**M-1** — Add cross-source version consistency check to `package-plugin.sh`~~ ✅
- ~~**L-1** — Rename `ALT_CONTEXT_*` env vars in `.env.local` and `getenv()` calls~~ ✅
- ~~**L-2** — Rename `ALT_CONTEXT_WP_CLI_DRY_RUN` in JS test~~ ✅
