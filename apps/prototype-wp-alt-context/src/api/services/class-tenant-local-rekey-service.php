<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use Throwable;

/**
 * Re-keys tenant-scoped local projection rows when identity changes.
 */
class TenantLocalRekeyService {
	public const ROW_THRESHOLD = 50_000;

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
				if ( false === $result ) {
					throw new \RuntimeException( sprintf( 'Could not re-key tenant rows in %s.', $table ) );
				}
				$updated += (int) $result;
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

	private function upsert_resync_required_stream( string $sync_table, string $stream, string $updated_at ): void {
		global $wpdb;

		$wpdb->delete( $sync_table, array( 'stream_name' => $stream ), array( '%s' ) );
		$inserted = $wpdb->insert(
			$sync_table,
			array(
				'stream_name'           => $stream,
				'last_snapshot_version' => 0,
				'last_sync_result'      => 'resync_required',
				'updated_at'            => $updated_at,
			),
			array( '%s', '%d', '%s', '%s' )
		);
		if ( false === $inserted ) {
			throw new \RuntimeException( 'Could not mark tenant sync stream for re-sync.' );
		}
	}

	private function mark_resync_required( string $tenant_id ): void {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! is_string( $wpdb->prefix ) ) {
			return;
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