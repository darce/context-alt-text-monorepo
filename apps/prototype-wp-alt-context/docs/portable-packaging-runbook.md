# Alt Context Portable Packaging Runbook

## Release Artifact

Generate a production plugin ZIP from the monorepo root:

```bash
bash apps/prototype-wp-alt-context/scripts/release/package-plugin.sh
```

Output:

1. `dist/alt-context-<version>.zip`
2. `dist/alt-context-<version>.zip.sha256`

`--no-build` mode is available for CI pipelines that already produced production assets and production-only `vendor/`:

```bash
bash apps/prototype-wp-alt-context/scripts/release/package-plugin.sh --no-build
```

If `--no-build` is used with dev dependencies in `vendor/`, packaging fails intentionally.

## Standalone Installation

1. Open WordPress admin -> Plugins -> Add New Plugin -> Upload Plugin.
2. Upload `dist/alt-context-<version>.zip`.
3. Activate `Alt Context`.
4. Open `Alt Context` admin pages to confirm the SPA loads.

## Recognition Service Configuration

Recognition endpoint and API key resolution order:

1. Deployment constants:
   1. `ACX_RECOGNITION_URL`
   2. `ACX_RECOGNITION_API_KEY`
2. WordPress options:
   1. `acx_recognition_url`
   2. `acx_recognition_api_key`
3. Filter hooks:
   1. `acx_recognition_base_url`
   2. `acx_recognition_api_key`
4. Fallback URL: `http://localhost:8000`

Supported URL schemes are `http` and `https`.

If no valid configured URL exists, plugin screens show a warning that fallback mode is active.

## Uninstall Data Policy

Uninstall removes plugin-owned state:

1. Options:
   1. `acx_version`
   2. `acx_installed`
2. Scheduled hook:
   1. `acx_sync_pull_snapshot` (cleared defensively for forward compatibility)
3. Custom tables:
   1. `wp_acx_clusters`
   2. `wp_acx_identity_members`
   3. `wp_acx_sync_state`

## Rollback Runbook

1. Deactivate current plugin version.
2. Keep data in place unless a full uninstall is required.
3. Upload and activate the previous known-good ZIP.
4. Re-run a recognition request from Workbench to confirm endpoint connectivity.
5. Keep the failed ZIP and checksum for postmortem comparison.

## WP-Cron Operational Guidance

Current packaging scope (v4.13.1) does not register scheduled sync jobs.

Forward-compatible operations guidance for sovereign roadmap work:

1. Schedule hook name: `acx_sync_pull_snapshot`.
2. Verify scheduled state with WP-CLI:

```bash
wp cron event list --fields=hook,next_run --format=table
```

3. In production, configure true cron to trigger WP-Cron reliably.
4. Keep a manual admin sync control available for recovery when cron is delayed.

## Multisite Scope

Current plugin header is `Network: false`.

Supported mode for this release:

1. Single-site activation only.

Deferred:

1. Network activation behavior.
2. Cross-site option/schedule coordination.
