<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

use function current_time;
use function is_array;
use function is_numeric;
use function is_object;
use function is_string;
use function max;
use function method_exists;
use function trim;
use function wp_json_encode;

class ConflictRepository {
	private string $table_name;

	public function __construct( ?string $table_name = null ) {
		global $wpdb;

		$default_table = 'wp_acx_sync_conflicts';
		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			$default_table = $wpdb->prefix . 'acx_sync_conflicts';
		}

		$this->table_name = $table_name ?? $default_table;
	}

	/**
	 * Persist one conflict result emitted by the outbox drain.
	 *
	 * @param array<string,mixed> $operation
	 * @param array<string,mixed> $result
	 */
	public function record_conflict( array $operation, array $result ): int|false {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'insert' ) ) {
			return false;
		}

		$tenant_id = trim( (string) ( $operation['tenant_id'] ?? '' ) );
		$entity_type = trim( (string) ( $operation['entity_type'] ?? '' ) );
		$entity_key = trim( (string) ( $operation['entity_key'] ?? '' ) );

		if ( '' === $tenant_id || '' === $entity_type || '' === $entity_key ) {
			return false;
		}

		$machine_payload = is_array( $result['machine_payload'] ?? null ) ? $result['machine_payload'] : array();
		$local_payload = is_array( $operation['payload'] ?? null ) ? $operation['payload'] : array();
		$machine_payload_json = wp_json_encode( $machine_payload );
		$local_payload_json = wp_json_encode( $local_payload );

		if ( ! is_string( $machine_payload_json ) || '' === $machine_payload_json ) {
			$machine_payload_json = '{}';
		}

		if ( ! is_string( $local_payload_json ) || '' === $local_payload_json ) {
			$local_payload_json = '{}';
		}

		$inserted = $wpdb->insert(
			$this->table_name,
			array(
				'tenant_id' => $tenant_id,
				'entity_type' => $entity_type,
				'entity_key' => $entity_key,
				'outbox_id' => max( 0, (int) ( $operation['id'] ?? 0 ) ),
				'expected_base_version' => max( 0, (int) ( $operation['expected_base_version'] ?? 0 ) ),
				'backend_version' => max( 0, (int) ( $result['backend_version'] ?? 0 ) ),
				'local_revision' => max( 0, (int) ( $operation['local_revision'] ?? 0 ) ),
				'conflict_code' => trim( (string) ( $result['conflict_code'] ?? 'version_conflict' ) ),
				'machine_payload' => $machine_payload_json,
				'local_payload' => $local_payload_json,
				'resolution_status' => 'open',
				'created_at' => current_time( 'mysql' ),
			),
			array( '%s', '%s', '%s', '%d', '%d', '%d', '%d', '%s', '%s', '%s', '%s', '%s' )
		);

		if ( false === $inserted ) {
			return false;
		}

		return $this->resolve_insert_id( $wpdb );
	}

	/**
	 * Resolve inserted primary key without relying on dynamic properties.
	 *
	 * @param object $wpdb
	 */
	private function resolve_insert_id( object $wpdb ): int {
		if ( method_exists( $wpdb, 'get_var' ) ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Constant query with no user input.
			$insert_id = $wpdb->get_var( 'SELECT LAST_INSERT_ID()' );
			if ( is_numeric( $insert_id ) ) {
				return max( 1, (int) $insert_id );
			}
		}

		return 1;
	}
}
