<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once dirname( __DIR__, 2 ) . '/api/class-blob-url-rewriter.php';
require_once dirname( __DIR__, 2 ) . '/api/services/class-person-resolution-service.php';
require_once __DIR__ . '/interface-sync-state-repository.php';
require_once __DIR__ . '/class-sync-state-repository.php';
require_once __DIR__ . '/trait-prepares-sql-queries.php';

use AltContext\Api\BlobUrlRewriter;
use AltContext\Api\Services\PersonResolutionService;

class RosterEntryProjectionRepository {
	use PreparesSqlQueries;

	private SyncStateRepositoryInterface $sync_state_repository;

	public function __construct( ?SyncStateRepositoryInterface $sync_state_repository = null ) {
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function list_entries( string $tenant_id ): array {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! \is_object( $wpdb ) || ! \method_exists( $wpdb, 'prepare' ) || ! \method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$table_persons = $wpdb->prefix . 'acx_persons';
		$sql           = $this->prepare_query(
			'SELECT * FROM %i ORDER BY name ASC',
			array( $table_persons )
		);
		if ( ! \is_string( $sql ) || '' === $sql ) {
			return array();
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$results = $wpdb->get_results( $sql, ARRAY_A );

		if ( ! \is_array( $results ) ) {
			return array();
		}

		// Survivor policy: lowest stable id is primary; aggregates are unions of member rows.
		$grouped_rows            = $this->group_rows_by_normalized_name( $results );
		$projection_refreshed_at = $this->sync_state_repository->get_last_updated( $tenant_id );
		$projection_status       = $this->resolve_projection_status( $tenant_id, $projection_refreshed_at );
		$source_version          = $this->sync_state_repository->get_snapshot_version( $tenant_id );
		$person_ids              = $this->collect_person_ids_from_groups( $grouped_rows );
		$cluster_rows_by_person  = $this->list_projected_cluster_rows_by_person( $person_ids );
		$instance_rows_by_cluster = $this->list_projected_instance_rows_by_cluster( $this->collect_cluster_uuids( $cluster_rows_by_person ) );

		return \array_map(
			function ( array $group ) use ( $projection_refreshed_at, $projection_status, $source_version, $cluster_rows_by_person, $instance_rows_by_cluster ): array {
				$primary = $group['primary'];
				$tags    = array();
				if ( isset( $primary['tags'] ) && \is_string( $primary['tags'] ) ) {
					$decoded = \json_decode( $primary['tags'], true );
					$tags    = \is_array( $decoded ) ? $decoded : array();
				}

				$member_ids = $group['member_ids'];
				$cluster_rows = array();
				foreach ( $member_ids as $member_id ) {
					foreach ( $cluster_rows_by_person[ $member_id ] ?? array() as $cluster_row ) {
						$cluster_rows[] = $cluster_row;
					}
				}
				$clusters = $this->map_projected_clusters_for_person(
					$cluster_rows,
					$instance_rows_by_cluster
				);
				$cluster_count = \count( $clusters );
				if ( 0 === $cluster_count ) {
					// Union of stored cluster_count values only when no projected clusters exist (rg-015).
					$cluster_count = 0;
					foreach ( $group['members'] as $member ) {
						if ( isset( $member['cluster_count'] ) ) {
							$cluster_count += (int) $member['cluster_count'];
						}
					}
				}

				return array(
					'id'                      => isset( $primary['id'] ) ? (int) $primary['id'] : 0,
					'person_uuid'             => \trim( (string) ( $primary['person_uuid'] ?? '' ) ),
					'name'                    => (string) ( $primary['name'] ?? '' ),
					'tags'                    => $tags,
					'cluster_count'           => $cluster_count,
					'clusters'                => $clusters,
					'queue_memberships'       => $this->union_queue_memberships( $group['members'] ),
					'updated_at'              => (string) ( $primary['updated_at'] ?? '' ),
					'source_version'          => $source_version,
					'projection_status'       => $projection_status,
					'projection_refreshed_at' => $projection_refreshed_at,
				);
			},
			$grouped_rows
		);
	}

	/**
	 * Group person rows by normalized_name. Lowest id is the primary survivor.
	 *
	 * @param array<int,array<string,mixed>> $results
	 * @return array<int,array{primary:array<string,mixed>,members:array<int,array<string,mixed>>,member_ids:array<int,int>}>
	 */
	private function group_rows_by_normalized_name( array $results ): array {
		$groups = array();

		foreach ( $results as $row ) {
			$key = $this->row_normalized_name( $row );
			if ( '' === $key ) {
				// Un-normalizable rows stay distinct so they cannot collapse incorrectly.
				$key = '__id:' . (string) ( isset( $row['id'] ) ? (int) $row['id'] : 0 );
			}
			if ( ! isset( $groups[ $key ] ) ) {
				$groups[ $key ] = array();
			}
			$groups[ $key ][] = $row;
		}

		$aggregated = array();
		foreach ( $groups as $members ) {
			\usort(
				$members,
				static function ( array $left, array $right ): int {
					return ( (int) ( $left['id'] ?? 0 ) ) <=> ( (int) ( $right['id'] ?? 0 ) );
				}
			);
			$member_ids = array();
			foreach ( $members as $member ) {
				$member_id = isset( $member['id'] ) ? (int) $member['id'] : 0;
				if ( $member_id > 0 ) {
					$member_ids[] = $member_id;
				}
			}
			$aggregated[] = array(
				'primary'    => $members[0],
				'members'    => $members,
				'member_ids' => $member_ids,
			);
		}

		// Stable list order by primary display name (matches pre-group ORDER BY name ASC).
		\usort(
			$aggregated,
			static function ( array $left, array $right ): int {
				return \strcmp( (string) ( $left['primary']['name'] ?? '' ), (string) ( $right['primary']['name'] ?? '' ) );
			}
		);

		return $aggregated;
	}

	/**
	 * @param array<string,mixed> $row
	 */
	private function row_normalized_name( array $row ): string {
		if ( isset( $row['normalized_name'] ) && \is_string( $row['normalized_name'] ) && '' !== \trim( $row['normalized_name'] ) ) {
			return \trim( $row['normalized_name'] );
		}

		return PersonResolutionService::normalize_name( (string) ( $row['name'] ?? '' ) );
	}

	/**
	 * @param array<int,array{member_ids:array<int,int>}> $grouped_rows
	 * @return array<int,int>
	 */
	private function collect_person_ids_from_groups( array $grouped_rows ): array {
		$person_ids = array();

		foreach ( $grouped_rows as $group ) {
			foreach ( $group['member_ids'] as $member_id ) {
				if ( $member_id > 0 ) {
					$person_ids[] = $member_id;
				}
			}
		}

		return \array_values( \array_unique( $person_ids ) );
	}

	/**
	 * @param array<int,array<string,mixed>> $members
	 * @return array<int,string>
	 */
	private function union_queue_memberships( array $members ): array {
		$union = array();

		foreach ( $members as $member ) {
			foreach ( $this->decode_string_list( $member['queue_memberships_json'] ?? $member['queue_memberships'] ?? array() ) as $queue ) {
				$union[ $queue ] = true;
			}
		}

		return \array_keys( $union );
	}

	/**
	 * @param array<int,array<int,array<string,mixed>>> $cluster_rows_by_person
	 * @return array<int,string>
	 */
	private function collect_cluster_uuids( array $cluster_rows_by_person ): array {
		$cluster_uuids = array();

		foreach ( $cluster_rows_by_person as $cluster_rows ) {
			foreach ( $cluster_rows as $cluster_row ) {
				$cluster_uuid = \trim( (string) ( $cluster_row['cluster_uuid'] ?? '' ) );
				if ( '' !== $cluster_uuid ) {
					$cluster_uuids[] = $cluster_uuid;
				}
			}
		}

		return \array_values( \array_unique( $cluster_uuids ) );
	}

	/**
	 * @param array<int,int> $person_ids
	 * @return array<int,array<int,array<string,mixed>>>
	 */
	private function list_projected_cluster_rows_by_person( array $person_ids ): array {
		global $wpdb;

		if ( array() === $person_ids || ! isset( $wpdb ) || ! \is_object( $wpdb ) || ! \method_exists( $wpdb, 'prepare' ) || ! \method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$table_clusters = $wpdb->prefix . 'acx_clusters';
		$placeholders   = \implode( ', ', \array_fill( 0, \count( $person_ids ), '%d' ) );
		$sql            = $this->prepare_query(
			"SELECT * FROM %i WHERE person_id IN ($placeholders) ORDER BY updated_at DESC",
			\array_merge( array( $table_clusters ), $person_ids )
		);
		if ( ! \is_string( $sql ) || '' === $sql ) {
			return array();
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );

		if ( ! \is_array( $rows ) ) {
			return array();
		}

		$cluster_rows_by_person = array();
		foreach ( $rows as $row ) {
			$person_id = isset( $row['person_id'] ) ? (int) $row['person_id'] : 0;
			if ( $person_id <= 0 ) {
				continue;
			}

			if ( ! isset( $cluster_rows_by_person[ $person_id ] ) ) {
				$cluster_rows_by_person[ $person_id ] = array();
			}

			$cluster_rows_by_person[ $person_id ][] = $row;
		}

		return $cluster_rows_by_person;
	}

	/**
	 * @param array<int,string> $cluster_uuids
	 * @return array<string,array<int,array<string,mixed>>>
	 */
	private function list_projected_instance_rows_by_cluster( array $cluster_uuids ): array {
		global $wpdb;

		if ( array() === $cluster_uuids || ! isset( $wpdb ) || ! \is_object( $wpdb ) || ! \method_exists( $wpdb, 'prepare' ) || ! \method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$table_members = $wpdb->prefix . 'acx_identity_members';
		$placeholders  = \implode( ', ', \array_fill( 0, \count( $cluster_uuids ), '%s' ) );
		$sql           = $this->prepare_query(
			"SELECT * FROM %i WHERE cluster_uuid IN ($placeholders) ORDER BY updated_at DESC",
			\array_merge( array( $table_members ), $cluster_uuids )
		);
		if ( ! \is_string( $sql ) || '' === $sql ) {
			return array();
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );

		if ( ! \is_array( $rows ) ) {
			return array();
		}

		$instance_rows_by_cluster = array();
		foreach ( $rows as $row ) {
			$cluster_uuid = \trim( (string) ( $row['cluster_uuid'] ?? '' ) );
			if ( '' === $cluster_uuid ) {
				continue;
			}

			if ( ! isset( $instance_rows_by_cluster[ $cluster_uuid ] ) ) {
				$instance_rows_by_cluster[ $cluster_uuid ] = array();
			}

			$instance_rows_by_cluster[ $cluster_uuid ][] = $row;
		}

		return $instance_rows_by_cluster;
	}

	/**
	 * @param array<int,array<string,mixed>> $cluster_rows
	 * @param array<string,array<int,array<string,mixed>>> $instance_rows_by_cluster
	 * @return array<int,array<string,mixed>>
	 */
	private function map_projected_clusters_for_person( array $cluster_rows, array $instance_rows_by_cluster ): array {
		return \array_map(
			function ( array $row ) use ( $instance_rows_by_cluster ): array {
				$cluster_uuid   = \trim( (string) ( $row['cluster_uuid'] ?? '' ) );
				$instance_rows  = $instance_rows_by_cluster[ $cluster_uuid ] ?? array();
				$instances      = \array_map( array( $this, 'map_projected_instance_row' ), $instance_rows );

				return array(
					'cluster_id'             => $cluster_uuid,
					'identity_count'         => isset( $row['identity_count'] ) ? (int) $row['identity_count'] : \count( $instances ),
					'representative_identity' => $this->resolve_representative_identity( \trim( (string) ( $row['representative_id'] ?? '' ) ), $instances ),
					'instances'              => $instances,
				);
			},
			$cluster_rows
		);
	}

	/**
	 * @param mixed $value
	 * @return array<int,string>
	 */
	private function decode_string_list( mixed $value ): array {
		if ( \is_array( $value ) ) {
			return \array_values(
				\array_filter(
					\array_map( static fn ( $item ): string => \trim( (string) $item ), $value ),
					static fn ( string $item ): bool => '' !== $item
				)
			);
		}

		if ( ! \is_string( $value ) || '' === \trim( $value ) ) {
			return array();
		}

		$decoded = \json_decode( $value, true );
		if ( ! \is_array( $decoded ) ) {
			return array();
		}

		return $this->decode_string_list( $decoded );
	}

	/**
	 * @param array<string,mixed> $row
	 * @return array<string,mixed>
	 */
	private function map_projected_instance_row( array $row ): array {
		// Resolve media_url and bbox together so original_image pixel rects are
		// never paired with a thumb_path face crop (coordinate-space trap).
		$resolved = $this->resolve_projected_media( $row );

		$similarity = null;
		if ( isset( $row['similarity'] ) && '' !== \trim( (string) $row['similarity'] ) ) {
			$similarity = (float) $row['similarity'];
		}

		$similarity_threshold = null;
		if ( isset( $row['similarity_threshold'] ) && '' !== \trim( (string) $row['similarity_threshold'] ) ) {
			$similarity_threshold = (float) $row['similarity_threshold'];
		}

		return array(
			'identity_id'           => \trim( (string) ( $row['identity_uuid'] ?? '' ) ),
			'media_id'              => isset( $row['attachment_id'] ) ? (int) $row['attachment_id'] : 0,
			'media_url'             => $resolved['media_url'],
			'bbox'                  => $resolved['bbox'],
			'similarity'            => $similarity,
			'similarity_threshold'  => $similarity_threshold,
		);
	}

	/**
	 * Resolve media_url and a matching null-preserving pixel bbox.
	 *
	 * Bbox is emitted only when media_url came from wp_get_attachment_url
	 * (original full-size image, coordinate_space original_image). On the
	 * thumb_path fallback path bbox is always null — the stored thumb is
	 * already the best available face image and is not original_image space.
	 *
	 * @param array<string,mixed> $row
	 * @return array{media_url:?string,bbox:?array{x:int,y:int,width:int,height:int}}
	 */
	private function resolve_projected_media( array $row ): array {
		$media_id = isset( $row['attachment_id'] ) ? (int) $row['attachment_id'] : 0;
		if ( $media_id > 0 && \function_exists( 'wp_get_attachment_url' ) ) {
			$attachment_url = \wp_get_attachment_url( $media_id );
			if ( \is_string( $attachment_url ) && '' !== \trim( $attachment_url ) ) {
				return array(
					'media_url' => $attachment_url,
					'bbox'      => $this->extract_projected_bbox_pixels( $row['bbox_json'] ?? null ),
				);
			}
		}

		return array(
			'media_url' => $this->resolve_thumb_path_media_url( $row ),
			'bbox'      => null,
		);
	}

	/**
	 * @param array<string,mixed> $row
	 */
	private function resolve_thumb_path_media_url( array $row ): ?string {
		$thumb_path = isset( $row['thumb_path'] ) ? \trim( (string) $row['thumb_path'] ) : '';
		if ( '' === $thumb_path ) {
			return null;
		}

		$rewritten = BlobUrlRewriter::rewrite_string( $thumb_path );
		if ( '' === \trim( $rewritten ) ) {
			return null;
		}

		if ( $rewritten !== $thumb_path || \str_starts_with( $rewritten, 'http://' ) || \str_starts_with( $rewritten, 'https://' ) || \str_starts_with( $rewritten, '/' ) ) {
			return $rewritten;
		}

		return null;
	}

	/**
	 * Null-preserving pixel extraction aligned with MapsResponseFields::extract_bbox_pixels.
	 *
	 * extract_bbox_pixels returns a zero rect for absent/undecodable input; that is
	 * wrong for roster (0×0 crops to a blank square). This wrapper returns null
	 * instead, then reuses the same pixels-or-decoded unwrap + absint shaping.
	 *
	 * @param mixed $bbox_json
	 * @return array{x:int,y:int,width:int,height:int}|null
	 */
	private function extract_projected_bbox_pixels( mixed $bbox_json ): ?array {
		if ( ! \is_string( $bbox_json ) || '' === \trim( $bbox_json ) ) {
			return null;
		}

		$decoded = \json_decode( $bbox_json, true );
		if ( ! \is_array( $decoded ) ) {
			return null;
		}

		// Same fallback as MapsResponseFields::extract_bbox_pixels: pixels wrapper
		// or legacy bare {x,y,width,height} payload.
		$pixels = $decoded['pixels'] ?? $decoded;
		if ( ! \is_array( $pixels ) ) {
			return null;
		}

		$rect = array(
			'x'      => \absint( $pixels['x'] ?? 0 ),
			'y'      => \absint( $pixels['y'] ?? 0 ),
			'width'  => \absint( $pixels['width'] ?? 0 ),
			'height' => \absint( $pixels['height'] ?? 0 ),
		);

		// Zero-area is not a face. Pixels-less partial envelopes (normalized only)
		// absint-default to {0,0,0,0}; that would reach IdentityThumbnail as a
		// "valid" bbox and blank-square the canvas. Null → untouched-source path.
		if ( $rect['width'] <= 0 || $rect['height'] <= 0 ) {
			return null;
		}

		return $rect;
	}

	/**
	 * @param array<int,array<string,mixed>> $instances
	 * @return array<string,mixed>|null
	 */
	private function resolve_representative_identity( string $representative_id, array $instances ): ?array {
		$normalized_representative_id = \trim( $representative_id );
		if ( '' === $normalized_representative_id ) {
			return $instances[0] ?? null;
		}

		foreach ( $instances as $instance ) {
			if ( $normalized_representative_id === ( $instance['identity_id'] ?? '' ) ) {
				return $instance;
			}
		}

		return $instances[0] ?? null;
	}

	private function resolve_projection_status( string $tenant_id, ?string $projection_refreshed_at ): string {
		$last_sync_result = $this->sync_state_repository->get_last_sync_result( $tenant_id );
		// Use SyncStateRepository::SYNC_RESULT_* vocabulary [sr-007]. 'skipped' is
		// not in normalize_sync_result()'s allow-list and is unreachable here.
		if ( SyncStateRepository::SYNC_RESULT_FAILED === $last_sync_result
			|| SyncStateRepository::SYNC_RESULT_UNREACHABLE === $last_sync_result ) {
			return 'failed';
		}

		if ( $this->sync_state_repository->get_pending_curation_operations( $tenant_id ) > 0
			|| $this->sync_state_repository->get_pending_topology_commands( $tenant_id ) > 0 ) {
			return 'refreshing';
		}

		// HARM-BR-03: rekey / threshold write resync_required; treat as stale so
		// RosterPage (projectionStatus !== 'current') surfaces the invalid projection.
		if ( null === $projection_refreshed_at
			|| SyncStateRepository::SYNC_RESULT_RESYNC_REQUIRED === $last_sync_result ) {
			return 'stale';
		}

		return 'current';
	}
}
