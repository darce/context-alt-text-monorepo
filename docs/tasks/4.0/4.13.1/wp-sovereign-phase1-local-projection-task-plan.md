# WordPress Sovereign Phase 1: Local Projection Task Plan (v4.13.1 Follow-up)

## Problem Statement

The plugin is now packageable and portable, but cluster UX is still proxy-first and depends on live backend availability. The roadmap requires a sovereign local projection so previously computed clusters remain available and curation can move toward local durability. This task defines the next actionable slice for the current branch: local projection foundations and snapshot ingestion scaffolding.

## Workflow Principles

- Build sovereign behavior as direct-cutover code, not behind long-lived feature flags.
- Keep runtime endpoint resolution configurable (constant -> option -> filter), with no monorepo path assumptions.
- Ship plugin-side storage and projection primitives before read-path flip and dual-write orchestration.
- Treat backend snapshot endpoint delivery as a parallel dependency, not a blocker for local schema/repository work.

## Terminology

- **Local projection**: plugin-owned WordPress tables (`wp_acx_clusters`, `wp_acx_identity_members`, `wp_acx_sync_state`) used as the local read model.
- **Snapshot projector**: plugin service that applies a full tenant snapshot payload into local tables idempotently.
- **Snapshot version**: monotonic backend-provided value persisted in `wp_acx_sync_state` and cluster rows.
- **Curation-first fields**: local fields that preserve user-authoritative state (`curation_state`, `is_user_confirmed`) during projection updates.

## Current State Analysis

What already works in this branch:

- Packaging and endpoint decoupling workstream is in place (`apps/prototype-wp-alt-context/scripts/release/package-plugin.sh`, ACX endpoint resolution, standalone install docs).
- `LifecycleManager` already declares owned sovereign table suffixes and uninstalls them cleanly.
- `LifecycleManager` already clears the planned sync hook (`acx_sync_pull_snapshot`) on deactivate/uninstall.

What is still missing for sovereign Phase 1:

- No table creation path (`dbDelta`) for `wp_acx_clusters`, `wp_acx_identity_members`, `wp_acx_sync_state`.
- No plugin repository layer for clusters, members, and sync state.
- No snapshot projector service to ingest payloads into local tables.
- No plugin contract artifact for snapshot payload shape and projection semantics.
- No backend snapshot contract/route (`GET /tenants/{tenant_id}/clusters/snapshot`) to feed projection from live service.

Roadmap scope boundary to make explicit:

- This plan intentionally delivers storage/projection foundations only.
- Roadmap v0.1.0 Phase 1 exit criterion says cluster list/detail UI must render from local store.
- That UI read-path flip is covered by the next task slice (Phase 2 read-path work), not by this document alone.

## Proposed Solution

Create a focused Phase 1 foundation slice that delivers local schema, repository, and projector primitives without coupling completion to the full read-path flip. Implementation should include fixture-driven projector tests so plugin-side behavior can be validated immediately even before the backend snapshot route is live.

Design guardrails for this slice:

1. Schema fidelity must match roadmap data model exactly for all three tables.
2. Projector writes must be transaction-safe and curation-safe (no destructive replace of user-confirmed rows).
3. Timestamp fields are managed explicitly by repositories (WordPress does not provide automatic row timestamps).
4. Backend snapshot endpoint delivery remains a linked parallel workstream and is tracked as an external dependency, not a plugin-slice completion gate.

## Patterns to Follow

### Pattern A: Lifecycle `dbDelta` Ownership (All Three Tables, Roadmap-Accurate)

```php
<?php
declare(strict_types=1);

private function maybe_create_projection_tables(): void {
	global $wpdb;

	if ( ! isset( $wpdb ) || ! is_object( $wpdb ) ) {
		return;
	}

	require_once ABSPATH . 'wp-admin/includes/upgrade.php';
	$charset_collate = $wpdb->get_charset_collate();

	$clusters_table = $wpdb->prefix . 'acx_clusters';
	$members_table  = $wpdb->prefix . 'acx_identity_members';
	$sync_table     = $wpdb->prefix . 'acx_sync_state';

	$clusters_sql = "CREATE TABLE {$clusters_table} (
		cluster_uuid varchar(64) NOT NULL,
		tenant_id varchar(64) NOT NULL,
		label text NULL,
		curation_state varchar(20) NOT NULL,
		representative_thumb_path text NULL,
		identity_count int(11) unsigned NOT NULL DEFAULT 0,
		snapshot_version bigint(20) unsigned NOT NULL,
		is_user_confirmed tinyint(1) NOT NULL DEFAULT 0,
		created_at datetime NOT NULL,
		updated_at datetime NOT NULL,
		last_synced_at datetime NOT NULL,
		PRIMARY KEY (cluster_uuid),
		KEY tenant_snapshot (tenant_id, snapshot_version),
		KEY tenant_confirmed (tenant_id, is_user_confirmed)
	) {$charset_collate};";

	$members_sql = "CREATE TABLE {$members_table} (
		identity_uuid varchar(64) NOT NULL,
		cluster_uuid varchar(64) NOT NULL,
		attachment_id bigint(20) unsigned NOT NULL,
		bbox_json longtext NOT NULL,
		thumb_path text NULL,
		similarity double NULL,
		created_at datetime NOT NULL,
		updated_at datetime NOT NULL,
		PRIMARY KEY (identity_uuid),
		KEY cluster_identity (cluster_uuid, identity_uuid),
		KEY attachment_lookup (attachment_id)
	) {$charset_collate};";

	$sync_sql = "CREATE TABLE {$sync_table} (
		stream_name varchar(100) NOT NULL,
		last_snapshot_version bigint(20) unsigned NOT NULL DEFAULT 0,
		updated_at datetime NOT NULL,
		PRIMARY KEY (stream_name)
	) {$charset_collate};";

	dbDelta( $clusters_sql );
	dbDelta( $members_sql );
	dbDelta( $sync_sql );
}
```

### Pattern B: Curation-Safe Merge Semantics (No Destructive Replace)

```php
<?php
declare(strict_types=1);

interface SnapshotProjectorInterface {
	/**
	 * @param array<string, mixed> $snapshot
	 */
	public function project(string $tenant_id, array $snapshot): void;
}

public function project(string $tenant_id, array $snapshot): void {
	$this->clusters_repository->merge_snapshot_for_tenant(
		$tenant_id,
		(array) ($snapshot['clusters'] ?? array()),
		(int) ($snapshot['snapshot_version'] ?? 0)
	);
	$this->members_repository->merge_snapshot_for_tenant(
		$tenant_id,
		(array) ($snapshot['members'] ?? array()),
		(int) ($snapshot['snapshot_version'] ?? 0)
	);
	$this->sync_state_repository->upsert_snapshot_version(
		$tenant_id,
		(int) $snapshot['snapshot_version']
	);
}

/**
 * Cluster merge contract:
 * - Never delete/update rows where is_user_confirmed = 1.
 * - Delete stale rows only where is_user_confirmed = 0 and row absent from incoming snapshot.
 * - Upsert incoming rows with guarded updates for curated fields.
 */

public function merge_snapshot_for_tenant(string $tenant_id, array $clusters, int $snapshot_version): void {
	$incoming_ids = array_map(static fn(array $c): string => (string) ($c['cluster_uuid'] ?? ''), $clusters);
	$incoming_ids = array_values(array_filter($incoming_ids));

	// Remove stale non-curated rows only.
	$this->delete_stale_non_curated_rows($tenant_id, $incoming_ids);

	foreach ($clusters as $cluster) {
		// INSERT ... ON DUPLICATE KEY UPDATE where curated fields remain authoritative.
		$this->upsert_cluster_with_curation_guard(
			$tenant_id,
			(string) ($cluster['cluster_uuid'] ?? ''),
			$cluster,
			$snapshot_version
		);
	}
}

/**
 * Guarded update semantics:
 * - label/curation_state/is_user_confirmed never overwritten when existing row is user-confirmed.
 * - representative_thumb_path, identity_count, snapshot_version, updated_at, last_synced_at can refresh.
 */
```

### Pattern C: Transaction Boundary for Multi-Table Projection

```php
<?php
declare(strict_types=1);

public function project(string $tenant_id, array $snapshot): void {
	global $wpdb;

	if ( ! isset($wpdb) || ! is_object($wpdb) || ! method_exists($wpdb, 'query') ) {
		return;
	}

	// Fail closed if transaction cannot be established; avoid partial projection writes.
	$started = false !== $wpdb->query('START TRANSACTION');
	if ( ! $started ) {
		throw new RuntimeException('Snapshot projection requires transaction support.');
	}

	try {
		$this->clusters_repository->merge_snapshot_for_tenant($tenant_id, (array) $snapshot['clusters'], (int) $snapshot['snapshot_version']);
		$this->members_repository->merge_snapshot_for_tenant($tenant_id, (array) $snapshot['members'], (int) $snapshot['snapshot_version']);
		$this->sync_state_repository->upsert_snapshot_version($tenant_id, (int) $snapshot['snapshot_version']);
		$wpdb->query('COMMIT');
	} catch (Throwable $e) {
		$wpdb->query('ROLLBACK');
		throw $e;
	}
}
```

### Pattern D: Explicit Timestamp Assignment + `bbox_json` Contract

```php
<?php
declare(strict_types=1);

private function now_utc(): string {
	return gmdate('Y-m-d H:i:s');
}

/**
 * bbox_json format (stored in wp_acx_identity_members):
 * {
 *   "pixels": {"x": 120, "y": 45, "width": 80, "height": 92},
 *   "normalized": {"x": 0.1875, "y": 0.09375, "width": 0.125, "height": 0.191667},
 *   "coordinate_space": "original_image"
 * }
 */
private function encode_bbox_json(array $bbox, int $image_width, int $image_height): string {
	$payload = array(
		'pixels' => array(
			'x' => (int) ($bbox['x'] ?? 0),
			'y' => (int) ($bbox['y'] ?? 0),
			'width' => (int) ($bbox['width'] ?? 0),
			'height' => (int) ($bbox['height'] ?? 0),
		),
		'normalized' => array(
			'x' => $image_width > 0 ? round(((int) ($bbox['x'] ?? 0)) / $image_width, 6) : 0.0,
			'y' => $image_height > 0 ? round(((int) ($bbox['y'] ?? 0)) / $image_height, 6) : 0.0,
			'width' => $image_width > 0 ? round(((int) ($bbox['width'] ?? 0)) / $image_width, 6) : 0.0,
			'height' => $image_height > 0 ? round(((int) ($bbox['height'] ?? 0)) / $image_height, 6) : 0.0,
		),
		'coordinate_space' => 'original_image',
	);

	return wp_json_encode($payload) ?: '{}';
}
```

### Pattern E: Snapshot Source Resolution (No Hardcoded Backend Path)

```php
<?php
declare(strict_types=1);

protected function get_snapshot_endpoint_path(): string {
	$default = '/tenants/%s/clusters/snapshot';
	$filtered = apply_filters('acx_snapshot_endpoint_path', $default);

	if ( is_string($filtered) && '' !== trim($filtered) ) {
		return trim($filtered);
	}

	return $default;
}
```

## Functions to Change

| File | Line | Change |
| --- | --- | --- |
| `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php` | 28 | Extend `activate()` to create sovereign projection tables via `dbDelta` and keep idempotence guarantees. |
| `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php` | 71 | Keep uninstall table-drop logic aligned with any schema changes (owned-table symmetry). |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php` | new | Implement curation-safe merge semantics (`merge_snapshot_for_tenant`) instead of destructive tenant replace. |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-identity-members-repository.php` | new | Add identity member repository for projection upsert/merge operations and explicit timestamp assignment. |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-sync-state-repository.php` | new | Add sync-state persistence for `last_snapshot_version` and sync timestamps. |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php` | new | Implement snapshot-to-local projection orchestration with curation-safe write rules. |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-client.php` | new | Add configurable snapshot fetcher using resolved recognition base URL plus filterable endpoint path. |
| `apps/prototype-wp-alt-context/tests/Unit/LifecycleManagerTest.php` | 1 | Add tests asserting projection tables are created idempotently on activation and preserved on re-activation. |
| `apps/prototype-wp-alt-context/tests/Unit` | new | Add unit tests for repositories and projector using deterministic snapshot fixtures. |
| `docs/agentic/contracts/cluster-snapshot-api.md` | new | Define snapshot endpoint request/response contract for backend handoff. |

## Related Files

| File | Note |
| --- | --- |
| `docs/roadmaps/v0.1.0/wp-sovereign-cluster-roadmap.md` | Source roadmap for phased sovereign delivery and exit criteria. |
| `docs/tasks/4.0/4.13.1/wp-plugin-portable-packaging-plan.md` | Packaging workstream that moved sovereign dependencies into this follow-up task. |
| `apps/prototype-wp-alt-context/src/api/class-clusters-controller.php` | Read-path flip target in later phases; Phase 1 should avoid premature coupling. |
| `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php` | Dual-write target for later Phase 3 local-first mutation work. |
| `apps/prototype-wp-alt-context/src/api/class-media-identities-controller.php` | Local-read migration target for later Phase 2 work. |
| `apps/prototype-wp-alt-context/docs/portable-packaging-runbook.md` | Operational docs to extend with local projection verification and manual snapshot pull checks. |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` | Backend-owned snapshot route implementation target, tracked as external linked dependency. |

---

## Phase 1 Checkpoint (2026-02-10)

- Plugin-side sovereign storage/projection foundation is implemented and verified in unit/integration tests.
- Read-path flip (`ClustersController` / `MediaIdentitiesController` local-first reads) remains deferred to roadmap Phase 2.
- Backend snapshot route remains external and unimplemented; plugin contract is now drafted at `docs/agentic/contracts/cluster-snapshot-api.md`.

### Dependency Tracker

| Dependency | Owner | Last Updated | Status | Blocker |
| --- | --- | --- | --- | --- |
| `GET /tenants/{tenant_id}/clusters/snapshot` backend route | recognition-service | 2026-02-10 | Not started | Backend API required for live snapshot pulls (plugin fixture projection is complete) |

# Consolidated Checklist

## Completed

- [x] Portable packaging and standalone artifact workflow are implemented (`0.0.2` release flow).
- [x] Endpoint/auth runtime resolution is decoupled from monorepo paths.
- [x] Lifecycle cleanup already unschedules `acx_sync_pull_snapshot` and drops owned sovereign tables on uninstall.

## Phase 0: Scaffolding (~30 min)

- [x] Add sovereign repository interfaces and class shells with typed method signatures and docblocks.
- [x] Add snapshot projector and snapshot client scaffolds with `TODO` implementation markers.
- [x] Add test stubs for lifecycle schema creation, repositories, and projector fixture ingestion.
- [x] Draft snapshot contract doc (`docs/agentic/contracts/cluster-snapshot-api.md`) before backend route implementation.
- [x] Verify scaffolds compile and tests invoke cleanly (`composer test`, `composer cs-check`, `npm run typecheck`, `npm run lint`, `npm run arch`, `npm run test -- --run`).

## Phase 1: Schema Foundation (`dbDelta`) (~60 min)

- [x] Implement `dbDelta` table creation for `wp_acx_clusters`, `wp_acx_identity_members`, and `wp_acx_sync_state`.
- [x] Ensure `wp_acx_clusters` includes full roadmap columns: `representative_thumb_path`, `identity_count`, `created_at`, `updated_at`, `last_synced_at`.
- [x] Ensure `wp_acx_identity_members` includes `bbox_json` with documented format and explicit coordinate space semantics.
- [x] Add deterministic indexes for tenant/snapshot lookups used by Phase 2 local-read queries.
- [x] Preserve activation idempotence and avoid clobbering existing curation fields.
- [x] Extend lifecycle tests to cover activation, re-activation, and uninstall symmetry.

## Phase 2: Local Repository Layer (~75 min)

- [x] Implement cluster repository methods for tenant-scoped list/detail reads and curation-safe snapshot merge writes.
- [x] Implement identity members repository methods for cluster membership hydration.
- [x] Implement sync-state repository methods for snapshot version tracking.
- [x] Implement explicit timestamp assignment (`created_at`, `updated_at`, `last_synced_at`) in repository writes.
- [x] Add repository unit tests for happy path, empty state, and invalid payload handling.

## Phase 3: Snapshot Projector and Ingestion (~75 min)

- [x] Implement projector that applies snapshot payloads to local tables idempotently.
- [x] Preserve curation-first fields when projecting refreshed backend data.
- [x] Add deterministic thumbnail key persistence strategy in projected records.
- [x] Wrap multi-table projection in transaction (`START TRANSACTION` / `COMMIT` / `ROLLBACK`) and fail closed on unsupported transaction state.
- [x] Add fixture-based projector tests covering first import, re-import, and higher-version replacement.

## Phase 4: Integration Readiness Gate (~45 min)

- [x] Add plugin integration test that ingests fixture snapshot and verifies local read-model rows.
- [x] Add manual smoke procedure to run one snapshot pull into a standalone packaged plugin install.
- [x] Document phase checkpoint status and pause for review before starting roadmap Phase 2 read-path flip.

## External Dependencies (Tracked, Not Gated by Plugin Slice)

- [ ] Backend team finalizes `GET /tenants/{tenant_id}/clusters/snapshot` contract with payload schema and version semantics.
- [ ] Backend team implements snapshot route and tests in `apps/prototype-description-service`.
- [x] Plugin task references backend dependency status (owner/date/blocker) without blocking local schema/repository delivery.

## Stretch Goals

- [x] Add `wp cron event` verification commands to runbook for pre-Phase-3 operability checks.
- [ ] Add optional admin diagnostics panel for last snapshot version and last sync timestamp.

## Success Criteria

- [x] Activating the plugin creates all three projection tables idempotently in a clean WordPress install.
- [x] Snapshot fixture ingestion populates local tables and persists monotonic sync version state.
- [x] Projection re-ingestion preserves curated local state and updates only non-authoritative fields.
- [ ] Snapshot endpoint contract/route dependency is explicitly tracked with owner/date and blocker status.
- [x] Team can begin roadmap Phase 2 (local-first read flip) without additional schema or projection scaffolding work.
- [x] Document explicitly states this task covers storage foundation only and does not by itself satisfy roadmap Phase 1 UI local-read exit criteria.
