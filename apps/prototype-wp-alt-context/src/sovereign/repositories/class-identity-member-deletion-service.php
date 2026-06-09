<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/trait-prepares-sql-queries.php';

use function is_int;
use function is_object;
use function is_string;
use function method_exists;
use function trim;

class IdentityMemberDeletionService {
	use PreparesSqlQueries;

	private string $members_table_name;
	private string $clusters_table_name;

	public function __construct( string $members_table_name, string $clusters_table_name ) {
		$this->members_table_name  = $members_table_name;
		$this->clusters_table_name = $clusters_table_name;
	}

	public function delete_member( string $identity_uuid, string $tenant_id ): int {
		global $wpdb;

		$normalized_identity_uuid = trim( $identity_uuid );
		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_identity_uuid || '' === $normalized_tenant_id ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$sql = $this->prepare_query(
			'DELETE m FROM %i m
			INNER JOIN %i c ON c.cluster_uuid = m.cluster_uuid
			WHERE m.identity_uuid = %s AND c.tenant_id = %s',
			array(
				$this->members_table_name,
				$this->clusters_table_name,
				$normalized_identity_uuid,
				$normalized_tenant_id,
			)
		);
		if ( ! is_string( $sql ) || '' === $sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$query_result = $wpdb->query( $sql );
		return is_int( $query_result ) ? $query_result : 0;
	}
}
