<?php

declare(strict_types=1);

namespace AltContext\Tests\Stubs;

use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;

/**
 * No-op implementation of SyncStateRepositoryInterface for unit tests.
 *
 * Extend this class and override only the methods your test needs.
 */
class NullSyncStateRepository implements SyncStateRepositoryInterface {
	public function upsert_snapshot_version( string $tenant_id, int $snapshot_version ): void {}

	public function get_snapshot_version( string $tenant_id ): int {
		return 0;
	}

	public function get_last_updated( string $tenant_id ): ?string {
		return null;
	}

	public function touch_local_curation_marker( string $tenant_id ): void {}

	public function refresh_curation_metrics( string $tenant_id ): void {}

	public function get_pending_curation_operations( string $tenant_id ): int {
		return 0;
	}

	public function get_conflict_count( string $tenant_id ): int {
		return 0;
	}

	public function get_last_curation_acknowledged_at( string $tenant_id ): ?string {
		return null;
	}

	public function get_last_curation_conflict_at( string $tenant_id ): ?string {
		return null;
	}
}
