<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/interface-sync-state-repository.php';
require_once __DIR__ . '/trait-prepares-sql-queries.php';
require_once __DIR__ . '/../sync/class-sync-pull-result.php';

use AltContext\Sovereign\Sync\SyncPullResult;
use function gmdate;
use function is_array;
use function is_object;
use function is_string;
use function in_array;
use function max;
use function method_exists;
use function sprintf;
use function trim;

class SyncStateRepository implements SyncStateRepositoryInterface {
	use PreparesSqlQueries;

	/**
	 * Durable last_sync_result vocabulary written/read by this repository [sr-007].
	 * Mirrored by TypeScript LAST_SYNC_RESULT in js/admin/api/recognition/types/sync.ts.
	 * rekey / threshold paths also write RESYNC_REQUIRED via the rekey service.
	 */
	public const SYNC_RESULT_OK              = 'ok';
	public const SYNC_RESULT_FAILED          = 'failed';
	public const SYNC_RESULT_UNREACHABLE     = 'unreachable';
	public const SYNC_RESULT_RESYNC_REQUIRED = 'resync_required';

	private string $table_name;
	private string $outbox_table_name;
	private string $topology_commands_table_name;
	private string $conflicts_table_name;

	public function __construct( ?string $table_name = null ) {
		global $wpdb;

		$default_table = 'wp_acx_sync_state';
		$default_outbox_table = 'wp_acx_sync_outbox';
		$default_topology_table = 'wp_acx_topology_commands';
		$default_conflicts_table = 'wp_acx_sync_conflicts';
		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			$default_table = $wpdb->prefix . 'acx_sync_state';
			$default_outbox_table = $wpdb->prefix . 'acx_sync_outbox';
			$default_topology_table = $wpdb->prefix . 'acx_topology_commands';
			$default_conflicts_table = $wpdb->prefix . 'acx_sync_conflicts';
		}

		$this->table_name = $table_name ?? $default_table;
		$this->outbox_table_name = $default_outbox_table;
		$this->topology_commands_table_name = $default_topology_table;
		$this->conflicts_table_name = $default_conflicts_table;
	}

	public function upsert_snapshot_version( string $tenant_id, int $snapshot_version ): void {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return;
		}

		$stream_name = $this->stream_name_for_tenant( $normalized_tenant_id );
		$sql         = $this->prepare_query(
			'INSERT INTO %i
				(stream_name, last_snapshot_version, updated_at)
			VALUES (%s, %d, %s)
			ON DUPLICATE KEY UPDATE
				last_snapshot_version = GREATEST(last_snapshot_version, VALUES(last_snapshot_version)),
				updated_at = VALUES(updated_at)',
			array(
				$this->table_name,
				$stream_name,
				max( 0, $snapshot_version ),
				gmdate( 'Y-m-d H:i:s' ),
			)
		);

		if ( is_string( $sql ) && '' !== $sql ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
			$wpdb->query( $sql );
		}
	}

	public function get_snapshot_version( string $tenant_id ): int {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_var' ) ) {
			return 0;
		}

		$sql = $this->prepare_query(
			'SELECT last_snapshot_version FROM %i WHERE stream_name = %s LIMIT 1',
			array(
				$this->table_name,
				$this->stream_name_for_tenant( $normalized_tenant_id ),
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$value = $wpdb->get_var( $sql );
		return max( 0, (int) $value );
	}

	public function get_last_updated( string $tenant_id ): ?string {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return null;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_var' ) ) {
			return null;
		}

		$sql = $this->prepare_query(
			'SELECT updated_at FROM %i WHERE stream_name = %s LIMIT 1',
			array(
				$this->table_name,
				$this->stream_name_for_tenant( $normalized_tenant_id ),
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return null;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$value = $wpdb->get_var( $sql );
		if ( ! is_string( $value ) ) {
			return null;
		}

		$normalized = trim( $value );
		if ( '' === $normalized || '1970-01-01 00:00:00' === $normalized ) {
			return null;
		}

		return $normalized;
	}

	public function get_last_sync_result( string $tenant_id ): string {
		$value = $this->get_string_state_value( $tenant_id, 'last_sync_result' );
		return $this->normalize_sync_result( $value );
	}

	/**
	 * Persist the last sync-pull outcome for the tenant stream.
	 *
	 * R23-BR-23: inspect the durable write. $wpdb->query returns false on write
	 * error and 0 when ON DUPLICATE KEY UPDATE changes no column values (identical
	 * re-apply). Those must not collapse: false is a storage failure reported to
	 * the caller; 0 is a legitimate no-op and must still succeed so the SPA is
	 * not told a green re-apply failed [rg-015].
	 *
	 * @throws \RuntimeException When the write errors (query === false).
	 */
	public function set_last_sync_result( string $tenant_id, string $result ): void {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			throw new \RuntimeException( 'Could not persist last_sync_result: wpdb unavailable.' );
		}

		$normalized_result = $this->normalize_sync_result( $result );
		$attempted_at      = gmdate( 'Y-m-d H:i:s' );
		if ( self::SYNC_RESULT_OK === $normalized_result || SyncPullResult::OK === $normalized_result ) {
			$sql = $this->prepare_query(
				'INSERT INTO %i (stream_name, last_snapshot_version, last_sync_result, last_sync_attempted_at, updated_at)
				VALUES (%s, 0, %s, %s, %s)
				ON DUPLICATE KEY UPDATE
					last_sync_result = VALUES(last_sync_result),
					last_sync_attempted_at = VALUES(last_sync_attempted_at),
					updated_at = VALUES(updated_at)',
				array(
					$this->table_name,
					$this->stream_name_for_tenant( $normalized_tenant_id ),
					$normalized_result,
					$attempted_at,
					$attempted_at,
				)
			);
		} else {
			$sql = $this->prepare_query(
				'INSERT INTO %i (stream_name, last_snapshot_version, last_sync_result, last_sync_attempted_at)
				VALUES (%s, 0, %s, %s)
				ON DUPLICATE KEY UPDATE
					last_sync_result = VALUES(last_sync_result),
					last_sync_attempted_at = VALUES(last_sync_attempted_at)',
				array(
					$this->table_name,
					$this->stream_name_for_tenant( $normalized_tenant_id ),
					$normalized_result,
					$attempted_at,
				)
			);
		}

		if ( ! is_string( $sql ) || '' === $sql ) {
			throw new \RuntimeException( 'Could not prepare last_sync_result write.' );
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$query_result = $wpdb->query( $sql );
		// false = write error. 0 = no-op re-apply (identical values). Do not collapse.
		if ( false === $query_result ) {
			throw new \RuntimeException( 'Could not persist last_sync_result (write error).' );
		}
	}

	public function touch_local_curation_marker( string $tenant_id ): void {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return;
		}

		$stream_name = $this->stream_name_for_tenant( $normalized_tenant_id );
		$sql         = $this->prepare_query(
			'INSERT INTO %i (stream_name, last_snapshot_version, updated_at)
			VALUES (%s, 0, %s)
			ON DUPLICATE KEY UPDATE updated_at = VALUES(updated_at)',
			array(
				$this->table_name,
				$stream_name,
				'1970-01-01 00:00:00',
			)
		);

		if ( is_string( $sql ) && '' !== $sql ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
			$wpdb->query( $sql );
		}
	}

	public function reset_projection_state( string $tenant_id ): void {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return;
		}

		$sql = $this->prepare_query(
			'INSERT INTO %i (stream_name, last_snapshot_version, updated_at)
			VALUES (%s, %d, %s)
			ON DUPLICATE KEY UPDATE
				last_snapshot_version = VALUES(last_snapshot_version),
				updated_at = VALUES(updated_at)',
			array(
				$this->table_name,
				$this->stream_name_for_tenant( $normalized_tenant_id ),
				0,
				'1970-01-01 00:00:00',
			)
		);

		if ( is_string( $sql ) && '' !== $sql ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
			$wpdb->query( $sql );
		}
	}

	/**
	 * Recompute and persist curation metric counters for the tenant stream.
	 *
	 * R23-BR-23: inspect each durable write before treating metrics as refreshed.
	 * $wpdb->update returns false on write error and 0 when no row matched the
	 * WHERE (or MySQL reports no column change). These are different conditions:
	 * - false → storage write error; metrics did not land.
	 * - 0 on a stream that pre-read as present → no-op / identical values (success).
	 *   This repository keys updates by stream_name only (not id+status CAS);
	 *   a true concurrent status CAS miss cannot arise here. 0 is therefore the
	 *   legitimate re-apply path and must not be reported as failure.
	 * - insert false → insert write error.
	 *
	 * @throws \RuntimeException When a durable metrics write does not land.
	 */
	public function refresh_curation_metrics( string $tenant_id ): void {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_var' ) || ! method_exists( $wpdb, 'get_row' ) || ! method_exists( $wpdb, 'update' ) || ! method_exists( $wpdb, 'insert' ) ) {
			throw new \RuntimeException( 'Could not refresh curation metrics: wpdb unavailable.' );
		}

		$stream_name = $this->stream_name_for_tenant( $normalized_tenant_id );
		$existing = $this->get_sync_state_row( $stream_name );
		$pending = $this->count_outbox_rows( $normalized_tenant_id, 'pending' );
		$failed = $this->count_outbox_rows( $normalized_tenant_id, 'failed' );
		$conflicts = $this->count_conflict_rows( $normalized_tenant_id, 'open' );
		$last_acknowledged_at = $this->max_outbox_acknowledged_at( $normalized_tenant_id );
		$last_conflict_at = $this->max_conflict_created_at( $normalized_tenant_id );
		$last_failed_at = $this->max_outbox_failed_at( $normalized_tenant_id );

		$data = array(
			'pending_curation_operations' => $pending,
			'failed_curation_operations' => $failed,
			'conflict_count' => $conflicts,
			'last_curation_acknowledged_at' => $last_acknowledged_at ?? ( $existing['last_curation_acknowledged_at'] ?? null ),
			'last_curation_conflict_at' => $last_conflict_at ?? ( $existing['last_curation_conflict_at'] ?? null ),
			'last_curation_failed_at' => $last_failed_at ?? ( $existing['last_curation_failed_at'] ?? null ),
		);

		if ( is_array( $existing ) ) {
			$updated = $wpdb->update(
				$this->table_name,
				$data,
				array( 'stream_name' => $stream_name ),
				array( '%d', '%d', '%d', '%s', '%s', '%s' ),
				array( '%s' )
			);
			// false = write error (distinct from 0 = no-op / no column change).
			if ( false === $updated ) {
				throw new \RuntimeException(
					'Could not refresh curation metrics: update write error on pending_curation_operations/failed_curation_operations/conflict_count.'
				);
			}
			// 0 = identical re-apply or no column change — success for this non-CAS WHERE.
			return;
		}

		$inserted = $wpdb->insert(
			$this->table_name,
			array(
				'stream_name' => $stream_name,
				'last_snapshot_version' => 0,
				'pending_curation_operations' => $pending,
				'failed_curation_operations' => $failed,
				'conflict_count' => $conflicts,
				'last_curation_acknowledged_at' => $data['last_curation_acknowledged_at'],
				'last_curation_conflict_at' => $data['last_curation_conflict_at'],
				'last_curation_failed_at' => $data['last_curation_failed_at'],
				'updated_at' => '1970-01-01 00:00:00',
			),
			array( '%s', '%d', '%d', '%d', '%d', '%s', '%s', '%s', '%s' )
		);
		if ( false === $inserted ) {
			throw new \RuntimeException(
				'Could not refresh curation metrics: insert write error on pending_curation_operations/failed_curation_operations/conflict_count.'
			);
		}
	}

	public function get_pending_curation_operations( string $tenant_id ): int {
		return max( 0, $this->get_numeric_state_value( $tenant_id, 'pending_curation_operations' ) );
	}

	public function get_conflict_count( string $tenant_id ): int {
		return max( 0, $this->get_numeric_state_value( $tenant_id, 'conflict_count' ) );
	}

	public function get_failed_curation_operations( string $tenant_id ): int {
		return max( 0, $this->get_numeric_state_value( $tenant_id, 'failed_curation_operations' ) );
	}

	public function get_last_curation_acknowledged_at( string $tenant_id ): ?string {
		return $this->get_string_state_value( $tenant_id, 'last_curation_acknowledged_at' );
	}

	public function get_last_curation_conflict_at( string $tenant_id ): ?string {
		return $this->get_string_state_value( $tenant_id, 'last_curation_conflict_at' );
	}

	public function get_last_curation_failed_at( string $tenant_id ): ?string {
		return $this->get_string_state_value( $tenant_id, 'last_curation_failed_at' );
	}

	public function get_pending_topology_commands( string $tenant_id ): int {
		return $this->count_topology_rows( trim( $tenant_id ), array( 'pending', 'dispatched' ) );
	}

	public function get_applied_topology_commands( string $tenant_id ): int {
		return $this->count_topology_rows( trim( $tenant_id ), array( 'applied' ) );
	}

	public function get_failed_topology_commands( string $tenant_id ): int {
		return $this->count_topology_rows( trim( $tenant_id ), array( 'failed' ) );
	}

	public function get_conflicted_topology_commands( string $tenant_id ): int {
		return $this->count_topology_rows( trim( $tenant_id ), array( 'conflict' ) );
	}

	public function get_last_topology_reconciled_at( string $tenant_id ): ?string {
		return $this->max_topology_reconciled_at( trim( $tenant_id ) );
	}

	private function stream_name_for_tenant( string $tenant_id ): string {
		return sprintf( 'tenant:%s:clusters', trim( $tenant_id ) );
	}

	private function get_numeric_state_value( string $tenant_id, string $column ): int {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_var' ) ) {
			return 0;
		}

		$sql = $this->prepare_query(
			'SELECT %i FROM %i WHERE stream_name = %s LIMIT 1',
			array(
				$column,
				$this->table_name,
				$this->stream_name_for_tenant( $normalized_tenant_id ),
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$value = $wpdb->get_var( $sql );

		return max( 0, (int) $value );
	}

	private function get_string_state_value( string $tenant_id, string $column ): ?string {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return null;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_var' ) ) {
			return null;
		}

		$sql = $this->prepare_query(
			'SELECT %i FROM %i WHERE stream_name = %s LIMIT 1',
			array(
				$column,
				$this->table_name,
				$this->stream_name_for_tenant( $normalized_tenant_id ),
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return null;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$value = $wpdb->get_var( $sql );
		if ( ! is_string( $value ) ) {
			return null;
		}

		$normalized = trim( $value );
		return '' !== $normalized ? $normalized : null;
	}

	/**
	 * @return array<string,mixed>|null
	 */
	private function get_sync_state_row( string $stream_name ): ?array {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_row' ) ) {
			return null;
		}

		$sql = $this->prepare_query(
			'SELECT last_curation_acknowledged_at, last_curation_conflict_at, last_curation_failed_at
			FROM %i
			WHERE stream_name = %s
			LIMIT 1',
			array(
				$this->table_name,
				$stream_name,
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return null;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$row = $wpdb->get_row( $sql, ARRAY_A );
		return is_array( $row ) ? $row : null;
	}

	private function count_outbox_rows( string $tenant_id, string $status ): int {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_var' ) ) {
			return 0;
		}

		$sql = $this->prepare_query(
			'SELECT COUNT(*) FROM %i WHERE tenant_id = %s AND status = %s',
			array(
				$this->outbox_table_name,
				$tenant_id,
				$status,
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$value = $wpdb->get_var( $sql );

		return max( 0, (int) $value );
	}

	private function count_conflict_rows( string $tenant_id, string $resolution_status ): int {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_var' ) ) {
			return 0;
		}

		$sql = $this->prepare_query(
			'SELECT COUNT(*) FROM %i WHERE tenant_id = %s AND resolution_status = %s',
			array(
				$this->conflicts_table_name,
				$tenant_id,
				$resolution_status,
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$value = $wpdb->get_var( $sql );

		return max( 0, (int) $value );
	}

	private function max_outbox_acknowledged_at( string $tenant_id ): ?string {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_var' ) ) {
			return null;
		}

		$sql = $this->prepare_query(
			'SELECT MAX(acknowledged_at) FROM %i WHERE tenant_id = %s AND status = %s',
			array(
				$this->outbox_table_name,
				$tenant_id,
				'acknowledged',
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return null;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$value = $wpdb->get_var( $sql );
		if ( ! is_string( $value ) ) {
			return null;
		}

		$normalized = trim( $value );
		return '' !== $normalized ? $normalized : null;
	}

	private function max_conflict_created_at( string $tenant_id ): ?string {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_var' ) ) {
			return null;
		}

		$sql = $this->prepare_query(
			'SELECT MAX(created_at) FROM %i WHERE tenant_id = %s AND resolution_status = %s',
			array(
				$this->conflicts_table_name,
				$tenant_id,
				'open',
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return null;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$value = $wpdb->get_var( $sql );
		if ( ! is_string( $value ) ) {
			return null;
		}

		$normalized = trim( $value );
		return '' !== $normalized ? $normalized : null;
	}

	private function max_outbox_failed_at( string $tenant_id ): ?string {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_var' ) ) {
			return null;
		}

		$sql = $this->prepare_query(
			'SELECT MAX(last_attempted_at) FROM %i WHERE tenant_id = %s AND status = %s',
			array(
				$this->outbox_table_name,
				$tenant_id,
				'failed',
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return null;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$value = $wpdb->get_var( $sql );
		if ( ! is_string( $value ) ) {
			return null;
		}

		$normalized = trim( $value );
		return '' !== $normalized ? $normalized : null;
	}

	/**
	 * @param string[] $statuses
	 */
	private function count_topology_rows( string $tenant_id, array $statuses ): int {
		global $wpdb;

		if ( empty( $statuses ) || ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_var' ) ) {
			return 0;
		}

		$placeholders = implode( ', ', array_fill( 0, count( $statuses ), '%s' ) );
		$args = array_merge(
			array( $this->topology_commands_table_name, $tenant_id ),
			$statuses
		);
		$sql = $this->prepare_query(
			"SELECT COUNT(*) FROM %i WHERE tenant_id = %s AND status IN ({$placeholders})",
			$args
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$value = $wpdb->get_var( $sql );
		return max( 0, (int) $value );
	}

	private function max_topology_reconciled_at( string $tenant_id ): ?string {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_var' ) ) {
			return null;
		}

		$sql = $this->prepare_query(
			'SELECT MAX(projection_reconciled_at) FROM %i WHERE tenant_id = %s AND status = %s',
			array(
				$this->topology_commands_table_name,
				$tenant_id,
				'reconciled',
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return null;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$value = $wpdb->get_var( $sql );
		if ( ! is_string( $value ) ) {
			return null;
		}

		$normalized = trim( $value );
		return '' !== $normalized ? $normalized : null;
	}

	/**
	 * Normalize a stored or requested last_sync_result.
	 *
	 * Empty / missing defaults to ok (never-synced is not a failure). Known
	 * vocabulary is preserved, including resync_required (written by rekey).
	 * Unknown non-empty values fail closed to failed — never invent ok [rg-015].
	 */
	private function normalize_sync_result( ?string $result ): string {
		$normalized = is_string( $result ) ? trim( $result ) : '';
		if ( '' === $normalized ) {
			return self::SYNC_RESULT_OK;
		}

		if ( in_array(
			$normalized,
			array(
				self::SYNC_RESULT_OK,
				self::SYNC_RESULT_FAILED,
				self::SYNC_RESULT_UNREACHABLE,
				self::SYNC_RESULT_RESYNC_REQUIRED,
				SyncPullResult::OK,
				SyncPullResult::FAILED,
				SyncPullResult::UNREACHABLE,
			),
			true
		) ) {
			return $normalized;
		}

		return self::SYNC_RESULT_FAILED;
	}
}
