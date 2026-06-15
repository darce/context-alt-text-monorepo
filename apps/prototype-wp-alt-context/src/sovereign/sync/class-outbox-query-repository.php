<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

require_once __DIR__ . '/class-outbox-status.php';

use function current_time;
use function implode;
use function is_array;
use function is_object;
use function is_string;
use function json_decode;
use function max;
use function method_exists;
use function trim;

class OutboxQueryRepository {
	private string $table_name;

	public function __construct( ?string $table_name = null ) {
		global $wpdb;

		$default_table = 'wp_acx_sync_outbox';
		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			$default_table = $wpdb->prefix . 'acx_sync_outbox';
		}

		$this->table_name = $table_name ?? $default_table;
	}

	/**
	 * @param int[] $outbox_ids
	 * @return array<int,array<string,mixed>>
	 */
	public function find_operations_by_ids( array $outbox_ids, string $tenant_id ): array {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		$normalized_ids = array_values(
			array_filter(
				array_map( 'intval', $outbox_ids ),
				static fn( int $outbox_id ): bool => $outbox_id > 0
			)
		);
		if (
			'' === $normalized_tenant_id
			|| array() === $normalized_ids
			|| ! isset( $wpdb )
			|| ! is_object( $wpdb )
			|| ! method_exists( $wpdb, 'prepare' )
			|| ! method_exists( $wpdb, 'get_results' )
		) {
			return array();
		}

		$rows = $wpdb->get_results(
			$wpdb->prepare(
				'SELECT id, tenant_id, operation_type, entity_type, entity_key, status, attempts, expected_base_version, local_revision, last_error_code, last_error_message, payload, created_at, last_attempted_at, acknowledged_at
				FROM %i
				WHERE tenant_id = %s AND id IN (' . implode( ',', array_fill( 0, count( $normalized_ids ), '%d' ) ) . ')',
				$this->table_name,
				$normalized_tenant_id,
				...$normalized_ids
			),
			ARRAY_A
		);
		if ( ! is_array( $rows ) ) {
			return array();
		}

		$operations = array();
		foreach ( $rows as $row ) {
			if ( ! is_array( $row ) ) {
				continue;
			}

			$decoded = $this->decode_operation_payload( $row );
			$operation_id = (int) ( $decoded['id'] ?? 0 );
			if ( $operation_id > 0 ) {
				$operations[ $operation_id ] = $decoded;
			}
		}

		return $operations;
	}

	/**
	 * @return array<string,mixed>|null
	 */
	public function find_operation_by_id( int $outbox_id, string $tenant_id ): ?array {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if (
			$outbox_id <= 0
			|| '' === $normalized_tenant_id
			|| ! isset( $wpdb )
			|| ! is_object( $wpdb )
			|| ! method_exists( $wpdb, 'prepare' )
			|| ! method_exists( $wpdb, 'get_row' )
		) {
			return null;
		}

		$row = $wpdb->get_row(
			$wpdb->prepare(
				'SELECT id, tenant_id, operation_type, entity_type, entity_key, status, attempts, expected_base_version, local_revision, last_error_code, last_error_message, payload, created_at, last_attempted_at, acknowledged_at
				FROM %i
				WHERE id = %d AND tenant_id = %s
				LIMIT 1',
				$this->table_name,
				$outbox_id,
				$normalized_tenant_id
			),
			ARRAY_A
		);
		if ( ! is_array( $row ) ) {
			return null;
		}

		return $this->decode_operation_payload( $row );
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function find_operations_by_status( string $tenant_id, ?string $status, int $limit, int $offset ): array {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		$normalized_status = is_string( $status ) ? trim( $status ) : '';
		if (
			'' === $normalized_tenant_id
			|| ! isset( $wpdb )
			|| ! is_object( $wpdb )
			|| ! method_exists( $wpdb, 'prepare' )
			|| ! method_exists( $wpdb, 'get_results' )
		) {
			return array();
		}

		if ( '' === $normalized_status ) {
			$rows = $wpdb->get_results(
				$wpdb->prepare(
					'SELECT id, tenant_id, operation_type, entity_type, entity_key, status, attempts, expected_base_version, local_revision, last_error_code, last_error_message, payload, created_at, last_attempted_at, acknowledged_at
					FROM %i
					WHERE tenant_id = %s
					ORDER BY created_at DESC, id DESC
					LIMIT %d OFFSET %d',
					$this->table_name,
					$normalized_tenant_id,
					max( 1, $limit ),
					max( 0, $offset )
				),
				ARRAY_A
			);
		} else {
			$rows = $wpdb->get_results(
				$wpdb->prepare(
					'SELECT id, tenant_id, operation_type, entity_type, entity_key, status, attempts, expected_base_version, local_revision, last_error_code, last_error_message, payload, created_at, last_attempted_at, acknowledged_at
					FROM %i
					WHERE tenant_id = %s AND status = %s
					ORDER BY created_at DESC, id DESC
					LIMIT %d OFFSET %d',
					$this->table_name,
					$normalized_tenant_id,
					$normalized_status,
					max( 1, $limit ),
					max( 0, $offset )
				),
				ARRAY_A
			);
		}
		if ( ! is_array( $rows ) ) {
			return array();
		}

		return array_values(
			array_filter(
				array_map( array( $this, 'decode_operation_payload' ), $rows ),
				'is_array'
			)
		);
	}

	public function count_operations_by_status( string $tenant_id, ?string $status ): int {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		$normalized_status = is_string( $status ) ? trim( $status ) : '';
		if (
			'' === $normalized_tenant_id
			|| ! isset( $wpdb )
			|| ! is_object( $wpdb )
			|| ! method_exists( $wpdb, 'prepare' )
			|| ! method_exists( $wpdb, 'get_var' )
		) {
			return 0;
		}

		if ( '' === $normalized_status ) {
			$value = $wpdb->get_var(
				$wpdb->prepare(
					'SELECT COUNT(*) FROM %i WHERE tenant_id = %s',
					$this->table_name,
					$normalized_tenant_id
				)
			);
		} else {
			$value = $wpdb->get_var(
				$wpdb->prepare(
					'SELECT COUNT(*) FROM %i WHERE tenant_id = %s AND status = %s',
					$this->table_name,
					$normalized_tenant_id,
					$normalized_status
				)
			);
		}

		return max( 0, (int) $value );
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function load_pending_operations( int $batch_size ): array {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$rows = $wpdb->get_results(
			$wpdb->prepare(
				'SELECT id, tenant_id, operation_type, entity_type, entity_key, idempotency_key, expected_base_version, local_revision, payload, attempts
				, created_at
				FROM %i
				WHERE status = %s
				ORDER BY created_at ASC, id ASC
				LIMIT %d',
				$this->table_name,
				'pending',
				max( 1, $batch_size )
			),
			ARRAY_A
		);
		if ( ! is_array( $rows ) ) {
			return array();
		}

		$operations = array();
		foreach ( $rows as $row ) {
			if ( ! is_array( $row ) ) {
				continue;
			}

			$payload = $row['payload'] ?? array();
			if ( is_string( $payload ) ) {
				$decoded_payload = json_decode( $payload, true );
				$payload = is_array( $decoded_payload ) ? $decoded_payload : array();
			}

			$row['payload'] = is_array( $payload ) ? $payload : array();
			$operations[] = $row;
		}

		return $operations;
	}

	/**
	 * Atomically claim a single pending operation for this drain.
	 *
	 * Transitions pending -> in_flight gated on the current status so a row already
	 * claimed by a concurrent drain matches 0 rows. Returns true only when this caller
	 * won the claim (CON-3).
	 */
	public function claim_operation( int $outbox_id ): bool {
		global $wpdb;

		if ( $outbox_id <= 0 || ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'update' ) ) {
			return false;
		}

		$updated = $wpdb->update(
			$this->table_name,
			array(
				'status'     => OutboxStatus::IN_FLIGHT,
				'claimed_at' => current_time( 'mysql' ),
			),
			array(
				'id'     => $outbox_id,
				'status' => OutboxStatus::PENDING,
			),
			array( '%s', '%s' ),
			array( '%d', '%s' )
		);

		return false !== $updated && (int) $updated > 0;
	}

	/**
	 * Reclaim operations stuck in `in_flight` past the claim lease back to `pending` (CON-3-FU-1).
	 *
	 * A drain that dies between {@see self::claim_operation()} (pending -> in_flight) and the
	 * terminal apply_result write orphans the row: load_pending_operations() and
	 * has_pending_operations() only see `pending`, so the stuck row is never reprocessed. This
	 * lease-expiry UPDATE returns such rows to `pending` and clears the claim. A freshly-claimed
	 * row (claimed_at = NOW) sits inside the lease window and is left untouched, so a peer drain
	 * mid-flight is not disturbed. Mirrors the topology drain's lease-reclaim. Returns the count.
	 */
	public function reclaim_stale_in_flight_operations( int $lease_seconds ): int {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$query = $wpdb->prepare(
			'UPDATE %i SET status = %s, claimed_at = NULL WHERE status = %s AND ( claimed_at IS NULL OR claimed_at <= DATE_SUB( NOW(), INTERVAL %d SECOND ) )',
			$this->table_name,
			OutboxStatus::PENDING,
			OutboxStatus::IN_FLIGHT,
			max( 1, $lease_seconds )
		);
		if ( ! is_string( $query ) || '' === $query ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$result = $wpdb->query( $query );

		return false !== $result ? max( 0, (int) $result ) : 0;
	}

	public function has_pending_operations(): bool {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_var' ) ) {
			return false;
		}

		$value = $wpdb->get_var(
			$wpdb->prepare(
				'SELECT id FROM %i WHERE status = %s ORDER BY created_at ASC LIMIT 1',
				$this->table_name,
				'pending'
			)
		);

		return (int) $value > 0;
	}

	/**
	 * @param array<string,mixed> $row
	 * @return array<string,mixed>
	 */
	private function decode_operation_payload( array $row ): array {
		$payload = $row['payload'] ?? array();
		if ( is_string( $payload ) ) {
			$decoded_payload = json_decode( $payload, true );
			$row['payload'] = is_array( $decoded_payload ) ? $decoded_payload : array();
		}

		return $row;
	}
}
