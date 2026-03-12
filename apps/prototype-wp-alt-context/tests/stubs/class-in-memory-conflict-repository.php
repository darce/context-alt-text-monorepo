<?php

declare(strict_types=1);

namespace AltContext\Tests\Stubs;

use AltContext\Sovereign\Sync\ConflictRepository;

class InMemoryConflictRepository extends ConflictRepository
{
	/** @var array<int,array<string,mixed>> */
	private array $conflicts = array();

	/**
	 * @param array<int,array<string,mixed>> $conflicts
	 */
	public function __construct( array $conflicts = array() ) {
		foreach ( $conflicts as $conflict ) {
			$this->conflicts[ (int) $conflict['id'] ] = $conflict;
		}
	}

	public function seed_conflict( array $conflict ): void {
		$this->conflicts[ (int) $conflict['id'] ] = $conflict;
	}

	public function find_conflicts_for_tenant( string $tenant_id, string $resolution_status = 'open', int $limit = 50, int $offset = 0 ): array {
		$matches = array_values(
			array_filter(
				$this->conflicts,
				static fn( array $conflict ): bool =>
					(string) ( $conflict['tenant_id'] ?? '' ) === $tenant_id
					&& (string) ( $conflict['resolution_status'] ?? 'open' ) === $resolution_status
			)
		);

		return array_slice( $matches, $offset, $limit );
	}

	public function count_conflicts( string $tenant_id, string $resolution_status = 'open' ): int {
		return count( $this->find_conflicts_for_tenant( $tenant_id, $resolution_status, 999, 0 ) );
	}

	public function find_conflict_by_id( int $conflict_id, string $tenant_id ): ?array {
		$conflict = $this->conflicts[ $conflict_id ] ?? null;
		if ( ! is_array( $conflict ) || (string) ( $conflict['tenant_id'] ?? '' ) !== $tenant_id ) {
			return null;
		}

		return $conflict;
	}

	public function mark_resolved( int $conflict_id, string $resolution_status, string $tenant_id ): bool {
		$conflict = $this->find_conflict_by_id( $conflict_id, $tenant_id );
		if ( ! is_array( $conflict ) ) {
			return false;
		}

		$this->conflicts[ $conflict_id ]['resolution_status'] = $resolution_status;
		$this->conflicts[ $conflict_id ]['resolved_at'] = '2026-03-11 10:15:00';

		return true;
	}
}
