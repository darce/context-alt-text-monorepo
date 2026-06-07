<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use AltContext\Api\ClusterMutationHostInterface;
use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function is_array;
use function is_object;
use function is_wp_error;
use function method_exists;
use function sanitize_text_field;
use function sprintf;

class ClusterLabelService {
	private ClusterMutationHostInterface $host;
	private ClustersRepositoryInterface $clusters_repository;
	private SyncStateRepositoryInterface $sync_state_repository;

	public function __construct(
		ClusterMutationHostInterface $host,
		?ClustersRepositoryInterface $clusters_repository = null,
		?SyncStateRepositoryInterface $sync_state_repository = null
	) {
		$this->host = $host;
		$this->clusters_repository = $clusters_repository ?? new ClustersRepository();
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
	}

	public function update_cluster_label( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;
		$tenant_id = $this->host->get_tenant_id();

		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		$label      = sanitize_text_field( (string) $request->get_param( 'label' ) );

		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( '' === $label ) {
			return new WP_Error( 'missing_label', 'Label cannot be empty.', array( 'status' => 400 ) );
		}

		if ( $this->host->should_proxy_mutation_to_backend( $tenant_id ) ) {
			return $this->host->proxy_cluster_mutation(
				'PATCH',
				sprintf( '/recognition/clusters/%s', $cluster_id ),
				array(
					'tenant_id' => $tenant_id,
					'label'     => $label,
				)
			);
		}

		$cluster = $this->clusters_repository->find_by_uuid( $cluster_id );
		if ( ! is_array( $cluster ) ) {
			$cluster = $this->host->get_projected_cluster_or_error( $cluster_id );
			if ( is_wp_error( $cluster ) ) {
				return $cluster;
			}
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return new WP_Error( 'acx_db_error', 'Database access is unavailable.', array( 'status' => 500 ) );
		}

		if ( false === $wpdb->query( 'START TRANSACTION' ) ) {
			return new WP_Error( 'acx_db_error', 'Could not start local transaction.', array( 'status' => 500 ) );
		}

		$affected_rows = $this->clusters_repository->update_label( $cluster_id, $label );
		if ( $affected_rows > 0 && ! $this->host->enqueue_curation_operation(
			'cluster_label_updated',
			$cluster_id,
			$cluster,
			array(
				'cluster_uuid' => $cluster_id,
				'label' => $label,
			)
		) ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', 'Could not queue label replay operation.', array( 'status' => 500 ) );
		}

		if ( $affected_rows > 0 ) {
			$this->sync_state_repository->touch_local_curation_marker( $tenant_id );
		}

		if ( false === $wpdb->query( 'COMMIT' ) ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', 'Could not commit local transaction.', array( 'status' => 500 ) );
		}

		if ( $affected_rows > 0 ) {
			$this->host->trigger_xmp_refresh_for_cluster_ids( array( $cluster_id ), 'cluster-label-update' );
		}

		return new WP_REST_Response(
			array(
				'cluster_id' => $cluster_id,
				'label' => $label,
				'synced' => false,
				'status' => $affected_rows > 0 ? 'pending' : 'acknowledged',
			),
			200
		);
	}
}
