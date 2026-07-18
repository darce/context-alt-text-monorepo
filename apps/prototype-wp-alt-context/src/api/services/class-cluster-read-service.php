<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use AltContext\Api\ClustersHostInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function count;
use function is_array;
use function is_bool;
use function is_numeric;
use function max;
use function min;
use function rest_sanitize_boolean;
use function sanitize_text_field;
use function sprintf;
use function time;
use function wp_next_scheduled;
use function wp_schedule_single_event;

class ClusterReadService {
	private const GET_CLUSTER_MEMBERS_MAX_LIMIT = IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT;
	private const LIST_CLUSTER_LABELS_DEFAULT_LIMIT = 50;
	private const LIST_CLUSTER_LABELS_MAX_LIMIT = 500;
	private const LIST_CLUSTERS_DEFAULT_LIMIT = 50;
	private const LIST_CLUSTERS_MAX_LIMIT = 500;
	private const LIST_TOP_UNLABELED_CLUSTERS_DEFAULT_LIMIT = 10;
	private const LIST_TOP_UNLABELED_CLUSTERS_MAX_LIMIT = 500;
	private const PREVIEW_IDENTITIES_PER_CLUSTER = 4;

	private ClustersHostInterface $host;
	private ClusterReadDependencies $dependencies;

	public function __construct( ClustersHostInterface $host, ClusterReadDependencies $dependencies ) {
		$this->host = $host;
		$this->dependencies = $dependencies;
	}

	public function list_clusters( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$tenant_id = $this->host->get_tenant_id();
		$limit  = absint( $request->get_param( 'limit' ) ?? self::LIST_CLUSTERS_DEFAULT_LIMIT );
		$limit  = max( 1, min( $limit, self::LIST_CLUSTERS_MAX_LIMIT ) );
		$offset = absint( $request->get_param( 'offset' ) ?? 0 );
		$search = sanitize_text_field( (string) $request->get_param( 'search' ) );
		$labeled_only = rest_sanitize_boolean( $request->get_param( 'labeled_only' ) );

		if ( $this->dependencies->projection_sync_service->should_use_local_projection( $tenant_id ) ) {
			$rows = $this->dependencies->clusters_repository->list_for_tenant(
				$tenant_id,
				$limit,
				$offset,
				array(
					'search' => $search,
					'labeled_only' => $labeled_only,
				)
			);

			$members_by_cluster = $this->load_members_by_cluster( $rows, self::PREVIEW_IDENTITIES_PER_CLUSTER );
			$clusters = $this->dependencies->cluster_mapper->map_cluster_list( $rows, $members_by_cluster );

			return new WP_REST_Response( $this->dependencies->response_envelope_service->build_cluster_list_envelope( $rows, $clusters, $limit ), 200 );
		}

		$query = array(
			'tenant_id' => $tenant_id,
			'limit'     => $limit,
			'offset'    => $offset,
		);

		if ( $labeled_only ) {
			$query['labeled_only'] = 'true';
		}

		if ( '' !== $search ) {
			$query['search'] = $search;
		}

		$response = $this->host->proxy_recognition_request( 'GET', '/recognition/clusters', array(), $query );
		$response = $this->dependencies->projection_sync_service->maybe_bootstrap_after_proxy_read( $tenant_id, $response );
		return $this->dependencies->response_envelope_service->normalize_cluster_list_response( $response, $limit );
	}

	public function list_top_unlabeled_clusters( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$tenant_id = $this->host->get_tenant_id();
		$limit     = absint( $request->get_param( 'limit' ) ?? self::LIST_TOP_UNLABELED_CLUSTERS_DEFAULT_LIMIT );
		$limit     = max( 1, min( $limit, self::LIST_TOP_UNLABELED_CLUSTERS_MAX_LIMIT ) );

		if ( ! $this->dependencies->projection_sync_service->should_use_local_projection( $tenant_id ) ) {
			$response = $this->host->proxy_recognition_request(
				'GET',
				'/recognition/clusters/top-unlabeled',
				array(),
				array(
					'tenant_id' => $tenant_id,
					'limit'     => $limit,
				)
			);
			$response = $this->dependencies->projection_sync_service->maybe_bootstrap_after_proxy_read( $tenant_id, $response );

			if ( $response instanceof WP_REST_Response && $response->get_status() >= 200 && $response->get_status() < 300 ) {
				$data = $response->get_data();
				if ( is_array( $data ) ) {
					if ( isset( $data['clusters'] ) && is_array( $data['clusters'] ) ) {
						if ( ! isset( $data['limit'], $data['total'], $data['truncated'] ) || ! is_numeric( $data['limit'] ) || ! is_numeric( $data['total'] ) || ! is_bool( $data['truncated'] ) ) {
							return new WP_Error(
								'invalid_top_unlabeled_envelope',
								'Top-unlabeled clusters response must include limit, total, and truncated when clusters is present.',
								array( 'status' => 502 )
							);
						}

						return new WP_REST_Response(
							array(
								'clusters' => $data['clusters'],
								'limit' => max( 1, (int) $data['limit'] ),
								'total' => max( 0, (int) $data['total'] ),
								'truncated' => $data['truncated'],
								'data_source' => $this->dependencies->config->data_source_backend_proxy,
							),
							200
						);
					}

					return new WP_REST_Response(
						array(
							'clusters' => $data,
							'limit' => $limit,
							'total' => count( $data ),
							'truncated' => false,
							'data_source' => $this->dependencies->config->data_source_backend_proxy,
						),
						200
					);
				}
			}

			$args = array( $tenant_id );
			if ( false === wp_next_scheduled( $this->dependencies->config->bootstrap_sync_hook, $args ) ) {
				wp_schedule_single_event( time(), $this->dependencies->config->bootstrap_sync_hook, $args );
			}
			return new WP_REST_Response(
				array(
					'clusters'          => array(),
					'limit' => $limit,
					'total' => 0,
					'truncated' => false,
					'singleton_count'   => 0,
					'data_source'       => $this->dependencies->config->data_source_unavailable,
					'projection_status' => $this->dependencies->config->projection_status_bootstrapping,
				),
				200
			);
		}

		$sovereign_data = $this->dependencies->cluster_facade->list_top_unlabeled( $tenant_id, $limit );
		$cluster_ids_to_repair = $this->dependencies->projection_sync_service->find_clusters_missing_projected_members(
			$sovereign_data['clusters'],
			$sovereign_data['members']
		);
		if ( ! empty( $cluster_ids_to_repair ) && $this->dependencies->projection_sync_service->repair_targeted_projection( $tenant_id, $cluster_ids_to_repair ) ) {
			$sovereign_data = $this->dependencies->cluster_facade->list_top_unlabeled( $tenant_id, $limit );
		}

		$has_clusters = $this->dependencies->clusters_repository->has_projection_rows_for_tenant( $tenant_id );
		$unlabeled_items = $this->dependencies->cluster_mapper->map_top_unlabeled_clusters(
			$sovereign_data['clusters'],
			$sovereign_data['members'],
			$tenant_id
		);
		$total = count( $unlabeled_items );
		if ( isset( $sovereign_data['clusters'][0]['total_count'] ) && is_numeric( $sovereign_data['clusters'][0]['total_count'] ) ) {
			$total = max( 0, (int) $sovereign_data['clusters'][0]['total_count'] );
		}

		return new WP_REST_Response(
			array(
				'clusters' => $unlabeled_items,
				'limit' => $limit,
				'total' => $total,
				'truncated' => $total > count( $unlabeled_items ),
				'singleton_count' => max( 0, (int) ( $sovereign_data['singleton_count'] ?? 0 ) ),
				'has_clusters' => $has_clusters,
				'data_source' => $this->dependencies->config->data_source_local_projection,
				'projection_status' => $this->dependencies->config->projection_status_available,
			),
			200
		);
	}

	public function list_cluster_labels( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$tenant_id = $this->host->get_tenant_id();
		$limit = absint( $request->get_param( 'limit' ) ?? self::LIST_CLUSTER_LABELS_DEFAULT_LIMIT );
		$limit = max( 1, min( $limit, self::LIST_CLUSTER_LABELS_MAX_LIMIT ) );
		$search = sanitize_text_field( (string) $request->get_param( 'search' ) );

		if ( $this->dependencies->projection_sync_service->should_use_local_projection( $tenant_id ) ) {
			$label_rows = $this->dependencies->clusters_repository->list_labels( $tenant_id, $search, $limit );
			$labels = $this->dependencies->cluster_mapper->map_labels_list( array_map( static fn ( array $row ): string => (string) ( $row['label'] ?? '' ), $label_rows ) );
			$total = count( $labels );
			if ( isset( $label_rows[0]['total_count'] ) && is_numeric( $label_rows[0]['total_count'] ) ) {
				$total = max( 0, (int) $label_rows[0]['total_count'] );
			}
			return new WP_REST_Response( $this->dependencies->response_envelope_service->build_cluster_labels_envelope( $labels, $limit, $total ), 200 );
		}

		$query = array(
			'tenant_id' => $tenant_id,
			'limit' => $limit,
		);

		if ( '' !== $search ) {
			$query['search'] = $search;
		}

		$response = $this->host->proxy_recognition_request( 'GET', '/recognition/clusters/labels', array(), $query );
		$response = $this->dependencies->projection_sync_service->maybe_bootstrap_after_proxy_read( $tenant_id, $response );
		return $this->dependencies->response_envelope_service->normalize_cluster_labels_response( $response, $limit );
	}

	public function get_cluster_detail( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$tenant_id = $this->host->get_tenant_id();
		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( $this->dependencies->projection_sync_service->should_use_local_projection( $tenant_id ) ) {
			$cluster_row = $this->dependencies->clusters_repository->find_by_uuid( $cluster_id );
			if ( is_array( $cluster_row ) ) {
				$members = $this->dependencies->members_repository->list_for_cluster( $cluster_id, 500, 0, $tenant_id );
				$payload = $this->dependencies->cluster_mapper->map_cluster_detail( $cluster_row, $members );
				return new WP_REST_Response( $payload, 200 );
			}

			return new WP_Error(
				'cluster_not_found',
				sprintf( 'Cluster %s not found.', $cluster_id ),
				array( 'status' => 404 )
			);
		}

		$response = $this->host->proxy_recognition_request(
			'GET',
			sprintf( '/recognition/clusters/%s', $cluster_id ),
			array(),
			array( 'tenant_id' => $tenant_id )
		);
		return $this->dependencies->projection_sync_service->maybe_bootstrap_after_proxy_read( $tenant_id, $response );
	}

	public function get_cluster_members( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$tenant_id = $this->host->get_tenant_id();
		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		$limit  = $this->resolve_cluster_members_limit( $request );
		$offset = absint( $request->get_param( 'offset' ) ?? 0 );

		if ( $this->dependencies->projection_sync_service->should_use_local_projection( $tenant_id ) ) {
			$cluster_row = $this->dependencies->clusters_repository->find_by_uuid( $cluster_id );
			if ( ! is_array( $cluster_row ) ) {
				return new WP_Error(
					'cluster_not_found',
					sprintf( 'Cluster %s not found.', $cluster_id ),
					array( 'status' => 404 )
				);
			}

			$member_rows = $this->dependencies->members_repository->list_for_cluster( $cluster_id, $limit, $offset, $tenant_id );
			if ( empty( $member_rows ) && 0 === $offset && $this->dependencies->projection_sync_service->cluster_row_should_have_members( $cluster_row ) && $this->dependencies->projection_sync_service->repair_targeted_projection( $tenant_id, array( $cluster_id ) ) ) {
				$member_rows = $this->dependencies->members_repository->list_for_cluster( $cluster_id, $limit, $offset, $tenant_id );
			}

			$members = $this->dependencies->member_mapper->map_cluster_members( $member_rows );
			if ( isset( $member_rows[0]['total_count'] ) && is_numeric( $member_rows[0]['total_count'] ) ) {
				$total = max( 0, (int) $member_rows[0]['total_count'] );
			} else {
				$total = $this->dependencies->members_repository->count_for_cluster( $cluster_id );
			}
			return new WP_REST_Response( $this->dependencies->response_envelope_service->build_cluster_members_envelope( $members, $limit, $total, $offset ), 200 );
		}

		$response = $this->host->proxy_recognition_request(
			'GET',
			sprintf( '/recognition/clusters/%s/members', $cluster_id ),
			array(),
			array(
				'tenant_id' => $tenant_id,
				'limit'     => $limit,
				'offset'    => $offset,
			)
		);
		$response = $this->dependencies->projection_sync_service->maybe_bootstrap_after_proxy_read( $tenant_id, $response );
		return $this->dependencies->response_envelope_service->normalize_cluster_members_response( $response, $limit, $offset );
	}

	/**
	 * Resolve members page size: default max, min 1, capped at GET_CLUSTER_MEMBERS_MAX_LIMIT.
	 */
	private function resolve_cluster_members_limit( WP_REST_Request $request ): int {
		$raw = $request->get_param( 'limit' );
		if ( null === $raw || '' === $raw ) {
			return self::GET_CLUSTER_MEMBERS_MAX_LIMIT;
		}

		return max( 1, min( absint( $raw ), self::GET_CLUSTER_MEMBERS_MAX_LIMIT ) );
	}

	/**
	 * @param array<int,array<string,mixed>> $cluster_rows
	 * @return array<string,array<int,array<string,mixed>>>
	 */
	private function load_members_by_cluster( array $cluster_rows, int $limit ): array {
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

		return $this->dependencies->members_repository->list_for_cluster_uuids( $cluster_uuids, $limit );
	}
}
