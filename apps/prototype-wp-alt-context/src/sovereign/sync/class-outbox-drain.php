<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

require_once __DIR__ . '/../repositories/class-sync-state-repository.php';
require_once __DIR__ . '/class-conflict-repository.php';
require_once __DIR__ . '/class-cross-plane-sequencer.php';
require_once __DIR__ . '/class-outbox-dispatcher.php';
require_once __DIR__ . '/class-outbox-query-repository.php';
require_once __DIR__ . '/class-outbox-maintenance-service.php';
require_once __DIR__ . '/../../api/class-tenant-identity.php';
require_once __DIR__ . '/class-topology-command-repository.php';

use AltContext\Api\TenantIdentity;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use Throwable;

use function add_action;
use function apply_filters;
use function array_keys;
use function current_time;
use function do_action;
use function function_exists;
use function is_array;
use function is_object;
use function is_string;
use function max;
use function method_exists;
use function time;
use function trim;
use function wp_clear_scheduled_hook;
use function wp_next_scheduled;
use function wp_schedule_event;
use function wp_schedule_single_event;

class OutboxDrain {
	private const DRAIN_HOOK = 'acx_sync_drain_curation_outbox';
	private const PURGE_HOOK = 'acx_sync_purge_terminal_rows';
	private const ACTION_SCHEDULER_GROUP = 'acx-sync';
	private const DEFAULT_BATCH_SIZE = 25;
	private const DEFAULT_MAX_ATTEMPTS = 5;

	private OutboxDispatcher $dispatcher;
	private ConflictRepository $conflict_repository;
	private SyncStateRepository $sync_state_repository;
	private CrossPlaneSequencer $sequencer;
	private OutboxQueryRepository $query_repository;
	private OutboxMaintenanceService $maintenance_service;
	private string $table_name;
	private int $batch_size;

	public function __construct(
		?OutboxDispatcher $dispatcher = null,
		?ConflictRepository $conflict_repository = null,
		?SyncStateRepository $sync_state_repository = null,
		?CrossPlaneSequencer $sequencer = null,
		?string $table_name = null,
		?OutboxQueryRepository $query_repository = null,
		?OutboxMaintenanceService $maintenance_service = null
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
		$this->query_repository = $query_repository ?? new OutboxQueryRepository( $this->table_name );
		$this->maintenance_service = $maintenance_service ?? new OutboxMaintenanceService(
			$this->query_repository,
			$this->sync_state_repository,
			$this->table_name
		);
		$this->batch_size = max( 1, (int) apply_filters( 'acx_outbox_drain_batch_size', self::DEFAULT_BATCH_SIZE ) );
	}

	public function register(): void {
		add_action( self::DRAIN_HOOK, array( $this, 'drain' ) );
		add_action( self::PURGE_HOOK, array( $this, 'purge_terminal_rows' ) );

		if ( false === wp_next_scheduled( self::PURGE_HOOK, array() ) ) {
			$hour_seconds = defined( 'HOUR_IN_SECONDS' ) ? (int) HOUR_IN_SECONDS : 3600;
			wp_schedule_event( time() + $hour_seconds, 'daily', self::PURGE_HOOK, array() );
		}

		if ( $this->query_repository->has_pending_operations() ) {
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
				if ( (int) $action_id > 0 ) {
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

	public static function clear_scheduled_purge(): void {
		wp_clear_scheduled_hook( self::PURGE_HOOK, array() );
	}

	public function drain(): void {
		$operations = $this->sequencer->filter_ready_outbox_operations(
			$this->query_repository->load_pending_operations( $this->batch_size )
		);
		if ( empty( $operations ) ) {
			if ( $this->query_repository->has_pending_operations() ) {
				self::maybe_schedule_drain();
			}
			return;
		}

		$processed_tenants = $this->process_operation_batch( $operations );
		$tenant_ids = array_keys( $processed_tenants );
		$this->refresh_curation_metrics_for_tenants( $tenant_ids );
		$this->purge_terminal_rows_for_tenants( $tenant_ids );

		if ( count( $operations ) >= $this->batch_size && $this->query_repository->has_pending_operations() ) {
			self::maybe_schedule_drain();
		}
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function find_operations( string $tenant_id, ?string $status = null, int $limit = 50, int $offset = 0 ): array {
		return $this->query_repository->find_operations_by_status( $tenant_id, $status, $limit, $offset );
	}

	public function count_operations( string $tenant_id, ?string $status = null ): int {
		return $this->query_repository->count_operations_by_status( $tenant_id, $status );
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function find_failed_operations( string $tenant_id, int $limit = 50, int $offset = 0 ): array {
		return $this->query_repository->find_operations_by_status( $tenant_id, 'failed', $limit, $offset );
	}

	public function count_failed_operations( string $tenant_id ): int {
		return $this->query_repository->count_operations_by_status( $tenant_id, 'failed' );
	}

	/**
	 * @param int[] $outbox_ids
	 * @return array<int,array<string,mixed>>
	 */
	public function find_operations_by_ids( array $outbox_ids, string $tenant_id ): array {
		return $this->query_repository->find_operations_by_ids( $outbox_ids, $tenant_id );
	}

	/**
	 * @return array<string,mixed>|null
	 */
	public function find_operation_by_id( int $outbox_id, string $tenant_id ): ?array {
		return $this->query_repository->find_operation_by_id( $outbox_id, $tenant_id );
	}

	public function retry_failed_operation( int $outbox_id, string $tenant_id ): bool {
		return $this->maintenance_service->retry_failed_operation( $outbox_id, $tenant_id );
	}

	public function discard_operation( int $outbox_id, string $tenant_id ): bool {
		return $this->maintenance_service->discard_operation( $outbox_id, $tenant_id );
	}

	public function re_enqueue_with_current_base( int $outbox_id, int $backend_version, string $tenant_id, ?string $merged_value = null ): bool {
		return $this->maintenance_service->re_enqueue_with_current_base( $outbox_id, $backend_version, $tenant_id, $merged_value );
	}

	public function purge_terminal_rows(): void {
		$tenant_ids = $this->maintenance_service->list_terminal_purge_tenant_ids();
		if ( empty( $tenant_ids ) ) {
			$tenant = TenantIdentity::resolve();
			$tenant_id = trim( (string) ( $tenant['value'] ?? '' ) );
			if ( '' === $tenant_id ) {
				return;
			}

			$tenant_ids = array( $tenant_id );
		}

		$this->purge_terminal_rows_for_tenants( $tenant_ids );
	}

	/**
	 * @param array<int,array<string,mixed>> $operations
	 * @return array<string,true>
	 */
	private function process_operation_batch( array $operations ): array {
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

		return $processed_tenants;
	}

	/**
	 * @param array<int,string> $tenant_ids
	 */
	private function refresh_curation_metrics_for_tenants( array $tenant_ids ): void {
		foreach ( $tenant_ids as $tenant_id ) {
			$this->sync_state_repository->refresh_curation_metrics( $tenant_id );
		}
	}

	/**
	 * @param array<int,string> $tenant_ids
	 */
	private function purge_terminal_rows_for_tenants( array $tenant_ids ): void {
		foreach ( $tenant_ids as $tenant_id ) {
			$normalized_tenant_id = trim( $tenant_id );
			if ( '' === $normalized_tenant_id ) {
				continue;
			}

			$this->maintenance_service->purge_terminal_rows( $normalized_tenant_id );
		}
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
}
