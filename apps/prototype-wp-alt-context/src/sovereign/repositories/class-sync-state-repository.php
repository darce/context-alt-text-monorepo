<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/trait-prepares-sql-queries.php';

use function gmdate;
use function is_object;
use function is_string;
use function max;
use function method_exists;
use function sprintf;
use function trim;

class SyncStateRepository implements SyncStateRepositoryInterface {
	use PreparesSqlQueries;

	private string $table_name;

	public function __construct( ?string $table_name = null ) {
		global $wpdb;

		$default_table = 'wp_acx_sync_state';
		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			$default_table = $wpdb->prefix . 'acx_sync_state';
		}

		$this->table_name = $table_name ?? $default_table;
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
		return '' !== $normalized ? $normalized : null;
	}

	private function stream_name_for_tenant( string $tenant_id ): string {
		return sprintf( 'tenant:%s:clusters', trim( $tenant_id ) );
	}
}
