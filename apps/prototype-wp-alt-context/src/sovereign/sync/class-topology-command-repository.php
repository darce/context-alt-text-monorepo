<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

require_once __DIR__ . '/../repositories/trait-prepares-sql-queries.php';
require_once __DIR__ . '/interface-topology-command-repository.php';

use AltContext\Sovereign\Repositories\PreparesSqlQueries;
use function current_time;
use function is_numeric;
use function is_object;
use function is_string;
use function max;
use function method_exists;
use function trim;
use function wp_generate_uuid4;
use function wp_json_encode;

class TopologyCommandRepository implements TopologyCommandRepositoryInterface {
	use PreparesSqlQueries;

	private string $table_name;

	public function __construct( ?string $table_name = null ) {
		global $wpdb;

		$default_table = 'wp_acx_topology_commands';
		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			$default_table = $wpdb->prefix . 'acx_topology_commands';
		}

		$this->table_name = $table_name ?? $default_table;
	}

	/**
	 * @param array<string,mixed> $payload
	 */
	public function enqueue(
		string $tenant_id,
		string $command_type,
		string $entity_key,
		int $expected_base_version,
		array $payload,
		?string $idempotency_key = null
	): int|false {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'insert' ) ) {
			return false;
		}

		$normalized_tenant_id = trim( $tenant_id );
		$normalized_command_type = trim( $command_type );
		$normalized_entity_key = trim( $entity_key );
		if ( '' === $normalized_tenant_id || '' === $normalized_command_type || '' === $normalized_entity_key ) {
			return false;
		}

		$key = trim( (string) $idempotency_key );
		if ( '' === $key ) {
			$key = wp_generate_uuid4();
		}

		$payload_json = wp_json_encode( $payload );
		if ( ! is_string( $payload_json ) || '' === $payload_json ) {
			$payload_json = '{}';
		}

		$inserted = $wpdb->insert(
			$this->table_name,
			array(
				'tenant_id' => $normalized_tenant_id,
				'command_type' => $normalized_command_type,
				'entity_key' => $normalized_entity_key,
				'payload_json' => $payload_json,
				'idempotency_key' => $key,
				'expected_base_version' => max( 0, $expected_base_version ),
				'status' => 'pending',
				'attempts' => 0,
				'created_at' => current_time( 'mysql' ),
				'updated_at' => current_time( 'mysql' ),
			),
			array( '%s', '%s', '%s', '%s', '%s', '%d', '%s', '%d', '%s', '%s' )
		);

		if ( false === $inserted ) {
			return false;
		}

		return $this->resolve_insert_id( $wpdb );
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function find_reconcilable( ?string $tenant_id = null, int $limit = 25 ): array {
		return $this->find_by_statuses( array( 'pending', 'applied' ), $tenant_id, $limit );
	}

	/**
	 * @param string[] $statuses
	 * @return array<int,array<string,mixed>>
	 */
	private function find_by_statuses( array $statuses, ?string $tenant_id = null, int $limit = 25 ): array {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_results' ) || ! method_exists( $wpdb, 'prepare' ) ) {
			return array();
		}

		$normalized_tenant_id = null;
		if ( is_string( $tenant_id ) ) {
			$normalized_tenant_id = trim( $tenant_id );
			if ( '' === $normalized_tenant_id ) {
				$normalized_tenant_id = null;
			}
		}

		if ( empty( $statuses ) ) {
			return array();
		}

		$status_placeholders = implode( ', ', array_fill( 0, count( $statuses ), '%s' ) );
		if ( null !== $normalized_tenant_id ) {
			$query = $this->prepare_query(
				"SELECT * FROM %i WHERE tenant_id = %s AND status IN ({$status_placeholders}) ORDER BY created_at ASC LIMIT %d",
				array_merge(
					array(
						$this->table_name,
						$normalized_tenant_id,
					),
					$statuses,
					array( max( 1, $limit ) )
				)
			);
		} else {
			$query = $this->prepare_query(
				"SELECT * FROM %i WHERE status IN ({$status_placeholders}) ORDER BY created_at ASC LIMIT %d",
				array_merge(
					array( $this->table_name ),
					$statuses,
					array( max( 1, $limit ) )
				)
			);
		}

		if ( ! is_string( $query ) || '' === $query ) {
			return array();
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$results = $wpdb->get_results( $query, ARRAY_A );

		return is_array( $results ) ? $results : array();
	}

	/**
	 * @param array<string,mixed>|null $result_payload
	 */
	public function update_status(
		int $command_id,
		string $status,
		?array $result_payload = null,
		?string $backend_command_id = null
	): bool {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'update' ) ) {
			return false;
		}

		$update = array(
			'status'     => trim( $status ),
			'updated_at' => current_time( 'mysql' ),
		);
		$formats = array( '%s', '%s' );

		if ( null !== $backend_command_id ) {
			$update['backend_command_id'] = trim( $backend_command_id );
			$formats[] = '%s';
		}

		if ( null !== $result_payload ) {
			$result_json = wp_json_encode( $result_payload );
			$update['result_json'] = is_string( $result_json ) && '' !== $result_json ? $result_json : '{}';
			$formats[] = '%s';
		}

		if ( 'applied' === $status || 'reconciled' === $status ) {
			$update['acknowledged_at'] = current_time( 'mysql' );
			$formats[] = '%s';
		}

		$updated = $wpdb->update(
			$this->table_name,
			$update,
			array( 'id' => max( 1, $command_id ) ),
			$formats,
			array( '%d' )
		);

		return false !== $updated;
	}

	/**
	 * @param array<string,mixed> $response
	 */
	public function record_dispatch_result( int $command_id, array $response ): bool {
		$status = isset( $response['status'] ) && is_string( $response['status'] ) ? trim( $response['status'] ) : 'applied';
		$backend_command_id = isset( $response['command_id'] ) && is_string( $response['command_id'] ) ? $response['command_id'] : null;

		$updated = $this->update_status( $command_id, $status, $response, $backend_command_id );
		if ( ! $updated ) {
			return false;
		}

		return $this->increment_attempts( $command_id );
	}

	/**
	 * @param array<string,mixed>|null $result_payload
	 */
	public function mark_reconciled( int $command_id, ?array $result_payload = null ): bool {
		global $wpdb;

		if ( ! $this->update_status( $command_id, 'reconciled', $result_payload ) ) {
			return false;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'update' ) ) {
			return false;
		}

		$updated = $wpdb->update(
			$this->table_name,
			array(
				'projection_reconciled_at' => current_time( 'mysql' ),
				'updated_at'               => current_time( 'mysql' ),
			),
			array( 'id' => max( 1, $command_id ) ),
			array( '%s', '%s' ),
			array( '%d' )
		);

		return false !== $updated;
	}

	public function record_failure( int $command_id, string $status, string $error_code, string $error_message, bool $increment_attempt = true ): bool {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'update' ) ) {
			return false;
		}

		$updated = $wpdb->update(
			$this->table_name,
			array(
				'status'             => trim( $status ),
				'last_error_code'    => trim( $error_code ),
				'last_error_message' => trim( $error_message ),
				'last_attempted_at'  => current_time( 'mysql' ),
				'updated_at'         => current_time( 'mysql' ),
			),
			array( 'id' => max( 1, $command_id ) ),
			array( '%s', '%s', '%s', '%s', '%s' ),
			array( '%d' )
		);
		if ( false === $updated ) {
			return false;
		}

		if ( ! $increment_attempt ) {
			return true;
		}

		return $this->increment_attempts( $command_id );
	}

	/**
	 * @param object $wpdb
	 */
	private function resolve_insert_id( object $wpdb ): int {
		if ( isset( $wpdb->insert_id ) && is_numeric( $wpdb->insert_id ) ) {
			return max( 1, (int) $wpdb->insert_id );
		}

		return 1;
	}

	private function increment_attempts( int $command_id ): bool {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) || ! method_exists( $wpdb, 'prepare' ) ) {
			return false;
		}

		$query = $this->prepare_query(
			'UPDATE %i SET attempts = attempts + 1, last_attempted_at = %s WHERE id = %d',
			array(
				$this->table_name,
				current_time( 'mysql' ),
				max( 1, $command_id ),
			)
		);
		if ( ! is_string( $query ) || '' === $query ) {
			return false;
		}
		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$result = $wpdb->query( $query );

		return false !== $result;
	}
}
