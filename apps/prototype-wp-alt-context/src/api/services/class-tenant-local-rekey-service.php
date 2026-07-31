<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use AltContext\Sovereign\Repositories\SyncStateRepository;
use Throwable;

/**
 * Re-keys tenant-scoped local projection rows when identity changes.
 */
class TenantLocalRekeyService {
	public const ROW_THRESHOLD = 50_000;

	/**
	 * Durable marker written to acx_sync_state.last_sync_result when a rekey
	 * (or threshold resync) completes. Alias of the canonical vocabulary
	 * SyncStateRepository::SYNC_RESULT_RESYNC_REQUIRED [sr-007] / SPA LAST_SYNC_RESULT.
	 */
	public const RESYNC_REQUIRED_RESULT = SyncStateRepository::SYNC_RESULT_RESYNC_REQUIRED;

	/** @var list<string> */
	private const TENANT_TABLE_SUFFIXES = array(
		'acx_clusters',
		'acx_batch_runs',
		'acx_batch_run_failures',
		'acx_sync_outbox',
		'acx_topology_commands',
		'acx_sync_conflicts',
	);

	/**
	 * @return array{strategy: 'rekey'|'resync', updated_rows: int}
	 */
	public function reconcile_identity_change( string $from_tenant_id, string $to_tenant_id ): array {
		$row_count = $this->count_rows_for_tenant( $from_tenant_id );
		if ( $row_count > self::ROW_THRESHOLD ) {
			// Threshold path: the marker IS the substantive outcome (too large to
			// rekey in-process). Verify it landed before reporting success.
			$this->mark_resync_required( $to_tenant_id );
			return array(
				'strategy'     => 'resync',
				'updated_rows' => 0,
			);
		}

		return array(
			'strategy'     => 'rekey',
			'updated_rows' => $this->rekey_rows_transactionally( $from_tenant_id, $to_tenant_id ),
		);
	}

	protected function count_rows_for_tenant( string $tenant_id ): int {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! is_string( $wpdb->prefix ) ) {
			return 0;
		}

		$total = 0;
		foreach ( self::TENANT_TABLE_SUFFIXES as $suffix ) {
			$table = $wpdb->prefix . $suffix;
			// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared -- table name is plugin-owned.
			$count = $wpdb->get_var( $wpdb->prepare( "SELECT COUNT(*) FROM {$table} WHERE tenant_id = %s", $tenant_id ) );
			$total += (int) $count;
		}

		return $total;
	}

	private function rekey_rows_transactionally( string $from_tenant_id, string $to_tenant_id ): int {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) || ! method_exists( $wpdb, 'prepare' ) || ! is_string( $wpdb->prefix ) ) {
			throw new \RuntimeException( 'Tenant re-key requires wpdb transaction support.' );
		}

		$started = false !== $wpdb->query( 'START TRANSACTION' );
		if ( ! $started ) {
			throw new \RuntimeException( 'Could not start tenant re-key transaction.' );
		}

		$updated = 0;
		try {
			foreach ( self::TENANT_TABLE_SUFFIXES as $suffix ) {
				$table  = $wpdb->prefix . $suffix;
				$result = $wpdb->update(
					$table,
					array( 'tenant_id' => $to_tenant_id ),
					array( 'tenant_id' => $from_tenant_id ),
					array( '%s' ),
					array( '%s' )
				);
				// false = write error. 0 = no rows for this tenant in this table
				// (legitimate no-op, including idempotent re-key). Do not collapse.
				if ( false === $result ) {
					throw new \RuntimeException( sprintf( 'Could not re-key tenant rows in %s.', $table ) );
				}
				$updated += (int) $result;
			}

			// R23-BR-28: verify the substantive rekey by read-back before writing
			// the resync_required marker. A return-value check alone cannot admit
			// the idempotent case (0 rows already under from_tenant_id); count
			// remaining source rows. Never set the marker on an unverified rekey.
			$remaining = $this->count_rows_for_tenant( $from_tenant_id );
			if ( $remaining > 0 ) {
				throw new \RuntimeException(
					sprintf(
						'Tenant re-key read-back found %d row(s) still under source tenant; resync marker not written.',
						$remaining
					)
				);
			}

			$this->migrate_sync_state_streams( $from_tenant_id, $to_tenant_id );

			if ( false === $wpdb->query( 'COMMIT' ) ) {
				throw new \RuntimeException( 'Could not commit tenant re-key transaction.' );
			}
		} catch ( Throwable $e ) {
			$wpdb->query( 'ROLLBACK' );
			throw $e;
		}

		return $updated;
	}

	private function migrate_sync_state_streams( string $from_tenant_id, string $to_tenant_id ): void {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! is_string( $wpdb->prefix ) ) {
			return;
		}

		$sync_table  = $wpdb->prefix . 'acx_sync_state';
		$from_stream = $this->stream_name_for_tenant( $from_tenant_id );
		$to_stream   = $this->stream_name_for_tenant( $to_tenant_id );
		$now         = gmdate( 'Y-m-d H:i:s' );

		$wpdb->delete( $sync_table, array( 'stream_name' => $from_stream ), array( '%s' ) );
		$this->upsert_resync_required_stream( $sync_table, $to_stream, $now );
	}

	/**
	 * Write the resync_required marker and verify it landed via read-back.
	 *
	 * insert returns false on storage failure; a successful insert (or a
	 * delete+insert that leaves the intended marker) must read back as
	 * RESYNC_REQUIRED_RESULT before callers treat the path as complete.
	 *
	 * @throws \RuntimeException When the marker does not land.
	 */
	private function upsert_resync_required_stream( string $sync_table, string $stream, string $updated_at ): void {
		global $wpdb;

		$wpdb->delete( $sync_table, array( 'stream_name' => $stream ), array( '%s' ) );
		$inserted = $wpdb->insert(
			$sync_table,
			array(
				'stream_name'           => $stream,
				'last_snapshot_version' => 0,
				'last_sync_result'      => self::RESYNC_REQUIRED_RESULT,
				'updated_at'            => $updated_at,
			),
			array( '%s', '%d', '%s', '%s' )
		);
		if ( false === $inserted ) {
			throw new \RuntimeException( 'Could not mark tenant sync stream for re-sync.' );
		}

		// Read-back: prove the marker is durable before reporting success.
		// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared -- table name is plugin-owned.
		$stored = $wpdb->get_var( $wpdb->prepare( "SELECT last_sync_result FROM {$sync_table} WHERE stream_name = %s LIMIT 1", $stream ) );
		if ( ! is_string( $stored ) || self::RESYNC_REQUIRED_RESULT !== trim( $stored ) ) {
			throw new \RuntimeException(
				'Could not verify resync_required marker after write; marker not set.'
			);
		}
	}

	private function mark_resync_required( string $tenant_id ): void {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! is_string( $wpdb->prefix ) ) {
			throw new \RuntimeException( 'Could not mark resync_required: wpdb unavailable.' );
		}

		$sync_table = $wpdb->prefix . 'acx_sync_state';
		$stream     = $this->stream_name_for_tenant( $tenant_id );
		$now        = gmdate( 'Y-m-d H:i:s' );
		$this->upsert_resync_required_stream( $sync_table, $stream, $now );
	}

	private function stream_name_for_tenant( string $tenant_id ): string {
		return sprintf( 'tenant:%s:clusters', trim( $tenant_id ) );
	}
}
