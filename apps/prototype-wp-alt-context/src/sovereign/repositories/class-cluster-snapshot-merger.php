<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/trait-prepares-sql-queries.php';
require_once __DIR__ . '/class-cluster-curation-writer.php';
require_once __DIR__ . '/class-cluster-projection-writer.php';
require_once __DIR__ . '/../../support/trait-detects-system-defined-labels.php';
require_once dirname( __DIR__, 2 ) . '/api/services/class-person-resolution-service.php';

use AltContext\Api\Services\PersonResolutionService;
use AltContext\Support\DetectsSystemDefinedLabels;

use function absint;
use function array_chunk;
use function array_fill_keys;
use function array_filter;
use function array_key_exists;
use function array_map;
use function array_unique;
use function array_values;
use function count;
use function gmdate;
use function in_array;
use function is_array;
use function is_bool;
use function is_int;
use function is_numeric;
use function is_object;
use function is_string;
use function is_wp_error;
use function max;
use function method_exists;
use function preg_match;
use function sprintf;
use function str_replace;
use function trim;

class ClusterSnapshotMerger {
	use DetectsSystemDefinedLabels;
	use PreparesSqlQueries;

	private string $table_name;

	public function __construct( string $table_name ) {
		$this->table_name = $table_name;
	}

	/**
	 * @param array<int,array<string,mixed>>|array<string,mixed> $clusters Cluster list or envelope with completeness flags.
	 * @return array{tombstoned_clusters:int,tombstoned_members:int,preserved_curated:int}
	 * @throws \RuntimeException When a snapshot write returns false.
	 */
	public function merge_snapshot_for_tenant( string $tenant_id, array $clusters, int $snapshot_version, bool $is_complete = false ): array {
		$parsed              = $this->parse_snapshot_clusters_payload( $clusters );
		$normalized_clusters = $this->normalize_snapshot_clusters( $parsed['clusters'] );
		$incoming_ids        = $this->extract_snapshot_cluster_ids( $normalized_clusters );
		$complete            = $is_complete || $parsed['is_complete'];

		$counts = $this->prepare_snapshot_merge_for_tenant( $tenant_id, $incoming_ids, $complete );

		foreach ( array_chunk( $normalized_clusters, ClustersRepositoryInterface::MAX_SNAPSHOT_MERGE_BATCH ) as $cluster_batch ) {
			$this->merge_snapshot_batch_for_tenant( $tenant_id, $cluster_batch, $snapshot_version );
		}

		return $counts;
	}

	/**
	 * @param string[] $incoming_cluster_ids
	 * @return array{tombstoned_clusters:int,tombstoned_members:int,preserved_curated:int}
	 * @throws \RuntimeException When a tombstone delete returns false.
	 */
	public function prepare_snapshot_merge_for_tenant( string $tenant_id, array $incoming_cluster_ids, bool $is_complete = false ): array {
		$empty_counts = array(
			'tombstoned_clusters' => 0,
			'tombstoned_members'  => 0,
			'preserved_curated'   => 0,
		);

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return $empty_counts;
		}

		if ( ! $is_complete ) {
			return $empty_counts;
		}

		return $this->tombstone_absent_clusters_for_tenant( $normalized_tenant_id, $incoming_cluster_ids );
	}

	/**
	 * @param array<int,array<string,mixed>> $clusters
	 * @throws \RuntimeException When a snapshot upsert query returns false.
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

			$incoming_label = $this->normalize_label( $cluster );
			$existing       = $this->load_existing_cluster( $cluster_uuid, $normalized_tenant_id );
			$cleared_label  = trim( (string) ( $existing['label_cleared_label'] ?? '' ) );
			$cleared_rev    = is_numeric( $existing['label_cleared_revision'] ?? null )
				? (int) $existing['label_cleared_revision']
				: 0;
			$keep_cleared = '' !== $cleared_label && $incoming_label === $cleared_label;
			$label        = $keep_cleared ? null : $incoming_label;
			$persisted_cleared_label = $keep_cleared ? $cleared_label : '';
			$persisted_cleared_rev   = $keep_cleared ? $cleared_rev : 0;
			$thumb_path              = $this->resolve_representative_thumb_path( $cluster, $cluster_uuid );
			$inserted_at             = $now_utc;
			$export                  = ClusterProjectionWriter::normalize_snapshot_export( $cluster );

			// Tombstone is decided in PHP (cleared-label match). SQL stays dumb.
			$sql = $this->prepare_query(
				'INSERT INTO %i
				(cluster_uuid, tenant_id, label, label_cleared_label, label_cleared_revision, curation_state, representative_thumb_path, representative_id, is_pinned, identity_count, snapshot_version, is_user_confirmed, created_at, updated_at, last_synced_at, suggested_label, suggested_label_source, suggested_label_confidence, suggested_target_cluster_id, representative_quality, quality_components, representative_media_id, undoable_merge_receipt_id)
				VALUES (%s, %s, NULLIF(%s, \'\'), %s, %d, %s, %s, %s, %d, %d, %d, %d, %s, %s, %s, NULLIF(%s, \'\'), NULLIF(%s, \'\'), NULLIF(%s, \'\'), NULLIF(%s, \'\'), NULLIF(%s, \'\'), NULLIF(%s, \'\'), NULLIF(%s, \'\'), NULLIF(%s, \'\'))
				ON DUPLICATE KEY UPDATE
					label = IF(is_user_confirmed = 1, label, VALUES(label)),
					label_cleared_label = IF(is_user_confirmed = 1, label_cleared_label, VALUES(label_cleared_label)),
					label_cleared_revision = IF(is_user_confirmed = 1, label_cleared_revision, VALUES(label_cleared_revision)),
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
					suggested_target_cluster_id = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(suggested_target_cluster_id), suggested_target_cluster_id),
					representative_quality = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(representative_quality), representative_quality),
					quality_components = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(quality_components), quality_components),
					representative_media_id = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(representative_media_id), representative_media_id),
					undoable_merge_receipt_id = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(undoable_merge_receipt_id), undoable_merge_receipt_id)',
				array(
					$this->table_name,
					$cluster_uuid,
					$normalized_tenant_id,
					null === $label ? '' : $label,
					$persisted_cleared_label,
					$persisted_cleared_rev,
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
					$export['representative_quality'],
					$export['quality_components'],
					$export['representative_media_id'],
					$export['undoable_merge_receipt_id'],
				)
			);

			if ( is_string( $sql ) && '' !== $sql ) {
				// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
				$query_result = $wpdb->query( $sql );
				$this->throw_on_write_failure( $query_result, 'upsert' );
			}
		}

		$this->backfill_persons_for_human_labels( $normalized_tenant_id, $normalized_clusters );
	}

	/**
	 * Bind a person from the STORED label after upsert (skip null/empty/reserved).
	 *
	 * @param array<int,array<string,mixed>> $clusters
	 */
	private function backfill_persons_for_human_labels( string $tenant_id, array $clusters ): void {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_row' ) ) {
			return;
		}

		$resolver = new PersonResolutionService();
		$writer   = new ClusterCurationWriter( $this->table_name );
		foreach ( $clusters as $cluster ) {
			$cluster_uuid = trim( (string) ( $cluster['cluster_uuid'] ?? '' ) );
			if ( '' === $cluster_uuid ) {
				continue;
			}

			$stored_sql = $this->prepare_query(
				'SELECT label, person_id FROM %i WHERE cluster_uuid = %s AND tenant_id = %s',
				array(
					$this->table_name,
					$cluster_uuid,
					$tenant_id,
				)
			);
			if ( ! is_string( $stored_sql ) || '' === $stored_sql ) {
				continue;
			}

			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
			$stored = $wpdb->get_row( $stored_sql, ARRAY_A );
			if ( ! is_array( $stored ) ) {
				continue;
			}

			if ( is_numeric( $stored['person_id'] ?? null ) && (int) $stored['person_id'] > 0 ) {
				continue;
			}

			$stored_label = trim( (string) ( $stored['label'] ?? '' ) );
			if ( '' === $stored_label || $this->is_reserved_label_shape( $stored_label ) ) {
				continue;
			}

			$resolved = $resolver->resolve_for_automatic_bind(
				$stored_label,
				$tenant_id,
				$cluster_uuid,
				static function (): bool {
					return true;
				}
			);
			if ( is_wp_error( $resolved ) ) {
				continue;
			}

			$bound = $writer->bind_person_to_cluster( $cluster_uuid, (int) $resolved['person_id'], $tenant_id, false );
			if ( false === $bound ) {
				continue;
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
	 * @param array<int|string,mixed> $clusters
	 * @return array{clusters:array<int,array<string,mixed>>,is_complete:bool}
	 */
	private function parse_snapshot_clusters_payload( array $clusters ): array {
		$has_nested_clusters = isset( $clusters['clusters'] ) && is_array( $clusters['clusters'] );
		if ( $has_nested_clusters || $this->has_completeness_key( $clusters ) ) {
			$nested = $has_nested_clusters ? $clusters['clusters'] : array();

			return array(
				'clusters'    => is_array( $nested ) ? $nested : array(),
				'is_complete' => $this->payload_declares_complete( $clusters ),
			);
		}

		return array(
			'clusters'    => $clusters,
			'is_complete' => false,
		);
	}

	/**
	 * @param array<string,mixed> $payload
	 */
	private function has_completeness_key( array $payload ): bool {
		return array_key_exists( 'is_complete', $payload )
			|| array_key_exists( 'complete', $payload )
			|| array_key_exists( 'is_full', $payload )
			|| array_key_exists( 'has_more', $payload )
			|| array_key_exists( 'partial', $payload );
	}

	/**
	 * @param array<string,mixed> $payload
	 */
	private function payload_declares_complete( array $payload ): bool {
		if ( array_key_exists( 'is_complete', $payload ) ) {
			return $this->to_bool( $payload['is_complete'] );
		}

		if ( array_key_exists( 'complete', $payload ) ) {
			return $this->to_bool( $payload['complete'] );
		}

		if ( array_key_exists( 'is_full', $payload ) ) {
			return $this->to_bool( $payload['is_full'] );
		}

		if ( array_key_exists( 'has_more', $payload ) ) {
			return ! $this->to_bool( $payload['has_more'] );
		}

		if ( array_key_exists( 'partial', $payload ) ) {
			return ! $this->to_bool( $payload['partial'] );
		}

		return false;
	}

	private function to_bool( mixed $value ): bool {
		if ( is_bool( $value ) ) {
			return $value;
		}

		if ( is_numeric( $value ) ) {
			return (int) $value === 1;
		}

		return in_array( trim( (string) $value ), array( '1', 'true', 'yes', 'on' ), true );
	}

	/**
	 * @param string[] $incoming_cluster_ids
	 * @return array{tombstoned_clusters:int,tombstoned_members:int,preserved_curated:int}
	 * @throws \RuntimeException When a tombstone delete returns false.
	 */
	private function tombstone_absent_clusters_for_tenant( string $tenant_id, array $incoming_cluster_ids ): array {
		$counts = array(
			'tombstoned_clusters' => 0,
			'tombstoned_members'  => 0,
			'preserved_curated'   => 0,
		);

		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_results' ) || ! method_exists( $wpdb, 'delete' ) ) {
			return $counts;
		}

		$local_sql = $this->prepare_query(
			'SELECT cluster_uuid, is_user_confirmed, person_id, curation_state FROM %i WHERE tenant_id = %s',
			array(
				$this->table_name,
				$tenant_id,
			)
		);
		if ( ! is_string( $local_sql ) || '' === $local_sql ) {
			return $counts;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$local_rows = $wpdb->get_results( $local_sql, ARRAY_A );
		if ( ! is_array( $local_rows ) ) {
			return $counts;
		}

		$incoming_set = array_fill_keys( $this->sanitize_uuid_list( $incoming_cluster_ids ), true );
		$absent_ids   = array();
		foreach ( $local_rows as $row ) {
			if ( ! is_array( $row ) ) {
				continue;
			}

			$cluster_uuid = trim( (string) ( $row['cluster_uuid'] ?? '' ) );
			if ( '' === $cluster_uuid || isset( $incoming_set[ $cluster_uuid ] ) ) {
				continue;
			}

			if ( ! $this->is_uncurated_cluster_row( $row ) ) {
				++$counts['preserved_curated'];
				continue;
			}

			$absent_ids[] = $cluster_uuid;
		}

		$absent_ids = $this->sanitize_uuid_list( $absent_ids );
		if ( empty( $absent_ids ) ) {
			return $counts;
		}

		$members_table   = $this->resolve_related_table_name( 'acx_identity_members' );
		$conflicts_table = $this->resolve_related_table_name( 'acx_sync_conflicts' );

		foreach ( $absent_ids as $cluster_uuid ) {
			$deleted_members = $wpdb->delete(
				$members_table,
				array(
					'cluster_uuid' => $cluster_uuid,
				)
			);
			$this->throw_on_write_failure( $deleted_members, 'member delete' );
			if ( is_int( $deleted_members ) && $deleted_members > 0 ) {
				$counts['tombstoned_members'] += $deleted_members;
			}

			$deleted_clusters = $wpdb->delete(
				$this->table_name,
				array(
					'cluster_uuid' => $cluster_uuid,
					'tenant_id'    => $tenant_id,
				)
			);
			$this->throw_on_write_failure( $deleted_clusters, 'cluster delete' );
			if ( is_int( $deleted_clusters ) && $deleted_clusters > 0 ) {
				$counts['tombstoned_clusters'] += $deleted_clusters;
			}

			$deleted_conflicts = $wpdb->delete(
				$conflicts_table,
				array(
					'tenant_id'     => $tenant_id,
					'conflict_code' => 'cluster_not_found',
					'entity_key'    => $cluster_uuid,
				)
			);
			$this->throw_on_write_failure( $deleted_conflicts, 'conflict delete' );
		}

		return $counts;
	}

	/**
	 * @param mixed $result
	 * @throws \RuntimeException When $result is false.
	 */
	private function throw_on_write_failure( $result, string $surface ): void {
		if ( false !== $result ) {
			return;
		}

		global $wpdb;

		$error = '';
		if ( isset( $wpdb ) && is_object( $wpdb ) ) {
			$raw   = $wpdb->last_error ?? '';
			$error = is_string( $raw ) ? trim( $raw ) : '';
		}

		$message = '' !== $error
			? sprintf( 'Snapshot merger %s failed: %s', $surface, $error )
			: sprintf( 'Snapshot merger %s failed', $surface );

		// phpcs:ignore WordPress.Security.EscapeOutput.ExceptionNotEscaped -- Internal diagnostic message; never rendered as output.
		throw new \RuntimeException( $message );
	}

	/**
	 * @param array<string,mixed> $row
	 */
	private function is_uncurated_cluster_row( array $row ): bool {
		$confirmed = $row['is_user_confirmed'] ?? 0;
		if ( is_bool( $confirmed ) ) {
			$confirmed_flag = $confirmed ? 1 : 0;
		} else {
			$confirmed_flag = in_array( trim( (string) $confirmed ), array( '1', 'true', 'yes', 'on' ), true ) ? 1 : 0;
		}
		if ( 1 === $confirmed_flag ) {
			return false;
		}

		$person_id = $row['person_id'] ?? null;
		if ( is_numeric( $person_id ) && (int) $person_id > 0 ) {
			return false;
		}

		$state = trim( (string) ( $row['curation_state'] ?? '' ) );

		return '' === $state || 'uncurated' === $state;
	}

	private function resolve_related_table_name( string $logical_suffix ): string {
		return str_replace( 'acx_clusters', $logical_suffix, $this->table_name );
	}

	/**
	 * @return array<string,mixed>|null
	 */
	private function load_existing_cluster( string $cluster_uuid, string $tenant_id ): ?array {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_row' ) ) {
			return null;
		}

		$sql = $this->prepare_query(
			'SELECT label, person_id, is_user_confirmed, label_cleared_revision, label_cleared_label, snapshot_version FROM %i WHERE cluster_uuid = %s AND tenant_id = %s',
			array( $this->table_name, $cluster_uuid, $tenant_id )
		);
		if ( ! is_string( $sql ) || '' === $sql ) {
			return null;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$row = $wpdb->get_row( $sql, ARRAY_A );
		return is_array( $row ) ? $row : null;
	}

	/**
	 * @param array<string,mixed> $cluster
	 */
	private function normalize_label( array $cluster ): ?string {
		$label = trim( (string) ( $cluster['label'] ?? $cluster['cluster_label'] ?? '' ) );
		return '' === $label ? null : $label;
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
