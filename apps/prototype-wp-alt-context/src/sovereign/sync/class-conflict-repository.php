<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

require_once __DIR__ . '/../repositories/trait-prepares-sql-queries.php';

use AltContext\Sovereign\Repositories\PreparesSqlQueries;

use function current_time;
use function is_array;
use function is_numeric;
use function is_object;
use function is_string;
use function json_decode;
use function max;
use function method_exists;
use function trim;
use function wp_json_encode;

class ConflictRepository {
	use PreparesSqlQueries;

	/**
	 * Aggregate conflict code recorded once per mass-divergence cycle instead of a
	 * per-entity curated_* conflict storm (E15-35 Slice 3).
	 */
	public const CONFLICT_CODE_BACKEND_ROSTER_REGRESSED = 'backend_roster_regressed';

	/**
	 * Constant entity coordinates for the aggregate row so upsert semantics keep at
	 * most one open aggregate per tenant.
	 */
	public const AGGREGATE_ENTITY_TYPE = 'roster';
	public const AGGREGATE_ENTITY_KEY  = 'backend_roster';

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
		$backend_proposed_value = $this->normalize_optional_text( $result['backend_proposed_value'] ?? null );
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
				'backend_proposed_value' => $backend_proposed_value,
				'machine_payload' => $machine_payload_json,
				'local_payload' => $local_payload_json,
				'resolution_status' => 'open',
				'created_at' => current_time( 'mysql' ),
			),
			array( '%s', '%s', '%s', '%d', '%d', '%d', '%d', '%s', '%s', '%s', '%s', '%s', '%s' )
		);

		if ( false === $inserted ) {
			return false;
		}

		return $this->resolve_insert_id( $wpdb );
	}

	/**
	 * Persist one projection conflict using idempotent upsert semantics.
	 *
	 * @param array<string,mixed> $machine_payload
	 * @param array<string,mixed> $local_payload
	 */
	public function record_projection_conflict(
		string $tenant_id,
		string $entity_type,
		string $entity_key,
		string $conflict_code,
		int $backend_version,
		int $expected_base_version,
		int $local_revision,
		array $machine_payload,
		array $local_payload
	): int|false {
		global $wpdb;

		$normalized_tenant_id  = trim( $tenant_id );
		$normalized_entity_type = trim( $entity_type );
		$normalized_entity_key = trim( $entity_key );
		$normalized_conflict_code = trim( $conflict_code );

		if (
			'' === $normalized_tenant_id
			|| '' === $normalized_entity_type
			|| '' === $normalized_entity_key
			|| '' === $normalized_conflict_code
			|| ! isset( $wpdb )
			|| ! is_object( $wpdb )
			|| ! method_exists( $wpdb, 'prepare' )
			|| ! method_exists( $wpdb, 'query' )
			|| ! method_exists( $wpdb, 'update' )
		) {
			return false;
		}

		$existing_open_conflict = $this->find_open_projection_conflict(
			$normalized_tenant_id,
			$normalized_entity_type,
			$normalized_entity_key,
			$normalized_conflict_code
		);

		$machine_payload_json = $this->encode_payload_json( $machine_payload );
		$local_payload_json   = $this->encode_payload_json( $local_payload );
		$backend_proposed_value = $this->normalize_optional_text( $machine_payload['proposed_value'] ?? null );
		$created_at           = current_time( 'mysql' );

		if ( is_array( $existing_open_conflict ) ) {
			$updated = $wpdb->update(
				$this->table_name,
				array(
					'expected_base_version' => max( 0, $expected_base_version ),
					'backend_version' => max( 0, $backend_version ),
					'local_revision' => max( 0, $local_revision ),
					'backend_proposed_value' => $backend_proposed_value,
					'machine_payload' => $machine_payload_json,
					'local_payload' => $local_payload_json,
				),
				array( 'id' => max( 0, (int) ( $existing_open_conflict['id'] ?? 0 ) ) ),
				array( '%d', '%d', '%d', '%s', '%s', '%s' ),
				array( '%d' )
			);

			if ( false === $updated ) {
				return false;
			}

			return max( 1, (int) ( $existing_open_conflict['id'] ?? 1 ) );
		}

		$sql = $this->prepare_query(
			"INSERT INTO %i
				(tenant_id, entity_type, entity_key, outbox_id, expected_base_version, backend_version, local_revision, conflict_code, backend_proposed_value, machine_payload, local_payload, resolution_status, created_at)
			VALUES (%s, %s, %s, %d, %d, %d, %d, %s, %s, %s, %s, %s, %s)
			ON DUPLICATE KEY UPDATE
				backend_proposed_value = VALUES(backend_proposed_value),
				machine_payload = VALUES(machine_payload),
				local_payload = VALUES(local_payload),
				backend_version = VALUES(backend_version),
				expected_base_version = VALUES(expected_base_version),
				local_revision = VALUES(local_revision)",
			array(
				$this->table_name,
				$normalized_tenant_id,
				$normalized_entity_type,
				$normalized_entity_key,
				0,
				max( 0, $expected_base_version ),
				max( 0, $backend_version ),
				max( 0, $local_revision ),
				$normalized_conflict_code,
				$backend_proposed_value,
				$machine_payload_json,
				$local_payload_json,
				'open',
				$created_at,
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return false;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$query_result = $wpdb->query( $sql );
		if ( false === $query_result ) {
			return false;
		}

		return $this->resolve_insert_id( $wpdb );
	}

	/**
	 * Record the aggregate backend-roster-regression conflict with cross-cycle dedup:
	 * while an open aggregate already exists for the same backend_version nothing is
	 * written; an open aggregate for another backend_version is refreshed in place via
	 * the projection-conflict upsert, so at most one aggregate row is ever open.
	 *
	 * @param array<string,mixed> $machine_payload Counts + code-partitioned entity map (+ truncation flag).
	 * @param array<string,mixed> $local_payload   Local curated-state summary.
	 */
	public function record_backend_roster_regression( string $tenant_id, int $backend_version, array $machine_payload, array $local_payload ): int|false {
		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			return false;
		}

		$existing_open_aggregate = $this->find_open_backend_roster_regression( $normalized_tenant_id );
		if (
			is_array( $existing_open_aggregate )
			&& max( 0, $backend_version ) === (int) ( $existing_open_aggregate['backend_version'] ?? -1 )
		) {
			return max( 1, (int) ( $existing_open_aggregate['id'] ?? 1 ) );
		}

		return $this->record_projection_conflict(
			$normalized_tenant_id,
			self::AGGREGATE_ENTITY_TYPE,
			self::AGGREGATE_ENTITY_KEY,
			self::CONFLICT_CODE_BACKEND_ROSTER_REGRESSED,
			$backend_version,
			0,
			0,
			$machine_payload,
			$local_payload
		);
	}

	/**
	 * @return array<string,mixed>|null Open aggregate row (id, backend_version, resolution_status) when present.
	 */
	public function find_open_backend_roster_regression( string $tenant_id ): ?array {
		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			return null;
		}

		return $this->find_open_projection_conflict(
			$normalized_tenant_id,
			self::AGGREGATE_ENTITY_TYPE,
			self::AGGREGATE_ENTITY_KEY,
			self::CONFLICT_CODE_BACKEND_ROSTER_REGRESSED
		);
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function find_conflicts_for_tenant( string $tenant_id, string $resolution_status = 'open', int $limit = 50, int $offset = 0 ): array {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		$normalized_status = trim( $resolution_status );
		if (
			'' === $normalized_tenant_id
			|| '' === $normalized_status
			|| ! isset( $wpdb )
			|| ! is_object( $wpdb )
			|| ! method_exists( $wpdb, 'prepare' )
			|| ! method_exists( $wpdb, 'get_results' )
		) {
			return array();
		}

		$sql = $this->prepare_query(
			'SELECT id, tenant_id, entity_type, entity_key, outbox_id, expected_base_version, backend_version, local_revision, conflict_code, backend_proposed_value, machine_payload, local_payload, resolution_status, resolved_at, created_at
			FROM %i
			WHERE tenant_id = %s AND resolution_status = %s
			ORDER BY created_at DESC, id DESC
			LIMIT %d OFFSET %d',
			array(
				$this->table_name,
				$normalized_tenant_id,
				$normalized_status,
				max( 1, $limit ),
				max( 0, $offset ),
			)
		);
		if ( ! is_string( $sql ) || '' === $sql ) {
			return array();
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );
		if ( ! is_array( $rows ) ) {
			return array();
		}

		return array_values(
			array_filter(
				array_map( array( $this, 'decode_payload_fields' ), $rows ),
				'is_array'
			)
		);
	}

	/**
	 * @return array<string,mixed>|null
	 */
	public function find_conflict_by_id( int $conflict_id, string $tenant_id ): ?array {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if (
			$conflict_id <= 0
			|| '' === $normalized_tenant_id
			|| ! isset( $wpdb )
			|| ! is_object( $wpdb )
			|| ! method_exists( $wpdb, 'prepare' )
			|| ! method_exists( $wpdb, 'get_row' )
		) {
			return null;
		}

		$sql = $this->prepare_query(
			'SELECT id, tenant_id, entity_type, entity_key, outbox_id, expected_base_version, backend_version, local_revision, conflict_code, backend_proposed_value, machine_payload, local_payload, resolution_status, resolved_at, created_at
			FROM %i
			WHERE id = %d AND tenant_id = %s
			LIMIT 1',
			array(
				$this->table_name,
				$conflict_id,
				$normalized_tenant_id,
			)
		);
		if ( ! is_string( $sql ) || '' === $sql ) {
			return null;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$row = $wpdb->get_row( $sql, ARRAY_A );
		if ( ! is_array( $row ) ) {
			return null;
		}

		return $this->decode_payload_fields( $row );
	}

	public function mark_resolved( int $conflict_id, string $resolution_status, string $tenant_id ): bool {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		$normalized_status = trim( $resolution_status );
		if (
			$conflict_id <= 0
			|| '' === $normalized_tenant_id
			|| '' === $normalized_status
			|| ! isset( $wpdb )
			|| ! is_object( $wpdb )
			|| ! method_exists( $wpdb, 'update' )
		) {
			return false;
		}

		$updated = $wpdb->update(
			$this->table_name,
			array(
				'resolution_status' => $normalized_status,
				'resolved_at' => current_time( 'mysql' ),
			),
			array(
				'id' => $conflict_id,
				'tenant_id' => $normalized_tenant_id,
				'resolution_status' => 'open',
			),
			array( '%s', '%s' ),
			array( '%d', '%s', '%s' )
		);

		return false !== $updated;
	}

	public function count_conflicts( string $tenant_id, string $resolution_status = 'open' ): int {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		$normalized_status = trim( $resolution_status );
		if (
			'' === $normalized_tenant_id
			|| '' === $normalized_status
			|| ! isset( $wpdb )
			|| ! is_object( $wpdb )
			|| ! method_exists( $wpdb, 'prepare' )
			|| ! method_exists( $wpdb, 'get_var' )
		) {
			return 0;
		}

		$sql = $this->prepare_query(
			'SELECT COUNT(*) FROM %i WHERE tenant_id = %s AND resolution_status = %s',
			array(
				$this->table_name,
				$normalized_tenant_id,
				$normalized_status,
			)
		);
		if ( ! is_string( $sql ) || '' === $sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		return max( 0, (int) $wpdb->get_var( $sql ) );
	}

	/**
	 * @param array<string,mixed> $payload
	 */
	private function encode_payload_json( array $payload ): string {
		$encoded_payload = wp_json_encode( $payload );
		if ( ! is_string( $encoded_payload ) || '' === $encoded_payload ) {
			return '{}';
		}

		return $encoded_payload;
	}

	/**
	 * @param array<string,mixed> $row
	 * @return array<string,mixed>
	 */
	private function decode_payload_fields( array $row ): array {
		foreach ( array( 'machine_payload', 'local_payload' ) as $field ) {
			$value = $row[ $field ] ?? array();
			if ( is_string( $value ) ) {
				$decoded = json_decode( $value, true );
				$row[ $field ] = is_array( $decoded ) ? $decoded : array();
			}
		}

		return $row;
	}

	private function normalize_optional_text( mixed $value ): ?string {
		$normalized = trim( (string) $value );
		return '' !== $normalized ? $normalized : null;
	}

	/**
	 * @return array<string,mixed>|null
	 */
	private function find_open_projection_conflict( string $tenant_id, string $entity_type, string $entity_key, string $conflict_code ): ?array {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_row' ) ) {
			return null;
		}

		$sql = $this->prepare_query(
			'SELECT id, backend_version, resolution_status FROM %i
			WHERE tenant_id = %s
				AND entity_type = %s
				AND entity_key = %s
				AND conflict_code = %s
				AND resolution_status = %s
			ORDER BY id DESC
			LIMIT 1',
			array(
				$this->table_name,
				$tenant_id,
				$entity_type,
				$entity_key,
				$conflict_code,
				'open',
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return null;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$row = $wpdb->get_row( $sql, ARRAY_A );
		return is_array( $row ) ? $row : null;
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
