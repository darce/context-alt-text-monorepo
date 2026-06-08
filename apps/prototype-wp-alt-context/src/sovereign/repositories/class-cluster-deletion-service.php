<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/trait-prepares-sql-queries.php';

use function is_int;
use function is_object;
use function is_string;
use function method_exists;
use function str_replace;
use function trim;

class ClusterDeletionService {
	use PreparesSqlQueries;

	private string $table_name;

	public function __construct( string $table_name ) {
		$this->table_name = $table_name;
	}

	public function delete_cluster_with_members( string $cluster_uuid, string $tenant_id ): int {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_cluster_uuid || '' === $normalized_tenant_id ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$members_table = str_replace( 'acx_clusters', 'acx_identity_members', $this->table_name );
		$delete_members_sql = $this->prepare_query(
			'DELETE m FROM %i m
			INNER JOIN %i c ON c.cluster_uuid = m.cluster_uuid
			WHERE m.cluster_uuid = %s AND c.tenant_id = %s',
			array(
				$members_table,
				$this->table_name,
				$normalized_cluster_uuid,
				$normalized_tenant_id,
			)
		);
		if ( is_string( $delete_members_sql ) && '' !== $delete_members_sql ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
			$wpdb->query( $delete_members_sql );
		}

		$delete_cluster_sql = $this->prepare_query(
			'DELETE FROM %i WHERE cluster_uuid = %s AND tenant_id = %s',
			array(
				$this->table_name,
				$normalized_cluster_uuid,
				$normalized_tenant_id,
			)
		);
		if ( ! is_string( $delete_cluster_sql ) || '' === $delete_cluster_sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$query_result = $wpdb->query( $delete_cluster_sql );
		return is_int( $query_result ) ? $query_result : 0;
	}
}
