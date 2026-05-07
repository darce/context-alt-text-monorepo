<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/interface-sync-state-repository.php';
require_once __DIR__ . '/class-sync-state-repository.php';

use function array_map;
use function is_array;
use function is_object;
use function is_string;
use function json_decode;
use function method_exists;
use function trim;

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

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$table_persons  = $wpdb->prefix . 'acx_persons';
		$table_clusters = $wpdb->prefix . 'acx_clusters';
		$results        = $wpdb->get_results(
			$wpdb->prepare(
				'SELECT p.*, (SELECT COUNT(*) FROM %i c WHERE c.person_id = p.id) AS cluster_count FROM %i p ORDER BY p.name ASC',
				$table_clusters,
				$table_persons
			),
			ARRAY_A
		);

		if ( ! is_array( $results ) ) {
			return array();
		}

		$projection_refreshed_at = $this->sync_state_repository->get_last_updated( $tenant_id );
		$projection_status       = $this->resolve_projection_status( $tenant_id, $projection_refreshed_at );
		$source_version          = $this->sync_state_repository->get_snapshot_version( $tenant_id );

		return array_map(
			static function ( array $row ) use ( $projection_refreshed_at, $projection_status, $source_version ): array {
				$tags = array();
				if ( isset( $row['tags'] ) && is_string( $row['tags'] ) ) {
					$decoded = json_decode( $row['tags'], true );
					$tags    = is_array( $decoded ) ? $decoded : array();
				}

				return array(
					'id'                     => isset( $row['id'] ) ? (int) $row['id'] : 0,
					'person_uuid'            => trim( (string) ( $row['person_uuid'] ?? '' ) ),
					'name'                   => (string) ( $row['name'] ?? '' ),
					'tags'                   => $tags,
					'cluster_count'          => isset( $row['cluster_count'] ) ? (int) $row['cluster_count'] : 0,
					'updated_at'             => (string) ( $row['updated_at'] ?? '' ),
					'source_version'         => $source_version,
					'projection_status'      => $projection_status,
					'projection_refreshed_at' => $projection_refreshed_at,
				);
			},
			$results
		);
	}

	private function resolve_projection_status( string $tenant_id, ?string $projection_refreshed_at ): string {
		if ( $this->sync_state_repository->get_pending_curation_operations( $tenant_id ) > 0
			|| $this->sync_state_repository->get_pending_topology_commands( $tenant_id ) > 0 ) {
			return 'refreshing';
		}

		$last_sync_result = $this->sync_state_repository->get_last_sync_result( $tenant_id );
		if ( 'failed' === $last_sync_result || 'unreachable' === $last_sync_result ) {
			return 'failed';
		}

		if ( null === $projection_refreshed_at || 'skipped' === $last_sync_result ) {
			return 'stale';
		}

		return 'current';
	}
}