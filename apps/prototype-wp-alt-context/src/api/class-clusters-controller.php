<?php

declare(strict_types=1);

namespace AltContext\Api;

use AltContext\Sovereign\Mappers\ClusterResponseMapper;
use AltContext\Sovereign\Mappers\MemberResponseMapper;
use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function is_array;
use function min;
use function rest_sanitize_boolean;
use function sanitize_text_field;
use function sprintf;
use function wp_get_attachment_url;

class ClustersController extends AbstractRecognitionProxyController {
	private ClustersRepositoryInterface $clusters_repository;
	private IdentityMembersRepositoryInterface $members_repository;
	private SyncStateRepositoryInterface $sync_state_repository;
	private ClusterResponseMapper $cluster_mapper;
	private MemberResponseMapper $member_mapper;

	public function __construct(
		?ClustersRepositoryInterface $clusters_repository = null,
		?IdentityMembersRepositoryInterface $members_repository = null,
		?SyncStateRepositoryInterface $sync_state_repository = null,
		?ClusterResponseMapper $cluster_mapper = null,
		?MemberResponseMapper $member_mapper = null
	) {
		$this->clusters_repository = $clusters_repository ?? new ClustersRepository();
		$this->members_repository = $members_repository ?? new IdentityMembersRepository();
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
		$this->cluster_mapper = $cluster_mapper ?? new ClusterResponseMapper();
		$this->member_mapper = $member_mapper ?? new MemberResponseMapper();
	}

	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/recognition/clusters',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'list_clusters' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/top-unlabeled',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'list_top_unlabeled_clusters' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/labels',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'list_cluster_labels' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_cluster_detail' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)/members',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_cluster_members' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);
	}

	public function list_clusters( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$tenant_id = $this->get_tenant_id();
		$limit  = absint( $request->get_param( 'limit' ) ?? 50 );
		$limit  = min( $limit, 500 );
		$search = sanitize_text_field( (string) $request->get_param( 'search' ) );
		$labeled_only = rest_sanitize_boolean( $request->get_param( 'labeled_only' ) );

		if ( $this->should_use_local_projection( $tenant_id ) ) {
			$rows = $this->clusters_repository->list_for_tenant(
				$tenant_id,
				$limit,
				absint( $request->get_param( 'offset' ) ?? 0 ),
				array(
					'search' => $search,
					'labeled_only' => $labeled_only,
				)
			);

			$members_by_cluster = $this->load_members_by_cluster( $rows, 4 );
			$clusters = $this->cluster_mapper->map_cluster_list( $rows, $members_by_cluster );

			$payload = array(
				'clusters' => $clusters,
				'tenant_id' => $tenant_id,
			);

			return new WP_REST_Response( $payload, 200 );
		}

		$query = array(
			'tenant_id' => $tenant_id,
			'limit'     => $limit,
			'offset'    => absint( $request->get_param( 'offset' ) ?? 0 ),
		);

		if ( $labeled_only ) {
			$query['labeled_only'] = 'true';
		}

		if ( '' !== $search ) {
			$query['search'] = $search;
		}

		return $this->proxy_request( 'GET', '/recognition/clusters', array(), $query );
	}

	public function list_top_unlabeled_clusters( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$tenant_id = $this->get_tenant_id();
		$limit     = absint( $request->get_param( 'limit' ) ?? 10 );

		if ( $this->should_use_local_projection( $tenant_id ) ) {
			$clusters = $this->clusters_repository->list_top_unlabeled( $tenant_id, $limit );
			$members_by_cluster = $this->load_members_by_cluster( $clusters, 4 );
			$unlabeled_items = $this->cluster_mapper->map_top_unlabeled_clusters( $clusters, $members_by_cluster, $tenant_id );

			$payload = array(
				'clusters' => $unlabeled_items,
				'tenant_id' => $tenant_id,
			);

			return new WP_REST_Response( $payload, 200 );
		}

		$query = array(
			'tenant_id' => $tenant_id,
			'limit'     => $limit,
		);

		$response = $this->proxy_request( 'GET', '/recognition/clusters/top-unlabeled', array(), $query );
		if ( ! ( $response instanceof WP_REST_Response ) ) {
			return $response;
		}

		if ( 200 !== $response->get_status() ) {
			return $response;
		}

		$data = $response->get_data();
		if ( ! is_array( $data ) ) {
			return $response;
		}

		foreach ( $data as $cluster_index => $cluster ) {
			if ( ! is_array( $cluster ) ) {
				continue;
			}
			if ( ! isset( $cluster['representatives'] ) || ! is_array( $cluster['representatives'] ) ) {
				continue;
			}

			foreach ( $cluster['representatives'] as $rep_index => $rep ) {
				if ( ! is_array( $rep ) ) {
					continue;
				}

				$thumb_url = $rep['thumb_url'] ?? null;
				if ( ( ! is_string( $thumb_url ) || '' === $thumb_url ) && isset( $rep['thumbnail_url'] ) ) {
					$legacy_thumb = $rep['thumbnail_url'];
					if ( is_string( $legacy_thumb ) && '' !== $legacy_thumb ) {
						$thumb_url = $legacy_thumb;
					}
				}

				if ( ( ! is_string( $thumb_url ) || '' === $thumb_url ) && isset( $rep['media_id'] ) ) {
					$media_id = absint( $rep['media_id'] );
					if ( $media_id > 0 ) {
						$fallback_url = wp_get_attachment_url( $media_id );
						if ( is_string( $fallback_url ) && '' !== $fallback_url ) {
							$thumb_url = $fallback_url;
						}
					}
				}

				$cluster['representatives'][ $rep_index ]['thumb_url'] = is_string( $thumb_url ) && '' !== $thumb_url ? $thumb_url : null;
			}

			$data[ $cluster_index ] = $cluster;
		}

		$response->set_data( $data );
		return $response;
	}

	public function list_cluster_labels( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$tenant_id = $this->get_tenant_id();
		if ( $this->should_use_local_projection( $tenant_id ) ) {
			$labels = $this->clusters_repository->list_labels( $tenant_id );
			$payload = $this->cluster_mapper->map_labels_list( $labels );
			return new WP_REST_Response( $payload, 200 );
		}

		$query = array(
			'tenant_id' => $tenant_id,
		);

		return $this->proxy_request( 'GET', '/recognition/clusters/labels', array(), $query );
	}

	public function get_cluster_detail( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$tenant_id = $this->get_tenant_id();
		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( $this->should_use_local_projection( $tenant_id ) ) {
			$cluster_row = $this->clusters_repository->find_by_uuid( $cluster_id );
			if ( is_array( $cluster_row ) ) {
				$members = $this->members_repository->list_for_cluster( $cluster_id, 500, 0, $tenant_id );
				$payload = $this->cluster_mapper->map_cluster_detail( $cluster_row, $members );
				return new WP_REST_Response( $payload, 200 );
			}

			// Local projection is authoritative, but cluster not found
			return new WP_Error(
				'cluster_not_found',
				sprintf( 'Cluster %s not found.', $cluster_id ),
				array( 'status' => 404 )
			);
		}

		return $this->proxy_request(
			'GET',
			sprintf( '/recognition/clusters/%s', $cluster_id ),
			array(),
			array( 'tenant_id' => $tenant_id )
		);
	}

	public function get_cluster_members( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$tenant_id = $this->get_tenant_id();
		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( $this->should_use_local_projection( $tenant_id ) ) {
			// Verify cluster exists before listing members
			$cluster_row = $this->clusters_repository->find_by_uuid( $cluster_id );
			if ( ! is_array( $cluster_row ) ) {
				return new WP_Error(
					'cluster_not_found',
					sprintf( 'Cluster %s not found.', $cluster_id ),
					array( 'status' => 404 )
				);
			}

			$members = $this->members_repository->list_for_cluster( $cluster_id, 500, 0, $tenant_id );
			$payload = $this->member_mapper->map_cluster_members( $members );
			return new WP_REST_Response( $payload, 200 );
		}

		return $this->proxy_request(
			'GET',
			sprintf( '/recognition/clusters/%s/members', $cluster_id ),
			array(),
			array( 'tenant_id' => $tenant_id )
		);
	}

	/**
	 * @param array<int,array<string,mixed>> $cluster_rows
	 * @return array<string,array<int,array<string,mixed>>>
	 */
	private function load_members_by_cluster( array $cluster_rows, int $limit ): array {
		// Extract cluster UUIDs for batch query
		$cluster_uuids = array();
		foreach ( $cluster_rows as $row ) {
			$cluster_id = sanitize_text_field( (string) ( $row['cluster_uuid'] ?? '' ) );
			if ( '' !== $cluster_id ) {
				$cluster_uuids[] = $cluster_id;
			}
		}

		if ( empty( $cluster_uuids ) ) {
			return array();
		}

		// Batch query all members at once
		return $this->members_repository->list_for_cluster_uuids( $cluster_uuids, $limit );
	}

	private function should_use_local_projection( string $tenant_id ): bool {
		return $this->should_use_local_projection_gate( $this->sync_state_repository, $tenant_id );
	}
}
