<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

require_once __DIR__ . '/../repositories/class-sync-state-repository.php';
require_once __DIR__ . '/class-conflict-repository.php';
require_once __DIR__ . '/class-cross-plane-sequencer.php';
require_once __DIR__ . '/class-outbox-dispatcher.php';
require_once __DIR__ . '/class-topology-command-repository.php';

use AltContext\Sovereign\Repositories\SyncStateRepository;
use Throwable;

use function add_action;
use function apply_filters;
use function array_keys;
use function current_time;
use function do_action;
use function function_exists;
use function implode;
use function is_array;
use function is_numeric;
use function is_object;
use function is_string;
use function json_decode;
use function max;
use function method_exists;
use function time;
use function trim;
use function wp_clear_scheduled_hook;
use function wp_next_scheduled;
use function wp_schedule_single_event;

class OutboxDrain {
	private const DRAIN_HOOK = 'acx_sync_drain_curation_outbox';
	private const ACTION_SCHEDULER_GROUP = 'acx-sync';
	private const DEFAULT_BATCH_SIZE = 25;
	private const DEFAULT_MAX_ATTEMPTS = 5;

	private OutboxDispatcher $dispatcher;
	private ConflictRepository $conflict_repository;
	private SyncStateRepository $sync_state_repository;
	private CrossPlaneSequencer $sequencer;
	private string $table_name;
	private int $batch_size;

	public function __construct(
		?OutboxDispatcher $dispatcher = null,
		?ConflictRepository $conflict_repository = null,
		?SyncStateRepository $sync_state_repository = null,
		?CrossPlaneSequencer $sequencer = null,
		?string $table_name = null
	) {
		global $wpdb;

		$default_table = 'wp_acx_sync_outbox';
		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			$default_table = $wpdb->prefix . 'acx_sync_outbox';
		}

		$this->dispatcher = $dispatcher ?? new OutboxDispatcher();
		$this->conflict_repository = $conflict_repository ?? new ConflictRepository();
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
		$this->table_name = $table_name ?? $default_table;
		$this->sequencer = $sequencer ?? new CrossPlaneSequencer( new TopologyCommandRepository(), $this->table_name );
		$this->batch_size = max( 1, (int) apply_filters( 'acx_outbox_drain_batch_size', self::DEFAULT_BATCH_SIZE ) );
	}

	public function register(): void {
		add_action( self::DRAIN_HOOK, array( $this, 'drain' ) );

		if ( $this->has_pending_operations() ) {
			self::maybe_schedule_drain();
		}
	}

	public static function maybe_schedule_drain(): void {
		if ( function_exists( 'as_enqueue_async_action' ) && function_exists( 'as_next_scheduled_action' ) ) {
			$group = self::action_scheduler_group();
			$existing = as_next_scheduled_action( self::DRAIN_HOOK, array(), $group );
			if ( false !== $existing && null !== $existing ) {
				return;
			}

			try {
				$action_id = as_enqueue_async_action( self::DRAIN_HOOK, array(), $group );
				if ( is_numeric( $action_id ) && (int) $action_id > 0 ) {
					return;
				}
			} catch ( Throwable $exception ) {
				do_action( 'acx_outbox_action_scheduler_enqueue_failed', $exception );
				// Fall through to WP-Cron when Action Scheduler is available but cannot enqueue.
			}
		}

		if ( false === wp_next_scheduled( self::DRAIN_HOOK, array() ) ) {
			wp_schedule_single_event( time(), self::DRAIN_HOOK, array() );
		}
	}

	public static function clear_scheduled_drain(): void {
		wp_clear_scheduled_hook( self::DRAIN_HOOK, array() );

		if ( function_exists( 'as_unschedule_all_actions' ) ) {
			as_unschedule_all_actions( self::DRAIN_HOOK, array(), self::action_scheduler_group() );
		}
	}

	public function drain(): void {
		$operations = $this->sequencer->filter_ready_outbox_operations( $this->load_pending_operations() );
		if ( empty( $operations ) ) {
			if ( $this->has_pending_operations() ) {
				self::maybe_schedule_drain();
			}
			return;
		}

		$results = $this->dispatcher->dispatch_batch( $operations );
		$processed_tenants = array();
		foreach ( $operations as $index => $operation ) {
			$result = is_array( $results[ $index ] ?? null )
				? $results[ $index ]
				: array(
					'status' => 'failed',
					'error_code' => 'unexpected_response',
					'error_message' => 'Remote curation replay did not return a result for this operation.',
					'retryable' => true,
				);
			$this->apply_result( $operation, $result );

			$tenant_id = trim( (string) ( $operation['tenant_id'] ?? '' ) );
			if ( '' !== $tenant_id ) {
				$processed_tenants[ $tenant_id ] = true;
			}
		}

		foreach ( array_keys( $processed_tenants ) as $tenant_id ) {
			$this->sync_state_repository->refresh_curation_metrics( $tenant_id );
		}

		if ( count( $operations ) >= $this->batch_size && $this->has_pending_operations() ) {
			self::maybe_schedule_drain();
		}
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function find_operations( string $tenant_id, ?string $status = null, int $limit = 50, int $offset = 0 ): array {
		return $this->find_operations_by_status( $tenant_id, $status, $limit, $offset );
	}

	public function count_operations( string $tenant_id, ?string $status = null ): int {
		return $this->count_operations_by_status( $tenant_id, $status );
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function find_failed_operations( string $tenant_id, int $limit = 50, int $offset = 0 ): array {
		return $this->find_operations_by_status( $tenant_id, 'failed', $limit, $offset );
	}

	public function count_failed_operations( string $tenant_id ): int {
		return $this->count_operations_by_status( $tenant_id, 'failed' );
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

	public function retry_failed_operation( int $outbox_id, string $tenant_id ): bool {
		global $wpdb;

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
		self::maybe_schedule_drain();

		return true;
	}

	public function discard_operation( int $outbox_id, string $tenant_id ): bool {
		$operation = $this->find_operation_by_id( $outbox_id, $tenant_id );
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

	public function re_enqueue_with_current_base( int $outbox_id, int $backend_version, string $tenant_id ): bool {
		$updated = $this->update_operation_status(
			$outbox_id,
			$tenant_id,
			'conflict',
			array(
				'status' => 'pending',
				'attempts' => 0,
				'expected_base_version' => max( 0, $backend_version ),
				'last_error_code' => null,
				'last_error_message' => null,
			),
			array( '%s', '%d', '%d', '%s', '%s' )
		);
		if ( ! $updated ) {
			return false;
		}

		$this->sync_state_repository->refresh_curation_metrics( $tenant_id );
		self::maybe_schedule_drain();
		return true;
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	private function load_pending_operations(): array {
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
				$this->batch_size
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
	 * @param array<string,mixed> $operation
	 * @param array<string,mixed> $result
	 */
	private function apply_result( array $operation, array $result ): void {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'update' ) ) {
			return;
		}

		$outbox_id = max( 0, (int) ( $operation['id'] ?? 0 ) );
		if ( $outbox_id <= 0 ) {
			return;
		}

		$attempts = max( 0, (int) ( $operation['attempts'] ?? 0 ) ) + 1;
		$attempted_at = current_time( 'mysql' );
		$status = trim( (string) ( $result['status'] ?? 'failed' ) );

		if ( 'acknowledged' === $status ) {
			$wpdb->update(
				$this->table_name,
				array(
					'status' => 'acknowledged',
					'attempts' => $attempts,
					'last_error_code' => null,
					'last_error_message' => null,
					'acknowledged_version' => max( 0, (int) ( $result['backend_version'] ?? 0 ) ),
					'last_attempted_at' => $attempted_at,
					'acknowledged_at' => $attempted_at,
				),
				array( 'id' => $outbox_id ),
				array( '%s', '%d', '%s', '%s', '%d', '%s', '%s' ),
				array( '%d' )
			);
			return;
		}

		if ( 'conflict' === $status ) {
			$this->conflict_repository->record_conflict( $operation, $result );

			$wpdb->update(
				$this->table_name,
				array(
					'status' => 'conflict',
					'attempts' => $attempts,
					'last_error_code' => $this->normalize_text( $result['conflict_code'] ?? '', 'version_conflict' ),
					'last_error_message' => $this->normalize_text( $result['error_message'] ?? '', 'Remote curation replay conflict.' ),
					'last_attempted_at' => $attempted_at,
				),
				array( 'id' => $outbox_id ),
				array( '%s', '%d', '%s', '%s', '%s' ),
				array( '%d' )
			);
			return;
		}

		$retryable = (bool) ( $result['retryable'] ?? true );
		$max_attempts = $this->resolve_max_attempts();
		$next_status = ( $retryable && $attempts < $max_attempts ) ? 'pending' : 'failed';

		$wpdb->update(
			$this->table_name,
			array(
				'status' => $next_status,
				'attempts' => $attempts,
				'last_error_code' => $this->normalize_text( $result['error_code'] ?? '', 'dispatch_failed' ),
				'last_error_message' => $this->normalize_text( $result['error_message'] ?? '', 'Outbox dispatch failed.' ),
				'last_attempted_at' => $attempted_at,
			),
			array( 'id' => $outbox_id ),
			array( '%s', '%d', '%s', '%s', '%s' ),
			array( '%d' )
		);
	}

	private function has_pending_operations(): bool {
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

	private function resolve_max_attempts(): int {
		return max( 1, (int) apply_filters( 'acx_outbox_max_attempts', self::DEFAULT_MAX_ATTEMPTS ) );
	}

	private function normalize_text( mixed $value, string $default ): string {
		if ( ! is_string( $value ) ) {
			return $default;
		}

		$normalized = trim( $value );
		return '' !== $normalized ? $normalized : $default;
	}

	private static function action_scheduler_group(): string {
		$value = apply_filters( 'acx_outbox_action_scheduler_group', self::ACTION_SCHEDULER_GROUP );
		if ( ! is_string( $value ) ) {
			return self::ACTION_SCHEDULER_GROUP;
		}

		$normalized = trim( $value );
		return '' !== $normalized ? $normalized : self::ACTION_SCHEDULER_GROUP;
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	private function find_operations_by_status( string $tenant_id, ?string $status, int $limit, int $offset ): array {
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

	private function count_operations_by_status( string $tenant_id, ?string $status ): int {
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
