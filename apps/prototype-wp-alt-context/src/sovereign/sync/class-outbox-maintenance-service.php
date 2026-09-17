<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

require_once __DIR__ . '/../repositories/class-sync-state-repository.php';
require_once __DIR__ . '/class-conflict-resolution-status.php';
require_once __DIR__ . '/class-outbox-status.php';
require_once __DIR__ . '/../../support/trait-runs-transactional.php';

use AltContext\Support\RunsTransactional;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use DateTimeImmutable;
use DateTimeZone;

use function apply_filters;
use function array_fill;
use function array_merge;
use function array_unique;
use function array_values;
use function current_time;
use function gmdate;
use function implode;
use function intdiv;
use function is_array;
use function is_finite;
use function is_float;
use function is_int;
use function is_numeric;
use function is_object;
use function is_string;
use function json_decode;
use function max;
use function method_exists;
use function min;
use function sprintf;
use function trim;
use function wp_json_encode;

class OutboxMaintenanceService {
	use RunsTransactional;

	private const DEFAULT_PURGE_BATCH_SIZE = 50;
	private const DEFAULT_ACKNOWLEDGED_RETENTION_DAYS = 14;
	private const DEFAULT_RESOLVED_CONFLICT_RETENTION_DAYS = 14;
	private const DEFAULT_FAILED_RETENTION_DAYS = 7;
	private const DEFAULT_MAX_AUTO_ATTEMPTS = 3;
	private const DEFAULT_AUTO_RETRY_BACKOFF_BASE_SECONDS = 60;
	private const DEFAULT_AUTO_RETRY_BACKOFF_CAP_SECONDS = 3600;
	private const MAX_PURGE_BATCH_ITERATIONS = 20;
	private const AUTO_ATTEMPT_PAYLOAD_KEY = 'acx_auto_attempts';
	private const DEAD_LETTER_REASON_AUTO_RETRY_EXHAUSTED = 'auto_retry_exhausted';
	// E15-35 Slice 2 bulk-requeue tunables (filterable, fail-safe floored at 1).
	private const DEFAULT_BULK_RETRY_MAX_ROWS = 1000;
	private const DEFAULT_BULK_RETRY_PACING_STRIDE_SECONDS = 60;

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
	 * @return array{outbox:int,conflicts:int,retried:int,dead_lettered:int,purged_failed:int,skipped_concurrent:int}|false
	 */
	public function purge_terminal_rows( string $tenant_id ): array|false {
		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			return false;
		}

		$result = $this->run_transactional(
			function () use ( $normalized_tenant_id ): array {
				$reclaim = $this->reclaim_retryable_failed_batch( $normalized_tenant_id );
				$purged_failed = $this->purge_failed_non_retryable_batch( $normalized_tenant_id );
				$purged_acknowledged = $this->purge_acknowledged_outbox_batch( $normalized_tenant_id );

				return array(
					// Keep the established aggregate meaning: all acknowledged and failed
					// outbox deletions. The failed-only breakdown remains available below.
					'outbox' => $purged_acknowledged + $purged_failed,
					'conflicts' => $this->purge_resolved_conflicts_batch( $normalized_tenant_id ),
					'retried' => $reclaim['retried'],
					'dead_lettered' => $reclaim['dead_lettered'],
					'purged_failed' => $purged_failed,
					'skipped_concurrent' => $reclaim['skipped_concurrent'],
				);
			}
		);

		if ( is_wp_error( $result ) ) {
			return false;
		}

		if ( ! is_array( $result ) ) {
			return false;
		}

		if ( ( $result['retried'] + $result['dead_lettered'] + $result['purged_failed'] ) > 0 ) {
			$this->sync_state_repository->refresh_curation_metrics( $normalized_tenant_id );
		}
		if ( $result['retried'] > 0 ) {
			OutboxDrain::maybe_schedule_drain();
		}

		return $result;
	}

	/**
	 * OBS-05 counters for spa-deadletter /sync/health.
	 *
	 * `failed` is FAILED rows still eligible for automatic retry.
	 * `dead_lettered` is FAILED rows with a terminal retryability decision
	 * (auto_retry_exhausted, missing error code, or an explicitly false retryable flag).
	 * Both remain operator-visible/retryable.
	 * Age is created_at of the oldest pending or failed row; 0 when the tenant has none.
	 * Returns false when the adapter is unavailable so callers do not fabricate zeros.
	 *
	 * @return array{pending:int,failed:int,dead_lettered:int,oldest_age_seconds:int}|false
	 */
	public function get_health_counters( string $tenant_id ): array|false {
		$empty = array(
			'pending' => 0,
			'failed' => 0,
			'dead_lettered' => 0,
			'oldest_age_seconds' => 0,
		);
		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			return $empty;
		}

		global $wpdb;

		if (
			! isset( $wpdb )
			|| ! is_object( $wpdb )
			|| ! method_exists( $wpdb, 'prepare' )
			|| ! method_exists( $wpdb, 'get_results' )
		) {
			return false;
		}

		$health_sql =
			'SELECT
				SUM(CASE WHEN status = %s THEN 1 ELSE 0 END) AS pending,
				SUM(CASE WHEN status = %s AND (last_error_retryable IS NULL OR last_error_retryable = 1) AND last_error_code <> %s THEN 1 ELSE 0 END) AS failed,
				SUM(CASE WHEN status = %s AND ((last_error_retryable IS NOT NULL AND last_error_retryable <> 1) OR last_error_code IS NULL OR last_error_code = %s) THEN 1 ELSE 0 END) AS dead_lettered,
				MIN(created_at) AS oldest_created_at
			FROM %i
			WHERE tenant_id = %s AND status IN (%s, %s)';
		$health_args = array(
			OutboxStatus::PENDING,
			OutboxStatus::FAILED,
			self::DEAD_LETTER_REASON_AUTO_RETRY_EXHAUSTED,
			OutboxStatus::FAILED,
			self::DEAD_LETTER_REASON_AUTO_RETRY_EXHAUSTED,
			$this->table_name,
			$normalized_tenant_id,
			OutboxStatus::PENDING,
			OutboxStatus::FAILED,
		);
		$rows = $wpdb->get_results(
			$wpdb->prepare( $health_sql, ...$health_args ),
			ARRAY_A
		);
		if ( ! is_array( $rows ) || ! isset( $rows[0] ) || ! is_array( $rows[0] ) ) {
			return false;
		}

		$aggregate = $rows[0];
		$oldest_created_at = trim( (string) ( $aggregate['oldest_created_at'] ?? '' ) );

		return array(
			'pending' => max( 0, (int) ( $aggregate['pending'] ?? 0 ) ),
			'failed' => max( 0, (int) ( $aggregate['failed'] ?? 0 ) ),
			'dead_lettered' => max( 0, (int) ( $aggregate['dead_lettered'] ?? 0 ) ),
			'oldest_age_seconds' => '' === $oldest_created_at
				? 0
				: $this->row_age_seconds( array( 'created_at' => $oldest_created_at ) ),
		);
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

	public function purge_failed_non_retryable_batch( string $tenant_id ): int {
		$batch_size = max( 1, (int) apply_filters( 'acx_sync_purge_batch_size', self::DEFAULT_PURGE_BATCH_SIZE ) );
		$total_deleted = 0;
		$after_id = 0;

		for ( $iteration = 0; $iteration < self::MAX_PURGE_BATCH_ITERATIONS; $iteration++ ) {
			$batch = $this->purge_failed_non_retryable_batch_once( $tenant_id, $batch_size, $after_id );
			$total_deleted += $batch['deleted'];
			$after_id = $batch['after_id'];
			if ( $batch['scanned'] < $batch_size ) {
				break;
			}
			if ( $after_id <= 0 ) {
				break;
			}
		}

		return $total_deleted;
	}

	/**
	 * @return array{retried:int,dead_lettered:int,skipped_concurrent:int}
	 */
	private function reclaim_retryable_failed_batch( string $tenant_id ): array {
		$batch_size = max( 1, (int) apply_filters( 'acx_sync_purge_batch_size', self::DEFAULT_PURGE_BATCH_SIZE ) );
		$retried = 0;
		$dead_lettered = 0;
		$skipped_concurrent = 0;
		$after_id = 0;

		for ( $iteration = 0; $iteration < self::MAX_PURGE_BATCH_ITERATIONS; $iteration++ ) {
			$candidates = $this->load_failed_reclaim_candidates( $tenant_id, $batch_size, $after_id );
			if ( array() === $candidates ) {
				break;
			}

			$last = $candidates[ count( $candidates ) - 1 ];
			$after_id = (int) ( $last['id'] ?? $after_id );

			foreach ( $candidates as $candidate ) {
				if ( $this->is_terminal_failed_row( $candidate ) ) {
					continue;
				}

				$outcome = $this->reclaim_retryable_failed_row( $tenant_id, $candidate );
				if ( 'retried' === $outcome ) {
					++$retried;
				} elseif ( 'dead_lettered' === $outcome ) {
					++$dead_lettered;
				} elseif ( 'skipped_concurrent' === $outcome ) {
					++$skipped_concurrent;
				}
			}

			if ( count( $candidates ) < $batch_size ) {
				break;
			}
		}

		return array(
			'retried' => $retried,
			'dead_lettered' => $dead_lettered,
			'skipped_concurrent' => $skipped_concurrent,
		);
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

	/**
	 * @return array{deleted:int,scanned:int,after_id:int}
	 */
	private function purge_failed_non_retryable_batch_once( string $tenant_id, int $batch_size, int $after_id ): array {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if (
			'' === $normalized_tenant_id
			|| ! isset( $wpdb )
			|| ! is_object( $wpdb )
			|| ! method_exists( $wpdb, 'prepare' )
			|| ! method_exists( $wpdb, 'get_results' )
			|| ! method_exists( $wpdb, 'delete' )
		) {
			return array(
				'deleted' => 0,
				'scanned' => 0,
				'after_id' => $after_id,
			);
		}

		$retention_days = $this->resolve_positive_int_tunable( 'acx_sync_purge_failed_days', self::DEFAULT_FAILED_RETENTION_DAYS );
		$day_seconds = defined( 'DAY_IN_SECONDS' ) ? (int) DAY_IN_SECONDS : 86400;
		$cutoff_epoch = (int) current_time( 'timestamp' ) - ( $retention_days * $day_seconds );
		$prepare_args = array(
			$this->table_name,
			$normalized_tenant_id,
			OutboxStatus::FAILED,
			max( 0, $after_id ),
			self::DEAD_LETTER_REASON_AUTO_RETRY_EXHAUSTED,
			max( 1, $batch_size ),
		);

		$rows = $wpdb->get_results(
			$wpdb->prepare(
				// Keep auto_retry_exhausted out of this purge selector. An exhausted row is
				// marked during the reclaim pass above and must remain visible to the operator;
				// it must not disappear in that same maintenance run merely because its original
				// failure timestamp is old.
				'SELECT id, first_failed_at, last_attempted_at, created_at, last_error_code, last_error_retryable, attempts FROM %i WHERE tenant_id = %s AND status = %s AND id > %d AND (last_error_retryable IS NULL OR last_error_retryable <> 1 OR last_error_code IS NULL) AND (last_error_code IS NULL OR last_error_code <> %s) ORDER BY id ASC LIMIT %d',
				...$prepare_args
			),
			ARRAY_A
		);
		if ( ! is_array( $rows ) ) {
			return array(
				'deleted' => 0,
				'scanned' => 0,
				'after_id' => $after_id,
			);
		}

		$deleted = 0;
		$scanned = 0;
		$last_id = $after_id;
		foreach ( $rows as $row ) {
			if ( ! is_array( $row ) ) {
				continue;
			}

			++$scanned;
			$last_id = max( $last_id, (int) ( $row['id'] ?? 0 ) );
			if (
				! $this->is_terminal_failed_row( $row )
				|| self::DEAD_LETTER_REASON_AUTO_RETRY_EXHAUSTED === (string) ( $row['last_error_code'] ?? '' )
			) {
				continue;
			}
			if ( ! $this->failed_row_is_past_retention( $row, $cutoff_epoch ) ) {
				continue;
			}

			$outbox_id = (int) ( $row['id'] ?? 0 );
			if ( $outbox_id <= 0 ) {
				continue;
			}

			$removed = $wpdb->delete(
				$this->table_name,
				array(
					'id' => $outbox_id,
					'tenant_id' => $normalized_tenant_id,
					'status' => OutboxStatus::FAILED,
					'last_attempted_at' => $this->fingerprint_nullable_value( $row['last_attempted_at'] ?? null ),
					'last_error_code' => $this->fingerprint_nullable_value( $row['last_error_code'] ?? null ),
					'attempts' => max( 0, (int) ( $row['attempts'] ?? 0 ) ),
					'first_failed_at' => $this->fingerprint_nullable_value( $row['first_failed_at'] ?? null ),
					'last_error_retryable' => $this->fingerprint_nullable_int( $row['last_error_retryable'] ?? null ),
				),
				array( '%d', '%s', '%s', '%s', '%s', '%d', '%s', '%d' )
			);
			if ( is_numeric( $removed ) && (int) $removed > 0 ) {
				++$deleted;
			}
		}

		return array(
			'deleted' => $deleted,
			'scanned' => $scanned,
			'after_id' => $last_id,
		);
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	private function load_failed_reclaim_candidates( string $tenant_id, int $limit, int $after_id = 0 ): array {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if (
			'' === $normalized_tenant_id
			|| ! isset( $wpdb )
			|| ! is_object( $wpdb )
			|| ! method_exists( $wpdb, 'prepare' )
			|| ! method_exists( $wpdb, 'get_results' )
		) {
			return array();
		}

		$rows = $wpdb->get_results(
			$wpdb->prepare(
				'SELECT id, attempts, last_error_code, last_error_message, last_error_retryable, first_failed_at, last_attempted_at, created_at, payload FROM %i WHERE tenant_id = %s AND status = %s AND id > %d AND (last_error_retryable IS NULL OR last_error_retryable = 1) AND last_error_code <> %s ORDER BY id ASC LIMIT %d',
				$this->table_name,
				$normalized_tenant_id,
				OutboxStatus::FAILED,
				max( 0, $after_id ),
				self::DEAD_LETTER_REASON_AUTO_RETRY_EXHAUSTED,
				max( 1, $limit )
			),
			ARRAY_A
		);
		if ( ! is_array( $rows ) ) {
			return array();
		}

		$candidates = array();
		foreach ( $rows as $row ) {
			if ( is_array( $row ) ) {
				$candidates[] = $row;
			}
		}

		return $candidates;
	}

	/**
	 * @param array<string,mixed> $row
	 */
	private function reclaim_retryable_failed_row( string $tenant_id, array $row ): string {
		$outbox_id = (int) ( $row['id'] ?? 0 );
		if ( $outbox_id <= 0 ) {
			return 'skipped';
		}

		$payload = $this->decode_payload( $row['payload'] ?? null );
		$auto_attempts = max( 0, (int) ( $payload[ self::AUTO_ATTEMPT_PAYLOAD_KEY ] ?? 0 ) );
		$max_auto_attempts = $this->resolve_positive_int_tunable( 'acx_sync_max_auto_attempts', self::DEFAULT_MAX_AUTO_ATTEMPTS );

		if ( $auto_attempts >= $max_auto_attempts ) {
			$updated = $this->dead_letter_failed_row( $outbox_id, $tenant_id, $row, $auto_attempts );
			if ( false === $updated ) {
				return 'skipped';
			}

			return $updated > 0 ? 'dead_lettered' : 'skipped_concurrent';
		}

		$next_auto_attempts = $auto_attempts + 1;
		$payload[ self::AUTO_ATTEMPT_PAYLOAD_KEY ] = $next_auto_attempts;
		$payload_json = wp_json_encode( $payload );
		if ( ! is_string( $payload_json ) || '' === $payload_json ) {
			$payload_json = '{}';
		}

		$updated = $this->update_operation_status(
			$outbox_id,
			$tenant_id,
			OutboxStatus::FAILED,
			array(
				'status' => OutboxStatus::PENDING,
				'attempts' => 0,
				'payload' => $payload_json,
				'last_error_code' => null,
				'last_error_message' => null,
				'last_error_retryable' => null,
				'last_attempted_at' => null,
				'first_failed_at' => null,
				'next_attempt_at' => $this->compute_auto_retry_next_attempt_at( $next_auto_attempts ),
			),
			array( '%s', '%d', '%s', '%s', '%s', '%s', '%s', '%s', '%s' ),
			$this->failed_row_fingerprint( $row )
		);
		if ( false === $updated ) {
			return 'skipped';
		}

		return $updated > 0 ? 'retried' : 'skipped_concurrent';
	}

	/**
	 * Exhausted automatic retries stay FAILED (contract dead-letter). DISCARDED is
	 * reserved for the operator discard transition.
	 *
	 * @param array<string,mixed> $row
	 * @return int|false Affected rows, or false on SQL failure.
	 */
	private function dead_letter_failed_row( int $outbox_id, string $tenant_id, array $row, int $auto_attempts ): int|false {
		$age_seconds = $this->row_age_seconds( $row );
		$max_auto_attempts = $this->resolve_positive_int_tunable( 'acx_sync_max_auto_attempts', self::DEFAULT_MAX_AUTO_ATTEMPTS );
		$message = sprintf(
			'Dead-lettered after %d auto-retry attempts; age %d seconds.',
			$max_auto_attempts,
			$age_seconds
		);
		$exhausted_at = gmdate( 'Y-m-d H:i:s', (int) current_time( 'timestamp' ) );
		$attempt_count = max( (int) ( $row['attempts'] ?? 0 ), $auto_attempts, $max_auto_attempts );

		return $this->update_operation_status(
			$outbox_id,
			$tenant_id,
			OutboxStatus::FAILED,
			array(
				'last_error_code' => self::DEAD_LETTER_REASON_AUTO_RETRY_EXHAUSTED,
				'last_error_message' => $message,
				'attempts' => $attempt_count,
				'last_attempted_at' => $exhausted_at,
				'next_attempt_at' => null,
			),
			array( '%s', '%s', '%d', '%s', '%s' ),
			$this->failed_row_fingerprint( $row )
		);
	}

	private function compute_auto_retry_next_attempt_at( int $auto_attempts ): string {
		$base = self::DEFAULT_AUTO_RETRY_BACKOFF_BASE_SECONDS;
		$cap = self::DEFAULT_AUTO_RETRY_BACKOFF_CAP_SECONDS;
		$attempt = max( 1, $auto_attempts );
		$delay = max( 1, (int) min( (float) $base * (float) ( 2 ** ( $attempt - 1 ) ), (float) $cap ) );

		return gmdate( 'Y-m-d H:i:s', (int) current_time( 'timestamp' ) + $delay );
	}

	/**
	 * @param array<string,mixed> $row
	 */
	private function is_terminal_failed_row( array $row ): bool {
		$retryable = $row['last_error_retryable'] ?? null;
		$error_code = $row['last_error_code'] ?? null;

		return ( null !== $retryable && 1 !== (int) $retryable )
			|| ! is_string( $error_code )
			|| self::DEAD_LETTER_REASON_AUTO_RETRY_EXHAUSTED === $error_code;
	}

	/**
	 * @param array<string,mixed> $row
	 */
	private function failed_row_is_past_retention( array $row, int $cutoff_epoch ): bool {
		$stamp = trim( (string) ( $row['first_failed_at'] ?? '' ) );
		if ( '' === $stamp ) {
			$stamp = trim( (string) ( $row['last_attempted_at'] ?? '' ) );
		}
		if ( '' === $stamp ) {
			$stamp = trim( (string) ( $row['created_at'] ?? '' ) );
		}

		$epoch = $this->wp_datetime_to_epoch( $stamp );
		if ( null === $epoch ) {
			return false;
		}

		return $epoch < $cutoff_epoch;
	}

	/**
	 * @param mixed $payload
	 * @return array<string,mixed>
	 */
	private function decode_payload( mixed $payload ): array {
		if ( is_array( $payload ) ) {
			return $payload;
		}

		if ( ! is_string( $payload ) || '' === $payload ) {
			return array();
		}

		$decoded = json_decode( $payload, true );
		return is_array( $decoded ) ? $decoded : array();
	}

	/**
	 * Remove the automatic retry budget before an operator re-enqueues a row.
	 *
	 * @param mixed $payload
	 */
	private function reset_auto_attempt_payload( mixed $payload ): string {
		$decoded_payload = $this->decode_payload( $payload );
		unset( $decoded_payload[ self::AUTO_ATTEMPT_PAYLOAD_KEY ] );

		$payload_json = wp_json_encode( $decoded_payload );
		return is_string( $payload_json ) && '' !== $payload_json ? $payload_json : '{}';
	}

	/**
	 * @param array<string,mixed> $row
	 */
	private function row_age_seconds( array $row ): int {
		$stamp = trim( (string) ( $row['first_failed_at'] ?? '' ) );
		if ( '' === $stamp ) {
			$stamp = trim( (string) ( $row['last_attempted_at'] ?? '' ) );
		}
		if ( '' === $stamp ) {
			$stamp = trim( (string) ( $row['created_at'] ?? '' ) );
		}

		$epoch = $this->wp_datetime_to_epoch( $stamp );
		if ( null === $epoch ) {
			return 0;
		}

		return max( 0, (int) current_time( 'timestamp' ) - $epoch );
	}

	private function wp_datetime_to_epoch( string $datetime ): ?int {
		$normalized = trim( $datetime );
		if ( '' === $normalized ) {
			return null;
		}

		$parsed = DateTimeImmutable::createFromFormat( 'Y-m-d H:i:s', $normalized, new DateTimeZone( 'UTC' ) );
		return false !== $parsed ? $parsed->getTimestamp() : null;
	}

	public function retry_failed_operation( int $outbox_id, string $tenant_id ): bool {
		$operation = $this->query_repository->find_operation_by_id( $outbox_id, $tenant_id );
		if ( ! is_array( $operation ) || OutboxStatus::FAILED !== ( $operation['status'] ?? null ) ) {
			return false;
		}

		$payload_json = $this->reset_auto_attempt_payload( $operation['payload'] ?? null );

		$updated = $this->update_operation_status(
			$outbox_id,
			$tenant_id,
			OutboxStatus::FAILED,
			array(
				'status' => OutboxStatus::PENDING,
				'attempts' => 0,
				'payload' => $payload_json,
				'last_error_code' => null,
				'last_error_message' => null,
				'last_error_retryable' => null,
				'last_attempted_at' => null,
				// E15-35: a requeued op starts a fresh retry window — stale first_failed_at
				// would instantly re-terminate it on the next retryable failure.
				'first_failed_at' => null,
				'next_attempt_at' => null,
			),
			array( '%s', '%d', '%s', '%s', '%s', '%s', '%s', '%s', '%s' ),
			$this->failed_row_fingerprint( $operation )
		);
		if ( ! $updated ) {
			return false;
		}

		$this->sync_state_repository->refresh_curation_metrics( $tenant_id );
		OutboxDrain::maybe_schedule_drain();

		return true;
	}

	/**
	 * Requeue every failed push for a tenant in one guarded action (E15-35 Slice 2).
	 *
	 * Every selected row is reset failed -> pending with attempts 0, cleared error fields,
	 * a fresh retry window (first_failed_at NULL — see retry_failed_operation), and the
	 * auto-attempt marker removed in SQL. The single set-based UPDATE is CAS-guarded by
	 * tenant, status, and the selected id set, so rows that transitioned since the id read
	 * are not requeued.
	 *
	 * Paced requeue (PA-05): rather than making every row due immediately, the first
	 * drain-batch-sized chunk gets next_attempt_at NULL and each later chunk is deferred
	 * by one further pacing stride, so a single drain cycle dispatches strictly fewer
	 * than N rows against a possibly still-fragile backend. Slice-1 backoff then paces
	 * subsequent retries.
	 *
	 * @return int|false Number of rows requeued, or false when the tenant id is invalid
	 *                   or the database adapter is unavailable.
	 */
	public function retry_failed_operations_bulk( string $tenant_id ): int|false {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if (
			'' === $normalized_tenant_id
			|| ! isset( $wpdb )
			|| ! is_object( $wpdb )
			|| ! method_exists( $wpdb, 'prepare' )
			|| ! method_exists( $wpdb, 'query' )
		) {
			return false;
		}

		$max_rows = $this->resolve_positive_int_tunable( 'acx_outbox_bulk_retry_max_rows', self::DEFAULT_BULK_RETRY_MAX_ROWS );
		$chunk_size = max( 1, (int) apply_filters( 'acx_outbox_drain_batch_size', OutboxDrain::DEFAULT_BATCH_SIZE ) );
		$stride_seconds = $this->resolve_positive_int_tunable( 'acx_outbox_bulk_retry_pacing_stride_seconds', self::DEFAULT_BULK_RETRY_PACING_STRIDE_SECONDS );

		$outbox_ids = $this->query_repository->find_failed_operation_ids( $normalized_tenant_id, $max_rows );
		if ( array() === $outbox_ids ) {
			return 0;
		}

		$normalized_ids = array_values(
			array_unique(
				array_filter(
					array_map( 'intval', $outbox_ids ),
					static fn( int $outbox_id ): bool => $outbox_id > 0
				)
			)
		);
		if ( array() === $normalized_ids ) {
			return 0;
		}

		$now_timestamp = (int) current_time( 'timestamp' );
		$next_attempt_at_values = array_map(
			static function ( int $index ) use ( $chunk_size, $now_timestamp, $stride_seconds ): ?string {
				$chunk_index = intdiv( $index, $chunk_size );
				return 0 === $chunk_index
					? null
					: gmdate( 'Y-m-d H:i:s', $now_timestamp + ( $chunk_index * $stride_seconds ) );
			},
			array_keys( $normalized_ids )
		);
		$case_fragments = array_map(
			static function ( int $outbox_id, ?string $next_attempt_at ): string {
				return null === $next_attempt_at ? 'WHEN %d THEN NULL' : 'WHEN %d THEN %s';
			},
			$normalized_ids,
			$next_attempt_at_values
		);
		$case_argument_parts = array_map(
			static function ( int $outbox_id, ?string $next_attempt_at ): array {
				return null === $next_attempt_at
					? array( $outbox_id )
					: array( $outbox_id, $next_attempt_at );
			},
			$normalized_ids,
			$next_attempt_at_values
		);
		$case_args = array_merge( ...$case_argument_parts );
		$id_placeholders = implode( ', ', array_fill( 0, count( $normalized_ids ), '%d' ) );
		$bulk_sql =
			'UPDATE %i SET status = %s,
				attempts = %d,
				payload = JSON_REMOVE(payload, %s),
				last_error_code = NULL,
				last_error_message = NULL,
				last_error_retryable = NULL,
				last_attempted_at = NULL,
				first_failed_at = NULL,
				next_attempt_at = CASE id ' . implode( ' ', $case_fragments ) . ' ELSE next_attempt_at END
			WHERE tenant_id = %s
				AND status = %s
				AND id IN (' . $id_placeholders . ')';
		$bulk_args = array_merge(
			array( $this->table_name, OutboxStatus::PENDING, 0, '$.' . self::AUTO_ATTEMPT_PAYLOAD_KEY ),
			$case_args,
			array( $normalized_tenant_id, OutboxStatus::FAILED ),
			$normalized_ids
		);
		$updated = $wpdb->query( $wpdb->prepare( $bulk_sql, ...$bulk_args ) );
		if ( false === $updated ) {
			return false;
		}
		$requeued = is_int( $updated ) ? max( 0, $updated ) : 0;

		if ( $requeued > 0 ) {
			$this->sync_state_repository->refresh_curation_metrics( $normalized_tenant_id );
			OutboxDrain::maybe_schedule_drain();
		}

		return $requeued;
	}

	/**
	 * Fail-safe tunable read (rg-008), mirroring OutboxDrain::resolve_positive_int_tunable:
	 * a filter returning a non-finite, non-numeric, or non-positive value falls back to
	 * the default — a bad filter can never shrink the bulk sweep or collapse the pacing
	 * stride. Duplicated locally because the drain's validator is private to that class.
	 */
	private function resolve_positive_int_tunable( string $filter_name, int $default ): int {
		$value = apply_filters( $filter_name, $default );

		if ( is_int( $value ) ) {
			return $value > 0 ? $value : $default;
		}

		if ( is_float( $value ) ) {
			return is_finite( $value ) && $value > 0.0 ? max( 1, (int) $value ) : $default;
		}

		if ( is_string( $value ) && is_numeric( $value ) ) {
			$numeric = (float) $value;
			return is_finite( $numeric ) && $numeric > 0.0 ? max( 1, (int) $numeric ) : $default;
		}

		return $default;
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
		$operation = $this->query_repository->find_operation_by_id( $outbox_id, $tenant_id );
		if ( ! is_array( $operation ) ) {
			return false;
		}

		$data = array(
			'status' => OutboxStatus::PENDING,
			'attempts' => 0,
			'expected_base_version' => max( 0, $backend_version ),
			'last_error_code' => null,
			'last_error_message' => null,
			'last_error_retryable' => null,
			// E15-35: re-enqueue starts a fresh retry window (see retry_failed_operation).
			'first_failed_at' => null,
			'next_attempt_at' => null,
		);
		$format = array( '%s', '%d', '%d', '%s', '%s', '%s', '%s', '%s', '%s' );
		$payload = $this->decode_payload( $operation['payload'] ?? null );

		$normalized_merged_value = is_string( $merged_value ) ? trim( $merged_value ) : '';
		if ( '' !== $normalized_merged_value ) {
			$payload['merged_value'] = $normalized_merged_value;

			if ( '' === trim( (string) ( $payload['label'] ?? '' ) ) ) {
				$payload['label'] = $normalized_merged_value;
			}

			if ( '' === trim( (string) ( $payload['name'] ?? '' ) ) ) {
				$payload['name'] = $normalized_merged_value;
			}
		}

		$data['payload'] = $this->reset_auto_attempt_payload( $payload );

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
	 * CAS-guarded status write. Success is an affected-row count > 0.
	 * 0 is a concurrent miss; false is a SQL/adapter failure.
	 *
	 * @param array<string,mixed> $data
	 * @param string[] $format
	 * @param array{last_attempted_at:?string,last_error_code:?string,attempts:int,first_failed_at:?string,last_error_retryable:?int}|null $fingerprint
	 * @return int|false
	 */
	private function update_operation_status( int $outbox_id, string $tenant_id, string $expected_status, array $data, array $format, ?array $fingerprint = null ): int|false {
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

		$where = array(
			'id' => $outbox_id,
			'tenant_id' => $normalized_tenant_id,
			'status' => $expected_status,
		);
		$where_format = array( '%d', '%s', '%s' );
		if ( is_array( $fingerprint ) ) {
			// wpdb renders nullable WHERE values as IS NULL, which is the NULL-safe
			// equivalent of a MySQL <=> comparison for the selected fingerprint.
			$where = array_merge(
				$where,
				array(
					'last_attempted_at' => $fingerprint['last_attempted_at'],
					'last_error_code' => $fingerprint['last_error_code'],
					'attempts' => $fingerprint['attempts'],
					'first_failed_at' => $fingerprint['first_failed_at'],
					'last_error_retryable' => $fingerprint['last_error_retryable'],
				)
			);
			$where_format = array_merge( $where_format, array( '%s', '%s', '%d', '%s', '%d' ) );
		}

		$updated = $wpdb->update(
			$this->table_name,
			$data,
			$where,
			$format,
			$where_format
		);
		if ( false === $updated ) {
			return false;
		}
		if ( ! is_int( $updated ) ) {
			return false;
		}
		if ( $updated <= 0 ) {
			return 0;
		}

		return $updated;
	}

	/**
	 * @param array<string,mixed> $row
	 * @return array{last_attempted_at:?string,last_error_code:?string,attempts:int,first_failed_at:?string,last_error_retryable:?int}
	 */
	private function failed_row_fingerprint( array $row ): array {
		return array(
			'last_attempted_at' => $this->fingerprint_nullable_value( $row['last_attempted_at'] ?? null ),
			'last_error_code' => $this->fingerprint_nullable_value( $row['last_error_code'] ?? null ),
			'attempts' => max( 0, (int) ( $row['attempts'] ?? 0 ) ),
			'first_failed_at' => $this->fingerprint_nullable_value( $row['first_failed_at'] ?? null ),
			'last_error_retryable' => $this->fingerprint_nullable_int( $row['last_error_retryable'] ?? null ),
		);
	}

	private function fingerprint_nullable_value( mixed $value ): ?string {
		return null === $value ? null : (string) $value;
	}

	private function fingerprint_nullable_int( mixed $value ): ?int {
		return null === $value ? null : (int) $value;
	}
}
