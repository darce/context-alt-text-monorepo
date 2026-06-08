<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/trait-prepares-sql-queries.php';
require_once __DIR__ . '/trait-resolves-persons-table-name.php';
require_once __DIR__ . '/class-clusters-read-repository.php';
require_once __DIR__ . '/class-cluster-curation-writer.php';
require_once __DIR__ . '/class-cluster-projection-writer.php';

use function absint;
use function array_fill;
use function array_filter;
use function array_merge;
use function array_map;
use function array_chunk;
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
class ClustersRepository implements ClustersRepositoryInterface {
	use PreparesSqlQueries;
	use ResolvesPersonsTableName;

	private string $table_name;

	private ClustersReadRepository $read_repository;

	private ClusterCurationWriter $curation_writer;

	private ClusterProjectionWriter $projection_writer;

	public function __construct(
		?string $table_name = null,
		?ClustersReadRepository $read_repository = null,
		?ClusterCurationWriter $curation_writer = null,
		?ClusterProjectionWriter $projection_writer = null
	) {
		global $wpdb;

		$default_table = 'wp_acx_clusters';
		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			$default_table = $wpdb->prefix . 'acx_clusters';
		}

		$this->table_name        = $table_name ?? $default_table;
		$this->read_repository   = $read_repository ?? new ClustersReadRepository( $this->table_name );
		$this->curation_writer   = $curation_writer ?? new ClusterCurationWriter( $this->table_name );
		$this->projection_writer = $projection_writer ?? new ClusterProjectionWriter( $this->table_name );
	}

	/**
	 * @param array<int,array<string,mixed>> $clusters
	 */
	public function merge_snapshot_for_tenant( string $tenant_id, array $clusters, int $snapshot_version ): void {
		$normalized_clusters = $this->normalize_snapshot_clusters( $clusters );
		$incoming_ids        = $this->extract_snapshot_cluster_ids( $normalized_clusters );

		$this->prepare_snapshot_merge_for_tenant( $tenant_id, $incoming_ids );

		// Stale-row pruning is still payload-wide; only the upsert phase is chunked.
		foreach ( array_chunk( $normalized_clusters, ClustersRepositoryInterface::MAX_SNAPSHOT_MERGE_BATCH ) as $cluster_batch ) {
			$this->merge_snapshot_batch_for_tenant( $tenant_id, $cluster_batch, $snapshot_version );
		}
	}

	/**
	 * @param string[] $incoming_cluster_ids
	 */
	public function prepare_snapshot_merge_for_tenant( string $tenant_id, array $incoming_cluster_ids ): void {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return;
		}

		$this->delete_stale_non_curated_rows( $normalized_tenant_id, $incoming_cluster_ids );
	}

	/**
	 * @param array<int,array<string,mixed>> $clusters
	 */
	public function merge_snapshot_batch_for_tenant( string $tenant_id, array $clusters, int $snapshot_version ): void {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return;
		}

		$normalized_clusters = $this->normalize_snapshot_clusters( $clusters );

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
				(cluster_uuid, tenant_id, label, curation_state, representative_thumb_path, representative_id, is_pinned, identity_count, snapshot_version, is_user_confirmed, created_at, updated_at, last_synced_at, suggested_label, suggested_label_source, suggested_label_confidence, suggested_target_cluster_id)
				VALUES (%s, %s, %s, %s, %s, %s, %d, %d, %d, %d, %s, %s, %s, NULLIF(%s, \'\'), NULLIF(%s, \'\'), NULLIF(%s, \'\'), NULLIF(%s, \'\'))
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
					last_synced_at = VALUES(last_synced_at),
					suggested_label = VALUES(suggested_label),
					suggested_label_source = VALUES(suggested_label_source),
					suggested_label_confidence = VALUES(suggested_label_confidence),
					suggested_target_cluster_id = VALUES(suggested_target_cluster_id)',
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
					trim( (string) ( $cluster['suggested_label'] ?? '' ) ),
					trim( (string) ( $cluster['suggested_label_source'] ?? '' ) ),
					isset( $cluster['suggested_label_confidence'] ) ? (string) (float) ( $cluster['suggested_label_confidence'] ) : '',
					trim( (string) ( $cluster['suggested_target_cluster_id'] ?? '' ) ),
				)
			);

			if ( is_string( $sql ) && '' !== $sql ) {
				// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
				$wpdb->query( $sql );
			}
		}
	}

	/**
	 * @param array<int,array<string,mixed>> $clusters
	 * @return array<int,array<string,mixed>>
	 */
	private function normalize_snapshot_clusters( array $clusters ): array {
		return array_values(
			array_filter(
				$clusters,
				static function ( $cluster ): bool {
					return '' !== trim( (string) ( $cluster['cluster_uuid'] ?? '' ) );
				}
			)
		);
	}

	/**
	 * @param array<int,array<string,mixed>> $clusters
	 * @return string[]
	 */
	private function extract_snapshot_cluster_ids( array $clusters ): array {
		return array_values(
			array_filter(
				array_map(
					static function ( array $cluster ): string {
						return trim( (string) ( $cluster['cluster_uuid'] ?? '' ) );
					},
					$clusters
				)
			)
		);
	}

	/**
	 * @param array<string,mixed> $filters
	 * @return array<int,array<string,mixed>>
	 */
	public function list_for_tenant( string $tenant_id, int $limit = ClustersRepositoryInterface::DEFAULT_LIST_LIMIT, int $offset = 0, array $filters = array() ): array {
		return $this->read_repository->list_for_tenant( $tenant_id, $limit, $offset, $filters );
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function list_labels( string $tenant_id, string $search = '', int $limit = self::DEFAULT_LIST_LIMIT ): array {
		return $this->read_repository->list_labels( $tenant_id, $search, $limit );
	}

	public function has_projection_rows_for_tenant( string $tenant_id ): bool {
		return $this->read_repository->has_projection_rows_for_tenant( $tenant_id );
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function list_top_unlabeled( string $tenant_id, int $limit = 10 ): array {
		return $this->read_repository->list_top_unlabeled( $tenant_id, $limit );
	}

	public function count_top_unlabeled_singletons( string $tenant_id ): int {
		return $this->read_repository->count_top_unlabeled_singletons( $tenant_id );
	}

	/**
	 * @return array<string,mixed>|null
	 */
	public function find_by_uuid( string $cluster_uuid ): ?array {
		return $this->read_repository->find_by_uuid( $cluster_uuid );
	}

	public function update_label( string $cluster_uuid, string $label, bool $mark_user_confirmed = true ): int {
		return $this->curation_writer->update_label( $cluster_uuid, $label, $mark_user_confirmed );
	}

	public function dismiss( string $cluster_uuid ): int {
		return $this->curation_writer->dismiss( $cluster_uuid );
	}

	public function update_identity_count( string $cluster_uuid, int $identity_count ): int {
		return $this->curation_writer->update_identity_count( $cluster_uuid, $identity_count );
	}

	public function update_representative_state( string $cluster_uuid, ?string $representative_id, bool $is_pinned, bool $is_local_curation = true ): int {
		return $this->curation_writer->update_representative_state( $cluster_uuid, $representative_id, $is_pinned, $is_local_curation );
	}

	public function create_local_cluster( string $tenant_id, string $cluster_uuid, string $label, int $identity_count = 1 ): int {
		return $this->projection_writer->create_local_cluster( $tenant_id, $cluster_uuid, $label, $identity_count );
	}

	public function upsert_projection_cluster( string $tenant_id, string $cluster_uuid, string $label, int $identity_count, int $snapshot_version, ?string $representative_thumb_path = null, ?string $representative_id = null, bool $is_pinned = false ): int {
		return $this->projection_writer->upsert_projection_cluster( $tenant_id, $cluster_uuid, $label, $identity_count, $snapshot_version, $representative_thumb_path, $representative_id, $is_pinned );
	}

	public function update_projection_cluster( string $cluster_uuid, int $identity_count, int $snapshot_version, ?string $representative_thumb_path = null, ?string $representative_id = null, bool $is_pinned = false ): int {
		return $this->projection_writer->update_projection_cluster( $cluster_uuid, $identity_count, $snapshot_version, $representative_thumb_path, $representative_id, $is_pinned );
	}

	public function undismiss( string $cluster_uuid ): int {
		return $this->curation_writer->undismiss( $cluster_uuid );
	}

	/**
	 * @return array<string,array<string,mixed>>
	 */
	public function get_curated_clusters_for_tenant( string $tenant_id ): array {
		return $this->read_repository->get_curated_clusters_for_tenant( $tenant_id );
	}

	public function reset_curation( string $cluster_uuid, string $tenant_id ): int {
		return $this->curation_writer->reset_curation( $cluster_uuid, $tenant_id );
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
