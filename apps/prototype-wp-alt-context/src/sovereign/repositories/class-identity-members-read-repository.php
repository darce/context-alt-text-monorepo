<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/trait-prepares-sql-queries.php';
require_once __DIR__ . '/trait-resolves-persons-table-name.php';

use function absint;
use function array_fill;
use function array_filter;
use function array_map;
use function array_unique;
use function array_values;
use function implode;
use function is_array;
use function is_object;
use function is_string;
use function max;
use function method_exists;
use function trim;

class IdentityMembersReadRepository {
	use PreparesSqlQueries;
	use ResolvesPersonsTableName;

	private string $members_table_name;
	private string $clusters_table_name;

	public function __construct( string $members_table_name, string $clusters_table_name ) {
		$this->members_table_name  = $members_table_name;
		$this->clusters_table_name = $clusters_table_name;
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function list_for_cluster( string $cluster_uuid, int $limit = IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT, int $offset = 0, ?string $tenant_id = null ): array {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		if ( '' === $normalized_cluster_uuid || ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$normalized_limit  = max( 1, $limit );
		$normalized_offset = max( 0, $offset );
		$persons_table     = $this->resolve_persons_table_name();

		if ( null !== $tenant_id && '' !== trim( $tenant_id ) ) {
			$sql = $this->prepare_projection_read_query(
				'SELECT COUNT(*) OVER() AS total_count, m.*, COALESCE(p.name, c.label) AS cluster_label, c.curation_state, c.is_user_confirmed, c.representative_id, c.is_pinned
				FROM %i m
				INNER JOIN %i c ON c.cluster_uuid = m.cluster_uuid
				LEFT JOIN %i p ON p.id = c.person_id
				WHERE m.cluster_uuid = %s AND c.tenant_id = %s
				ORDER BY m.assigned_at ASC, m.identity_uuid LIMIT %d OFFSET %d',
				array(
					$this->members_table_name,
					$this->clusters_table_name,
					$persons_table,
					$normalized_cluster_uuid,
					trim( $tenant_id ),
					$normalized_limit,
					$normalized_offset,
				)
			);
		} else {
			$sql = $this->prepare_projection_read_query(
				'SELECT COUNT(*) OVER() AS total_count, m.*, COALESCE(p.name, c.label) AS cluster_label, c.curation_state, c.is_user_confirmed, c.representative_id, c.is_pinned
				FROM %i m
				LEFT JOIN %i c ON c.cluster_uuid = m.cluster_uuid
				LEFT JOIN %i p ON p.id = c.person_id
				WHERE m.cluster_uuid = %s
				ORDER BY m.assigned_at ASC, m.identity_uuid LIMIT %d OFFSET %d',
				array(
					$this->members_table_name,
					$this->clusters_table_name,
					$persons_table,
					$normalized_cluster_uuid,
					$normalized_limit,
					$normalized_offset,
				)
			);
		}

		$this->clear_query_error();
		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );
		$this->guard_query_error( 'identity_members.list_for_cluster', $rows, true );
		return is_array( $rows ) ? $rows : array();
	}

	/**
	 * @param string[] $cluster_uuids
	 * @return array<string,array<int,array<string,mixed>>>
	 */
	public function list_for_cluster_uuids( array $cluster_uuids, int $limit_per_cluster ): array {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$normalized_uuids = array_values(
			array_unique(
				array_filter(
					array_map(
						static function ( $uuid ): string {
							return trim( (string) $uuid );
						},
						$cluster_uuids
					),
					static function ( string $uuid ): bool {
						return '' !== $uuid;
					}
				)
			)
		);

		if ( empty( $normalized_uuids ) ) {
			return array();
		}

		$normalized_limit = max( 1, $limit_per_cluster );
		$placeholders     = implode( ', ', array_fill( 0, count( $normalized_uuids ), '%s' ) );
		$persons_table    = $this->resolve_persons_table_name();

		$sql = $this->prepare_projection_read_query(
			"SELECT * FROM (
				SELECT m.*, COALESCE(p.name, c.label) AS cluster_label, c.curation_state, c.is_user_confirmed, c.representative_id, c.is_pinned, ROW_NUMBER() OVER (PARTITION BY m.cluster_uuid ORDER BY m.assigned_at ASC, m.identity_uuid) as rn
				FROM %i m
				LEFT JOIN %i c ON c.cluster_uuid = m.cluster_uuid
				LEFT JOIN %i p ON p.id = c.person_id
				WHERE m.cluster_uuid IN ($placeholders)
			) subquery WHERE rn <= %d",
			array_merge(
				array( $this->members_table_name, $this->clusters_table_name, $persons_table ),
				$normalized_uuids,
				array( $normalized_limit )
			)
		);

		$this->clear_query_error();
		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );
		$this->guard_query_error( 'identity_members.list_for_cluster_uuids', $rows, true );

		if ( ! is_array( $rows ) ) {
			return array();
		}

		$members_by_cluster = array();
		foreach ( $rows as $row ) {
			if ( ! is_array( $row ) ) {
				continue;
			}

			$cluster_uuid = trim( (string) ( $row['cluster_uuid'] ?? '' ) );
			if ( '' === $cluster_uuid ) {
				continue;
			}

			if ( ! isset( $members_by_cluster[ $cluster_uuid ] ) ) {
				$members_by_cluster[ $cluster_uuid ] = array();
			}

			unset( $row['rn'] );
			$members_by_cluster[ $cluster_uuid ][] = $row;
		}

		return $members_by_cluster;
	}

	/**
	 * @param int[] $media_ids
	 * @return array<int,array<string,mixed>>
	 */
	public function list_for_media_ids( string $tenant_id, array $media_ids ): array {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return array();
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$normalized_ids = array_values(
			array_unique(
				array_filter(
					array_map(
						static function ( $media_id ): int {
							return absint( $media_id );
						},
						$media_ids
					)
				)
			)
		);

		if ( empty( $normalized_ids ) ) {
			return array();
		}

		$placeholders  = implode( ', ', array_fill( 0, count( $normalized_ids ), '%d' ) );
		$persons_table = $this->resolve_persons_table_name();
		$sql           = $this->prepare_projection_read_query(
			"SELECT m.*, COALESCE(p.name, c.label) AS cluster_label, p.name AS person_name, c.curation_state, c.is_user_confirmed, c.representative_id, c.is_pinned
			FROM %i m
			INNER JOIN %i c ON c.cluster_uuid = m.cluster_uuid
			LEFT JOIN %i p ON p.id = c.person_id
			WHERE c.tenant_id = %s AND m.attachment_id IN ($placeholders)
			ORDER BY m.assigned_at ASC, m.identity_uuid",
			array_merge(
				array(
					$this->members_table_name,
					$this->clusters_table_name,
					$persons_table,
					$normalized_tenant_id,
				),
				$normalized_ids
			)
		);

		$this->clear_query_error();
		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );
		$this->guard_query_error( 'identity_members.list_for_media_ids', $rows, true );
		return is_array( $rows ) ? $rows : array();
	}

	public function has_projection_rows_for_tenant( string $tenant_id ): bool {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return false;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_var' ) ) {
			return false;
		}

		$sql = $this->prepare_projection_read_query(
			"SELECT EXISTS(SELECT 1
			FROM %i m
			INNER JOIN %i c ON c.cluster_uuid = m.cluster_uuid
			WHERE c.tenant_id = %s LIMIT 1)",
			array(
				$this->members_table_name,
				$this->clusters_table_name,
				$normalized_tenant_id,
			)
		);

		$this->clear_query_error();
		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$value = $wpdb->get_var( $sql );
		$this->guard_query_error( 'identity_members.has_projection_rows_for_tenant', $value, true );
		return 0 < (int) $value;
	}

	public function count_for_cluster( string $cluster_uuid, ?string $tenant_id = null ): int {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		if ( '' === $normalized_cluster_uuid ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_var' ) ) {
			return 0;
		}

		if ( null !== $tenant_id && '' !== trim( $tenant_id ) ) {
			$sql = $this->prepare_projection_read_query(
				'SELECT COUNT(*) FROM %i m
				INNER JOIN %i c ON c.cluster_uuid = m.cluster_uuid
				WHERE m.cluster_uuid = %s AND c.tenant_id = %s',
				array(
					$this->members_table_name,
					$this->clusters_table_name,
					$normalized_cluster_uuid,
					trim( $tenant_id ),
				)
			);
		} else {
			$sql = $this->prepare_projection_read_query(
				'SELECT COUNT(*) FROM %i WHERE cluster_uuid = %s',
				array(
					$this->members_table_name,
					$normalized_cluster_uuid,
				)
			);
		}

		$this->clear_query_error();
		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$value = $wpdb->get_var( $sql );
		// COUNT(*) always returns a row on success; null means the query did not run.
		$this->guard_query_error( 'identity_members.count_for_cluster', $value, true );
		return max( 0, (int) $value );
	}

	public function find_by_identity_uuid( string $identity_uuid ): ?array {
		global $wpdb;

		$normalized_identity_uuid = trim( $identity_uuid );
		if ( '' === $normalized_identity_uuid ) {
			return null;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_row' ) ) {
			return null;
		}

		$sql = $this->prepare_projection_read_query(
			'SELECT * FROM %i WHERE identity_uuid = %s LIMIT 1',
			array(
				$this->members_table_name,
				$normalized_identity_uuid,
			)
		);

		$this->clear_query_error();
		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$row = $wpdb->get_row( $sql, ARRAY_A );
		// null is a legitimate miss for get_row.
		$this->guard_query_error( 'identity_members.find_by_identity_uuid', $row, false );
		return is_array( $row ) ? $row : null;
	}

	/**
	 * @return array<string,array<string,mixed>>
	 */
	public function get_curated_members_for_tenant( string $tenant_id ): array {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return array();
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$sql = $this->prepare_projection_read_query(
			"SELECT m.* FROM %i m
			INNER JOIN %i c ON c.cluster_uuid = m.cluster_uuid
			WHERE c.tenant_id = %s AND m.is_curated = 1",
			array(
				$this->members_table_name,
				$this->clusters_table_name,
				$normalized_tenant_id,
			)
		);

		$this->clear_query_error();
		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );
		$this->guard_query_error( 'identity_members.get_curated_members_for_tenant', $rows, true );
		if ( ! is_array( $rows ) ) {
			return array();
		}

		$members = array();
		foreach ( $rows as $row ) {
			if ( ! is_array( $row ) ) {
				continue;
			}

			$identity_uuid = trim( (string) ( $row['identity_uuid'] ?? '' ) );
			if ( '' === $identity_uuid ) {
				continue;
			}

			$members[ $identity_uuid ] = $row;
		}

		return $members;
	}
}
