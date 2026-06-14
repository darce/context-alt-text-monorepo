<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/trait-prepares-sql-queries.php';

use function gmdate;
use function is_int;
use function is_object;
use function is_string;
use function method_exists;
use function trim;

class IdentityMemberCurationWriter {
	use PreparesSqlQueries;

	private string $members_table_name;
	private string $clusters_table_name;

	public function __construct( string $members_table_name, string $clusters_table_name ) {
		$this->members_table_name  = $members_table_name;
		$this->clusters_table_name = $clusters_table_name;
	}

	public function reassign_to_cluster( string $identity_uuid, string $target_cluster_uuid ): int {
		global $wpdb;

		$normalized_identity_uuid = trim( $identity_uuid );
		$normalized_target_cluster_uuid = trim( $target_cluster_uuid );
		if ( '' === $normalized_identity_uuid || '' === $normalized_target_cluster_uuid ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$sql = $this->prepare_query(
			'UPDATE %i SET cluster_uuid = %s, is_curated = 1, updated_at = %s WHERE identity_uuid = %s',
			array(
				$this->members_table_name,
				$normalized_target_cluster_uuid,
				$now_utc,
				$normalized_identity_uuid,
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$query_result = $wpdb->query( $sql );
		return is_int( $query_result ) ? $query_result : 0;
	}

	public function reassign_cluster_members( string $source_cluster_uuid, string $target_cluster_uuid ): int {
		global $wpdb;

		$normalized_source_cluster_uuid = trim( $source_cluster_uuid );
		$normalized_target_cluster_uuid = trim( $target_cluster_uuid );
		if ( '' === $normalized_source_cluster_uuid || '' === $normalized_target_cluster_uuid || $normalized_source_cluster_uuid === $normalized_target_cluster_uuid ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$sql = $this->prepare_query(
			'UPDATE %i SET cluster_uuid = %s, is_curated = 1, updated_at = %s WHERE cluster_uuid = %s',
			array(
				$this->members_table_name,
				$normalized_target_cluster_uuid,
				$now_utc,
				$normalized_source_cluster_uuid,
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$query_result = $wpdb->query( $sql );
		return is_int( $query_result ) ? $query_result : 0;
	}

	public function reset_curation( string $identity_uuid, string $tenant_id ): int {
		global $wpdb;

		$normalized_identity_uuid = trim( $identity_uuid );
		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_identity_uuid || '' === $normalized_tenant_id ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$sql = $this->prepare_query(
			'UPDATE %i m
			INNER JOIN %i c ON c.cluster_uuid = m.cluster_uuid
			SET m.is_curated = 0, m.updated_at = %s
			WHERE m.identity_uuid = %s AND c.tenant_id = %s',
			array(
				$this->members_table_name,
				$this->clusters_table_name,
				$now_utc,
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

	public function accept_machine_cluster_assignment( string $identity_uuid, string $cluster_uuid, string $tenant_id ): int {
		global $wpdb;

		$normalized_identity_uuid = trim( $identity_uuid );
		$normalized_cluster_uuid = trim( $cluster_uuid );
		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_identity_uuid || '' === $normalized_cluster_uuid || '' === $normalized_tenant_id ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$sql = $this->prepare_query(
			'UPDATE %i m
			INNER JOIN %i current_cluster ON current_cluster.cluster_uuid = m.cluster_uuid
			INNER JOIN %i target_cluster ON target_cluster.cluster_uuid = %s
			SET m.cluster_uuid = %s, m.is_curated = 0, m.updated_at = %s
			WHERE m.identity_uuid = %s
				AND current_cluster.tenant_id = %s
				AND target_cluster.tenant_id = %s',
			array(
				$this->members_table_name,
				$this->clusters_table_name,
				$this->clusters_table_name,
				$normalized_cluster_uuid,
				$normalized_cluster_uuid,
				$now_utc,
				$normalized_identity_uuid,
				$normalized_tenant_id,
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
