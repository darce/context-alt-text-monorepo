# Alt Context Portable Packaging Runbook

For LocalWP day-to-day development, pair this document with
[localwp-development-runbook.md](./localwp-development-runbook.md). The short
rule is:

- use a stable-checkout symlink for active LocalWP iteration
- use the ZIP artifact from this runbook for gates, reproducible smoke tests,
  and release-style verification such as `E15-3a`

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

For `E15-3a`, prefer this standalone ZIP install over a symlinked LocalWP
plugin path so the run log can point to a concrete tested artifact.

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

## Sovereign Snapshot Projection Smoke (Phase 1 Foundation)

Run this in a standalone WordPress install with the plugin activated:

```bash
wp eval '
$tenant = md5(get_site_url());
$projector = new AltContext\Sovereign\Sync\SnapshotProjector(
    new AltContext\Sovereign\Repositories\ClustersRepository(),
    new AltContext\Sovereign\Repositories\IdentityMembersRepository(),
    new AltContext\Sovereign\Repositories\SyncStateRepository()
);
$projector->project($tenant, [
    "snapshot_version" => 1,
    "clusters" => [[
        "cluster_uuid" => "smoke-cluster-1",
        "label" => "Smoke User",
        "curation_state" => "uncurated",
        "is_user_confirmed" => false,
        "identity_count" => 1,
        "representative_media_id" => 101
    ]],
    "members" => [[
        "identity_uuid" => "smoke-identity-1",
        "cluster_uuid" => "smoke-cluster-1",
        "attachment_id" => 101,
        "bbox" => ["x" => 10, "y" => 20, "width" => 30, "height" => 40],
        "image_width" => 1000,
        "image_height" => 800,
        "similarity" => 0.9
    ]]
]);
echo "snapshot projected\n";
'
```

Verify rows landed:

```bash
wp db query "SELECT COUNT(*) AS clusters FROM wp_acx_clusters;"
wp db query "SELECT COUNT(*) AS members FROM wp_acx_identity_members;"
wp db query "SELECT stream_name,last_snapshot_version FROM wp_acx_sync_state;"
```

## Multisite Scope

Current plugin header is `Network: false`.

Supported mode for this release:

1. Single-site activation only.

Deferred:

1. Network activation behavior.
2. Cross-site option/schedule coordination.
