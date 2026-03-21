<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/trait-prepares-sql-queries.php';

use function absint;
use function array_fill;
use function array_filter;
use function array_merge;
use function array_map;
use function array_unique;
use function array_values;
use function count;
use function gmdate;
use function implode;
use function in_array;
use function is_array;
use function is_bool;
use function is_numeric;
use function is_object;
use function is_string;
use function max;
use function method_exists;
use function preg_match;
use function sprintf;
use function trim;
use function str_ends_with;
use function substr;

class ClustersRepository implements ClustersRepositoryInterface {
	use PreparesSqlQueries;

	private string $table_name;

	public function __construct( ?string $table_name = null ) {
		global $wpdb;

		$default_table = 'wp_acx_clusters';
		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			$default_table = $wpdb->prefix . 'acx_clusters';
		}

		$this->table_name = $table_name ?? $default_table;
	}

	/**
	 * @param array<int,array<string,mixed>> $clusters
	 */
	public function merge_snapshot_for_tenant( string $tenant_id, array $clusters, int $snapshot_version ): void {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return;
		}

		$normalized_clusters = array_values(
			array_filter(
				$clusters,
				static function ( $cluster ): bool {
					return is_array( $cluster ) && '' !== trim( (string) ( $cluster['cluster_uuid'] ?? '' ) );
				}
			)
		);

		$incoming_ids = array_values(
			array_filter(
				array_map(
					static function ( array $cluster ): string {
						return trim( (string) ( $cluster['cluster_uuid'] ?? '' ) );
					},
					$normalized_clusters
				)
			)
		);

		$this->delete_stale_non_curated_rows( $normalized_tenant_id, $incoming_ids );

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		foreach ( $normalized_clusters as $cluster ) {
			$cluster_uuid = trim( (string) ( $cluster['cluster_uuid'] ?? '' ) );
			if ( '' === $cluster_uuid ) {
				continue;
			}

			$label       = $this->normalize_label( $cluster );
			$thumb_path  = $this->resolve_representative_thumb_path( $cluster, $cluster_uuid );
			$inserted_at = $now_utc;

			$sql = $this->prepare_query(
				'INSERT INTO %i
				(cluster_uuid, tenant_id, label, curation_state, representative_thumb_path, representative_id, is_pinned, identity_count, snapshot_version, is_user_confirmed, created_at, updated_at, last_synced_at)
				VALUES (%s, %s, %s, %s, %s, %s, %d, %d, %d, %d, %s, %s, %s)
				ON DUPLICATE KEY UPDATE
					label = IF(is_user_confirmed = 1, label, VALUES(label)),
					curation_state = IF(is_user_confirmed = 1, curation_state, VALUES(curation_state)),
					is_user_confirmed = IF(is_user_confirmed = 1, is_user_confirmed, VALUES(is_user_confirmed)),
					person_id = IF(is_user_confirmed = 1, person_id, person_id),
					local_revision = IF(is_user_confirmed = 1, local_revision, local_revision),
					representative_thumb_path = VALUES(representative_thumb_path),
					representative_id = VALUES(representative_id),
					is_pinned = VALUES(is_pinned),
					identity_count = VALUES(identity_count),
					snapshot_version = GREATEST(snapshot_version, VALUES(snapshot_version)),
					updated_at = VALUES(updated_at),
					last_synced_at = VALUES(last_synced_at)',
				array(
					$this->table_name,
					$cluster_uuid,
					$normalized_tenant_id,
					$label,
					$this->normalize_curation_state( $cluster ),
					$thumb_path,
					$this->normalize_representative_id( $cluster ),
					$this->resolve_representative_pin_flag( $cluster ),
					$this->resolve_identity_count( $cluster ),
					max( 0, $snapshot_version ),
					$this->resolve_user_confirmed_flag( $cluster ),
					$inserted_at,
					$now_utc,
					$now_utc,
				)
			);

			if ( is_string( $sql ) && '' !== $sql ) {
				// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
				$wpdb->query( $sql );
			}
		}
	}

	/**
	 * @param array<string,mixed> $filters
	 * @return array<int,array<string,mixed>>
	 */
	public function list_for_tenant( string $tenant_id, int $limit = 50, int $offset = 0, array $filters = array() ): array {
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
				'SELECT c.*, COALESCE(p.name, c.label) as label 
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
	 * @return string[]
	 */
	public function list_labels( string $tenant_id ): array {
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
			"SELECT DISTINCT label FROM %i WHERE tenant_id = %s AND label IS NOT NULL AND label != '' ORDER BY label ASC",
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

		$labels = array();
		foreach ( $rows as $row ) {
			$label = trim( (string) ( $row['label'] ?? '' ) );
			if ( '' !== $label ) {
				$labels[] = $label;
			}
		}

		return array_values( array_unique( $labels ) );
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
			"SELECT c.*, COALESCE(p.name, c.label) as label 
			FROM %i c
			LEFT JOIN %i p ON c.person_id = p.id
			WHERE c.tenant_id = %s
				AND (c.label IS NULL OR c.label = '')
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

	public function update_label( string $cluster_uuid, string $label, bool $mark_user_confirmed = true ): int {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		$normalized_label        = trim( $label );
		if ( '' === $normalized_cluster_uuid || '' === $normalized_label ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$sql     = $this->prepare_query(
			'UPDATE %i SET label = %s, is_user_confirmed = %d, local_revision = local_revision + 1, updated_at = %s WHERE cluster_uuid = %s',
			array(
				$this->table_name,
				$normalized_label,
				$mark_user_confirmed ? 1 : 0,
				$now_utc,
				$normalized_cluster_uuid,
			)
		);

		if ( is_string( $sql ) && '' !== $sql ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
			$query_result = $wpdb->query( $sql );
			if ( is_int( $query_result ) ) {
				return $query_result;
			}
		}

		return 0;
	}

	public function dismiss( string $cluster_uuid ): int {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		if ( '' === $normalized_cluster_uuid ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$sql     = $this->prepare_query(
			'UPDATE %i SET curation_state = %s, is_user_confirmed = 1, local_revision = local_revision + 1, updated_at = %s WHERE cluster_uuid = %s',
			array(
				$this->table_name,
				'dismissed',
				$now_utc,
				$normalized_cluster_uuid,
			)
		);

		if ( is_string( $sql ) && '' !== $sql ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
			$query_result = $wpdb->query( $sql );
			if ( is_int( $query_result ) ) {
				return $query_result;
			}
		}

		return 0;
	}

	public function update_identity_count( string $cluster_uuid, int $identity_count ): int {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		if ( '' === $normalized_cluster_uuid ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$sql     = $this->prepare_query(
			'UPDATE %i SET identity_count = %d, local_revision = local_revision + 1, updated_at = %s WHERE cluster_uuid = %s',
			array(
				$this->table_name,
				max( 0, $identity_count ),
				$now_utc,
				$normalized_cluster_uuid,
			)
		);

		if ( is_string( $sql ) && '' !== $sql ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
			$query_result = $wpdb->query( $sql );
			if ( is_int( $query_result ) ) {
				return $query_result;
			}
		}

		return 0;
	}

	public function update_representative_state( string $cluster_uuid, ?string $representative_id, bool $is_pinned, bool $is_local_curation = true ): int {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		if ( '' === $normalized_cluster_uuid ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$normalized_representative_id = is_string( $representative_id ) ? trim( $representative_id ) : '';
		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$sql = $this->prepare_query(
			'UPDATE %i
			SET representative_id = %s,
				is_pinned = %d,
				local_revision = local_revision + 1,
				updated_at = %s
			WHERE cluster_uuid = %s',
			array(
				$this->table_name,
				'' !== $normalized_representative_id ? $normalized_representative_id : null,
				$is_pinned ? 1 : 0,
				$now_utc,
				$normalized_cluster_uuid,
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$query_result = $wpdb->query( $sql );
		return is_int( $query_result ) ? $query_result : 0;
	}

	public function create_local_cluster( string $tenant_id, string $cluster_uuid, string $label, int $identity_count = 1 ): int {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		$normalized_cluster_uuid = trim( $cluster_uuid );
		$normalized_label = trim( $label );
		if ( '' === $normalized_tenant_id || '' === $normalized_cluster_uuid || '' === $normalized_label ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'insert' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$inserted = $wpdb->insert(
			$this->table_name,
			array(
				'cluster_uuid' => $normalized_cluster_uuid,
				'tenant_id' => $normalized_tenant_id,
				'label' => $normalized_label,
				'curation_state' => 'uncurated',
				'identity_count' => max( 0, $identity_count ),
				'snapshot_version' => 0,
				'is_user_confirmed' => 1,
				'local_revision' => 1,
				'created_at' => $now_utc,
				'updated_at' => $now_utc,
				'last_synced_at' => $now_utc,
			),
			array( '%s', '%s', '%s', '%s', '%d', '%d', '%d', '%d', '%s', '%s', '%s' )
		);

		return is_int( $inserted ) ? $inserted : 0;
	}

	public function upsert_projection_cluster( string $tenant_id, string $cluster_uuid, string $label, int $identity_count, int $snapshot_version, ?string $representative_thumb_path = null, ?string $representative_id = null, bool $is_pinned = false ): int {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		$normalized_cluster_uuid = trim( $cluster_uuid );
		if ( '' === $normalized_tenant_id || '' === $normalized_cluster_uuid ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$sql = $this->prepare_query(
			'INSERT INTO %i
				(cluster_uuid, tenant_id, label, curation_state, representative_thumb_path, representative_id, is_pinned, identity_count, snapshot_version, is_user_confirmed, local_revision, created_at, updated_at, last_synced_at)
			VALUES (%s, %s, %s, %s, %s, %s, %d, %d, %d, %d, %d, %s, %s, %s)
			ON DUPLICATE KEY UPDATE
				label = VALUES(label),
				curation_state = VALUES(curation_state),
				representative_thumb_path = VALUES(representative_thumb_path),
				representative_id = VALUES(representative_id),
				is_pinned = VALUES(is_pinned),
				identity_count = VALUES(identity_count),
				snapshot_version = GREATEST(snapshot_version, VALUES(snapshot_version)),
				is_user_confirmed = VALUES(is_user_confirmed),
				updated_at = VALUES(updated_at),
				last_synced_at = VALUES(last_synced_at)',
			array(
				$this->table_name,
				$normalized_cluster_uuid,
				$normalized_tenant_id,
				trim( $label ),
				'uncurated',
				null === $representative_thumb_path ? null : trim( $representative_thumb_path ),
				$this->normalize_optional_text( $representative_id ),
				$is_pinned ? 1 : 0,
				max( 0, $identity_count ),
				max( 0, $snapshot_version ),
				0,
				0,
				$now_utc,
				$now_utc,
				$now_utc,
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$query_result = $wpdb->query( $sql );
		return is_int( $query_result ) ? $query_result : 0;
	}

	public function update_projection_cluster( string $cluster_uuid, int $identity_count, int $snapshot_version, ?string $representative_thumb_path = null, ?string $representative_id = null, bool $is_pinned = false ): int {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		if ( '' === $normalized_cluster_uuid ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		if ( null === $representative_thumb_path ) {
			$sql = $this->prepare_query(
				'UPDATE %i
				SET identity_count = %d,
					snapshot_version = GREATEST(snapshot_version, %d),
					representative_id = %s,
					is_pinned = %d,
					updated_at = %s,
					last_synced_at = %s
				WHERE cluster_uuid = %s',
				array(
					$this->table_name,
					max( 0, $identity_count ),
					max( 0, $snapshot_version ),
					$this->normalize_optional_text( $representative_id ),
					$is_pinned ? 1 : 0,
					$now_utc,
					$now_utc,
					$normalized_cluster_uuid,
				)
			);
		} else {
			$sql = $this->prepare_query(
				'UPDATE %i
				SET identity_count = %d,
					snapshot_version = GREATEST(snapshot_version, %d),
					representative_thumb_path = %s,
					representative_id = %s,
					is_pinned = %d,
					updated_at = %s,
					last_synced_at = %s
				WHERE cluster_uuid = %s',
				array(
					$this->table_name,
					max( 0, $identity_count ),
					max( 0, $snapshot_version ),
					trim( $representative_thumb_path ),
					$this->normalize_optional_text( $representative_id ),
					$is_pinned ? 1 : 0,
					$now_utc,
					$now_utc,
					$normalized_cluster_uuid,
				)
			);
		}

		if ( ! is_string( $sql ) || '' === $sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$query_result = $wpdb->query( $sql );
		return is_int( $query_result ) ? $query_result : 0;
	}

	public function undismiss( string $cluster_uuid ): int {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		if ( '' === $normalized_cluster_uuid ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$sql     = $this->prepare_query(
				'UPDATE %i SET curation_state = %s, is_user_confirmed = 0, local_revision = local_revision + 1, updated_at = %s WHERE cluster_uuid = %s',
				array(
					$this->table_name,
					'uncurated',
					$now_utc,
					$normalized_cluster_uuid,
				)
			);

		if ( is_string( $sql ) && '' !== $sql ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
			$query_result = $wpdb->query( $sql );
			if ( is_int( $query_result ) ) {
				return $query_result;
			}
		}

		return 0;
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

	public function reset_curation( string $cluster_uuid, string $tenant_id ): int {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_cluster_uuid || '' === $normalized_tenant_id ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$sql = $this->prepare_query(
			'UPDATE %i
			SET label = NULL,
				person_id = NULL,
				curation_state = %s,
				is_user_confirmed = 0,
				local_revision = local_revision + 1,
				updated_at = %s
			WHERE cluster_uuid = %s AND tenant_id = %s',
			array(
				$this->table_name,
				'uncurated',
				$now_utc,
				$normalized_cluster_uuid,
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

	/**
	 * @param string[] $incoming_cluster_ids
	 */
	private function delete_stale_non_curated_rows( string $tenant_id, array $incoming_cluster_ids ): void {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return;
		}

		if ( empty( $incoming_cluster_ids ) ) {
			$sql = $this->prepare_query(
				'DELETE FROM %i WHERE tenant_id = %s AND is_user_confirmed = 0',
				array(
					$this->table_name,
					$tenant_id,
				)
			);

			if ( is_string( $sql ) && '' !== $sql ) {
				// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
				$wpdb->query( $sql );
			}

			return;
		}

		$valid_cluster_ids = $this->sanitize_uuid_list( $incoming_cluster_ids );
		if ( empty( $valid_cluster_ids ) ) {
			return;
		}

		$placeholders = implode( ', ', array_fill( 0, count( $valid_cluster_ids ), '%s' ) );
		$sql = $this->prepare_query(
			"DELETE FROM %i
			WHERE tenant_id = %s
				AND is_user_confirmed = 0
				AND cluster_uuid NOT IN ($placeholders)",
			array_merge(
				array(
					$this->table_name,
					$tenant_id,
				),
				$valid_cluster_ids
			)
		);

		if ( is_string( $sql ) && '' !== $sql ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
			$wpdb->query( $sql );
		}
	}

	private function resolve_persons_table_name(): string {
		if ( str_ends_with( $this->table_name, 'acx_clusters' ) ) {
			return substr( $this->table_name, 0, -12 ) . 'acx_persons';
		}

		return 'wp_acx_persons';
	}

	/**
	 * @param array<string,mixed> $cluster
	 */
	private function normalize_label( array $cluster ): string {
		$label = trim( (string) ( $cluster['label'] ?? $cluster['cluster_label'] ?? '' ) );
		return $label;
	}

	/**
	 * @param array<string,mixed> $cluster
	 */
	private function resolve_identity_count( array $cluster ): int {
		if ( is_numeric( $cluster['identity_count'] ?? null ) ) {
			return max( 0, (int) $cluster['identity_count'] );
		}

		if ( is_array( $cluster['members'] ?? null ) ) {
			return count( $cluster['members'] );
		}

		if ( is_array( $cluster['identities'] ?? null ) ) {
			return count( $cluster['identities'] );
		}

		return 0;
	}

	/**
	 * @param array<string,mixed> $cluster
	 */
	private function normalize_curation_state( array $cluster ): string {
		$state = trim( (string) ( $cluster['curation_state'] ?? '' ) );
		if ( 'active' === $state ) {
			return 'uncurated';
		}

		if ( in_array( $state, array( 'uncurated', 'confirmed', 'dismissed' ), true ) ) {
			return $state;
		}

		return 'uncurated';
	}

	/**
	 * @param array<string,mixed> $cluster
	 */
	private function resolve_user_confirmed_flag( array $cluster ): int {
		$value = $cluster['is_user_confirmed'] ?? false;
		if ( is_bool( $value ) ) {
			return $value ? 1 : 0;
		}

		return in_array( trim( (string) $value ), array( '1', 'true', 'yes', 'on' ), true ) ? 1 : 0;
	}

	/**
	 * @param array<string,mixed> $cluster
	 */
	private function resolve_representative_thumb_path( array $cluster, string $cluster_uuid ): string {
		$explicit_path = trim( (string) ( $cluster['representative_thumb_path'] ?? '' ) );
		if ( '' !== $explicit_path ) {
			return $explicit_path;
		}

		$representative_media_id = absint( $cluster['representative_media_id'] ?? 0 );
		if ( $representative_media_id > 0 ) {
			return $this->build_thumb_key( $cluster_uuid, $representative_media_id );
		}

		$representatives = $cluster['representatives'] ?? null;
		if ( is_array( $representatives ) ) {
			foreach ( $representatives as $representative ) {
				if ( ! is_array( $representative ) ) {
					continue;
				}

				$thumb_path = trim( (string) ( $representative['thumb_path'] ?? '' ) );
				if ( '' !== $thumb_path ) {
					return $thumb_path;
				}

				$media_id = absint( $representative['media_id'] ?? 0 );
				if ( $media_id > 0 ) {
					return $this->build_thumb_key( $cluster_uuid, $media_id );
				}
			}
		}

		return '';
	}

	/**
	 * @param array<string,mixed> $cluster
	 */
	private function normalize_representative_id( array $cluster ): ?string {
		$representative_id = trim( (string) ( $cluster['representative_id'] ?? '' ) );
		if ( '' !== $representative_id ) {
			return $representative_id;
		}

		$representatives = $cluster['representatives'] ?? null;
		if ( is_array( $representatives ) ) {
			foreach ( $representatives as $representative ) {
				if ( ! is_array( $representative ) ) {
					continue;
				}

				$id = trim( (string) ( $representative['id'] ?? $representative['identity_id'] ?? '' ) );
				if ( '' !== $id ) {
					return $id;
				}
			}
		}

		return null;
	}

	/**
	 * @param array<string,mixed> $cluster
	 */
	private function resolve_representative_pin_flag( array $cluster ): int {
		$value = $cluster['is_pinned'] ?? false;
		if ( is_bool( $value ) ) {
			return $value ? 1 : 0;
		}

		return in_array( trim( (string) $value ), array( '1', 'true', 'yes', 'on' ), true ) ? 1 : 0;
	}

	private function normalize_optional_text( ?string $value ): ?string {
		if ( ! is_string( $value ) ) {
			return null;
		}

		$normalized = trim( $value );
		return '' !== $normalized ? $normalized : null;
	}

	private function build_thumb_key( string $cluster_uuid, int $media_id ): string {
		return sprintf( 'acx://cluster/%s/media/%d', trim( $cluster_uuid ), $media_id );
	}

	/**
	 * @param string[] $candidate_ids
	 * @return string[]
	 */
	private function sanitize_uuid_list( array $candidate_ids ): array {
		$normalized_ids = array_map(
			static function ( $candidate ): string {
				return trim( (string) $candidate );
			},
			$candidate_ids
		);

		$valid_ids = array_filter(
			$normalized_ids,
			static function ( string $value ): bool {
				return '' !== $value && 1 === preg_match( '/^[A-Za-z0-9-]+$/', $value );
			}
		);

		return array_values( array_unique( $valid_ids ) );
	}
}
