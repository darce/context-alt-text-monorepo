<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

require_once __DIR__ . '/../repositories/class-sync-state-repository.php';

use AltContext\Sovereign\Repositories\SyncStateRepository;

use function is_array;
use function is_object;
use function is_string;
use function max;
use function method_exists;
use function trim;
use function wp_json_encode;

class OutboxMaintenanceService {
	private OutboxQueryRepository $query_repository;
	private SyncStateRepository $sync_state_repository;
	private string $table_name;

	public function __construct(
		?OutboxQueryRepository $query_repository = null,
		?SyncStateRepository $sync_state_repository = null,
		?string $table_name = null
	) {
		global $wpdb;

		$default_table = 'wp_acx_sync_outbox';
		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			$default_table = $wpdb->prefix . 'acx_sync_outbox';
		}

		$this->table_name = $table_name ?? $default_table;
		$this->query_repository = $query_repository ?? new OutboxQueryRepository( $this->table_name );
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
	}

	public function retry_failed_operation( int $outbox_id, string $tenant_id ): bool {
		$updated = $this->update_operation_status(
			$outbox_id,
			$tenant_id,
			'failed',
			array(
				'status' => 'pending',
				'attempts' => 0,
				'last_error_code' => null,
				'last_error_message' => null,
				'last_attempted_at' => null,
			),
			array( '%s', '%d', '%s', '%s', '%s' )
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
		if ( ! in_array( $current_status, array( 'failed', 'conflict' ), true ) ) {
			return false;
		}

		$updated = $this->update_operation_status(
			$outbox_id,
			$tenant_id,
			$current_status,
			array(
				'status' => 'discarded',
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
			'status' => 'pending',
			'attempts' => 0,
			'expected_base_version' => max( 0, $backend_version ),
			'last_error_code' => null,
			'last_error_message' => null,
		);
		$format = array( '%s', '%d', '%d', '%s', '%s' );

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
			'conflict',
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
