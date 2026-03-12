<?php

declare(strict_types=1);

namespace AltContext\Tests\Stubs;

class TrackingSyncStateRepository extends NullSyncStateRepository
{
	/** @var array<string,mixed> */
	private array $state;

	public int $refreshCount = 0;
	public ?string $lastTenantId = null;

	/**
	 * @param array<string,mixed> $state
	 */
	public function __construct( array $state = array() ) {
		$this->state = $state;
	}

	public function refresh_curation_metrics( string $tenant_id ): void {
		++$this->refreshCount;
		$this->lastTenantId = $tenant_id;
	}

	public function get_snapshot_version( string $tenant_id ): int {
		return (int) ( $this->state['snapshot_version'] ?? 12 );
	}

	public function get_last_updated( string $tenant_id ): ?string {
		$value = $this->state['last_updated'] ?? null;
		if ( 'recent' === $value ) {
			return gmdate( 'Y-m-d H:i:s' );
		}

		return $value;
	}

	public function get_last_sync_result( string $tenant_id ): string {
		return (string) ( $this->state['last_sync_result'] ?? 'ok' );
	}

	public function get_pending_curation_operations( string $tenant_id ): int {
		return (int) ( $this->state['pending_curation_operations'] ?? 0 );
	}

	public function get_conflict_count( string $tenant_id ): int {
		return (int) ( $this->state['conflict_count'] ?? 0 );
	}

	public function get_failed_curation_operations( string $tenant_id ): int {
		return (int) ( $this->state['failed_curation_operations'] ?? 0 );
	}

	public function get_pending_topology_commands( string $tenant_id ): int {
		return (int) ( $this->state['topology_pending'] ?? 0 );
	}

	public function get_applied_topology_commands( string $tenant_id ): int {
		return (int) ( $this->state['topology_applied'] ?? 0 );
	}

	public function get_failed_topology_commands( string $tenant_id ): int {
		return (int) ( $this->state['topology_failed'] ?? 0 );
	}

	public function get_conflicted_topology_commands( string $tenant_id ): int {
		return (int) ( $this->state['topology_conflict'] ?? 0 );
	}
}
