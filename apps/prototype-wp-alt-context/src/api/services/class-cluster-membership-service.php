<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

require_once __DIR__ . '/../../support/trait-runs-transactional.php';

use AltContext\Api\ClusterMutationHostInterface;
use AltContext\Support\RunsTransactional;
use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function array_filter;
use function array_values;
use function get_current_user_id;
use function is_array;
use function is_object;
use function is_wp_error;
use function method_exists;
use function rest_sanitize_boolean;
use function sanitize_text_field;
use function sprintf;
use function wp_generate_uuid4;

class ClusterMembershipService {
	use RunsTransactional;

	private ClusterMutationHostInterface $host;
	private ClustersRepositoryInterface $clusters_repository;
	private IdentityMembersRepositoryInterface $members_repository;
	private SyncStateRepositoryInterface $sync_state_repository;

	public function __construct(
		ClusterMutationHostInterface $host,
		?ClustersRepositoryInterface $clusters_repository = null,
		?IdentityMembersRepositoryInterface $members_repository = null,
		?SyncStateRepositoryInterface $sync_state_repository = null
	) {
		$this->host = $host;
		$this->clusters_repository = $clusters_repository ?? new ClustersRepository();
		$this->members_repository = $members_repository ?? new IdentityMembersRepository();
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
	}

	public function reassign_cluster_identity( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;
		$tenant_id = $this->host->get_tenant_id();

		$identity_id = sanitize_text_field( (string) $request->get_param( 'identity_id' ) );
		if ( '' === $identity_id ) {
			return new WP_Error( 'missing_identity_id', 'Identity ID is required.', array( 'status' => 400 ) );
		}

		$target = sanitize_text_field( (string) ( $request->get_param( 'target_cluster_id' ) ?? '' ) );
		if ( '' === $target ) {
			return new WP_Error( 'missing_target_cluster_id', 'Target cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( $this->host->should_proxy_mutation_to_backend( $tenant_id ) ) {
			$payload = array(
				'tenant_id'         => $tenant_id,
				'identity_id'       => $identity_id,
				'target_cluster_id' => $target,
			);
			$block_from_cluster = $request->get_param( 'block_from_cluster' );
			if ( null !== $block_from_cluster ) {
				$payload['block_from_cluster'] = rest_sanitize_boolean( $block_from_cluster );
			}

			return $this->host->proxy_cluster_mutation( 'POST', '/recognition/clusters/reassign', $payload );
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return new WP_Error( 'acx_db_error', 'Database access is unavailable.', array( 'status' => 500 ) );
		}

		$payload = array(
			'tenant_id'         => $tenant_id,
			'identity_id'       => $identity_id,
			'target_cluster_id' => $target,
			'user_id'           => get_current_user_id(),
		);
		$block_from_cluster = $request->get_param( 'block_from_cluster' );
		if ( null !== $block_from_cluster ) {
			$payload['block_from_cluster'] = rest_sanitize_boolean( $block_from_cluster );
		}

		$affected_rows = 0;
		$result        = $this->run_transactional(
			function () use ( $identity_id, $target, $tenant_id, $payload, &$affected_rows ): WP_REST_Response|WP_Error {
				$affected_rows = $this->members_repository->reassign_to_cluster( $identity_id, $target );
				if ( $affected_rows > 0 && ! $this->host->enqueue_curation_operation( 'identity_reassigned', $identity_id, array(), $payload, 'member' ) ) {
					return new WP_Error( 'acx_db_error', 'Could not queue reassign replay operation.', array( 'status' => 500 ) );
				}

				if ( $affected_rows > 0 ) {
					$this->sync_state_repository->touch_local_curation_marker( $tenant_id );
				}

				return new WP_REST_Response(
					array(
						'identity_id' => $identity_id,
						'target_cluster_id' => $target,
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
			$this->host->trigger_xmp_refresh_for_cluster_ids( array( $target ), 'cluster-reassign' );
		}

		return $result;
	}

	public function create_cluster_for_identity( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;
		$tenant_id = $this->host->get_tenant_id();

		$identity_id = sanitize_text_field( (string) $request->get_param( 'identity_id' ) );
		$label       = sanitize_text_field( (string) $request->get_param( 'label' ) );

		if ( '' === $identity_id ) {
			return new WP_Error( 'missing_identity_id', 'Identity ID is required.', array( 'status' => 400 ) );
		}

		if ( '' === $label ) {
			return new WP_Error( 'missing_label', 'Label is required.', array( 'status' => 400 ) );
		}

		if ( $this->host->should_proxy_mutation_to_backend( $tenant_id ) ) {
			return $this->host->proxy_cluster_mutation(
				'POST',
				'/recognition/clusters/create-for-identity',
				array(
					'tenant_id'   => $tenant_id,
					'identity_id' => $identity_id,
					'label'       => $label,
				)
			);
		}

		$existing_member = $this->members_repository->find_by_identity_uuid( $identity_id );
		if ( ! is_array( $existing_member ) ) {
			return new WP_Error( 'identity_not_found', 'Identity is not present in the local projection.', array( 'status' => 404 ) );
		}

		$new_cluster_id = wp_generate_uuid4();
		$source_cluster_id = sanitize_text_field( (string) ( $existing_member['cluster_uuid'] ?? '' ) );

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return new WP_Error( 'acx_db_error', 'Database access is unavailable.', array( 'status' => 500 ) );
		}

		$result = $this->run_transactional(
			function () use ( $tenant_id, $new_cluster_id, $label, $identity_id, $source_cluster_id ): WP_REST_Response|WP_Error {
				$created = $this->clusters_repository->create_local_cluster( $tenant_id, $new_cluster_id, $label, 1 );
				if ( is_wp_error( $created ) ) {
					return $created;
				}
				if ( $created <= 0 ) {
					return new WP_Error( 'acx_db_error', 'Could not create local cluster projection.', array( 'status' => 500 ) );
				}

				$this->members_repository->reassign_to_cluster( $identity_id, $new_cluster_id );
				if ( '' !== $source_cluster_id ) {
					$this->clusters_repository->adjust_identity_count( $source_cluster_id, -1 );
				}

				$payload = array(
					'tenant_id'   => $tenant_id,
					'identity_id' => $identity_id,
					'label'       => $label,
					'user_id'     => get_current_user_id(),
					'desired_cluster_id' => $new_cluster_id,
				);

				if ( ! $this->host->enqueue_curation_operation( 'cluster_created_for_identity', $new_cluster_id, array(
					'cluster_uuid' => $new_cluster_id,
					'snapshot_version' => 0,
					'local_revision' => 1,
				), $payload ) ) {
					return new WP_Error( 'acx_db_error', 'Could not queue create-cluster replay operation.', array( 'status' => 500 ) );
				}

				$this->sync_state_repository->touch_local_curation_marker( $tenant_id );

				return new WP_REST_Response(
					array(
						'cluster_id' => $new_cluster_id,
						'identity_id' => $identity_id,
						'label' => $label,
						'synced' => false,
						'status' => 'pending',
					),
					200
				);
			}
		);

		if ( is_wp_error( $result ) ) {
			return $result;
		}

		$this->host->trigger_xmp_refresh_for_cluster_ids( array_values( array_filter( array( $source_cluster_id, $new_cluster_id ) ) ), 'cluster-create-for-identity' );

		return $result;
	}

	public function assign_outlier_to_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;
		$tenant_id = $this->host->get_tenant_id();

		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		$identity_id = sanitize_text_field( (string) $request->get_param( 'identity_id' ) );
		$similarity = (float) $request->get_param( 'similarity' );

		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( '' === $identity_id ) {
			return new WP_Error( 'missing_identity_id', 'Identity ID is required.', array( 'status' => 400 ) );
		}

		if ( $this->host->should_proxy_mutation_to_backend( $tenant_id ) ) {
			return $this->host->proxy_cluster_mutation(
				'POST',
				sprintf( '/recognition/clusters/%s/assign', $cluster_id ),
				array(
					'tenant_id'   => $tenant_id,
					'identity_id' => $identity_id,
					'similarity'  => $similarity,
				)
			);
		}

		$target_cluster = $this->host->get_projected_cluster_or_error( $cluster_id, 'target_cluster_not_found', 'Target cluster not found.' );
		if ( is_wp_error( $target_cluster ) ) {
			return $target_cluster;
		}

		$existing_member = $this->members_repository->find_by_identity_uuid( $identity_id );
		if ( ! is_array( $existing_member ) ) {
			return new WP_Error( 'identity_not_found', 'Identity is not present in the local projection.', array( 'status' => 404 ) );
		}

		$source_cluster_id = sanitize_text_field( (string) ( $existing_member['cluster_uuid'] ?? '' ) );
		if ( '' === $source_cluster_id ) {
			return new WP_Error( 'missing_source_cluster_id', 'Identity is not currently assigned to a projected cluster.', array( 'status' => 409 ) );
		}

		if ( $cluster_id === $source_cluster_id ) {
			return new WP_REST_Response(
				array(
					'identity_id' => $identity_id,
					'source_cluster_id' => $source_cluster_id,
					'target_cluster_id' => $cluster_id,
					'synced' => true,
					'status' => 'acknowledged',
				),
				200
			);
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return new WP_Error( 'acx_db_error', 'Database access is unavailable.', array( 'status' => 500 ) );
		}

		$affected_rows = 0;
		$result        = $this->run_transactional(
			function () use ( $identity_id, $cluster_id, $source_cluster_id, $tenant_id, $similarity, $target_cluster, &$affected_rows ): WP_REST_Response|WP_Error {
				$affected_rows = $this->members_repository->reassign_to_cluster( $identity_id, $cluster_id );
				if ( $affected_rows > 0 ) {
					$this->clusters_repository->adjust_identity_count( $source_cluster_id, -1 );
					$this->clusters_repository->adjust_identity_count( $cluster_id, 1 );
				}

				$payload = array(
					'tenant_id' => $tenant_id,
					'identity_id' => $identity_id,
					'similarity' => $similarity,
					'user_id' => get_current_user_id(),
				);

				if ( $affected_rows > 0 && ! $this->host->enqueue_curation_operation( 'assign_outlier_to_cluster', $cluster_id, $target_cluster, $payload ) ) {
					return new WP_Error( 'acx_db_error', 'Could not queue assign-outlier replay operation.', array( 'status' => 500 ) );
				}

				if ( $affected_rows > 0 ) {
					$this->sync_state_repository->touch_local_curation_marker( $tenant_id );
				}

				return new WP_REST_Response(
					array(
						'identity_id' => $identity_id,
						'source_cluster_id' => $source_cluster_id,
						'target_cluster_id' => $cluster_id,
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
			$this->host->trigger_xmp_refresh_for_cluster_ids( array( $source_cluster_id, $cluster_id ), 'cluster-assign-outlier' );
		}

		return $result;
	}
}
