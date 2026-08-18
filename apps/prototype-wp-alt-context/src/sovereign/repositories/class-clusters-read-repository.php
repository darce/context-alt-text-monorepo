<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/trait-prepares-sql-queries.php';
require_once __DIR__ . '/trait-resolves-persons-table-name.php';

use function is_array;
use function is_numeric;
use function is_object;
use function is_string;
use function max;
use function method_exists;
use function str_replace;
use function trim;

class ClustersReadRepository {
	use PreparesSqlQueries;
	use ResolvesPersonsTableName;

	private string $table_name;

	public function __construct( string $table_name ) {
		$this->table_name = $table_name;
	}

	/**
	 * @param array<string,mixed> $filters
	 * @return array<int,array<string,mixed>>
	 */
	public function list_for_tenant( string $tenant_id, int $limit = ClustersRepositoryInterface::DEFAULT_LIST_LIMIT, int $offset = 0, array $filters = array() ): array {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return array();
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$search       = trim( (string) ( $filters['search'] ?? '' ) );
		$labeled_only = true === ( $filters['labeled_only'] ?? false );

		$normalized_limit  = max( 1, $limit );
		$normalized_offset = max( 0, $offset );
		$persons_table     = $this->resolve_persons_table_name();

		// Literal SQL templates (four filter combinations) so parity scanners see fixed strings.
		if ( $labeled_only && '' !== $search && method_exists( $wpdb, 'esc_like' ) ) {
			$sql = $this->prepare_projection_read_query(
				"SELECT COUNT(*) OVER() AS total_count, c.*, p.person_uuid, COALESCE(p.name, c.label) as label
				 FROM %i c
				 LEFT JOIN %i p ON c.person_id = p.id
				 WHERE c.tenant_id = %s AND c.label IS NOT NULL AND c.label != '' AND c.label LIKE %s
				 ORDER BY c.updated_at DESC, c.cluster_uuid ASC
				 LIMIT %d OFFSET %d",
				array(
					$this->table_name,
					$persons_table,
					$normalized_tenant_id,
					'%' . $wpdb->esc_like( $search ) . '%',
					$normalized_limit,
					$normalized_offset,
				)
			);
		} elseif ( $labeled_only ) {
			$sql = $this->prepare_projection_read_query(
				"SELECT COUNT(*) OVER() AS total_count, c.*, p.person_uuid, COALESCE(p.name, c.label) as label
				 FROM %i c
				 LEFT JOIN %i p ON c.person_id = p.id
				 WHERE c.tenant_id = %s AND c.label IS NOT NULL AND c.label != ''
				 ORDER BY c.updated_at DESC, c.cluster_uuid ASC
				 LIMIT %d OFFSET %d",
				array(
					$this->table_name,
					$persons_table,
					$normalized_tenant_id,
					$normalized_limit,
					$normalized_offset,
				)
			);
		} elseif ( '' !== $search && method_exists( $wpdb, 'esc_like' ) ) {
			$sql = $this->prepare_projection_read_query(
				'SELECT COUNT(*) OVER() AS total_count, c.*, p.person_uuid, COALESCE(p.name, c.label) as label
				 FROM %i c
				 LEFT JOIN %i p ON c.person_id = p.id
				 WHERE c.tenant_id = %s AND c.label LIKE %s
				 ORDER BY c.updated_at DESC, c.cluster_uuid ASC
				 LIMIT %d OFFSET %d',
				array(
					$this->table_name,
					$persons_table,
					$normalized_tenant_id,
					'%' . $wpdb->esc_like( $search ) . '%',
					$normalized_limit,
					$normalized_offset,
				)
			);
		} else {
			$sql = $this->prepare_projection_read_query(
				'SELECT COUNT(*) OVER() AS total_count, c.*, p.person_uuid, COALESCE(p.name, c.label) as label
				 FROM %i c
				 LEFT JOIN %i p ON c.person_id = p.id
				 WHERE c.tenant_id = %s
				 ORDER BY c.updated_at DESC, c.cluster_uuid ASC
				 LIMIT %d OFFSET %d',
				array(
					$this->table_name,
					$persons_table,
					$normalized_tenant_id,
					$normalized_limit,
					$normalized_offset,
				)
			);
		}

		$this->clear_query_error();
		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );
		$this->guard_query_error( 'clusters.list_for_tenant', $rows, true );
		return is_array( $rows ) ? $rows : array();
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function list_labels( string $tenant_id, string $search = '', int $limit = ClustersRepositoryInterface::DEFAULT_LIST_LIMIT ): array {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return array();
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$normalized_search = trim( $search );
		$normalized_limit  = max( 1, $limit );

		if ( '' !== $normalized_search && method_exists( $wpdb, 'esc_like' ) ) {
			$sql = $this->prepare_projection_read_query(
				"SELECT COUNT(*) OVER() AS total_count, filtered.label FROM (SELECT DISTINCT label FROM %i WHERE tenant_id = %s AND label IS NOT NULL AND label != '' AND label LIKE %s ORDER BY label ASC) filtered LIMIT %d",
				array(
					$this->table_name,
					$normalized_tenant_id,
					'%' . $wpdb->esc_like( $normalized_search ) . '%',
					$normalized_limit,
				)
			);
		} else {
			$sql = $this->prepare_projection_read_query(
				"SELECT COUNT(*) OVER() AS total_count, filtered.label FROM (SELECT DISTINCT label FROM %i WHERE tenant_id = %s AND label IS NOT NULL AND label != '' ORDER BY label ASC) filtered LIMIT %d",
				array(
					$this->table_name,
					$normalized_tenant_id,
					$normalized_limit,
				)
			);
		}

		$this->clear_query_error();
		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );
		$this->guard_query_error( 'clusters.list_labels', $rows, true );
		if ( ! is_array( $rows ) ) {
			return array();
		}

		$labels = array();
		foreach ( $rows as $row ) {
			$label = trim( (string) ( $row['label'] ?? '' ) );
			if ( '' !== $label ) {
				$labels[] = array(
					'label' => $label,
					'total_count' => max( 0, (int) ( $row['total_count'] ?? 0 ) ),
				);
			}
		}

		return $labels;
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
			'SELECT EXISTS(SELECT 1 FROM %i WHERE tenant_id = %s LIMIT 1)',
			array(
				$this->table_name,
				$normalized_tenant_id,
			)
		);

		$this->clear_query_error();
		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$value = $wpdb->get_var( $sql );
		$this->guard_query_error( 'clusters.has_projection_rows_for_tenant', $value, true );
		return 0 < (int) $value;
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function list_top_unlabeled( string $tenant_id, int $limit = 10 ): array {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return array();
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$normalized_limit = max( 1, $limit );
		$persons_table    = $this->resolve_persons_table_name();
		$members_table    = $this->resolve_identity_members_table_name();
		$sql = $this->prepare_projection_read_query(
				"SELECT COUNT(*) OVER() AS total_count, c.*, p.person_uuid, COALESCE(p.name, c.label) as label 
				FROM %i c
				LEFT JOIN %i p ON c.person_id = p.id
				WHERE c.tenant_id = %s
					AND c.is_user_confirmed = 0
					AND (c.label IS NULL OR c.label = '' OR c.label LIKE 'cluster-%%')
					AND c.identity_count >= 2
					AND (
						SELECT COUNT(*)
						FROM %i m
						WHERE m.cluster_uuid = c.cluster_uuid
					) >= 2
					AND (c.curation_state IS NULL OR c.curation_state <> 'dismissed')
				ORDER BY c.identity_count DESC, c.updated_at DESC, c.cluster_uuid ASC
				LIMIT %d",
				array(
					$this->table_name,
					$persons_table,
					$normalized_tenant_id,
					$members_table,
					$normalized_limit,
				)
			);

		$this->clear_query_error();
		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );
		$this->guard_query_error( 'clusters.list_top_unlabeled', $rows, true );
		return is_array( $rows ) ? $rows : array();
	}

	private function resolve_identity_members_table_name(): string {
		return str_replace( 'acx_clusters', 'acx_identity_members', $this->table_name );
	}

	public function count_top_unlabeled_singletons( string $tenant_id ): int {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_var' ) ) {
			return 0;
		}

		$sql = $this->prepare_projection_read_query(
			"SELECT COUNT(*)
			FROM %i c
			WHERE c.tenant_id = %s
				AND c.is_user_confirmed = 0
				AND (c.label IS NULL OR c.label = '' OR c.label LIKE 'cluster-%%')
				AND c.identity_count <= 1
				AND (c.curation_state IS NULL OR c.curation_state <> 'dismissed')",
			array(
				$this->table_name,
				$normalized_tenant_id,
			)
		);

		$this->clear_query_error();
		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$count = $wpdb->get_var( $sql );
		// COUNT(*) always returns a row on success; null means the query did not run.
		$this->guard_query_error( 'clusters.count_top_unlabeled_singletons', $count, true );
		return is_numeric( $count ) ? max( 0, (int) $count ) : 0;
	}

	/**
	 * @return array<string,mixed>|null
	 */
	public function find_by_uuid( string $cluster_uuid ): ?array {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		if ( '' === $normalized_cluster_uuid || ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_row' ) ) {
			return null;
		}

		$persons_table = $this->resolve_persons_table_name();
		$sql = $this->prepare_projection_read_query(
			"SELECT c.*, p.person_uuid, COALESCE(p.name, c.label) as label 
			 FROM %i c 
			 LEFT JOIN %i p ON c.person_id = p.id
			 WHERE c.cluster_uuid = %s 
			 LIMIT 1",
				array(
					$this->table_name,
					$persons_table,
					$normalized_cluster_uuid,
				)
			);

		$this->clear_query_error();
		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$row = $wpdb->get_row( $sql, ARRAY_A );
		// null is a legitimate miss for get_row.
		$this->guard_query_error( 'clusters.find_by_uuid', $row, false );
		return is_array( $row ) ? $row : null;
	}

	/**
	 * @return array<string,array<string,mixed>>
	 */
	public function get_curated_clusters_for_tenant( string $tenant_id ): array {
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
			'SELECT * FROM %i WHERE tenant_id = %s AND is_user_confirmed = 1',
			array(
				$this->table_name,
				$normalized_tenant_id,
			)
		);

		$this->clear_query_error();
		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );
		$this->guard_query_error( 'clusters.get_curated_clusters_for_tenant', $rows, true );
		if ( ! is_array( $rows ) ) {
			return array();
		}

		$clusters = array();
		foreach ( $rows as $row ) {
			if ( ! is_array( $row ) ) {
				continue;
			}

			$cluster_uuid = trim( (string) ( $row['cluster_uuid'] ?? '' ) );
			if ( '' === $cluster_uuid ) {
				continue;
			}

			$clusters[ $cluster_uuid ] = $row;
		}

		return $clusters;
	}
}
