<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/trait-prepares-sql-queries.php';
require_once __DIR__ . '/trait-resolves-persons-table-name.php';

use function implode;
use function is_array;
use function is_numeric;
use function is_object;
use function is_string;
use function max;
use function method_exists;
use function sprintf;
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

		$conditions    = array( 'c.tenant_id = %s' );
		$persons_table = $this->resolve_persons_table_name();
		$args          = array( $this->table_name, $persons_table, $normalized_tenant_id );

		if ( $labeled_only ) {
			$conditions[] = "c.label IS NOT NULL AND c.label != ''";
		}

		if ( '' !== $search && method_exists( $wpdb, 'esc_like' ) ) {
			$conditions[] = 'c.label LIKE %s';
			$args[]       = '%' . $wpdb->esc_like( $search ) . '%';
		}

		$sql = $this->prepare_query(
			sprintf(
				'SELECT COUNT(*) OVER() AS total_count, c.*, COALESCE(p.name, c.label) as label 
				 FROM %%i c 
				 LEFT JOIN %%i p ON c.person_id = p.id
				 WHERE %s 
				 ORDER BY c.updated_at DESC 
				 LIMIT %%d OFFSET %%d',
				implode( ' AND ', $conditions )
			),
			array_merge(
				$args,
				array(
					$normalized_limit,
					$normalized_offset,
				)
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return array();
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );
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
		$conditions        = array(
			'tenant_id = %s',
			"label IS NOT NULL",
			"label != ''",
		);
		$args = array(
			$this->table_name,
			$normalized_tenant_id,
		);

		if ( '' !== $normalized_search && method_exists( $wpdb, 'esc_like' ) ) {
			$conditions[] = 'label LIKE %s';
			$args[]       = '%' . $wpdb->esc_like( $normalized_search ) . '%';
		}

		$sql = $this->prepare_query(
			sprintf(
				'SELECT COUNT(*) OVER() AS total_count, filtered.label FROM (SELECT DISTINCT label FROM %%i WHERE %s ORDER BY label ASC) filtered LIMIT %%d',
				implode( ' AND ', $conditions )
			),
			array_merge(
				$args,
				array( $normalized_limit )
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return array();
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );
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

		$sql = $this->prepare_query(
			'SELECT 1 FROM %i WHERE tenant_id = %s LIMIT 1',
			array(
				$this->table_name,
				$normalized_tenant_id,
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return false;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		return null !== $wpdb->get_var( $sql );
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
		$sql = $this->prepare_query(
				"SELECT COUNT(*) OVER() AS total_count, c.*, COALESCE(p.name, c.label) as label 
				FROM %i c
				LEFT JOIN %i p ON c.person_id = p.id
				WHERE c.tenant_id = %s
					AND c.is_user_confirmed = 0
					AND (c.label IS NULL OR c.label = '' OR c.label LIKE 'cluster-%%')
					AND c.identity_count >= 2
					AND (c.curation_state IS NULL OR c.curation_state <> 'dismissed')
				ORDER BY c.identity_count DESC, c.updated_at DESC
				LIMIT %d",
				array(
					$this->table_name,
					$persons_table,
					$normalized_tenant_id,
					$normalized_limit,
				)
			);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return array();
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );
		return is_array( $rows ) ? $rows : array();
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

		$sql = $this->prepare_query(
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

		if ( ! is_string( $sql ) || '' === $sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$count = $wpdb->get_var( $sql );
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
		$sql = $this->prepare_query(
			"SELECT c.*, COALESCE(p.name, c.label) as label 
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

		if ( ! is_string( $sql ) || '' === $sql ) {
			return null;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$row = $wpdb->get_row( $sql, ARRAY_A );
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

		$sql = $this->prepare_query(
			'SELECT * FROM %i WHERE tenant_id = %s AND is_user_confirmed = 1',
			array(
				$this->table_name,
				$normalized_tenant_id,
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return array();
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );
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
