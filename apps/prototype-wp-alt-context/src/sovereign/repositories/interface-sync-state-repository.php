<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

interface SyncStateRepositoryInterface {
	public function upsert_snapshot_version( string $tenant_id, int $snapshot_version ): void;

	public function get_snapshot_version( string $tenant_id ): int;

	public function get_last_updated( string $tenant_id ): ?string;

	public function touch_local_curation_marker( string $tenant_id ): void;

	public function refresh_curation_metrics( string $tenant_id ): void;

	public function get_pending_curation_operations( string $tenant_id ): int;

	public function get_conflict_count( string $tenant_id ): int;

	public function get_failed_curation_operations( string $tenant_id ): int;

	public function get_last_curation_acknowledged_at( string $tenant_id ): ?string;

	public function get_last_curation_conflict_at( string $tenant_id ): ?string;

	public function get_last_curation_failed_at( string $tenant_id ): ?string;

	public function get_pending_topology_commands( string $tenant_id ): int;

	public function get_applied_topology_commands( string $tenant_id ): int;

	public function get_failed_topology_commands( string $tenant_id ): int;

	public function get_conflicted_topology_commands( string $tenant_id ): int;

	public function get_last_topology_reconciled_at( string $tenant_id ): ?string;
}
