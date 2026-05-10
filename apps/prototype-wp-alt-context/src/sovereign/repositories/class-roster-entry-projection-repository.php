<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/interface-sync-state-repository.php';
require_once __DIR__ . '/class-sync-state-repository.php';

class RosterEntryProjectionRepository {
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
		$results       = $wpdb->get_results(
			$wpdb->prepare(
				'SELECT * FROM %i ORDER BY name ASC',
				$table_persons
			),
			ARRAY_A
		);

		if ( ! \is_array( $results ) ) {
			return array();
		}

		$projection_refreshed_at = $this->sync_state_repository->get_last_updated( $tenant_id );
		$projection_status       = $this->resolve_projection_status( $tenant_id, $projection_refreshed_at );
		$source_version          = $this->sync_state_repository->get_snapshot_version( $tenant_id );
		$person_ids              = $this->collect_person_ids( $results );
		$cluster_rows_by_person  = $this->list_projected_cluster_rows_by_person( $person_ids );
		$instance_rows_by_cluster = $this->list_projected_instance_rows_by_cluster( $this->collect_cluster_uuids( $cluster_rows_by_person ) );

		return \array_map(
			function ( array $row ) use ( $projection_refreshed_at, $projection_status, $source_version, $cluster_rows_by_person, $instance_rows_by_cluster ): array {
				$tags = array();
				if ( isset( $row['tags'] ) && \is_string( $row['tags'] ) ) {
					$decoded = \json_decode( $row['tags'], true );
					$tags    = \is_array( $decoded ) ? $decoded : array();
				}

				$person_id = isset( $row['id'] ) ? (int) $row['id'] : 0;
				$clusters  = $this->map_projected_clusters_for_person(
					$cluster_rows_by_person[ $person_id ] ?? array(),
					$instance_rows_by_cluster
				);
				$cluster_count = \count( $clusters );
				if ( 0 === $cluster_count && isset( $row['cluster_count'] ) ) {
					$cluster_count = (int) $row['cluster_count'];
				}

				return array(
					'id'                     => isset( $row['id'] ) ? (int) $row['id'] : 0,
					'person_uuid'            => \trim( (string) ( $row['person_uuid'] ?? '' ) ),
					'name'                   => (string) ( $row['name'] ?? '' ),
					'tags'                   => $tags,
					'cluster_count'          => $cluster_count,
					'clusters'               => $clusters,
					'queue_memberships'      => $this->decode_string_list( $row['queue_memberships_json'] ?? $row['queue_memberships'] ?? array() ),
					'updated_at'             => (string) ( $row['updated_at'] ?? '' ),
					'source_version'         => $source_version,
					'projection_status'      => $projection_status,
					'projection_refreshed_at' => $projection_refreshed_at,
				);
			},
			$results
		);
	}

	/**
	 * @param array<int,array<string,mixed>> $results
	 * @return array<int,int>
	 */
	private function collect_person_ids( array $results ): array {
		$person_ids = array();

		foreach ( $results as $row ) {
			$person_id = isset( $row['id'] ) ? (int) $row['id'] : 0;
			if ( $person_id > 0 ) {
				$person_ids[] = $person_id;
			}
		}

		return \array_values( \array_unique( $person_ids ) );
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
		$query          = $wpdb->prepare(
			\sprintf( 'SELECT * FROM %%i WHERE person_id IN (%s) ORDER BY updated_at DESC', $placeholders ),
			$table_clusters,
			...$person_ids
		);
		$rows           = $wpdb->get_results( $query, ARRAY_A );

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
		$query         = $wpdb->prepare(
			\sprintf( 'SELECT * FROM %%i WHERE cluster_uuid IN (%s) ORDER BY updated_at DESC', $placeholders ),
			$table_members,
			...$cluster_uuids
		);
		$rows          = $wpdb->get_results( $query, ARRAY_A );

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
		$bbox = null;
		if ( isset( $row['bbox_json'] ) && \is_string( $row['bbox_json'] ) ) {
			$decoded_bbox = \json_decode( $row['bbox_json'], true );
			$bbox = \is_array( $decoded_bbox ) ? $decoded_bbox : null;
		}

		$similarity = null;
		if ( isset( $row['similarity'] ) && '' !== \trim( (string) $row['similarity'] ) ) {
			$similarity = (float) $row['similarity'];
		}

		return array(
			'identity_id' => \trim( (string) ( $row['identity_uuid'] ?? '' ) ),
			'media_id'    => isset( $row['attachment_id'] ) ? (int) $row['attachment_id'] : 0,
			'media_url'   => isset( $row['thumb_path'] ) ? \trim( (string) $row['thumb_path'] ) : null,
			'bbox'        => $bbox,
			'similarity'  => $similarity,
		);
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
		if ( 'failed' === $last_sync_result || 'unreachable' === $last_sync_result ) {
			return 'failed';
		}

		if ( $this->sync_state_repository->get_pending_curation_operations( $tenant_id ) > 0
			|| $this->sync_state_repository->get_pending_topology_commands( $tenant_id ) > 0 ) {
			return 'refreshing';
		}

		if ( null === $projection_refreshed_at || 'skipped' === $last_sync_result ) {
			return 'stale';
		}

		return 'current';
	}
}