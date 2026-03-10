<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use RuntimeException;
use Throwable;

use function do_action;
use function function_exists;
use function is_array;
use function is_object;
use function method_exists;
use function trim;

class SnapshotProjector implements SnapshotProjectorInterface {
	private ClustersRepositoryInterface $clusters_repository;
	private IdentityMembersRepositoryInterface $members_repository;
	private SyncStateRepositoryInterface $sync_state_repository;
	private ConflictRepository $conflict_repository;

	public function __construct(
		ClustersRepositoryInterface $clusters_repository,
		IdentityMembersRepositoryInterface $members_repository,
		SyncStateRepositoryInterface $sync_state_repository,
		?ConflictRepository $conflict_repository = null
	) {
		$this->clusters_repository   = $clusters_repository;
		$this->members_repository    = $members_repository;
		$this->sync_state_repository = $sync_state_repository;
		$this->conflict_repository   = $conflict_repository ?? new ConflictRepository();
	}

	/**
	 * @param array<string,mixed> $snapshot
	 * @throws RuntimeException When transaction support is unavailable.
	 * @throws Throwable Re-throws repository errors after rollback.
	 */
	public function project( string $tenant_id, array $snapshot ): void {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard();
			return;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			throw new RuntimeException( 'Snapshot projection requires $wpdb query support.' );
		}

		$started = false !== $wpdb->query( 'START TRANSACTION' );
		if ( ! $started ) {
			throw new RuntimeException( 'Snapshot projection requires transaction support.' );
		}

		try {
			$snapshot_version = (int) ( $snapshot['snapshot_version'] ?? 0 );
			$clusters         = is_array( $snapshot['clusters'] ?? null ) ? $snapshot['clusters'] : array();
			$members          = is_array( $snapshot['members'] ?? null ) ? $snapshot['members'] : array();
			$pre_projection_conflict_count = $this->sync_state_repository->get_conflict_count( $normalized_tenant_id );

			$this->record_curated_cluster_deletion_conflicts( $normalized_tenant_id, $clusters, $snapshot_version );

			$this->clusters_repository->merge_snapshot_for_tenant( $normalized_tenant_id, $clusters, $snapshot_version );
			$this->members_repository->merge_snapshot_for_tenant( $normalized_tenant_id, $members, $snapshot_version );
			$this->sync_state_repository->upsert_snapshot_version( $normalized_tenant_id, $snapshot_version );
			$this->sync_state_repository->refresh_curation_metrics( $normalized_tenant_id );
			$post_projection_conflict_count = $this->sync_state_repository->get_conflict_count( $normalized_tenant_id );
			$conflicts_generated            = max( 0, $post_projection_conflict_count - $pre_projection_conflict_count );

			if ( $conflicts_generated > 0 && function_exists( 'do_action' ) ) {
				do_action( 'acx_projection_conflicts_detected', $conflicts_generated, $normalized_tenant_id );
			}

			$committed = false !== $wpdb->query( 'COMMIT' );
			if ( ! $committed ) {
				throw new RuntimeException( 'Snapshot projection failed to commit transaction.' );
			}
		} catch ( Throwable $throwable ) {
			$wpdb->query( 'ROLLBACK' );
			throw $throwable;
		}
	}

	/**
	 * @param array<int,array<string,mixed>> $incoming_clusters
	 */
	private function record_curated_cluster_deletion_conflicts( string $tenant_id, array $incoming_clusters, int $snapshot_version ): void {
		$curated_clusters = $this->clusters_repository->get_curated_clusters_for_tenant( $tenant_id );
		if ( empty( $curated_clusters ) ) {
			return;
		}

		$incoming_cluster_ids = array();
		foreach ( $incoming_clusters as $cluster ) {
			if ( ! is_array( $cluster ) ) {
				continue;
			}

			$cluster_uuid = trim( (string) ( $cluster['cluster_uuid'] ?? '' ) );
			if ( '' !== $cluster_uuid ) {
				$incoming_cluster_ids[ $cluster_uuid ] = true;
			}
		}

		foreach ( $curated_clusters as $cluster_uuid => $cluster ) {
			if ( isset( $incoming_cluster_ids[ $cluster_uuid ] ) || ! is_array( $cluster ) ) {
				continue;
			}

			$this->conflict_repository->record_projection_conflict(
				$tenant_id,
				'cluster',
				(string) $cluster_uuid,
				'curated_cluster_deleted',
				$snapshot_version,
				max( 0, (int) ( $cluster['snapshot_version'] ?? 0 ) ),
				max( 0, (int) ( $cluster['local_revision'] ?? 0 ) ),
				array(
					'cluster_uuid' => (string) $cluster_uuid,
					'status' => 'missing_from_snapshot',
				),
				array(
					'cluster_uuid' => (string) $cluster_uuid,
					'label' => $cluster['label'] ?? null,
					'person_id' => $cluster['person_id'] ?? null,
					'curation_state' => $cluster['curation_state'] ?? null,
				)
			);
		}
	}

	private function log_empty_tenant_id_guard(): void {
		if ( function_exists( 'do_action' ) ) {
			do_action(
				'acx_sovereign_warning',
				'empty_tenant_id',
				array(
					'method' => __METHOD__,
				)
			);
		}

		if ( function_exists( '_doing_it_wrong' ) ) {
			_doing_it_wrong( __METHOD__, 'Tenant ID must be non-empty for snapshot projection.', '4.13.1' );
		}
	}
}
