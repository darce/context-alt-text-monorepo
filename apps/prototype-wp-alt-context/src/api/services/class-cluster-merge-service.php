<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

require_once __DIR__ . '/../../support/trait-runs-transactional.php';
require_once __DIR__ . '/../../support/trait-detects-system-defined-labels.php';

use AltContext\Api\ClusterMutationHostInterface;
use AltContext\Support\RunsTransactional;
use AltContext\Support\DetectsSystemDefinedLabels;
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
use function array_map;
use function array_unique;
use function get_current_user_id;
use function is_array;
use function is_object;
use function is_wp_error;
use function max;
use function method_exists;
use function sanitize_text_field;
use function trim;
use function wp_generate_uuid4;

class ClusterMergeService {
	use DetectsSystemDefinedLabels;
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

	public function merge_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;
		$tenant_id = $this->host->get_tenant_id();

		$source_id         = sanitize_text_field( (string) $request->get_param( 'source_id' ) );
		$target_cluster_id = sanitize_text_field( (string) $request->get_param( 'target_cluster_id' ) );
		$target_label      = sanitize_text_field( (string) $request->get_param( 'target_label' ) );

		if ( '' === $source_id ) {
			return new WP_Error( 'missing_source_id', 'Source cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( '' === $target_cluster_id ) {
			return new WP_Error( 'missing_target_cluster_id', 'Target cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( $source_id === $target_cluster_id ) {
			return new WP_Error( 'invalid_target_cluster_id', 'Source and target cluster IDs must differ.', array( 'status' => 400 ) );
		}

		if ( '' !== $target_label && $this->is_reserved_label_shape( $target_label ) ) {
			return new WP_Error( 'reserved_label', 'Labels beginning with cluster- or cluster_ are reserved.', array( 'status' => 400 ) );
		}

		if ( $this->host->should_proxy_mutation_to_backend( $tenant_id ) ) {
			$payload = array(
				'tenant_id'         => $tenant_id,
				'target_cluster_id' => $target_cluster_id,
			);
			if ( '' !== $target_label ) {
				$payload['target_label'] = $target_label;
			}

			return $this->host->proxy_cluster_mutation(
				'POST',
				sprintf( '/recognition/clusters/%s/merge', $source_id ),
				$payload
			);
		}

		$source_cluster = $this->host->get_projected_cluster_or_error( $source_id, 'source_cluster_not_found', 'Source cluster not found.' );
		if ( is_wp_error( $source_cluster ) ) {
			return $source_cluster;
		}

		$target_cluster = $this->host->get_projected_cluster_or_error( $target_cluster_id, 'target_cluster_not_found', 'Target cluster not found.' );
		if ( is_wp_error( $target_cluster ) ) {
			return $target_cluster;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return new WP_Error( 'acx_db_error', 'Database access is unavailable.', array( 'status' => 500 ) );
		}

		$moved_rows = 0;
		$result     = $this->run_transactional(
			function () use ( $source_id, $target_cluster_id, $target_label, $tenant_id, $source_cluster, &$moved_rows ): WP_REST_Response|WP_Error {
				$moved_rows = $this->members_repository->reassign_cluster_members( $source_id, $target_cluster_id );
				$this->clusters_repository->update_identity_count( $source_id, 0 );
				$this->clusters_repository->adjust_identity_count( $target_cluster_id, $moved_rows );

				if ( '' !== $target_label ) {
					$this->clusters_repository->update_label( $target_cluster_id, $target_label );
				}

				$this->clusters_repository->dismiss( $source_id );

				$payload = array(
					'tenant_id'         => $tenant_id,
					'target_cluster_id' => $target_cluster_id,
				);

				if ( '' !== $target_label ) {
					$payload['target_label'] = $target_label;
				}

				if ( ! $this->host->enqueue_curation_operation( 'cluster_merged', $source_id, $source_cluster, $payload ) ) {
					return new WP_Error( 'acx_db_error', 'Could not queue merge replay operation.', array( 'status' => 500 ) );
				}

				$this->sync_state_repository->touch_local_curation_marker( $tenant_id );

				return new WP_REST_Response(
					array(
						'source_cluster_id' => $source_id,
						'target_cluster_id' => $target_cluster_id,
						'moved_identity_count' => $moved_rows,
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

		$this->host->trigger_xmp_refresh_for_cluster_ids( array( $source_id, $target_cluster_id ), 'cluster-merge' );

		return $result;
	}

	public function revert_merge_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;
		$tenant_id = $this->host->get_tenant_id();

		$target_cluster_id  = sanitize_text_field( (string) $request->get_param( 'target_cluster_id' ) );
		$moved_identity_ids = $request->get_param( 'moved_identity_ids' );
		$source_label       = $request->get_param( 'source_label' );
		$requested_source_cluster_id = sanitize_text_field( (string) ( $request->get_param( 'source_cluster_id' ) ?? '' ) );

		if ( '' === $target_cluster_id ) {
			return new WP_Error( 'missing_target_cluster_id', 'Target cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( ! is_array( $moved_identity_ids ) || empty( $moved_identity_ids ) ) {
			return new WP_Error( 'missing_moved_identity_ids', 'Provide one or more identity IDs to revert.', array( 'status' => 400 ) );
		}

		$sanitized_ids = array_values(
			array_unique(
				array_filter(
					array_map(
						static function ( $value ): string {
							return sanitize_text_field( (string) $value );
						},
						$moved_identity_ids
					),
					static function ( string $value ): bool {
						return '' !== $value;
					}
				)
			)
		);
		if ( empty( $sanitized_ids ) ) {
			return new WP_Error( 'missing_moved_identity_ids', 'Provide one or more valid identity IDs to revert.', array( 'status' => 400 ) );
		}

		if ( $this->host->should_proxy_mutation_to_backend( $tenant_id ) ) {
			$payload = array(
				'tenant_id'          => $tenant_id,
				'target_cluster_id'  => $target_cluster_id,
				'moved_identity_ids' => $sanitized_ids,
			);
			if ( '' !== $requested_source_cluster_id ) {
				$payload['desired_source_cluster_id'] = $requested_source_cluster_id;
			}
			if ( is_string( $source_label ) && '' !== trim( $source_label ) ) {
				$payload['source_label'] = sanitize_text_field( (string) $source_label );
			}

			return $this->host->proxy_cluster_mutation( 'POST', '/recognition/clusters/revert-merge', $payload );
		}

		$target_cluster = $this->host->get_projected_cluster_or_error( $target_cluster_id, 'target_cluster_not_found', 'Target cluster not found.' );
		if ( is_wp_error( $target_cluster ) ) {
			return $target_cluster;
		}

		foreach ( $sanitized_ids as $identity_id ) {
			$member = $this->members_repository->find_by_identity_uuid( $identity_id );
			if ( ! is_array( $member ) ) {
				return new WP_Error( 'identity_not_found', 'One or more identities are not present in the local projection.', array( 'status' => 404 ) );
			}

			$current_cluster_id = sanitize_text_field( (string) ( $member['cluster_uuid'] ?? '' ) );
			if ( $target_cluster_id !== $current_cluster_id ) {
				return new WP_Error( 'identity_not_in_target_cluster', 'One or more identities are no longer assigned to the target cluster.', array( 'status' => 409 ) );
			}
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return new WP_Error( 'acx_db_error', 'Database access is unavailable.', array( 'status' => 500 ) );
		}

		$source_cluster_id = '' !== $requested_source_cluster_id ? $requested_source_cluster_id : wp_generate_uuid4();
		$restored_label = $source_label ? sanitize_text_field( (string) $source_label ) : '';
		$target_member_count = $this->members_repository->count_for_cluster( $target_cluster_id );

		$moved_rows = 0;
		$result     = $this->run_transactional(
			function () use ( $tenant_id, $source_cluster_id, $restored_label, $sanitized_ids, $target_cluster_id, $target_member_count, $target_cluster, &$moved_rows ): WP_REST_Response|WP_Error {
				if ( $this->clusters_repository->create_local_cluster( $tenant_id, $source_cluster_id, $restored_label, count( $sanitized_ids ) ) <= 0 ) {
					return new WP_Error( 'acx_db_error', 'Could not create restored local cluster projection.', array( 'status' => 500 ) );
				}

				$moved_rows = 0;
				foreach ( $sanitized_ids as $identity_id ) {
					$moved_rows += $this->members_repository->reassign_to_cluster( $identity_id, $source_cluster_id );
				}

				$this->clusters_repository->adjust_identity_count( $target_cluster_id, -$moved_rows );

				$payload = array(
					'tenant_id' => $tenant_id,
					'target_cluster_id' => $target_cluster_id,
					'moved_identity_ids' => $sanitized_ids,
					'user_id' => get_current_user_id(),
					'desired_source_cluster_id' => $source_cluster_id,
				);
				if ( '' !== $restored_label ) {
					$payload['source_label'] = $restored_label;
				}

				if ( ! $this->host->enqueue_curation_operation( 'revert_merge_cluster', $target_cluster_id, $target_cluster, $payload ) ) {
					return new WP_Error( 'acx_db_error', 'Could not queue revert-merge replay operation.', array( 'status' => 500 ) );
				}

				$this->sync_state_repository->touch_local_curation_marker( $tenant_id );

				return new WP_REST_Response(
					array(
						'restored_cluster_id' => $source_cluster_id,
						'restored_label' => '' !== $restored_label ? $restored_label : null,
						'restored_identity_count' => $moved_rows,
						'target_cluster_id' => $target_cluster_id,
						'target_identity_count' => max( 0, $target_member_count - $moved_rows ),
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

		$this->host->trigger_xmp_refresh_for_cluster_ids( array( $target_cluster_id, $source_cluster_id ), 'cluster-revert-merge' );

		return $result;
	}
}
