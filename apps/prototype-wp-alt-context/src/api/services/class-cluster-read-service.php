<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

require_once __DIR__ . '/../../sovereign/class-projection-query-exception.php';

use AltContext\Api\ClustersHostInterface;
use AltContext\Sovereign\ProjectionQueryException;
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
	/**
	 * Per-cluster sample size for list / top-unlabeled cards. Canonical value
	 * lives on the repository interface (PREVIEW_IDENTITIES_PER_CLUSTER); do not
	 * re-state the magnitude — facade fetch and mapper both consume that const
	 * (sr-007, E21-14-R3-COORDINATOR-02).
	 */
	private const PREVIEW_IDENTITIES_PER_CLUSTER = IdentityMembersRepositoryInterface::PREVIEW_IDENTITIES_PER_CLUSTER;
	/**
	 * Cluster detail member page size. Canonical value lives on the repository
	 * interface (DEFAULT_CLUSTER_MEMBER_LIMIT); do not re-state the magnitude.
	 */
	private const CLUSTER_DETAIL_MEMBER_LIMIT = IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT;

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
			try {
				$rows = $this->dependencies->clusters_repository->list_for_tenant(
					$tenant_id,
					$limit,
					$offset,
					array(
						'search' => $search,
						'labeled_only' => $labeled_only,
					)
				);

				$preview_limit      = self::PREVIEW_IDENTITIES_PER_CLUSTER;
				$members_by_cluster = $this->load_members_by_cluster( $rows, $preview_limit );
				$clusters           = $this->dependencies->cluster_mapper->map_cluster_list( $rows, $members_by_cluster, $preview_limit );

				return new WP_REST_Response( $this->dependencies->response_envelope_service->build_cluster_list_envelope( $rows, $clusters, $limit ), 200 );
			} catch ( ProjectionQueryException $exception ) {
				return $this->projection_query_failed_error( 'list_clusters', $exception );
			}
		}

		/*
		 * WHY: Remote recognition payloads have no person binding. person_uuid
		 * is intentionally absent (honest null per rg-015). Do not fabricate a
		 * fallback — FE renders Unresolved until the local projection path is used.
		 */
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
				$normalized = $this->dependencies->response_envelope_service->normalize_top_unlabeled_response( $response );
				if ( $normalized instanceof WP_Error ) {
					return $normalized;
				}

				// After the WP_Error branch, normalize_top_unlabeled_response yields WP_REST_Response.
				$data = $normalized->get_data();
				if ( is_array( $data ) ) {
					$data['data_source'] = $this->dependencies->config->data_source_backend_proxy;
					return new WP_REST_Response( $data, 200 );
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

		try {
			// Query errors throw before empty-member repair — repair only heals
			// true projection gaps, not MySQL 1054 / read failures (RLSE-05).
			$sovereign_data = $this->dependencies->cluster_facade->list_top_unlabeled( $tenant_id, $limit );
			$cluster_ids_to_repair = $this->dependencies->projection_sync_service->find_clusters_missing_projected_members(
				$sovereign_data['clusters'],
				$sovereign_data['members']
			);
			if ( ! empty( $cluster_ids_to_repair ) && $this->dependencies->projection_sync_service->repair_targeted_projection( $tenant_id, $cluster_ids_to_repair ) ) {
				$sovereign_data = $this->dependencies->cluster_facade->list_top_unlabeled( $tenant_id, $limit );
			}

			$has_clusters     = $this->dependencies->clusters_repository->has_projection_rows_for_tenant( $tenant_id );
			$preview_limit    = self::PREVIEW_IDENTITIES_PER_CLUSTER;
			$unlabeled_items  = $this->dependencies->cluster_mapper->map_top_unlabeled_clusters(
				$sovereign_data['clusters'],
				$sovereign_data['members'],
				$tenant_id,
				$preview_limit
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
		} catch ( ProjectionQueryException $exception ) {
			return $this->projection_query_failed_error( 'list_top_unlabeled_clusters', $exception );
		}
	}

	public function list_cluster_labels( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$tenant_id = $this->host->get_tenant_id();
		$limit = absint( $request->get_param( 'limit' ) ?? self::LIST_CLUSTER_LABELS_DEFAULT_LIMIT );
		$limit = max( 1, min( $limit, self::LIST_CLUSTER_LABELS_MAX_LIMIT ) );
		$search = sanitize_text_field( (string) $request->get_param( 'search' ) );

		if ( $this->dependencies->projection_sync_service->should_use_local_projection( $tenant_id ) ) {
			try {
				$label_rows = $this->dependencies->clusters_repository->list_labels( $tenant_id, $search, $limit );
				$labels = $this->dependencies->cluster_mapper->map_labels_list( array_map( static fn ( array $row ): string => (string) ( $row['label'] ?? '' ), $label_rows ) );
				$total = count( $labels );
				if ( isset( $label_rows[0]['total_count'] ) && is_numeric( $label_rows[0]['total_count'] ) ) {
					$total = max( 0, (int) $label_rows[0]['total_count'] );
				}
				return new WP_REST_Response( $this->dependencies->response_envelope_service->build_cluster_labels_envelope( $labels, $limit, $total ), 200 );
			} catch ( ProjectionQueryException $exception ) {
				return $this->projection_query_failed_error( 'list_cluster_labels', $exception );
			}
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
			try {
				$cluster_row = $this->dependencies->clusters_repository->find_by_uuid( $cluster_id );
				if ( is_array( $cluster_row ) ) {
					$member_limit = self::CLUSTER_DETAIL_MEMBER_LIMIT;
					$members      = $this->dependencies->members_repository->list_for_cluster( $cluster_id, $member_limit, 0, $tenant_id );
					$payload      = $this->dependencies->cluster_mapper->map_cluster_detail( $cluster_row, $members, $member_limit );
					return new WP_REST_Response( $payload, 200 );
				}

				return new WP_Error(
					'cluster_not_found',
					sprintf( 'Cluster %s not found.', $cluster_id ),
					array( 'status' => 404 )
				);
			} catch ( ProjectionQueryException $exception ) {
				return $this->projection_query_failed_error( 'get_cluster_detail', $exception );
			}
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

		$limit = $this->resolve_cluster_members_limit( $request );
		if ( $limit instanceof WP_Error ) {
			return $limit;
		}

		$offset = $this->resolve_cluster_members_offset( $request );
		if ( $offset instanceof WP_Error ) {
			return $offset;
		}

		if ( $this->dependencies->projection_sync_service->should_use_local_projection( $tenant_id ) ) {
			try {
				$cluster_row = $this->dependencies->clusters_repository->find_by_uuid( $cluster_id );
				if ( ! is_array( $cluster_row ) ) {
					return new WP_Error(
						'cluster_not_found',
						sprintf( 'Cluster %s not found.', $cluster_id ),
						array( 'status' => 404 )
					);
				}

				// Empty-member repair must not run when the read itself failed —
				// ProjectionQueryException exits before this branch (RLSE-05).
				$member_rows = $this->dependencies->members_repository->list_for_cluster( $cluster_id, $limit, $offset, $tenant_id );
				if ( empty( $member_rows ) && 0 === $offset && $this->dependencies->projection_sync_service->cluster_row_should_have_members( $cluster_row ) && $this->dependencies->projection_sync_service->repair_targeted_projection( $tenant_id, array( $cluster_id ) ) ) {
					$member_rows = $this->dependencies->members_repository->list_for_cluster( $cluster_id, $limit, $offset, $tenant_id );
				}

				$members = $this->dependencies->member_mapper->map_cluster_members( $member_rows );
				if ( isset( $member_rows[0]['total_count'] ) && is_numeric( $member_rows[0]['total_count'] ) ) {
					$total = max( 0, (int) $member_rows[0]['total_count'] );
				} else {
					$total = $this->dependencies->members_repository->count_for_cluster( $cluster_id, $tenant_id );
				}
				return new WP_REST_Response( $this->dependencies->response_envelope_service->build_cluster_members_envelope( $members, $limit, $total, $offset ), 200 );
			} catch ( ProjectionQueryException $exception ) {
				return $this->projection_query_failed_error( 'get_cluster_members', $exception );
			}
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
		return $this->dependencies->response_envelope_service->normalize_cluster_members_response( $response );
	}

	/**
	 * Resolve members page size: default max; reject-not-clamp on out-of-range
	 * values (400), matching recognition's validate_paging policy so both legs
	 * of the boundary behave identically.
	 */
	private function resolve_cluster_members_limit( WP_REST_Request $request ): int|WP_Error {
		$raw = $request->get_param( 'limit' );
		if ( null === $raw || '' === $raw ) {
			return self::GET_CLUSTER_MEMBERS_MAX_LIMIT;
		}

		if ( ! is_numeric( $raw ) || (int) $raw < 1 || (int) $raw > self::GET_CLUSTER_MEMBERS_MAX_LIMIT ) {
			return new WP_Error( 'invalid_limit', 'limit out of range', array( 'status' => 400 ) );
		}

		return absint( $raw );
	}

	/**
	 * Resolve members page offset: default 0; reject-not-clamp on negative
	 * values (400), matching recognition's validate_paging policy.
	 */
	private function resolve_cluster_members_offset( WP_REST_Request $request ): int|WP_Error {
		$raw = $request->get_param( 'offset' );
		if ( null === $raw || '' === $raw ) {
			return 0;
		}

		if ( ! is_numeric( $raw ) || (int) $raw < 0 ) {
			return new WP_Error( 'invalid_offset', 'offset must be non-negative', array( 'status' => 400 ) );
		}

		return absint( $raw );
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

	/**
	 * Convert a sovereign projection SQL failure into a typed REST error.
	 *
	 * Must not collapse into an empty 200 list (RLSE-05 / OBS-08).
	 */
	private function projection_query_failed_error( string $surface, ProjectionQueryException $exception ): WP_Error {
		return ProjectionQueryException::to_rest_error( $surface );
	}
}
