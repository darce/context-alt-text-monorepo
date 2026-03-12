<?php

declare(strict_types=1);

namespace AltContext\Tests\Stubs;

use AltContext\Sovereign\Sync\OutboxDrain;

class InMemoryOutboxDrain extends OutboxDrain
{
	/** @var array<int,array<string,mixed>> */
	private array $operations = array();

	public bool $retryScheduled = false;
	public int $findByIdCalls = 0;
	public int $findByIdsCalls = 0;

	/**
	 * @param array<int,array<string,mixed>> $operations
	 */
	public function __construct( array $operations = array() ) {
		foreach ( $operations as $operation ) {
			$this->operations[ (int) $operation['id'] ] = $operation;
		}
	}

	public function seed_operation( array $operation ): void {
		$this->operations[ (int) $operation['id'] ] = $operation;
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function find_operations( string $tenant_id, ?string $status = null, int $limit = 50, int $offset = 0 ): array {
		$normalized_status = is_string( $status ) ? trim( $status ) : '';
		$matches = array_values(
			array_filter(
				$this->operations,
				static fn( array $operation ): bool =>
					(string) ( $operation['tenant_id'] ?? '' ) === $tenant_id
					&& ( '' === $normalized_status || (string) ( $operation['status'] ?? '' ) === $normalized_status )
			)
		);

		return array_slice( $matches, $offset, $limit );
	}

	public function count_operations( string $tenant_id, ?string $status = null ): int {
		return count( $this->find_operations( $tenant_id, $status, 999, 0 ) );
	}

	public function find_failed_operations( string $tenant_id, int $limit = 50, int $offset = 0 ): array {
		return $this->find_operations( $tenant_id, 'failed', $limit, $offset );
	}

	public function count_failed_operations( string $tenant_id ): int {
		return $this->count_operations( $tenant_id, 'failed' );
	}

	public function find_operations_by_ids( array $outbox_ids, string $tenant_id ): array {
		++$this->findByIdsCalls;
		$saved_find_by_id_calls = $this->findByIdCalls;

		$matches = array();
		foreach ( $outbox_ids as $outbox_id ) {
			$operation = $this->find_operation_by_id( (int) $outbox_id, $tenant_id );
			if ( is_array( $operation ) ) {
				$matches[ (int) $operation['id'] ] = $operation;
			}
		}

		$this->findByIdCalls = $saved_find_by_id_calls;

		return $matches;
	}

	public function find_operation_by_id( int $outbox_id, string $tenant_id ): ?array {
		++$this->findByIdCalls;
		$operation = $this->operations[ $outbox_id ] ?? null;
		if ( ! is_array( $operation ) || (string) ( $operation['tenant_id'] ?? '' ) !== $tenant_id ) {
			return null;
		}

		return $operation;
	}

	public function retry_failed_operation( int $outbox_id, string $tenant_id ): bool {
		$operation = $this->find_operation_by_id( $outbox_id, $tenant_id );
		if ( ! is_array( $operation ) || 'failed' !== (string) ( $operation['status'] ?? '' ) ) {
			return false;
		}

		$this->operations[ $outbox_id ]['status'] = 'pending';
		$this->operations[ $outbox_id ]['attempts'] = 0;
		$this->operations[ $outbox_id ]['last_error_code'] = null;
		$this->operations[ $outbox_id ]['last_error_message'] = null;
		$this->operations[ $outbox_id ]['last_attempted_at'] = null;
		$this->retryScheduled = true;

		return true;
	}

	public function discard_operation( int $outbox_id, string $tenant_id ): bool {
		$operation = $this->find_operation_by_id( $outbox_id, $tenant_id );
		if ( ! is_array( $operation ) || ! in_array( (string) ( $operation['status'] ?? '' ), array( 'failed', 'conflict' ), true ) ) {
			return false;
		}

		$this->operations[ $outbox_id ]['status'] = 'discarded';

		return true;
	}
}
