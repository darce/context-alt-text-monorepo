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

		return \array_map(
			function ( array $row ) use ( $projection_refreshed_at, $projection_status, $source_version ): array {
				$tags = array();
				if ( isset( $row['tags'] ) && \is_string( $row['tags'] ) ) {
					$decoded = \json_decode( $row['tags'], true );
					$tags    = \is_array( $decoded ) ? $decoded : array();
				}

				$clusters = $this->list_projected_clusters_for_person( isset( $row['id'] ) ? (int) $row['id'] : 0 );
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
	 * @return array<int,array<string,mixed>>
	 */
	private function list_projected_clusters_for_person( int $person_id ): array {
		global $wpdb;

		if ( $person_id <= 0 || ! isset( $wpdb ) || ! \is_object( $wpdb ) || ! \method_exists( $wpdb, 'prepare' ) || ! \method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$table_clusters = $wpdb->prefix . 'acx_clusters';
		$rows = $wpdb->get_results(
			$wpdb->prepare(
				'SELECT * FROM %i WHERE person_id = %d ORDER BY updated_at DESC',
				$table_clusters,
				$person_id
			),
			ARRAY_A
		);

		if ( ! \is_array( $rows ) ) {
			return array();
		}

		return \array_map(
			function ( array $row ): array {
				$instances = $this->list_projected_instances_for_cluster( \trim( (string) ( $row['cluster_uuid'] ?? '' ) ) );

				return array(
					'cluster_id'             => \trim( (string) ( $row['cluster_uuid'] ?? '' ) ),
					'identity_count'         => isset( $row['identity_count'] ) ? (int) $row['identity_count'] : \count( $instances ),
					'representative_identity' => $this->resolve_representative_identity( \trim( (string) ( $row['representative_id'] ?? '' ) ), $instances ),
					'instances'              => $instances,
				);
			},
			$rows
		);
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	private function list_projected_instances_for_cluster( string $cluster_uuid ): array {
		global $wpdb;

		$normalized_cluster_uuid = \trim( $cluster_uuid );
		if ( '' === $normalized_cluster_uuid || ! isset( $wpdb ) || ! \is_object( $wpdb ) || ! \method_exists( $wpdb, 'prepare' ) || ! \method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$table_members = $wpdb->prefix . 'acx_identity_members';
		$rows = $wpdb->get_results(
			$wpdb->prepare(
				'SELECT * FROM %i WHERE cluster_uuid = %s ORDER BY updated_at DESC',
				$table_members,
				$normalized_cluster_uuid
			),
			ARRAY_A
		);

		if ( ! \is_array( $rows ) ) {
			return array();
		}

		return \array_map(
			array( $this, 'map_projected_instance_row' ),
			$rows
		);
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