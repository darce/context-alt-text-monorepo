<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

require_once __DIR__ . '/../repositories/class-sync-state-repository.php';
require_once __DIR__ . '/class-conflict-repository.php';
require_once __DIR__ . '/class-outbox-dispatcher.php';

use AltContext\Sovereign\Repositories\SyncStateRepository;
use Throwable;

use function add_action;
use function apply_filters;
use function array_keys;
use function current_time;
use function do_action;
use function function_exists;
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
	private string $table_name;
	private int $batch_size;

	public function __construct(
		?OutboxDispatcher $dispatcher = null,
		?ConflictRepository $conflict_repository = null,
		?SyncStateRepository $sync_state_repository = null,
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
		$operations = $this->load_pending_operations();
		if ( empty( $operations ) ) {
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
	private function load_pending_operations(): array {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$rows = $wpdb->get_results(
			$wpdb->prepare(
				'SELECT id, tenant_id, operation_type, entity_type, entity_key, idempotency_key, expected_base_version, local_revision, payload, attempts
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
				array( 'id' => $outbox_id )
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
				array( 'id' => $outbox_id )
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
			array( 'id' => $outbox_id )
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
}
