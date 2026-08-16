<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

require_once __DIR__ . '/../../support/trait-runs-transactional.php';

use AltContext\Api\ClusterMutationHostInterface;
use AltContext\Support\RunsTransactional;
use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function is_object;
use function is_wp_error;
use function method_exists;
use function rest_sanitize_boolean;
use function sanitize_text_field;
use function sprintf;

class ClusterRepresentativeService {
	use RunsTransactional;

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

	public function pin_representative( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;
		$tenant_id = $this->host->get_tenant_id();

		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		$representative_id = sanitize_text_field( (string) $request->get_param( 'representative_id' ) );
		if ( '' === $representative_id ) {
			return new WP_Error( 'missing_representative_id', 'Representative ID is required.', array( 'status' => 400 ) );
		}

		$is_pinned = $request->get_param( 'is_pinned' );
		$desired_is_pinned = null === $is_pinned ? true : rest_sanitize_boolean( $is_pinned );

		if ( $this->host->should_proxy_mutation_to_backend( $tenant_id ) ) {
			return $this->host->proxy_cluster_mutation(
				'PATCH',
				sprintf( '/recognition/clusters/%s/representatives/%s/pin', $cluster_id, $representative_id ),
				array(
					'tenant_id' => $tenant_id,
					'is_pinned' => $desired_is_pinned,
				)
			);
		}

		$cluster = $this->host->get_projected_cluster_or_error( $cluster_id );
		if ( is_wp_error( $cluster ) ) {
			return $cluster;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return new WP_Error( 'acx_db_error', 'Database access is unavailable.', array( 'status' => 500 ) );
		}

		$payload = array(
			'tenant_id' => $tenant_id,
			'cluster_uuid' => $cluster_id,
			'representative_id' => $representative_id,
			'is_pinned' => $desired_is_pinned,
		);

		$affected_rows = 0;
		$result        = $this->run_transactional(
			function () use ( $cluster_id, $representative_id, $desired_is_pinned, $cluster, $tenant_id, $payload, &$affected_rows ): WP_REST_Response|WP_Error {
				$affected_rows = $this->clusters_repository->update_representative_state( $cluster_id, $representative_id, $desired_is_pinned );
				if ( $affected_rows > 0 && ! $this->host->enqueue_curation_operation( 'representative_pin_updated', $cluster_id, $cluster, $payload ) ) {
					return new WP_Error( 'acx_db_error', 'Could not queue representative pin replay operation.', array( 'status' => 500 ) );
				}

				if ( $affected_rows > 0 ) {
					$this->sync_state_repository->touch_local_curation_marker( $tenant_id );
				}

				return new WP_REST_Response(
					array(
						'cluster_id' => $cluster_id,
						'representative_id' => $representative_id,
						'is_pinned' => $desired_is_pinned,
						'synced' => false,
						'status' => $affected_rows > 0 ? 'pending' : 'acknowledged',
					),
					200
				);
			}
		);

		if ( is_wp_error( $result ) ) {
			return $result;
		}

		if ( $affected_rows > 0 ) {
			$this->host->trigger_xmp_refresh_for_cluster_ids( array( $cluster_id ), 'cluster-pin-representative' );
		}

		return $result;
	}
}
