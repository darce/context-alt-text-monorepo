# ESMFIX-1. SPA `type=module` render fix (script_loader_tag)

**Status:** implemented @30c23f2f (feature/esmfix-1), pending adversarial review + merge gate.
**Type:** latent production bug fix (tech-debt). Blocks [[UXP-NET-2]] merge (blocker #71); risks `deploy-demo` CI.

## Problem

The admin SPA (and the attachment-edit entry) fail to mount on any freshly-built frontend. Console shows `Uncaught SyntaxError: Cannot use import statement outside a module`; the page is stuck at "Loading the Alt Context dashboard…". Live site only works because it currently serves a **stale single-bundle build**.

## Root cause

`src/admin/class-admin.php` marks the SPA script as a module via `wp_script_add_data( $handle, 'type', 'module' )` (lines ~213/223/245) but **nothing renders `type="module"` on the emitted `<script>` tag** — there is no `script_loader_tag` filter, and `wp_script_add_data('type','module')` alone does not affect tag output.

While the Vite build was a single self-contained bundle the entry had no top-level `import`, so it loaded fine as a classic script and masked the defect (eng [OBS-08] false-green; [RLSE-05] a masked latent failure is still a failure). **Current `main` already code-splits** — `js/admin/main.tsx` and `js/attachment-edit/main.tsx` share a `_FaceThumbnail` chunk, so the entry carries a top-level `import`. Loaded as a classic script → `SyntaxError` → SPA never mounts. Any fresh build (incl. the `deploy-demo` CI frontend build) reproduces it.

## Fix

Add a `script_loader_tag` filter (registered in `Admin::init()`) that injects `type="module"` into the opening tag for any handle registered with `'type' => 'module'` data, guarded against double-injection. Handle-based (not filename-based) so it is robust to chunk-hash churn.

- Reads the module flag via `wp_scripts()->get_data( $handle, 'type' )` — the canonical read for what `wp_script_add_data` wrote (round-trips in WP core).
- Idempotent: skips tags that already carry `type="module"` / `type='module'`.

## Slices

1. **Filter + tests** — *done @30c23f2f.* `filter_module_script_tag()` + `init()` registration; `wp_scripts()` test stub; 3 unit tests.

## Verification

- PHP lint clean; core `preg_replace` proven independently for both quote styles + skip-if-present.
- Unit tests (eng [TEST-15] each proven able to fail; discrimination guard included):
  - module handle → tag gains `type="module"`;
  - non-module handle → tag unchanged (discrimination);
  - already-module tag → not doubled.
- Full PHP suite green: **1084 tests / 4752 assertions**, 2 pre-existing `setAccessible` deprecations (not introduced here). No TS changed → tsc baseline unaffected.
- Empirical live-render on LocalWP after an opcache-flushing site restart (smoke `dashboard-loads` on a code-split build).

## Risks / constraints

- LocalWP PHP opcache pins the plugin dir; a symlink-swap cannot exercise new PHP without a site restart. **Production deploys are unaffected** (fresh dir / cold cache).
- Scope is strictly the enqueue tag; no JS/behaviour change. UX and nonce behaviour ([[UXP-NET-2]]) unchanged.

## Heuristics

eng [OBS-08] (false-green observability), [RLSE-05] (masked latent failure is a failure), [TEST-15] (prove the assertion can fail + ship a discrimination guard), [API-02]/[RES-01] (pre-existing nonce-path comments, untouched).
