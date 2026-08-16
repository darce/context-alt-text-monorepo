<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

require_once __DIR__ . '/../../support/trait-runs-transactional.php';

use AltContext\Api\ClusterMutationHostInterface;
use AltContext\Support\RunsTransactional;
use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function is_object;
use function is_wp_error;
use function method_exists;
use function sanitize_text_field;
use function sprintf;

class ClusterLifecycleService {
	use RunsTransactional;

	private ClusterMutationHostInterface $host;
	private ClustersRepositoryInterface $clusters_repository;

	public function __construct(
		ClusterMutationHostInterface $host,
		?ClustersRepositoryInterface $clusters_repository = null
	) {
		$this->host = $host;
		$this->clusters_repository = $clusters_repository ?? new ClustersRepository();
	}

	public function dismiss_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;
		$tenant_id = $this->host->get_tenant_id();

		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( $this->host->should_proxy_mutation_to_backend( $tenant_id ) ) {
			return $this->host->proxy_cluster_mutation( 'POST', sprintf( '/recognition/clusters/%s/dismiss', $cluster_id ) );
		}

		$cluster = $this->host->get_projected_cluster_or_error( $cluster_id );
		if ( is_wp_error( $cluster ) ) {
			return $cluster;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return new WP_Error( 'acx_db_error', 'Database access is unavailable.', array( 'status' => 500 ) );
		}

		$affected_rows = 0;
		$result        = $this->run_transactional(
			function () use ( $cluster_id, $cluster, &$affected_rows ): WP_REST_Response|WP_Error {
				$affected_rows = $this->clusters_repository->dismiss( $cluster_id );

				if ( $affected_rows > 0 && ! $this->host->enqueue_curation_operation( 'cluster_dismissed', $cluster_id, $cluster ) ) {
					return new WP_Error( 'acx_db_error', 'Could not queue dismiss replay operation.', array( 'status' => 500 ) );
				}

				return new WP_REST_Response(
					array(
						'dismissed' => true,
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

		return $result;
	}

	public function undismiss_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;
		$tenant_id = $this->host->get_tenant_id();

		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( $this->host->should_proxy_mutation_to_backend( $tenant_id ) ) {
			return $this->host->proxy_cluster_mutation( 'DELETE', sprintf( '/recognition/clusters/%s/dismiss', $cluster_id ) );
		}

		$cluster = $this->host->get_projected_cluster_or_error( $cluster_id );
		if ( is_wp_error( $cluster ) ) {
			return $cluster;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return new WP_Error( 'acx_db_error', 'Database access is unavailable.', array( 'status' => 500 ) );
		}

		$affected_rows = 0;
		$result        = $this->run_transactional(
			function () use ( $cluster_id, $cluster, &$affected_rows ): WP_REST_Response|WP_Error {
				$affected_rows = $this->clusters_repository->undismiss( $cluster_id );

				if ( $affected_rows > 0 && ! $this->host->enqueue_curation_operation( 'cluster_undismissed', $cluster_id, $cluster ) ) {
					return new WP_Error( 'acx_db_error', 'Could not queue undismiss replay operation.', array( 'status' => 500 ) );
				}

				return new WP_REST_Response(
					array(
						'dismissed' => false,
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

		return $result;
	}
}
