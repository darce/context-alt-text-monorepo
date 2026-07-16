<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

require_once __DIR__ . '/../repositories/class-sync-state-repository.php';
require_once __DIR__ . '/class-conflict-resolution-status.php';
require_once __DIR__ . '/class-outbox-status.php';
require_once __DIR__ . '/../../support/trait-runs-transactional.php';

use AltContext\Support\RunsTransactional;
use AltContext\Sovereign\Repositories\SyncStateRepository;

use function apply_filters;
use function array_merge;
use function array_unique;
use function array_values;
use function current_time;
use function gmdate;
use function is_array;
use function is_object;
use function is_string;
use function max;
use function method_exists;
use function trim;
use function wp_json_encode;

class OutboxMaintenanceService {
	use RunsTransactional;

	private const DEFAULT_PURGE_BATCH_SIZE = 50;
	private const DEFAULT_ACKNOWLEDGED_RETENTION_DAYS = 14;
	private const DEFAULT_RESOLVED_CONFLICT_RETENTION_DAYS = 14;
	private const MAX_PURGE_BATCH_ITERATIONS = 20;

	private OutboxQueryRepository $query_repository;
	private SyncStateRepository $sync_state_repository;
	private string $table_name;
	private string $conflicts_table_name;

	public function __construct(
		?OutboxQueryRepository $query_repository = null,
		?SyncStateRepository $sync_state_repository = null,
		?string $table_name = null,
		?string $conflicts_table_name = null
	) {
		global $wpdb;

		$default_table = 'wp_acx_sync_outbox';
		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			$default_table = $wpdb->prefix . 'acx_sync_outbox';
		}

		$default_conflicts_table = 'wp_acx_sync_conflicts';
		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			$default_conflicts_table = $wpdb->prefix . 'acx_sync_conflicts';
		}

		$this->table_name = $table_name ?? $default_table;
		$this->conflicts_table_name = $conflicts_table_name ?? $default_conflicts_table;
		$this->query_repository = $query_repository ?? new OutboxQueryRepository( $this->table_name );
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
	}

	/**
	 * @return array{outbox:int,conflicts:int}|false
	 */
	public function purge_terminal_rows( string $tenant_id ): array|false {
		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			return false;
		}

		$result = $this->run_transactional(
			function () use ( $normalized_tenant_id ): array {
				return array(
					'outbox' => $this->purge_acknowledged_outbox_batch( $normalized_tenant_id ),
					'conflicts' => $this->purge_resolved_conflicts_batch( $normalized_tenant_id ),
				);
			}
		);

		if ( is_wp_error( $result ) ) {
			return false;
		}

		return is_array( $result ) ? $result : false;
	}

	/**
	 * @return string[]
	 */
	public function list_terminal_purge_tenant_ids(): array {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_col' ) ) {
			return array();
		}

		$tenant_ids = array();

		$outbox_tenant_ids = $wpdb->get_col(
			$wpdb->prepare(
				'SELECT DISTINCT tenant_id FROM %i WHERE tenant_id <> %s',
				$this->table_name,
				''
			)
		);
		$conflict_tenant_ids = $wpdb->get_col(
			$wpdb->prepare(
				'SELECT DISTINCT tenant_id FROM %i WHERE tenant_id <> %s',
				$this->conflicts_table_name,
				''
			)
		);

		foreach ( array_merge( is_array( $outbox_tenant_ids ) ? $outbox_tenant_ids : array(), is_array( $conflict_tenant_ids ) ? $conflict_tenant_ids : array() ) as $tenant_id ) {
			$normalized_tenant_id = trim( (string) $tenant_id );
			if ( '' !== $normalized_tenant_id ) {
				$tenant_ids[] = $normalized_tenant_id;
			}
		}

		return array_values( array_unique( $tenant_ids ) );
	}

	public function purge_acknowledged_outbox_batch( string $tenant_id ): int {
		$batch_size = max( 1, (int) apply_filters( 'acx_sync_purge_batch_size', self::DEFAULT_PURGE_BATCH_SIZE ) );
		$total_deleted = 0;

		for ( $iteration = 0; $iteration < self::MAX_PURGE_BATCH_ITERATIONS; $iteration++ ) {
			$deleted = $this->purge_acknowledged_outbox_batch_once( $tenant_id, $batch_size );
			$total_deleted += $deleted;
			if ( $deleted < $batch_size ) {
				break;
			}
		}

		return $total_deleted;
	}

	public function purge_resolved_conflicts_batch( string $tenant_id ): int {
		$batch_size = max( 1, (int) apply_filters( 'acx_sync_purge_batch_size', self::DEFAULT_PURGE_BATCH_SIZE ) );
		$total_deleted = 0;

		for ( $iteration = 0; $iteration < self::MAX_PURGE_BATCH_ITERATIONS; $iteration++ ) {
			$deleted = $this->purge_resolved_conflicts_batch_once( $tenant_id, $batch_size );
			$total_deleted += $deleted;
			if ( $deleted < $batch_size ) {
				break;
			}
		}

		return $total_deleted;
	}

	private function purge_acknowledged_outbox_batch_once( string $tenant_id, int $batch_size ): int {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if (
			'' === $normalized_tenant_id
			|| ! isset( $wpdb )
			|| ! is_object( $wpdb )
			|| ! method_exists( $wpdb, 'query' )
		) {
			return 0;
		}

		$retention_days = max( 1, (int) apply_filters( 'acx_sync_purge_acknowledged_days', self::DEFAULT_ACKNOWLEDGED_RETENTION_DAYS ) );
		$day_seconds = defined( 'DAY_IN_SECONDS' ) ? (int) DAY_IN_SECONDS : 86400;
		$cutoff = gmdate( 'Y-m-d H:i:s', current_time( 'timestamp' ) - ( $retention_days * $day_seconds ) );

		$deleted = $wpdb->query(
			$wpdb->prepare(
				'DELETE FROM %i
				WHERE tenant_id = %s
					AND status = %s
					AND acknowledged_at IS NOT NULL
					AND acknowledged_at < %s
				ORDER BY acknowledged_at ASC
				LIMIT %d',
				$this->table_name,
				$normalized_tenant_id,
				OutboxStatus::ACKNOWLEDGED,
				$cutoff,
				$batch_size
			)
		);

		return max( 0, (int) $deleted );
	}

	private function purge_resolved_conflicts_batch_once( string $tenant_id, int $batch_size ): int {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if (
			'' === $normalized_tenant_id
			|| ! isset( $wpdb )
			|| ! is_object( $wpdb )
			|| ! method_exists( $wpdb, 'query' )
		) {
			return 0;
		}

		$retention_days = max( 1, (int) apply_filters( 'acx_sync_purge_resolved_conflict_days', self::DEFAULT_RESOLVED_CONFLICT_RETENTION_DAYS ) );
		$day_seconds = defined( 'DAY_IN_SECONDS' ) ? (int) DAY_IN_SECONDS : 86400;
		$cutoff = gmdate( 'Y-m-d H:i:s', current_time( 'timestamp' ) - ( $retention_days * $day_seconds ) );

		$deleted = $wpdb->query(
			$wpdb->prepare(
				'DELETE FROM %i
				WHERE tenant_id = %s
					AND resolution_status <> %s
					AND resolved_at IS NOT NULL
					AND resolved_at < %s
				ORDER BY resolved_at ASC
				LIMIT %d',
				$this->conflicts_table_name,
				$normalized_tenant_id,
				ConflictResolutionStatus::OPEN,
				$cutoff,
				$batch_size
			)
		);

		return max( 0, (int) $deleted );
	}

	public function retry_failed_operation( int $outbox_id, string $tenant_id ): bool {
		$updated = $this->update_operation_status(
			$outbox_id,
			$tenant_id,
			OutboxStatus::FAILED,
			array(
				'status' => OutboxStatus::PENDING,
				'attempts' => 0,
				'last_error_code' => null,
				'last_error_message' => null,
				'last_attempted_at' => null,
				// E15-35: a requeued op starts a fresh retry window — stale first_failed_at
				// would instantly re-terminate it on the next retryable failure.
				'first_failed_at' => null,
				'next_attempt_at' => null,
			),
			array( '%s', '%d', '%s', '%s', '%s', '%s', '%s' )
		);
		if ( ! $updated ) {
			return false;
		}

		$this->sync_state_repository->refresh_curation_metrics( $tenant_id );
		OutboxDrain::maybe_schedule_drain();

		return true;
	}

	public function discard_operation( int $outbox_id, string $tenant_id ): bool {
		$operation = $this->query_repository->find_operation_by_id( $outbox_id, $tenant_id );
		if ( ! is_array( $operation ) ) {
			return false;
		}

		$current_status = trim( (string) ( $operation['status'] ?? '' ) );
		if ( ! in_array( $current_status, array( OutboxStatus::FAILED, OutboxStatus::CONFLICT ), true ) ) {
			return false;
		}

		$updated = $this->update_operation_status(
			$outbox_id,
			$tenant_id,
			$current_status,
			array(
				'status' => OutboxStatus::DISCARDED,
			),
			array( '%s' )
		);
		if ( ! $updated ) {
			return false;
		}

		$this->sync_state_repository->refresh_curation_metrics( $tenant_id );
		return true;
	}

	public function re_enqueue_with_current_base( int $outbox_id, int $backend_version, string $tenant_id, ?string $merged_value = null ): bool {
		$data = array(
			'status' => OutboxStatus::PENDING,
			'attempts' => 0,
			'expected_base_version' => max( 0, $backend_version ),
			'last_error_code' => null,
			'last_error_message' => null,
			// E15-35: re-enqueue starts a fresh retry window (see retry_failed_operation).
			'first_failed_at' => null,
			'next_attempt_at' => null,
		);
		$format = array( '%s', '%d', '%d', '%s', '%s', '%s', '%s' );

		$normalized_merged_value = is_string( $merged_value ) ? trim( $merged_value ) : '';
		if ( '' !== $normalized_merged_value ) {
			$operation = $this->query_repository->find_operation_by_id( $outbox_id, $tenant_id );
			if ( is_array( $operation ) ) {
				$payload = is_array( $operation['payload'] ?? null ) ? $operation['payload'] : array();
				$payload['merged_value'] = $normalized_merged_value;

				if ( '' === trim( (string) ( $payload['label'] ?? '' ) ) ) {
					$payload['label'] = $normalized_merged_value;
				}

				if ( '' === trim( (string) ( $payload['name'] ?? '' ) ) ) {
					$payload['name'] = $normalized_merged_value;
				}

				$payload_json = wp_json_encode( $payload );
				if ( ! is_string( $payload_json ) || '' === $payload_json ) {
					$payload_json = '{}';
				}

				$data['payload'] = $payload_json;
				$format[] = '%s';
			}
		}

		$updated = $this->update_operation_status(
			$outbox_id,
			$tenant_id,
			OutboxStatus::CONFLICT,
			$data,
			$format
		);
		if ( ! $updated ) {
			return false;
		}

		$this->sync_state_repository->refresh_curation_metrics( $tenant_id );
		OutboxDrain::maybe_schedule_drain();
		return true;
	}

	/**
	 * @param array<string,mixed> $data
	 * @param string[] $format
	 */
	private function update_operation_status( int $outbox_id, string $tenant_id, string $expected_status, array $data, array $format ): bool {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if (
			$outbox_id <= 0
			|| '' === $normalized_tenant_id
			|| '' === trim( $expected_status )
			|| ! isset( $wpdb )
			|| ! is_object( $wpdb )
			|| ! method_exists( $wpdb, 'update' )
		) {
			return false;
		}

		$updated = $wpdb->update(
			$this->table_name,
			$data,
			array(
				'id' => $outbox_id,
				'tenant_id' => $normalized_tenant_id,
				'status' => $expected_status,
			),
			$format,
			array( '%d', '%s', '%s' )
		);

		return false !== $updated;
	}
}
