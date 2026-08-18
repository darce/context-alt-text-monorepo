<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/trait-prepares-sql-queries.php';
require_once __DIR__ . '/../../support/trait-detects-system-defined-labels.php';
require_once dirname( __DIR__, 2 ) . '/api/services/class-person-resolution-service.php';

use AltContext\Api\Services\PersonResolutionService;
use AltContext\Support\DetectsSystemDefinedLabels;

use function absint;
use function array_chunk;
use function array_fill;
use function array_filter;
use function array_map;
use function array_merge;
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
use function is_wp_error;
use function max;
use function method_exists;
use function preg_match;
use function sprintf;
use function trim;

class ClusterSnapshotMerger {
	use DetectsSystemDefinedLabels;
	use PreparesSqlQueries;

	private string $table_name;

	public function __construct( string $table_name ) {
		$this->table_name = $table_name;
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

			// COR-1: gate each overwritten data column on the incoming version so
			// an out-of-order (older) snapshot cannot regress newer projection data.
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
					representative_thumb_path = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(representative_thumb_path), representative_thumb_path),
					representative_id = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(representative_id), representative_id),
					is_pinned = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(is_pinned), is_pinned),
					identity_count = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(identity_count), identity_count),
					snapshot_version = GREATEST(snapshot_version, VALUES(snapshot_version)),
					updated_at = VALUES(updated_at),
					last_synced_at = VALUES(last_synced_at),
					suggested_label = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(suggested_label), suggested_label),
					suggested_label_source = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(suggested_label_source), suggested_label_source),
					suggested_label_confidence = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(suggested_label_confidence), suggested_label_confidence),
					suggested_target_cluster_id = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(suggested_target_cluster_id), suggested_target_cluster_id)',
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

		$this->backfill_persons_for_human_labels( $normalized_tenant_id, $normalized_clusters );
	}

	/**
	 * Bind a person for each batch cluster whose label is human and person_id is null.
	 *
	 * @param array<int,array<string,mixed>> $clusters
	 */
	private function backfill_persons_for_human_labels( string $tenant_id, array $clusters ): void {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_var' ) || ! method_exists( $wpdb, 'update' ) ) {
			return;
		}

		$resolver = new PersonResolutionService();
		foreach ( $clusters as $cluster ) {
			$cluster_uuid = trim( (string) ( $cluster['cluster_uuid'] ?? '' ) );
			$label        = $this->normalize_label( $cluster );
			if ( '' === $cluster_uuid || '' === $label || $this->is_reserved_label_shape( $label ) ) {
				continue;
			}

			$person_id_sql = $this->prepare_query(
				'SELECT person_id FROM %i WHERE cluster_uuid = %s AND tenant_id = %s',
				array(
					$this->table_name,
					$cluster_uuid,
					$tenant_id,
				)
			);
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
			$existing_person_id = is_string( $person_id_sql ) ? $wpdb->get_var( $person_id_sql ) : null;
			if ( is_numeric( $existing_person_id ) && (int) $existing_person_id > 0 ) {
				continue;
			}

			$resolved = $resolver->resolve_or_create(
				$label,
				static function (): bool {
					return true;
				}
			);
			if ( is_wp_error( $resolved ) ) {
				continue;
			}

			$wpdb->update(
				$this->table_name,
				array(
					'person_id'  => $resolved['person_id'],
					'updated_at' => gmdate( 'Y-m-d H:i:s' ),
				),
				array( 'cluster_uuid' => $cluster_uuid ),
				array( '%d', '%s' ),
				array( '%s' )
			);
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
