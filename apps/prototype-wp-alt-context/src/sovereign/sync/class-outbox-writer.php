<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

require_once __DIR__ . '/../repositories/class-sync-state-repository.php';
require_once __DIR__ . '/class-outbox-drain.php';

use AltContext\Sovereign\Repositories\SyncStateRepository;

use function current_time;
use function is_numeric;
use function is_object;
use function is_string;
use function max;
use function method_exists;
use function trim;
use function wp_generate_uuid4;
use function wp_json_encode;

class OutboxWriter {
	private string $table_name;
	private SyncStateRepository $sync_state_repository;

	public function __construct( ?string $table_name = null, ?SyncStateRepository $sync_state_repository = null ) {
		global $wpdb;

		$default_table = 'wp_acx_sync_outbox';
		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			$default_table = $wpdb->prefix . 'acx_sync_outbox';
		}

		$this->table_name = $table_name ?? $default_table;
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
	}

	/**
	 * Persist one durable curation operation in the local outbox.
	 *
	 * @param array<string,mixed> $payload
	 */
	public function enqueue(
		string $tenant_id,
		string $operation_type,
		string $entity_type,
		string $entity_key,
		int $expected_base_version,
		int $local_revision,
		array $payload,
		?string $idempotency_key = null
	): int|false {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'insert' ) ) {
			return false;
		}

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			return false;
		}

		$normalized_operation = trim( $operation_type );
		$normalized_entity_type = trim( $entity_type );
		$normalized_entity_key = trim( $entity_key );
		if ( '' === $normalized_operation || '' === $normalized_entity_type || '' === $normalized_entity_key ) {
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
				'tenant_id'              => $normalized_tenant_id,
				'operation_type'         => $normalized_operation,
				'entity_type'            => $normalized_entity_type,
				'entity_key'             => $normalized_entity_key,
				'idempotency_key'        => $key,
				'expected_base_version'  => max( 0, $expected_base_version ),
				'local_revision'         => max( 0, $local_revision ),
				'payload'                => $payload_json,
				'status'                 => 'pending',
				'attempts'               => 0,
				'created_at'             => current_time( 'mysql' ),
			),
			array( '%s', '%s', '%s', '%s', '%s', '%d', '%d', '%s', '%s', '%d', '%s' )
		);

		if ( false === $inserted ) {
			return false;
		}

		$this->sync_state_repository->refresh_curation_metrics( $normalized_tenant_id );
		OutboxDrain::maybe_schedule_drain();

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
